# LINE 個人助理（行事曆 + 記帳）

在 LINE 上用講的查行程、加行程、記帳。行程資料放 Google Calendar（會同步到 iPhone 原生行事曆 App），記帳資料放 Notion。

```
你：今天有什麼安排
助理：今天三件事——
     ・10:00 跟設計師對稿
     ・14:00-15:30 客戶提案
     ・19:00 晚餐聚會
     下午提案完到晚餐中間有三個半小時空檔。

你：下週二下午三點跟客戶開會
助理：[卡片] 要加入行事曆嗎？
     時間 2026/09/01(二) 15:00-16:00
     項目 跟客戶開會
     [取消] [確認新增]

你：午餐 120
助理：已記錄 午餐 $120（餐飲）
     [撤銷這筆]
```

另外每天早上會推播當日行程摘要，每月 1 號推播上個月的消費月報，分類快超支時會提醒。

---

## 先搞清楚兩件事

1. **LINE Notify 已於 2025-03-31 終止服務**。網路上很多教學還在教 LINE Notify，那些都不能用了，本專案用的是 LINE Messaging API。
2. **費用**：LINE 官方帳號輕用量方案 0 元，每月 200 則免費**推播**額度。你傳訊息、bot 回覆你（reply）**完全不計費**，只有 bot 主動推播才算則數。本專案的排程一個月大約用掉 35-45 則，很寬裕。

---

## 設定步驟

依序做完這四步，缺一不可。

### 1. iPhone：把行事曆接上 Google

設定 →「應用程式」→「行事曆」→「行事曆帳號」→「加入帳號」→ Google → 登入。

加完之後，**務必把預設行事曆改成 Google 那本**（設定 → 行事曆 → 預設行事曆）。不改的話，你在手機上隨手新增的行程會存進 iCloud，這個 bot 讀不到。

設好之後 Google Calendar 的行程會顯示在 iPhone 原生行事曆 App 裡，雙向同步，手機端的使用習慣完全不用改。

### 2. Google Cloud：開 Calendar API 並取得憑證

1. 到 https://console.cloud.google.com 建立一個新專案
2. 「API 和服務」→「已啟用的 API」→ 搜尋並啟用 **Google Calendar API**
3. 「API 和服務」→「OAuth 同意畫面」→ 使用者類型選「外部」，填基本資料
4. **重要：把應用程式「發布為正式版」**
   > 如果停在「測試中」狀態，發出的 refresh token **七天就會失效**，bot 會每週壞一次。
   > 個人使用不需要通過 Google 驗證，發布後登入時會出現「此應用程式未經 Google 驗證」的警告畫面，點「進階」→「繼續前往」就好。
5. 「憑證」→「建立憑證」→「OAuth 用戶端 ID」→ 應用程式類型選 **電腦版應用程式**
6. 拿到 `Client ID` 與 `Client secret`，填進 `.env`
7. 執行下面這個腳本取得 refresh token：
   ```bash
   python scripts/get_google_token.py
   ```
   瀏覽器會開啟，登入**步驟 1 用的那個 Google 帳號**並授權。拿到的 refresh token 會直接寫回 `.env`，不會顯示在畫面上（印在終端機會留在捲動記錄裡）。

### 3. Notion：建立記帳資料庫

1. 到 https://www.notion.so/my-integrations 建立一個 **internal integration**，複製它的 secret 填進 `.env` 的 `NOTION_TOKEN`
2. 在 Notion 裡建立一個資料庫，欄位如下（**名稱要完全一樣**）：

   | 欄位 | 型別 | 說明 |
   |---|---|---|
   | 項目 | Title | 消費項目 |
   | 金額 | Number | 新台幣 |
   | 分類 | Select | 選項要和 `.env` 的 `BUDGET_JSON` 的 key 完全一致 |
   | 日期 | Date | |
   | 來源 | Select | 加一個選項「LINE」 |

3. 在資料庫頁面右上角「⋯」→「連線」→ 把剛剛建的 integration 加進去（**這步沒做的話 API 會回 404**）
4. 複製資料庫網址中的 32 碼 id 填進 `.env` 的 `NOTION_EXPENSE_DB_ID`
   ```
   https://www.notion.so/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx?v=...
                         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ 這段
   ```

### 4. LINE：建立 Messaging API channel

