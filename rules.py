"""規則層：不用 LLM 就能接住的句型。

日常最常講的那些（記帳、查行程、新增行程、查空檔、查消費、查預算）句型夠規律，
用正規表達式加上 zh_datetime 的中文日期解析就能處理，不必每次花錢叫 Claude，
回應也快得多。

接不住的回傳 None，由呼叫端決定要交給 agent 還是回一句提示。

設計原則是**寧可放過、不可誤判**：記帳誤判會直接寫進 Notion，
查詢誤判會給出看起來合理但錯誤的答案，兩者都比「看不懂」更糟。
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

import calendar_api
import config
import expense_api
import zh_datetime
from agent import AgentResult, _WEEKDAYS

# 關鍵字 → 記帳分類。想調整分類判斷就改這裡。
# 找不到對應時回傳 None，讓 Claude 去判斷，避免全部塞進「其他」。
_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "餐飲": (
        "早餐", "午餐", "晚餐", "宵夜", "下午茶", "便當", "咖啡", "星巴克", "飲料",
        "手搖", "麵", "飯", "火鍋", "燒烤", "拉麵", "壽司", "披薩", "漢堡", "超商",
        "7-11", "全家", "麥當勞", "吃飯", "聚餐", "外送", "foodpanda", "ubereats",
        "買菜", "超市", "全聯", "家樂福", "菜市場", "零食", "水果",
    ),
    "交通": (
        "捷運", "公車", "計程車", "uber", "加油", "停車", "高鐵", "火車", "客運",
        "機票", "油錢", "過路費", "youbike", "運費", "悠遊卡",
    ),
    "購物": (
        "衣服", "鞋", "蝦皮", "momo", "pchome", "淘寶", "書", "電器", "日用品",
        "生活用品", "文具", "包包", "保養品", "化妝品",
    ),
    "娛樂": (
        "電影", "遊戲", "ktv", "唱歌", "展覽", "演唱會", "訂閱", "netflix",
        "spotify", "健身", "旅遊", "住宿", "門票",
    ),
    "居家": (
        "房租", "水電", "電費", "水費", "瓦斯", "網路費", "管理費", "家具",
        "電話費", "手機費", "清潔",
    ),
    "醫療": ("看醫生", "診所", "醫院", "藥", "健檢", "牙醫", "掛號", "保健食品"),
    "其他": ("剪頭髮", "理髮", "美髮", "寵物", "課程", "學費", "補習", "紅包", "禮金"),
}

# 出現這些字就不是記帳，是在講行程
_CALENDAR_WORDS = ("開會", "會議", "提醒", "行程", "安排", "預約", "約", "點", "面試", "上課")

# 出現這些字代表在問問題，不是要新增行程
_QUESTION_WORDS = ("嗎", "呢", "?", "？", "有空", "什麼", "幾點", "哪天", "多少", "忙不忙")

# 修改／取消既有行程需要先知道是哪一個，規則做不到，一律交給 Claude
_MODIFY_WORDS = (
    "改到", "改成", "改為", "改一下", "改期", "取消", "刪除", "移到", "移除",
    "延到", "延後", "提前", "調整", "換到",
)

_ASK_CALENDAR = ("行程", "安排", "有什麼", "有啥", "幹嘛", "要做什麼", "有事", "忙不忙", "忙嗎")
_ASK_FREE = ("有空", "空檔", "有沒有空", "空的")

_ITEM = r"[^\d\n]{1,20}"
_AMOUNT = r"\d{1,7}"

# 「娛樂 PS5 3000」——開頭直接講分類，就不必靠關鍵字猜。
# 項目允許含數字（PS5、iPhone 16、7-11），金額取結尾那串數字。
_RE_EXPENSE_CATEGORY = re.compile(
    r"^\s*(?P<category>" + "|".join(re.escape(c) for c in config.CATEGORIES) + r")"
    r"\s*(?:(?P<item>\S.*?)\s+)?(?P<amount>\d{1,7})\s*(元|塊)?\s*$"
)
# 「午餐 120」「星巴克85元」
_RE_EXPENSE_TAIL = re.compile(rf"^\s*(?P<item>{_ITEM}?)\s*(?P<amount>{_AMOUNT})\s*(元|塊)?\s*$")
# 「120 午餐」
_RE_EXPENSE_HEAD = re.compile(rf"^\s*(?P<amount>{_AMOUNT})\s*(元|塊)?\s*(?P<item>{_ITEM})\s*$")

# 標題前後常見的贅字
_TITLE_NOISE = re.compile(r"^(的|要|去|跟|和|與|幫我|提醒我|我|記得|安排|新增|加|預約)+|(的)+$")


def _now() -> datetime:
    return datetime.now(config.TZ)


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, config.TZ)
    return start, start + timedelta(days=1)


def _day_label(day: date) -> str:
    today = _now().date()
    delta = (day - today).days
    if delta in (0, 1, 2, 3):
        return ("今天", "明天", "後天", "大後天")[delta]
    return f"{day.month}/{day.day}（週{_WEEKDAYS[day.weekday()]}）"


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


def _resolve_period(text: str) -> tuple[date, date, str] | None:
    """把「明天」「這週」「這週五」「下下週」換成實際的日期區間。

    指名星期幾的要先判斷，否則「這週五」會被當成整個「這週」——
    那會給出看起來合理但錯誤的答案。
    """
    today = _now().date()
    monday = today - timedelta(days=today.weekday())

    if zh_datetime.has_weekday(text):
        hit = zh_datetime.parse_date_only(text)
        if hit:
            return hit[0], hit[0], _day_label(hit[0])

    if any(k in text for k in ("下下週", "下下禮拜", "下下星期")):
        start = monday + timedelta(days=14)
        return start, start + timedelta(days=6), "下下週"
    if any(k in text for k in ("下週", "下禮拜", "下星期")):
        start = monday + timedelta(days=7)
        return start, start + timedelta(days=6), "下週"
    if any(k in text for k in ("這週", "本週", "這禮拜", "這星期")):
        return monday, monday + timedelta(days=6), "這週"
    if "週末" in text or "禮拜六日" in text:
        saturday = monday + timedelta(days=5)
        return saturday, saturday + timedelta(days=1), "這週末"

    hit = zh_datetime.parse_date_only(text)
    if hit:
        return hit[0], hit[0], _day_label(hit[0])
    return None


def _clean_title(text: str) -> str:
    title = _TITLE_NOISE.sub("", text.strip()).strip()
    return re.sub(r"\s+", " ", title)


# --- 各條規則 ---


def _looks_like_expense(text: str) -> bool:
    """排除明顯在講行程的句子，避免把行程誤記成一筆消費。"""
    if any(word in text for word in _CALENDAR_WORDS):
        return False
    return not any(ch in text for ch in ("/", ":", "：", "月", "日"))


def _match_expense_with_category(text: str) -> AgentResult | None:
    """「娛樂 PS5 3000」——自己指定分類，項目照樣記下來。

    關鍵字表猜不到的東西（PS5、某個課程名）用這個語法就能記，
    是純規則模式下的逃生門。
    """
    stripped = text.strip()
    if not _looks_like_expense(stripped):
        return None

    match = _RE_EXPENSE_CATEGORY.match(stripped)
    if not match:
        return None

    category = match.group("category")
    # 只講「娛樂 3000」沒講買什麼，就拿分類名當項目
    item = (match.group("item") or category).strip()

    result = expense_api.add_expense(
        float(match.group("amount")), category, item, _now().date().isoformat()
    )
    return AgentResult(
        text=f"已記錄 {result['item']} {_money(result['amount'])}（{result['category']}）",
        created_expense=result,
    )


def _match_expense_add(text: str) -> AgentResult | None:
    """「午餐 120」這種一句話記帳，靠關鍵字猜分類。"""
    stripped = text.strip()
    if not _looks_like_expense(stripped):
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


def _guess_category(item: str) -> str | None:
    lowered = item.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category if category in config.CATEGORIES else None
    return None


def _match_budget(text: str) -> AgentResult | None:
    if "預算" not in text:
        return None

    today = _now().date()
    totals = expense_api.totals_by_category(
        expense_api.query_expenses(today.replace(day=1), today)
    )
    lines = [
        f"・{name} {_money(totals.get(name, 0))}/{_money(budget)}"
        f"（剩 {_money(budget - totals.get(name, 0))}）"
        for name, budget in config.BUDGETS.items()
    ]
    return AgentResult(text="本月預算狀況：\n" + "\n".join(lines))


def _match_expense_query(text: str) -> AgentResult | None:
    """這個月／上個月／這週／今天 花多少。"""
    if not any(word in text for word in ("花", "消費", "支出", "開銷")):
        return None
    if any(word in text for word in ("預算", "剩")):
        return None

    today = _now().date()
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

    detail = "\n".join(
        f"・{name} {_money(amount)}"
        for name, amount in sorted(totals.items(), key=lambda kv: -kv[1])
    )
    return AgentResult(text=f"{label}總共花了 {_money(total)}\n{detail}")


def _match_free_slots(text: str) -> AgentResult | None:
    """「明天下午有空嗎」「這週哪天有空」。"""
    if not any(word in text for word in _ASK_FREE):
        return None

    period = _resolve_period(text)
    if period is None:
        return None
    start_day, end_day, label = period

    duration = 60
    hit = zh_datetime._parse_duration(text)
    if hit:
        duration = hit[0]

    slots = calendar_api.find_free_slots(start_day, end_day, duration)
    if not slots:
        return AgentResult(text=f"{label}找不到 {duration} 分鐘以上的空檔。")

    lines = [
        f"・{begin.month}/{begin.day}({_WEEKDAYS[begin.weekday()]}) "
        f"{begin:%H:%M}-{finish:%H:%M}"
        for begin, finish in slots[:10]
    ]
    return AgentResult(text=f"{label}的空檔：\n" + "\n".join(lines))


def _match_calendar(text: str) -> AgentResult | None:
    """今天／明天／這週五／下週 的行程查詢。"""
    asking = any(word in text for word in _ASK_CALENDAR)
    period = _resolve_period(text)
    if period is None:
        return None
    start_day, end_day, label = period

    # 「今天」單獨出現也算問行程；否則要有疑問詞，避免誤判「明天三點開會」
    if not asking and text.strip() != label:
        return None

    start, _ = _day_bounds(start_day)
    _, end = _day_bounds(end_day)
    events = calendar_api.list_events(start, end)
    if not events:
        return AgentResult(text=f"{label}沒有安排任何行程。")

    return AgentResult(text=f"{label}的行程：\n{_fmt_events(events, start_day != end_day)}")


def _match_create_event(text: str) -> AgentResult | None:
    """「明天下午三點開會」這種新增行程。

    只在明確講了時間、而且不是在問問題時才觸發。沒講時間就交給 Claude，
    寧可多花一次呼叫，也不要自作主張猜一個時間塞進行事曆。
    """
    if any(word in text for word in _QUESTION_WORDS):
        return None
    if any(word in text for word in _MODIFY_WORDS):
        return None

    parsed = zh_datetime.parse(text)
    if parsed is None or not parsed.has_time:
        return None

    title = _clean_title(zh_datetime.strip_spans(text, parsed.spans))
    if len(title) < 2:
        return None

    duration = parsed.duration_minutes or 60
    end = parsed.start + timedelta(minutes=duration)
    return AgentResult(
        text="",
        pending_event={
            "title": title,
            "start": parsed.start.isoformat(),
            "end": end.isoformat(),
            "location": "",
            "description": "",
        },
    )


# 順序有意義：越明確的規則越前面，最寬鬆的新增行程放最後
_RULES = (
    # 指定分類的要排在關鍵字猜測前面，否則「餐飲 午餐 120」的項目
    # 會變成「餐飲 午餐」
    _match_expense_with_category,
    _match_expense_add,
    _match_budget,
    _match_expense_query,
    _match_free_slots,
    _match_calendar,
    _match_create_event,
)


def try_handle(text: str) -> AgentResult | None:
    """規則接得住就回 AgentResult，接不住回 None。"""
    for rule in _RULES:
        result = rule(text)
        if result is not None:
            return result
    return None
