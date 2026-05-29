"""get_team_payroll：球队总薪资 + 球员合同明细。"""
from __future__ import annotations

from langchain_core.tools import tool
from loguru import logger
from pydantic import BaseModel, Field

from ..base import safe_tool, with_cache, with_retry
from ..data._resolver import resolve_team
from ._hoopshype import fetch_team_payroll
from ._slugs import HOOPSHYPE_SLUG


class TeamPayrollInput(BaseModel):
    team: str = Field(..., description='球队名，中英文皆可，如 "湖人"/"Lakers"/"LAL"。')


@tool("get_team_payroll", args_schema=TeamPayrollInput)
@safe_tool
@with_retry(max_attempts=3)
@with_cache(tool_name="get_team_payroll", ttl_seconds=24 * 60 * 60)
def get_team_payroll(team: str) -> str:
    """获取某队的薪资总览（含未来几年）和每个球员的合同明细。

    数据源：HoopsHype。注意：金额是实际签约金额，**不一定**等于工资帽计算中的 Team Salary
    （后者还要考虑死合同、激励奖金等，需配合 query_cba_rule 查具体规则）。

    用于回答：
    - "湖人本赛季总薪资多少？"
    - "勇士有哪些到期合同？"
    - "雷霆未来三年的薪资结构如何？"
    """
    info = resolve_team(team)
    if not info:
        return f'{{"error": "无法识别球队 \\"{team}\\""}}'
    slug = HOOPSHYPE_SLUG.get(info["nba_abbr"])
    if not slug:
        return f'{{"error": "{info["full_name"]} 没有对应的 HoopsHype slug"}}'

    logger.info("[get_team_payroll] {} → {}", info["full_name"], slug)
    payroll = fetch_team_payroll(slug)

    lines = [f"{info['full_name']} 薪资总览（数据源：HoopsHype）"]
    lines.append(f"链接：{payroll['url']}")
    lines.append("")
    season_cols = payroll["seasons"]
    lines.append("【全队薪资总额】")
    for s in season_cols:
        total = payroll["totals"].get(s, 0)
        if total > 0:
            lines.append(f"  {s}:  ${total:>14,}")

    lines.append("")
    lines.append("【球员合同明细（按 2025-26 当前合同金额降序）】")
    current = season_cols[0] if season_cols else None
    players = sorted(
        payroll["players"],
        key=lambda p: p["salaries"].get(current, 0) if current else 0,
        reverse=True,
    )
    header_cols = ["Player"] + season_cols
    lines.append("  " + "  ".join([f"{c:<22}" if c == "Player" else f"{c:>15}" for c in header_cols]))
    for p in players:
        row = [f"{p['player']:<22}"]
        for s in season_cols:
            amt = p["salaries"].get(s)
            opt = p["options"].get(s, "")
            cell = "—" if amt is None else f"${amt:,}"
            if opt == "player_option":
                cell = f"P:{cell}"
            elif opt == "team_option":
                cell = f"T:{cell}"
            row.append(f"{cell:>15}")
        lines.append("  " + "  ".join(row))
    lines.append("")
    lines.append("注：'P:'=Player Option（球员选项），'T:'=Team Option（球队选项），'—' 表示当年没有合同。")
    return "\n".join(lines)
