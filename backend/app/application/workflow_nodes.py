import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import json
import math
import re
from typing import Any

from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    message_chunk_to_message,
)
from langchain_core.tools import StructuredTool

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
from app.ports.llm import (
    ModelToolCall,
    RegisteredModel,
    build_chat_model,
    build_reranker,
)
from app.schemas.workflow import (
    ClassifierNodeConfig,
    CodeNodeConfig,
    ConditionNodeConfig,
    DocumentExtractNodeConfig,
    EndNodeConfig,
    FormNodeConfig,
    KnowledgeNodeConfig,
    LlmNodeConfig,
    McpNodeConfig,
    ReplyNodeConfig,
    RerankerNodeConfig,
    StartNodeConfig,
    TemplateNodeConfig,
    VariableNodeConfig,
    WorkflowNode,
)
from app.shareddomain.agents.runtime import AgentExecutionPaused
from app.shareddomain.agents.runtime.graph import model_completion
from app.shareddomain.agents.runtime.state import PendingToolCall
from app.shareddomain.agents.runtime.tools import (
    AgentToolResult,
    agent_tool_metadata,
)
from app.shareddomain.agents.runtime.usage import merge_usage, usage_from_message
from app.shareddomain.tools.services import ResolvedMcpTool
from app.shareddomain.workflows.engine import NodeExecutionContext, NodeResult

MAX_WORKFLOW_LLM_TOOL_CALLS = 8
DEFAULT_WORKFLOW_LLM_MAX_TOKENS = 4096
REPLY_TEMPLATE_ENV = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)
REPLY_TEMPLATE_ENV.globals.clear()
FORM_PLACEHOLDER_PATTERN = re.compile(r"{{\s*form\s*}}")


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
    node_histories: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict
    )
    form_submissions: dict[str, dict[str, Any]] = field(default_factory=dict)
    output_delta: Callable[[str, str], Awaitable[None]] | None = None


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

    def reference_value(name: str, path: str) -> Any:
        if name == "global":
            return _path_value(context.globals, path)
        if name in context.node_outputs:
            return _path_value(outputs(name), path)
        if name in context.globals and not path:
            return context.globals[name]
        return _path_value(outputs(name), path)

    exact = REFERENCE_PATTERN.fullmatch(value)
    if exact:
        return reference_value(exact.group(1), exact.group(2) or "")

    def replace(match) -> str:
        item = reference_value(match.group(1), match.group(2) or "")
        if isinstance(item, (dict, list)):
            return json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        return str(item)

    return REFERENCE_PATTERN.sub(replace, value)


def render_reply_template(template: str, context: NodeExecutionContext) -> str:
    from app.shareddomain.workflows.engine import REFERENCE_PATTERN

    references: dict[str, Any] = {}

    def replace(match) -> str:
        key = f"value_{len(references)}"
        references[key] = resolve_value(match.group(0), context)
        return "{{ workflow_refs." + key + " }}"

    normalized = REFERENCE_PATTERN.sub(replace, template)
    variables: dict[str, Any] = {
        **context.globals,
        "global": context.globals,
        "workflow_refs": references,
    }
    variables.update(
        {
            node_id: outputs
            for node_id, outputs in context.node_outputs.items()
            if node_id.isidentifier()
        }
    )
    try:
        return REPLY_TEMPLATE_ENV.from_string(normalized).render(variables)
    except TemplateError as exc:
        raise ValueError(f"Invalid workflow reply template: {exc}") from exc


def render_form_template(template: str, context: NodeExecutionContext) -> str:
    placeholder = "\ue000workflow_form\ue001"
    normalized = FORM_PLACEHOLDER_PATTERN.sub(placeholder, template)
    return render_reply_template(normalized, context).replace(
        placeholder,
        "{{ form }}",
    )


