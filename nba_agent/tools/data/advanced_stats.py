"""get_team_advanced_stats：BBRef 联赛级球队高阶 stats（含联赛排名）。

数据源：`/leagues/NBA_{year}.html` 里的 `advanced-team` 表。
含 W/L、MOV、SRS、ORtg/DRtg/NRtg、Pace、FTr、3PAr、TS%、Off 四要素、Def 四要素。
"""
from __future__ import annotations

import io

import pandas as pd
from langchain_core.tools import tool
from loguru import logger
from pydantic import BaseModel, Field

from ..base import safe_tool, with_cache, with_retry
from ._bbref import fetch_html
from ._resolver import resolve_team


class TeamAdvancedStatsInput(BaseModel):
    team: str = Field(..., description='球队名，中英文皆可，如 "湖人"/"Lakers"/"LAL"。')
    season: int = Field(default=2026, description="赛季末尾年份（2025-26 → 传 2026）")


_OFF_FACTORS = ["eFG%", "TOV%", "ORB%", "FT/FGA"]
_DEF_FACTORS = ["eFG%", "TOV%", "DRB%", "FT/FGA"]
_SIMPLE_STATS = [
    "Age", "W", "L", "PW", "PL",
    "MOV", "SOS", "SRS",
    "ORtg", "DRtg", "NRtg",
    "Pace", "FTr", "3PAr", "TS%",
]
_RANK_LOWER_IS_BETTER = {
    "L", "PL", "DRtg",
    "Off-TOV%",
    "Def-eFG%", "Def-FT/FGA",
}
_RANK_NEUTRAL = {"Age", "Pace", "3PAr", "FTr", "SOS"}


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    """把 MultiIndex 列展平。
    Offense Four Factors / eFG% → 'Off-eFG%'
    Defense Four Factors / eFG% → 'Def-eFG%'
    其余只保留二级列名。
    """
    new_cols: list[str] = []
    for c in df.columns:
        if isinstance(c, tuple):
            top, bot = c[0], c[1]
            if "Offense Four Factors" in top:
                new_cols.append(f"Off-{bot}")
            elif "Defense Four Factors" in top:
                new_cols.append(f"Def-{bot}")
            else:
                new_cols.append(bot)
        else:
            new_cols.append(str(c))
    df = df.copy()
    df.columns = new_cols
    return df


def _compute_ranks(df: pd.DataFrame, columns: list[str]) -> dict[str, dict[str, int]]:
    """对每个数值列计算 1..N 的排名（剔除联赛平均行）。

    - "Lower is better" 的列（L、DRtg、Off-TOV%、Def-eFG% 等） ascending=True
    - 中性列（Pace/3PAr/FTr/Age/SOS）：不排名（None）
    - 其余默认越高越好

    返回 {team_name_no_asterisk: {col: rank or None}}。
    """
    teams_only = df[df["Team"].notna() & ~df["Team"].str.contains("League Average", na=False)].copy()
    teams_only["_team_key"] = teams_only["Team"].str.replace("*", "", regex=False).str.strip()
    ranks: dict[str, dict[str, int | None]] = {k: {} for k in teams_only["_team_key"]}
    for col in columns:
        if col not in teams_only.columns:
            continue
        if col in _RANK_NEUTRAL:
            for key in teams_only["_team_key"]:
                ranks[key][col] = None
            continue
        try:
            vals = pd.to_numeric(teams_only[col], errors="coerce")
        except Exception:
            continue
        if vals.isna().all():
            continue
        ascending = col in _RANK_LOWER_IS_BETTER
        ranked = vals.rank(method="min", ascending=ascending).astype(int)
        for key, r in zip(teams_only["_team_key"], ranked):
            ranks[key][col] = int(r)
    return ranks


