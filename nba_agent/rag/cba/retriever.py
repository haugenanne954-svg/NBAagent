"""CBA RAG 检索接口。"""
from __future__ import annotations

from functools import lru_cache

from langchain_chroma import Chroma
from langchain_core.documents import Document
from loguru import logger

from ...config import CBA_CHROMA_DIR, settings
from .ingest import get_embeddings


@lru_cache(maxsize=1)
def _get_store() -> Chroma:
    """获取 Chroma 向量库单例。首次调用时加载，后续复用。

    Raises:
        FileNotFoundError: 如果 Chroma 向量库未构建
    """
    persist_dir = str(CBA_CHROMA_DIR)
    if not CBA_CHROMA_DIR.exists() or not any(CBA_CHROMA_DIR.iterdir()):
        raise FileNotFoundError(
            f"Chroma 向量库未建：{persist_dir}\n"
            "请先运行：python -m nba_agent.rag.cba.ingest"
        )
    embeddings = get_embeddings()
    logger.info("[cba.retriever] loading Chroma store at {}", persist_dir)
    return Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings,
        collection_name=settings.cba_collection_name,
    )


def retrieve(query: str, top_k: int = 5, use_mmr: bool = True) -> list[Document]:
    """语义检索 CBA 条款原文。

    Args:
        query: 检索查询（可中英文混合）
        top_k: 返回最相关的 k 条片段
        use_mmr: 使用 MMR（最大边际相关性）去冗余，避免多条来自同一段落

    Returns:
        包含 page_content + metadata(article/section/page) 的 Document 列表
    """
    store = _get_store()
    if use_mmr:
        return store.max_marginal_relevance_search(query, k=top_k, fetch_k=top_k * 4)
    return store.similarity_search(query, k=top_k)
