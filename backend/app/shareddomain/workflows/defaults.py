from app.schemas.workflow import WorkflowGraph


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
                        "config": {"inputs": [{"name": "input", "required": True}]},
                    },
                },
                {
                    "id": "end",
                    "type": "workflow",
                    "position": {"x": 460, "y": 180},
                    "data": {
                        "type": "end",
                        "title": "End",
                        "config": {"outputs": {"result": "{{start.input}}"}},
                    },
                },
            ],
            "edges": [{"id": "start-end", "source": "start", "target": "end"}],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        }
    )
