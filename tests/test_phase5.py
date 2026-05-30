"""Fast pytest coverage for phase 5 engineering/experience helpers.

These tests avoid LLM and network calls; they cover the streaming normalization
layer, routing helpers, SSE formatting, and CBA passage rendering.
"""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("LLM_MODEL_ID", "test-model")
os.environ.setdefault("LLM_BASE_URL", "http://localhost/v1")

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, AIMessageChunk

from nba_agent.agents.state import _merge_dicts, _replace_list
from nba_agent.flow import astream_normalized_events, normalize_graph_event
from nba_agent.graph import route_next
from nba_agent.server import _sse_event


def test_route_next_follows_plan_order_and_finalizes() -> None:
    assert route_next({"plan": ["data", "salary"], "visited": []}) == "data"
    assert route_next({"plan": ["data", "salary"], "visited": ["data"]}) == "salary"
    assert route_next({"plan": ["data"], "visited": ["data"]}) == "finalize"


def test_state_reducers_support_incremental_updates_and_reset() -> None:
    assert _merge_dicts({"data": "old"}, {"salary": "new"}) == {
        "data": "old",
        "salary": "new",
    }
    assert _merge_dicts({"data": "old"}, {"__reset__": True}) == {}
    assert _replace_list(["data"], ["data", "news"]) == ["data", "news"]
    assert _replace_list(["data"], None) == ["data"]


def test_normalize_graph_event_maps_plan_agents_and_finalize_tokens() -> None:
    plan_events = normalize_graph_event({
        "event": "on_chain_end",
        "name": "supervisor",
        "data": {"output": {"plan": ["data", "analysis"], "plan_reasoning": "need stats"}},
    })
    assert plan_events == [{
        "type": "plan",
        "plan": ["data", "analysis"],
        "reasoning": "need stats",
    }]

    start_events = normalize_graph_event({"event": "on_chain_start", "name": "data", "data": {}})
    assert start_events[0]["type"] == "agent_start"
    assert start_events[0]["agent"] == "data"

    token_events = normalize_graph_event({
        "event": "on_chat_model_stream",
        "name": "ChatOpenAI",
        "metadata": {"langgraph_node": "finalize"},
        "data": {"chunk": AIMessageChunk(content="答案")},
    })
    assert token_events == [{"type": "answer_delta", "content": "答案"}]

    final_events = normalize_graph_event({
        "event": "on_chain_end",
        "name": "finalize",
        "data": {"output": {"messages": [AIMessage(content="完整答案")]}},
    })
    assert final_events == [{"type": "answer", "content": "完整答案"}]


def test_astream_normalized_events_falls_back_to_final_answer() -> None:
    class FakeGraph:
        async def astream_events(self, _state, config=None, version="v2"):
            yield {
                "event": "on_chain_end",
                "name": "supervisor",
                "data": {"output": {"plan": ["data"], "plan_reasoning": "stats"}},
            }
            yield {
                "event": "on_chain_end",
                "name": "finalize",
                "data": {"output": {"messages": [AIMessage(content="最终回答")]}},
            }

    async def collect():
        return [
            event
            async for event in astream_normalized_events(FakeGraph(), "湖人如何？", "t1")
        ]

    events = asyncio.run(collect())
    assert events[0]["type"] == "plan"
    assert {"type": "answer_delta", "content": "最终回答"} in events
    assert events[-1] == {"type": "done", "thread_id": "t1"}


def test_sse_event_keeps_multiline_payload_parseable() -> None:
    assert _sse_event("answer", "第一行\n第二行") == "event: answer\ndata: 第一行\\n第二行\n\n"


def test_query_cba_rule_renders_citations(monkeypatch) -> None:
    from nba_agent.rag.cba import tool as cba_tool

    def fake_retrieve(_question: str, top_k: int = 5):
        return [
            Document(
                page_content="A Qualifying Veteran Free Agent keeps Bird rights after three seasons.",
                metadata={"article": "I", "section": "1", "page": 31, "source": "2023_NBA_CBA"},
            )
        ]

    monkeypatch.setattr(cba_tool, "retrieve", fake_retrieve)
    result = cba_tool.query_cba_rule.invoke({
        "question": "Bird rights test unique phase5",
        "top_k": 1,
    })

    assert "Article I" in result
    assert "Section 1" in result
    assert "Page 31" in result
    assert "Qualifying Veteran Free Agent" in result
