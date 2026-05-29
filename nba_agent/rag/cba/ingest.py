"""CBA 协议 PDF 入库脚本。

流程：pdfplumber 抽文本 → 跟踪 Article/Section 上下文 → RecursiveCharacterTextSplitter
切分 → HuggingFaceEmbeddings 向量化 → 写 Chroma persistent store。

运行：
    python -m nba_agent.rag.cba.ingest
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable

import pdfplumber
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from loguru import logger

from ...config import CBA_CHROMA_DIR, CBA_PDF_PATH, ensure_dirs, settings


# ── CBA PDF 文本解析用的正则 ─────────────────────────────
# 匹配页眉 "Article XX 77" 格式
HEADER_RE = re.compile(r"^\s*Article\s+([IVXLCDM]+)\s+\d+\s*$", re.IGNORECASE | re.MULTILINE)
# 匹配 "Section N." 格式
SECTION_RE = re.compile(r"^\s*Section\s+(\d+)\.", re.MULTILINE)
# 匹配目录行 "..........123" 格式（至少 8 个点 + 页码）
TOC_HINT_RE = re.compile(r"\.{8,}\s*\d+\s*$", re.MULTILINE)


def _is_toc_page(text: str) -> bool:
    """判断是否为目录页（包含大量 …………123 这种行）。"""
    matches = TOC_HINT_RE.findall(text)
    return len(matches) >= 4


def _extract_pages(pdf_path: Path) -> Iterable[tuple[int, str, str | None]]:
    """逐页抽取 (page_no, text, current_article_in_header)。"""
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if not text.strip():
                continue
            if _is_toc_page(text):
                logger.debug("[cba.ingest] skip TOC page {}", i)
                continue
            header = HEADER_RE.search(text[:200])
            article = header.group(1).upper() if header else None
            yield i, text, article


def _strip_header(text: str) -> str:
    """去掉每页首行的 "Article XXX 77" 这种页头。"""
    lines = text.splitlines()
    if lines and HEADER_RE.match(lines[0]):
        return "\n".join(lines[1:])
    return text


def build_documents(pdf_path: Path) -> list[Document]:
    logger.info("[cba.ingest] reading PDF: {}", pdf_path)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=900,
        chunk_overlap=150,
        separators=["\n\n", "\n", ". ", "? ", "! ", "; ", " "],
        length_function=len,
    )

    current_article: str | None = None
    current_section: str | None = None
    docs: list[Document] = []

    for page_no, raw_text, header_article in _extract_pages(pdf_path):
        if header_article:
            current_article = header_article

        text = _strip_header(raw_text)

        for sec_match in SECTION_RE.finditer(text):
            current_section = sec_match.group(1)

        chunks = splitter.split_text(text)
        for chunk in chunks:
            local_sec = SECTION_RE.search(chunk)
            chunk_section = local_sec.group(1) if local_sec else current_section
            docs.append(Document(
                page_content=chunk,
                metadata={
                    "page": page_no,
                    "article": current_article or "?",
                    "section": chunk_section or "?",
                    "source": "2023_NBA_CBA",
                },
            ))

    logger.info("[cba.ingest] built {} chunks", len(docs))
    return docs


def get_embeddings():
    """获取 HuggingFace 多语言 embedding 模型。

    首次调用会下载约 470MB 的权重到 ~/.cache/huggingface/。
    """
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("[cba.ingest] embedding model={} device={}", settings.embedding_model_name, device)
    return HuggingFaceEmbeddings(
        model_name=settings.embedding_model_name,
        model_kwargs={"device": device},
        encode_kwargs={"normalize_embeddings": True, "batch_size": 64},
    )


def ingest(pdf_path: Path | None = None, force: bool = False) -> None:
    pdf_path = pdf_path or CBA_PDF_PATH
    if not pdf_path.exists():
        raise FileNotFoundError(f"找不到 CBA PDF: {pdf_path}")

    ensure_dirs()
    persist_dir = str(CBA_CHROMA_DIR)

    if not force and any(CBA_CHROMA_DIR.iterdir()) if CBA_CHROMA_DIR.exists() else False:
        logger.info("[cba.ingest] {} 已存在；如需重建请传 --force", persist_dir)
        return

    docs = build_documents(pdf_path)

    embeddings = get_embeddings()
    logger.info("[cba.ingest] writing {} chunks to Chroma at {}", len(docs), persist_dir)
    Chroma.from_documents(
        documents=docs,
        embedding=embeddings,
        persist_directory=persist_dir,
        collection_name=settings.cba_collection_name,
    )
    logger.info("[cba.ingest] done.")


if __name__ == "__main__":
    force = "--force" in sys.argv
    ingest(force=force)
