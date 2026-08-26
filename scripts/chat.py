"""在終端機直接跟助理對話，不經過 LINE。

行事曆與記帳的邏輯可以在這裡快速反覆測試，不用每次都繞一圈 webhook。

使用方式：
    python scripts/chat.py
    python scripts/chat.py "今天有什麼安排"     # 單次提問後結束

新增行程在這裡不會真的寫入（跟 LINE 一樣要按確認），會印出待確認的內容，
並詢問你要不要建立，方便驗證確認流程。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent
import calendar_api
import config
import rules


def ask(text: str) -> None:
    result = rules.try_handle(text)
    source = "規則"
    if result is None:
        if config.LLM_ENABLED:
            source = "Claude"
            result = agent.run(text)
        else:
            source = "接不住"
            result = agent.AgentResult(text="這句規則接不住，且未設定 ANTHROPIC_API_KEY。")
    print(f"\n助理（{source}）：{result.text}\n")

    if result.created_expense:
        print(f"[已寫入 Notion] page_id={result.created_expense['page_id']}")

    if result.pending_event:
        event = result.pending_event
        start = calendar_api.parse_dt(event["start"])
        end = calendar_api.parse_dt(event["end"])
        print("[待確認行程] 尚未寫入行事曆：")
        print(f"  時間：{start:%Y-%m-%d %H:%M} - {end:%H:%M}")
        print(f"  標題：{event['title']}")
        if event["location"]:
            print(f"  地點：{event['location']}")

        if input("  要建立嗎？(y/N) ").strip().lower() == "y":
            created = calendar_api.create_event(
                event["title"],
                event["start"],
                event["end"],
                event["location"],
                event["description"],
            )
            print(f"  已建立：{created['link']}")
        else:
            print("  已略過。")
        print()


def main() -> None:
    missing = config.check_config()
    if missing:
        print(f"提醒：這些環境變數還沒設定：{missing}\n")

    if len(sys.argv) > 1:
        ask(" ".join(sys.argv[1:]))
        return

    print("輸入訊息跟助理對話，Ctrl+C 離開。\n")
    while True:
        try:
            text = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if text:
            ask(text)


if __name__ == "__main__":
    main()
