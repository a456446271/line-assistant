"""FastAPI 進入點：LINE webhook 與排程端點。

Webhook 必須立刻回 200（LINE 對回應時間很敏感），但 Claude 推理要好幾秒，
所以實際處理一律丟進 BackgroundTasks，跑完再用 reply token 回覆。
"""

from __future__ import annotations

import hmac
import json
import logging
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path

from fastapi import BackgroundTasks, Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse

import agent
import calendar_api
import config
import expense_api
import line_api
import pending
import rules
import sop_api
import todo_api

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("line-assistant")

app = FastAPI(title="LINE 個人助理")

_ERROR_REPLY = "抱歉，剛剛出了點狀況，再說一次好嗎？"

# 純規則模式（沒設 ANTHROPIC_API_KEY）下，規則接不住時的回覆
_NO_RULE_REPLY = (
    "這句我看不懂。可以試試這些講法：\n"
    "・記帳：午餐 120\n"
    "・指定分類：娛樂 PS5 3000\n"
    "・查行程：今天有什麼安排\n"
    "・加行程：明天下午三點開會\n"
    "・查空檔：明天下午有空嗎\n"
    "・查消費：這個月花多少\n"
    "・加待辦：待辦 買牛奶\n"
    "・看待辦：待辦\n"
    "・查流程：收班流程"
)


@app.get("/healthz")
def healthz() -> dict:
    """健康檢查，順便回報設定狀態，方便遠端診斷。只回布林值與數量，不外洩任何值。"""
    missing = config.check_config()
    return {
        "ok": not missing,
        "missing_env": missing,
        "llm": config.LLM_ENABLED,  # False = 純規則模式，不花 API 錢
        "allowed_users": len(config.ALLOWED_USER_IDS),
        "model": config.CLAUDE_MODEL if config.LLM_ENABLED else None,
        "todo": todo_api.enabled(),
        "sop": sop_api.enabled(),
        "liff": config.LIFF_ENABLED,
    }


# --- LIFF：在 LINE 裡開的待辦網頁 ---


@lru_cache(maxsize=1)
def _liff_page() -> str:
    html = (Path(__file__).parent / "liff.html").read_text(encoding="utf-8")
    return html.replace("__LIFF_ID__", config.LIFF_ID)


@app.get("/liff", response_class=HTMLResponse)
def liff_page() -> str:
    if not config.LIFF_ENABLED:
        raise HTTPException(status_code=404, detail="LIFF 沒有啟用")
    return _liff_page()


def _liff_user(id_token: str) -> str:
    """驗證 LIFF 傳來的身分。這是這幾個 API 唯一的門，驗不過就擋掉。

    webhook 靠 channel secret 的簽章擋住外人，但 /api 是瀏覽器直接打的，
    只能靠 ID token。沒驗證的話待辦清單等於公開在網路上。
    """
    if not config.LIFF_ENABLED:
        raise HTTPException(status_code=404, detail="LIFF 沒有啟用")
    user_id = line_api.verify_id_token(id_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="身分驗證失敗")
    if config.ALLOWED_USER_IDS and user_id not in config.ALLOWED_USER_IDS:
        logger.warning("LIFF 拒絕未授權的 user_id=%s", user_id)
        raise HTTPException(status_code=403, detail="沒有權限")
    return user_id


def _row_json(row: dict) -> dict:
    return {
        "page_id": row["page_id"],
        "title": row["title"],
        "due": row["due"].isoformat() if row["due"] else None,
        "done_at": row["done_at"].isoformat() if row["done_at"] else None,
        "category": row["category"],
    }


def _todo_json() -> list[dict]:
    """回傳目前的未完成清單。每個寫入 API 都回這個，前端就不必自己維護狀態。"""
    return [_row_json(row) for row in todo_api.open_todos()]


@app.get("/api/todos")
def api_list_todos(x_line_id_token: str = Header("")) -> list[dict]:
    _liff_user(x_line_id_token)
    return _todo_json()


@app.get("/api/todos/done")
def api_list_done_todos(x_line_id_token: str = Header("")) -> list[dict]:
    _liff_user(x_line_id_token)
    return [_row_json(row) for row in todo_api.done_todos()]