def _reranker_candidates(values: list[Any]) -> tuple[list[Any], list[str]]:
    candidates: list[Any] = []
    for value in values:
        candidates.extend(value if isinstance(value, list) else [value])
    texts = [
        str(item.get("content") or "") if isinstance(item, dict) else str(item)
        for item in candidates
    ]
    if not candidates or any(not text for text in texts):
        raise ValueError("Workflow reranker content must contain non-empty text.")
    return candidates, texts


def _model_output_limit(provider_type: str, remaining_model_tokens: int) -> dict[str, int]:
    output_tokens = min(remaining_model_tokens, DEFAULT_WORKFLOW_LLM_MAX_TOKENS)
    if provider_type == "google_genai":
        return {"max_output_tokens": output_tokens}
    if provider_type == "ollama":
        return {"num_predict": output_tokens}
    return {"max_tokens": output_tokens}


def _model_call_params(
    provider_type: str,
    setting: dict[str, Any],
    remaining_model_tokens: int,
) -> dict[str, Any]:
    """Merge user model parameters with the remaining token output limit.

    Only parameters every supported provider accepts are honored; a user
    ``max_tokens`` is capped by the run's remaining model token budget.
    """
    output_limit = _model_output_limit(provider_type, remaining_model_tokens)
    native_max_key = next(iter(output_limit))
    params: dict[str, Any] = {}
    temperature = setting.get("temperature")
    if isinstance(temperature, (int, float)) and not isinstance(temperature, bool):
        params["temperature"] = float(temperature)
    top_p = setting.get("top_p")
    if isinstance(top_p, (int, float)) and not isinstance(top_p, bool):
        params["top_p"] = float(top_p)
    max_tokens = setting.get("max_tokens")
    if (
        isinstance(max_tokens, int)
        and not isinstance(max_tokens, bool)
        and max_tokens > 0
    ):
        params[native_max_key] = min(max_tokens, remaining_model_tokens)
    return {**output_limit, **params}


def _history_messages(
    parsed: LlmNodeConfig,
    scope: WorkflowNodeScope,
    node: WorkflowNode,
    context: NodeExecutionContext,
) -> list[Any]:
    """Build the multi-turn history messages for an LLM node.

    ``NODE`` keeps only prior turns whose answer was produced by this node;
    ``WORKFLOW`` keeps the whole conversation history. Both take the last
    ``dialogue_number`` rounds, mirroring MaxKB semantics.
    """
    rounds = parsed.dialogue_number
    if rounds <= 0:
        return []
    history: Any = context.globals.get("history_context") or []
    if parsed.dialogue_type == "NODE":
        history = scope.node_histories.get(node.id) or []
    messages: list[Any] = []
    for item in history[-rounds:]:
        if not isinstance(item, dict):
            continue
        question = item.get("question")
        answer = item.get("answer")
        if question is None or answer is None:
            continue
        messages.append(HumanMessage(content=str(question)))
        messages.append(AIMessage(content=str(answer)))
    return messages


def _message_reasoning(message: Any) -> str:
    reasoning = getattr(message, "additional_kwargs", None)
    value = reasoning.get("reasoning_content") if isinstance(reasoning, dict) else None
    return value if isinstance(value, str) else ""


async def _invoke_model(
    chat_model: Any,
    messages: list[Any],
    call_params: dict[str, Any],
    on_delta: Callable[[str], Awaitable[None]] | None,
) -> Any:
    if on_delta is None:
        return await chat_model.ainvoke(messages, **call_params)
    aggregate: AIMessageChunk | None = None
    async for chunk in chat_model.astream(messages, **call_params):
        if not isinstance(chunk, AIMessageChunk):
            raise ValueError("Workflow model returned an invalid stream message.")
        if chunk.text:
            await on_delta(chunk.text)
        aggregate = chunk if aggregate is None else aggregate + chunk
    return message_chunk_to_message(aggregate or AIMessageChunk(content=""))


