# 排程通知系統實作規格

## 1. 目標

在指定時間自動執行台股程式，並將重要結果傳送到手機。

第一版採用：

- Windows 工作排程器
- Telegram Bot
- 桌電作為唯一正式排程主機
- 盤中每 15 分鐘監控
- 收盤後執行完整 `main.py`
- 防止重複執行、重複通知與 Git 衝突

LINE 暫不納入第一版。LINE Notify 已於 2025 年 3 月 31 日停止服務，目前需改用設定成本較高的 LINE Messaging API。

參考資料：

- [Telegram Bot 官方教學](https://core.telegram.org/bots/tutorial)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [LINE Notify 終止服務公告](https://developers.line.biz/en/news/2025/04/01/line-notify/)
- [Windows schtasks 官方文件](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks-create)

## 2. 執行模式

### 2.1 盤中監控 `intraday`

執行時間：

```text
週一至週五
09:00～13:30
每 15 分鐘
```

排程執行：

```powershell
python scripts/run_scheduled.py intraday
```

內部呼叫：

```powershell
python main.py --realtime --no-push --summary-json logs/latest_summary.json
```

行為：

- 抓取即時行情
- 計算市場狀態與籌碼訊號
- 不建立 Git commit
- 不推送 GitHub
- 只有重要結果改變才通知
- 沒有變化時不傳送訊息

### 2.2 收盤更新 `close`

執行時間：

```text
週一至週五 15:00
```

排程執行：

```powershell
python scripts/run_scheduled.py close
```

內部呼叫：

```powershell
python main.py --summary-json logs/latest_summary.json
```

行為：

- 執行完整每日更新
- 更新 HTML
- 建立 commit、同步遠端並推送 GitHub
- 無論訊號是否改變，皆傳送每日摘要
- 資料不完整時在通知中明確標示

### 2.3 通知測試 `test-notify`

```powershell
python scripts/run_scheduled.py test-notify
```

用途：

- 驗證 Bot Token
- 驗證 Chat ID
- 驗證手機能收到通知
- 不執行爬蟲與 Git 操作

## 3. 系統架構

```text
Windows Task Scheduler
          │
          ▼
scripts/run_scheduled.py
  ├─ 檢查交易日與時間
  ├─ 取得執行鎖
  ├─ 執行 main.py
  ├─ 讀取 latest_summary.json
  ├─ 比對 notification_state.json
  ├─ 決定是否需要通知
  └─ 寫入 scheduler.log
          │
          ▼
notifications/telegram.py
          │
          ▼
Telegram Bot → 手機
```

## 4. 預計檔案結構

```text
notifications/
├─ __init__.py
└─ telegram.py

scripts/
├─ run_scheduled.py
└─ install_scheduler.ps1

tests/
├─ test_scheduled_runner.py
└─ test_telegram_notifier.py

logs/
├─ scheduler.log
├─ latest_summary.json
└─ scheduler.lock

data/
└─ notification_state.json

.env.example
scheduler_setup.bat
main.py
.gitignore
```

### 4.1 `notifications/telegram.py`

責任：

- 呼叫 Telegram `sendMessage`
- 處理 timeout 與 HTTP 錯誤
- 分割超長訊息
- 不將 Bot Token 輸出到 log

### 4.2 `scripts/run_scheduled.py`

責任：

- 作為排程總控制器
- 防止重複執行
- 執行 `main.py`
- 整理成功或失敗通知
- 過濾非交易日及非盤中時間

### 4.3 `scripts/install_scheduler.ps1`

責任：

- 建立 Windows 排程
- 使用目前 Python 的絕對路徑
- 使用專案的絕對路徑
- 設定已有執行個體時不啟動新的執行個體
- 設定錯過收盤排程時，在電腦恢復後補執行

## 5. `main.py` 修改

新增參數：

```python
parser.add_argument(
    "--no-push",
    action="store_true",
    help="產生結果但不執行 Git commit/push",
)

parser.add_argument(
    "--summary-json",
    type=str,
    default=None,
    help="將本次執行摘要輸出為 JSON",
)
```

調整呼叫方式：

```python
run(
    realtime=args.realtime,
    push=not args.no_push,
    summary_path=args.summary_json,
)
```

原本：

```python
_push_html(trade_date)
```

調整為：

```python
if push:
    _push_html(trade_date)
```

盤中模式因此不會每 15 分鐘建立 Git commit。

## 6. 執行摘要格式

輸出位置：

```text
logs/latest_summary.json
```

成功範例：

```json
{
  "status": "success",
  "mode": "intraday",
  "started_at": "2026-07-16T10:30:00+08:00",
  "finished_at": "2026-07-16T10:31:25+08:00",
  "trade_date": "2026-07-16",
  "market_regime": "bull",
  "market_regime_label": "多頭",
  "signals": [
    {
      "stock_id": "2330",
      "stock_name": "台積電",
      "signal_type": "joint_buy",
      "signal_label": "外資投信同步買超",
      "score": 82
    }
  ],
  "warnings": [],
  "html_updated": false,
  "git_pushed": false,
  "duration_seconds": 85
}
```

失敗範例：

```json
{
  "status": "failed",
  "mode": "close",
  "error": "TPEx API timeout",
  "duration_seconds": 130
}
```

## 7. 通知規則

### 7.1 盤中發送條件

- 新增重要訊號
- 原有訊號消失
- 訊號分數跨過門檻
- 市場狀態改變
- 資料來源失敗
- 程式執行失敗

### 7.2 盤中不發送條件

- 訊號與上次完全相同
- 只有執行時間改變
- 只有 HTML 排版或非投資訊息改變

### 7.3 收盤固定發送內容

- 市場狀態
- 訊號數量
- 前 5 名訊號
- 資料完整性
- GitHub push 是否成功
- 網站連結

### 7.4 盤中通知範例

```text
台股盤中更新｜10:30

市場狀態：多頭
新增訊號：2 檔

2330 台積電
外資投信同步買超｜分數 82

2382 廣達
外資連買 3 日｜分數 76

資料異常：無
```

### 7.5 失敗通知範例

```text
台股排程執行失敗｜15:02

模式：收盤更新
錯誤：TPEx API timeout
執行時間：2 分 10 秒

已保留 logs/scheduler.log
網站未推送
```

## 8. 防重複機制

必須同時實作執行鎖與通知去重。

### 8.1 執行鎖

鎖定檔案：

```text
logs/scheduler.lock
```

規則：

- 有其他程序執行時，本次直接結束
- 避免上一輪超過 15 分鐘，下一輪又啟動
- 程序異常結束後，鎖必須能自動釋放
- 鎖定狀態要寫入 `scheduler.log`

### 8.2 通知去重

狀態檔案：

```text
data/notification_state.json
```

格式：

```json
{
  "last_signal_hash": "abc123",
  "last_market_regime": "bull",
  "last_notified_at": "2026-07-16T10:30:00+08:00"
}
```

只有影響通知內容的資料 hash 改變時，才發送盤中通知。

## 9. 環境變數

`.env.example` 預計新增：

```dotenv
FINMIND_TOKEN=your-finmind-api-token-here
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
TELEGRAM_CHAT_ID=your-telegram-chat-id
SITE_URL=https://coody0111.github.io/tw-sector-tracker/
```

安全規則：

- `.env` 不得加入 Git
- Token 不得寫入 log
- Telegram 錯誤訊息不得包含完整 Token
- Token 外洩時必須透過 BotFather 撤銷並重建

## 10. Windows 排程

建立兩個工作：

```text
TW-Sector-Intraday
TW-Sector-DailyClose
```

### 10.1 盤中工作

```text
觸發：週一至週五 09:00
重複：每 15 分鐘
持續：4 小時 45 分鐘
```

### 10.2 收盤工作

```text
觸發：週一至週五 15:00
錯過排程：電腦恢復後立即執行
```

### 10.3 執行限制

- 桌電關機時無法盤中執行
- 桌電睡眠時需設定喚醒電腦執行工作
- 桌電與筆電不可同時啟用正式排程，否則可能同時 push Git
- 正式排程應使用穩定的正式工作目錄，不應指向暫時性 worktree

## 11. 測試要求

### 11.1 單元測試

- Telegram 成功發送
- Telegram timeout
- Token 缺少時安全失敗
- 非交易日不執行
- 非盤中時間不執行
- 執行鎖生效
- 訊號相同時不重複通知
- 訊號改變時才通知
- `--no-push` 不執行 Git
- `main.py` 失敗時傳送錯誤通知
- 通知狀態檔損壞時能安全重建

### 11.2 人工驗收

1. 執行 `test-notify`，手機收到測試訊息。
2. 執行一次 `intraday`，不產生 Git commit。
3. 立刻再執行相同資料，不重複通知。
4. 模擬新訊號，手機收到通知。
5. 執行 `close`，HTML 更新並成功 push。
6. 工作排程器可以正常啟動且工作目錄正確。
7. 同時啟動兩次 runner，第二次應安全結束。
8. 中斷網路後，手機收到或在恢復後補送失敗資訊。

## 12. 實作順序

1. 建立 Telegram Bot 並設定 `.env`。
2. 實作 `notifications/telegram.py`。
3. 替 `main.py` 加入 `--no-push`。
4. 實作 `latest_summary.json`。
5. 實作 `scripts/run_scheduled.py`。
6. 加入執行鎖與通知去重。
7. 補齊單元測試。
8. 實作 `scripts/install_scheduler.ps1`。
9. 進行手機實機測試。
10. 啟用正式排程。

## 13. 第一版完成條件

以下條件全部成立才算第一版完成：

- Telegram 測試通知可送達手機
- 盤中每 15 分鐘排程可正常執行
- 非交易時間不執行爬蟲
- 盤中模式不 commit、不 push
- 相同訊號不重複通知
- 收盤模式可更新頁面並推送 GitHub
- 執行失敗時可收到錯誤通知
- 排程重疊時不會同時執行兩個 `main.py`
- Token 未出現在 Git、log 或錯誤輸出中

第一版完成後，再評估 LINE Messaging API、圖片通知、Telegram 指令查詢及雲端常駐執行。
