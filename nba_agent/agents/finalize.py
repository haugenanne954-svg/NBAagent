"""Finalize 节点：把 facts 整合为一条干净的最终回答。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from loguru import logger

from ..llm import get_llm
from ..prompts import FINALIZE_PROMPT


def finalize_node(state: dict) -> dict:
    """Finalize 节点：将各子 Agent 的 facts 整合为一条面向用户的最终回答。

    工作流程：
    1. 收集所有 facts，按 data→news→salary→analysis 顺序排列
    2. 调用 LLM 整合为结构化的中文 markdown 回答
    3. 若 LLM 无输出，回退到第一个非空的 fact
    4. 将最终回答写入 messages（由 add_messages reducer 自动追加）
    """
    user_query = state.get("user_query") or ""
    facts = state.get("facts", {}) or {}
    visited = state.get("visited", [])

    if not facts:
        logger.warning("[finalize] no facts; passing through messages")
        return {"messages": [AIMessage(content="抱歉，本次没有从工具拿到有效结果，请换种问法或换个角度再试。")]}

    facts_block = ["【各子 Agent 输出】"]
    for name in ["data", "news", "salary", "analysis"]:
        if name in facts and facts[name]:
            facts_block.append(f"\n=== {name}Agent ===\n{facts[name]}")
    facts_text = "\n".join(facts_block)

    llm = get_llm(temperature=0.2, streaming=False)
    msgs = [
        SystemMessage(content=FINALIZE_PROMPT),
        HumanMessage(content=(
            f"用户问题：{user_query}\n\n"
            f"{facts_text}\n\n"
            "请基于上面各子 Agent 的输出，写一条**直接给用户看**的最终回答。\n"
            "要求：\n"
            "- 整合多个 Agent 的信息，不要简单拼接；\n"
            "- 保留所有数字、引用、来源；\n"
            "- 中文 markdown，结构清晰；\n"
            "- 不要重复中间思考过程；\n"
            "- 文末附数据来源（basketball-reference / Tavily / HoopsHype / 2023 NBA CBA 等，按用到的列出）。"
        )),
    ]

    response = llm.invoke(msgs)
    content = getattr(response, "content", "") or ""
    if not content:
        for name in ("analysis", "salary", "data", "news"):
            if facts.get(name):
                content = facts[name]
                break
    logger.info("[finalize] visited={}  output_len={}", visited, len(content))
    return {"messages": [AIMessage(content=content)]}
