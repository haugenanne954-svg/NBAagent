"""get_team_stats：球队赛季场均/累计数据。"""
from __future__ import annotations

from datetime import datetime

from langchain_core.tools import tool
from loguru import logger
from pydantic import BaseModel, Field

from ..base import safe_tool, with_cache, with_retry
from ._bbref import fetch_html, read_table
from ._resolver import resolve_team


def _current_season() -> int:
    today = datetime.now()
    return today.year + 1 if today.month >= 10 else today.year


class TeamStatsInput(BaseModel):
    team: str = Field(..., description='球队名，中英文/缩写皆可。')
    season: int | None = Field(
        default=None,
        description="赛季末尾年份（2026 = 2025-26 赛季），不填默认当前。",
    )


@tool("get_team_stats", args_schema=TeamStatsInput)
@safe_tool
@with_retry(max_attempts=3)
@with_cache(tool_name="get_team_stats", ttl_seconds=6 * 60 * 60)
def get_team_stats(team: str, season: int | None = None) -> str:
    """获取某队某赛季的整体场均数据（得分/篮板/助攻/三分命中率等）和对手数据。

    数据源：basketball-reference.com 球队页 team_and_opponent 表。
    """
    info = resolve_team(team)
    if not info:
        return f'{{"error": "无法识别球队 \\"{team}\\""}}'

    season = season or _current_season()
    path = f"/teams/{info['bbref_abbr']}/{season}.html"
    logger.info("[get_team_stats] {} {}", info["full_name"], season)
    html = fetch_html(path)

    df = read_table(html, "team_and_opponent")
    if df is None or df.empty:
        return f'{{"error": "未找到 {info["full_name"]} {season} 赛季统计"}}'

    keep_rows = ["Team/G", "Opponent/G", "Lg Rank Team", "Year/Year Team"]
    first_col = df.columns[0]
    df = df[df[first_col].isin(keep_rows)]

    show_cols = [c for c in ["FG", "FGA", "FG%", "3P", "3P%", "FT", "TRB", "AST", "STL", "BLK", "TOV", "PTS"] if c in df.columns]

    lines = [f"{info['full_name']} {season-1}-{str(season)[-2:]} 赛季统计（场均 vs 对手 vs 联盟排名）："]
    lines.append("  " + "  ".join(["项目".ljust(14)] + [f"{c:>6}" for c in show_cols]))
    for _, row in df.iterrows():
        lines.append("  " + "  ".join([str(row[first_col]).ljust(14)] + [f"{str(row[c]):>6}" for c in show_cols]))
    return "\n".join(lines)
