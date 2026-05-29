"""资讯搜索工具：基于 Tavily，限定到 NBA 相关高质量站点。"""
from __future__ import annotations

from langchain_core.tools import tool
from loguru import logger
from pydantic import BaseModel, Field
from tavily import TavilyClient

from ...config import settings
from ..base import safe_tool, with_cache, with_retry


_NBA_SITE_FILTER = (
    "site:nba.com OR site:espn.com/nba OR site:bleacherreport.com "
    "OR site:theathletic.com OR site:hoopshype.com"
)


class NBASearchInput(BaseModel):
    query: str = Field(
        ...,
        description="要搜索的 NBA 主题关键词，例如 '湖人最近战绩' / 'LeBron James injury'。",
    )
    max_results: int = Field(
        default=3,
        ge=1,
        le=8,
        description="最多返回多少条搜索结果，默认 3。",
    )


@tool("nba_news_search", args_schema=NBASearchInput)
@safe_tool
@with_retry(max_attempts=3)
@with_cache(tool_name="nba_news_search", ttl_seconds=60 * 30)
def nba_news_search(query: str, max_results: int = 3) -> str:
    """搜索 NBA 新闻、球员动态、伤病、交易传闻、比赛综述等资讯。

    返回若干条带来源 URL 的摘要片段，适合用作"资讯类"问题的事实依据。
    """
    if not settings.tavily_api_key:
        return '{"error": "TAVILY_API_KEY 未配置", "retryable": false}'

    client = TavilyClient(api_key=settings.tavily_api_key)
    enhanced_query = f"{query} {_NBA_SITE_FILTER}"
    logger.info("[nba_news_search] query={}", enhanced_query)

    response = client.search(
        enhanced_query,
        search_depth="advanced",
        max_results=max_results,
    )

    pieces: list[str] = []
    for r in response.get("results", []):
        pieces.append(
            f"【来源】{r.get('url', '')}\n"
            f"【标题】{r.get('title', '')}\n"
            f"【内容】{r.get('content', '')}"
        )

    if not pieces:
        return "未检索到相关资讯。"
    return "\n\n---\n\n".join(pieces)
