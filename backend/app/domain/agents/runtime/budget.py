"""Replaceable model feedback from the actual frozen Run execution limits."""

from datetime import UTC, datetime

from langchain_core.messages import HumanMessage

RUNTIME_STATUS_MARKER = "nexaflow_runtime_status"


def runtime_status(
    turn: int,
    max_turns: int,
    tool_calls: int,
    max_tool_calls: int,
    deadline: datetime | None,
) -> HumanMessage:
    tool_turns_left = max(0, max_turns - turn)
    calls_left = max(0, max_tool_calls - tool_calls)
    seconds = None
    if deadline is not None:
        seconds = max(0, int((deadline - datetime.now(UTC)).total_seconds()))
    text = (
        f"Runtime status: model turn {turn}/{max_turns}; "
        f"tool calls used {tool_calls}/{max_tool_calls}; "
        f"{tool_turns_left} model turns that may call tools remain, including this turn. "
    )
    if seconds is not None:
        text += f"Execution deadline in approximately {seconds} seconds. "
    if not calls_left:
        text += "The tool-call budget is exhausted. Do not call tools. "
    elif not tool_turns_left:
        text += "This is the final model turn (model-turn limit reached). Do not call tools. "
    elif (
        tool_turns_left <= min(4, max_turns // 3)
        or calls_left <= min(8, max_tool_calls // 3)
        or (seconds is not None and seconds <= 120)
    ):
        text += (
            "Prioritize completing the requested deliverable and verifying it now; "
            "avoid further optional exploration. Tools are still available within these limits. "
        )
    if not calls_left or not tool_turns_left:
        text += "Answer using the information already available and explain anything that remains incomplete."
    return HumanMessage(content=text, additional_kwargs={RUNTIME_STATUS_MARKER: True})
