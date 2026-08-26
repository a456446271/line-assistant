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

# --- LINE ---
LINE_CHANNEL_SECRET = _get("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = _get("LINE_CHANNEL_ACCESS_TOKEN")
ALLOWED_USER_IDS = [uid for uid in _get("ALLOWED_USER_IDS").split(",") if uid.strip()]

# --- Google Calendar ---
GOOGLE_CLIENT_ID = _get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = _get("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = _get("GOOGLE_REFRESH_TOKEN")
GOOGLE_CALENDAR_ID = _get("GOOGLE_CALENDAR_ID", "primary")
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

# --- Notion ---
NOTION_TOKEN = _get("NOTION_TOKEN")
NOTION_EXPENSE_DB_ID = _get("NOTION_EXPENSE_DB_ID")
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
    "ANTHROPIC_API_KEY",
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
