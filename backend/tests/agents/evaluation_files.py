"""Actual file assertions and multi-turn release gate contracts."""

import hashlib
from dataclasses import replace
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import tests.support  # noqa: F401
from openpyxl import Workbook

from app.domain.agents.evaluation import AgentEvaluationSuite
from app.domain.agents.evaluation_files import (
    EvaluationFileExpectation,
    EvaluationFileObservation,
    evaluate_files,
)
from scripts.agent_eval import _report, execute_case
from scripts.agent_eval_files import delivered_files, inspect_deliverable


def check_files():
    workbook = Workbook()
    workbook.active.title = "Data"
    workbook.active.append(["产品", "数量"])
    workbook.active.append(["甲", 12])
    data = BytesIO()
    workbook.save(data)
    expected = EvaluationFileExpectation.from_dict({"path": "data.xlsx", "cells": {"Data!B2": 12}, "text_contains": ["产品", "甲"]})
    observed = inspect_deliverable(expected, str(uuid4()), data.getvalue(), inspection_passed=True)
    assert not evaluate_files([expected], [observed])
    assert evaluate_files([replace(expected, cells={"Data!B2": 13})], [observed]) == ["file:1:cell:1"]
    assert evaluate_files([replace(expected, cells={"Data!B2": False})], [replace(observed, cells={"Data!B2": 0})]) == ["file:1:cell:1"]
    for path, address in (("../bad.xlsx", "Data!B2"), ("data.xlsx", "Data!ZZZ1"), ("data.xlsx", "Data!A1048577")):
        try:
            EvaluationFileExpectation.from_dict({"path": path, "cells": {address: 12}})
        except ValueError:
            pass
        else:
            raise AssertionError("Unsafe path or cell accepted.")
    doc = BytesIO()
    with ZipFile(doc, "w") as archive:
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>中文</w:t></w:r><w:r><w:t>报告</w:t></w:r></w:p></w:body></w:document>')
    expected = EvaluationFileExpectation.from_dict({"path": "report.docx", "text_contains": ["中文报告"]})
    assert not evaluate_files([expected], [inspect_deliverable(expected, str(uuid4()), doc.getvalue(), inspection_passed=True)])
    assert evaluate_files([expected], [EvaluationFileObservation(path=expected.path, error=True)]) == ["file:1:unreadable"]
    assert evaluate_files([expected], []) == ["file:1:missing"]


class DeliveryClient:
    def __init__(self, *, corrupt_old=False):
        self.calls = []
        self.files = {}
        self.corrupt_old = corrupt_old

    def request(self, method, path, payload=None):
        assert method == "POST" and path.endswith("/runs")
        self.calls.append(payload)
        run_id, artifact_id = str(uuid4()), str(uuid4())
        number = len(self.calls)
        self.files[artifact_id] = (run_id, f"private file content {number}".encode())
        return {
            "id": run_id, "status": "succeeded", "result": "done",
            "model_usage": {"model_calls": 1, "reported_model_calls": 1, "total_tokens": 12},
            "execution_manifest": {"schema_version": 1, "model": {"fingerprint": "fixed"}},
            "events": [{"type": "tool", "status": "succeeded", "output": {"artifacts": [{"artifact_id": artifact_id, "relative_path": "result.txt"}]}}],
        }

    def download_artifact(self, artifact_id, *, run_id):
        source_run, content = self.files[artifact_id]
        assert source_run == run_id
        if self.corrupt_old and len(self.files) == 3 and artifact_id == next(iter(self.files)):
            content = b"changed after delivery"
        return content, True


def check_multiturn():
    suite = AgentEvaluationSuite.from_dict({"cases": [{
        "id": "three-turn-edit", "goal": "private user goal",
        "expect": {"files": [{"path": "result.txt", "text_contains": ["content 1"]}]},
        "follow_ups": [
            {"goal": "edit", "expect": {"files": [{"path": "result.txt", "text_contains": ["content 2"], "changed": True}]}},
            {"goal": "edit again", "expect": {"files": [{"path": "result.txt", "text_contains": ["content 3"], "changed": True}]}},
        ],
    }]})
    client = DeliveryClient()
    result = execute_case(client, suite.cases[0], workspace_id="ws", agent_id="agent", sample=1, poll_seconds=0.01, timeout_seconds=10)
    assert result.passed, result.failures
    assert len(result.turns) == 3
    assert len({call["conversation_id"] for call in client.calls}) == 1
    assert len({call["request_id"] for call in client.calls}) == 3
    assert len({file["sha256"] for turn in result.turns for file in turn["files"]}) == 3
    passed, report = _report(suite, [result])
    assert passed and report["schema_version"] == 2
    assert "private user goal" not in str(report) and "private file content" not in str(report)
    bad = execute_case(DeliveryClient(corrupt_old=True), suite.cases[0], workspace_id="ws", agent_id="agent", sample=1, poll_seconds=0.01, timeout_seconds=10)
    assert not bad.passed and "previous_file:1:changed" in bad.failures
    artifact_id = str(uuid4())
    assert not delivered_files([{"type": "tool", "status": "failed", "output": {"artifact_id": artifact_id, "filename": "bad.txt"}}])
    assert hashlib.sha256(b"private file content 1").hexdigest() == result.turns[0]["files"][0]["sha256"]


def main():
    check_files()
    check_multiturn()
    print("AGENT_FILE_EVALUATION_OK")


if __name__ == "__main__":
    main()
