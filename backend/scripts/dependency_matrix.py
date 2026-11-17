"""Inspect backend imports and enforce the modular monolith's dependencies.

Usage:
    python scripts/dependency_matrix.py
    python scripts/dependency_matrix.py --check
    python scripts/dependency_matrix.py --json out.json
"""

from __future__ import annotations

import argparse
import ast
import json
from importlib.util import resolve_name
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
LAYERS = {
    name: name
    for name in (
        "api",
        "application",
        "domain",
        "entities",
        "schemas",
        "ports",
        "adapters",
        "infra",
        "tasks",
        "bootstrap",
    )
}
EXTERNAL = {
    name: name
    for name in (
        "fastapi",
        "sqlalchemy",
        "celery",
        "redis",
        "qdrant_client",
        "mcp",
        "pydantic",
    )
}
LAYER_RULES = {
    ("api", "tasks"): "HTTP handlers must dispatch through application use cases",
    ("api", "adapters"): "HTTP handlers must not import concrete adapters",
    ("api", "bootstrap"): "HTTP handlers must not import composition roots",
    ("application", "api"): "application must not import HTTP handlers",
    ("application", "tasks"): "application must not import tasks",
    ("application", "adapters"): "application must not import concrete adapters",
    ("application", "bootstrap"): "application must not import composition roots",
    ("ports", "adapters"): "ports may only compose adapters inside factories",
    ("ports", "infra"): "ports must not import infrastructure",
    ("ports", "application"): "ports must not import application",
    ("ports", "domain"): "ports must not import domain",
    ("ports", "api"): "ports must not import HTTP handlers",
    ("ports", "tasks"): "ports must not import task entry points",
    (
        "ports",
        "bootstrap",
    ): "ports may only compose the run dispatcher inside its delegate",
    ("adapters", "application"): "adapters must not import application",
    ("adapters", "domain"): "adapters must not import domain",
    ("adapters", "schemas"): "adapters must not import schemas",
    ("adapters", "api"): "adapters must not import HTTP handlers",
    ("adapters", "tasks"): "adapters must not import task entry points",
    ("adapters", "bootstrap"): "adapters must not import composition roots",
    ("infra", "api"): "infrastructure must not import HTTP handlers",
    ("infra", "application"): "infrastructure must not import application",
    ("infra", "tasks"): "infrastructure must not import task entry points",
    ("infra", "bootstrap"): "infrastructure must not import composition roots",
    ("domain", "adapters"): "domain must not import concrete adapters",
    ("domain", "application"): "domain must not import application",
    ("domain", "api"): "domain must not import HTTP handlers",
    ("domain", "tasks"): "domain must not import tasks",
    ("domain", "bootstrap"): "domain must not import composition roots",
}
# These existing model catalog use cases are documented composition points.
LAYER_EXCEPTIONS = {
    ("app.application.models.registry", "app.adapters.llm.credentials"),
    ("app.application.models.registry", "app.adapters.llm.providers"),
    ("app.application.models.service", "app.adapters.llm.credentials"),
    ("app.application.models.service", "app.adapters.llm.providers"),
}


def layer_of(module: str) -> str | None:
    parts = module.split(".")
    return LAYERS.get(parts[1]) if len(parts) > 1 and parts[0] == "app" else None


def feature_of(module: str, *, layer: str = "application") -> str | None:
    parts = module.split(".")
    return parts[2] if len(parts) > 2 and parts[:2] == ["app", layer] else None


def _is_type_checking_guard(node: ast.If) -> bool:
    test = node.test
    return (
        isinstance(test, ast.Name)
        and test.id == "TYPE_CHECKING"
        or isinstance(test, ast.Attribute)
        and test.attr == "TYPE_CHECKING"
        and isinstance(test.value, ast.Name)
        and test.value.id == "typing"
    )


def iter_modules() -> list[tuple[Path, str]]:
    modules = []
    for path in sorted(APP.rglob("*.py")):
        parts = path.relative_to(APP.parent).with_suffix("").parts
        module = ".".join(parts).removesuffix(".__init__")
        modules.append((path, module))
    return modules


