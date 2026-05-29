"""HoopsHype 薪资页面抓取。

返回结构化的球员-赛季薪资表 (list of dict)。
"""
from __future__ import annotations

import io
import re
import threading
import time
from typing import Any

import pandas as pd
import requests
from loguru import logger

_HH_BASE = "https://hoopshype.com"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

_last_call = 0.0
_lock = threading.Lock()
_MIN_INTERVAL = 2.0


def _throttle() -> None:
    global _last_call
    with _lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _money_to_int(s: str) -> int | None:
    if not s or s in {"-", "—", "nan"}:
        return None
    digits = re.sub(r"[^\d]", "", str(s))
    return int(digits) if digits else None


def _is_player_option(s: str) -> bool:
    return isinstance(s, str) and s.strip().startswith("P$")


def _is_team_option(s: str) -> bool:
    return isinstance(s, str) and s.strip().startswith("T$")


def fetch_team_payroll(team_slug: str) -> dict[str, Any]:
    """从 HoopsHype 拉球队薪资页，解析每个球员每年的合同金额。

    返回:
        {
          "team_slug": "...",
          "seasons": ["2025-26", "2026-27", ...],
          "players": [{"player": "LeBron James", "salaries": {"2025-26": 52627153, ...}, "options": {...}}, ...],
          "totals": {"2025-26": ...},
        }
    """
    url = f"{_HH_BASE}/salaries/{team_slug}/"
    _throttle()
    logger.info("[hoopshype] GET {}", url)
    r = requests.get(url, headers=_UA, timeout=20)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"

    tables = pd.read_html(io.StringIO(r.text))
    target = None
    for t in tables:
        cols = [str(c) for c in t.columns]
        if "Player" in cols and any(re.match(r"^\d{4}-\d{2}$", c) for c in cols):
            target = t
            break
    if target is None:
        raise ValueError(f"未找到 {team_slug} 的薪资表")

    season_cols = [c for c in target.columns if re.match(r"^\d{4}-\d{2}$", str(c))]
    players: list[dict[str, Any]] = []
    totals: dict[str, int] = {s: 0 for s in season_cols}

    for _, row in target.iterrows():
        name = str(row.get("Player", "")).strip()
        if not name or name.lower() in {"totals", "total", "nan"}:
            continue
        sals: dict[str, int] = {}
        opts: dict[str, str] = {}
        for s in season_cols:
            val = row[s]
            amt = _money_to_int(val)
            if amt is not None:
                sals[s] = amt
                totals[s] = totals.get(s, 0) + amt
            if _is_player_option(val):
                opts[s] = "player_option"
            elif _is_team_option(val):
                opts[s] = "team_option"
        if sals:
            players.append({"player": name, "salaries": sals, "options": opts})

    return {
        "team_slug": team_slug,
        "url": url,
        "seasons": season_cols,
        "players": players,
        "totals": totals,
    }
