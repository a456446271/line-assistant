"""待確認動作的暫存（記憶體 + TTL）。

刻意不落地到資料庫：確認卡片的壽命只有幾分鐘，服務重啟後讓卡片失效
（按下去回一句「已過期，請再說一次」）是可以接受的取捨。
"""

from __future__ import annotations

import secrets
import threading
import time

TTL_SECONDS = 30 * 60

_lock = threading.Lock()
_store: dict[str, tuple[float, dict]] = {}


def _sweep(now: float) -> None:
    expired = [key for key, (created, _) in _store.items() if now - created > TTL_SECONDS]
    for key in expired:
        del _store[key]


def put(payload: dict) -> str:
    """存入一筆待確認動作，回傳短 id（會塞進 postback data，有長度上限）。"""
    key = secrets.token_urlsafe(8)
    now = time.time()
    with _lock:
        _sweep(now)
        _store[key] = (now, payload)
    return key


def take(key: str) -> dict | None:
    """取出並移除。回 None 代表不存在或已過期。"""
    now = time.time()
    with _lock:
        _sweep(now)
        entry = _store.pop(key, None)
    return entry[1] if entry else None