1. 到 https://developers.line.biz/console/ 登入，建立一個 Provider
2. 在該 Provider 下建立 **Messaging API** channel
3. 「Basic settings」分頁 → 複製 **Channel secret** 填進 `.env`
4. 「Messaging API」分頁 → 最下方 **Channel access token（long-lived）** → 按 Issue → 複製填進 `.env`
5. 同一頁把 **自動回應訊息** 和 **歡迎訊息** 都關掉（不關的話 bot 會多回一堆罐頭訊息）
6. 用手機掃該頁的 QR code 加自己的 bot 好友
7. `ALLOWED_USER_IDS` 先留空，等服務跑起來、你傳第一則訊息後，終端機的 log 會印出 `user_id=Uxxxxx`，把它填進 `.env` 再重啟

> `ALLOWED_USER_IDS` 是白名單。留空的話任何加你 bot 好友的人都能用，會消耗你的 Claude API 額度，設定完務必填上。

---

## 本機跑起來

```bash
cd line-assistant
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # 然後把上面拿到的值填進去
```

### 先在終端機測，不用碰 LINE

```bash
python scripts/chat.py
```

行事曆與記帳的邏輯可以在這裡快速反覆調整，不用每次都繞一圈 webhook。建議依序試這幾句：

- `今天有什麼安排`
- `這禮拜三下午有空嗎`
- `下週二下午三點跟客戶開會` → 應該印出「待確認行程」而不是直接建立
- `午餐 120` → 去 Notion 確認欄位對不對
- `這個月花多少`

### 接上 LINE

```bash
uvicorn main:app --reload
```

另開一個終端機跑 `ngrok http 8000`，把 ngrok 給的 https 網址加上 `/webhook`（例如 `https://xxxx.ngrok-free.app/webhook`）填進 LINE Developers Console 的 Webhook URL，按 **Verify** 應該顯示 Success，並把 **Use webhook** 打開。

然後用手機傳訊息測試。

---

## 部署到 Render

專案內附 `render.yaml`，Render 會自動帶好建置與啟動指令，不用手動填。

1. **確認程式碼已推到 GitHub**（`git push`）
2. Render → **New** → **Blueprint** → 選這個 repo → Render 會讀到 `render.yaml`
3. 它會列出所有標記 `sync: false` 的環境變數要你填值。**最快的做法是把本機 `.env` 裡對應的值複製過去**（Render 的環境變數頁面支援直接貼上 `.env` 格式的整段內容）
   - `ANTHROPIC_API_KEY` 想維持純規則模式（NT$0）就留空
4. 部署完成後會拿到一個 `https://xxx.onrender.com` 的固定網址
5. 把 **LINE 的 webhook 網址改成** `https://xxx.onrender.com/webhook`
   （LINE Developers Console → 你的頻道 → Messaging API 分頁 → Webhook settings）

> **免費方案會休眠**：閒置 15 分鐘後服務會睡著，下次喚醒要 30-50 秒，第一則訊息會明顯卡住。
> 解法是到 https://cron-job.org 設一個每 10 分鐘打 `https://xxx.onrender.com/healthz` 的任務保活。
> 不想處理這件事的話可以改用 Fly.io（不休眠，但要綁信用卡）。

### 排程

排程做成一個帶密鑰的 HTTP 端點，由外部服務定時打進來：

```
POST /cron?key=<CRON_SECRET>&job=daily     # 每日早報
POST /cron?key=<CRON_SECRET>&job=budget    # 預算檢查（只有超標才推播）
POST /cron?key=<CRON_SECRET>&job=monthly   # 上個月的消費月報
```

專案內附 `.github/workflows/cron.yml`，用 GitHub Actions 免費跑。要用的話在 repo 的 Settings → Secrets 加上 `APP_BASE_URL`（你的服務網址，結尾不要斜線）和 `CRON_SECRET`。

GitHub Actions 的排程常有 5-20 分鐘延遲，在意早報準時的話改用 cron-job.org 打同一個網址會比較準。

### 本機測試用的臨時網址

不想部署、只想在自己電腦上跑的話，用 cloudflared 開一個臨時隧道：

```bash
winget install --id Cloudflare.cloudflared
cloudflared tunnel --url http://127.0.0.1:8000
```

它會給一個 `https://xxx.trycloudflare.com` 網址，把 `網址/webhook` 填進 LINE 即可。不用註冊帳號，但電腦或隧道一關就失效。

---

## 費用