class ImportCollector(ast.NodeVisitor):
    def __init__(self, module: str, package: str, modules: set[str]):
        self.module = module
        self.package = package
        self.modules = modules
        self.imports: list[dict] = []
        self.deferred = False
        self.bindings: dict[str, str] = {}

    def record(self, target: str, names: list[str], line: int) -> None:
        root = target.split(".")[0]
        if root == "app" or root in EXTERNAL:
            self.imports.append(
                {
                    "source": self.module,
                    "target": target if root == "app" else root,
                    "names": names,
                    "line": line,
                    "deferred": self.deferred,
                }
            )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.record(alias.name, [], node.lineno)
            self.bindings[alias.asname or alias.name.split(".")[0]] = (
                alias.name if alias.asname else alias.name.split(".")[0]
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        target = node.module or ""
        if node.level:
            target = resolve_name("." * node.level + target, self.package)
        for alias in node.names:
            submodule = f"{target}.{alias.name}"
            if submodule in self.modules:
                self.record(submodule, [], node.lineno)
                self.bindings[alias.asname or alias.name] = submodule
            else:
                self.record(target, [alias.name], node.lineno)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        parts = []
        value = node
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name) and value.id in self.bindings:
            qualified = self.bindings[value.id].split(".") + list(reversed(parts))
            if ".".join(qualified) in self.modules:
                return
            for length in range(len(qualified) - 1, 0, -1):
                target = ".".join(qualified[:length])
                if target in self.modules:
                    self.record(target, [qualified[length]], node.lineno)
                    return
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking_guard(node):
            for item in node.orelse:
                self.visit(item)
        else:
            self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        previous = self.deferred
        self.deferred = True
        self.generic_visit(node)
        self.deferred = previous

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        # Literal dynamic imports must not bypass dependency checks.
        function = node.func
        dynamic = (
            isinstance(function, ast.Name)
            and function.id in {"import_module", "__import__"}
            or isinstance(function, ast.Attribute)
            and function.attr == "import_module"
        )
        if dynamic and node.args and isinstance(node.args[0], ast.Constant):
            target = node.args[0].value
            if isinstance(target, str):
                if target.startswith("."):
                    target = resolve_name(target, self.package)
                self.record(target, [], node.lineno)
        self.generic_visit(node)


def analyze() -> dict:
    """Return full import targets, including deferred and relative imports.

    Parse errors deliberately propagate: a broken file must never silently
    disappear from an architecture check. Type-only imports are not runtime edges.
    """
    modules = iter_modules()
    known_modules = {module for _, module in modules}
    imports = []
    exports = {}
    for path, module in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        collector = ImportCollector(module, package, known_modules)
        collector.visit(tree)
        imports.extend(collector.imports)
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            ):
                exports[module] = list(ast.literal_eval(node.value))
    return {
        "edges": sorted({(item["source"], item["target"]) for item in imports}),
        "imports": imports,
        "exports": exports,
        "modules": sorted(known_modules),
    }


def _composition_import(item: dict) -> bool:
    if not item["deferred"]:
        return False
    source, target = item["source"], item["target"]
    return (
        layer_of(source) == "ports"
        and layer_of(target) == "adapters"
        or source == "app.ports.runs"
        and target == "app.bootstrap.runs"
    )


def summarize(data: dict) -> dict:
    counts: dict[tuple[str, str], int] = {}
    forbidden = set()
    for source, target in data["edges"]:
        key = (layer_of(source), layer_of(target) or target)
        if key[0] is not None and key[1] is not None:
            counts[key] = counts.get(key, 0) + 1
    for item in data["imports"]:
        source, target = item["source"], item["target"]
        key = (layer_of(source), layer_of(target) or target)
        if key[0] == "entities":
            if (
                target.startswith("app.") and key[1] != "entities"
            ) or target in EXTERNAL:
                forbidden.add(
                    (
                        "entities must be independent of frameworks and other layers",
                        source,
                        target,
                    )
                )
        if (
            key in LAYER_RULES
            and (source, target) not in LAYER_EXCEPTIONS
            and not _composition_import(item)
        ):
            forbidden.add((LAYER_RULES[key], source, target))
    return {
        "layer_edges": {f"{a}->{b}": n for (a, b), n in sorted(counts.items())},
        "forbidden": sorted(forbidden),
    }


