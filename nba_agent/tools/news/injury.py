"""get_injury_report：伤病报告（Tavily 限定到伤病/资讯专业站点）。"""
from __future__ import annotations

from langchain_core.tools import tool
from loguru import logger
from pydantic import BaseModel, Field
from tavily import TavilyClient

from ...config import settings
from ..base import safe_tool, with_cache, with_retry


_INJURY_SITES = (
    "site:rotowire.com/basketball/nba/injuries.php "
    "OR site:nba.com OR site:espn.com/nba/injuries "
    "OR site:hoopshype.com OR site:spotrac.com/nba/disabled-list"
)


class InjuryInput(BaseModel):
    team: str | None = Field(
        default=None,
        description='可选：限定球队，中文或英文皆可，如 "湖人" / "Lakers"。',
    )
    player: str | None = Field(
        default=None,
        description='可选：限定球员，中文或英文皆可。',
    )


@tool("get_injury_report", args_schema=InjuryInput)
@safe_tool
@with_retry(max_attempts=3)
@with_cache(tool_name="get_injury_report", ttl_seconds=30 * 60)
def get_injury_report(team: str | None = None, player: str | None = None) -> str:
    """查询 NBA 伤病情况：可按球队或球员过滤。

    数据源：Tavily 限定到 rotowire / espn / nba.com 等专业站点。
    阶段 2 会接 Spotrac 结构化爬虫做替代。
    """
    if not settings.tavily_api_key:
        return '{"error": "TAVILY_API_KEY 未配置", "retryable": false}'

    bits: list[str] = ["NBA injury report"]
    if team:
        bits.append(team)
    if player:
        bits.append(player)
    bits.append(_INJURY_SITES)
    query = " ".join(bits)

    logger.info("[get_injury_report] {}", query)
    client = TavilyClient(api_key=settings.tavily_api_key)
    response = client.search(query, search_depth="advanced", max_results=5)

    pieces = []
    for r in response.get("results", []):
        pieces.append(
            f"【来源】{r.get('url','')}\n"
            f"【标题】{r.get('title','')}\n"
            f"【内容】{r.get('content','')}"
        )
    return "\n\n---\n\n".join(pieces) if pieces else "未检索到伤病信息。"
