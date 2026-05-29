"""get_league_leaders：联盟数据排行榜（得分王/篮板王等）。"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
from langchain_core.tools import tool
from loguru import logger
from pydantic import BaseModel, Field

from ..base import safe_tool, with_cache, with_retry
from ._bbref import fetch_html, read_table


_CATEGORY_MAP = {
    "pts": "PTS", "ppg": "PTS", "得分": "PTS",
    "trb": "TRB", "rpg": "TRB", "篮板": "TRB",
    "ast": "AST", "apg": "AST", "助攻": "AST",
    "stl": "STL", "spg": "STL", "抢断": "STL",
    "blk": "BLK", "bpg": "BLK", "盖帽": "BLK",
    "fg%": "FG%", "命中率": "FG%",
    "3p%": "3P%", "三分命中率": "3P%",
    "ft%": "FT%", "罚球命中率": "FT%",
}

_MIN_GAMES = 20


def _current_season() -> int:
    today = datetime.now()
    return today.year + 1 if today.month >= 10 else today.year


class LeadersInput(BaseModel):
    category: str = Field(
        ...,
        description='排行类别：可填 "pts/得分" / "trb/篮板" / "ast/助攻" / "stl/抢断" / "blk/盖帽" / "fg%/命中率" / "3p%" / "ft%" 等。',
    )
    season: int | None = Field(
        default=None,
        description="赛季末尾年份（2026 = 2025-26 赛季），不填默认当前。",
    )
    top_n: int = Field(default=10, ge=1, le=30, description="返回前 N 名。")


@tool("get_league_leaders", args_schema=LeadersInput)
@safe_tool
@with_retry(max_attempts=3)
@with_cache(tool_name="get_league_leaders", ttl_seconds=6 * 60 * 60)
def get_league_leaders(category: str, season: int | None = None, top_n: int = 10) -> str:
    """获取某赛季某项数据的联盟排行榜前 N 名。

    数据源：basketball-reference.com 联盟 leaders 页面。
    """
    sort_col = _CATEGORY_MAP.get(category.lower())
    if not sort_col:
        return f'{{"error": "未知排行类别 \\"{category}\\"。支持：得分/篮板/助攻/抢断/盖帽/命中率/三分命中率/罚球命中率"}}'

    season = season or _current_season()
    path = f"/leagues/NBA_{season}_per_game.html"
    logger.info("[get_league_leaders] cat={} season={} top={}", category, season, top_n)
    html = fetch_html(path)

    df = read_table(html, "per_game_stats")
    if df is None or df.empty:
        return f'{{"error": "未找到 {season} 赛季 per_game_stats 表"}}'

    df = df[df["Rk"].astype(str) != "Rk"]
    df = df[df["Player"] != "Player"]

    for c in ["G", sort_col]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=[sort_col])

    if "G" in df.columns:
        df = df[df["G"] >= _MIN_GAMES]

    df = df.sort_values(by=sort_col, ascending=False).head(top_n)

    lines = [f"{season-1}-{str(season)[-2:]} 赛季 {category} 排行榜 Top {top_n}（出场 ≥ {_MIN_GAMES} 场）："]
    cols_show = [c for c in ["Player", "Team", "G", sort_col] if c in df.columns]
    lines.append("  " + "  ".join(f"{c:>10}" for c in cols_show))
    for _, row in df.iterrows():
        lines.append("  " + "  ".join(f"{str(row[c]):>10}" for c in cols_show))
    return "\n".join(lines)