@app.post("/api/todos/{page_id}/undone")
def api_uncomplete_todo(page_id: str, x_line_id_token: str = Header("")) -> list[dict]:
    _liff_user(x_line_id_token)
    todo_api.uncomplete_todo(page_id)
    return [_row_json(row) for row in todo_api.done_todos()]


@app.post("/api/todos")
def api_add_todo(
    payload: dict = Body(...),
    x_line_id_token: str = Header(""),
) -> list[dict]:
    _liff_user(x_line_id_token)
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="沒有內容")

    due = payload.get("due")
    todo_api.add_todo(
        title,
        date.fromisoformat(due) if due else None,
        str(payload.get("category") or ""),
    )
    return _todo_json()


@app.post("/api/todos/{page_id}/done")
def api_complete_todo(page_id: str, x_line_id_token: str = Header("")) -> list[dict]:
    _liff_user(x_line_id_token)
    todo_api.complete_todo(page_id)
    return _todo_json()


@app.delete("/api/todos/{page_id}")
def api_delete_todo(page_id: str, x_line_id_token: str = Header("")) -> list[dict]:
    _liff_user(x_line_id_token)
    todo_api.delete_todo(page_id)
    return _todo_json()


# --- LIFF：行程 ---
#
# 網頁上新增行程刻意不走確認卡片，跟對話的規矩不同。
# 卡片的存在是為了防「AI 把話解讀錯」，但這裡的日期時間是使用者自己在
# 表單上選的，沒有任何解讀的空間，表單本身就是確認。

_EVENT_DAYS = 21


def _events_json() -> list[dict]:
    now = datetime.now(config.TZ)
    start = datetime.combine(now.date(), time.min, config.TZ)
    events = calendar_api.list_events(start, start + timedelta(days=_EVENT_DAYS))
    return [
        {
            "id": event["id"],
            "title": event["title"],
            "start": event["start"].isoformat(),
            "end": event["end"].isoformat(),
            "all_day": event["all_day"],
            "location": event["location"],
        }
        for event in events
    ]


@app.get("/api/events")
def api_list_events(x_line_id_token: str = Header("")) -> list[dict]:
    _liff_user(x_line_id_token)
    return _events_json()


@app.post("/api/events")
def api_add_event(payload: dict = Body(...), x_line_id_token: str = Header("")) -> list[dict]:
    _liff_user(x_line_id_token)
    title = str(payload.get("title") or "").strip()
    day = str(payload.get("date") or "").strip()
    if not title or not day:
        raise HTTPException(status_code=400, detail="標題和日期都要填")

    # 沒填時間就當整天行程——生日、休假這種本來就沒有時間點
    clock = str(payload.get("time") or "").strip()
    if not clock:
        calendar_api.create_event(title, day, day, all_day=True)
        return _events_json()

    begin = datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=config.TZ)
    minutes = int(payload.get("minutes") or 60)
    calendar_api.create_event(
        title,
        begin.isoformat(),
        (begin + timedelta(minutes=minutes)).isoformat(),
        str(payload.get("location") or ""),
    )
    return _events_json()


@app.get("/api/free")
def api_free_slots(
    days: int = 7, minutes: int = 60, x_line_id_token: str = Header("")
) -> list[dict]:
    """工作時段內長度足夠的空檔。班表在行事曆裡，所以上班時間會自動被扣掉。"""
    _liff_user(x_line_id_token)
    today = datetime.now(config.TZ).date()
    slots = calendar_api.find_free_slots(
        today, today + timedelta(days=max(1, min(days, 30)) - 1), max(15, minutes)
    )
    return [
        {"start": begin.isoformat(), "end": finish.isoformat()} for begin, finish in slots
    ]


@app.delete("/api/events/{event_id}")
def api_delete_event(event_id: str, x_line_id_token: str = Header("")) -> list[dict]:
    _liff_user(x_line_id_token)
    calendar_api.delete_event(event_id)
    return _events_json()


# --- LIFF：記帳 ---


def _expenses_json(month: str) -> dict:
    start, end = agent._month_range(month)
    rows = expense_api.query_expenses(start, end)
    totals = expense_api.totals_by_category(rows)
    return {
        "month": f"{start:%Y-%m}",
        "total": sum(totals.values()),
        "totals": totals,
        "budgets": config.BUDGETS,
        "rows": list(reversed(rows)),  # 新的排前面，剛記的一眼就看到
    }


