"""一次性工具：透過瀏覽器登入 Google 帳號，取得 Google Calendar 所需的 refresh token。

使用方式：
    1. 先在 .env 填好 GOOGLE_CLIENT_ID 與 GOOGLE_CLIENT_SECRET
    2. 執行： python scripts/get_google_token.py
    3. 瀏覽器會自動開啟，登入你 iPhone 行事曆同步的那個 Google 帳號並同意授權
    4. 終端機會印出 refresh token，複製貼到 .env 的 GOOGLE_REFRESH_TOKEN

注意：OAuth 同意畫面若停留在「測試中」狀態，這裡拿到的 refresh token 七天就會失效。
記得到 Google Cloud Console 把應用程式「發布為正式版」。
"""

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

    print("\n請將以下值複製到 .env 的 GOOGLE_REFRESH_TOKEN：\n")
    print(credentials.refresh_token)


if __name__ == "__main__":
    main()
