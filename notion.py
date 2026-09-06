"""Notion REST 的共用底層。

直接打 REST 而不是用 notion-client，是為了能自己釘住 Notion-Version：
較新的 API 版本把 database_id 換成 data_source_id，釘住版本可以避開那次改版。

記帳、待辦、流程三個資料庫都走這裡，錯誤處理與標頭只有一份。
"""

from __future__ import annotations

import httpx

import config

API = "https://api.notion.com/v1"

_TIMEOUT = 20


def headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.NOTION_TOKEN}",
        "Notion-Version": config.NOTION_VERSION,
        "Content-Type": "application/json",
    }


def post(path: str, payload: dict) -> dict:
    response = httpx.post(f"{API}{path}", headers=headers(), json=payload, timeout=_TIMEOUT)
    response.raise_for_status()
    return response.json()


def patch(path: str, payload: dict) -> dict:
    response = httpx.patch(f"{API}{path}", headers=headers(), json=payload, timeout=_TIMEOUT)
    response.raise_for_status()
    return response.json()


def get(path: str) -> dict:
    response = httpx.get(f"{API}{path}", headers=headers(), timeout=_TIMEOUT)
    response.raise_for_status()
    return response.json()


def query_all(database_id: str, payload: dict) -> list[dict]:
    """把一個資料庫查詢的所有分頁抓完。"""
    rows: list[dict] = []
    cursor: str | None = None
    while True:
        body = dict(payload, page_size=100)
        if cursor:
            body["start_cursor"] = cursor
        data = post(f"/databases/{database_id}/query", body)
        rows.extend(data["results"])
        if not data.get("has_more"):
            break
        cursor = data["next_cursor"]
    return rows


def plain(rich_text: list[dict]) -> str:
    """把 Notion 的 rich text 陣列攤平成純文字。"""
    return "".join(part.get("plain_text", "") for part in rich_text)


def title_of(page: dict) -> str:
    """取出頁面的標題，不必事先知道標題欄位叫什麼名字。"""
    for value in page.get("properties", {}).values():
        if value.get("type") == "title":
            return plain(value["title"])
    return ""


def delete(path: str) -> dict:
    response = httpx.delete(f"{API}{path}", headers=headers(), timeout=_TIMEOUT)
    response.raise_for_status()
    return response.json()
