"""FastAPI 后端：为 NBA Agent 提供 HTTP + SSE 交互接口。

端点：
    GET  /            → 前端页面
    POST /api/chat    → 同步对话（等待完整回答）
    GET  /api/stream  → SSE 流式对话（实时推送进度 + 最终回答）
    POST /api/history → 获取指定 thread 的对话历史
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage, HumanMessage
from loguru import logger

from .agents import NBAState
from .config import DATA_DIR, ensure_dirs
from .graph import build_graph

# ── 应用实例 ──────────────────────────────────────────────

app = FastAPI(title="NBA Agent", version="1.0.0")

# 静态文件（前端页面）
_STATIC_DIR = DATA_DIR.parent / "nba_agent" / "static"

# 全局 graph 实例（延迟初始化）
_graph = None


def _get_graph():
    """懒加载 graph 实例，避免 import 时就初始化 LLM。"""
    global _graph
    if _graph is None:
        ensure_dirs()
        _graph = build_graph(use_checkpointer=True)
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

    graph = _get_graph()
    config = {"configurable": {"thread_id": thread_id}}

    # 在线程池中执行阻塞的 graph.invoke
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: graph.invoke(
            {
                "messages": [HumanMessage(content=query)],
                "user_query": query,
                "visited": [],
                "facts": {},
            },
            config=config,
        ),
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
    graph = _get_graph()
    config = {"configurable": {"thread_id": tid}}

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # 1. 发送 plan 信息（先跑 supervisor，单独获取 plan）
            yield _sse_event("status", "Supervisor 正在分析问题...")

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: graph.invoke(
                    {
                        "messages": [HumanMessage(content=query)],
                        "user_query": query,
                        "visited": [],
                        "facts": {},
                    },
                    config=config,
                ),
            )

            plan = result.get("plan", [])
            visited = result.get("visited", [])
            answer = result["messages"][-1].content if result.get("messages") else ""

            # 2. 发送 plan
            if plan:
                yield _sse_event("plan", json.dumps({
                    "plan": plan,
                    "reasoning": result.get("plan_reasoning", ""),
                }, ensure_ascii=False))

            # 3. 发送每个 agent 的完成状态
            agent_labels = {
                "data": "数据查询",
                "news": "资讯搜索",
                "salary": "薪资查询",
                "analysis": "深度分析",
            }
            for agent_name in visited:
                label = agent_labels.get(agent_name, agent_name)
                yield _sse_event("agent_done", json.dumps({
                    "agent": agent_name,
                    "label": label,
                }, ensure_ascii=False))

            # 4. 发送最终回答（分段模拟流式效果）
            if answer:
                # 将回答按段落分割，逐段发送
                chunks = _split_answer(answer)
                for chunk in chunks:
                    yield _sse_event("answer", chunk)
                    await asyncio.sleep(0.03)
            else:
                yield _sse_event("answer", "抱歉，本次没有获取到有效结果。")

            # 5. 完成
            yield _sse_event("done", json.dumps({"thread_id": tid}, ensure_ascii=False))

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

    graph = _get_graph()
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
    # 转义 data 中的换行符
    safe_data = data.replace("\n", "\\n")
    return f"event: {event}\ndata: {safe_data}\n\n"


def _split_answer(text: str) -> list[str]:
    """将长文本按段落分割，模拟流式推送效果。"""
    if len(text) <= 50:
        return [text]

    chunks = []
    remaining = text
    while remaining:
        # 尝试在换行符处分割，每次约 80-200 字符
        split_at = min(200, len(remaining))
        if split_at < len(remaining):
            # 找最近的换行符
            nl_pos = remaining[:split_at + 50].rfind("\n")
            if nl_pos > 30:
                split_at = nl_pos + 1
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    return chunks
