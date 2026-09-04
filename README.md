# LINE 個人助理（行事曆 + 記帳 + 待辦 + 流程）

在 LINE 上用講的查行程、加行程、記帳、管待辦、查流程。行程資料放 Google Calendar（會同步到 iPhone 原生行事曆 App），記帳／待辦／流程放 Notion。

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

你：待辦 買貓砂
助理：已加入待辦：買貓砂

你：待辦
助理：[卡片] 待辦事項（4 筆）
     交學費（逾期 3 天）        [完成]
     把轉換修好                [完成]
     買貓砂                    [完成]

你：收班流程
助理：收班流程
     1. 結帳、對帳
     2. 關掉展示機電源
     3. 鎖後門
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

### 3. Notion：建立資料庫

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

#### 待辦與流程（選填）

這兩個留空就是關閉該功能，其他功能照常運作。**每個資料庫都要各自做一次上面第 3 步的「連線」**，
integration 的權限不會自己擴散到別的資料庫。

**待辦**（`NOTION_TODO_DB_ID`）：

| 欄位 | 型別 | 說明 |
|---|---|---|
| 事項 | Title | |
| 完成 | Checkbox | 清單只列沒打勾的 |
| 期限 | Date | 逾期與今天到期的會標色，也會出現在早報 |
| 分類 | Select | 工作／家裡／購物／其他 |
| 完成時間 | Date | 打勾時自動填 |
| 來源 | Select | LINE／Notion |

刻意用一張自己控制的乾淨表，而不是接生活模板附的那種待辦庫——
模板那種有三十幾個欄位、公式、按鈕與重複性任務的機制，這裡只需要其中六個欄位，
綁上去只會讓模板一改版就壞掉。欄位名稱集中在 `todo_api.py` 最上面的 `PROP_*` 常數。

**流程**（`NOTION_SOP_DB_ID`）：欄位 `名稱`(Title)、`別名`(Text，逗號分隔)、`分類`(Select)。
步驟寫在**頁面內容**裡，一行一步。段落、編號清單、項目符號、待辦框、標題都讀得到，
所以在 Notion 裡怎麼排版都沒差。

`別名` 是讓不同講法問到同一份用的：`收班流程` 填別名 `關店,打烊`，
那 `怎麼關店`、`打烊要做什麼` 都會找到它。

`分類` 是自由的，網頁上的新增表單可以直接打一個新的，Notion 會自己建選項。
網頁的分類過濾器**在只有一種分類時會自動隱藏**——那時候篩選沒有意義，只是佔版面。

設定完跑 `python scripts/check_notion.py` 會逐一檢查三個資料庫連得上沒，
404 的話它會直接告訴你是哪一個、要去哪裡按連線。

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

### 保活（必做，而且不能只靠一個工具）

Render 免費方案閒置 15 分鐘會休眠，**冷啟動實測要 42 秒**。這對 webhook 是致命的——LINE 等不到回應就放棄，那則訊息直接消失。

問題在於單一保活工具救不了：

| | |
|---|---|
| Render 冷啟動 | 42 秒 |
| cron-job.org 免費版請求逾時 | 30 秒（固定，不可調） |

服務一旦睡著，cron-job.org 的每次 ping 都必然逾時失敗，而連續失敗 25 次後它會**自動停用該任務**，服務就永遠睡死。它能防止睡著，卻救不回睡著的。

所以要兩層：

1. **cron-job.org 每 5 分鐘**打 `/healthz` — 日常防止睡著
2. **GitHub Actions 每小時**打 `/healthz`，逾時設 120 秒（`.github/workflows/cron.yml`）— 救援。GitHub 的 curl 沒有 30 秒限制，能等滿冷啟動，所以就算真的睡著，最多一小時內會被完整喚醒

要啟用第 2 層，在 repo 的 Settings → Secrets and variables → Actions 加上 `APP_BASE_URL`（服務網址，結尾不要斜線）和 `CRON_SECRET`。

> GitHub 會在 repo 連續 60 天沒有任何提交後自動停用排程 workflow，並寄信通知。長期不動這個專案的話要留意。

### 排程推播

