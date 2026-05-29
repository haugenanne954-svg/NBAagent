"""LangGraph 共享状态。

阶段 3 起所有字段都有意义：
- messages: 主对话流（finalize 输出会写回这里），用 add_messages reducer 自动 append
- user_query: 本轮的原始 query（supervisor 每轮覆盖）
- plan: 本轮要跑的子 Agent 名称列表（supervisor 决定）
- plan_reasoning: supervisor 的简要推理
- facts: 每个子 Agent 跑完写一段 markdown，key=agent 名；用 _merge_dicts 累加
- citations: 引用列表
- visited: 已经跑过的子 Agent，sub-agent 节点会显式 [*old, name] append

为什么 visited 用 _replace_list 而 facts 用 _merge_dicts：
- visited 由 sub-agent 节点显式拼接（已读 state 再 return 全量），
  使用 replace 语义可以让 supervisor 每轮通过 `return {"visited": []}` 重置。
- facts 由各节点 return 单 key 增量，merge 语义最自然；
  supervisor 想清空时显式 `return {"facts": {}}`——_merge_dicts 在 new 为空 dict 时
  会保留旧字典，所以我们用一个特殊的 reset 路径：supervisor 检测到新 query 时显式
  返回 `{"facts": {}, "visited": []}`，并由 reducer 看 new 非 None 即覆盖。
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


def _merge_dicts(old: dict | None, new: dict | None) -> dict:
    """facts 字段的自定义 reducer：增量合并。

    - 普通更新：new 中的 key-value 合并到 old（同 key 覆盖）
    - 重置信号：当 new 包含 {"__reset__": True} 时，整体清空为 {}
    """
    if isinstance(new, dict) and new.get("__reset__") is True:
        return {}
    return {**(old or {}), **(new or {})}


def _replace_list(old: list | None, new: list | None) -> list:
    """visited 字段：节点 return 时全量替换（节点自己负责读取旧值再 append）。"""
    return list(new) if new is not None else (old or [])


class NBAState(TypedDict, total=False):
    """LangGraph 全局共享状态。

    字段说明：
    - messages:  主对话流，用 add_messages reducer 自动 append
    - user_query: 本轮用户原始问题（supervisor 每轮覆盖）
    - plan: Supervisor 决定的子 Agent 执行顺序
    - plan_reasoning: Supervisor 的推理过程
    - facts: 各子 Agent 输出的 markdown 结果，key=agent 名，用 _merge_dicts 增量合并
    - citations: 引用列表（预留）
    - visited: 已执行的子 Agent 列表，用 _replace_list 全量替换
    """

    messages: Annotated[list, add_messages]

    user_query: str

    plan: list[str]
    plan_reasoning: str

    facts: Annotated[dict[str, str], _merge_dicts]
    citations: list[dict[str, Any]]

    visited: Annotated[list[str], _replace_list]
