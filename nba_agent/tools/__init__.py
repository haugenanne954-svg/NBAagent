"""工具层：所有对外能力以 LangChain @tool 形式暴露。"""
from ..rag.cba.tool import query_cba_rule
from .data import (
    DATA_TOOLS,
    get_daily_scoreboard,
    get_league_leaders,
    get_player_career_stats,
    get_player_info,
    get_standings,
    get_team_advanced_stats,
    get_team_schedule,
    get_team_stats,
)
from .news.injury import get_injury_report
from .news.search import nba_news_search
from .salary import (
    SALARY_TOOLS,
    get_player_salary,
    get_salary_cap_info,
    get_team_payroll,
    validate_trade,
)

NEWS_TOOLS = [nba_news_search, get_injury_report]
RAG_TOOLS = [query_cba_rule]

ALL_TOOLS = [*DATA_TOOLS, *NEWS_TOOLS, *SALARY_TOOLS, *RAG_TOOLS]

__all__ = [
    "ALL_TOOLS",
    "DATA_TOOLS",
    "NEWS_TOOLS",
    "SALARY_TOOLS",
    "RAG_TOOLS",
    "get_daily_scoreboard",
    "get_team_schedule",
    "get_standings",
    "get_player_career_stats",
    "get_player_info",
    "get_team_stats",
    "get_team_advanced_stats",
    "get_league_leaders",
    "nba_news_search",
    "get_injury_report",
    "get_team_payroll",
    "get_player_salary",
    "get_salary_cap_info",
    "validate_trade",
    "query_cba_rule",
]
