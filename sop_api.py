"""Notion 流程筆記（SOP）的讀寫。

步驟放在頁面內容而不是某個欄位，因為 rich text 欄位有 2000 字上限，
而且在 Notion 裡直接編輯一篇文件比編輯一格文字舒服得多。
讀取時接受多種區塊型別，這樣使用者在 Notion 裡怎麼排版都讀得到。
"""

from __future__ import annotations

import re
import time

import config
import notion

PROP_NAME = "名稱"    # title
PROP_ALIAS = "別名"   # rich text，逗號分隔
PROP_CATEGORY = "分類"  # select

# 問法裡的贅字。把這些去掉之後剩下的才是真正要找的東西。
_NOISE = re.compile(
    r"(流程|步驟|SOP|sop|怎麼做|怎麼用|怎麼弄|怎麼|如何|要做什麼|是什麼|該做什麼"
    r"|教學|方法|的|一下|我|請問|問一下|[?？。，,、\s])"
)

# 讀得到內容的區塊型別。清單刻意放寬，使用者在 Notion 裡用什麼排版都能讀。
_TEXT_BLOCKS = (
    "paragraph", "numbered_list_item", "bulleted_list_item", "to_do", "quote",
    "heading_1", "heading_2", "heading_3", "callout", "toggle", "code",
)

# 新增時把使用者自己打的編號去掉，交給 Notion 的編號清單去編
_LEADING_MARK = re.compile(r"^\s*(?:\d{1,2}\s*[.、)）:：]|[-*•‧・]|第\s*\d{1,2}\s*步[.、:：]?)\s*")

_CACHE_TTL = 300
_cache: tuple[float, list[dict]] | None = None


def enabled() -> bool:
    return bool(config.NOTION_SOP_DB_ID)


def _invalidate() -> None:
    global _cache
    _cache = None


def list_sops(force: bool = False) -> list[dict]:
    """列出所有流程的名稱與別名。

    每次問流程都要先拿這份清單，所以做了短期快取——
    流程不常變，五分鐘內重複問不必再打一次 Notion。
    """
    global _cache
    now = time.time()
    if not force and _cache and now - _cache[0] < _CACHE_TTL:
        return _cache[1]

    rows = []
    for page in notion.query_all(config.NOTION_SOP_DB_ID, {}):
        props = page["properties"]
        name = notion.plain(props[PROP_NAME]["title"]).strip()
        if not name:
            continue
        alias_text = notion.plain(props.get(PROP_ALIAS, {}).get("rich_text", []))
        aliases = [part.strip() for part in re.split(r"[,，、/\s]+", alias_text) if part.strip()]
        rows.append({"page_id": page["id"], "name": name, "aliases": aliases})

    _cache = (now, rows)
    return rows


def _core(text: str) -> str:
    """把問句剝到只剩關鍵字：「收班流程是什麼？」→「收班」。"""
    return _NOISE.sub("", text).strip()


def find(query: str) -> dict | None:
    """從問句找出最合適的流程。找不到回 None。

    比對的是「剝掉贅字後的核心字」，所以「收班流程」「怎麼收班」「收班要做什麼」
    都能找到同一份。多個命中時取最長的，避免「班」誤中「收班」與「交班」。
    """
    core = _core(query)
    if len(core) < 2:
        return None

    best: tuple[int, dict] | None = None
    for sop in list_sops():
        for candidate in [_core(sop["name"]), *sop["aliases"]]:
            if len(candidate) < 2:
                continue
            if candidate in core or core in candidate:
                score = len(candidate)
                if best is None or score > best[0]:
                    best = (score, sop)
    return best[1] if best else None


def _block_text(block: dict) -> str:
    kind = block.get("type", "")
    if kind not in _TEXT_BLOCKS:
        return ""
    body = block.get(kind, {})
    text = notion.plain(body.get("rich_text", []))
    if kind == "to_do":
        text = ("[v] " if body.get("checked") else "[ ] ") + text
    return text.strip()


def steps(page_id: str) -> list[str]:
    """讀出一份流程的步驟。空行會被略過。"""
    data = notion.get(f"/blocks/{page_id}/children?page_size=100")
    return [text for block in data.get("results", []) if (text := _block_text(block))]


def add_sop(name: str, lines: list[str], category: str = "") -> dict:
    """新增一份流程。每一行變成編號清單的一步。"""
    children = [
        {
            "object": "block",
            "type": "numbered_list_item",
            "numbered_list_item": {
                "rich_text": [{"type": "text", "text": {"content": step[:2000]}}]
            },
        }
        for line in lines
        if (step := _LEADING_MARK.sub("", line).strip())
    ]

    properties: dict = {PROP_NAME: {"title": [{"text": {"content": name}}]}}
    if category:
        properties[PROP_CATEGORY] = {"select": {"name": category}}

    created = notion.post(
        "/pages",
        {
            "parent": {"database_id": config.NOTION_SOP_DB_ID},
            "properties": properties,
            "children": children,
        },
    )
    _invalidate()
    return {"page_id": created["id"], "name": name, "count": len(children)}
