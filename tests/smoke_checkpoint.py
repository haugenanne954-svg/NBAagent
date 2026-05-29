"""阶段 0 烟测：确认 SqliteSaver 真的把 checkpoint 落库了。"""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "checkpoints.sqlite"

conn = sqlite3.connect(str(DB))
tables = [r[0] for r in conn.execute(
    "select name from sqlite_master where type='table'"
)]
print("tables:", tables)

if "checkpoints" in tables:
    n = conn.execute("select count(*) from checkpoints").fetchone()[0]
    print("checkpoints rows:", n)
    if n:
        sample = conn.execute(
            "select thread_id, checkpoint_id from checkpoints limit 3"
        ).fetchall()
        print("sample:", sample)