@app.get("/api/expenses")
def api_list_expenses(month: str = "", x_line_id_token: str = Header("")) -> dict:
    _liff_user(x_line_id_token)
    return _expenses_json(month)


@app.post("/api/expenses")
def api_add_expense(payload: dict = Body(...), x_line_id_token: str = Header("")) -> dict:
    _liff_user(x_line_id_token)
    item = str(payload.get("item") or "").strip()
    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="金額怪怪的")
    if not item or amount <= 0:
        raise HTTPException(status_code=400, detail="項目和金額都要填")

    spent_on = str(payload.get("date") or "") or datetime.now(config.TZ).date().isoformat()
    expense_api.add_expense(amount, str(payload.get("category") or ""), item, spent_on)
    return _expenses_json(spent_on[:7])


@app.delete("/api/expenses/{page_id}")
def api_delete_expense(
    page_id: str, month: str = "", x_line_id_token: str = Header("")
) -> dict:
    _liff_user(x_line_id_token)
    expense_api.archive_expense(page_id)
    return _expenses_json(month)


# --- LIFF：流程 ---


@app.get("/api/sops")
def api_list_sops(x_line_id_token: str = Header("")) -> list[dict]:
    _liff_user(x_line_id_token)
    if not sop_api.enabled():
        return []
    return [
        {
            "page_id": sop["page_id"],
            "name": sop["name"],
            "aliases": sop["aliases"],
            "category": sop["category"],
        }
        for sop in sop_api.list_sops(force=True)
    ]


@app.post("/api/sops")
def api_add_sop(payload: dict = Body(...), x_line_id_token: str = Header("")) -> list[dict]:
    _liff_user(x_line_id_token)
    name = str(payload.get("name") or "").strip()
    lines = [line for line in str(payload.get("steps") or "").splitlines() if line.strip()]
    if not name or not lines:
        raise HTTPException(status_code=400, detail="名稱和步驟都要填")

    sop_api.add_sop(name, lines, str(payload.get("category") or ""))
    return api_list_sops(x_line_id_token)


@app.get("/api/sops/{page_id}")
def api_get_sop(page_id: str, x_line_id_token: str = Header("")) -> dict:
    _liff_user(x_line_id_token)
    return {"steps": sop_api.steps(page_id)}


# --- Webhook ---


@app.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks) -> dict:
    body = await request.body()
    if not line_api.verify_signature(body, request.headers.get("X-Line-Signature", "")):
        raise HTTPException(status_code=403, detail="bad signature")

    payload = json.loads(body or b"{}")
    for event in payload.get("events", []):
        user_id = event.get("source", {}).get("userId", "")
        logger.info("event=%s user_id=%s", event.get("type"), user_id)

        if config.ALLOWED_USER_IDS and user_id not in config.ALLOWED_USER_IDS:
            logger.warning("拒絕未授權的 user_id=%s", user_id)
            continue

        reply_token = event.get("replyToken", "")
        if event["type"] == "message" and event["message"]["type"] == "text":
            background.add_task(
                _handle_text, user_id, reply_token, event["message"]["text"]
            )
        elif event["type"] == "postback":
            background.add_task(
                _handle_postback, user_id, reply_token, event["postback"]["data"]
            )

    return {"ok": True}


def _todo_card(rows: list[dict]) -> dict:
    today = datetime.now(config.TZ).date()
    return line_api.todo_list_card(rows, today, len(rows), config.LIFF_URL)


def _describe(start_iso: str, end_iso: str) -> str:
    start = calendar_api.parse_dt(start_iso)
    end = calendar_api.parse_dt(end_iso)
    weekday = "一二三四五六日"[start.weekday()]
    return f"{start:%Y/%m/%d}({weekday}) {start:%H:%M}-{end:%H:%M}"


