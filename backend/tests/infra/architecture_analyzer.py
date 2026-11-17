"""Regression checks for the import analyzer, using isolated source trees."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import dependency_matrix as matrix


class DependencyAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = Path(self.directory.name) / "app"

    def source(self, name: str, content: str = "") -> None:
        path = self.app / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def analyze(self):
        with patch.multiple(matrix, APP=self.app, BACKEND=self.app.parent):
            return matrix.analyze()

    def test_full_targets_relative_imports_and_lazy_imports(self):
        self.source("application/agents/__init__.py")
        self.source(
            "application/agents/service.py",
            """
from app.application.knowledge.retrieval.service import retrieve_knowledge_base
from . import helpers
from app.application import workflows
import app.adapters.llm.runtime as provider
def execute():
    from app.application.workflows.runs.service import create_workflow_run
""",
        )
        self.source("application/agents/helpers.py")
        self.source("application/workflows/__init__.py")
        edges = set(map(tuple, self.analyze()["edges"]))
        source = "app.application.agents.service"
        for target in (
            "app.application.knowledge.retrieval.service",
            "app.application.agents.helpers",
            "app.application.workflows",
            "app.adapters.llm.runtime",
            "app.application.workflows.runs.service",
        ):
            self.assertIn((source, target), edges)

    def test_type_only_imports_do_not_create_runtime_edges(self):
        self.source(
            "application/agents/service.py",
            """
from typing import TYPE_CHECKING
import typing
if TYPE_CHECKING:
    from app.application.workflows.runs.service import create_workflow_run
if typing.TYPE_CHECKING:
    from app.adapters.llm.runtime import ChatProvider
else:
    from app.entities.agents import Agent
""",
        )
        edges = set(map(tuple, self.analyze()["edges"]))
        self.assertEqual(
            edges, {("app.application.agents.service", "app.entities.agents")}
        )

    def test_forbidden_layer_edges_are_actually_reported(self):
        self.source(
            "domain/knowledge/service.py",
            """
def query():
    from app.application.agents import create_agent
    from app.adapters.rag.vector_store import query_vectors
""",
        )
        forbidden = matrix.summarize(self.analyze())["forbidden"]
        self.assertEqual(len(forbidden), 2)

    def test_composition_exceptions_are_scoped_and_deferred(self):
        self.source(
            "ports/runs.py",
            """
def enqueue():
    from app.bootstrap.runs import enqueue_agent_run
""",
        )
        self.source(
            "ports/other.py",
            """
def enqueue():
    from app.bootstrap.runs import enqueue_agent_run
""",
        )
        self.source("ports/llm.py", "from app.adapters.llm.runtime import ChatProvider")
        forbidden = matrix.summarize(self.analyze())["forbidden"]
        self.assertEqual(
            {item[1] for item in forbidden}, {"app.ports.other", "app.ports.llm"}
        )
        self.source("ports/runs.py", "from app.bootstrap.runs import enqueue_agent_run")
        forbidden = matrix.summarize(self.analyze())["forbidden"]
        self.assertIn("app.ports.runs", {item[1] for item in forbidden})

    def test_syntax_errors_fail_the_check(self):
        self.source("application/agents/service.py", "def broken(:")
        with self.assertRaises(SyntaxError):
            self.analyze()

    def test_package_initializers_have_canonical_names(self):
        self.source(
            "application/agents/__init__.py",
            "from app.application.tools.runtime.service import execute_tool_invocation",
        )
        self.assertEqual(
            self.analyze()["edges"],
            [("app.application.agents", "app.application.tools.runtime.service")],
        )

    def test_cross_module_calls_use_only_the_declared_interface(self):
        self.source(
            "application/knowledge/retrieval/service.py", "__all__ = ['retrieve']"
        )
        self.source(
            "application/agents/service.py",
            """
from app.application.knowledge.retrieval import service as knowledge
def execute():
    knowledge.retrieve()
""",
        )
        interfaces = {"knowledge": {"app.application.knowledge.retrieval.service"}}
        dependencies = {"agents": {"knowledge"}}
        self.assertEqual(
            matrix.module_violations(self.analyze(), interfaces, dependencies), []
        )
        self.source(
            "application/agents/service.py",
            """
from app.application.knowledge.retrieval import service as knowledge
def execute():
    knowledge._query_candidates()
""",
        )
        violations = matrix.module_violations(self.analyze(), interfaces, dependencies)
        self.assertTrue(any("not in public __all__" in item for item in violations))

    def test_private_modules_and_undeclared_dependencies_are_rejected(self):
        self.source(
            "application/agents/service.py",
            """
def execute():
    from app.application.knowledge.retrieval.internal import query
""",
        )
        violations = matrix.module_violations(self.analyze(), {}, {})
        self.assertTrue(
            any("private module implementation" in item for item in violations)
        )
        self.assertTrue(
            any("undeclared module dependency" in item for item in violations)
        )

    def test_deferred_and_dynamic_imports_cannot_hide_a_cycle(self):
        self.source(
            "application/agents/service.py",
            """
def execute():
    from app.application.workflows.service import run
""",
        )
        self.source(
            "application/workflows/service.py",
            """
import importlib
def run():
    importlib.import_module('app.application.agents.service')
""",
        )
        self.assertEqual(
            matrix.find_cycles(matrix.module_dependencies(self.analyze())),
            [["agents", "workflows"]],
        )

    def test_wildcards_cannot_bypass_public_names(self):
        self.source("application/knowledge/service.py", "__all__ = ['retrieve']")
        self.source(
            "application/agents/service.py",
            "from app.application.knowledge.service import *",
        )
        violations = matrix.module_violations(
            self.analyze(),
            {"knowledge": {"app.application.knowledge.service"}},
            {"agents": {"knowledge"}},
        )
        self.assertTrue(any("not in public __all__" in item for item in violations))

    def test_domain_feature_cycles_are_rejected(self):
        self.source(
            "domain/agents/service.py",
            "from app.domain.workflows.service import defaults",
        )
        self.source(
            "domain/workflows/service.py",
            "from app.domain.agents.service import permissions",
        )
        violations = matrix.module_violations(self.analyze(), {}, {})
        self.assertTrue(any("domain module cycle" in item for item in violations))

    def test_qualified_imports_do_not_expose_intermediate_packages(self):
        self.source("application/knowledge/__init__.py")
        self.source("application/knowledge/retrieval/__init__.py")
        self.source(
            "application/knowledge/retrieval/service.py", "__all__ = ['retrieve']"
        )
        self.source(
            "application/agents/service.py",
            """
import app.application.knowledge.retrieval.service
def execute():
    app.application.knowledge.retrieval.service.retrieve()
""",
        )
        violations = matrix.module_violations(
            self.analyze(),
            {"knowledge": {"app.application.knowledge.retrieval.service"}},
            {"agents": {"knowledge"}},
        )
        self.assertEqual(violations, [])


def run_tests():
    result = unittest.TextTestRunner().run(
        unittest.defaultTestLoader.loadTestsFromTestCase(DependencyAnalyzerTests)
    )
    assert result.wasSuccessful(), "Dependency analyzer regression checks failed"


if __name__ == "__main__":
    run_tests()