三個排程也建在 cron-job.org 上（GitHub Actions 的排程常延遲 5-20 分鐘，早報會不準時）：

```
https://你的網址/cron?key=<CRON_SECRET>&job=daily     每天 08:00
https://你的網址/cron?key=<CRON_SECRET>&job=budget    每天 21:00（只有超標才推播）
https://你的網址/cron?key=<CRON_SECRET>&job=monthly   每月 1 號 08:30（上個月的月報）
```

`cron.yml` 刻意**不排**這三個，否則會跟 cron-job.org 重複推播。需要手動測試時用該 workflow 的 workflow_dispatch。

### 待辦網頁（LIFF）與常駐選單

這兩個是選填的，但加了之後才真的好用：聊天室下方常駐四顆按鈕，
點「待辦」開一頁四個分頁的網頁——待辦、行程、記帳、流程都在裡面，
新增、刪除、勾選都不用打字。

| 分頁 | 能做什麼 |
|---|---|
| 待辦 | 看清單、新增（可帶期限與分類）、勾完成、刪除 |
| 行程 | 看未來三週、新增（**不填時間就是整天行程**）、刪除 |
| 記帳 | 看本月總計與各分類預算條、記一筆、刪除 |
| 流程 | 列出流程、點開看步驟、依分類篩選、新增（可指定分類）|

**行程與記帳在網頁上是直接寫入的，沒有確認卡片。** 卡片的存在是為了防
「AI 把話解讀錯」，而網頁上的日期時間是你自己在欄位裡選的，表單本身就是確認。
只有行事曆的刪除會多問一次，因為 Google 沒有封存、刪掉就真的沒了。

**1. 另開一個 LINE Login channel**

**LIFF 不能加在 Messaging API channel 上**——LINE 已經擋掉，那一頁只會顯示
「Use a LINE Login channel」。要在 LINE Developers 建一個新的 **LINE Login** channel：

- **一定要選跟 Messaging API channel 同一個 Provider**。不同 Provider 拿到的
  user id 不一樣，會跟 `ALLOWED_USER_IDS` 對不起來，每次都被擋在門外。
- App types 勾 **Web app**。

**2. 在那個 Login channel 建 LIFF**

| 欄位 | 填什麼 |
|---|---|
| LIFF app name | 待辦 |
| Size | Tall |
| Endpoint URL | `https://你的網址/liff` |
| Scopes | **一定要勾 `openid`**，沒勾就拿不到身分，網頁會顯示「拿不到登入資訊」 |

建好之後複製 **LIFF ID** 填進 `LIFF_ID`，
再到那個 **Login channel** 的 Basic settings 複製 **Channel ID** 填進 `LINE_LOGIN_CHANNEL_ID`
（不是 Messaging API channel 的 id，填錯會一律驗不過）。

`LINE_LOGIN_CHANNEL_ID` 不是可有可無的：`/api/todos` 那幾個端點是瀏覽器直接打的，
沒有 webhook 的簽章可以擋外人，只能靠驗證 LIFF 的 ID token。
驗證時一定要帶 audience，否則別的 channel 發的 token 也會通過。
兩個變數少一個，整個 LIFF 就會停用（回 404），不會半開著。

**2. 建常駐選單**

```bash
pip install pillow                        # 只有這支腳本要用，沒列進 requirements.txt
python scripts/setup_richmenu.py --preview  # 先看圖長怎樣
python scripts/setup_richmenu.py            # 上傳並套用
```

四顆按鈕：待辦（開 LIFF）、今天行程、流程、本月消費。
重複執行是安全的，會先刪掉舊的同名選單。想改版面就改腳本裡的 `BUTTONS` 再跑一次。

