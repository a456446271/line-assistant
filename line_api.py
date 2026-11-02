"""LINE Messaging API：簽章驗證、送訊息、組卡片。

計費重點：reply 不計入每月推播額度，push 會。
所以對話一律走 reply，只有排程通知才用 push。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from urllib.parse import parse_qsl

import httpx

import config

_API = "https://api.line.me/v2/bot"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def verify_signature(body: bytes, signature: str) -> bool:
    expected = base64.b64encode(
        hmac.new(config.LINE_CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(expected, signature or "")


def parse_postback(data: str) -> dict[str, str]:
    return dict(parse_qsl(data))


def show_loading(user_id: str, seconds: int = 30) -> None:
    """讓對話框顯示「輸入中」動畫。失敗不影響主流程，所以吞掉錯誤。"""
    try:
        httpx.post(
            f"{_API}/chat/loading/start",
            headers=_headers(),
            json={"chatId": user_id, "loadingSeconds": seconds},
            timeout=10,
        )
    except httpx.HTTPError:
        pass


def reply(reply_token: str, messages: list[dict]) -> None:
    response = httpx.post(
        f"{_API}/message/reply",
        headers=_headers(),
        json={"replyToken": reply_token, "messages": messages[:5]},
        timeout=20,
    )
    response.raise_for_status()


def push(user_id: str, messages: list[dict]) -> None:
    response = httpx.post(
        f"{_API}/message/push",
        headers=_headers(),
        json={"to": user_id, "messages": messages[:5]},
        timeout=20,
    )
    response.raise_for_status()


# --- 訊息組裝 ---


def text(content: str) -> dict:
    # LINE 單則文字上限 5000 字，超過會整包被拒。
    return {"type": "text", "text": content[:4900]}


# --- 卡片 ---
#
# 配色跟 LIFF 網頁一致，兩邊看起來才像同一個東西。
# Flex 不會跟著手機切深色模式，所以這裡寫死淺色。

_GREEN = "#06C755"
_INK = "#1C1C1E"
_DIM = "#8A8A8E"
_FAINT = "#C4C4C8"
_TRACK = "#ECECEF"
_SOFT = "#F2F2F7"
_RED = "#E5484D"
_AMBER = "#E8890C"

_WEEK = "一二三四五六日"

# 一張卡片列太多會被 LINE 截斷，而且在手機上也滑不完
_MAX_EVENTS = 15


def _money(amount: float) -> str:
    return f"${amount:,.0f}"


def _header(kicker: str, title: str, color: str = _GREEN) -> dict:
    """卡片頂端：一行彩色小字標類別，底下一行粗體標題。"""
    return {
        "type": "box",
        "layout": "vertical",
        "contents": [
            {"type": "text", "text": kicker, "size": "xs", "weight": "bold", "color": color},
            {"type": "text", "text": title, "size": "lg", "weight": "bold", "color": _INK,
             "wrap": True, "margin": "xs"},
        ],
    }


def _bar(ratio: float, color: str) -> dict:
    """進度條。ratio 可以超過 1，畫的時候封頂在 100%。"""
    track: dict = {
        "type": "box",
        "layout": "vertical",
        "height": "6px",
        "cornerRadius": "3px",
        "backgroundColor": _TRACK,
        "margin": "sm",
        "contents": [],
    }
    if ratio > 0:
        # 太短的話圓角會吃掉整條，看起來像沒有，給個最小寬度
        width = max(3, min(100, round(ratio * 100)))
        track["contents"] = [
            {"type": "box", "layout": "vertical", "width": f"{width}%", "height": "6px",
             "cornerRadius": "3px", "backgroundColor": color, "contents": []}
        ]
    return track


def _tag(label: str) -> dict:
    return {
        "type": "box",
        "layout": "vertical",
        "flex": 0,
        "cornerRadius": "10px",
        "backgroundColor": _SOFT,
        "paddingStart": "8px",
        "paddingEnd": "8px",
        "paddingTop": "2px",
        "paddingBottom": "2px",
        "contents": [{"type": "text", "text": label, "size": "xxs", "color": _DIM}],
    }


def _link_footer(label: str, uri: str) -> dict:
    return {
        "type": "box",
        "layout": "vertical",
        "contents": [
            {"type": "button", "style": "link", "height": "sm", "color": _GREEN,
             "action": {"type": "uri", "label": label, "uri": uri}},
        ],
    }


def _bubble(body: list[dict], footer: dict | None = None, size: str = "mega") -> dict:
    bubble: dict = {
        "type": "bubble",
        "size": size,
        "body": {"type": "box", "layout": "vertical", "spacing": "md",
                 "paddingAll": "18px", "contents": body},
    }
    if footer:
        bubble["footer"] = footer
    return bubble


def _flex(alt: str, bubble: dict) -> dict:
    # altText 是通知與聊天列表的預覽文字，上限 400 字
    return {"type": "flex", "altText": alt[:400], "contents": bubble}


def _liff(tab: str) -> str:
    return f"{config.LIFF_URL}?tab={tab}" if config.LIFF_URL else ""


def _row(label: str, value: str) -> dict:
    return {
        "type": "box",
        "layout": "baseline",
        "spacing": "sm",
        "contents": [
            {"type": "text", "text": label, "color": _DIM, "size": "sm", "flex": 2},
            {"type": "text", "text": value, "size": "sm", "color": _INK, "flex": 5, "wrap": True},
        ],
    }


def event_confirm_card(pending_id: str, when: str, title: str, location: str) -> dict:
    rows = [_row("時間", when), _row("項目", title)]
    if location:
        rows.append(_row("地點", location))

    body = [
        _header("新增行程", "要加入行事曆嗎？"),
        {"type": "separator", "color": _TRACK},
        {"type": "box", "layout": "vertical", "spacing": "sm", "contents": rows},
    ]
    footer = {
        "type": "box",
        "layout": "horizontal",
        "spacing": "sm",
        "contents": [
            {
                "type": "button",
                "style": "secondary",
                "height": "sm",
                "action": {
                    "type": "postback",
                    "label": "取消",
                    "data": f"action=cancel_event&pid={pending_id}",
                },
            },
            {
                "type": "button",
                "style": "primary",
                "height": "sm",
                "color": _GREEN,
                "action": {
                    "type": "postback",
                    "label": "確認新增",
                    "data": f"action=confirm_event&pid={pending_id}",
                    "displayText": "確認新增",
                },
            },
        ],
    }
    return _flex(f"要新增行程「{title}」嗎？", _bubble(body, footer))


def expense_card(expense: dict) -> dict:
    """記帳成功的回覆，附一顆撤銷按鈕。

    記帳不做事前確認（每筆都確認太煩），改成事後可撤銷。
    """
    alt = f"已記錄 {expense['item']} {_money(expense['amount'])}（{expense['category']}）"
    body = [
        {"type": "text", "text": "✓ 已記帳", "size": "xs", "weight": "bold", "color": _GREEN},
        {
            "type": "box",
            "layout": "horizontal",
            "alignItems": "center",
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "flex": 1,
                    "spacing": "xs",
                    "contents": [
                        {"type": "text", "text": expense["item"], "size": "md",
                         "weight": "bold", "color": _INK, "wrap": True},
                        {"type": "box", "layout": "horizontal",
                         "contents": [_tag(expense["category"])]},
                    ],
                },
                {"type": "text", "text": _money(expense["amount"]), "size": "xl",
                 "weight": "bold", "color": _INK, "flex": 0, "align": "end"},
            ],
        },
    ]
    footer = {
        "type": "box",
        "layout": "vertical",
        "contents": [
            {
                "type": "button",
                "style": "link",
                "height": "sm",
                "color": _DIM,
                "action": {
                    "type": "postback",
                    "label": "撤銷這筆",
                    "data": f"action=undo_expense&page_id={expense['page_id']}",
                },
            }
        ],
    }
    return _flex(alt, _bubble(body, footer, size="kilo"))


def _event_line(event: dict) -> dict:
    """行程的一列：左邊色條、時間，右邊名稱與地點。整天的用橘色條。"""
    if event["all_day"]:
        when = [{"type": "text", "text": "整天", "size": "sm", "weight": "bold", "color": _AMBER}]
        color = _AMBER
    else:
        when = [
            {"type": "text", "text": f"{event['start']:%H:%M}", "size": "sm",
             "weight": "bold", "color": _INK},
            {"type": "text", "text": f"{event['end']:%H:%M}", "size": "xs", "color": _DIM},
        ]
        color = _GREEN

    detail = [{"type": "text", "text": event["title"], "size": "sm", "color": _INK, "wrap": True}]
    if event["location"]:
        detail.append({"type": "text", "text": event["location"], "size": "xs",
                       "color": _DIM, "wrap": True})

    return {
        "type": "box",
        "layout": "horizontal",
        "spacing": "md",
        "contents": [
            {"type": "box", "layout": "vertical", "width": "4px", "cornerRadius": "2px",
             "backgroundColor": color, "contents": []},
            {"type": "box", "layout": "vertical", "width": "44px", "contents": when},
            {"type": "box", "layout": "vertical", "flex": 1, "contents": detail},
        ],
    }


def _day_head(day) -> dict:
    return {"type": "text", "text": f"{day.month}/{day.day}（{_WEEK[day.weekday()]}）",
            "size": "xs", "weight": "bold", "color": _DIM, "margin": "lg"}


def _event_lines(events: list[dict], multi_day: bool) -> list[dict]:
    lines: list[dict] = []
    last_day = None
    for event in events[:_MAX_EVENTS]:
        day = event["start"].date()
        if multi_day and day != last_day:
            lines.append(_day_head(day))
            last_day = day
        lines.append(_event_line(event))
    if len(events) > _MAX_EVENTS:
        lines.append({"type": "text", "text": f"⋯ 還有 {len(events) - _MAX_EVENTS} 個",
                      "size": "xs", "color": _DIM})
    return lines


def schedule_card(label: str, events: list[dict], multi_day: bool, alt: str) -> dict:
    """查行程的回覆。多天的依日期分段。"""
    body = [
        _header("行程", f"{label}的行程（{len(events)}）"),
        {"type": "separator", "color": _TRACK},
        {"type": "box", "layout": "vertical", "spacing": "md",
         "contents": _event_lines(events, multi_day)},
    ]
    uri = _liff("event")
    return _flex(alt, _bubble(body, _link_footer("開啟行程", uri) if uri else None))


def budget_card(month: int, totals: dict[str, float], budgets: dict[str, float], alt: str) -> dict:
    """本月預算：每個分類一條進度條，八成以上變橘、超過變紅。"""
    rows: list[dict] = []
    for name, budget in budgets.items():
        spent = totals.get(name, 0)
        ratio = spent / budget if budget else 0
        color = _RED if ratio >= 1 else _AMBER if ratio >= config.BUDGET_ALERT_RATIO else _GREEN
        left = budget - spent
        status = f"剩 {_money(left)}" if left >= 0 else f"超支 {_money(-left)}"
        rows.append({
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "box",
                    "layout": "baseline",
                    "contents": [
                        {"type": "text", "text": name, "size": "sm", "color": _INK, "flex": 1},
                        {"type": "text", "text": f"{_money(spent)} / {_money(budget)}",
                         "size": "xs", "color": _DIM, "flex": 0},
                    ],
                },
                _bar(ratio, color),
                {"type": "text", "text": status, "size": "xxs", "align": "end", "margin": "xs",
                 "color": _RED if left < 0 else _DIM},
            ],
        })

    spent_all = sum(totals.get(name, 0) for name in budgets)
    budget_all = sum(budgets.values())
    body = [
        _header("預算", f"{month} 月預算"),
        {
            "type": "box",
            "layout": "baseline",
            "contents": [
                {"type": "text", "text": _money(spent_all), "size": "xxl", "weight": "bold",
                 "color": _INK, "flex": 0},
                {"type": "text", "text": f"/ {_money(budget_all)}", "size": "sm",
                 "color": _DIM, "margin": "sm"},
            ],
        },
        {"type": "separator", "color": _TRACK},
        {"type": "box", "layout": "vertical", "spacing": "md", "contents": rows},
    ]
    uri = _liff("expense")
    return _flex(alt, _bubble(body, _link_footer("開啟記帳", uri) if uri else None))


def spending_card(label: str, totals: dict[str, float], count: int, alt: str) -> dict:
    """某段期間花了多少：總額大字，下面每個分類的佔比。"""
    total = sum(totals.values())
    rows: list[dict] = []
    for name, amount in sorted(totals.items(), key=lambda kv: -kv[1]):
        share = amount / total if total else 0
        rows.append({
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "box",
                    "layout": "baseline",
                    "contents": [
                        {"type": "text", "text": name, "size": "sm", "color": _INK, "flex": 1},
                        {"type": "text", "text": f"{share:.0%}", "size": "xs", "color": _DIM,
                         "flex": 0, "margin": "md"},
                        {"type": "text", "text": _money(amount), "size": "sm", "color": _INK,
                         "flex": 0, "margin": "md"},
                    ],
                },
                _bar(share, _GREEN),
            ],
        })

    body = [
        _header("消費", f"{label}總共花了"),
        {
            "type": "box",
            "layout": "baseline",
            "contents": [
                {"type": "text", "text": _money(total), "size": "xxl", "weight": "bold",
                 "color": _INK, "flex": 0},
                {"type": "text", "text": f"{count} 筆", "size": "sm", "color": _DIM,
                 "margin": "sm"},
            ],
        },
        {"type": "separator", "color": _TRACK},
        {"type": "box", "layout": "vertical", "spacing": "md", "contents": rows},
    ]
    uri = _liff("expense")
    return _flex(alt, _bubble(body, _link_footer("開啟記帳", uri) if uri else None))


def daily_brief_card(today, events: list[dict], todos: list[dict], summary: str, alt: str) -> dict:
    """早報。有 Claude 的話最上面是它寫的摘要，底下照樣列出行程與待辦。

    只推一則，跟原本的純文字早報吃一樣的額度。
    """
    body: list[dict] = [_header("早安", f"{today.month}/{today.day}（週{_WEEK[today.weekday()]}）")]
    if summary:
        body.append({"type": "text", "text": summary, "size": "sm", "color": _INK, "wrap": True})

    body.append({"type": "separator", "color": _TRACK})
    body.append({"type": "text", "text": f"今天的行程（{len(events)}）", "size": "xs",
                 "weight": "bold", "color": _DIM})
    if events:
        body.append({"type": "box", "layout": "vertical", "spacing": "md",
                     "contents": _event_lines(events, False)})
    else:
        body.append({"type": "text", "text": "沒有安排的行程", "size": "sm", "color": _FAINT})

    if todos:
        lines = []
        for row in todos[:10]:
            overdue = (today - row["due"]).days
            lines.append({
                "type": "box",
                "layout": "baseline",
                "spacing": "sm",
                "contents": [
                    {"type": "text", "text": "●", "size": "xxs", "flex": 0,
                     "color": _RED if overdue > 0 else _AMBER},
                    {"type": "text", "text": row["title"], "size": "sm", "color": _INK,
                     "wrap": True, "flex": 1},
                    {"type": "text", "text": f"逾期 {overdue} 天" if overdue > 0 else "今天",
                     "size": "xxs", "flex": 0, "color": _RED if overdue > 0 else _AMBER},
                ],
            })
        if len(todos) > 10:
            lines.append({"type": "text", "text": f"⋯ 還有 {len(todos) - 10} 筆",
                          "size": "xs", "color": _DIM})
        body.append({"type": "separator", "color": _TRACK})
        body.append({"type": "text", "text": f"該處理的待辦（{len(todos)}）", "size": "xs",
                     "weight": "bold", "color": _DIM})
        body.append({"type": "box", "layout": "vertical", "spacing": "sm", "contents": lines})

    uri = _liff("event")
    return _flex(alt, _bubble(body, _link_footer("打開助理", uri) if uri else None))


def _icon_button(label: str, data: str, color: str) -> dict:
    """清單列右邊的小按鈕。用符號而不是文字，兩顆才排得下一列。"""
    return {
        "type": "text",
        "text": label,
        "size": "lg",
        "flex": 0,
        "align": "center",
        "gravity": "center",
        "color": color,
        "margin": "md",
        "action": {"type": "postback", "data": data},
    }


def _todo_line(row: dict, today) -> dict:
    """待辦清單的一列：左邊事項，右邊完成與刪除。"""
    due = row["due"]
    if due is None:
        mark, color = "", _INK
    elif due < today:
        mark, color = f"（逾期 {(today - due).days} 天）", _RED
    elif due == today:
        mark, color = "（今天）", _AMBER
    else:
        mark, color = f"（{due.month}/{due.day}）", _INK

    return {
        "type": "box",
        "layout": "horizontal",
        "alignItems": "center",
        "contents": [
            {
                "type": "text",
                "text": f"{row['title']}{mark}",
                "size": "sm",
                "wrap": True,
                "flex": 1,
                "color": color,
            },
            _icon_button("✓", f"action=done_todo&page_id={row['page_id']}", _GREEN),
            _icon_button("✕", f"action=delete_todo&page_id={row['page_id']}", _FAINT),
        ],
    }


def todo_list_card(rows: list[dict], today, total: int, liff_url: str = "") -> dict:
    """待辦清單卡片。每列都能直接按，不用再回一句話。

    LINE 的 Flex 泡泡塞太多列會被截斷，所以最多顯示 10 筆，其餘只報數量，
    要看全部就按底下開網頁。
    """
    shown = rows[:10]
    lines: list[dict] = []
    for index, row in enumerate(shown):
        line = _todo_line(row, today)
        if index:
            line["margin"] = "sm"
        lines.append(line)

    if total > len(shown):
        lines.append(
            {
                "type": "text",
                "text": f"⋯ 還有 {total - len(shown)} 筆",
                "size": "xs",
                "color": _DIM,
                "margin": "md",
            }
        )

    body = [
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "box", "layout": "vertical", "flex": 1,
                 "contents": [_header("待辦", f"{total} 件事")]},
                {"type": "text", "text": "✓ 完成　✕ 刪除", "size": "xxs", "color": _DIM,
                 "align": "end", "gravity": "bottom", "flex": 0},
            ],
        },
        {"type": "separator", "color": _TRACK},
        {"type": "box", "layout": "vertical", "contents": lines},
    ]
    footer = _link_footer("開啟完整清單", liff_url) if liff_url else None
    return _flex(f"待辦（{total} 筆）", _bubble(body, footer))


# --- LIFF 身分驗證 ---


def verify_id_token(id_token: str) -> str:
    """驗證 LIFF 傳來的 ID token，回傳 LINE user id。驗不過回空字串。

    刻意送去 LINE 的 verify 端點而不是自己解 JWT：簽章、有效期與 audience
    都由 LINE 檢查，這裡不必自己實作也就不會實作錯。
    audience 一定要帶，否則別的 channel 發的 token 也會通過。

    這裡的 client_id 是 LINE Login channel 的 id（LIFF 掛在那邊），
    不是 Messaging API channel 的，填錯會一律驗不過。
    """
    if not id_token or not config.LINE_LOGIN_CHANNEL_ID:
        return ""
    try:
        response = httpx.post(
            "https://api.line.me/oauth2/v2.1/verify",
            data={"id_token": id_token, "client_id": config.LINE_LOGIN_CHANNEL_ID},
            timeout=10,
        )
    except httpx.HTTPError:
        return ""
    if response.status_code != 200:
        return ""
    return response.json().get("sub", "")
