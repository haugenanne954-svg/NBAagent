"""DataAgent / NewsAgent / SalaryAgent / AnalysisAgent 节点工厂。

每个 sub-agent：
- 用 create_react_agent 包装自己的工具子集（AnalysisAgent 不挂工具）
- 节点入口构建简洁的 messages：HumanMessage(user_query + 前置 facts 摘要)
- 节点出口把 final AI message 写入 state.facts[agent_name]
- 把自己加入 state.visited
"""
from __future__ import annotations

from typing import Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
from loguru import logger

from ..llm import get_llm
from ..prompts import (
    build_analysis_agent_prompt,
    build_data_agent_prompt,
    build_news_agent_prompt,
    build_salary_agent_prompt,
)
from ..tools import (
    DATA_TOOLS,
    NEWS_TOOLS,
    RAG_TOOLS,
    SALARY_TOOLS,
)


def _format_prior_facts(facts: dict[str, str], skip: str) -> str:
    """渲染 facts 给当前 sub-agent 当作上下文。"""
    other = {k: v for k, v in facts.items() if k != skip and v}
    if not other:
        return ""
    parts = ["【前置 Agent 已经查到的事实，**直接引用，不要重复查**】"]
    for name, content in other.items():
        parts.append(f"\n--- 来自 {name}Agent ---\n{content}")
    return "\n".join(parts)


def _make_react_subagent(
    name: str,
    tools: list,
    prompt_builder: Callable[[], str],
) -> Callable[[dict], dict]:
    """工厂：返回一个 LangGraph 节点函数，内部包了一个 react agent。

    每次调用节点都重新渲染 prompt 和构造 react agent，
    避免长进程里日期被冻结、tool 列表被冻结。

    Args:
        name: Agent 名称（如 "data"），同时作为 facts 的 key
        tools: 该 Agent 可调用的 LangChain 工具列表
        prompt_builder: 无参函数，返回当前时间渲染后的 system prompt

    Returns:
        节点函数，接收 state dict，返回 {"facts": {name: 输出}, "visited": [..., name]}
    """
    llm = get_llm(temperature=0.0, streaming=False)

    def node(state: dict) -> dict:
        user_query = state.get("user_query") or ""
        facts = state.get("facts", {}) or {}
        # 将前置 Agent 的 facts 作为上下文注入，避免重复查询
        prior = _format_prior_facts(facts, skip=name)

        agent = create_react_agent(
            model=llm,
            tools=tools,
            prompt=prompt_builder(),
        )

        msgs = []
        if prior:
            msgs.append(SystemMessage(content=prior))
        msgs.append(HumanMessage(content=user_query))

        logger.info("[{}Agent] start  prior_facts_keys={}  query='{}'", name, list(facts), user_query[:60])
        result = agent.invoke({"messages": msgs})

        # 取最后一条 AI 消息作为该 Agent 的输出
        final_ai = next(
            (m for m in reversed(result["messages"])
             if isinstance(m, AIMessage) and getattr(m, "content", "")),
            None,
        )
        text = final_ai.content if final_ai else "(无输出)"
        logger.info("[{}Agent] done  output_len={}", name, len(text))

        return {
            "facts": {name: text},
            "visited": [*state.get("visited", []), name],
        }

    node.__name__ = f"{name}_agent_node"
    return node


def _analysis_agent_node(state: dict) -> dict:
    """AnalysisAgent：纯分析节点，不挂任何工具，直接用 LLM 基于 facts 写分析。

    - temperature=0.3（比取数 Agent 高），允许适度推理创造性
    - 如果没有前置 Agent 提供数据，会输出缺数据提示而非编造
    """
    user_query = state.get("user_query") or ""
    facts = state.get("facts", {}) or {}
    prior = _format_prior_facts(facts, skip="analysis")

    llm = get_llm(temperature=0.3, streaming=False)
    msgs = [SystemMessage(content=build_analysis_agent_prompt())]
    if prior:
        msgs.append(SystemMessage(content=prior))
    else:
        # 无数据兜底提示，防止 LLM 凭空编造
        msgs.append(SystemMessage(content=(
            "⚠ 没有前置 Agent 提供数据。\n"
            "请如实告知用户'缺少数据无法分析'，并建议补充哪些数据。"
        )))
    msgs.append(HumanMessage(content=user_query))

    logger.info("[analysisAgent] start  prior_facts_keys={}", list(facts))
    response = llm.invoke(msgs)
    text = getattr(response, "content", "") or "(空输出)"
    logger.info("[analysisAgent] done  output_len={}", len(text))

    return {
        "facts": {"analysis": text},
        "visited": [*state.get("visited", []), "analysis"],
    }


# ── 实例化 4 个子 Agent ────────────────────────────────
# DataAgent：8 个数据查询工具
data_agent_node = _make_react_subagent("data", DATA_TOOLS, build_data_agent_prompt)
# NewsAgent：2 个资讯搜索工具
news_agent_node = _make_react_subagent("news", NEWS_TOOLS, build_news_agent_prompt)
# SalaryAgent：4 个薪资工具 + CBA RAG 工具
salary_agent_node = _make_react_subagent(
    "salary",
    [*SALARY_TOOLS, *RAG_TOOLS],
    build_salary_agent_prompt,
)
# AnalysisAgent：无工具，纯 LLM 推理
analysis_agent_node = _analysis_agent_node