async def _invoke_chat(
    scope: WorkflowNodeScope,
    model: RegisteredModel,
    messages: list[Any],
    remaining_model_tokens: int,
    call_params: dict[str, Any] | None = None,
    on_delta: Callable[[str], Awaitable[None]] | None = None,
) -> tuple[str, dict[str, Any], str]:
    """One chat-model call returning content, usage, and reasoning content."""
    output_limit = _model_output_limit(model.provider_type, remaining_model_tokens)
    merged = {**output_limit, **(call_params or {})}
    message = await _invoke_model(
        build_chat_model(scope.settings, model), messages, merged, on_delta
    )
    usage = usage_from_message(message)
    return model_completion(message).content, usage, _message_reasoning(message)


async def _llm_tool_call(
    scope: WorkflowNodeScope,
    node: WorkflowNode,
    tool: StructuredTool,
    call: ModelToolCall,
    tool_call_count: int,
) -> AgentToolResult:
    arguments: Any = {}
    if call.arguments:
        try:
            arguments = json.loads(call.arguments)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "Workflow model returned invalid tool arguments."
            ) from exc
    if not isinstance(arguments, dict):
        raise ValueError("Workflow model returned invalid tool arguments.")
    pending: PendingToolCall = {
        "id": f"workflow-{node.id}-tool-{tool_call_count}",
        "name": tool.name,
        "arguments": call.arguments or "{}",
    }
    metadata = agent_tool_metadata(tool)
    turn = scope.node_order.get(node.id, 0) + 1 + tool_call_count
    try:
        stored = await scope.ledger.before(turn, pending, metadata, arguments)
        if stored is None:
            result = await tool.ainvoke(arguments)
            await scope.ledger.after(turn, pending, metadata, arguments, result)
        else:
            result = stored
    except AgentExecutionPaused as exc:
        raise RuntimeError(
            "Workflow LLM MCP tool call is not permitted."
        ) from exc
    return result


async def _model_tool_loop(
    scope: WorkflowNodeScope,
    node: WorkflowNode,
    model: RegisteredModel,
    messages: list[Any],
    remaining_model_tokens: int,
    call_params: dict[str, Any],
    tools: list[StructuredTool],
    on_delta: Callable[[str], Awaitable[None]] | None = None,
) -> tuple[str, dict[str, Any], str]:
    """Run the LLM with bound MCP tools until it answers or the call cap hits.

    Tool executions are durably recorded through the run's tool ledger, and
    every model invocation counts against the run's model token budget.
    """
    bound = build_chat_model(scope.settings, model).bind_tools(tools)
    total_usage: dict[str, Any] = {}
    tool_call_count = 0
    reasoning = ""
    for _ in range(MAX_WORKFLOW_LLM_TOOL_CALLS):
        message = await _invoke_model(bound, messages, call_params, on_delta)
        reasoning = _message_reasoning(message)
        total_usage = merge_usage(total_usage, usage_from_message(message))
        if int(total_usage.get("total_tokens") or 0) > remaining_model_tokens:
            raise ValueError("Workflow model token budget exceeded.")
        completion = model_completion(message)
        if completion.tool_calls:
            messages.append(message)
            for call in completion.tool_calls:
                if not call.id or not call.name:
                    raise ValueError("Workflow model returned an invalid tool call.")
                tool = next(
                    (item for item in tools if item.name == call.name), None
                )
                if tool is None:
                    raise ValueError("Workflow model requested an unavailable tool.")
                result = await _llm_tool_call(
                    scope,
                    node,
                    tool,
                    call,
                    tool_call_count,
                )
                tool_call_count += 1
                messages.append(
                    ToolMessage(
                        content=result.content,
                        tool_call_id=call.id,
                        name=tool.name,
                    )
                )
            continue
        return completion.content, total_usage, reasoning
    raise ValueError("Workflow model tool call limit reached.")


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
    content, usage, _reasoning = await _invoke_chat(
        scope, model, messages, remaining_model_tokens
    )
    return content, usage


