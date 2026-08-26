"""Notion 記帳資料庫的讀寫。

直接打 REST 而不是用 notion-client，是為了能自己釘住 Notion-Version：
較新的 API 版本把 database_id 換成 data_source_id，釘住版本可以避開那次改版。
"""

from __future__ import annotations

from datetime import date

import httpx

import config

_API = "https://api.notion.com/v1"

# Notion 資料庫的欄位名稱。改欄位名稱時只要動這裡。
PROP_ITEM = "項目"
PROP_AMOUNT = "金額"
PROP_CATEGORY = "分類"
PROP_DATE = "日期"
PROP_SOURCE = "來源"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.NOTION_TOKEN}",
        "Notion-Version": config.NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _post(path: str, payload: dict) -> dict:
    response = httpx.post(f"{_API}{path}", headers=_headers(), json=payload, timeout=20)
    response.raise_for_status()
    return response.json()


def add_expense(amount: float, category: str, item: str, spent_on: str) -> dict:
    """新增一筆消費，回傳含 page_id 的結果供之後撤銷。"""
    if category not in config.CATEGORIES:
        category = "其他"

    payload = {
        "parent": {"database_id": config.NOTION_EXPENSE_DB_ID},
        "properties": {
            PROP_ITEM: {"title": [{"text": {"content": item}}]},
            PROP_AMOUNT: {"number": amount},
            PROP_CATEGORY: {"select": {"name": category}},
            PROP_DATE: {"date": {"start": spent_on}},
            PROP_SOURCE: {"select": {"name": "LINE"}},
        },
    }
    created = _post("/pages", payload)
    return {
        "page_id": created["id"],
        "item": item,
        "amount": amount,
        "category": category,
        "date": spent_on,
    }


def archive_expense(page_id: str) -> None:
    """把某筆消費封存（撤銷）。"""
    response = httpx.patch(
        f"{_API}/pages/{page_id}",
        headers=_headers(),
        json={"archived": True},
        timeout=20,
    )
    response.raise_for_status()


def _row(page: dict) -> dict:
    props = page["properties"]
    title = props[PROP_ITEM]["title"]
    category = props[PROP_CATEGORY].get("select")
    spent_on = props[PROP_DATE].get("date")
    return {
        "page_id": page["id"],
        "item": title[0]["plain_text"] if title else "(無標題)",
        "amount": props[PROP_AMOUNT].get("number") or 0,
        "category": category["name"] if category else "其他",
        "date": spent_on["start"] if spent_on else "",
    }


def query_expenses(
    start_date: date,
    end_date: date,
    category: str | None = None,
) -> list[dict]:
    """取出區間內的消費明細，依日期排序。"""
    conditions: list[dict] = [
        {"property": PROP_DATE, "date": {"on_or_after": start_date.isoformat()}},
        {"property": PROP_DATE, "date": {"on_or_before": end_date.isoformat()}},
    ]
    if category:
        conditions.append({"property": PROP_CATEGORY, "select": {"equals": category}})

    rows: list[dict] = []
    cursor: str | None = None
    while True:
        payload: dict = {
            "filter": {"and": conditions},
            "sorts": [{"property": PROP_DATE, "direction": "ascending"}],
            "page_size": 100,
        }
        if cursor:
            payload["start_cursor"] = cursor

        data = _post(f"/databases/{config.NOTION_EXPENSE_DB_ID}/query", payload)
        rows.extend(_row(page) for page in data["results"])

        if not data.get("has_more"):
            break
        cursor = data["next_cursor"]

    return rows


def totals_by_category(rows: list[dict]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        totals[row["category"]] = totals.get(row["category"], 0) + row["amount"]
    return totals
