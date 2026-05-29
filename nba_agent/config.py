"""全局配置：从项目上级目录的 .env 读取环境变量。"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


# ── 路径常量 ──────────────────────────────────────────────
# PROJECT_ROOT 指向 nba_agent 的上级目录（即 .env 所在目录）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"                       # 数据根目录
CHECKPOINT_DB = DATA_DIR / "checkpoints.sqlite"        # LangGraph SQLite 检查点
CBA_PDF_PATH = DATA_DIR / "cba" / "2023_cba.pdf"       # CBA 协议 PDF 原文件
CBA_CHROMA_DIR = DATA_DIR / "cba" / "chroma"            # Chroma 向量库持久化目录
TOOL_CACHE_DIR = DATA_DIR / "tool_cache"                # diskcache 工具结果缓存


class Settings(BaseSettings):
    """应用配置项，从 .env 自动加载。字段名不区分大小写。"""
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",      # 忽略 .env 中多余的变量
        case_sensitive=False,  # 环境变量名不区分大小写
    )

    # ── LLM 配置（兼容 OpenAI 接口，可接豆包/Ark 等） ──
    llm_api_key: str
    llm_model_id: str
    llm_base_url: str
    llm_timeout: int = 180  # 超时秒数，LLM 生成可能较慢

    # ── Tavily 搜索 API（NewsAgent 依赖，可选） ──
    tavily_api_key: str | None = None

    # ── RAG / Embedding 配置 ──
    embedding_model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    hf_endpoint: str | None = None  # HuggingFace 镜像端点，国内可设为 hf-mirror.com
    cba_collection_name: str = "cba_2023"  # Chroma 集合名


settings = Settings()

# ── HuggingFace 环境变量（需在 import embeddings 之前设置） ──
import os as _os
if settings.hf_endpoint:
    _os.environ.setdefault("HF_ENDPOINT", settings.hf_endpoint)
_os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")  # 模型下载超时 60 秒


def ensure_dirs() -> None:
    """运行前确保关键目录存在。"""
    for p in (DATA_DIR, TOOL_CACHE_DIR, CBA_CHROMA_DIR.parent, CBA_CHROMA_DIR):
        p.mkdir(parents=True, exist_ok=True)
