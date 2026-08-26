"""規則層：不用 LLM 就能接住的常見句型。

日常最常講的那幾句（記帳、查今天明天的行程、看這個月花多少）句型很固定，
用正規表達式接住就好，不必每次都花錢叫 Claude，回應也更快。

規則接不住的（例如「下週二下午三點跟客戶開會」這種要真的理解語意的），
回傳 None 讓呼叫端交給 agent 處理。
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

import calendar_api
import config
import expense_api
from agent import AgentResult, _WEEKDAYS

# 關鍵字 → 記帳分類。想調整分類判斷就改這裡。
# 找不到對應時回傳 None，讓 Claude 去判斷，避免全部塞進「其他」。
_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "餐飲": (
        "早餐", "午餐", "晚餐", "宵夜", "下午茶", "便當", "咖啡", "星巴克", "飲料",
        "手搖", "麵", "飯", "火鍋", "燒烤", "拉麵", "壽司", "披薩", "漢堡", "超商",
        "7-11", "全家", "麥當勞", "吃飯", "聚餐", "外送", "foodpanda", "ubereats",
    ),
    "交通": (
        "捷運", "公車", "計程車", "uber", "加油", "停車", "高鐵", "火車", "客運",
        "機票", "油錢", "過路費", "youbike", "運費",
    ),
    "購物": ("衣服", "鞋", "蝦皮", "momo", "pchome", "淘寶", "書", "電器", "日用品", "生活用品"),
    "娛樂": ("電影", "遊戲", "ktv", "唱歌", "展覽", "演唱會", "訂閱", "netflix", "spotify", "健身"),
    "居家": ("房租", "水電", "電費", "水費", "瓦斯", "網路費", "管理費", "家具", "housing"),
    "醫療": ("看醫生", "診所", "醫院", "藥", "健檢", "牙醫", "掛號"),
}

# 出現這些字就不是記帳，是在講行程
_CALENDAR_WORDS = ("開會", "會議", "提醒", "行程", "安排", "預約", "約", "點", "面試", "上課")

_ITEM = r"[^\d\n]{1,20}"
_AMOUNT = r"\d{1,7}"
# 「午餐 120」「星巴克85元」
_RE_EXPENSE_TAIL = re.compile(rf"^\s*(?P<item>{_ITEM}?)\s*(?P<amount>{_AMOUNT})\s*(元|塊)?\s*$")
# 「120 午餐」
_RE_EXPENSE_HEAD = re.compile(rf"^\s*(?P<amount>{_AMOUNT})\s*(元|塊)?\s*(?P<item>{_ITEM})\s*$")


def _now() -> datetime:
    return datetime.now(config.TZ)


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, config.TZ)
    return start, start + timedelta(days=1)


def _fmt_events(events: list[dict], multi_day: bool) -> str:
    lines: list[str] = []
    last_day = None
    for event in events:
        day = event["start"].date()
        if multi_day and day != last_day:
            lines.append(f"\n{day.month}/{day.day}({_WEEKDAYS[day.weekday()]})")
            last_day = day
        if event["all_day"]:
            body = f"・整天 {event['title']}"
        else:
            body = f"・{event['start']:%H:%M}-{event['end']:%H:%M} {event['title']}"
        if event["location"]:
            body += f" @ {event['location']}"
        lines.append(body)
    return "\n".join(lines).strip()


def _money(amount: float) -> str:
    return f"${amount:,.0f}"


# --- 各條規則 ---


def _match_calendar(text: str) -> AgentResult | None:
    """今天／明天／後天／這週／下週 的行程查詢。"""
    asking = any(word in text for word in ("行程", "安排", "有什麼", "有啥", "幹嘛", "要做什麼", "有事"))
    today = _now().date()

    periods: list[tuple[tuple[str, ...], date, date, str]] = [
        (("今天", "今日"), today, today, "今天"),
        (("明天", "明日"), today + timedelta(days=1), today + timedelta(days=1), "明天"),
        (("後天",), today + timedelta(days=2), today + timedelta(days=2), "後天"),
        (("這週", "本週", "這禮拜", "這星期"),
         today - timedelta(days=today.weekday()),
         today - timedelta(days=today.weekday()) + timedelta(days=6), "這週"),
        (("下週", "下禮拜", "下星期"),
         today - timedelta(days=today.weekday()) + timedelta(days=7),
         today - timedelta(days=today.weekday()) + timedelta(days=13), "下週"),
    ]

    for keywords, start_day, end_day, label in periods:
        if not any(k in text for k in keywords):
            continue
        # 「今天」單獨出現也算問行程；否則要有疑問詞，避免誤判「今天午餐 120」
        if not asking and text.strip() not in keywords:
            return None

        start, _ = _day_bounds(start_day)
        _, end = _day_bounds(end_day)
        events = calendar_api.list_events(start, end)
        if not events:
            return AgentResult(text=f"{label}沒有安排任何行程。")

        multi_day = start_day != end_day
        return AgentResult(text=f"{label}的行程：\n{_fmt_events(events, multi_day)}")

    return None


def _match_expense_query(text: str) -> AgentResult | None:
    """這個月／上個月／這週／今天 花多少。"""
    if not any(word in text for word in ("花", "消費", "支出", "開銷")):
        return None
    if any(word in text for word in ("預算", "剩")):
        return None

    today = _now().date()

    # 有指定分類就只看那個分類
    category = next((c for c in config.CATEGORIES if c in text), None)

    if any(k in text for k in ("上個月", "上月")):
        end = today.replace(day=1) - timedelta(days=1)
        start, label = end.replace(day=1), "上個月"
    elif any(k in text for k in ("這個月", "本月", "這月")):
        start, end, label = today.replace(day=1), today, "這個月"
    elif any(k in text for k in ("這週", "本週", "這禮拜", "這星期")):
        start, end, label = today - timedelta(days=today.weekday()), today, "這週"
    elif "今天" in text:
        start, end, label = today, today, "今天"
    elif category:
        start, end, label = today.replace(day=1), today, "這個月"
    else:
        return None

    rows = expense_api.query_expenses(start, end, category)
    if not rows:
        scope = f"{label}的{category}" if category else label
        return AgentResult(text=f"{scope}沒有任何消費紀錄。")

    totals = expense_api.totals_by_category(rows)
    total = sum(totals.values())
    if category:
        return AgentResult(text=f"{label}的{category}花了 {_money(total)}，共 {len(rows)} 筆。")

    detail = "\n".join(f"・{name} {_money(amount)}" for name, amount in
                       sorted(totals.items(), key=lambda kv: -kv[1]))
    return AgentResult(text=f"{label}總共花了 {_money(total)}\n{detail}")


def _match_budget(text: str) -> AgentResult | None:
    if "預算" not in text:
        return None

    today = _now().date()
    totals = expense_api.totals_by_category(
        expense_api.query_expenses(today.replace(day=1), today)
    )
    lines = []
    for name, budget in config.BUDGETS.items():
        spent = totals.get(name, 0)
        lines.append(f"・{name} {_money(spent)}/{_money(budget)}（剩 {_money(budget - spent)}）")
    return AgentResult(text=f"本月預算狀況：\n" + "\n".join(lines))


def _guess_category(item: str) -> str | None:
    lowered = item.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category if category in config.CATEGORIES else None
    return None


def _match_expense_add(text: str) -> AgentResult | None:
    """「午餐 120」這種一句話記帳。"""
    stripped = text.strip()
    if any(word in stripped for word in _CALENDAR_WORDS):
        return None
    if any(ch in stripped for ch in ("/", ":", "：", "月", "日")):
        return None

    match = _RE_EXPENSE_TAIL.match(stripped) or _RE_EXPENSE_HEAD.match(stripped)
    if not match:
        return None

    item = match.group("item").strip()
    if not item:
        return None

    # 猜不出分類就交給 Claude，別全部塞進「其他」
    category = _guess_category(item)
    if category is None:
        return None

    result = expense_api.add_expense(
        float(match.group("amount")), category, item, _now().date().isoformat()
    )
    return AgentResult(
        text=f"已記錄 {result['item']} {_money(result['amount'])}（{result['category']}）",
        created_expense=result,
    )


_RULES = (_match_expense_add, _match_calendar, _match_expense_query, _match_budget)


def try_handle(text: str) -> AgentResult | None:
    """規則接得住就回 AgentResult，接不住回 None（交給 agent）。"""
    for rule in _RULES:
        result = rule(text)
        if result is not None:
            return result
    return None