def _handle_text(user_id: str, reply_token: str, user_text: str) -> None:
    line_api.show_loading(user_id)
    try:
        # 常見句型先讓規則層接，接不住才花錢叫 Claude。
        result = rules.try_handle(user_text)
        if result is not None:
            logger.info("由規則層處理")
        elif config.LLM_ENABLED:
            result = agent.run(user_text)
        else:
            logger.info("規則接不住，且未啟用 Claude")
            result = agent.AgentResult(text=_NO_RULE_REPLY)
    except Exception:
        logger.exception("處理訊息失敗")
        line_api.reply(reply_token, [line_api.text(_ERROR_REPLY)])
        return

    if result.created_expense:
        # 記帳的回覆本身就帶撤銷按鈕，不用再多送一則純文字。
        messages = [line_api.expense_card(result.text, result.created_expense["page_id"])]
    elif result.todo_list:
        # 用卡片而不是純文字，這樣每一列都能直接按完成或刪除，不用再打字回覆。
        messages = [_todo_card(result.todo_list)]
        if result.text:
            messages.insert(0, line_api.text(result.text))
    elif result.pending_event:
        event = result.pending_event
        pending_id = pending.put(event)
        messages = [
            line_api.event_confirm_card(
                pending_id,
                _describe(event["start"], event["end"]),
                event["title"],
                event["location"],
            )
        ]
        if result.text:
            messages.insert(0, line_api.text(result.text))
    else:
        messages = [line_api.text(result.text)]

    try:
        line_api.reply(reply_token, messages)
    except Exception:
        logger.exception("回覆失敗")


def _handle_postback(user_id: str, reply_token: str, data: str) -> None:
    params = line_api.parse_postback(data)
    action = params.get("action", "")

    messages: list[dict] = []
    try:
        if action == "confirm_event":
            event = pending.take(params.get("pid", ""))
            if event is None:
                message = "這張卡片已經用過或過期了，再跟我說一次行程內容吧。"
            else:
                calendar_api.create_event(
                    event["title"],
                    event["start"],
                    event["end"],
                    event["location"],
                    event["description"],
                )
                message = f"已加入行事曆：{_describe(event['start'], event['end'])} {event['title']}"

        elif action == "cancel_event":
            pending.take(params.get("pid", ""))
            message = "好，沒有加入。"

        elif action == "undo_expense":
            expense_api.archive_expense(params.get("page_id", ""))
            message = "已撤銷這筆記帳。"

        elif action in ("done_todo", "delete_todo"):
            page_id = params.get("page_id", "")
            if action == "done_todo":
                message = f"已完成：{todo_api.complete_todo(page_id)}"
            else:
                message = f"已刪除：{todo_api.delete_todo(page_id)}"
            # 順便把更新後的清單再送一次，這樣要連續處理好幾筆時不用重打「待辦」
            rows = todo_api.open_todos()
            if rows:
                messages = [_todo_card(rows)]
            else:
                message += "\n待辦都清完了。"

        else:
            message = "不認得這個動作。"

    except Exception:
        logger.exception("postback 處理失敗 action=%s", action)
        message = _ERROR_REPLY
        messages = []

    try:
        line_api.reply(reply_token, [line_api.text(message), *messages])
    except Exception:
        logger.exception("回覆失敗")


# --- 排程 ---


def _push_all(messages: list[dict]) -> int:
    for user_id in config.ALLOWED_USER_IDS:
        line_api.push(user_id, messages)
    return len(config.ALLOWED_USER_IDS)


def _todo_digest(today) -> str:
    """今天（含逾期）該處理的待辦。沒有就回空字串。

    待辦本來要自己想到才會去問，放進早報才真的會被看到。
    只列到期的，沒期限的不推——那些推了只會變成每天都在的雜訊。
    """
    if not todo_api.enabled():
        return ""
    try:
        rows = todo_api.due_by(today)
    except Exception:
        logger.exception("早報取待辦失敗")
        return ""
    return "\n".join(
        f"・{row['title']}" + (f"（逾期 {(today - row['due']).days} 天）" if row["due"] < today else "")
        for row in rows
    )


