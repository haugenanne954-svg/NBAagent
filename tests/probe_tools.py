"""阶段 1 工具 smoke test：不调 LLM，直接 invoke 各工具看返回。"""
from nba_agent.tools import (
    get_team_schedule,
    get_daily_scoreboard,
    get_standings,
    get_player_career_stats,
    get_player_info,
    get_team_stats,
    get_league_leaders,
)


def sep(title):
    print("\n" + "=" * 6, title, "=" * 6)


sep("get_team_schedule(湖人, 2026, last_n=12)")
print(get_team_schedule.invoke({"team": "湖人", "season": 2026, "last_n": 12}))

sep("get_daily_scoreboard(2026-05-12)")
print(get_daily_scoreboard.invoke({"date": "2026-05-12"}))

sep("get_standings(2026, west)")
print(get_standings.invoke({"season": 2026, "conference": "west"}))

sep("get_player_career_stats(詹姆斯, 3)")
print(get_player_career_stats.invoke({"player": "詹姆斯", "last_n_seasons": 3}))

sep("get_player_info(SGA)")
print(get_player_info.invoke({"player": "SGA"}))

sep("get_team_stats(雷霆, 2026)")
print(get_team_stats.invoke({"team": "雷霆", "season": 2026}))

sep("get_league_leaders(得分, 2026, 5)")
print(get_league_leaders.invoke({"category": "得分", "season": 2026, "top_n": 5}))
