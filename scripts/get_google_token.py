"""一次性工具：透過瀏覽器登入 Google 帳號，取得 Google Calendar 所需的 refresh token。

使用方式：
    1. 先在 .env 填好 GOOGLE_CLIENT_ID 與 GOOGLE_CLIENT_SECRET
    2. 執行： python scripts/get_google_token.py
    3. 瀏覽器會自動開啟，登入你 iPhone 行事曆同步的那個 Google 帳號並同意授權
    4. 拿到的 refresh token 會直接寫回 .env，不會顯示在畫面上
       （token 印在終端機上會留在捲動記錄裡，所以刻意不印）

注意：OAuth 同意畫面若停留在「測試中」狀態，這裡拿到的 refresh token 七天就會失效。
記得到 Google Cloud Console 把應用程式「發布為正式版」。
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google_auth_oauthlib.flow import InstalledAppFlow

import config


def main():
    if not config.GOOGLE_CLIENT_ID or not config.GOOGLE_CLIENT_SECRET:
        raise SystemExit("請先在 .env 設定 GOOGLE_CLIENT_ID 與 GOOGLE_CLIENT_SECRET")

    client_config = {
        "installed": {
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, scopes=config.GOOGLE_SCOPES)
    credentials = flow.run_local_server(port=0)

    token = credentials.refresh_token
    if not token:
        raise SystemExit(
            "Google 沒有回傳 refresh token。通常是因為這個帳號先前已經授權過，"
            "到 https://myaccount.google.com/permissions 移除授權後再跑一次。"
        )

    write_to_env(token)


def write_to_env(token: str) -> None:
    """把 token 寫回 .env。刻意不印出來，避免留在終端機的捲動記錄裡。"""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        raise SystemExit(f"找不到 {env_path}，請先從 .env.example 複製一份")

    content = env_path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r"^GOOGLE_REFRESH_TOKEN=.*$",
        f"GOOGLE_REFRESH_TOKEN={token}",
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if count == 0:
        raise SystemExit("在 .env 裡找不到 GOOGLE_REFRESH_TOKEN 這一行")

    env_path.write_text(updated, encoding="utf-8")
    print(f"完成，refresh token 已寫入 .env（長度 {len(token)}）。")


if __name__ == "__main__":
    main()
