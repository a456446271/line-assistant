"""Google Calendar 讀寫。

憑證用 refresh token 換 access token，google-auth 會自己處理續期，
所以這裡只要建一次 service 就好。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from functools import lru_cache

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

import config

_TOKEN_URI = "https://oauth2.googleapis.com/token"


@lru_cache(maxsize=1)
def _service():
    creds = Credentials(
        token=None,
        refresh_token=config.GOOGLE_REFRESH_TOKEN,
        client_id=config.GOOGLE_CLIENT_ID,
        client_secret=config.GOOGLE_CLIENT_SECRET,
        token_uri=_TOKEN_URI,
        scopes=config.GOOGLE_SCOPES,
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def parse_dt(value: str) -> datetime:
    """把模型或使用者給的時間字串轉成帶時區的 datetime。

    模型通常給 '2026-08-27T15:00:00' 這種不帶時區的字串，一律當成本地時間。
    """
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if len(text) == 10:  # 只有日期
        dt = datetime.fromisoformat(text)
    else:
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=config.TZ)
    return dt.astimezone(config.TZ)


def _event_time(node: dict) -> tuple[datetime, bool]:
    """Google 的全日行程回 date，一般行程回 dateTime，兩種都要處理。"""
    if "dateTime" in node:
        return parse_dt(node["dateTime"]), False
    return parse_dt(node["date"]), True


def list_events(start: datetime, end: datetime) -> list[dict]:
    """取出區間內的行程，已依開始時間排序。"""
    result = (
        _service()
        .events()
        .list(
            calendarId=config.GOOGLE_CALENDAR_ID,
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=100,
        )
        .execute()
    )

    events = []
    for item in result.get("items", []):
        if item.get("status") == "cancelled":
            continue
        started, all_day = _event_time(item["start"])
        ended, _ = _event_time(item["end"])
        events.append(
            {
                "id": item["id"],
                "title": item.get("summary", "(無標題)"),
                "start": started,
                "end": ended,
                "all_day": all_day,
                "location": item.get("location", ""),
            }
        )
    return events


def create_event(
    title: str,
    start_iso: str,
    end_iso: str,
    location: str = "",
    description: str = "",
    all_day: bool = False,
) -> dict:
    if all_day:
        # Google 的整天行程用 date 而非 dateTime，而且 end 是「不含」的，
        # 所以單日行程的 end 要是隔天。
        start_date = date.fromisoformat(start_iso[:10])
        end_date = date.fromisoformat(end_iso[:10]) if end_iso else start_date
        body = {
            "summary": title,
            "start": {"date": start_date.isoformat()},
            "end": {"date": (end_date + timedelta(days=1)).isoformat()},
        }
    else:
        body = {
            "summary": title,
            "start": {"dateTime": parse_dt(start_iso).isoformat(), "timeZone": config.TIMEZONE},
            "end": {"dateTime": parse_dt(end_iso).isoformat(), "timeZone": config.TIMEZONE},
        }
    if location:
        body["location"] = location
    if description:
        body["description"] = description

    created = (
        _service()
        .events()
        .insert(calendarId=config.GOOGLE_CALENDAR_ID, body=body)
        .execute()
    )
    return {"id": created["id"], "link": created.get("htmlLink", "")}


def delete_event(event_id: str) -> None:
    """刪掉一個行程。

    Google 沒有「封存」這種中間狀態，這是真的刪掉，救不回來。
    所以只從 LIFF 網頁按得到——那邊是點著清單上某一列刪的，
    不會有「AI 猜錯是哪一個」的問題。
    """
    _service().events().delete(
        calendarId=config.GOOGLE_CALENDAR_ID, eventId=event_id
    ).execute()


def _busy_intervals(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """算出忙碌區間。

    刻意不用 freeBusy API——它需要 calendar.readonly 以上的權限，
    而我們只要 calendar.events。用 events.list 自己算，權限維持最小。

    跳過標記為「有空」（transparent）的行程，以及整天行程——
    生日、節日這種整天事件不該讓一整天都算忙。
    """
    events = (
        _service()
        .events()
        .list(
            calendarId=config.GOOGLE_CALENDAR_ID,
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=250,
        )
        .execute()
        .get("items", [])
    )

    intervals = []
    for item in events:
        if item.get("status") == "cancelled" or item.get("transparency") == "transparent":
            continue
        if "dateTime" not in item.get("start", {}):
            continue
        intervals.append((parse_dt(item["start"]["dateTime"]), parse_dt(item["end"]["dateTime"])))
    return sorted(intervals)


def find_free_slots(
    start_date: date,
    end_date: date,
    duration_minutes: int,
) -> list[tuple[datetime, datetime]]:
    """在工作時段內找出長度足夠的空檔。"""
    window_start = datetime.combine(start_date, time(config.WORK_START_HOUR), config.TZ)
    window_end = datetime.combine(end_date, time(config.WORK_END_HOUR), config.TZ)
    busy = _busy_intervals(window_start, window_end)
    needed = timedelta(minutes=duration_minutes)

    slots: list[tuple[datetime, datetime]] = []
    day = start_date
    while day <= end_date:
        cursor = datetime.combine(day, time(config.WORK_START_HOUR), config.TZ)
        day_end = datetime.combine(day, time(config.WORK_END_HOUR), config.TZ)

        for busy_start, busy_end in busy:
            if busy_end <= cursor or busy_start >= day_end:
                continue
            if busy_start - cursor >= needed:
                slots.append((cursor, busy_start))
            cursor = max(cursor, busy_end)

        if day_end - cursor >= needed:
            slots.append((cursor, day_end))
        day += timedelta(days=1)

    return slots
