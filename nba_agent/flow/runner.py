"""Shared streaming runners for CLI and Web frontends."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

from langchain_core.messages import HumanMessage

from .normalize import normalize_graph_event

FlowCallback = Callable[[dict[str, Any]], None]


def _initial_state(query: str) -> dict[str, Any]:
    """Build the per-turn input state used by all frontends."""
    return {
        "messages": [HumanMessage(content=query)],
        "user_query": query,
        "visited": [],
        "facts": {},
    }


async def astream_normalized_events(
    graph: Any,
    query: str,
    thread_id: str = "default",
) -> AsyncIterator[dict[str, Any]]:
    """Yield normalized flow events from ``graph.astream_events``.

    If the underlying model does not emit token chunks, this function falls back
    to sending the final answer as a single ``answer_delta`` event when the
    ``finalize`` node ends.
    """
    config = {"configurable": {"thread_id": thread_id}}
    answer_streamed = False
    final_answer = ""

    try:
        async for raw_event in graph.astream_events(
            _initial_state(query),
            config=config,
            version="v2",
        ):
            for event in normalize_graph_event(raw_event):
                if event.get("type") == "answer_delta":
                    answer_streamed = True
                    yield event
                elif event.get("type") == "answer":
                    final_answer = str(event.get("content", ""))
                else:
                    yield event

        if final_answer and not answer_streamed:
            yield {"type": "answer_delta", "content": final_answer}

        yield {"type": "done", "thread_id": thread_id}
    except Exception as exc:  # noqa: BLE001
        yield {"type": "error", "message": str(exc), "thread_id": thread_id}


async def run_graph_with_flow(
    graph: Any,
    query: str,
    thread_id: str = "default",
    emit: FlowCallback | None = None,
) -> str:
    """Run a graph turn, optionally emitting normalized events, and return answer."""
    answer_parts: list[str] = []
    async for event in astream_normalized_events(graph, query, thread_id=thread_id):
        if emit:
            emit(event)
        if event.get("type") == "answer_delta":
            answer_parts.append(str(event.get("content", "")))
    return "".join(answer_parts)


def run_graph_with_flow_sync(
    graph: Any,
    query: str,
    thread_id: str = "default",
    emit: FlowCallback | None = None,
) -> str:
    """Synchronous wrapper for CLI use."""
    return asyncio.run(run_graph_with_flow(graph, query, thread_id=thread_id, emit=emit))
