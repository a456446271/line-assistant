"""Notion 待辦資料庫的讀寫。

刻意用一張自己控制的乾淨表，而不是接生活模板附的那種待辦庫——
模板那種有三十幾個欄位、公式、按鈕與重複性任務的機制，
這裡只需要其中五個欄位，綁上去只會讓模板一改版就壞掉。

欄位名稱集中成常數放在最上面，換資料庫時只要改這裡。
"""

from __future__ import annotations

from datetime import date

import config
import notion

# 對應 Notion 待辦資料庫的欄位名稱
PROP_TITLE = "事項"       # title
PROP_DONE = "完成"        # checkbox
PROP_DUE = "期限"         # date
PROP_CATEGORY = "分類"    # select
PROP_DONE_AT = "完成時間"  # date
PROP_SOURCE = "來源"      # select

CATEGORIES = ("工作", "家裡", "購物", "其他")


def enabled() -> bool:
    return bool(config.NOTION_TODO_DB_ID)


def add_todo(title: str, due: date | None = None, category: str = "") -> dict:
    """新增一筆待辦，回傳含 page_id 的結果供之後勾選或刪除。"""
    properties: dict = {
        PROP_TITLE: {"title": [{"text": {"content": title[:2000]}}]},
        PROP_DONE: {"checkbox": False},
        PROP_SOURCE: {"select": {"name": "LINE"}},
    }
    if due:
        properties[PROP_DUE] = {"date": {"start": due.isoformat()}}
    if category in CATEGORIES:
        properties[PROP_CATEGORY] = {"select": {"name": category}}

    created = notion.post(
        "/pages",
        {"parent": {"database_id": config.NOTION_TODO_DB_ID}, "properties": properties},
    )
    return {"page_id": created["id"], "title": title, "due": due}


def complete_todo(page_id: str) -> str:
    """勾掉一筆待辦，回傳它的標題（方便回覆時講出來）。

    只是打勾不是刪除——完成紀錄留著，之後想回顧做過什麼還查得到。
    """
    updated = notion.patch(
        f"/pages/{page_id}",
        {
            "properties": {
                PROP_DONE: {"checkbox": True},
                PROP_DONE_AT: {"date": {"start": date.today().isoformat()}},
            }
        },
    )
    return notion.title_of(updated)


def delete_todo(page_id: str) -> str:
    """刪掉一筆待辦，回傳它的標題。

    用 Notion 的封存而不是真的刪除，所以誤刪三十天內都能從垃圾桶救回來。
    """
    title = notion.title_of(notion.get(f"/pages/{page_id}"))
    notion.patch(f"/pages/{page_id}", {"archived": True})
    return title


def uncomplete_todo(page_id: str) -> str:
    """把打勾的待辦還原成未完成。按錯的時候用。"""
    updated = notion.patch(
        f"/pages/{page_id}",
        {"properties": {PROP_DONE: {"checkbox": False}, PROP_DONE_AT: {"date": None}}},
    )
    return notion.title_of(updated)


def _row(page: dict) -> dict | None:
    """把一頁轉成清單用的資料。沒有標題的空白列回 None——在 LINE 上既顯示不了也按不了。"""
    props = page["properties"]
    title = notion.plain(props[PROP_TITLE]["title"]).strip()
    if not title:
        return None

    due = props.get(PROP_DUE, {}).get("date")
    done_at = props.get(PROP_DONE_AT, {}).get("date")
    category = props.get(PROP_CATEGORY, {}).get("select")
    return {
        "page_id": page["id"],
        "title": title,
        "due": date.fromisoformat(due["start"][:10]) if due else None,
        "done_at": date.fromisoformat(done_at["start"][:10]) if done_at else None,
        "category": category["name"] if category else "",
    }


def open_todos(limit: int = 100) -> list[dict]:
    """取出未完成的待辦。

    沒期限的排最後——沒設期限通常代表「有空再做」，
    不該擠在有期限的事情前面。
    """
    pages = notion.query_all(
        config.NOTION_TODO_DB_ID,
        {"filter": {"property": PROP_DONE, "checkbox": {"equals": False}}},
    )
    rows = [row for page in pages if (row := _row(page))]
    rows.sort(key=lambda row: (row["due"] is None, row["due"] or date.max, row["title"]))
    return rows[:limit]


def done_todos(limit: int = 50) -> list[dict]:
    """最近完成的待辦，新的排前面。

    打勾之後就從清單消失，回顧不了做過什麼——這個是給那個用的。
    """
    pages = notion.query_all(
        config.NOTION_TODO_DB_ID,
        {
            "filter": {"property": PROP_DONE, "checkbox": {"equals": True}},
            "sorts": [{"property": PROP_DONE_AT, "direction": "descending"}],
        },
    )
    return [row for page in pages if (row := _row(page))][:limit]


def due_by(day: date) -> list[dict]:
    """在指定日期（含）之前到期、而且還沒做完的待辦。"""
    return [row for row in open_todos() if row["due"] and row["due"] <= day]
