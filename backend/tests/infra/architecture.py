"""Architecture guard: layer dependency rules enforced over backend/app.

AST based (no test dependency on runtime imports): each module's
module-level imports are resolved to a layer; forbidden layer pairs are
asserted with a small allow-list for documented composition points.

Current scope (decoupling stage 7):
- application must not import tasks or concrete adapters (models hub is a
  documented provider composition point and is allow-listed).
- ports must not import adapters/infra/domain/application.
- adapters must not import application/domain.
- entities must not import infra/adapters.
- domain must not import adapters.
- tasks must not import application (tasks -> application is allowed the
  other way for worker entry points? no: tasks may import application,
  application must not import tasks).

Known debt (tracked in docs/local/2026-09-07-backend-dependency-decoupling-plan.md):
domain modules still import FastAPI/schemas/repositories and the
agents<->workflows application import graph is not yet single-direction;
those rules are intentionally not enforced here until stage 6 lands.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]

_LOADED = False
_matrix = None


def _analyzer() -> "module":
    global _matrix, _LOADED
    if not _LOADED:
        spec = importlib.util.spec_from_file_location(
            "dependency_matrix", BACKEND / "scripts" / "dependency_matrix.py"
        )
        _matrix = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(_matrix)
        _LOADED = True
    return _matrix


ALLOWLIST = {
    # models hub composes provider catalog/credentials (documented seam).
    ("application", "adapters"): {
        "app.application.models.registry",
        "app.application.models.service",
    },
}


def test_architecture_layer_rules() -> None:
    analyzer = _analyzer()
    data = analyzer.analyze()
    violations: list[str] = []
    rules = {
        ("application", "tasks"): "application must not import tasks",
        ("application", "adapters"): "application must not import concrete adapters",
        ("ports", "adapters"): "ports must not import adapters",
        ("ports", "infra"): "ports must not import infra",
        ("ports", "application"): "ports must not import application",
        ("ports", "domain"): "ports must not import domain",
        ("adapters", "application"): "adapters must not import application",
        ("adapters", "domain"): "adapters must not import domain",
        ("entities", "infra"): "entities must not import infra",
        ("entities", "adapters"): "entities must not import adapters",
        ("domain", "adapters"): "domain must not import concrete adapters",
    }
    for src, dst in data["edges"]:
        src_layer = analyzer.layer_of(src)
        if dst.startswith("app"):
            dst_layer = analyzer.layer_of(dst)
        else:
            dst_layer = dst
        if src_layer is None or dst_layer is None:
            continue
        key = (src_layer, dst_layer)
        rule = rules.get(key)
        if rule is None:
            continue
        allowed = ALLOWLIST.get(key, set())
        if src in allowed:
            continue
        violations.append(f"[{rule}] {src} -> {dst}")
    assert not violations, "\n".join(sorted(violations))


def test_entities_and_ports_are_import_free() -> None:
    analyzer = _analyzer()
    data = analyzer.analyze()
    # entities may only depend on entities/stdlib/external libs, never app layers
    for src, dst in data["edges"]:
        if analyzer.layer_of(src) != "entities":
            continue
        if dst.startswith("app"):
            assert analyzer.layer_of(dst) == "entities", (
                f"entities module {src} imports {dst}"
            )
        elif dst in {"fastapi", "sqlalchemy", "celery", "pydantic", "redis"}:
            raise AssertionError(f"entities module {src} imports framework {dst}")


def main() -> None:
    test_architecture_layer_rules()
    test_entities_and_ports_are_import_free()
    print("ARCHITECTURE_SUITE_OK")


if __name__ == "__main__":
    main()
