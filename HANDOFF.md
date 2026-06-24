# 交接文件 — tw-sector-tracker

日期：2026-06-24  
交接給：Codex

---

## 專案概述

台股產業族群追蹤器。每日抓 TWSE + TPEx 行情，計算各 META 族群漲跌，生成 `docs/index.html` 推上 GitHub Pages。

**每日執行：** `python main.py`  
**部署：** GitHub Pages → `docs/index.html`

---

## 目前 DuckDB 資料狀況（`data/screener.db`）

| 日期範圍 | 股票數/日 | 來源 |
|---|---|---|
| 2026-01-02 ~ 2026-06-18 | 27 支 | TWSE 補齊（有 bug，見下） |
| 2026-06-22 | 552 支 | FinMind 補齊（partial） |
| 2026-06-23 ~ 2026-06-24 | 1031 支 | 日常 TWSE+TPEx scraper |

**歷史資料有嚴重問題：** 只有 27 支股票有 6 個月歷史，其餘 1013 支都沒有。  
27 支清單：`1516, 1537, 2301, 2303, 2312, 2324, 2328, 2330, 2331, 2352, 2353, 2355, 2363, 3231, 3515, 3701, 3706, 3711, 3715, 4919, 4938, 5434, 6239, 6281, 8112, 8210, 9105`

---

## 歷史補資料失敗的根本原因

`scrapers/backfill.py` 有兩個函式：

### 1. `backfill_twse_monthly()` — TWSE 逐股月別（今天寫的，有 bug）

**問題：** 用了 `ThreadPoolExecutor(max_workers=5)`，5 個 worker 同時打 TWSE，觸發速率限制。TWSE 對被限速的請求回傳「無資料」，而 skip 邏輯把「連 2 個月無資料」視為「這支不在 TWSE」並跳過。結果：1013/1040 支股票因誤判全部被跳過。

**正確修法（兩選一）：**

**A. 修 skip 邏輯** — 只在收到特定訊息 `"很抱歉，沒有符合條件的資料"` 時才記為「非 TWSE」，若是 timeout 或其他網路錯誤則不跳過：

```python
# 在 _fetch_stock_months 裡
if data.get("stat") != "OK" or not data.get("data"):
    # 區分「真的沒資料」和「被限速/網路錯誤」
    stat_msg = data.get("stat", "")
    if "沒有符合條件" in stat_msg or "查詢日期" in stat_msg:
        stock_fail += 1  # 真的不在 TWSE
    # else: 被限速，不計入 stock_fail
```

同時把 workers 降到 2，sleep 從 0.1s 增到 0.5s。

**B. 改用 FinMind（更穩定，推薦）**

### 2. `backfill_prices()` — FinMind 逐股抓（可靠但有每日 600 次上限）

- 今天的 quota 已用完（前兩次跑用掉 600 次）
- **明天 quota 重置後**：`python main.py --backfill 180`
- 每次跑約 550 支（遇上限自動停止，提早退出有 log）
- 需跑 **2 次**（分兩天）才能涵蓋全部 1040 支
- 多次執行會自動 merge CSV，不會覆蓋已有資料

---

## 立即待辦事項（優先順序）

### P0 — 補齊歷史資料（最高優先）

**方案（推薦走 FinMind）：**

```bash
# 明天（2026-06-25）quota 重置後
python main.py --backfill 180   # 約 13 分鐘，得 ~550 支 × 6 個月

# 後天（2026-06-26）
python main.py --backfill 180   # 再跑一次補剩下 ~490 支
```

跑完後 DuckDB 會有 1040 支 × 126 個交易日（約 6 個月）歷史。

清理目前的 27 支垃圾資料（可選）：
```python
import duckdb
con = duckdb.connect("data/screener.db")
con.execute("DELETE FROM daily_prices WHERE date < '2026-06-22'")
con.close()
```
然後刪掉 `data/daily_prices/2026-01*.csv` 到 `data/daily_prices/2026-06-18*.csv`，重新 import。

