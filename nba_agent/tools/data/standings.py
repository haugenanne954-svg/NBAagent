"""get_standings：联盟分区排名。"""
from __future__ import annotations

from datetime import datetime

from langchain_core.tools import tool
from loguru import logger
from pydantic import BaseModel, Field

from ..base import safe_tool, with_cache, with_retry
from ._bbref import fetch_html, read_table


def _current_season() -> int:
    today = datetime.now()
    return today.year + 1 if today.month >= 10 else today.year


class StandingsInput(BaseModel):
    season: int | None = Field(
        default=None,
        description="赛季末尾年份，例如 2026 表示 2025-26 赛季；不填默认当前。",
    )
    conference: str | None = Field(
        default=None,
        description='可选过滤：填 "east" 或 "west"，不填返回两个分区。',
    )


@tool("get_standings", args_schema=StandingsInput)
@safe_tool
@with_retry(max_attempts=3)
@with_cache(tool_name="get_standings", ttl_seconds=6 * 60 * 60)
def get_standings(season: int | None = None, conference: str | None = None) -> str:
    """获取某赛季 NBA 东西部排名（含战绩 / 胜率 / 胜场差）。

    数据源：basketball-reference.com。
    """
    season = season or _current_season()
    path = f"/leagues/NBA_{season}_standings.html"
    logger.info("[get_standings] season={} conf={}", season, conference)
    html = fetch_html(path)

    parts: list[str] = []
    east = read_table(html, "confs_standings_E")
    west = read_table(html, "confs_standings_W")

    if conference is None or conference.lower().startswith("e"):
        if east is not None:
            parts.append("东部:\n" + _format_standings(east))
    if conference is None or conference.lower().startswith("w"):
        if west is not None:
            parts.append("西部:\n" + _format_standings(west))

    if not parts:
        return f'{{"error": "未找到 {season} 赛季排名"}}'

    return f"{season-1}-{str(season)[-2:]} 赛季排名（{datetime.now().strftime('%Y-%m-%d')}）：\n\n" + "\n\n".join(parts)


def _format_standings(df) -> str:
    name_col = df.columns[0]
    lines = []
    for i, row in df.iterrows():
        name = str(row[name_col])
        w, l = row.get("W", ""), row.get("L", "")
        pct = row.get("W/L%", "")
        gb = row.get("GB", "")
        lines.append(f"  {i+1:>2}. {name:<28} {w}-{l}  {pct}  GB:{gb}")
    return "\n".join(lines)
