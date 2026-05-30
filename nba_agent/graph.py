"""LangGraph Supervisor 多 Agent 图（阶段 3）。

结构：
    START
      ↓
    supervisor (LLM 出 plan)
      ↓
    router ─→ data / news / salary / analysis  (按 plan 顺序，逐个跑)
              ↓                                    ↑
              └────── 回到 router ─────────────────┘
                                ↓
                            finalize → END

router 是无状态函数：根据 (plan, visited) 选下一个未访问的 agent；
plan 跑完后跳 finalize。
"""
from __future__ import annotations

import sqlite3

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from loguru import logger

from .agents import (
    NBAState,
    analysis_agent_node,
    data_agent_node,
    finalize_node,
    news_agent_node,
    salary_agent_node,
    supervisor_node,
)
from .config import CHECKPOINT_DB, ensure_dirs

_SUBAGENT_NAMES = ("data", "news", "salary", "analysis")


def route_next(state: NBAState) -> str:
    """路由函数：根据 plan 和已访问列表，决定下一个要执行的子 Agent。

    返回值必须与 route_map 中的 key 对应：
    - 未访问的下一个 Agent 名（"data"/"news"/"salary"/"analysis"）
    - plan 已全部执行完则返回 "finalize"
    """
    plan = state.get("plan", []) or []
    visited = set(state.get("visited", []) or [])
    remaining = [a for a in plan if a not in visited]
    next_node = remaining[0] if remaining else "finalize"
    logger.debug("[router] plan={} visited={} → {}", plan, sorted(visited), next_node)
    return next_node


def _build_builder() -> StateGraph:
    """构建未编译的 StateGraph builder（节点和边已注册完毕）。"""
    ensure_dirs()
    builder = StateGraph(NBAState)
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("data", data_agent_node)
    builder.add_node("news", news_agent_node)
    builder.add_node("salary", salary_agent_node)
    builder.add_node("analysis", analysis_agent_node)
    builder.add_node("finalize", finalize_node)

    builder.add_edge(START, "supervisor")

    route_map = {name: name for name in _SUBAGENT_NAMES}
    route_map["finalize"] = "finalize"

    builder.add_conditional_edges("supervisor", route_next, route_map)
    for name in _SUBAGENT_NAMES:
        builder.add_conditional_edges(name, route_next, route_map)

    builder.add_edge("finalize", END)
    return builder


async def build_graph_async(use_checkpointer: bool = True):
    """异步编译图，使用 AsyncSqliteSaver 支持 astream_events。"""
    import aiosqlite

    builder = _build_builder()

    if use_checkpointer:
        CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(str(CHECKPOINT_DB))
        checkpointer = AsyncSqliteSaver(conn)
        result = builder.compile(checkpointer=checkpointer)
    else:
        result = builder.compile()

    return result


def build_graph(use_checkpointer: bool = True):
    """同步编译图（兼容旧代码），使用 SqliteSaver。"""
    builder = _build_builder()

    if use_checkpointer:
        CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(CHECKPOINT_DB), check_same_thread=False)
        checkpointer = SqliteSaver(conn)
        return builder.compile(checkpointer=checkpointer)

    return builder.compile()


def run_once(user_query: str, thread_id: str = "default") -> str:
    """便捷入口：跑一次完整对话，返回最终自然语言回答。"""
    graph = build_graph()
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke(
        {
            "messages": [HumanMessage(content=user_query)],
            "user_query": user_query,
            "visited": [],
            "facts": {},
        },
        config=config,
    )
    return result["messages"][-1].content
