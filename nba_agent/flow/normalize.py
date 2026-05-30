"""Normalize LangGraph event dictionaries into UI/CLI friendly flow events."""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage


SUBAGENT_LABELS = {
    "data": "数据查询",
    "news": "资讯搜索",
    "salary": "薪资查询",
    "analysis": "深度分析",
}

_SUBAGENT_NAMES = set(SUBAGENT_LABELS)


def _event_node_name(event: dict[str, Any]) -> str:
    """Best-effort LangGraph node name extraction from a raw event."""
    metadata = event.get("metadata") or {}
    return str(metadata.get("langgraph_node") or event.get("name") or "")


def _message_content(message: Any) -> str:
    """Extract text content from AIMessage/AIMessageChunk-like objects."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _last_ai_content(output: Any) -> str:
    """Find the last AI message content in a LangGraph node output."""
    if not isinstance(output, dict):
        return ""
    messages = output.get("messages") or []
    for message in reversed(messages):
        if isinstance(message, AIMessage) or message.__class__.__name__ in {"AIMessage", "AIMessageChunk"}:
            text = _message_content(message)
            if text:
                return text
    return ""


def normalize_graph_event(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert one raw ``graph.astream_events`` event into zero or more flow events.

    The returned events are intentionally small and stable so both terminal output
    and the FastAPI SSE endpoint can consume the same stream.
    """
    kind = event.get("event")
    node = _event_node_name(event)
    data = event.get("data") or {}
    normalized: list[dict[str, Any]] = []

    if kind == "on_chain_start" and node in _SUBAGENT_NAMES:
        normalized.append({
            "type": "agent_start",
            "agent": node,
            "label": SUBAGENT_LABELS[node],
        })

    if kind == "on_chain_end":
        output = data.get("output") or {}
        if node == "supervisor" and isinstance(output, dict):
            plan = output.get("plan") or []
            if plan:
                normalized.append({
                    "type": "plan",
                    "plan": plan,
                    "reasoning": output.get("plan_reasoning", ""),
                })
        elif node in _SUBAGENT_NAMES:
            normalized.append({
                "type": "agent_done",
                "agent": node,
                "label": SUBAGENT_LABELS[node],
            })
        elif node == "finalize":
            answer = _last_ai_content(output)
            if answer:
                normalized.append({"type": "answer", "content": answer})

    if kind == "on_chat_model_stream" and node == "finalize":
        text = _message_content(data.get("chunk"))
        if text:
            normalized.append({"type": "answer_delta", "content": text})

    return normalized
