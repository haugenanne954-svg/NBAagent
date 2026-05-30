"""FastAPI 后端：为 NBA Agent 提供 HTTP + SSE 交互接口。

端点：
    GET  /            → 前端页面
    POST /api/chat    → 同步对话（等待完整回答）
    GET  /api/stream  → SSE 流式对话（实时推送进度 + 最终回答）
    POST /api/history → 获取指定 thread 的对话历史
"""
from __future__ import annotations

import json
import uuid
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from langchain_core.messages import HumanMessage
from loguru import logger

from .agents import NBAState
from .config import DATA_DIR, ensure_dirs
from .flow import astream_normalized_events
from .graph import build_graph_async

# ── 应用实例 ──────────────────────────────────────────────

app = FastAPI(title="NBA Agent", version="1.0.0")

# 静态文件（前端页面）
_STATIC_DIR = DATA_DIR.parent / "nba_agent" / "static"

# 全局 graph 实例（延迟初始化）
_graph = None


async def _get_graph():
    """懒加载 graph 实例（异步），使用 AsyncSqliteSaver 支持 SSE 流式。"""
    global _graph
    if _graph is None:
        ensure_dirs()
        _graph = await build_graph_async(use_checkpointer=True)
    return _graph


# ── 前端页面 ──────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    """返回前端交互页面。"""
    html_path = _STATIC_DIR / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


# ── 同步对话 ──────────────────────────────────────────────

@app.post("/api/chat")
async def chat(request: Request):
    """同步对话接口：等待 Agent 完成全部推理后返回最终回答。

    请求体：
        {"query": "湖人最近怎么样？", "thread_id": "可选，默认自动生成"}
    """
    body = await request.json()
    query = body.get("query", "").strip()
    thread_id = body.get("thread_id") or f"web-{uuid.uuid4().hex[:8]}"

    if not query:
        return {"error": "query 不能为空"}

    # 使用 graph.ainvoke 异步执行
    graph = await _get_graph()
    config = {"configurable": {"thread_id": thread_id}}
    result = await graph.ainvoke(
        {
            "messages": [HumanMessage(content=query)],
            "user_query": query,
            "visited": [],
            "facts": {},
        },
        config=config,
    )

    answer = result["messages"][-1].content if result.get("messages") else ""
    plan = result.get("plan", [])
    visited = result.get("visited", [])

    return {
        "answer": answer,
        "thread_id": thread_id,
        "plan": plan,
        "visited": visited,
    }


# ── SSE 流式对话 ──────────────────────────────────────────

@app.get("/api/stream")
async def stream(query: str, thread_id: str | None = None):
    """SSE 流式对话接口：实时推送 Agent 执行进度和最终回答。

    事件类型：
        - plan:       Supervisor 输出的执行计划
        - agent_start: 子 Agent 开始执行
        - agent_done:  子 Agent 执行完成
        - answer:      最终回答（分段推送）
        - done:        全部完成
        - error:       错误信息
    """
    if not query or not query.strip():
        return StreamingResponse(
            _sse_event("error", "query 不能为空"),
            media_type="text/event-stream",
        )

    tid = thread_id or f"web-{uuid.uuid4().hex[:8]}"
    graph = await _get_graph()

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            yield _sse_event("status", "Supervisor 正在分析问题...")
            async for event in astream_normalized_events(graph, query.strip(), thread_id=tid):
                event_type = event.get("type")
                if event_type == "plan":
                    yield _sse_event("plan", json.dumps({
                        "plan": event.get("plan", []),
                        "reasoning": event.get("reasoning", ""),
                    }, ensure_ascii=False))
                elif event_type == "agent_start":
                    yield _sse_event("agent_start", json.dumps({
                        "agent": event.get("agent"),
                        "label": event.get("label"),
                    }, ensure_ascii=False))
                elif event_type == "agent_done":
                    yield _sse_event("agent_done", json.dumps({
                        "agent": event.get("agent"),
                        "label": event.get("label"),
                    }, ensure_ascii=False))
                elif event_type == "answer_delta":
                    yield _sse_event("answer", str(event.get("content", "")))
                elif event_type == "done":
                    yield _sse_event("done", json.dumps({"thread_id": tid}, ensure_ascii=False))
                elif event_type == "error":
                    yield _sse_event("error", str(event.get("message", "")))

        except Exception as e:
            logger.exception("[stream] error")
            yield _sse_event("error", str(e))

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── 对话历史 ──────────────────────────────────────────────

@app.post("/api/history")
async def history(request: Request):
    """获取指定 thread_id 的对话历史。

    请求体：
        {"thread_id": "xxx"}
    """
    body = await request.json()
    thread_id = body.get("thread_id", "")
    if not thread_id:
        return {"error": "thread_id 不能为空"}

    graph = await _get_graph()
    config = {"configurable": {"thread_id": thread_id}}

    try:
        state = graph.get_state(config)
        messages = state.values.get("messages", [])
        history = []
        for m in messages:
            role = "user" if isinstance(m, HumanMessage) else "assistant"
            history.append({"role": role, "content": m.content})
        return {"thread_id": thread_id, "messages": history}
    except Exception as e:
        logger.warning("[history] error: {}", e)
        return {"thread_id": thread_id, "messages": []}


# ── 工具函数 ──────────────────────────────────────────────

def _sse_event(event: str, data: str) -> str:
    """格式化一个 SSE 事件。"""
    # 前端当前按单行 data 解析，这里保留既有约定，避免多行 markdown 被截断。
    safe_data = data.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
    return f"event: {event}\ndata: {safe_data}\n\n"
