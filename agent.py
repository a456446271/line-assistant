"""Claude 大腦：定義工具、組 system prompt、跑 tool runner。

新增行程刻意不直接寫入。propose_create_event 只把解析結果放進 TurnContext，
由呼叫端組成確認卡片，使用者按下確認後才真的寫進 Google Calendar。
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import anthropic
from anthropic import beta_tool

import calendar_api
import config
import expense_api
import sop_api
import todo_api

_WEEKDAYS = "一二三四五六日"


@dataclass
class TurnContext:
    """這一輪對話中，工具產生的、需要讓呼叫端知道的副作用。"""

    pending_event: dict | None = None
    created_expense: dict | None = None
    todo_list: list[dict] | None = None


_ctx: ContextVar[TurnContext] = ContextVar("turn_context")


@dataclass
class AgentResult:
    text: str
    pending_event: dict | None = None
    created_expense: dict | None = None
    # 有值時（可能是空 list）呼叫端要改用待辦清單卡片回覆，讓每列都能直接勾完成
    todo_list: list[dict] | None = None


def _now() -> datetime:
    return datetime.now(config.TZ)


def _fmt_dt(value: datetime) -> str:
    return f"{value.month}/{value.day}({_WEEKDAYS[value.weekday()]}) {value:%H:%M}"


def fmt_event(event: dict) -> str:
    if event["all_day"]:
        head = f"{event['start'].month}/{event['start'].day}"
        head += f"({_WEEKDAYS[event['start'].weekday()]}) 整天"
    else:
        head = f"{_fmt_dt(event['start'])}-{event['end']:%H:%M}"
    line = f"{head} {event['title']}"
    if event["location"]:
        line += f" @ {event['location']}"
    return line


def _month_range(month: str) -> tuple[date, date]:
    """'2026-08' 或空字串（本月）轉成該月的起訖日。"""
    today = _now().date()
    if month:
        year, mon = (int(part) for part in month.split("-")[:2])
    else:
        year, mon = today.year, today.month
    start = date(year, mon, 1)
    end = date(year + (mon == 12), (mon % 12) + 1, 1) - timedelta(days=1)
    return start, end


# --- 工具（唯讀） ---


@beta_tool
def list_events(start: str, end: str) -> str:
    """查詢某段時間內的行事曆行程。

    Args:
        start: 區間開始時間，ISO 格式，例如 2026-08-27T00:00:00
        end: 區間結束時間，ISO 格式，例如 2026-08-27T23:59:59
    """
    events = calendar_api.list_events(
        calendar_api.parse_dt(start), calendar_api.parse_dt(end)
    )
    if not events:
        return "這段時間沒有任何行程。"
    return "\n".join(fmt_event(event) for event in events)


@beta_tool
def find_free_slots(start_date: str, end_date: str, duration_minutes: int = 60) -> str:
    """在指定日期範圍內找出足夠長的空檔，用來回答「哪天有空」這類問題。

    Args:
        start_date: 開始日期，YYYY-MM-DD
        end_date: 結束日期，YYYY-MM-DD
        duration_minutes: 需要的空檔長度（分鐘），預設 60
    """
    slots = calendar_api.find_free_slots(
        date.fromisoformat(start_date), date.fromisoformat(end_date), duration_minutes
    )
    if not slots:
        return "這段期間找不到足夠長的空檔。"
    return "\n".join(f"{_fmt_dt(begin)}-{finish:%H:%M}" for begin, finish in slots)


@beta_tool
def query_expenses(start_date: str, end_date: str, category: str = "") -> str:
    """查詢某段期間的消費明細與加總。

    Args:
        start_date: 開始日期，YYYY-MM-DD
        end_date: 結束日期，YYYY-MM-DD
        category: 只看某個分類，留空代表全部
    """
    rows = expense_api.query_expenses(
        date.fromisoformat(start_date), date.fromisoformat(end_date), category or None
    )
    if not rows:
        return "這段期間沒有任何消費紀錄。"

    totals = expense_api.totals_by_category(rows)
    detail = "\n".join(
        f"{row['date']} {row['item']} ${row['amount']:g}（{row['category']}）" for row in rows
    )
    summary = "\n".join(f"{name} ${amount:g}" for name, amount in totals.items())
    return f"明細：\n{detail}\n\n分類小計：\n{summary}\n總計 ${sum(totals.values()):g}"


@beta_tool
def get_budget_status(month: str = "") -> str:
    """查詢某個月各分類的預算使用狀況。

    Args:
        month: 月份，格式 YYYY-MM，留空代表本月
    """
    start, end = _month_range(month)
    totals = expense_api.totals_by_category(expense_api.query_expenses(start, end))

    lines = []
    for name, budget in config.BUDGETS.items():
        spent = totals.get(name, 0)
        lines.append(f"{name} ${spent:g}/${budget:g}（剩 ${budget - spent:g}）")
    return f"{start:%Y年%m月} 預算狀況：\n" + "\n".join(lines)


@beta_tool
def list_todos() -> str:
    """列出所有還沒完成的待辦事項。使用者問「有什麼事要做」「待辦」時用這個。"""
    rows = todo_api.open_todos()
    _ctx.get().todo_list = rows
    if not rows:
        return "目前沒有未完成的待辦。"
    return (
        "已經把清單做成可勾選的卡片給使用者了。"
        "請只用一句話總結（例如有幾筆、哪幾筆逾期），不要逐條複述。\n"
        + "\n".join(
            f"{row['title']}（{row['due'] or '沒有期限'}）" for row in rows
        )
    )


@beta_tool
def get_sop(name: str) -> str:
    """查一份流程／SOP 的步驟，例如「收班流程」「印保證卡流程」。

    Args:
        name: 流程名稱或關鍵字
    """
    sop = sop_api.find(name)
    if sop is None:
        names = "、".join(item["name"] for item in sop_api.list_sops())
        return f"找不到這份流程。目前有的流程：{names or '（一份都沒有）'}"
    lines = sop_api.steps(sop["page_id"])
    if not lines:
        return f"「{sop['name']}」這份流程還沒有寫任何步驟。"
    body = "\n".join(f"{index}. {line}" for index, line in enumerate(lines, 1))
    return f"{sop['name']}\n{body}\n\n請原樣呈現這些步驟，不要改寫或補充。"


# --- 工具（寫入） ---


@beta_tool
def propose_create_event(
    title: str,
    start: str,
    end: str,
    location: str = "",
    description: str = "",
) -> str:
    """提議新增一個行程。這不會直接寫入行事曆，只會產生一張確認卡片給使用者按。

    Args:
        title: 行程標題
        start: 開始時間，ISO 格式，例如 2026-09-01T15:00:00
        end: 結束時間，ISO 格式。使用者沒說多久就抓一小時
        location: 地點，沒有就留空
        description: 備註，沒有就留空
    """
    _ctx.get().pending_event = {
        "title": title,
        "start": start,
        "end": end,
        "location": location,
        "description": description,
    }
    return (
        "已產生確認卡片。請只用一句話告訴使用者確認一下，"
        "不要重複行程細節，卡片上已經有了。"
    )


@beta_tool
def add_expense(amount: float, item: str, category: str, spent_on: str = "") -> str:
    """記錄一筆消費。

    Args:
        amount: 金額（新台幣）
        item: 消費項目，例如「午餐」「星巴克咖啡」
        category: 分類，必須是允許的分類之一
        spent_on: 消費日期，YYYY-MM-DD，留空代表今天
    """
    spent = spent_on or _now().date().isoformat()
    result = expense_api.add_expense(amount, category, item, spent)
    _ctx.get().created_expense = result
    return (
        f"已記錄 {result['item']} ${result['amount']:g}（{result['category']}）。"
        "請只用一句話確認，不要重複細節。"
    )


@beta_tool
def add_todo(title: str, due: str = "", category: str = "") -> str:
    """新增一筆待辦事項。沒有明確時間點、只是「要記得做」的事情用這個，
    有明確時間的行程要用 propose_create_event。

    Args:
        title: 待辦內容
        due: 期限，YYYY-MM-DD，沒講期限就留空
        category: 分類，只能是 工作／家裡／購物／其他，判斷不出來就留空
    """
    result = todo_api.add_todo(
        title, date.fromisoformat(due) if due else None, category
    )
    return f"已加入待辦：{result['title']}。請只用一句話確認。"


@beta_tool
def add_sop(name: str, steps: str) -> str:
    """新增一份流程／SOP。

    Args:
        name: 流程名稱，例如「收班流程」
        steps: 步驟，一行一步，用換行分隔
    """
    lines = [line for line in steps.splitlines() if line.strip()]
    if not lines:
        return "沒有任何步驟，沒有建立。請問使用者流程的內容。"
    result = sop_api.add_sop(name, lines)
    return f"已建立流程「{result['name']}」，共 {result['count']} 步。請只用一句話確認。"


TOOLS = [
    list_events,
    find_free_slots,
    query_expenses,
    get_budget_status,
    propose_create_event,
    add_expense,
]

# 待辦與流程是選填功能，沒設資料庫就不要給模型這些工具，
# 否則它會呼叫一個必定失敗的東西。
if todo_api.enabled():
    TOOLS += [list_todos, add_todo]
if sop_api.enabled():
    TOOLS += [get_sop, add_sop]


def _date_reference() -> str:
    """列出近兩週的實際日期。

    直接把日曆攤開給模型看，比讓它自己算「下週二」可靠得多。
    """
    today = _now().date()
    lines = []
    for offset in range(14):
        day = today + timedelta(days=offset)
        label = {0: "（今天）", 1: "（明天）", 2: "（後天）"}.get(offset, "")
        lines.append(f"{day.isoformat()} 星期{_WEEKDAYS[day.weekday()]}{label}")
    return "\n".join(lines)


def _extra_rules() -> str:
    """待辦與流程沒開啟時，這些規則講了也沒用，只會佔 token。"""
    rules = []
    if todo_api.enabled():
        rules.append(
            "- 有明確時間點的事（三點開會）走 propose_create_event；"
            "只是「要記得做」而沒有時間的（買牛奶、繳費）走 add_todo。分不出來時問一句。"
        )
    if sop_api.enabled():
        rules.append(
            "- 問「某某流程」「怎麼做某事」時呼叫 get_sop，並原樣列出步驟，不要自己改寫或補充。"
            "找不到就照實說找不到，絕對不要憑常識編一套流程出來。"
        )
    return ("\n" + "\n".join(rules)) if rules else ""


def _system_prompt() -> str:
    now = _now()
    budgets = "、".join(f"{name} ${amount:g}" for name, amount in config.BUDGETS.items())
    return f"""你是使用者的個人助理，透過 LINE 對話，負責行事曆與記帳。

