"""Initial Workflow definitions and canonical hashes used by application CRUD.

These value operations do not load either execution engine.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from app.schemas.workflows.contracts import WorkflowGraph


def default_workflow_graph() -> WorkflowGraph:
    return WorkflowGraph.model_validate(
        {
            "nodes": [
                {
                    "id": "start",
                    "type": "workflow",
                    "position": {"x": 80, "y": 180},
                    "data": {
                        "type": "start",
                        "title": "Start",
                        "config": {},
                    },
                },
            ],
            "edges": [],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        }
    )


def graph_hash(graph: WorkflowGraph | Mapping[str, Any]) -> str:
    value = (
        graph.model_dump(by_alias=True, mode="json")
        if isinstance(graph, WorkflowGraph)
        else graph
    )
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
