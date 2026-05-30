"""get_head_to_head：两队当季交手记录（含主客场/系列赛聚合）。"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
from langchain_core.tools import tool
from loguru import logger
from pydantic import BaseModel, Field

from ..base import safe_tool, with_cache, with_retry
from ._bbref import BBREF_BASE, clean_repeated_header, fetch_html, read_table
from ._resolver import resolve_team


def _current_bbref_season() -> int:
    today = datetime.now()
    return today.year + 1 if today.month >= 10 else today.year


class HeadToHeadInput(BaseModel):
    team_a: str = Field(
        ...,
        description='球队A名称，可中文也可英文/缩写，如 "马刺" / "Spurs" / "SAS"。',
    )
    team_b: str = Field(
        ...,
        description='球队B名称，可中文也可英文/缩写，如 "雷霆" / "Thunder" / "OKC"。',
    )
    season: int | None = Field(
        default=None,
        description="赛季末尾年份，例如 2025-26 赛季传 2026；不填默认当前赛季。",
    )


def _parse_score(series: pd.Series) -> tuple[int | None, int | None]:
    """返回 (己方得分, 对方得分)，解析失败返回 (None, None)。"""
    try:
        tm = int(series.get("Tm", 0))
        opp = int(series.get("Opp", 0))
        return tm, opp
    except (ValueError, TypeError):
        return None, None


def _get_schedule_df(info: dict, abbr: str, season: int) -> pd.DataFrame | None:
    """获取某队某赛季的完整赛程（常规赛+季后赛）。"""
    path = f"/teams/{abbr}/{season}_games.html"
    try:
        html = fetch_html(path)
    except Exception:
        return None

    rs = read_table(html, "games")
    ps = read_table(html, "games_playoffs")
    rs = clean_repeated_header(rs, "G") if rs is not None else None
    ps = clean_repeated_header(ps, "G") if ps is not None else None

    frames = []
    if rs is not None and not rs.empty:
        rs = rs.copy()
        rs["_game_type"] = "REG"
        frames.append(rs)
    if ps is not None and not ps.empty:
        ps = ps.copy()
        ps["_game_type"] = "PLAYOFF"
        frames.append(ps)
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    return df


@tool("get_head_to_head", args_schema=HeadToHeadInput)
@safe_tool
@with_retry(max_attempts=2)
@with_cache(tool_name="get_head_to_head", ttl_seconds=30 * 60)
def get_head_to_head(
    team_a: str,
    team_b: str,
    season: int | None = None,
) -> str:
    """查询两支球队当季所有交手记录（含常规赛+季后赛），返回单场比分及主客场聚合统计。

    用途：
    - "XX系列赛走势怎样"、"谁在对方主场赢过"、"两队交手战绩"
    - 解决 LLM 无法从逐场赛程中正确计数主客场胜负的问题

    返回结构：
    - 每场比赛：日期 / 主队 / 客队 / 比分 / 胜者 / 比赛类型
    - 聚合统计：
      - 总战绩（team_a X 胜 Y 负 vs team_b）
      - 主客场拆分（team_a 主场/客场胜率、team_b 主场/客场胜率）
      - 系列赛主队胜率（主场优势评估）
    """
    info_a = resolve_team(team_a)
    info_b = resolve_team(team_b)
    if not info_a:
        return f'{{"error": "无法识别球队A \\"{team_a}\\""}}'
    if not info_b:
        return f'{{"error": "无法识别球队B \\"{team_b}\\""}}'

    season_val = season or _current_bbref_season()
    season_str = f"{season_val - 1}-{str(season_val)[-2:]}"

    logger.info(
        "[get_head_to_head] {} vs {} season={}",
        info_a["full_name"], info_b["full_name"], season_val,
    )

    # 取两队完整赛程
    df_a = _get_schedule_df(info_a, info_a["bbref_abbr"], season_val)
    df_b = _get_schedule_df(info_b, info_b["bbref_abbr"], season_val)

    if df_a is None and df_b is None:
        return (
            f'{{"error": "未找到 {info_a["full_name"]} 和 {info_b["full_name"]} '
            f'{season_str} 赛季赛程数据"}}'
        )

    # 从 team_a 的角度找所有对阵 team_b 的比赛
    # Opponent 列包含对手缩写（如 "SAS"）
    opp_abbr_a = info_b["bbref_abbr"]

    games: list[dict] = []

    if df_a is not None:
        mask = df_a["Opponent"].astype(str).str.strip() == opp_abbr_a
        matched = df_a[mask]
        for _, row in matched.iterrows():
            date = str(row.get("Date", "")).strip()
            is_away = str(row.get("Unnamed: 5", "")).strip() == "@"
            result = str(row.get("Unnamed: 7", "")).strip()  # W/L/OT
            tm, opp = _parse_score(row)
            game_type = str(row.get("_game_type", ""))

            if is_away:
                home_team = info_b["full_name"]
                away_team = info_a["full_name"]
                away_score, home_score = tm, opp
            else:
                home_team = info_a["full_name"]
                away_team = info_b["full_name"]
                home_score, away_score = tm, opp

            winner = home_team if result == "W" else away_team
            loser = away_team if result == "W" else home_team

            games.append({
                "date": date,
                "home": home_team,
                "away": away_team,
                "score": f"{home_score}-{away_score}" if home_score is not None else "?",
                "winner": winner,
                "loser": loser,
                "type": game_type,
                "home_win": result == "W",
            })

    # 去重（按日期+比赛类型，同一场比赛可能出现在两队赛程中）
    seen = set()
    unique_games: list[dict] = []
    for g in games:
        key = (g["date"], g["type"])
        if key not in seen:
            seen.add(key)
            unique_games.append(g)
    unique_games.sort(key=lambda x: x["date"])

    if not unique_games:
        return (
            f'{{"message": "{info_a["full_name"]} 与 {info_b["full_name"]} '
            f'在 {season_str} 赛季暂无交手记录。"}}'
        )

    # ── 生成输出 ──
    lines: list[str] = [
        f"## {info_a['full_name']} vs {info_b['full_name']}  {season_str} 赛季交手记录",
        f"共 {len(unique_games)} 场\n",
    ]

    # 单场明细表格
    lines.append("| 日期 | 主队 | 客队 | 比分 | 胜者 | 类型 |")
    lines.append("|------|------|------|------|------|------|")
    for g in unique_games:
        gt_label = "季后" if g["type"] == "PLAYOFF" else "常规"
        lines.append(
            f"| {g['date']} | {g['home']} | {g['away']} "
            f"| {g['score']} | {g['winner']} | {gt_label} |"
        )

    # 聚合统计
    total = len(unique_games)

    # 按球队统计
    def _count_team_wins(team_name: str) -> int:
        return sum(1 for g in unique_games if g["winner"] == team_name)

    def _count_team_home_wins(team_name: str) -> int:
        return sum(1 for g in unique_games
                   if g["home"] == team_name and g["home_win"])

    def _count_team_road_wins(team_name: str) -> int:
        return sum(1 for g in unique_games
                   if g["away"] == team_name and g["winner"] == team_name)

    wins_a = _count_team_wins(info_a["full_name"])
    wins_b = _count_team_wins(info_b["full_name"])
    home_wins_a = _count_team_home_wins(info_a["full_name"])
    road_wins_a = _count_team_road_wins(info_a["full_name"])
    home_wins_b = _count_team_home_wins(info_b["full_name"])
    road_wins_b = _count_team_road_wins(info_b["full_name"])
    home_wins_total = sum(1 for g in unique_games if g["home_win"])
    road_wins_total = total - home_wins_total

    lines.append(f"\n### 聚合统计")
    lines.append("")
    lines.append(f"- **总战绩**：{info_a['full_name']} {wins_a} 胜 {wins_b} 负 "
                 f"vs {info_b['full_name']}")
    lines.append(f"")
    lines.append(f"- **{info_a['full_name']}**：")
    lines.append(f"  - 主场 {home_wins_a} 胜 "
                 f"{sum(1 for g in unique_games if g['home'] == info_a['full_name']) - home_wins_a} 负")
    lines.append(f"  - 客场 {road_wins_a} 胜 "
                 f"{sum(1 for g in unique_games if g['away'] == info_a['full_name']) - road_wins_a} 负")
    lines.append(f"")
    lines.append(f"- **{info_b['full_name']}**：")
    lines.append(f"  - 主场 {home_wins_b} 胜 "
                 f"{sum(1 for g in unique_games if g['home'] == info_b['full_name']) - home_wins_b} 负")
    lines.append(f"  - 客场 {road_wins_b} 胜 "
                 f"{sum(1 for g in unique_games if g['away'] == info_b['full_name']) - road_wins_b} 负")

    # 系列赛主队胜率（系列赛分析核心指标）
    lines.append(f"\n### 系列赛关键指标")
    lines.append(f"- **主队胜率**：{home_wins_total} 胜 {road_wins_total} 负 "
                 f"（{home_wins_total}/{total} = {home_wins_total/total:.0%}）")
    lines.append(f"- **客队胜率**：{road_wins_total} 胜 {home_wins_total} 负 "
                 f"（{road_wins_total}/{total} = {road_wins_total/total:.0%}）")
    lines.append(f"\n数据来源：{BBREF_BASE}")

    return "\n".join(lines)
