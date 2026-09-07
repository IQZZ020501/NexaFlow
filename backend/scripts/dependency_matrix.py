"""AST-based backend dependency matrix analyzer (stdlib only).

Scans backend/app for import edges between architecture layers and
module-level forbidden edges. Used by the decoupling effort to measure
progress per stage and as the engine for the architecture guard test.

Usage:
    python scripts/dependency_matrix.py            # human-readable summary
    python scripts/dependency_matrix.py --json out.json
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"

# Layer membership by top-level package inside app/
LAYERS = {
    "api": "api",
    "application": "application",
    "domain": "domain",
    "entities": "entities",
    "schemas": "schemas",
    "ports": "ports",
    "adapters": "adapters",
    "infra": "infra",
    "tasks": "tasks",
}

EXTERNAL = {
    "fastapi": "fastapi",
    "sqlalchemy": "sqlalchemy",
    "celery": "celery",
    "redis": "redis",
    "qdrant_client": "qdrant",
    "mcp": "mcp",
    "pydantic": "pydantic",
}


def layer_of(module: str) -> str | None:
    """app.<layer>... -> layer; app.<x> unknown -> None; non-app -> external name or None."""
    if not module.startswith("app."):
        return None
    parts = module.split(".")
    if len(parts) < 2:
        return None
    top = parts[1]
    if top in LAYERS:
        return LAYERS[top]
    return None


def is_orm_module(path: Path) -> bool:
    """Module whose primary job is SQLAlchemy model definitions."""
    text = path.read_text(errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    has_base_subclass = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if isinstance(base, ast.Name) and base.id == "Base":
                    has_base_subclass = True
                elif (
                    isinstance(base, ast.Attribute)
                    and base.attr == "Base"
                ):
                    has_base_subclass = True
    return has_base_subclass


def _is_type_checking_guard(node: ast.If) -> bool:
    """True for ``if TYPE_CHECKING:`` blocks (annotations only, no runtime edge)."""
    test = node.test
    return isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"


def iter_modules() -> list[tuple[Path, str]]:
    out = []
    for path in sorted(APP.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(BACKEND)
        module = ".".join(rel.with_suffix("").parts)
        out.append((path, module))
    return out


def analyze() -> dict:
    """Return edges: list of (src_module, dst_external_or_layer, dst_module)."""
    edges: list[tuple[str, str]] = []  # (src_module, dst_module_or_external)
    for path, module in iter_modules():
        try:
            tree = ast.parse(path.read_text(errors="replace"))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.If) and _is_type_checking_guard(node):
                node = None  # imports guarded by TYPE_CHECKING are not runtime edges
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root == "app":
                        edges.append((module, alias.name.split(".")[1] if len(alias.name.split(".")) > 1 else alias.name))
                    elif root in EXTERNAL:
                        edges.append((module, root))
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                if node.module == "app" or node.module.startswith("app."):
                    parts = node.module.split(".")
                    dst = parts[1] if len(parts) > 1 else "app"
                    edges.append((module, dst))
                elif node.module in EXTERNAL or node.module.split(".")[0] in EXTERNAL:
                    edges.append((module, node.module.split(".")[0]))
    return {"edges": sorted(set(edges))}


def summarize(data: dict) -> dict:
    """Layer->layer counts plus module-level forbidden edges and cycles."""
    counts: dict[tuple[str, str], int] = {}
    forbidden: list[tuple[str, str, str]] = []  # rule, src_module, dst
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
    }
    for src, dst in data["edges"]:
        src_layer = layer_of(src)
        if dst.startswith("app"):
            dst_layer = layer_of(dst)
        else:
            dst_layer = dst  # external root
        if src_layer is not None and dst_layer is not None:
            key = (src_layer, dst_layer)
            counts[key] = counts.get(key, 0) + 1
            if key in rules:
                forbidden.append((rules[key], src, dst))
    return {
        "layer_edges": {f"{a}->{b}": n for (a, b), n in sorted(counts.items())},
        "forbidden": sorted(set(forbidden)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default=None, help="write JSON matrix to path")
    args = parser.parse_args()
    data = analyze()
    summary = summarize(data)
    if args.json:
        payload = {
            "edges": data["edges"],
            "layer_edges": summary["layer_edges"],
            "forbidden": summary["forbidden"],
        }
        Path(args.json).write_text(json.dumps(payload, indent=1, sort_keys=True))
        print(f"wrote {args.json}")
        return 0
    print("== layer -> layer import counts ==")
    for k, v in summary["layer_edges"].items():
        print(f"  {k}: {v}")
    print("== currently forbidden edges ==")
    for rule, src, dst in summary["forbidden"]:
        print(f"  [{rule}] {src} -> {dst}")
    if not summary["forbidden"]:
        print("  none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
