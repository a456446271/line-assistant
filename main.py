"""FastAPI 進入點：LINE webhook 與排程端點。

Webhook 必須立刻回 200（LINE 對回應時間很敏感），但 Claude 推理要好幾秒，
所以實際處理一律丟進 BackgroundTasks，跑完再用 reply token 回覆。
"""

from __future__ import annotations

import hmac
import json
import logging
from datetime import datetime, time, timedelta

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

import agent
import calendar_api
import config
import expense_api
import line_api
import pending
import rules

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
    "・查消費：這個月花多少"
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
    }


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

        else:
            message = "不認得這個動作。"

    except Exception:
        logger.exception("postback 處理失敗 action=%s", action)
        message = _ERROR_REPLY

    try:
        line_api.reply(reply_token, [line_api.text(message)])
    except Exception:
        logger.exception("回覆失敗")


# --- 排程 ---


def _push_all(messages: list[dict]) -> int:
    for user_id in config.ALLOWED_USER_IDS:
        line_api.push(user_id, messages)
    return len(config.ALLOWED_USER_IDS)


def _job_daily() -> dict:
    today = datetime.now(config.TZ).date()
    start = datetime.combine(today, time.min, config.TZ)
    events = calendar_api.list_events(start, start + timedelta(days=1))

    if not events:
        body = "今天沒有安排的行程。"
    else:
        listing = "\n".join(f"・{agent.fmt_event(event)}" for event in events)
        # 沒啟用 Claude 就直接排版，早報本來也不一定要 AI 潤稿
        body = (
            agent.summarize(
                "這是使用者今天的行程，請寫一段簡短的早安摘要（三到五行，口語一點，"
                f"點出時間壓力或空檔）：\n{listing}"
            )
            if config.LLM_ENABLED
            else f"今天有 {len(events)} 個行程：\n{listing}"
        )

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
