"""阶段 4 端到端 smoke：4 类高阶分析 query。"""
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
    ("战术分析", "雷霆这赛季为什么防守这么强？分析一下他们的打法"),
    ("球队对比", "对比一下雷霆和马刺这赛季，谁的攻防风格更均衡？"),
    ("比赛预测", "假设今晚雷霆对阵湖人在 OKC 主场，谁会赢？给个预测"),
    ("交易评估", "假设湖人用 Austin Reaves + Rui Hachimura 换鹈鹕的 Trey Murphy III，这笔交易合不合理？双方都受益吗？"),
]


graph = build_graph(use_checkpointer=False)
print(f"\n[setup] graph built, running {len(CASES)} cases\n")

for label, query in CASES:
    print(f"\n{'='*82}\n【{label}】Q: {query}\n{'='*82}")
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
        print(f"\n--- 最终回答 ---\n{state['messages'][-1].content}")
    except Exception as e:
        import traceback
        print(f"❌ {type(e).__name__}: {e}")
        traceback.print_exc()
