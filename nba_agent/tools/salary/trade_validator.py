"""validate_trade：交易薪资匹配硬规则核查。

只做最常见的硬规则数值计算（送出/收入薪资、是否满足匹配公式），
更复杂的条款（Apron 触发限制、签换、Base Year Compensation 等）
建议同时调用 query_cba_rule 查 CBA 原文。
"""
from __future__ import annotations

import json

from langchain_core.tools import tool
from loguru import logger
from pydantic import BaseModel, Field

from ..base import safe_tool
from .cap_info import _CAP_BY_SEASON
from .player_salary import get_player_salary


class TradeSide(BaseModel):
    team: str = Field(..., description="该方球队")
    players: list[str] = Field(..., description="该方送出的球员名（中英文皆可）")


class TradeInput(BaseModel):
    side_a: TradeSide = Field(..., description="交易 A 方")
    side_b: TradeSide = Field(..., description="交易 B 方")
    season: str = Field(default="2025-26", description="当前赛季，默认 2025-26")
    apron_status_a: str = Field(
        default="under_first_apron",
        description="A 队薪资状态：under_first_apron / between_aprons / over_second_apron",
    )
    apron_status_b: str = Field(
        default="under_first_apron",
        description="B 队薪资状态：同上",
    )


def _extract_current_salary(salary_text: str, season: str) -> int | None:
    """从 get_player_salary 的输出文本里解析指定赛季金额。粗暴但够用。"""
    import re
    for line in salary_text.splitlines():
        line = line.strip()
        if line.startswith(season):
            m = re.search(r"\$([\d,]+)", line)
            if m:
                return int(m.group(1).replace(",", ""))
    return None


def _matching_rule_below_apron(out_salary: int) -> tuple[int, int]:
    """非 Apron 球队的薪资匹配范围（简化版）。

    基于 2023 CBA Article VII §6 的核心规则：
    - 送出薪资 ≤ $7.5M: 可收回 ≤ 送出 + $7.5M
    - 7.5M < 送出 ≤ 29.0M: 可收回 ≤ 送出 × 125% + $250K
    - 送出 > 29.0M: 可收回 ≤ 送出 + $7.5M

    Returns:
        (min_incoming, max_incoming) 允许收回的薪资范围
    """
    threshold_low = 7_500_000
    threshold_high = 29_000_000
    if out_salary <= threshold_low:
        return 0, out_salary + threshold_low
    if out_salary <= threshold_high:
        return 0, int(out_salary * 1.25) + 250_000
    return 0, out_salary + threshold_low


@tool("validate_trade", args_schema=TradeInput)
@safe_tool
def validate_trade(
    side_a: TradeSide,
    side_b: TradeSide,
    season: str = "2025-26",
    apron_status_a: str = "under_first_apron",
    apron_status_b: str = "under_first_apron",
) -> str:
    """快速核查一笔双方交易的薪资匹配规则。

    输入：双方球队 + 送出的球员列表 + 双方薪资状态。
    输出：双方薪资总额、匹配范围、是否合规、以及 Apron 限制提示。

    注意：只检查薪资匹配的数值层；完整合规检查（签换限制、BYC、Apron 限制等）
    必须再用 query_cba_rule 查 CBA 原文，本工具会在输出里给出对应提示。
    """
    if season not in _CAP_BY_SEASON:
        return json.dumps({"error": f"未收录 {season} 工资帽数据"}, ensure_ascii=False)

    def _gather(side: TradeSide) -> dict:
        details = []
        total = 0
        for name in side.players:
            txt = get_player_salary.invoke({"player": name, "team_hint": None})
            amt = _extract_current_salary(txt, season)
            details.append({"player": name, "salary": amt})
            if amt:
                total += amt
        return {"team": side.team, "players": details, "outgoing": total}

    logger.info("[validate_trade] season={}, a={}, b={}", season, side_a, side_b)
    a_info = _gather(side_a)
    b_info = _gather(side_b)

    a_out, b_out = a_info["outgoing"], b_info["outgoing"]
    a_min, a_max = _matching_rule_below_apron(a_out)
    b_min, b_max = _matching_rule_below_apron(b_out)

    a_incoming_ok = b_out <= a_max
    b_incoming_ok = a_out <= b_max

    lines = [f"【交易薪资匹配核查 ({season})】"]
    lines.append("")
    lines.append(f"A 方：{side_a.team}（状态：{apron_status_a}）")
    for d in a_info["players"]:
        amt = f"${d['salary']:,}" if d['salary'] else "未解析到金额"
        lines.append(f"  - 送出 {d['player']}：{amt}")
    lines.append(f"  送出总薪资：${a_out:,}")
    lines.append(f"  允许收回上限（非 Apron 规则）：${a_max:,}")
    lines.append(f"  实际收回（来自 B）：${b_out:,}  →  {'✓ 满足' if a_incoming_ok else '✗ 超过上限'}")
    lines.append("")
    lines.append(f"B 方：{side_b.team}（状态：{apron_status_b}）")
    for d in b_info["players"]:
        amt = f"${d['salary']:,}" if d['salary'] else "未解析到金额"
        lines.append(f"  - 送出 {d['player']}：{amt}")
    lines.append(f"  送出总薪资：${b_out:,}")
    lines.append(f"  允许收回上限（非 Apron 规则）：${b_max:,}")
    lines.append(f"  实际收回（来自 A）：${a_out:,}  →  {'✓ 满足' if b_incoming_ok else '✗ 超过上限'}")
    lines.append("")
    overall = a_incoming_ok and b_incoming_ok
    lines.append(f"【整体结论】薪资匹配：{'✓ 合规' if overall else '✗ 不合规（任一方超上限即整体不合规）'}")
    lines.append("")
    lines.append("⚠ 仅核查了薪资匹配数值。下列情形会有额外限制，请用 query_cba_rule 追查：")
    if "between_aprons" in (apron_status_a, apron_status_b):
        lines.append("  - 任一方在两个 Apron 之间 → 触发 First Apron 硬上限，禁止接收高于送出薪资的薪水（aggregation 受限）")
    if "over_second_apron" in (apron_status_a, apron_status_b):
        lines.append("  - 任一方超过 Second Apron → 不能合并薪资、不能用 MLE、严格禁止接超薪")
    lines.append("  - 任何被签换（sign-and-trade）的球员 → 触发 Hard Cap 整季")
    lines.append("  - Base Year Compensation：6 个月内涨薪超过 20% 的球员，BYC 规则会让送出薪资按一半算")
    lines.append("  → 上述条款建议用 query_cba_rule 查 Article VII Section 6/8、Article VII Section 12。")
    return "\n".join(lines)
