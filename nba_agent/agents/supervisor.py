"""Supervisor 节点：LLM 看 user_query → 输出 JSON plan。"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from ..llm import get_llm
from ..prompts import build_supervisor_prompt

_VALID_AGENTS = {"data", "news", "salary", "analysis"}


def _extract_json(text: str) -> dict | None:
    """从 LLM 输出中提取 JSON 对象。

    容忍 LLM 偶尔输出的 ```json``` 代码块包裹或前后多余文字。
    """
    if not text:
        return None
    # 尝试匹配 ```json ... ``` 包裹的 JSON
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        # 尝试匹配最外层大括号
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if brace:
            text = brace.group(0)
    try:
        return json.loads(text)
    except Exception:
        return None


def _clean_plan(plan: list[Any]) -> list[str]:
    """清洗 LLM 输出的 plan 列表：去重、过滤无效名、保证 analysis 在最后。

    - 只保留 _VALID_AGENTS 中的合法 Agent 名
    - 去重（同一 Agent 只执行一次）
    - analysis 必须在最后（它依赖前置 Agent 的数据）
    """
    seen: set[str] = set()
    out: list[str] = []
    for x in plan:
        if not isinstance(x, str):
            continue
        x = x.strip().lower()
        if x not in _VALID_AGENTS or x in seen:
            continue
        seen.add(x)
        out.append(x)
    # analysis 必须排在最后（它没有工具，只看前置 facts）
    if "analysis" in out:
        out = [a for a in out if a != "analysis"] + ["analysis"]
    return out


def supervisor_node(state: dict) -> dict:
    """Supervisor 节点：分析用户问题，输出执行计划（plan）和推理。

    工作流程：
    1. 提取 user_query（优先从 state，回退到 messages）
    2. 调用 LLM 对问题做意图分类，输出 JSON plan
    3. 清洗 plan（去重/排序/兜底）
    4. 重置 facts 和 visited，开启新一轮执行
    """
    user_query = state.get("user_query") or ""
    # 兜底：从 messages 里取最近一条有内容的消息
    if not user_query:
        msgs = state.get("messages", [])
        for m in msgs:
            content = getattr(m, "content", "")
            if isinstance(content, str) and content.strip():
                user_query = content
                break

    llm = get_llm(temperature=0.0, streaming=False)
    response = llm.invoke([
        SystemMessage(content=build_supervisor_prompt()),
        HumanMessage(content=f"用户问题：{user_query}\n\n请输出 JSON。"),
    ])
    raw = (response.content or "").strip()
    parsed = _extract_json(raw)

    plan: list[str] = []
    reasoning = ""
    if parsed:
        plan = _clean_plan(parsed.get("plan", []))
        reasoning = str(parsed.get("reasoning", ""))[:200]

    # 兜底：LLM 未输出有效 plan 时默认走 data agent
    if not plan:
        plan = ["data"]
        reasoning = reasoning or "Supervisor 未能正确规划，默认走 data agent。"

    logger.info("[supervisor] plan={} reasoning={}", plan, reasoning)
    return {
        "plan": plan,
        "plan_reasoning": reasoning,
        "user_query": user_query,
        "visited": [],           # 新一轮清空已访问列表
        "facts": {"__reset__": True},  # 发送重置信号，清空旧 facts
    }
