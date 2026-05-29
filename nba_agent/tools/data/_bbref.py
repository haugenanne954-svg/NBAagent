"""basketball-reference.com 抓取层。

封装：
- HTTP 调用（统一 UA + 超时 + 速率限制）
- 注释剥离（bbref 把不少表格藏在 HTML 注释里）
- 通过 table id 取 DataFrame
"""
from __future__ import annotations

import io
import re
import threading
import time
import urllib.parse

import pandas as pd
import requests
from loguru import logger

from ..base import with_cache, with_retry

BBREF_BASE = "https://www.basketball-reference.com"
_UA = {"User-Agent": "Mozilla/5.0 (compatible; NBAAgent/0.1)"}

_last_call_at = 0.0      # 上次请求的时间戳（用于速率限制）
_lock = threading.Lock()  # 线程锁，保证速率限制的线程安全
_MIN_INTERVAL = 3.5      # 最小请求间隔（秒），bbref 限制约 20 次/分钟


def _throttle():
    """请求节流：确保两次请求之间至少间隔 _MIN_INTERVAL 秒。"""
    global _last_call_at
    with _lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call_at)
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.monotonic()


def fetch_html(path: str, timeout: int = 20) -> str:
    """GET 一个 bbref 页面，自动剥离注释。

    bbref 对每分钟超过 ~20 次请求会临时封禁，这里强制最小间隔。
    """
    url = path if path.startswith("http") else f"{BBREF_BASE}{path}"
    _throttle()
    logger.debug("[bbref] GET {}", url)
    r = requests.get(url, headers=_UA, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    html = r.text
    html = html.replace("<!--", "").replace("-->", "")
    return html


@with_retry(max_attempts=2)
@with_cache(tool_name="bbref_player_lookup", ttl_seconds=30 * 24 * 60 * 60)
def lookup_player_path(name_en: str) -> str | None:
    """通过 bbref 自带搜索找到球员页路径，自动处理：
    - 后缀 Jr./Sr./III/IV
    - 连字符姓（如 Gilgeous-Alexander）
    - 同名球员（默认取搜索结果第一个，bbref 按相关度排）

    返回相对路径（如 "/players/s/smithja05.html"），找不到时 None。
    缓存 30 天（球员 bbref ID 几乎永不变）。
    """
    if not name_en or not name_en.strip():
        return None

    url = f"{BBREF_BASE}/search/search.fcgi?search={urllib.parse.quote(name_en.strip())}&hint=1"
    _throttle()
    logger.debug("[bbref] SEARCH {}", url)
    r = requests.get(url, headers=_UA, allow_redirects=False, timeout=15)

    if r.status_code in (301, 302):
        loc = r.headers.get("Location", "")
        if loc.startswith("http"):
            loc = loc.split(BBREF_BASE, 1)[-1]
        if "/players/" in loc and loc.endswith(".html"):
            return loc

    if r.status_code == 200:
        r.encoding = r.apparent_encoding or "utf-8"
        m = re.search(r'href="(/players/[a-z]/[a-z\-]+\d+\.html)"', r.text)
        if m:
            return m.group(1)

    return None


def read_table(html: str, table_id: str) -> pd.DataFrame | None:
    """从已剥离注释的 HTML 里按 table id 读表。"""
    try:
        tables = pd.read_html(io.StringIO(html), attrs={"id": table_id})
    except ValueError:
        return None
    return tables[0] if tables else None


def clean_repeated_header(df: pd.DataFrame, key_col: str) -> pd.DataFrame:
    """bbref 表里会插入"重复表头行"。简单粗暴地按 key_col 去除等于列名的行。"""
    if df is None or key_col not in df.columns:
        return df
    mask = df[key_col].astype(str) != key_col
    return df[mask].reset_index(drop=True)