def _condition(left: Any, operator: str, right: Any) -> bool:
    if operator == "is_null":
        return left is None or left == "" or left == [] or left == {}
    if operator == "is_not_null":
        return not (left is None or left == "" or left == [] or left == {})
    if operator in {"contain", "not_contain"}:
        target = str(right)
        if isinstance(left, list):
            matched = any(str(item) == target for item in left)
        else:
            matched = target in str(left)
        return matched if operator == "contain" else not matched
    if operator == "eq":
        return str(left) == str(right)
    if operator == "not_eq":
        return str(left) != str(right)
    if operator in {"ge", "gt", "le", "lt"}:
        try:
            ordered_left: Any = float(left)
            ordered_right: Any = float(right)
        except (TypeError, ValueError):
            ordered_left, ordered_right = str(left), str(right)
        if operator == "ge":
            return ordered_left >= ordered_right
        if operator == "gt":
            return ordered_left > ordered_right
        if operator == "le":
            return ordered_left <= ordered_right
        return ordered_left < ordered_right
    if operator.startswith("len_"):
        if not isinstance(left, (str, list, dict)):
            raise ValueError(
                "Workflow length condition requires a string, array, or object."
            )
        try:
            length = int(right)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Workflow length condition requires a non-negative integer."
            ) from exc
        if length < 0:
            raise ValueError(
                "Workflow length condition requires a non-negative integer."
            )
        if operator == "len_eq":
            return len(left) == length
        if operator == "len_ge":
            return len(left) >= length
        if operator == "len_gt":
            return len(left) > length
        if operator == "len_le":
            return len(left) <= length
        if operator == "len_lt":
            return len(left) < length
    if operator == "is_true":
        return left is True
    if operator == "is_not_true":
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
        StartNodeConfig.model_validate(config)
        question = scope.run.goal or ""
        files = context.workflow_inputs.get("files", []) or []
        return NodeResult(
            inputs={"question": question},
            outputs={
                "files": files,
                "question": question,
                **context.globals,
            },
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
    if node_type == "reply-node":
        parsed = ReplyNodeConfig.model_validate(config)
        if parsed.reply_type == "referencing":
            path, description = parsed.fields or ([], "")
            answer = str(resolve_value("{{" + ".".join(path) + "}}", context))
            inputs = {"fields": [path, description]}
        else:
            answer = render_reply_template(parsed.content, context)
            inputs = {"content": parsed.content}
        return NodeResult(inputs=inputs, outputs={"answer": answer})
    if node_type == "condition":
        parsed = ConditionNodeConfig.model_validate(config)
        selected = None
        resolved_conditions = []
        for branch in parsed.branch:
            if branch.type == "ELSE":
                selected = branch
                break
            matches = []
            for rule in branch.conditions:
                left = resolve_value(
                    f"{{{{{rule.field[0]}.{rule.field[1]}}}}}", context
                )
                right = resolve_value(rule.value, context)
                matched = _condition(left, rule.compare, right)
                matches.append(matched)
                resolved_conditions.append(
                    {
                        "branch_id": branch.id,
                        "field": list(rule.field),
                        "compare": rule.compare,
                        "value": right,
                        "matched": matched,
                    }
                )
            if (branch.condition == "and" and all(matches)) or (
                branch.condition == "or" and any(matches)
            ):
                selected = branch
                break
        if selected is None:
            raise ValueError("Workflow condition did not match a branch.")
        return NodeResult(
            inputs={"conditions": resolved_conditions},
            outputs={"branch_name": selected.type},
            selected_handles=frozenset({selected.id}),
        )
    if node_type == "llm":
        parsed = LlmNodeConfig.model_validate(config)
        prompt = str(resolve_value(parsed.prompt, context))
        system_prompt = str(resolve_value(parsed.system_prompt, context))
        model_id = parsed.model_id or scope.run.model_id
        model = scope.models.get(model_id)
        if model is None:
            raise ValueError("Workflow model is unavailable.")
        if context.remaining_model_tokens <= 0:
            raise ValueError("Workflow model token budget exceeded.")
        messages: list[Any] = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.extend(_history_messages(parsed, scope, node, context))
        messages.append(HumanMessage(content=prompt))
        call_params = _model_call_params(
            model.provider_type,
            parsed.model_params_setting,
            context.remaining_model_tokens,
        )
        tools: list[StructuredTool] = []
        if parsed.mcp_enable:
            for reference in parsed.mcp_servers:
                resolved = scope.mcp_tools.get(
                    (reference.server_id, reference.tool_name)
                )
                if resolved is None:
                    raise ValueError(
                        "Workflow MCP tool is unavailable or not read-only."
                    )
                tools.append(
                    build_mcp_agent_tool(resolved[0], scope.settings, "read_only")
                )
        async def emit_output_delta(delta: str) -> None:
            assert scope.output_delta is not None
            await scope.output_delta(node.id, delta)

        on_delta = emit_output_delta if parsed.is_result and scope.output_delta else None
        if tools:
            content, usage, reasoning = await _model_tool_loop(
                scope,
                node,
                model,
                messages,
                context.remaining_model_tokens,
                call_params,
                tools,
                on_delta,
            )
        else:
            content, usage, reasoning = await _invoke_chat(
                scope,
                model,
                messages,
                context.remaining_model_tokens,
                call_params,
                on_delta,
            )
        outputs: dict[str, Any] = {"text": content}
        if parsed.model_setting.reasoning_content_enable and reasoning:
            outputs["reasoning_content"] = reasoning
        return NodeResult(
            inputs={
                "prompt": prompt,
                "system_prompt": system_prompt,
                "model_id": model_id,
                "dialogue_type": parsed.dialogue_type,
                "dialogue_number": parsed.dialogue_number,
                "mcp_enable": parsed.mcp_enable,
            },
            outputs=outputs,
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
    if node_type == "reranker-node":
        parsed = RerankerNodeConfig.model_validate(config)
        query = str(resolve_value(parsed.question_reference_address, context))
        candidates, texts = _reranker_candidates(
            resolve_value(parsed.reranker_reference_list, context)
        )
        model = scope.models.get(parsed.reranker_model_id)
        if model is None or model.model_type != "RERANKER":
            raise ValueError("Workflow reranker model is unavailable.")
        results = await asyncio.to_thread(
            build_reranker(scope.settings, model).rerank,
            query,
            texts,
        )
        ranked: list[tuple[int, float]] = []
        for fallback_index, item in enumerate(results):
            if not isinstance(item, dict):
                continue
            index = item.get("index", fallback_index)
            score = item.get("relevance_score", 0)
            if (
                isinstance(index, int)
                and 0 <= index < len(candidates)
                and isinstance(score, (int, float))
                and not isinstance(score, bool)
                and math.isfinite(float(score))
                and float(score) >= parsed.reranker_setting.similarity
            ):
                ranked.append((index, float(score)))
        ranked.sort(key=lambda item: item[1], reverse=True)
        selected: list[dict[str, Any]] = []
        selected_indexes: set[int] = set()
        total_chars = 0
        for index, score in ranked:
            if index in selected_indexes:
                continue
            text = texts[index]
            remaining = parsed.reranker_setting.max_paragraph_char_number - total_chars
            if remaining <= 0 or len(selected) >= parsed.reranker_setting.top_n:
                break
            content = text[:remaining]
            source = candidates[index]
            selected.append(
                {
                    **(source if isinstance(source, dict) else {}),
                    "content": content,
                    "similarity": score,
                }
            )
            selected_indexes.add(index)
            total_chars += len(content)
        return NodeResult(
            inputs={
                "question": query,
                "candidate_count": len(candidates),
                "reranker_model_id": parsed.reranker_model_id,
            },
            outputs={
                "result_list": selected,
                "result": "\n\n".join(item["content"] for item in selected),
            },
        )
    if node_type == "form-node":
        parsed = FormNodeConfig.model_validate(config)
        submitted = scope.form_submissions.get(node.id)
        if submitted is None:
            pending = {
                "runtime_node_id": node.id,
                "content": render_form_template(parsed.form_content_format, context),
                "fields": [
                    field.model_dump(mode="json") for field in parsed.form_field_list
                ],
            }
            return NodeResult(inputs=pending, interrupt=pending)
        result = json.dumps(submitted, ensure_ascii=False, separators=(",", ":"))
        return NodeResult(
            inputs={"form_data": submitted},
            outputs={**submitted, "form_data": submitted, "result": result},
        )
    if node_type == "document-extract-node":
        parsed = DocumentExtractNodeConfig.model_validate(config)
        resolved = resolve_value(parsed.document_list, context)
        documents = resolved if isinstance(resolved, list) else [resolved]
        sections: list[str] = []
        for item in documents:
            if not isinstance(item, dict) or not (item.get("file_id") or item.get("id")):
                raise ValueError("Workflow document references must contain a file id.")
            content = item.get("content")
            if not isinstance(content, str):
                raise ValueError("Workflow document content is unavailable.")
            name = str(item.get("name") or item.get("filename") or "document")
            sections.append(f"--- {name} ---\n{content}")
        return NodeResult(
            inputs={"document_count": len(documents)},
            outputs={"content": "\n\n".join(sections)},
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
        result = await tool.ainvoke(
            {
                "query": query,
                "limit": parsed.limit,
                "search_mode": parsed.search_mode,
                "similarity": parsed.similarity,
            }
        )
        if result.is_error:
            raise RuntimeError(result.summary)
        output = result.output if isinstance(result.output, dict) else {"content": result.content}
        hits = output.get("hits")
        selected_hits = hits[: parsed.limit] if isinstance(hits, list) else []
        paragraph_list = []
        for item in selected_hits:
            if not isinstance(item, dict):
                continue
            paragraph = {
                "knowledge_base": str(item.get("knowledge_base") or ""),
                "document": str(item.get("document") or ""),
                "chunk_id": str(item.get("chunk_id") or ""),
                "document_id": str(item.get("document_id") or ""),
                "content": str(item.get("content") or ""),
                "distance": item.get("distance"),
                "similarity": item.get("similarity"),
            }
            trace_id = item.get("trace_id")
            if isinstance(trace_id, str) and trace_id:
                paragraph["trace_id"] = trace_id[:64]
            rerank_status = item.get("rerank_status")
            if rerank_status in {"not_configured", "applied", "fallback", "skipped"}:
                paragraph["rerank_status"] = rerank_status
            sources = item.get("sources")
            if isinstance(sources, list):
                paragraph["sources"] = [
                    source
                    for source in sources[:3]
                    if source in {"vector", "keywords", "reference"}
                ]
            reference_hops = item.get("reference_hops")
            if (
                isinstance(reference_hops, int)
                and not isinstance(reference_hops, bool)
                and 0 <= reference_hops <= 1
            ):
                paragraph["reference_hops"] = reference_hops
            paragraph_list.append(paragraph)
        # 达到检索相似度阈值的向量命中视为可直接回答（MaxKB 的分段级
        # hit_handling_method 元数据在 NexaFlow 中不存在，故以节点阈值为准）
        is_hit_handling_method_list = [
            item
            for item in paragraph_list
            if isinstance(item["similarity"], (int, float))
            and not isinstance(item["similarity"], bool)
            and item["similarity"] >= parsed.similarity
        ]
        joined = "\n\n".join(
            item["content"] for item in paragraph_list if item["content"]
        )
        direct_joined = "\n\n".join(
            item["content"]
            for item in is_hit_handling_method_list
            if item["content"]
        )
        outputs = {
            **output,
            "hits": selected_hits,
            "paragraph_list": paragraph_list,
            "is_hit_handling_method_list": is_hit_handling_method_list,
            "data": joined[: parsed.max_paragraph_char_number],
            "directly_return": direct_joined,
            "content": joined,
        }
        return NodeResult(
            inputs={
                "query": query,
                "knowledge_base_ids": parsed.resolved_knowledge_base_ids,
                "limit": parsed.limit,
                "search_mode": parsed.search_mode,
                "similarity": parsed.similarity,
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