### P1 — 巨量換手回測（資料備齊後）

```bash
python -c "
from screener.backtest import run_backtest, print_summary
df = run_backtest()
print_summary(df)
"
```

`screener/backtest.py` 和 `screener/signals.py` 已寫好，只等資料。  
三個條件：① 成交量 N 日最大值 ② 當日收盤 < 前日且跌幅 > -9.5% ③ 前日漲幅 ≥ 9.5%

### P2 — HTML 加入巨量換手區塊

把今日訊號顯示在 `docs/index.html`，呼叫 `scan_volume_turnover('2026-06-24')` 取得結果後加 HTML section。

### P3 — 籌碼面功能（有完整設計稿）

設計稿在 `.claude/plans/swirling-enchanting-sphinx.md`。
- P1: META 層級籌碼摘要 (`calc_meta_chips_signals()` 在 `processors/performance.py`)
- P2: 個股外資/投信 badge
- P3: 分組區改 mini-card grid
- P4: 手機版 RWD

---

## 關鍵技術說明

### TWSE API 特性
- `STOCK_DAY_ALL`：回傳**當日**全股行情（CSV 格式，需 User-Agent header）
- `STOCK_DAY?stockNo=2330&date=20260301`：逐股**月別**歷史（JSON，有效）
- 兩者都需要 browser User-Agent，否則回傳空值

### TPEx API 特性
- `tpex_mainboard_quotes`：當日全股行情（無歷史）
- 逐股歷史端點：在公司網路環境 SSL handshake 超時，無法使用
- **結論：TPEx 歷史只能用 FinMind 抓**

### FinMind 使用
- Token: 在 `scrapers/chips.py` 的 `FINMIND_TOKEN`
- Dataset: `TaiwanStockPrice`，支援 `start_date`/`end_date` 查歷史
- 免費帳號：每日約 600 次請求上限
- 帳號：learncody1@gmail.com

### DuckDB Schema（`data/screener.db`）
```sql
daily_prices:  date, stock_id, close, change, change_pct, volume
institutional: date, stock_id, foreign_net, trust_net, dealer_net, total_net
margin:        date, stock_id, margin_buy, margin_sell, margin_balance, margin_change
```

### 股票清單
- `data/stock_universe.csv`：1040 支股票，含 `meta_sector`（大分類）、`sub_sector`（小族群）
- 每日行情 CSV：`data/daily_prices/YYYY-MM-DD.csv`

---

## 今天的已知問題清單

| 問題 | 狀態 | 解法 |
|---|---|---|
| 歷史資料只有 27 支 | ❌ 未解 | 明天 FinMind 補齊 |
| TWSE backfill 的 skip 邏輯在高並發下誤判 | ❌ 有 bug | 修 skip 邏輯或直接用 FinMind |
| 三大法人（institutional）今日資料 | ⚠️ 需確認 | 每天 3:30 後跑 `main.py` 會自動抓 |
| git commit author 問題 | ✅ 已修（在上一個 session）| - |

---

## 檔案結構

```
scrapers/
  twse.py          # 每日 TWSE 全股行情（User-Agent + CSV parse）
  tpex.py          # 每日 TPEx 行情
  finmind.py       # fetch_prices_for_stocks()（組合 TWSE+TPEx 當日）
  chips.py         # fetch_institutional(), fetch_margin_all_today()
  backfill.py      # backfill_prices() + backfill_twse_monthly()

processors/
  performance.py   # calc_meta_chips_signals() 等計算函式
  changes.py       # 成份股異動偵測

screener/
  database.py      # DuckDB init, import_csv_prices()
  signals.py       # scan_volume_turnover()（巨量換手訊號）
  backtest.py      # run_backtest(), print_summary()

export/
  html_generator.py  # generate() → docs/index.html

main.py            # CLI entrypoint：run / --update-sectors / --backfill / --backfill-twse
```
