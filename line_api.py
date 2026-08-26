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
