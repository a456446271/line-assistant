"""建立 LINE 的 Rich Menu：聊天室下方那排常駐按鈕。

畫好圖、上傳、設成所有使用者的預設選單，一支腳本做完。
重複執行是安全的：會先刪掉舊的同名選單，不會越積越多。

只有第一次設定與改版面時要跑，所以 Pillow 不列進 requirements.txt
（Render 上永遠不會執行這支）。跑之前先 pip install pillow。

用法：
    python scripts/setup_richmenu.py            # 建立並套用
    python scripts/setup_richmenu.py --preview  # 只產生圖片，不上傳
    python scripts/setup_richmenu.py --delete   # 刪掉現有的
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from PIL import Image, ImageDraw, ImageFont

import config

NAME = "line-assistant-main"
WIDTH, HEIGHT = 2500, 1686
COLS, ROWS = 2, 2
CELL_W, CELL_H = WIDTH // COLS, HEIGHT // ROWS

BG = (247, 247, 249)
LINE_COLOR = (226, 226, 232)
TITLE_COLOR = (28, 28, 30)
HINT_COLOR = (142, 142, 147)

FONT_BOLD = "C:/Windows/Fonts/msjhbd.ttc"
FONT_REGULAR = "C:/Windows/Fonts/msjh.ttc"

# 版面順序是由左到右、由上到下。
# action 是按下去要做的事：message 直接送出那句話，uri 開網頁。
#
# 刻意不放 ✓ ▤ 這類圖示符號——微軟正黑體沒有那些字形，會印成豆腐塊。
# 改用一個色點區分，● 是字型裡確定有的。
BUTTONS = [
    {"color": (6, 199, 85), "title": "待辦", "hint": "開清單", "action": "liff"},
    {"color": (47, 111, 237), "title": "今天行程", "hint": "查行事曆",
     "action": {"type": "message", "text": "今天有什麼安排"}},
    {"color": (139, 92, 246), "title": "流程", "hint": "看有哪些",
     "action": {"type": "message", "text": "流程"}},
    {"color": (245, 158, 11), "title": "本月消費", "hint": "查記帳",
     "action": {"type": "message", "text": "這個月花多少"}},
]


def draw_image() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)

    title_font = ImageFont.truetype(FONT_BOLD, 118)
    hint_font = ImageFont.truetype(FONT_REGULAR, 60)

    for index, button in enumerate(BUTTONS):
        col, row = index % COLS, index // COLS
        left, top = col * CELL_W, row * CELL_H
        center_x = left + CELL_W // 2
        center_y = top + CELL_H // 2

        # 格子之間留白線，看起來才像四顆分開的按鈕
        pad = 12
        draw.rectangle(
            [left + pad, top + pad, left + CELL_W - pad, top + CELL_H - pad],
            fill=(255, 255, 255),
            outline=LINE_COLOR,
            width=3,
        )

        radius = 26
        draw.ellipse(
            [center_x - radius, center_y - 150 - radius, center_x + radius, center_y - 150 + radius],
            fill=button["color"],
        )
        draw.text((center_x, center_y + 20), button["title"],
                  font=title_font, fill=TITLE_COLOR, anchor="mm")
        draw.text((center_x, center_y + 145), button["hint"],
                  font=hint_font, fill=HINT_COLOR, anchor="mm")

    return image


def build_areas() -> list[dict]:
    areas = []
    for index, button in enumerate(BUTTONS):
        col, row = index % COLS, index // COLS
        action = button["action"]
        if action == "liff":
            if not config.LIFF_URL:
                # 沒設 LIFF 就退成送出「待辦」，一樣叫得出卡片
                action = {"type": "message", "text": "待辦"}
            else:
                action = {"type": "uri", "uri": config.LIFF_URL}
        areas.append(
            {
                "bounds": {"x": col * CELL_W, "y": row * CELL_H, "width": CELL_W, "height": CELL_H},
                "action": action,
            }
        )
    return areas


def headers() -> dict:
    return {"Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}"}


def delete_existing() -> int:
    response = httpx.get("https://api.line.me/v2/bot/richmenu/list", headers=headers(), timeout=20)
    response.raise_for_status()
    removed = 0
    for menu in response.json().get("richmenus", []):
        if menu.get("name") == NAME:
            httpx.delete(
                f"https://api.line.me/v2/bot/richmenu/{menu['richMenuId']}",
                headers=headers(),
                timeout=20,
            ).raise_for_status()
            removed += 1
    return removed


def main() -> None:
    image = draw_image()

    if "--preview" in sys.argv:
        out = Path(__file__).parent.parent / "richmenu.png"
        image.save(out, "PNG")
        print(f"已產生 {out}（沒有上傳）")
        return

    if not config.LINE_CHANNEL_ACCESS_TOKEN:
        print("LINE_CHANNEL_ACCESS_TOKEN 沒設。")
        raise SystemExit(1)

    removed = delete_existing()
    if removed:
        print(f"刪掉 {removed} 個舊的「{NAME}」選單")
    if "--delete" in sys.argv:
        return

    created = httpx.post(
        "https://api.line.me/v2/bot/richmenu",
        headers={**headers(), "Content-Type": "application/json"},
        json={
            "size": {"width": WIDTH, "height": HEIGHT},
            "selected": True,      # 進聊天室就展開，不用先點一下
            "name": NAME,
            "chatBarText": "選單",
            "areas": build_areas(),
        },
        timeout=20,
    )
    created.raise_for_status()
    menu_id = created.json()["richMenuId"]
    print(f"建立選單 {menu_id}")

    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    upload = httpx.post(
        f"https://api-data.line.me/v2/bot/richmenu/{menu_id}/content",
        headers={**headers(), "Content-Type": "image/png"},
        content=buffer.getvalue(),
        timeout=60,
    )
    upload.raise_for_status()
    print(f"上傳圖片（{len(buffer.getvalue()) // 1024} KB）")

    httpx.post(
        f"https://api.line.me/v2/bot/user/all/richmenu/{menu_id}",
        headers=headers(),
        timeout=20,
    ).raise_for_status()
    print("已設為所有使用者的預設選單。回 LINE 把聊天室關掉再開就會看到。")

    if not config.LIFF_URL:
        print("\n注意：LIFF_ID 沒設，「待辦」按鈕暫時改成送出「待辦」兩個字。")
        print("設好 LIFF_ID 之後再跑一次這支，按鈕就會改成直接開網頁。")


if __name__ == "__main__":
    main()
