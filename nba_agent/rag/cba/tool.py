"""query_cba_rule：CBA 条款 RAG 工具。"""
from __future__ import annotations

import json

from langchain_core.tools import tool
from loguru import logger
from pydantic import BaseModel, Field

from ...tools.base import safe_tool, with_cache
from .retriever import retrieve


class CBAQueryInput(BaseModel):
    question: str = Field(
        ...,
        description=(
            "想查询的 CBA 条款相关问题，可中英文混合。"
            "例如：'什么是 Bird Rights？Bird 权要满足什么条件？'、"
            "'non-taxpayer mid-level exception 上限多少？'、"
            "'Apron 触发后有哪些限制？'"
        ),
    )
    top_k: int = Field(default=5, ge=1, le=10, description="返回最相关的 k 条原文片段，默认 5。")


@tool("query_cba_rule", args_schema=CBAQueryInput)
@safe_tool
@with_cache(tool_name="query_cba_rule", ttl_seconds=24 * 60 * 60)
def query_cba_rule(question: str, top_k: int = 5) -> str:
    """检索 2023 NBA CBA 协议原文，回答任何关于：
    - 薪资规则（工资帽、奢侈税、Apron、硬上限）
    - 各种 Exception（MLE / BAE / 退伍军人最低 / 双向合同 / Exhibit 10）
    - 自由球员（Bird / Early Bird / Non-Bird / 签换 / Qualifying Offer）
    - 交易限制（薪资匹配、Apron 触发后限制、签换限制）
    - 选秀、合同长度、保障类型等
    的问题。

    返回 N 条原文片段，每条带 (Article / Section / Page) 引用。
    SalaryAgent 在回答规则类问题时必须以这里返回的片段为依据，禁止凭记忆。
    """
    logger.info("[query_cba_rule] {}", question)
    docs = retrieve(question, top_k=top_k)
    if not docs:
        return json.dumps({"error": "在 CBA 协议中未找到相关条款"}, ensure_ascii=False)

    passages = []
    for d in docs:
        meta = d.metadata
        passages.append({
            "text": d.page_content.strip(),
            "article": meta.get("article", "?"),
            "section": meta.get("section", "?"),
            "page": meta.get("page", "?"),
            "source": meta.get("source", "2023_NBA_CBA"),
        })

    out = ["以下是 CBA 协议检索到的相关条款（**回答时请引用 Article / Section / Page**）："]
    for i, p in enumerate(passages, 1):
        out.append(
            f"\n--- 片段 {i} (Article {p['article']}, Section {p['section']}, Page {p['page']}) ---\n"
            f"{p['text']}"
        )
    return "\n".join(out)
