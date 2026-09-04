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


def _row(label: str, value: str) -> dict:
    return {
        "type": "box",
        "layout": "baseline",
        "spacing": "sm",
        "contents": [
            {"type": "text", "text": label, "color": "#999999", "size": "sm", "flex": 2},
            {"type": "text", "text": value, "size": "sm", "flex": 5, "wrap": True},
        ],
    }


def event_confirm_card(pending_id: str, when: str, title: str, location: str) -> dict:
    rows = [_row("時間", when), _row("項目", title)]
    if location:
        rows.append(_row("地點", location))

    return {
        "type": "flex",
        "altText": f"要新增行程「{title}」嗎？",
        "contents": {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {"type": "text", "text": "要加入行事曆嗎？", "weight": "bold", "size": "md"},
                    {"type": "box", "layout": "vertical", "spacing": "sm", "contents": rows},
                ],
            },
            "footer": {
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
                        "action": {
                            "type": "postback",
                            "label": "確認新增",
                            "data": f"action=confirm_event&pid={pending_id}",
                            "displayText": "確認新增",
                        },
                    },
                ],
            },
        },
    }


def expense_card(summary: str, page_id: str) -> dict:
    """記帳成功的回覆，附一顆撤銷按鈕。

    記帳不做事前確認（每筆都確認太煩），改成事後可撤銷。
    """
    return {
        "type": "flex",
        "altText": summary,
        "contents": {
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [{"type": "text", "text": summary, "size": "sm", "wrap": True}],
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "button",
                        "style": "link",
                        "height": "sm",
                        "action": {
                            "type": "postback",
                            "label": "撤銷這筆",
                            "data": f"action=undo_expense&page_id={page_id}",
                        },
                    }
                ],
            },
        },
    }


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
        mark, color = "", "#333333"
    elif due < today:
        mark, color = f"（逾期 {(today - due).days} 天）", "#D64545"
    elif due == today:
        mark, color = "（今天）", "#D67B20"
    else:
        mark, color = f"（{due.month}/{due.day}）", "#333333"

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
            _icon_button("✓", f"action=done_todo&page_id={row['page_id']}", "#2E7D32"),
            _icon_button("✕", f"action=delete_todo&page_id={row['page_id']}", "#BBBBBB"),
        ],
    }


def todo_list_card(rows: list[dict], today, total: int, liff_url: str = "") -> dict:
    """待辦清單卡片。每列都能直接按，不用再回一句話。

    LINE 的 Flex 泡泡塞太多列會被截斷，所以最多顯示 10 筆，其餘只報數量，
    要看全部就按底下開網頁。
    """
    shown = rows[:10]
    contents: list[dict] = [
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "text", "text": f"待辦（{total} 筆）", "weight": "bold", "size": "md", "flex": 1},
                {"type": "text", "text": "✓ 完成　✕ 刪除", "size": "xxs", "color": "#999999",
                 "align": "end", "gravity": "center", "flex": 0},
            ],
        },
        {"type": "separator", "margin": "md"},
    ]
    for index, row in enumerate(shown):
        line = _todo_line(row, today)
        if index:
            line["margin"] = "sm"
        contents.append(line)

    if total > len(shown):
        contents.append(
            {
                "type": "text",
                "text": f"⋯ 還有 {total - len(shown)} 筆",
                "size": "xs",
                "color": "#999999",
                "margin": "md",
            }
        )

    bubble: dict = {
        "type": "bubble",
        "body": {"type": "box", "layout": "vertical", "spacing": "none", "contents": contents},
    }
    if liff_url:
        bubble["footer"] = {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "style": "link",
                    "height": "sm",
                    "action": {"type": "uri", "label": "開啟完整清單", "uri": liff_url},
                }
            ],
        }

    return {
        "type": "flex",
        "altText": f"待辦（{total} 筆）",
        "contents": bubble,
    }


# --- LIFF 身分驗證 ---


def verify_id_token(id_token: str) -> str:
    """驗證 LIFF 傳來的 ID token，回傳 LINE user id。驗不過回空字串。

    刻意送去 LINE 的 verify 端點而不是自己解 JWT：簽章、有效期與 audience
    都由 LINE 檢查，這裡不必自己實作也就不會實作錯。
    audience 一定要帶，否則別的 channel 發的 token 也會通過。
    """
    if not id_token or not config.LINE_CHANNEL_ID:
        return ""
    try:
        response = httpx.post(
            "https://api.line.me/oauth2/v2.1/verify",
            data={"id_token": id_token, "client_id": config.LINE_CHANNEL_ID},
            timeout=10,
        )
    except httpx.HTTPError:
        return ""
    if response.status_code != 200:
        return ""
    return response.json().get("sub", "")
