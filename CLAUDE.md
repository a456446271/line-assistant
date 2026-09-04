# LINE 個人助理

## 專案規則

- **對話裡的行事曆寫入一律要經過使用者確認**。`agent.py` 的 `propose_create_event` 只產生待確認項目，對話流程真正呼叫 `calendar_api.create_event` 的地方只有 `main.py` 處理 `confirm_event` postback 的那一段。不要為了「方便」讓 agent 直接寫入行事曆。
- **LIFF 網頁是這條規矩唯一的例外，而且是有理由的**：卡片存在是為了防「AI 把話解讀錯」，但網頁上的日期時間是使用者自己在表單欄位選的，沒有任何解讀空間，表單本身就是確認。再加一層卡片只是多按一次。
- **`calendar_api.delete_event` 是真的刪掉**，Google 沒有封存這種中間狀態。所以它只從 LIFF 的清單上按得到（點著某一列刪），不開放給規則層或 agent——那兩個都有「猜錯是哪一個」的風險。
- **對話一律用 reply，只有排程通知用 push**。LINE 的 reply 不計入每月 200 則免費額度，push 會。新增任何主動通知前先想清楚會吃掉多少額度。
- Webhook 必須立刻回 200，實際處理丟 `BackgroundTasks`。不要在 `/webhook` 裡同步跑 Claude。
- 記帳分類必須和 Notion 資料庫「分類」欄位的 Select 選項完全一致，來源是 `.env` 的 `BUDGET_JSON` 的 key。
- 時間一律用 `config.TZ`（預設 Asia/Taipei）。Google Calendar 的全日行程回 `date` 而非 `dateTime`，兩種都要處理。
- Notion API 版本釘在 `2022-06-28`（`config.NOTION_VERSION`）。較新版本把 `database_id` 換成 `data_source_id`，升版前要先改 `expense_api.py`。
- 機密設定放 `.env`，已被 .gitignore 排除，不要寫進任何提交或文件中。
- **`rules.py` 是規則層**，日常常見句型（記帳、查今天明天行程、查月消費、查預算）在這裡用正規表達式處理掉，不呼叫 Claude。接不住就回 `None` 交給 `agent.run()`。這是成本控制的主要手段，加功能時優先想能不能用規則做。
- 規則層的原則是**寧可放過、不可誤判**。記帳規則誤判會直接寫進 Notion，所以句子裡有「開會、提醒、行程、預約、點」或日期符號時一律不當成記帳；猜不出分類時也交給 Claude，不要塞進「其他」。
- **`ANTHROPIC_API_KEY` 是選填的**。`config.LLM_ENABLED` 為 False 時是純規則模式：規則接不住就回提示，早報與月報改成直接排版。任何新增的 Claude 呼叫都要先檢查 `config.LLM_ENABLED`，否則純規則模式會壞掉。
- **中文日期時間解析在 `zh_datetime.py`**，跟業務邏輯分開，方便單獨測試。要支援新的時間講法改這裡，不要在 `rules.py` 裡另外寫日期解析。
- **Notion 的 HTTP 底層集中在 `notion.py`**（標頭、版本、分頁、rich text 攤平）。`expense_api.py`／`todo_api.py`／`sop_api.py` 只管各自那張表的欄位與查詢，不要再各自寫 httpx。
- **待辦用一張自己控制的乾淨表**，不接生活模板附的那種待辦庫（三十幾個欄位、公式、按鈕、重複性任務機制），綁上去只會讓模板一改版就壞掉。欄位名稱集中成 `todo_api.py` 最上面的 `PROP_*` 常數，改資料庫只改那裡。
- **待辦清單過濾在 `todo_api._row()`**：沒標題的空白列不列，在 LINE 上既顯示不了也按不了。
- **完成是打勾、刪除是封存**，兩者都不是真的刪。完成紀錄留著能回顧，封存三十天內能從 Notion 垃圾桶救回來。
- **流程的步驟放頁面內容，不放欄位**。rich text 欄位有 2000 字上限，而且在 Notion 裡編一篇文件比編一格文字好用。讀取時 `sop_api._TEXT_BLOCKS` 刻意放寬，使用者用什麼排版都讀得到。
- **`_match_todo_add` 必須排在記帳規則前面**。「待辦 咖啡豆 300」如果先給記帳規則看，會被記成一筆 300 元的餐飲支出。
- **`_match_sop_query` 必須排在 `_match_calendar` 後面**。它的觸發詞含「怎麼」「要做什麼」，排前面的話「明天怎麼安排」會跑去找流程。也因為排在後面，觸發詞才能放寬。
- 查流程沒命中時，只有句子明講「流程」「步驟」「SOP」才回「沒有這份流程」，否則回 `None`。不然「洗衣機壞了怎麼辦」會得到一句看似合理的廢話。
- `NOTION_TODO_DB_ID` 與 `NOTION_SOP_DB_ID` 是選填的，用 `todo_api.enabled()`／`sop_api.enabled()` 判斷。新增相關程式碼都要先檢查，否則沒設的人會壞掉。agent 的工具清單也是照這個條件動態組的。
- 加新的 Notion 資料庫時，**integration 的連線權限不會自己擴散**，每個資料庫都要在 Notion 頁面裡各自加一次，否則 404。`scripts/check_notion.py` 會逐一檢查並指出是哪一個。
- **LIFF 的 `/api/*` 端點只靠 ID token 擋外人**。webhook 有 channel secret 的簽章，但 `/api` 是瀏覽器直接打的，沒有那層保護。`_liff_user()` 是唯一的門：驗 token → 比對 `ALLOWED_USER_IDS`。新增任何 `/api` 端點都要先呼叫它，漏掉等於把資料公開在網路上。
- **驗 ID token 一定要帶 audience**（`client_id=LINE_LOGIN_CHANNEL_ID`），否則別的 channel 發的 token 也會通過。驗證送去 LINE 的 `/oauth2/v2.1/verify` 而不是自己解 JWT，簽章與有效期就不會自己實作錯。
- **LIFF 掛在 LINE Login channel，不是 Messaging API channel**（LINE 已經不允許後者）。所以 audience 是 Login channel 的 id，`LINE_LOGIN_CHANNEL_ID` 這個名字就是為了不要填錯。那個 Login channel 必須跟 Messaging API channel 同一個 Provider，否則 ID token 的 `sub` 會跟 `ALLOWED_USER_IDS` 裡的 user id 對不起來。
- `LIFF_ID` 與 `LINE_LOGIN_CHANNEL_ID` 少一個就整個停用（`config.LIFF_ENABLED` 為 False，端點回 404），不會半開著跑。
- **Rich Menu 的圖不要用 ✓ ▤ 這類符號**，微軟正黑體沒有那些字形，會印成豆腐塊。`scripts/setup_richmenu.py` 改用色點。Pillow 只有那支腳本要用，不要加進 `requirements.txt`（Render 上永遠不會執行它）。