@tool("get_team_advanced_stats", args_schema=TeamAdvancedStatsInput)
@safe_tool
@with_retry(max_attempts=3)
@with_cache(tool_name="get_team_advanced_stats", ttl_seconds=12 * 60 * 60)
def get_team_advanced_stats(team: str, season: int = 2026) -> str:
    """获取某队该赛季的**高阶数据**：节奏、效率、四要素，每项附联赛排名。

    高阶指标可用于：
    - 战术分析：Pace 节奏快慢、3PAr 三分依赖、TS% 真实命中率、FT/FGA 罚球率
    - 攻防效率：ORtg / DRtg / NRtg（每 100 possession 的得失分）
    - 四要素：eFG% / TOV% / ORB% / FT-FGA（Dean Oliver 的胜负四要素）
    - 比赛预测：用 NRtg + Pace + 主客场判断攻守风格碰撞结果

    用于回答："勇士这赛季打法怎样？"、"OKC 防守强在哪？"、"湖人节奏快不快？"
    """
    info = resolve_team(team)
    if not info:
        return f'{{"error": "无法识别球队 \\"{team}\\""}}'

    logger.info("[get_team_advanced_stats] team={} season={}", info["full_name"], season)
    html = fetch_html(f"/leagues/NBA_{season}.html")
    tables = pd.read_html(io.StringIO(html))

    target = None
    for t in tables:
        cols = t.columns
        if not isinstance(cols, pd.MultiIndex):
            continue
        flat = [c[1] if isinstance(c, tuple) else c for c in cols]
        if "ORtg" in flat and "DRtg" in flat and "Pace" in flat and "Team" in flat:
            target = t
            break
    if target is None:
        return '{"error": "未在 BBRef 找到 advanced-team 表"}'

    df = _flatten(target)
    df["_team_key"] = df["Team"].fillna("").str.replace("*", "", regex=False).str.strip()
    team_name = info["full_name"]
    row = df[df["_team_key"].str.casefold() == team_name.casefold()]
    if row.empty:
        return f'{{"error": "在 advanced-team 表里没找到 {team_name}（请检查赛季）"}}'

    rank_cols = [c for c in _SIMPLE_STATS if c in df.columns] + \
                [f"Off-{x}" for x in _OFF_FACTORS if f"Off-{x}" in df.columns] + \
                [f"Def-{x}" for x in _DEF_FACTORS if f"Def-{x}" in df.columns]
    ranks = _compute_ranks(df, rank_cols)
    r = row.iloc[0]
    team_key = r["_team_key"]
    team_ranks = ranks.get(team_key, {})

    season_str = f"{season-1}-{str(season)[-2:]}"

    def _line(label: str, key: str, fmt: str = "{}") -> str | None:
        if key not in df.columns:
            return None
        val = r[key]
        try:
            val_num = float(val)
        except (TypeError, ValueError):
            return f"  {label:<28} {val}"
        val_str = fmt.format(val_num)
        rk = team_ranks.get(key)
        rk_str = f"  (联盟 #{rk}/30)" if rk else ""
        return f"  {label:<28} {val_str}{rk_str}"

    lines = [f"{team_name} 高阶数据 ({season_str} 赛季)"]
    lines.append("")
    lines.append("【战绩基本面】")
    lines.append(_line("胜场 W", "W", "{:.0f}"))
    lines.append(_line("负场 L", "L", "{:.0f}"))
    lines.append(_line("平均分差 MOV", "MOV", "{:+.2f}"))
    lines.append(_line("SRS 实力分（含 SOS 修正）", "SRS", "{:+.2f}"))
    lines.append(_line("赛程难度 SOS", "SOS", "{:+.2f}"))
    lines.append("")
    lines.append("【攻防效率（每 100 possessions）】")
    lines.append(_line("进攻效率 ORtg", "ORtg", "{:.1f}"))
    lines.append(_line("防守效率 DRtg", "DRtg", "{:.1f}"))
    lines.append(_line("净效率 NRtg", "NRtg", "{:+.1f}"))
    lines.append("")
    lines.append("【节奏与风格】")
    lines.append(_line("Pace 每场回合数", "Pace", "{:.1f}"))
    lines.append(_line("3PAr 三分出手比例", "3PAr", "{:.3f}"))
    lines.append(_line("FTr 罚球出手比例", "FTr", "{:.3f}"))
    lines.append(_line("TS% 真实命中率", "TS%", "{:.3f}"))
    lines.append("")
    lines.append("【进攻四要素（Off-）】")
    for f in _OFF_FACTORS:
        key = f"Off-{f}"
        lines.append(_line(f"  {f}", key, "{:.3f}" if f.endswith("%") or "FGA" in f else "{:.1f}"))
    lines.append("")
    lines.append("【防守四要素（Def-）】")
    for f in _DEF_FACTORS:
        key = f"Def-{f}"
        lines.append(_line(f"  {f}", key, "{:.3f}" if f.endswith("%") or "FGA" in f else "{:.1f}"))
    lines.append("")
    lines.append("数据来源：basketball-reference")
    return "\n".join([l for l in lines if l is not None])
