from dataclasses import dataclass
import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.application.agent_executor import DurableToolLedger
from app.application.agent_tools import (
    build_knowledge_search_tool,
    build_mcp_agent_tool,
)
from app.entities.agents import AgentRun
from app.entities.knowledge import KnowledgeBase
from app.entities.tools import McpToolPolicy
from app.entities.user import User
from app.infrastructure.code_sandbox import execute_workflow_code
from app.infrastructure.config import Settings
from app.ports.llm import RegisteredModel, build_chat_model
from app.schemas.workflow import (
    ClassifierNodeConfig,
    CodeNodeConfig,
    ConditionNodeConfig,
    EndNodeConfig,
    KnowledgeNodeConfig,
    LlmNodeConfig,
    McpNodeConfig,
    StartNodeConfig,
    TemplateNodeConfig,
    VariableNodeConfig,
    WorkflowNode,
)
from app.shareddomain.agents.runtime import AgentExecutionPaused
from app.shareddomain.agents.runtime.graph import model_completion
from app.shareddomain.agents.runtime.state import PendingToolCall
from app.shareddomain.agents.runtime.tools import agent_tool_metadata
from app.shareddomain.agents.runtime.usage import usage_from_message
from app.shareddomain.tools.services import ResolvedMcpTool
from app.shareddomain.workflows.engine import NodeExecutionContext, NodeResult


@dataclass(frozen=True)
class WorkflowNodeScope:
    run: AgentRun
    actor: User
    workspace_role: str | None
    settings: Settings
    models: dict[str, RegisteredModel]
    knowledge_bases: dict[str, KnowledgeBase]
    mcp_tools: dict[tuple[str, str], tuple[ResolvedMcpTool, McpToolPolicy]]
    ledger: DurableToolLedger
    node_order: dict[str, int]
    input_assignment_method: str | None = None


def _path_value(value: Any, path: str) -> Any:
    current = value
    if not path:
        return current
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise ValueError(f"Workflow reference path not found: {path}.")
    return current


