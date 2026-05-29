"""验证 LangGraph + SqliteSaver 能跨进程恢复 thread 状态。

不再次调用 LLM，只验证 checkpoint 能取回上一轮的 messages。
"""
from nba_agent.graph import build_graph

graph = build_graph()

last_thread_id = None
import sqlite3
from nba_agent.config import CHECKPOINT_DB

conn = sqlite3.connect(str(CHECKPOINT_DB))
row = conn.execute(
    "select thread_id from checkpoints order by rowid desc limit 1"
).fetchone()
if row:
    last_thread_id = row[0]

if not last_thread_id:
    print("没有历史 thread，跳过。")
    raise SystemExit(0)

print(f"恢复 thread_id={last_thread_id} 的状态：")
snapshot = graph.get_state({"configurable": {"thread_id": last_thread_id}})
msgs = snapshot.values.get("messages", [])
print(f"  恢复到 {len(msgs)} 条消息：")
for m in msgs:
    typ = type(m).__name__
    text = (getattr(m, "content", "") or "")[:60].replace("\n", " ")
    print(f"  - [{typ}] {text}")
print(f"  visited = {snapshot.values.get('visited', [])}")