現在時間：{now:%Y-%m-%d %H:%M} 星期{_WEEKDAYS[now.weekday()]}（{config.TIMEZONE}）

接下來兩週的日期對照：
{_date_reference()}

記帳分類只能用這幾個（必須完全一致）：{"、".join(config.CATEGORIES)}
每月預算：{budgets}

規則：
- 一律用繁體中文回覆。
- 這是手機上的聊天視窗，回覆要簡短。不要用 markdown 表格或標題，LINE 不會渲染。條列用「・」開頭。
- 使用者說要安排、預約、開會、提醒某個時間做某事時，呼叫 propose_create_event。
  絕對不要假裝行程已經建立，卡片還沒被按下之前它並不存在。
- 使用者提到花了多少錢時，呼叫 add_expense。金額沒講單位就當新台幣。
- 講到「今天」「明天」「下週二」時，對照上面的日期表換算成實際日期再呼叫工具。
- 沒講結束時間的行程一律抓一小時。
- 查完資料後直接講結論，不要複述你呼叫了哪些工具。
- 資料裡沒有的事就說沒有，不要編。{_extra_rules()}"""


def run(user_text: str) -> AgentResult:
    """跑一輪對話。回傳文字回覆，以及這一輪產生的副作用。"""
    context = TurnContext()
    token = _ctx.set(context)
    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        runner = client.beta.messages.tool_runner(
            model=config.CLAUDE_MODEL,
            max_tokens=4096,
            system=_system_prompt(),
            tools=TOOLS,
            messages=[{"role": "user", "content": user_text}],
            thinking={"type": "adaptive"},
            output_config={"effort": config.CLAUDE_EFFORT},
        )

        final = None
        for message in runner:
            final = message
    finally:
        _ctx.reset(token)

    if final is None:
        return AgentResult(text="抱歉，這次沒有拿到回覆，再說一次好嗎？")

    if final.stop_reason == "refusal":
        return AgentResult(text="抱歉，這個請求我沒辦法處理。")

    text = "\n".join(
        block.text for block in final.content if block.type == "text" and block.text.strip()
    ).strip()

    return AgentResult(
        text=text or "（沒有內容）",
        pending_event=context.pending_event,
        created_expense=context.created_expense,
        todo_list=context.todo_list,
    )


def summarize(prompt: str) -> str:
    """給排程用的單純生成，不帶工具。"""
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=1024,
        system=_system_prompt(),
        messages=[{"role": "user", "content": prompt}],
        thinking={"type": "adaptive"},
        output_config={"effort": config.CLAUDE_EFFORT},
    )
    return "\n".join(
        block.text for block in message.content if block.type == "text"
    ).strip()