回 LINE 要把聊天室關掉再開才會看到新選單。

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
| 記帳（指定分類）| `娛樂 PS5 3000`、`購物 iPhone 16 保護殼 590`、`其他 阿姨的東西 500` |
| 新增行程 | `明天下午三點開會`、`下週二下午三點跟客戶開會`、`禮拜五晚上七點聚餐`、`9/1 15:00 提案`、`明天下午三點開會 兩小時` |
| 查行程 | `今天有什麼安排`、`這禮拜五的行程`、`下下週有什麼安排`、`今天` |
| 查空檔 | `明天下午有空嗎`、`這週哪天有空` |
| 查消費 | `這個月花多少`、`上個月花多少`、`餐飲花了多少` |
| 查預算 | `預算`、`還剩多少預算` |
| 加待辦 | `待辦 買貓砂`、`記得繳電話費`、`提醒我下週三交報告` |
| 看待辦 | `待辦`、`有什麼待辦`、`今天的待辦` |
| 查流程 | `收班流程`、`怎麼收班`、`保證卡怎麼印`、`打烊要做什麼` |
| 加流程 | 第一行 `流程 收班流程`，接下來每行一步 |
| 列出流程 | `流程`（Rich Menu 的按鈕送的就是這兩個字） |

`zh_datetime.py` 認得的時間講法：今天／明天／後天／大後天、`(這|本|下|下下|上)` + 週／禮拜／星期 + 幾、`M/D`、`M月D日`、早上／上午／中午／下午／傍晚／晚上、`X點`、`X點半`、`X:XX`、中文數字（十點、兩點半）、`X小時`。

開頭直接講分類（`娛樂 PS5 3000`）就不必靠關鍵字猜，項目名稱照樣完整記下來。
這是關鍵字表猜不到的東西（`PS5`、某個課程名）的逃生門，在純規則模式下特別重要——
沒有它的話，猜不出分類的消費根本記不進去。項目允許含數字與空格，金額取結尾那串數字。

### 規則層刻意不做的事

這些一律交給 Claude（純規則模式下則回提示），因為規則做不好，硬做會出錯：

- **修改／取消既有行程**（`把明天的會改到四點`）——要先判斷是哪一個行程
- **沒講時間的行程**（`8/30 生日聚餐`）——不猜一個時間塞進行事曆
- **猜不出分類的記帳**（`阿姨的東西 500`）——不亂塞進「其他」
- **模糊查詢**（`我跟客戶的會是什麼時候`）
- **沒有明確開頭的待辦**（`欸幫我記一下要買貓砂`）——只認 `待辦`／`代辦`／`todo`／`記得`／`提醒我` 開頭，
  模糊的講法跟查行程分不開
- **沒命中任何流程的問句**（`洗衣機壞了怎麼辦`）——除非句子裡明講「流程」「步驟」「SOP」，
  否則寧可不回，也不要回一句「找不到這個流程」讓人以為問錯了

設計原則是**寧可放過、不可誤判**。記帳誤判會直接寫進 Notion，查詢誤判會給出看起來合理但錯誤的答案——這兩者都比老實說「看不懂」更糟。

想調整記帳的分類判斷，改 `rules.py` 最上面的 `_CATEGORY_KEYWORDS`。用 `python scripts/chat.py` 測試時，每則回覆會標示是「規則」還是「Claude」處理的，方便你調規則。

---

## 已知限制

- **待辦的欄位名稱寫死在程式裡**（`todo_api.py` 最上面）。換一個 schema 不同的待辦資料庫要先改那幾個常數，否則寫入會 400。
- **LIFF 網頁只有待辦**，行程與記帳還是走對話。
- **流程清單有 5 分鐘快取**。在 Notion 新增流程後最多 5 分鐘才問得到（從 LINE 新增的會立刻生效）。
- **不記得上一句話**。每則訊息都是獨立處理的，所以「那改到四點」這種接續指令不會work，要重講完整的一句。要多輪對話的話得在 `main.py` 加上每個使用者的短期歷史。
- **確認卡片存在記憶體**。服務重啟（Render 部署或休眠喚醒）後，還沒按的卡片會失效，按下去會回「已過期，請再說一次」。
- **只讀寫一本行事曆**（`GOOGLE_CALENDAR_ID`，預設 `primary`）。
- Claude 若因安全機制拒絕回應，bot 會回一句制式訊息。沒有啟用 server-side fallback，個人行事曆場景幾乎不會遇到。

## 之後可以加的

行程前 N 分鐘提醒、每週日晚上下週行程總覽、傳活動海報截圖讓 Claude 解析後建行程、結合天氣與通勤時間、iOS 提醒事項整合。