def find_cycles(edges: list[tuple[str, str]]) -> list[list[str]]:
    """Return strongly connected groups; any multi-module group is a cycle."""
    graph: dict[str, set[str]] = {}
    for source, target in edges:
        graph.setdefault(source, set()).add(target)
        graph.setdefault(target, set())
    index = {}
    low = {}
    stack = []
    active = set()
    cycles = []

    def visit(node):
        index[node] = low[node] = len(index)
        stack.append(node)
        active.add(node)
        for target in sorted(graph[node]):
            if target not in index:
                visit(target)
                low[node] = min(low[node], low[target])
            elif target in active:
                low[node] = min(low[node], index[target])
        if low[node] == index[node]:
            group = []
            while True:
                member = stack.pop()
                active.remove(member)
                group.append(member)
                if member == node:
                    break
            if len(group) > 1 or node in graph[node]:
                cycles.append(sorted(group))

    for node in sorted(graph):
        if node not in index:
            visit(node)
    return sorted(cycles)


def module_dependencies(
    data: dict, *, layer: str = "application"
) -> list[tuple[str, str]]:
    return sorted(
        {
            (feature_of(source, layer=layer), feature_of(target, layer=layer))
            for source, target in data["edges"]
            if feature_of(source, layer=layer)
            and feature_of(target, layer=layer)
            and feature_of(source, layer=layer) != feature_of(target, layer=layer)
        }
    )


def module_violations(data: dict, interfaces: dict, dependencies: dict) -> list[str]:
    violations = set()
    for item in data["imports"]:
        source, target = item["source"], item["target"]
        caller, owner = feature_of(source), feature_of(target)
        if (
            not owner
            or caller == owner
            or layer_of(source) not in {"api", "application"}
        ):
            continue
        location = f"{source}:{item['line']} -> {target}"
        if target not in interfaces.get(owner, set()):
            violations.add(f"[private module implementation] {location}")
        else:
            exports = data["exports"].get(target, [])
            for name in item["names"]:
                if name == "*" or name.startswith("_") or name not in exports:
                    violations.add(f"[name is not in public __all__] {location}.{name}")
        if caller and owner not in dependencies.get(caller, set()):
            violations.add(f"[undeclared module dependency] {location}")
    for cycle in find_cycles(module_dependencies(data)):
        violations.add(f"[application module cycle] {', '.join(cycle)}")
    for cycle in find_cycles(module_dependencies(data, layer="domain")):
        violations.add(f"[domain module cycle] {', '.join(cycle)}")
    return sorted(violations)


def module_contracts() -> tuple[dict, dict]:
    if __package__:
        from .module_boundaries import MODULE_DEPENDENCIES, PUBLIC_INTERFACES
    else:
        from module_boundaries import MODULE_DEPENDENCIES, PUBLIC_INTERFACES
    return PUBLIC_INTERFACES, MODULE_DEPENDENCIES


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", help="write JSON matrix to path")
    parser.add_argument(
        "--check", action="store_true", help="fail on forbidden dependencies"
    )
    args = parser.parse_args()
    data = analyze()
    summary = summarize(data)
    interfaces, dependencies = module_contracts()
    violations = module_violations(data, interfaces, dependencies)
    payload = {
        **data,
        **summary,
        "module_edges": module_dependencies(data),
        "module_cycles": find_cycles(module_dependencies(data)),
        "domain_edges": module_dependencies(data, layer="domain"),
        "domain_cycles": find_cycles(module_dependencies(data, layer="domain")),
        "module_violations": violations,
    }
    if args.json:
        Path(args.json).write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(f"wrote {args.json}")
    else:
        for key, count in summary["layer_edges"].items():
            print(f"{key}: {count}")
        for rule, source, target in summary["forbidden"]:
            print(f"[{rule}] {source} -> {target}")
        for violation in violations:
            print(violation)
        print(
            f"Application modules: {len(interfaces)}; cycles: {len(payload['module_cycles'])}"
        )
        print(f"Domain module cycles: {len(payload['domain_cycles'])}")
    return int(args.check and bool(summary["forbidden"] or violations))


if __name__ == "__main__":
    raise SystemExit(main())
