"""阶段 3 端到端 smoke test（共用单个 graph 实例避免重复构图）。"""
import sys
import time

for s in ("stdout", "stderr"):
    st = getattr(sys, s, None)
    if st and hasattr(st, "reconfigure"):
        try:
            st.reconfigure(encoding="utf-8")
        except Exception:
            pass

from loguru import logger
from langchain_core.messages import HumanMessage

from nba_agent.graph import build_graph


logger.remove()
logger.add(sys.stderr, level="INFO", format="[{level}] {message}")

CASES = [
    ("纯数据 (data)", "湖人最近 5 场战绩怎么样？", ["data"]),
    ("混合 (data+salary)", "勇士的薪资情况和最近战绩如何？", None),
    ("带分析 (data+analysis)", "对比一下东契奇和约基奇本赛季的场均数据，谁的进攻更全面？", None),
]


graph = build_graph(use_checkpointer=False)
print(f"\n[setup] graph built, running {len(CASES)} cases\n")

for label, query, expected_plan in CASES:
    print(f"\n{'='*80}\n【{label}】Q: {query}\n{'='*80}")
    t0 = time.time()
    try:
        state = graph.invoke({
            "messages": [HumanMessage(content=query)],
            "user_query": query,
            "visited": [],
        })
        elapsed = time.time() - t0
        print(f">>> plan      = {state.get('plan')}")
        print(f">>> reasoning = {state.get('plan_reasoning', '')[:160]}")
        print(f">>> visited   = {state.get('visited')}")
        print(f">>> facts keys= {list(state.get('facts', {}).keys())}")
        print(f">>> elapsed   = {elapsed:.1f}s")
        if expected_plan and state.get('plan') != expected_plan:
            print(f"  ⚠ 预期 plan={expected_plan}, 实际={state.get('plan')}")
        print(f"\n--- 最终回答 ---\n{state['messages'][-1].content}")
    except Exception as e:
        print(f"❌ {type(e).__name__}: {e}")
