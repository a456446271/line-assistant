"""集中讀取環境變數。

刻意不在 import 時就對缺漏的設定拋錯，這樣 /healthz 仍然起得來，
可以透過 check_config() 得到一份人看得懂的缺漏清單。
"""

import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# --- Claude ---
ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
CLAUDE_MODEL = _get("CLAUDE_MODEL", "claude-opus-5")
CLAUDE_EFFORT = _get("CLAUDE_EFFORT", "low")

# Claude 是選填的兜底。留空就是純規則模式，完全不花 API 的錢，
# 代價是規則接不住的句子會回一句提示而不是想辦法理解。
LLM_ENABLED = bool(ANTHROPIC_API_KEY)

# --- LINE ---
LINE_CHANNEL_SECRET = _get("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = _get("LINE_CHANNEL_ACCESS_TOKEN")
ALLOWED_USER_IDS = [uid for uid in _get("ALLOWED_USER_IDS").split(",") if uid.strip()]

# --- LIFF（在 LINE 裡開的待辦網頁）---
# 兩個都設了才會啟用。LINE_CHANNEL_ID 是驗證 ID token 用的 audience，
# 沒有它就無法確認打進 /api 的人是誰，那等於把待辦清單公開在網路上。
LIFF_ID = _get("LIFF_ID")
LINE_CHANNEL_ID = _get("LINE_CHANNEL_ID")
LIFF_ENABLED = bool(LIFF_ID and LINE_CHANNEL_ID)
LIFF_URL = f"https://liff.line.me/{LIFF_ID}" if LIFF_ID else ""

# --- Google Calendar ---
GOOGLE_CLIENT_ID = _get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = _get("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = _get("GOOGLE_REFRESH_TOKEN")
GOOGLE_CALENDAR_ID = _get("GOOGLE_CALENDAR_ID", "primary")
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

# --- Notion ---
NOTION_TOKEN = _get("NOTION_TOKEN")
NOTION_EXPENSE_DB_ID = _get("NOTION_EXPENSE_DB_ID")
# 待辦與流程是選填的。沒設就當作沒有這個功能，相關規則直接跳過，
# 其他功能照常運作。
NOTION_TODO_DB_ID = _get("NOTION_TODO_DB_ID")
NOTION_SOP_DB_ID = _get("NOTION_SOP_DB_ID")
# 釘住這個版本：Notion 較新的 API 版本把 database_id 換成 data_source_id，
# 釘版本可以避開那次改版。
NOTION_VERSION = "2022-06-28"

# --- 記帳 ---
try:
    BUDGETS: dict[str, int] = json.loads(_get("BUDGET_JSON") or "{}")
except json.JSONDecodeError:
    BUDGETS = {}
CATEGORIES = list(BUDGETS.keys()) or ["餐飲", "交通", "購物", "娛樂", "居家", "醫療", "其他"]
BUDGET_ALERT_RATIO = float(_get("BUDGET_ALERT_RATIO", "0.8"))

# --- 排程 ---
CRON_SECRET = _get("CRON_SECRET")

# --- 其他 ---
TIMEZONE = _get("TIMEZONE", "Asia/Taipei")
TZ = ZoneInfo(TIMEZONE)
WORK_START_HOUR = int(_get("WORK_START_HOUR", "9"))
WORK_END_HOUR = int(_get("WORK_END_HOUR", "21"))


_REQUIRED = [
    "LINE_CHANNEL_SECRET",
    "LINE_CHANNEL_ACCESS_TOKEN",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REFRESH_TOKEN",
    "NOTION_TOKEN",
    "NOTION_EXPENSE_DB_ID",
    "CRON_SECRET",
]


def check_config() -> list[str]:
    """回傳尚未設定的必要環境變數名稱。"""
    return [name for name in _REQUIRED if not globals().get(name)]
