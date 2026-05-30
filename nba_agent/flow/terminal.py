"""Terminal rendering helpers for normalized flow events."""
from __future__ import annotations

import sys
from typing import Any, TextIO


def format_flow_event(event: dict[str, Any]) -> str:
    """Return a compact human-readable string for a normalized flow event."""
    event_type = event.get("type")

    if event_type == "status":
        return str(event.get("message", ""))

    if event_type == "plan":
        plan = " -> ".join(str(x) for x in event.get("plan", []))
        reasoning = event.get("reasoning") or ""
        suffix = f" ({reasoning})" if reasoning else ""
        return f"[plan] {plan}{suffix}"

    if event_type == "agent_start":
        return f"[{event.get('label') or event.get('agent')}] 开始"

    if event_type == "agent_done":
        return f"[{event.get('label') or event.get('agent')}] 完成"

    if event_type == "done":
        thread_id = event.get("thread_id")
        return f"[done] thread_id={thread_id}" if thread_id else "[done]"

    if event_type == "error":
        return f"[error] {event.get('message', '')}"

    if event_type in {"answer_delta", "answer"}:
        return str(event.get("content", ""))

    return str(event)


def emit_flow_event(event: dict[str, Any], stream: TextIO | None = None) -> None:
    """Print one normalized event to a terminal stream."""
    out = stream or sys.stdout
    event_type = event.get("type")
    text = format_flow_event(event)
    if not text:
        return

    if event_type == "answer_delta":
        print(text, end="", file=out, flush=True)
    elif event_type == "answer":
        print(text, file=out, flush=True)
    else:
        print(text, file=out, flush=True)
