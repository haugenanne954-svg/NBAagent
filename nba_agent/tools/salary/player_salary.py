"""get_player_salary：单个球员未来几年合同明细。"""
from __future__ import annotations

import re

from langchain_core.tools import tool
from loguru import logger
from pydantic import BaseModel, Field

from bs4 import BeautifulSoup

from ..base import safe_tool, with_cache, with_retry
from ..data._bbref import fetch_html, lookup_player_path
from ._hoopshype import fetch_team_payroll
from ._slugs import HOOPSHYPE_SLUG


class PlayerSalaryInput(BaseModel):
    player: str = Field(..., description='球员名，中英文皆可，如 "詹姆斯"/"LeBron James"。')
    team_hint: str | None = Field(
        default=None,
        description="可选：球员当前所在球队（BBRef 缩写或英文）。"
        "如果不传，工具会先用 BBRef 查球员当前队。",
    )


_BBREF_TO_NBA = {
    "BRK": "BKN", "CHO": "CHA", "PHO": "PHX",
}


def _detect_team_bbref(player_path: str) -> str | None:
    """从 BBRef 球员页提取当前所在球队的 NBA 缩写。

    BBRef 球员页右侧有 "Team: ATL" 信息，但解析略繁琐；
    更简单的办法：抓 per_game_stats 表的最后一行 'Team' 字段。
    """
    html = fetch_html(f"https://www.basketball-reference.com{player_path}")
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table[id*='per_game']")
    if not table or not table.tbody:
        return None
    rows = table.tbody.find_all("tr")
    for row in reversed(rows):
        team_cell = row.find("td", attrs={"data-stat": "team_name_abbr"}) or row.find(
            "td", attrs={"data-stat": "team_id"}
        )
        if team_cell and team_cell.get_text(strip=True):
            tm = team_cell.get_text(strip=True)
            return _BBREF_TO_NBA.get(tm, tm)
    return None


def _fuzzy_match_player(table_players: list[dict], query: str) -> dict | None:
    """在 HoopsHype 球员列表里 fuzzy 匹配。"""
    q_norm = re.sub(r"[^a-z]", "", query.lower())
    if not q_norm:
        return None
    for p in table_players:
        n_norm = re.sub(r"[^a-z]", "", p["player"].lower())
        if q_norm in n_norm or n_norm.endswith(q_norm):
            return p
    return None


@tool("get_player_salary", args_schema=PlayerSalaryInput)
@safe_tool
@with_retry(max_attempts=3)
@with_cache(tool_name="get_player_salary", ttl_seconds=24 * 60 * 60)
def get_player_salary(player: str, team_hint: str | None = None) -> str:
    """获取某球员未来几年的合同明细：年薪、保障状态、Player/Team Option。

    数据源：HoopsHype（通过球员所在球队的薪资页）。
    工具会先用 BBRef 定位球员现在所在球队，再去拉对应球队薪资表，最后 fuzzy 匹配球员行。

    用于回答：
    - "詹姆斯还有几年合同？"
    - "东契奇下赛季薪资？"
    - "约基奇合同结构？"
    """
    path = lookup_player_path(player)
    if not path:
        return f'{{"error": "未在 BBRef 找到球员 \\"{player}\\""}}'

    team_abbr = team_hint or _detect_team_bbref(path)
    if not team_abbr:
        return f'{{"error": "无法确定 {player} 当前所在球队"}}'

    slug = HOOPSHYPE_SLUG.get(team_abbr.upper())
    if not slug:
        return f'{{"error": "球队 \\"{team_abbr}\\" 不在已知映射表里"}}'

    logger.info("[get_player_salary] {} @ {} → {}", player, team_abbr, slug)
    payroll = fetch_team_payroll(slug)
    hit = _fuzzy_match_player(payroll["players"], player)
    if not hit:
        names = ", ".join(p["player"] for p in payroll["players"][:8])
        return (
            f'{{"error": "在 {team_abbr} 薪资表里 fuzzy 没匹配到 \\"{player}\\"，'
            f'可见样本: [{names}]"}}'
        )

    lines = [f"{hit['player']} ({team_abbr}) 合同明细（数据源：HoopsHype）"]
    lines.append(f"链接：{payroll['url']}")
    lines.append("")
    for s in payroll["seasons"]:
        amt = hit["salaries"].get(s)
        opt = hit["options"].get(s)
        if amt is None:
            lines.append(f"  {s}:  —（无合同）")
            continue
        marker = ""
        if opt == "player_option":
            marker = "  (Player Option：球员可选择跳出)"
        elif opt == "team_option":
            marker = "  (Team Option：球队可选择执行)"
        lines.append(f"  {s}:  ${amt:>14,}{marker}")

    years_left = sum(1 for s in payroll["seasons"] if hit["salaries"].get(s))
    lines.append("")
    lines.append(f"合同年限剩余：{years_left} 个赛季")
    return "\n".join(lines)