def _job_daily() -> dict:
    today = datetime.now(config.TZ).date()
    start = datetime.combine(today, time.min, config.TZ)
    events = calendar_api.list_events(start, start + timedelta(days=1))
    listing = "\n".join(f"・{agent.fmt_event(event)}" for event in events)
    todos = _todo_digest(today)

    if config.LLM_ENABLED:
        body = agent.summarize(
            "這是使用者今天的行程與待辦，請寫一段簡短的早安摘要（三到五行，口語一點，"
            "點出時間壓力或空檔，逾期的待辦要特別提）：\n"
            f"行程：\n{listing or '（沒有行程）'}\n"
            f"今天到期的待辦：\n{todos or '（沒有）'}"
        )
    else:
        # 沒啟用 Claude 就直接排版，早報本來也不一定要 AI 潤稿
        parts = [f"今天有 {len(events)} 個行程：\n{listing}" if events else "今天沒有安排的行程。"]
        if todos:
            parts.append(f"該處理的待辦：\n{todos}")
        body = "\n\n".join(parts)

    return {"job": "daily", "pushed_to": _push_all([line_api.text(f"早安！\n\n{body}")])}


def _job_monthly() -> dict:
    """報告「上一個完整月份」。

    排在每月 1 號跑，這樣統計的一定是完整的一個月，
    也避開了 cron 沒辦法表達「每月最後一天」的問題。
    """
    today = datetime.now(config.TZ).date()
    target_end = today.replace(day=1) - timedelta(days=1)
    target_start = target_end.replace(day=1)
    prior_end = target_start - timedelta(days=1)
    prior_start = prior_end.replace(day=1)

    target = expense_api.totals_by_category(
        expense_api.query_expenses(target_start, target_end)
    )
    prior = expense_api.totals_by_category(
        expense_api.query_expenses(prior_start, prior_end)
    )

    if config.LLM_ENABLED:
        body = agent.summarize(
            "這是使用者的月度消費統計，請寫一段簡短的月報（分類佔比、與前一個月比較、"
            "點出異常支出，五到八行）：\n"
            f"{target_start:%Y年%m月}：{target}\n"
            f"{prior_start:%Y年%m月}：{prior}\n"
            f"每月預算：{config.BUDGETS}"
        )
    else:
        # 沒啟用 Claude 就直接列數字：各分類金額與跟上個月的增減
        lines = []
        for name in config.CATEGORIES:
            amount = target.get(name, 0)
            if not amount:
                continue
            diff = amount - prior.get(name, 0)
            arrow = f"（較上月 {'+' if diff >= 0 else ''}${diff:,.0f}）" if diff else ""
            lines.append(f"・{name} ${amount:,.0f}{arrow}")
        total = sum(target.values())
        body = f"總支出 ${total:,.0f}\n" + ("\n".join(lines) or "（沒有任何紀錄）")
    header = f"{target_start:%Y年%m月}消費月報\n\n"
    return {"job": "monthly", "pushed_to": _push_all([line_api.text(header + body)])}


def _job_budget() -> dict:
    """只有超標才推播，避免浪費每月 200 則的免費額度。"""
    today = datetime.now(config.TZ).date()
    totals = expense_api.totals_by_category(
        expense_api.query_expenses(today.replace(day=1), today)
    )

    alerts = []
    for name, budget in config.BUDGETS.items():
        spent = totals.get(name, 0)
        if budget > 0 and spent >= budget * config.BUDGET_ALERT_RATIO:
            ratio = spent / budget * 100
            alerts.append(f"・{name} ${spent:g}/${budget:g}（{ratio:.0f}%）")

    if not alerts:
        return {"job": "budget", "pushed_to": 0}

    body = "本月這些分類快超支了：\n" + "\n".join(alerts)
    return {"job": "budget", "pushed_to": _push_all([line_api.text(body)])}


_JOBS = {"daily": _job_daily, "monthly": _job_monthly, "budget": _job_budget}


@app.api_route("/cron", methods=["GET", "POST"])
def cron(key: str = "", job: str = "") -> dict:
    if not config.CRON_SECRET or not hmac.compare_digest(key, config.CRON_SECRET):
        raise HTTPException(status_code=403, detail="bad key")
    if job not in _JOBS:
        raise HTTPException(status_code=400, detail=f"job 必須是 {list(_JOBS)} 其中之一")

    try:
        return _JOBS[job]()
    except Exception:
        logger.exception("排程 %s 執行失敗", job)
        raise HTTPException(status_code=500, detail="job failed")
