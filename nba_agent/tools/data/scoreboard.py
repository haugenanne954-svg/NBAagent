"""get_daily_scoreboard：某日所有 NBA 比赛 + 比分（含季后赛）。"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from langchain_core.tools import tool
from loguru import logger
from pydantic import BaseModel, Field

from ..base import safe_tool, with_cache, with_retry
from ._bbref import BBREF_BASE, fetch_html


ET = ZoneInfo("America/New_York")


class ScoreboardInput(BaseModel):
    date: str | None = Field(
        default=None,
        description=(
            '日期 YYYY-MM-DD（**美东时间 ET**），例如 "2026-05-13"。'
            '"today"=ET 今天；"yesterday"=ET 昨天。'
            '注意：NBA 比赛全部按 ET 记录，北京时间凌晨~下午"今天"通常对应 ET 昨天。'
        ),
    )


def _parse_date(date_str: str | None) -> datetime:
    today_et = datetime.now(ET).replace(tzinfo=None)
    if not date_str or date_str.lower() == "today":
        return today_et
    if date_str.lower() == "yesterday":
        return today_et - timedelta(days=1)
    return datetime.strptime(date_str, "%Y-%m-%d")


@tool("get_daily_scoreboard", args_schema=ScoreboardInput)
@safe_tool
@with_retry(max_attempts=3)
@with_cache(tool_name="get_daily_scoreboard", ttl_seconds=30 * 60)
def get_daily_scoreboard(date: str | None = None) -> str:
    """查询某一天的全部 NBA 比赛及比分。

    数据源：basketball-reference.com（直播比赛要等 2-6 小时后才入库）。
    用于回答"昨天有哪些比赛"、"5/12 湖人对谁"等问题。
    """
    d = _parse_date(date)
    path = f"/boxscores/?month={d.month}&day={d.day}&year={d.year}"
    logger.info("[get_daily_scoreboard] date={}", d.strftime("%Y-%m-%d"))

    html = fetch_html(path)

    if "No games played on this date" in html:
        return (
            f"{d.strftime('%Y-%m-%d')} (ET) **没有 NBA 比赛**（bbref 官方明确标注 No games played）。"
            "请勿编造任何这天的比赛或战况；可以建议用户查询前后日期。"
        )

    games = []
    pattern = re.compile(
        r'<table[^>]*class="teams"[\s\S]*?</table>',
        re.IGNORECASE,
    )
    for m in pattern.finditer(html):
        block = m.group(0)
        try:
            df = pd.read_html(block)[0]
        except (ValueError, IndexError):
            continue
        if df.shape[0] < 2:
            continue
        try:
            v_team, v_pts = str(df.iloc[0, 0]).strip(), int(df.iloc[0, 1])
            h_team, h_pts = str(df.iloc[1, 0]).strip(), int(df.iloc[1, 1])
        except (ValueError, TypeError):
            continue
        status_match = re.search(r"<td[^>]*>(Final[^<]*)</td>", block)
        status = status_match.group(1) if status_match else "—"
        link_match = re.search(r'<a href="(/boxscores/[^"]+)"', block)
        link = f"{BBREF_BASE}{link_match.group(1)}" if link_match else ""
        games.append(f"{v_team} {v_pts} @ {h_team} {h_pts}  [{status}]  {link}".strip())

    if not games:
        return f"{d.strftime('%Y-%m-%d')} 当日未检索到比赛（也可能是赛季外或数据尚未入库）。"

    header = f"{d.strftime('%Y-%m-%d')} 当日比赛（共 {len(games)} 场）："
    return header + "\n" + "\n".join(games)
