"""get_salary_cap_info：工资帽 / 奢侈税 / Apron 等关键数字。

数据每年只更新 1 次（赛季开始前 NBA 公布），所以硬编码 + 注明来源。
权威来源：NBA League Memo + Larry Coon's CBA FAQ。
"""
from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ..base import safe_tool


_CAP_BY_SEASON = {
    "2023-24": {
        "salary_cap": 136_021_000,
        "luxury_tax": 165_294_000,
        "first_apron": 172_346_000,
        "second_apron": 182_794_000,
        "min_team_salary": 122_419_000,
        "bae": 4_516_000,
        "non_taxpayer_mle": 12_405_000,
        "taxpayer_mle": 5_000_000,
        "room_mle": 7_723_000,
        "max_15pct": 40_806_300,
        "max_25pct": 34_005_250,
        "max_30pct": 40_806_300,
        "max_35pct": 47_607_350,
    },
    "2024-25": {
        "salary_cap": 140_588_000,
        "luxury_tax": 170_814_000,
        "first_apron": 178_132_000,
        "second_apron": 188_931_000,
        "min_team_salary": 126_529_000,
        "bae": 4_667_000,
        "non_taxpayer_mle": 12_822_000,
        "taxpayer_mle": 5_168_000,
        "room_mle": 7_983_000,
        "max_25pct": 35_147_000,
        "max_30pct": 42_176_400,
        "max_35pct": 49_205_800,
    },
    "2025-26": {
        "salary_cap": 154_647_000,
        "luxury_tax": 187_895_000,
        "first_apron": 195_945_000,
        "second_apron": 207_824_000,
        "min_team_salary": 139_182_000,
        "bae": 5_134_000,
        "non_taxpayer_mle": 14_104_000,
        "taxpayer_mle": 5_685_000,
        "room_mle": 8_781_000,
        "max_25pct": 38_661_750,
        "max_30pct": 46_394_100,
        "max_35pct": 54_126_450,
    },
}

_LABEL = {
    "salary_cap": "工资帽 (Salary Cap)",
    "luxury_tax": "奢侈税线 (Luxury Tax Level)",
    "first_apron": "第一土豪线 (First Apron)",
    "second_apron": "第二土豪线 (Second Apron)",
    "min_team_salary": "工资底线 (Min Team Salary = 90% of Cap)",
    "bae": "BAE 双年特例 (Bi-Annual Exception)",
    "non_taxpayer_mle": "非奢侈税中产 (Non-Taxpayer MLE)",
    "taxpayer_mle": "奢侈税中产 (Taxpayer MLE)",
    "room_mle": "空间中产 (Room MLE)",
    "max_25pct": "25% 顶薪基准 (≤6 年球龄)",
    "max_30pct": "30% 顶薪基准 (7-9 年球龄)",
    "max_35pct": "35% 顶薪基准 (≥10 年球龄)",
}


class CapInfoInput(BaseModel):
    season: str = Field(
        default="2025-26",
        description='赛季，格式 "YYYY-YY"，默认 "2025-26"。',
    )


@tool("get_salary_cap_info", args_schema=CapInfoInput)
@safe_tool
def get_salary_cap_info(season: str = "2025-26") -> str:
    """获取指定赛季的工资帽、奢侈税、Apron 等核心数字。

    用于回答：
    - "今年工资帽多少？"
    - "Apron 是多少？"
    - "中产特例上限？"
    - 计算薪资匹配/奢侈税位置时的基准。

    返回结构化的金额列表 + 简要解释。
    """
    data = _CAP_BY_SEASON.get(season)
    if not data:
        avail = ", ".join(_CAP_BY_SEASON.keys())
        return f'{{"error": "未收录 {season} 数据，可用赛季: {avail}"}}'
    lines = [f"{season} 赛季 NBA 工资帽体系（来源：NBA League Memo / Larry Coon CBA FAQ）"]
    lines.append("")
    for key, value in data.items():
        label = _LABEL.get(key, key)
        lines.append(f"  {label:<42}  ${value:>13,}")
    lines.append("")
    lines.append("说明：")
    lines.append("  - 团队薪资低于 First Apron → 可用 Non-Taxpayer MLE；")
    lines.append("  - 在 First Apron 与 Second Apron 之间 → 只能用 Taxpayer MLE，且 First Apron 触发硬上限；")
    lines.append("  - 超过 Second Apron → 不能聚合薪资交易、不能用 MLE、首轮签冻结等强限制；")
    lines.append("  - 详细条款请用 query_cba_rule 检索。")
    return "\n".join(lines)
