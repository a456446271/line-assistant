"""中文日期時間解析。

把「下週二下午三點」「明天早上十點」「9/1 15:00」這類講法轉成實際時間，
讓規則層不用呼叫 LLM 也能處理新增行程與查空檔。

解析不出來就回 None，交給上層決定要不要丟給 Claude。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import config

_CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

# 星期幾 → Python 的 weekday()（週一 = 0）
_WEEKDAY_NAMES = {
    "一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5,
    "日": 6, "天": 6, "７": 6,
}

_PERIOD_OFFSETS = {
    "凌晨": 0,
    "早上": 0,
    "上午": 0,
    "中午": 12,
    "下午": 12,
    "傍晚": 12,
    "晚上": 12,
    "晚": 12,
}


@dataclass
class Parsed:
    """解析結果。

    start 是行程開始時間；has_time 為 False 代表只講了日期沒講時間。
    duration_minutes 沒特別講就是 None，由呼叫端決定預設值。
    """

    start: datetime
    has_time: bool
    duration_minutes: int | None
    # 原句中被日期時間佔掉的區段，呼叫端可以用來取出剩下的標題
    spans: list[tuple[int, int]]


def _cn_to_int(text: str) -> int | None:
    """把「三」「十」「十一」「二十」轉成數字。"""
    if text.isdigit():
        return int(text)
    if not text or any(ch not in _CN_DIGITS for ch in text):
        return None

    if "十" not in text:
        return _CN_DIGITS[text] if len(text) == 1 else None

    head, _, tail = text.partition("十")
    tens = _CN_DIGITS[head] if head else 1
    ones = _CN_DIGITS[tail] if tail else 0
    return tens * 10 + ones


def _today() -> date:
    return datetime.now(config.TZ).date()


# --- 日期 ---

_NUM = r"\d{1,2}|[零一二兩三四五六七八九十]{1,3}"

_RE_MD = re.compile(r"(?P<m>\d{1,2})\s*[/月]\s*(?P<d>\d{1,2})\s*日?")
_RE_WEEKDAY = re.compile(
    r"(?P<prefix>這|本|下下|下|上)?\s*(?:週|周|禮拜|星期)\s*(?P<day>[一二三四五六日天])"
)
_RE_RELATIVE_DAY = re.compile(r"大後天|後天|明天|明日|今天|今日")


def _parse_date(text: str) -> tuple[date, tuple[int, int]] | None:
    today = _today()

    match = _RE_RELATIVE_DAY.search(text)
    if match:
        offset = {"今天": 0, "今日": 0, "明天": 1, "明日": 1, "後天": 2, "大後天": 3}[match.group()]
        return today + timedelta(days=offset), match.span()

    match = _RE_WEEKDAY.search(text)
    if match:
        target = _WEEKDAY_NAMES[match.group("day")]
        prefix = match.group("prefix")
        monday = today - timedelta(days=today.weekday())

        if prefix in ("這", "本"):
            day = monday + timedelta(days=target)
        elif prefix == "下":
            day = monday + timedelta(days=7 + target)
        elif prefix == "下下":
            day = monday + timedelta(days=14 + target)
        elif prefix == "上":
            day = monday + timedelta(days=target - 7)
        else:
            # 沒有前綴：指最近的那一天，今天已過就算下週
            day = monday + timedelta(days=target)
            if day < today:
                day += timedelta(days=7)
        return day, match.span()

    match = _RE_MD.search(text)
    if match:
        month, day_num = int(match.group("m")), int(match.group("d"))
        if not (1 <= month <= 12 and 1 <= day_num <= 31):
            return None
        year = today.year
        try:
            parsed = date(year, month, day_num)
        except ValueError:
            return None
        # 日期已經過了就當作明年
        if parsed < today - timedelta(days=30):
            parsed = parsed.replace(year=year + 1)
        return parsed, match.span()

    return None


# --- 時間 ---

_RE_CLOCK = re.compile(
    r"(?P<period>凌晨|早上|上午|中午|下午|傍晚|晚上)?\s*"
    r"(?P<hour>" + _NUM + r")\s*[點點:：]\s*"
    r"(?P<minute>半|\d{1,2}|[零一二兩三四五六七八九十]{1,3})?\s*分?"
)
_RE_HHMM = re.compile(r"(?P<hour>\d{1,2})\s*[:：]\s*(?P<minute>\d{2})")
_RE_PERIOD_ONLY = re.compile(r"(?P<period>凌晨|早上|上午|中午|下午|傍晚|晚上)")
_RE_DURATION = re.compile(r"(?P<n>" + _NUM + r")\s*(?P<unit>小時|個小時|分鐘)")

# 只講「中午」「下午」沒講幾點時，用這些預設鐘點
_PERIOD_DEFAULT_HOURS = {
    "凌晨": 6,
    "早上": 9,
    "上午": 9,
    "中午": 12,
    "下午": 14,
    "傍晚": 17,
    "晚上": 19,
}


def _parse_time(text: str) -> tuple[time, tuple[int, int]] | None:
    match = _RE_HHMM.search(text)
    if match:
        hour, minute = int(match.group("hour")), int(match.group("minute"))
        if hour > 23 or minute > 59:
            return None
        # 「下午 3:00」這種也要吃到 period
        period_match = _RE_PERIOD_ONLY.search(text[: match.start()])
        if period_match and hour < 12:
            hour += _PERIOD_OFFSETS[period_match.group("period")]
        start = period_match.start() if period_match else match.start()
        return time(hour % 24, minute), (start, match.end())

    match = _RE_CLOCK.search(text)
    if match:
        hour = _cn_to_int(match.group("hour"))
        if hour is None or hour > 23:
            return None

        raw_minute = match.group("minute")
        if raw_minute == "半":
            minute = 30
        elif raw_minute:
            minute = _cn_to_int(raw_minute)
            if minute is None or minute > 59:
                return None
        else:
            minute = 0

        period = match.group("period")
        if period and hour < 12:
            hour += _PERIOD_OFFSETS[period]
        elif not period and hour < 8:
            # 沒講上下午又講「三點」，日常幾乎都是下午
            hour += 12
        return time(hour % 24, minute), match.span()

    # 只講了「中午」「下午」這種時段，給一個合理的預設鐘點
    match = _RE_PERIOD_ONLY.search(text)
    if match:
        return time(_PERIOD_DEFAULT_HOURS[match.group("period")]), match.span()

    return None


def _parse_duration(text: str) -> tuple[int, tuple[int, int]] | None:
    match = _RE_DURATION.search(text)
    if not match:
        return None
    value = _cn_to_int(match.group("n"))
    if value is None:
        return None
    minutes = value * 60 if "小時" in match.group("unit") else value
    return minutes, match.span()


# --- 對外 ---


def parse(text: str) -> Parsed | None:
    """解析出時間。日期和時間至少要有一個，否則回 None。"""
    spans: list[tuple[int, int]] = []

    date_hit = _parse_date(text)
    time_hit = _parse_time(text)
    if date_hit is None and time_hit is None:
        return None

    day = date_hit[0] if date_hit else _today()
    if date_hit:
        spans.append(date_hit[1])

    if time_hit:
        clock, span = time_hit
        spans.append(span)
        # 只講時間沒講日期，且時間已經過了，就當明天
        if date_hit is None and datetime.combine(day, clock, config.TZ) < datetime.now(config.TZ):
            day += timedelta(days=1)
    else:
        clock = time(config.WORK_START_HOUR)

    duration_hit = _parse_duration(text)
    if duration_hit:
        spans.append(duration_hit[1])

    return Parsed(
        start=datetime.combine(day, clock, config.TZ),
        has_time=time_hit is not None,
        duration_minutes=duration_hit[0] if duration_hit else None,
        spans=sorted(spans),
    )


def parse_date_only(text: str) -> tuple[date, tuple[int, int]] | None:
    """只解析日期，不管時間。給「查某天行程」這類用途。"""
    return _parse_date(text)


def has_weekday(text: str) -> bool:
    """句子裡是否指名了星期幾（用來區分「這週五」和「這週」）。"""
    return _RE_WEEKDAY.search(text) is not None


def strip_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """把被日期時間佔掉的區段挖掉，剩下的通常就是行程標題。"""
    result = []
    cursor = 0
    for start, end in spans:
        if start >= cursor:
            result.append(text[cursor:start])
            cursor = end
    result.append(text[cursor:])
    return "".join(result)
