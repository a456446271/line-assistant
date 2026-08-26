# LINE 個人助理

## 專案規則

- **行事曆的寫入一律要經過使用者確認**。`agent.py` 的 `propose_create_event` 只產生待確認項目，真正呼叫 `calendar_api.create_event` 的地方只有 `main.py` 處理 `confirm_event` postback 的那一段。不要為了「方便」讓 agent 直接寫入行事曆。
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