def resolve_value(value: Any, context: NodeExecutionContext) -> Any:
    from app.shareddomain.workflows.engine import REFERENCE_PATTERN

    if isinstance(value, dict):
        return {key: resolve_value(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_value(item, context) for item in value]
    if not isinstance(value, str):
        return value

    def outputs(node_id: str) -> dict[str, Any]:
        if node_id not in context.node_outputs:
            raise ValueError(f"Workflow reference node did not run: {node_id}.")
        return context.node_outputs[node_id]

    exact = REFERENCE_PATTERN.fullmatch(value)
    if exact:
        node_id, path = exact.group(1), exact.group(2) or ""
        return _path_value(outputs(node_id), path)

    def replace(match) -> str:
        item = _path_value(
            outputs(match.group(1)),
            match.group(2) or "",
        )
        if isinstance(item, (dict, list)):
            return json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        return str(item)

    return REFERENCE_PATTERN.sub(replace, value)


def _matches_type(value: Any, expected: str) -> bool:
    return {
        "string": isinstance(value, str),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
    }[expected]


def _start_result(
    config: StartNodeConfig,
    inputs: dict[str, Any],
    *,
    assignment_method: str | None = None,
) -> NodeResult:
    fields = {field.name: field for field in config.inputs}
    unknown = set(inputs) - set(fields) - {"files"}
    if unknown:
        raise ValueError(f"Unknown workflow inputs: {', '.join(sorted(unknown))}.")
    if assignment_method is not None:
        invalid = {
            name
            for name in inputs
            if name in fields and fields[name].assignment_method != assignment_method
        }
        if invalid:
            raise ValueError(
                "Workflow inputs are not accepted from this workflow access source: "
                f"{', '.join(sorted(invalid))}."
            )
    output: dict[str, Any] = {}
    output["files"] = inputs.get("files", [])
    for name, field in fields.items():
        if name in inputs:
            value = inputs[name]
        elif field.default is not None:
            value = field.default
        elif field.required and (
            assignment_method is None or field.assignment_method == assignment_method
        ):
            raise ValueError(f"Required workflow input is missing: {name}.")
        else:
            value = None
        if value is not None and not _matches_type(value, field.type):
            raise ValueError(f"Workflow input {name} must be {field.type}.")
        if value is not None:
            field.validate_control_value(value)
        output[name] = value
    return NodeResult(inputs=dict(inputs), outputs=output)


def _model_output_limit(provider_type: str, remaining_model_tokens: int) -> dict[str, int]:
    if provider_type == "google_genai":
        return {"max_output_tokens": remaining_model_tokens}
    if provider_type == "ollama":
        return {"num_predict": remaining_model_tokens}
    return {"max_tokens": remaining_model_tokens}


async def _model_result(
    scope: WorkflowNodeScope,
    model_id: str,
    system_prompt: str,
    prompt: str,
    remaining_model_tokens: int,
) -> tuple[str, dict[str, Any]]:
    model = scope.models.get(model_id)
    if model is None:
        raise ValueError("Workflow model is unavailable.")
    if remaining_model_tokens <= 0:
        raise ValueError("Workflow model token budget exceeded.")
    messages = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    messages.append(HumanMessage(content=prompt))
    output_limit = _model_output_limit(model.provider_type, remaining_model_tokens)
    message = await build_chat_model(scope.settings, model).ainvoke(
        messages, **output_limit
    )
    usage = usage_from_message(message)
    return model_completion(message).content, usage


def _condition(left: Any, operator: str, right: Any) -> bool:
    if operator == "equals":
        return left == right
    if operator == "not_equals":
        return left != right
    if operator in {"contains", "not_contains"}:
        if not isinstance(left, (str, list, dict)):
            raise ValueError(
                "Workflow contains condition requires a string, array, or object."
            )
        if isinstance(left, str) and not isinstance(right, str):
            raise ValueError("Workflow contains condition has incompatible operands.")
        if isinstance(left, dict):
            try:
                hash(right)
            except TypeError as exc:
                raise ValueError(
                    "Workflow contains condition has incompatible operands."
                ) from exc
        matched = right in left
        return matched if operator == "contains" else not matched
    if operator in {
        "greater_than",
        "greater_than_or_equal",
        "less_than",
        "less_than_or_equal",
    } and not (
        (isinstance(left, str) and isinstance(right, str))
        or (
            isinstance(left, (int, float))
            and not isinstance(left, bool)
            and isinstance(right, (int, float))
            and not isinstance(right, bool)
        )
    ):
        raise ValueError(
            "Workflow ordering condition requires two strings or two numbers."
        )
    if operator == "greater_than":
        return left > right
    if operator == "greater_than_or_equal":
        return left >= right
    if operator == "less_than":
        return left < right
    if operator == "less_than_or_equal":
        return left <= right
    if operator == "is_empty":
        return left is None or left == "" or left == [] or left == {}
    if operator == "is_not_empty":
        return not (left is None or left == "" or left == [] or left == {})
    if operator.startswith("length_"):
        if not isinstance(left, (str, list, dict)):
            raise ValueError(
                "Workflow length condition requires a string, array, or object."
            )
        if not isinstance(right, int) or isinstance(right, bool) or right < 0:
            raise ValueError(
                "Workflow length condition requires a non-negative integer."
            )
    if operator == "length_equals":
        return len(left) == right
    if operator == "length_greater_than":
        return len(left) > right
    if operator == "length_greater_than_or_equal":
        return len(left) >= right
    if operator == "length_less_than":
        return len(left) < right
    if operator == "length_less_than_or_equal":
        return len(left) <= right
    if operator == "is_true":
        return left is True
    if operator == "is_false":
        return left is False
    raise ValueError("Unknown workflow condition operator.")


async def execute_workflow_node(
    scope: WorkflowNodeScope,
    node: WorkflowNode,
    context: NodeExecutionContext,
) -> NodeResult:
    config = node.data.config
    node_type = node.data.type
    if node_type == "start":
        return _start_result(
            StartNodeConfig.model_validate(config),
            context.workflow_inputs,
            assignment_method=scope.input_assignment_method,
        )
    if node_type == "end":
        outputs = resolve_value(EndNodeConfig.model_validate(config).outputs, context)
        return NodeResult(inputs=dict(outputs), outputs=dict(outputs))
    if node_type == "variable":
        value = resolve_value(VariableNodeConfig.model_validate(config).value, context)
        return NodeResult(inputs={"value": value}, outputs={"value": value})
    if node_type == "template":
        template = TemplateNodeConfig.model_validate(config).template
        text = resolve_value(template, context)
        return NodeResult(inputs={"template": template}, outputs={"text": text})
    if node_type == "condition":
        parsed = ConditionNodeConfig.model_validate(config)
        left = resolve_value(parsed.left, context)
        right = resolve_value(parsed.right, context)
        matched = _condition(left, parsed.operator, right)
        return NodeResult(
            inputs={"left": left, "operator": parsed.operator, "right": right},
            outputs={"matched": matched},
            selected_handles=frozenset({"true" if matched else "false"}),
        )
    if node_type == "llm":
        parsed = LlmNodeConfig.model_validate(config)
        prompt = str(resolve_value(parsed.prompt, context))
        system_prompt = str(resolve_value(parsed.system_prompt, context))
        model_id = parsed.model_id or scope.run.model_id
        content, usage = await _model_result(
            scope, model_id, system_prompt, prompt, context.remaining_model_tokens
        )
        return NodeResult(
            inputs={"prompt": prompt, "system_prompt": system_prompt, "model_id": model_id},
            outputs={"text": content},
            model_tokens=int(usage.get("total_tokens") or 0),
            model_usage=usage,
        )
    if node_type == "classifier":
        parsed = ClassifierNodeConfig.model_validate(config)
        value = resolve_value(parsed.input, context)
        handles = [item.handle for item in parsed.classes]
        class_lines = "\n".join(
            f"- {item.handle}: {item.label}. {item.description}" for item in parsed.classes
        )
        prompt = (
            "Classify the input into exactly one handle. Return only the handle.\n"
            f"Classes:\n{class_lines}\nInput:\n{json.dumps(value, ensure_ascii=False)}"
        )
        model_id = parsed.model_id or scope.run.model_id
        content, usage = await _model_result(
            scope, model_id, "", prompt, context.remaining_model_tokens
        )
        selected = content.strip() if content.strip() in handles else parsed.default_handle
        return NodeResult(
            inputs={"input": value, "model_id": model_id},
            outputs={"class": selected},
            selected_handles=frozenset({selected}),
            model_tokens=int(usage.get("total_tokens") or 0),
            model_usage=usage,
        )
    if node_type == "knowledge":
        parsed = KnowledgeNodeConfig.model_validate(config)
        query = str(resolve_value(parsed.query, context))
        knowledge_bases = [
            scope.knowledge_bases[knowledge_base_id]
            for knowledge_base_id in parsed.resolved_knowledge_base_ids
            if knowledge_base_id in scope.knowledge_bases
        ]
        if len(knowledge_bases) != len(parsed.resolved_knowledge_base_ids):
            raise ValueError("Workflow knowledge base is unavailable.")
        tool = build_knowledge_search_tool(
            knowledge_bases,
            scope.run.workspace_id,
            scope.actor,
            scope.workspace_role,
            scope.settings,
        )
        result = await tool.ainvoke({"query": query, "limit": parsed.limit})
        if result.is_error:
            raise RuntimeError(result.summary)
        output = result.output if isinstance(result.output, dict) else {"content": result.content}
        hits = output.get("hits")
        selected_hits = hits[: parsed.limit] if isinstance(hits, list) else []
        outputs = {
            **output,
            "hits": selected_hits,
            "content": "\n\n".join(
                str(item.get("content") or "")
                for item in selected_hits
                if isinstance(item, dict) and item.get("content")
            ),
        }
        return NodeResult(
            inputs={
                "query": query,
                "knowledge_base_ids": parsed.resolved_knowledge_base_ids,
                "limit": parsed.limit,
            },
            outputs=outputs,
        )
    if node_type == "mcp":
        parsed = McpNodeConfig.model_validate(config)
        arguments = resolve_value(parsed.arguments, context)
        resolved = scope.mcp_tools.get((parsed.server_id, parsed.tool_name))
        if resolved is None:
            raise ValueError("Workflow MCP tool is unavailable or not read-only.")
        tool = build_mcp_agent_tool(resolved[0], scope.settings, "read_only")
        metadata = agent_tool_metadata(tool)
        call: PendingToolCall = {
            "id": f"workflow-{node.id}",
            "name": tool.name,
            "arguments": json.dumps(arguments, ensure_ascii=False),
        }
        turn = scope.node_order[node.id] + 1
        try:
            result = await scope.ledger.before(turn, call, metadata, arguments)
            if result is None:
                result = await tool.ainvoke(arguments)
                await scope.ledger.after(turn, call, metadata, arguments, result)
        except AgentExecutionPaused as exc:
            raise RuntimeError("Workflow MCP node requires a current read-only policy.") from exc
        if result.is_error:
            raise RuntimeError(result.summary)
        output = result.output if isinstance(result.output, dict) else {"content": result.content}
        return NodeResult(inputs=dict(arguments), outputs=dict(output))
    if node_type == "code":
        parsed = CodeNodeConfig.model_validate(config)
        inputs = resolve_value(parsed.inputs, context)
        result = await execute_workflow_code(scope.settings, parsed.code, inputs)
        return NodeResult(
            inputs=dict(inputs),
            outputs={
                "result": result.result,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )
    raise ValueError(f"Unsupported workflow node type: {node_type}.")
