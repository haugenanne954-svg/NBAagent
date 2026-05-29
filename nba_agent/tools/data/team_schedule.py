"""get_team_schedule：球队某赛季的赛程 + 赛果（常规赛 + 季后赛）。"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
from langchain_core.tools import tool
from loguru import logger
from pydantic import BaseModel, Field

from ..base import safe_tool, with_cache, with_retry
from ._bbref import clean_repeated_header, fetch_html, read_table
from ._resolver import resolve_team


def _current_bbref_season() -> int:
    """bbref 用赛季末尾年份命名；10 月切赛季。"""
    today = datetime.now()
    return today.year + 1 if today.month >= 10 else today.year


class TeamScheduleInput(BaseModel):
    team: str = Field(
        ...,
        description='球队名，可中文也可英文/缩写，如 "湖人" / "Lakers" / "LAL"。',
    )
    season: int | None = Field(
        default=None,
        description="赛季末尾年份，例如 2025-26 赛季传 2026；不填默认当前赛季。",
    )
    last_n: int = Field(
        default=10,
        ge=1,
        le=30,
        description="返回最近 N 场（按时间倒序）。",
    )
    include_playoffs: bool = Field(
        default=True,
        description="是否包含季后赛比赛。",
    )


def _format_rows(df: pd.DataFrame, label: str) -> list[str]:
    out: list[str] = []
    for _, row in df.iterrows():
        date = str(row.get("Date", "")).strip()
        opp = str(row.get("Opponent", "")).strip()
        loc = "@" if str(row.get("Unnamed: 5", "")).strip() == "@" else "vs"
        result = str(row.get("Unnamed: 7", "")).strip()
        tm = row.get("Tm", "")
        opp_pts = row.get("Opp", "")
        streak = str(row.get("Streak", "")).strip()
        try:
            tm, opp_pts = int(tm), int(opp_pts)
        except (TypeError, ValueError):
            pass
        out.append(
            f"[{label}] {date} {loc} {opp}: {result} {tm}-{opp_pts} (streak: {streak})"
        )
    return out


@tool("get_team_schedule", args_schema=TeamScheduleInput)
@safe_tool
@with_retry(max_attempts=3)
@with_cache(tool_name="get_team_schedule", ttl_seconds=60 * 60)
def get_team_schedule(
    team: str,
    season: int | None = None,
    last_n: int = 10,
    include_playoffs: bool = True,
) -> str:
    """获取某支球队某赛季的近 N 场比赛（含赛果/比分/胜负/连胜情况）。

    数据源：basketball-reference.com（数据延迟数小时；季后赛和常规赛分开列出）。
    用于回答"湖人最近战绩"、"勇士本赛季表现"、"雷霆季后赛走势"等问题。
    """
    info = resolve_team(team)
    if not info:
        return f'{{"error": "无法识别球队 \\"{team}\\""}}'

    season = season or _current_bbref_season()
    abbr = info["bbref_abbr"]
    path = f"/teams/{abbr}/{season}_games.html"
    logger.info("[get_team_schedule] team={} season={} last_n={}", info["full_name"], season, last_n)

    html = fetch_html(path)

    rs = read_table(html, "games")
    ps = read_table(html, "games_playoffs") if include_playoffs else None
    rs = clean_repeated_header(rs, "G") if rs is not None else None
    ps = clean_repeated_header(ps, "G") if ps is not None else None

    if rs is None and ps is None:
        return f'{{"error": "未找到 {info["full_name"]} {season} 赛季赛程"}}'

    lines: list[str] = []
    if ps is not None and not ps.empty:
        lines += _format_rows(ps.tail(last_n), "PLAYOFF")
    remain = last_n - len([l for l in lines if "[PLAYOFF]" in l])
    if remain > 0 and rs is not None and not rs.empty:
        played = rs[rs["Unnamed: 4"].astype(str).str.contains("Box", na=False)]
        lines = _format_rows(played.tail(remain), "REG") + lines

    header = f"{info['full_name']} {season-1}-{str(season)[-2:]} 赛季近 {last_n} 场（含季后赛={include_playoffs}）："
    return header + "\n" + "\n".join(lines)
