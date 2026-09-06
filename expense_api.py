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


# 還沒有足夠歷史時的起手快捷。等真實紀錄累積起來就會被擠掉，
# 所以這裡不必想得太全，能讓第一天就有東西可按就好。
_STARTER = (
    ("午餐", "餐飲", 120),
    ("晚餐", "餐飲", 150),
    ("飲料", "餐飲", 60),
    ("超商", "餐飲", 100),
    ("加油", "交通", 500),
    ("停車", "交通", 50),
    ("捷運", "交通", 30),
    ("日用品", "購物", 200),
)

# 記過幾次才算「常用」。設 1 的話買一次沙發、買一款遊戲就會變成快捷按鈕，
# 但那些東西這輩子不會再按第二次。
_MIN_TIMES = 2


def frequent_items(rows: list[dict], limit: int = 8) -> list[dict]:
    """最常記的項目，附上最近一次的金額，給快捷按鈕用。

    金額取「最近一次」而不是平均：午餐從 100 漲到 140 之後，
    平均會給出一個你從來沒付過的數字。
    """
    seen: dict[str, dict] = {}
    for row in rows:  # rows 依日期由舊到新，後面的會蓋掉前面的金額
        item = row["item"].strip()
        if not item:
            continue
        entry = seen.setdefault(item, {"item": item, "count": 0})
        entry["count"] += 1
        entry["category"] = row["category"]
        entry["amount"] = row["amount"]

    picked = sorted(
        (entry for entry in seen.values() if entry["count"] >= _MIN_TIMES),
        key=lambda entry: -entry["count"],
    )[:limit]

    # 比對的是「已經挑進來的」而不是「歷史出現過的」：只記過一次的午餐
    # 兩邊都不算數，會整個消失，但那正是最該有快捷的東西。
    # 歷史上有記過的話金額沿用你自己付過的，不要用我猜的預設值。
    chosen = {entry["item"] for entry in picked}
    for item, category, amount in _STARTER:
        if len(picked) >= limit:
            break
        if item in chosen or category not in config.CATEGORIES:
            continue
        past = seen.get(item)
        picked.append(
            {
                "item": item,
                "category": past["category"] if past else category,
                "amount": past["amount"] if past else amount,
                "count": past["count"] if past else 0,
            }
        )

    return picked


def search_expenses(keyword: str, start_date: date, end_date: date) -> list[dict]:
    """在區間內用項目名稱搜尋。

    Notion 的 title contains 篩選是區分不了大小寫的，而且中英混雜的項目名
    （foodpanda、7-11）常常記得跟當初不完全一樣，所以改成全抓回來自己比對。
    個人記帳一年也才幾百筆，這個量級不值得為了省流量犧牲搜得到的機率。
    """
    needle = keyword.strip().lower()
    if not needle:
        return []
    return [
        row for row in query_expenses(start_date, end_date)
        if needle in row["item"].lower() or needle == row["category"]
    ]


def totals_by_category(rows: list[dict]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        totals[row["category"]] = totals.get(row["category"], 0) + row["amount"]
    return totals


def update_expense(
    page_id: str,
    item: str | None = None,
    amount: float | None = None,
    category: str | None = None,
    spent_on: str | None = None,
) -> None:
    """改一筆消費。只送有給的欄位，沒給的維持原樣。"""
    properties: dict = {}
    if item is not None:
        properties[PROP_ITEM] = {"title": [{"text": {"content": item[:2000]}}]}
    if amount is not None:
        properties[PROP_AMOUNT] = {"number": amount}
    if category is not None and category in config.CATEGORIES:
        properties[PROP_CATEGORY] = {"select": {"name": category}}
    if spent_on:
        properties[PROP_DATE] = {"date": {"start": spent_on}}

    if properties:
        notion.patch(f"/pages/{page_id}", {"properties": properties})
