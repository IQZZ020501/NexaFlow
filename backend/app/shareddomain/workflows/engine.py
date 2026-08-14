import asyncio
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
import re
from typing import Any

from jinja2 import Environment, meta
from pydantic import BaseModel, ValidationError

from app.schemas.workflow import (
    ClassifierNodeConfig,
    CodeNodeConfig,
    ConditionNodeConfig,
    EndNodeConfig,
    KnowledgeNodeConfig,
    LlmNodeConfig,
    McpNodeConfig,
    ReplyNodeConfig,
    StartNodeConfig,
    TemplateNodeConfig,
    VariableNodeConfig,
    WorkflowGraph,
    WorkflowNode,
)


class WorkflowValidationError(ValueError):
    pass


class WorkflowEngineError(RuntimeError):
    def __init__(self, message: str, *, node_id: str | None = None):
        super().__init__(message)
        self.node_id = node_id


class EdgeState(StrEnum):
    UNKNOWN = "unknown"
    TAKEN = "taken"
    SKIPPED = "skipped"


class NodeState(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    FAILED = "failed"


NODE_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "start": StartNodeConfig,
    "end": EndNodeConfig,
    "llm": LlmNodeConfig,
    "classifier": ClassifierNodeConfig,
    "knowledge": KnowledgeNodeConfig,
    "condition": ConditionNodeConfig,
    "reply-node": ReplyNodeConfig,
    "template": TemplateNodeConfig,
    "variable": VariableNodeConfig,
    "mcp": McpNodeConfig,
    "code": CodeNodeConfig,
}

REFERENCE_PATTERN = re.compile(
    r"{{\s*([A-Za-z0-9_-]+)(?:\.([A-Za-z0-9_.-]+))?\s*}}"
)
JINJA_ENV = Environment()

# Start node globals are available to every node as bare references like {{time}}
# or through the {{global.<field>}} namespace (MaxKB-compatible).
WORKFLOW_GLOBALS = frozenset({"time", "history_context", "chat_id", "start_time"})


@dataclass(frozen=True)
class NodeExecutionContext:
    workflow_inputs: dict[str, Any]
    node_outputs: dict[str, dict[str, Any]]
    remaining_model_tokens: int
    globals: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NodeResult:
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    selected_handles: frozenset[str] | None = None
    model_tokens: int = 0
    model_usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NodeTransition:
    node: WorkflowNode
    status: NodeState
    sequence: int
    result: NodeResult = field(default_factory=NodeResult)
    error: str | None = None


@dataclass
class WorkflowEngineState:
    node_states: dict[str, str]
    edge_states: dict[str, str]
    node_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    step_count: int = 0
    model_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_states": self.node_states,
            "edge_states": self.edge_states,
            "node_outputs": self.node_outputs,
            "step_count": self.step_count,
            "model_tokens": self.model_tokens,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkflowEngineState":
        return cls(
            node_states={str(key): str(item) for key, item in value["node_states"].items()},
            edge_states={str(key): str(item) for key, item in value["edge_states"].items()},
            node_outputs={
                str(key): dict(item) for key, item in value.get("node_outputs", {}).items()
            },
            step_count=int(value.get("step_count", 0)),
            model_tokens=int(value.get("model_tokens", 0)),
        )


@dataclass(frozen=True)
class WorkflowEngineResult:
    outputs: dict[str, Any]
    state: WorkflowEngineState


ExecuteNode = Callable[[WorkflowNode, NodeExecutionContext], Awaitable[NodeResult]]
NodeStarted = Callable[[WorkflowNode, int], Awaitable[None]]
NodeFinished = Callable[[NodeTransition, WorkflowEngineState], Awaitable[None]]


async def _noop_started(node: WorkflowNode, sequence: int) -> None:
    return None


async def _noop_finished(
    transition: NodeTransition,
    state: WorkflowEngineState,
) -> None:
    return None