| 項目 | 費用 |
|---|---|
| LINE 官方帳號（輕用量） | 0 元 |
| Render / Notion / Google Calendar / GitHub Actions | 0 元 |
| Claude API | **選填**：NT$0 或約 NT$5-15 / 月 |

`ANTHROPIC_API_KEY` 是選填的，決定了兩種模式：

**填了**（推薦）——規則接不住的句子交給 Claude 理解。規則能接住九成左右的日常句型，剩下的一週不過幾則，一則約 NT$1，所以月費落在 NT$5-15。好處是**你永遠不用思考「這句話要怎麼講它才聽得懂」**。

**留空**——純規則模式，完全 NT$0。規則接不住時會回一句提示列出支援的講法；每日早報和月報也改成直接排版，不叫 AI 潤稿。

兩種模式隨時切換，改 `.env` 重啟就好，程式不用動。

有啟用 Claude 的話，建議到 https://console.anthropic.com/settings/limits 設一個每月支出上限。模型預設 `claude-opus-5`（$5 / $25 per MTok），想更省可以改成 `claude-sonnet-5`（$2 / $10）或 `claude-haiku-4-5`（$1 / $5）。

> Prompt caching 對這個 bot 幫助不大：快取預設只活 5 分鐘，而個人使用是一天零星幾則，幾乎每次都會 miss。

---

## 規則層

`rules.py` 加上 `zh_datetime.py` 的中文日期解析，讓大部分句型不必呼叫 LLM，回應也是瞬間的：

| 功能 | 你可以這樣講 |
|---|---|
| 記帳 | `午餐 120`、`星巴克85`、`剪頭髮 600`、`120 午餐`、`晚餐 250 元` |
| 新增行程 | `明天下午三點開會`、`下週二下午三點跟客戶開會`、`禮拜五晚上七點聚餐`、`9/1 15:00 提案`、`明天下午三點開會 兩小時` |
| 查行程 | `今天有什麼安排`、`這禮拜五的行程`、`下下週有什麼安排`、`今天` |
| 查空檔 | `明天下午有空嗎`、`這週哪天有空` |
| 查消費 | `這個月花多少`、`上個月花多少`、`餐飲花了多少` |
| 查預算 | `預算`、`還剩多少預算` |

`zh_datetime.py` 認得的時間講法：今天／明天／後天／大後天、`(這|本|下|下下|上)` + 週／禮拜／星期 + 幾、`M/D`、`M月D日`、早上／上午／中午／下午／傍晚／晚上、`X點`、`X點半`、`X:XX`、中文數字（十點、兩點半）、`X小時`。

### 規則層刻意不做的事

這些一律交給 Claude（純規則模式下則回提示），因為規則做不好，硬做會出錯：

- **修改／取消既有行程**（`把明天的會改到四點`）——要先判斷是哪一個行程
- **沒講時間的行程**（`8/30 生日聚餐`）——不猜一個時間塞進行事曆
- **猜不出分類的記帳**（`阿姨的東西 500`）——不亂塞進「其他」
- **模糊查詢**（`我跟客戶的會是什麼時候`）

設計原則是**寧可放過、不可誤判**。記帳誤判會直接寫進 Notion，查詢誤判會給出看起來合理但錯誤的答案——這兩者都比老實說「看不懂」更糟。

想調整記帳的分類判斷，改 `rules.py` 最上面的 `_CATEGORY_KEYWORDS`。用 `python scripts/chat.py` 測試時，每則回覆會標示是「規則」還是「Claude」處理的，方便你調規則。

---

## 已知限制

- **不記得上一句話**。每則訊息都是獨立處理的，所以「那改到四點」這種接續指令不會work，要重講完整的一句。要多輪對話的話得在 `main.py` 加上每個使用者的短期歷史。
- **確認卡片存在記憶體**。服務重啟（Render 部署或休眠喚醒）後，還沒按的卡片會失效，按下去會回「已過期，請再說一次」。
- **只讀寫一本行事曆**（`GOOGLE_CALENDAR_ID`，預設 `primary`）。
- Claude 若因安全機制拒絕回應，bot 會回一句制式訊息。沒有啟用 server-side fallback，個人行事曆場景幾乎不會遇到。

## 之後可以加的

行程前 N 分鐘提醒、每週日晚上下週行程總覽、傳活動海報截圖讓 Claude 解析後建行程、結合天氣與通勤時間、iOS 提醒事項整合。
