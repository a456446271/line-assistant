"""Notion 記帳資料庫的讀寫。

底層的 HTTP 與版本釘選在 notion.py，這裡只管記帳這張表的欄位與查詢。
"""

from __future__ import annotations

from datetime import date

import config
import notion

# Notion 資料庫的欄位名稱。改欄位名稱時只要動這裡。
PROP_ITEM = "項目"
PROP_AMOUNT = "金額"
PROP_CATEGORY = "分類"
PROP_DATE = "日期"
PROP_SOURCE = "來源"


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
    created = notion.post("/pages", payload)
    return {
        "page_id": created["id"],
        "item": item,
        "amount": amount,
        "category": category,
        "date": spent_on,
    }


def archive_expense(page_id: str) -> None:
    """把某筆消費封存（撤銷）。"""
    notion.patch(f"/pages/{page_id}", {"archived": True})


def _row(page: dict) -> dict:
    props = page["properties"]
    category = props[PROP_CATEGORY].get("select")
    spent_on = props[PROP_DATE].get("date")
    return {
        "page_id": page["id"],
        "item": notion.plain(props[PROP_ITEM]["title"]) or "(無標題)",
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

    pages = notion.query_all(
        config.NOTION_EXPENSE_DB_ID,
        {
            "filter": {"and": conditions},
            "sorts": [{"property": PROP_DATE, "direction": "ascending"}],
        },
    )
    return [_row(page) for page in pages]


def totals_by_category(rows: list[dict]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        totals[row["category"]] = totals.get(row["category"], 0) + row["amount"]
    return totals
