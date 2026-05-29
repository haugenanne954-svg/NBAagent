"""球员生涯/赛季数据 + 基本信息。"""
from __future__ import annotations

import re

from langchain_core.tools import tool
from loguru import logger
from pydantic import BaseModel, Field

from ..base import safe_tool, with_cache, with_retry
from ._bbref import fetch_html, lookup_player_path, read_table
from ._resolver import resolve_player


class PlayerStatsInput(BaseModel):
    player: str = Field(
        ...,
        description='球员名，中英文皆可，如 "詹姆斯" / "LeBron James"。',
    )
    last_n_seasons: int = Field(
        default=5,
        ge=1,
        le=25,
        description="返回最近 N 个赛季（按时间倒序）的场均数据；如要看完整生涯传 25。",
    )


@tool("get_player_career_stats", args_schema=PlayerStatsInput)
@safe_tool
@with_retry(max_attempts=3)
@with_cache(tool_name="get_player_career_stats", ttl_seconds=12 * 60 * 60)
def get_player_career_stats(player: str, last_n_seasons: int = 5) -> str:
    """获取球员的赛季场均数据（得分/篮板/助攻/命中率等）。

    数据源：basketball-reference.com 球员页 per_game 表。
    """
    info = resolve_player(player)
    name_for_lookup = info["full_name"] if info else player
    path = lookup_player_path(name_en=name_for_lookup)
    if not path:
        return f'{{"error": "在 bbref 上找不到球员 \\"{name_for_lookup}\\"，请确认是英文全名，例如 \\"Jabari Smith Jr.\\""}}'

    logger.info("[get_player_career_stats] player={} path={}", name_for_lookup, path)
    html = fetch_html(path)

    df = read_table(html, "per_game_stats")
    if df is None or df.empty:
        df = read_table(html, "per_game")
    if df is None or df.empty:
        return f'{{"error": "未找到 {info["full_name"]} 的 per_game 表"}}'

    df = df[df["Season"].astype(str).str.match(r"^\d{4}-\d{2}$")]
    df = df.tail(last_n_seasons)

    cols = [c for c in ["Season", "Team", "Age", "G", "MP", "PTS", "TRB", "AST", "STL", "BLK", "FG%", "3P%", "FT%"] if c in df.columns]
    df = df[cols]

    lines = [f"{info['full_name']} 近 {last_n_seasons} 个赛季场均（数据来源 basketball-reference）："]
    lines.append("  " + "  ".join(f"{c:>6}" for c in cols))
    for _, row in df.iterrows():
        lines.append("  " + "  ".join(f"{str(row[c]):>6}" for c in cols))
    return "\n".join(lines)


class PlayerInfoInput(BaseModel):
    player: str = Field(..., description='球员名，中英文皆可。')


@tool("get_player_info", args_schema=PlayerInfoInput)
@safe_tool
@with_retry(max_attempts=3)
@with_cache(tool_name="get_player_info", ttl_seconds=24 * 60 * 60)
def get_player_info(player: str) -> str:
    """获取球员基础信息：位置 / 身高 / 体重 / 球队 / 球衣号 / 出生日期。

    数据源：basketball-reference.com 球员页头部元信息。
    """
    info = resolve_player(player)
    name_for_lookup = info["full_name"] if info else player
    path = lookup_player_path(name_en=name_for_lookup)
    if not path:
        return f'{{"error": "在 bbref 上找不到球员 \\"{name_for_lookup}\\"，请确认是英文全名"}}'

    logger.info("[get_player_info] player={} path={}", name_for_lookup, path)
    import html as _htmlmod
    html = fetch_html(path)

    text = re.sub(r"<[^>]+>", " ", html)
    text = _htmlmod.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)

    def grab(label: str, max_len: int = 60) -> str | None:
        m = re.search(rf"{label}[:：]\s*([^|·]+?)\s+(?:Position|Shoots|Team|Born|Draft|Experience|College|\.|$)", text)
        return m.group(1).strip()[:max_len] if m else None

    pos = grab("Position")
    shoots = grab("Shoots")
    born = grab("Born")
    team = grab("Team")
    draft = grab("Draft")
    college = grab("College")
    height_m = re.search(r'(\d+-\d+),\s*(\d+)lb', text)
    height = height_m.group(0) if height_m else None

    bits = {
        "全名": info["full_name"],
        "位置": pos, "投手": shoots,
        "球队": team, "身高/体重": height,
        "出生": born, "选秀": draft, "大学": college,
        "活跃中": "是" if info["is_active"] else "否",
    }
    out = [f"{k}: {v}" for k, v in bits.items() if v]
    return "球员信息：\n  " + "\n  ".join(out)
