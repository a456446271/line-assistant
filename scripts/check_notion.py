"""檢查三個 Notion 資料庫是不是都連上了。

新加資料庫時最常見的錯誤是忘記在 Notion 頁面右上角把 integration 加為連線，
症狀是 404 object_not_found，訊息本身看不出是哪個資料庫。這支腳本直接講清楚。

用法：python scripts/check_notion.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

import config
import notion

CHECKS = [
    ("記帳", config.NOTION_EXPENSE_DB_ID, True),
    ("待辦", config.NOTION_TODO_DB_ID, False),
    ("流程筆記", config.NOTION_SOP_DB_ID, False),
]


def main() -> int:
    if not config.NOTION_TOKEN:
        print("NOTION_TOKEN 沒設，先去 .env 補上。")
        return 1

    failed = 0
    for name, db_id, required in CHECKS:
        if not db_id:
            print(f"[略過] {name}：沒有設定 id{'（這個是必要的！）' if required else '，功能關閉'}")
            failed += required
            continue

        try:
            data = notion.get(f"/databases/{db_id}")
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 404:
                print(f"[失敗] {name} {db_id}")
                print("        integration 看不到這個資料庫。到那個資料庫頁面右上角")
                print("        「⋯」→「連接」→ 選你的 integration，然後再跑一次。")
            else:
                print(f"[失敗] {name}：HTTP {error.response.status_code} {error.response.text[:120]}")
            failed += 1
            continue

        title = notion.plain(data.get("title", []))
        props = "、".join(data.get("properties", {}))
        print(f"[OK]   {name} → 「{title}」")
        print(f"        欄位：{props}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
