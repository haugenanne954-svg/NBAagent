"""LLM 客户端：用 LangChain 的 ChatOpenAI 适配豆包 endpoint。

豆包 / Ark 的 chat completions 接口与 OpenAI 兼容，
因此可以直接复用 ChatOpenAI，只需指向自定义 base_url。
"""
from functools import lru_cache

from langchain_openai import ChatOpenAI

from ..config import settings


@lru_cache(maxsize=4)
def get_llm(temperature: float = 0.0, streaming: bool = False) -> ChatOpenAI:
    """获取一个可复用的 ChatOpenAI 实例（最多缓存 4 种参数组合）。

    底层使用豆包/Ark 的 OpenAI 兼容接口，通过 settings 中的
    llm_base_url 和 llm_api_key 配置。

    Args:
        temperature: 生成温度，0.0=最稳定（适合事实/规划），0.3=适度创造（适合分析）
        streaming: 是否启用流式输出（图节点内部一般不需要）
    """
    return ChatOpenAI(
        model=settings.llm_model_id,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout,
        temperature=temperature,
        streaming=streaming,
        max_retries=2,
    )
