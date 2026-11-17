"""Frozen historical rows used only in migration and removal regression tests."""

import sys
from functools import cache
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


@cache
def _migration(filename):
    path = Path(__file__).resolve().parents[2] / "alembic/versions" / filename
    spec = spec_from_file_location("fixture_" + path.stem, path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


build_workspace_system_catalog = _migration(
    "202609050001_shanghai_timezone.py"
).build_workspace_system_catalog
CURRENT_TIME_TOOL_CODE = _migration(
    "202609050001_shanghai_timezone.py"
).CURRENT_TIME_TOOL_CODE
build_inline_python_tool = _migration(
    "202608290001_enable_skills.py"
).build_inline_python_tool