def graph_hash(graph: WorkflowGraph | Mapping[str, Any]) -> str:
    value = graph.model_dump(by_alias=True, mode="json") if isinstance(graph, WorkflowGraph) else graph
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _iter_references(value: Any):
    if isinstance(value, str):
        yield from (
            match.group(1)
            for match in REFERENCE_PATTERN.finditer(value)
            if match.group(1) not in WORKFLOW_GLOBALS and match.group(1) != "global"
        )
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _iter_references(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_references(item)


def _reachable(start: str, adjacency: Mapping[str, list[str]]) -> set[str]:
    found: set[str] = set()
    queue = deque([start])
    while queue:
        node_id = queue.popleft()
        if node_id in found:
            continue
        found.add(node_id)
        queue.extend(adjacency[node_id])
    return found


def validate_graph(graph: WorkflowGraph | Mapping[str, Any]) -> WorkflowGraph:
    try:
        parsed = graph if isinstance(graph, WorkflowGraph) else WorkflowGraph.model_validate(graph)
    except ValidationError as exc:
        raise WorkflowValidationError(str(exc)) from exc

    node_ids = [node.id for node in parsed.nodes]
    if len(node_ids) != len(set(node_ids)):
        raise WorkflowValidationError("Workflow node ids must be unique.")
    reserved_node_ids = set(node_ids) & (WORKFLOW_GLOBALS | {"global"})
    if reserved_node_ids:
        raise WorkflowValidationError(
            "Workflow node ids must not use reserved global names."
        )
    edge_ids = [edge.id for edge in parsed.edges]
    if len(edge_ids) != len(set(edge_ids)):
        raise WorkflowValidationError("Workflow edge ids must be unique.")

    nodes = {node.id: node for node in parsed.nodes}
    starts = [node for node in parsed.nodes if node.data.type == "start"]
    ends = [node for node in parsed.nodes if node.data.type == "end"]
    if len(starts) != 1 or len(ends) != 1:
        raise WorkflowValidationError("Workflow must contain exactly one start and one end node.")

    incoming: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    outgoing_edges = {node_id: [] for node_id in nodes}
    for edge in parsed.edges:
        if edge.source not in nodes or edge.target not in nodes:
            raise WorkflowValidationError(f"Edge {edge.id} has an unknown endpoint.")
        if edge.source == edge.target:
            raise WorkflowValidationError(f"Edge {edge.id} cannot connect a node to itself.")
        outgoing[edge.source].append(edge.target)
        incoming[edge.target].append(edge.source)
        outgoing_edges[edge.source].append(edge)

    start_id, end_id = starts[0].id, ends[0].id
    if incoming[start_id]:
        raise WorkflowValidationError("Start node cannot have incoming edges.")
    if outgoing[end_id]:
        raise WorkflowValidationError("End node cannot have outgoing edges.")
    if _reachable(start_id, outgoing) != set(nodes):
        raise WorkflowValidationError("Every node must be reachable from the start node.")

    reverse_reachable = _reachable(end_id, incoming)
    if reverse_reachable != set(nodes):
        raise WorkflowValidationError("Every node must lead to the end node.")

    indegree = {node_id: len(values) for node_id, values in incoming.items()}
    ready = deque(node_id for node_id in node_ids if indegree[node_id] == 0)
    topological: list[str] = []
    while ready:
        node_id = ready.popleft()
        topological.append(node_id)
        for target in outgoing[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if len(topological) != len(nodes):
        raise WorkflowValidationError("Workflow graph must not contain cycles.")

    for node in parsed.nodes:
        try:
            config = NODE_CONFIG_MODELS[node.data.type].model_validate(node.data.config)
        except ValidationError as exc:
            raise WorkflowValidationError(
                f"Node {node.id} has invalid {node.data.type} configuration: {exc}"
            ) from exc
        edges = outgoing_edges[node.id]
        handles = [edge.source_handle for edge in edges]
        if node.data.type == "condition":
            condition = ConditionNodeConfig.model_validate(config)
            expected = {branch.id for branch in condition.branch}
            if set(handles) != expected or len(handles) != len(expected):
                raise WorkflowValidationError(
                    f"Condition node {node.id} requires one edge for every branch."
                )
        if node.data.type == "classifier":
            classifier = ClassifierNodeConfig.model_validate(config)
            expected = {item.handle for item in classifier.classes} | {
                classifier.default_handle
            }
            if len(expected) != len(classifier.classes) + 1:
                raise WorkflowValidationError(
                    f"Classifier node {node.id} handles must be unique."
                )
            if set(handles) != expected or len(handles) != len(expected):
                raise WorkflowValidationError(
                    f"Classifier node {node.id} requires one edge for every class and default."
                )

    ancestors: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    for node_id in topological:
        for parent in incoming[node_id]:
            ancestors[node_id].add(parent)
            ancestors[node_id].update(ancestors[parent])
        node = nodes[node_id]
        references = list(_iter_references(node.data.config))
        if node.data.type == "reply-node":
            reply = ReplyNodeConfig.model_validate(node.data.config)
            if reply.reply_type == "referencing" and reply.fields:
                references.append(reply.fields[0][0])
            elif reply.reply_type == "custom":
                normalized = REFERENCE_PATTERN.sub(
                    "{{ workflow_refs.value }}", reply.content
                )
                references.extend(
                    name
                    for name in meta.find_undeclared_variables(
                        JINJA_ENV.parse(normalized)
                    )
                    if name != "workflow_refs"
                )
        if node.data.type == "condition":
            condition = ConditionNodeConfig.model_validate(node.data.config)
            references.extend(
                rule.field[0]
                for branch in condition.branch
                for rule in branch.conditions
            )
        for reference in references:
            if reference in WORKFLOW_GLOBALS or reference == "global":
                continue
            if reference not in ancestors[node_id]:
                raise WorkflowValidationError(
                    f"Node {node_id} references non-upstream node {reference}."
                )
    return parsed


class WorkflowEngine:
    def __init__(
        self,
        graph: WorkflowGraph | Mapping[str, Any],
        *,
        max_steps: int,
        max_model_tokens: int,
        deadline_at: datetime,
    ) -> None:
        if max_steps <= 0 or max_model_tokens <= 0:
            raise ValueError("Workflow budgets must be greater than zero.")
        self.graph = validate_graph(graph)
        self.max_steps = max_steps
        self.max_model_tokens = max_model_tokens
        self.deadline_at = deadline_at
        self.nodes = {node.id: node for node in self.graph.nodes}
        self.incoming = {node.id: [] for node in self.graph.nodes}
        self.outgoing = {node.id: [] for node in self.graph.nodes}
        for edge in self.graph.edges:
            self.incoming[edge.target].append(edge)
            self.outgoing[edge.source].append(edge)

    def initial_state(self) -> WorkflowEngineState:
        return WorkflowEngineState(
            node_states={node.id: NodeState.PENDING for node in self.graph.nodes},
            edge_states={edge.id: EdgeState.UNKNOWN for edge in self.graph.edges},
        )

    def _remaining_seconds(self) -> float:
        deadline = self.deadline_at
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        return (deadline - datetime.now(UTC)).total_seconds()

    async def run(
        self,
        workflow_inputs: dict[str, Any],
        execute_node: ExecuteNode,
        *,
        state: WorkflowEngineState | None = None,
        on_node_started: NodeStarted = _noop_started,
        on_node_finished: NodeFinished = _noop_finished,
        workflow_globals: Mapping[str, Any] | None = None,
    ) -> WorkflowEngineResult:
        current = state or self.initial_state()
        node_order = {node.id: index for index, node in enumerate(self.graph.nodes)}
        run_globals = dict(workflow_globals or {})

        while any(value == NodeState.PENDING for value in current.node_states.values()):
            if self._remaining_seconds() <= 0:
                raise WorkflowEngineError("Workflow deadline exceeded.")

            skipped: list[WorkflowNode] = []
            ready: list[WorkflowNode] = []
            for node in self.graph.nodes:
                if current.node_states[node.id] != NodeState.PENDING:
                    continue
                incoming = self.incoming[node.id]
                states = [current.edge_states[edge.id] for edge in incoming]
                if not incoming or (
                    all(value != EdgeState.UNKNOWN for value in states)
                    and any(value == EdgeState.TAKEN for value in states)
                ):
                    ready.append(node)
                elif states and all(value == EdgeState.SKIPPED for value in states):
                    skipped.append(node)

            if skipped:
                for node in sorted(skipped, key=lambda item: node_order[item.id]):
                    current.node_states[node.id] = NodeState.SKIPPED
                    for edge in self.outgoing[node.id]:
                        current.edge_states[edge.id] = EdgeState.SKIPPED
                    await on_node_finished(
                        NodeTransition(
                            node=node,
                            status=NodeState.SKIPPED,
                            sequence=current.step_count,
                        ),
                        current,
                    )
                continue

            if not ready:
                raise WorkflowEngineError("Workflow scheduler reached an invalid graph state.")
            if current.step_count + len(ready) > self.max_steps:
                raise WorkflowEngineError("Workflow step limit exceeded.")

            ready.sort(key=lambda item: node_order[item.id])
            starts = [
                on_node_started(node, current.step_count + offset + 1)
                for offset, node in enumerate(ready)
            ]
            await asyncio.gather(*starts)

            async def execute(node: WorkflowNode) -> NodeResult | BaseException:
                context = NodeExecutionContext(
                    workflow_inputs=dict(workflow_inputs),
                    node_outputs={
                        key: dict(value) for key, value in current.node_outputs.items()
                    },
                    remaining_model_tokens=self.max_model_tokens - current.model_tokens,
                    globals=run_globals,
                )
                try:
                    async with asyncio.timeout(self._remaining_seconds()):
                        return await execute_node(node, context)
                except Exception as exc:
                    return exc

            results = await asyncio.gather(*(execute(node) for node in ready))
            first_error: WorkflowEngineError | None = None
            for node, result in zip(ready, results, strict=True):
                sequence = current.step_count + 1
                if isinstance(result, BaseException):
                    current.node_states[node.id] = NodeState.FAILED
                    message = (
                        "Workflow deadline exceeded."
                        if isinstance(result, TimeoutError)
                        else str(result) or result.__class__.__name__
                    )
                    current.step_count += 1
                    await on_node_finished(
                        NodeTransition(
                            node=node,
                            status=NodeState.FAILED,
                            sequence=sequence,
                            error=message,
                        ),
                        current,
                    )
                    first_error = first_error or WorkflowEngineError(
                        message,
                        node_id=node.id,
                    )
                    continue

                if result.model_tokens < 0:
                    current.node_states[node.id] = NodeState.FAILED
                    current.step_count += 1
                    message = "Node returned invalid model token usage."
                    await on_node_finished(
                        NodeTransition(
                            node=node,
                            status=NodeState.FAILED,
                            sequence=sequence,
                            error=message,
                        ),
                        current,
                    )
                    first_error = first_error or WorkflowEngineError(
                        message, node_id=node.id
                    )
                    continue
                projected_model_tokens = current.model_tokens + result.model_tokens
                if projected_model_tokens > self.max_model_tokens:
                    current.node_states[node.id] = NodeState.FAILED
                    current.model_tokens = projected_model_tokens
                    current.step_count += 1
                    message = "Workflow model token budget exceeded."
                    await on_node_finished(
                        NodeTransition(
                            node=node,
                            status=NodeState.FAILED,
                            sequence=sequence,
                            result=result,
                            error=message,
                        ),
                        current,
                    )
                    first_error = first_error or WorkflowEngineError(
                        message, node_id=node.id
                    )
                    continue
                current.node_states[node.id] = NodeState.SUCCEEDED
                current.node_outputs[node.id] = dict(result.outputs)
                current.model_tokens = projected_model_tokens
                selected = result.selected_handles
                for edge in self.outgoing[node.id]:
                    current.edge_states[edge.id] = (
                        EdgeState.TAKEN
                        if selected is None or edge.source_handle in selected
                        else EdgeState.SKIPPED
                    )
                current.step_count += 1
                await on_node_finished(
                    NodeTransition(
                        node=node,
                        status=NodeState.SUCCEEDED,
                        sequence=sequence,
                        result=result,
                    ),
                    current,
                )
            if first_error:
                raise first_error

        end = next(node for node in self.graph.nodes if node.data.type == "end")
        if current.node_states[end.id] != NodeState.SUCCEEDED:
            raise WorkflowEngineError("Workflow ended without producing an output.")
        outputs = dict(current.node_outputs[end.id])
        answers: list[str] = []
        for node in self.graph.nodes:
            if current.node_states[node.id] != NodeState.SUCCEEDED:
                continue
            if node.data.type == "llm":
                config = LlmNodeConfig.model_validate(node.data.config)
                value = current.node_outputs[node.id].get("text")
            elif node.data.type == "reply-node":
                config = ReplyNodeConfig.model_validate(node.data.config)
                value = current.node_outputs[node.id].get("answer")
            else:
                continue
            if config.is_result and value is not None:
                answers.append(str(value))
        if answers:
            outputs.setdefault("result", "\n\n".join(answers))
        return WorkflowEngineResult(outputs=outputs, state=current)
