"""工具通用装饰器：缓存 / 重试 / 错误结构化。

这一层只关注横切关注点，业务工具实现放在 tools/<domain>/ 下面。
"""
from __future__ import annotations

import functools
import hashlib
import json
import time
from typing import Any, Callable

from diskcache import Cache
from loguru import logger

from ..config import TOOL_CACHE_DIR


_cache: Cache | None = None  # 全局 diskcache 实例（懒加载）


def _get_cache() -> Cache:
    """获取或创建 diskcache 实例（单例模式）。"""
    global _cache
    if _cache is None:
        TOOL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache = Cache(str(TOOL_CACHE_DIR))
    return _cache


def _make_key(
    tool_name: str,
    args: tuple,
    kwargs: dict[str, Any],
    date_bucket: str | None,
) -> str:
    """根据工具名、参数和日期桶生成缓存键（MD5 哈希）。"""
    payload = {"tool": tool_name, "args": args, "kwargs": kwargs, "bucket": date_bucket}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def with_cache(
    tool_name: str,
    ttl_seconds: int = 60 * 60,
    date_bucket: str | None = None,
):
    """工具结果缓存。

    - tool_name：缓存键命名空间
    - ttl_seconds：过期时间
    - date_bucket：可选，比如 "daily" 时调用方可以传入当日字符串使同一天命中
    """
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            cache = _get_cache()
            key = _make_key(tool_name, args, kwargs, date_bucket)
            hit = cache.get(key)
            if hit is not None:
                logger.debug("[cache hit] {} key={}", tool_name, key[:8])
                return hit
            result = fn(*args, **kwargs)
            try:
                cache.set(key, result, expire=ttl_seconds)
            except Exception as e:  # noqa: BLE001
                logger.warning("[cache write failed] {} err={}", tool_name, e)
            return result
        return wrapper
    return deco


def with_retry(max_attempts: int = 3, backoff: float = 1.5):
    """简单的指数退避重试。"""
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_err: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    if attempt == max_attempts:
                        break
                    sleep = backoff ** attempt
                    logger.warning(
                        "[retry] {} attempt={}/{} err={} sleep={:.1f}s",
                        fn.__name__, attempt, max_attempts, e, sleep,
                    )
                    time.sleep(sleep)
            raise last_err  # type: ignore[misc]
        return wrapper
    return deco


def safe_tool(fn: Callable[..., Any]) -> Callable[..., Any]:
    """把工具内部抛出的异常转成结构化错误字符串。

    LangChain 的 @tool 期望返回字符串/可序列化对象，
    Agent 在拿到 {"error": ...} 时可以自己换工具或如实告知用户。
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            logger.exception("[tool error] {}: {}", fn.__name__, e)
            return json.dumps(
                {"error": str(e), "retryable": True, "tool": fn.__name__},
                ensure_ascii=False,
            )
    return wrapper
