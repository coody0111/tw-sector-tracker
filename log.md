# 開發日誌

> 跨電腦開發用途。每次重要變更後更新並 push，在另一台電腦 pull 後先讀這裡。
> 記錄：進行中的工作、已知問題、重要決策、下一步行動。

---

## 目前狀態（2026-06-26）

### Working tree 乾淨。commit 96d9cf4

### backfill 問題修正（重要）
- **根本原因**：`STOCK_DAY_ALL` endpoint 完全忽略 `date` 參數，永遠回傳最新一天資料
- **影響**：1~4 月歷史資料全部是某一天的複製，巨量換手回測無法命中 1~4 月訊號
- **修法**：`backfill_twse_monthly` 改用 per-stock `STOCK_DAY` endpoint（`_fetch_stock_months`）
- **狀態**：部分修復（TWSE 403 封鎖後只補到 1 月底，2~4 月待 IP 解封後重補）

### 其他修正
- `import_csv_prices`：加去重，避免 UNIQUE constraint 衝突
- `_update_chips_db`：今日法人/融資尚未發布時自動 fallback 前一交易日（凌晨跑不再噴 WARNING）

### 目前回測狀態（40 訊號，2026-01-23 ~ 2026-06-25）
- D+1 勝率 32%，D+3 37%，D+5 42%
- 2~4 月資料待補齊後訊號數量會增加

### 下一步
- **重要**：TWSE IP 解封後，以 workers=2 跑 `--backfill-twse 6` 補 2~4 月
- backfill-institutional 60 ✅（36 天）
- backfill-marg 60 ✅（38 天）

---

## 目前狀態（2026-06-25）

### Working tree：pull 後須確認兩台電腦各有獨立進度

### 已完成功能
- **四項 signal badges**：3/5/7d 累積排名 badge + 漲跌方向 + 連漲連跌 + 量能異常
- **sparkline**：展開面板頂部 10 日 SVG 條形圖
- **籌碼 META 彙總**：`calc_meta_chips_signals()` — 外資/投信連買連賣 + 融資警示
- **籌碼獨立分頁**：`docs/chips.html` — 七區塊籌碼分析，index.html 加導覽連結
- **融資背離警示**：`get_margin_divergence()` — 看空背離 + 融資鬆動，chips.html Section 7（家裡電腦）
- **股票搜尋欄**：header 搜尋 → 自動展開並定位個股卡片
- **先進封裝設備 META**：CoWoS 供應鏈 9 家
- **歷史補齊**：`--backfill-twse 6`（TWSE 月別）、`--backfill 180`（FinMind）
- **訊號掃描器**：`screener/signals.py` 巨量換手三條件
- **回測框架**：`screener/backtest.py`、`--backtest` CLI
- **即時行情**：`scrapers/realtime.py`、`--realtime` CLI（公司電腦 2026-06-25）
- **法人篩選器**：`screener/institutional.py`、`--backfill-institutional 60`（公司）
- **融資 TWSE API**：`fetch_margin_all_twse()`、`--backfill-margin 60`（公司）
- **巨量換手 HTML 區塊**：`index.html` Top10 上方（公司）

### chips.html 區塊（目前 8 區，兩台進度略有差異）
0. 🔥 強力訊號（外資+投信同買 ≥2 日）— 公司新增
1. 外資持續買進 Top 15 / 投信持續買進 Top 15 — 公司新增
2. 外資連買/連賣 META 排行
3. 外資大買/大賣個股 Top10
4. 投信加碼 META 彙總
5. 融資擴張警示（增幅 > 5%）
6. META 外資籌碼集中度
7. 融資背離警示（看空背離 + 融資鬆動）— 家裡新增

### DuckDB 資料狀況（data/screener.db，公司電腦）

| 表格 | 日期範圍 | 筆數/日 |
|---|---|---|
| daily_prices | 2017-01-03 ~ 2026-06-25 | ~1032 支 |
| institutional | 2026-04-27 ~ 2026-06-25 | ~1322 支 |
| margin | 2026-04-27 ~ 2026-06-23 | ~1278 支 |

### 下一步

**P0（最高優先）— 歷史行情補齊**
```bash
python main.py --backfill 180   # 每日 600 次上限，需跑兩天
```
補完後 `daily_prices` 才有 1040 支 × 126 日，巨量換手回測才有完整資料。

**之後可做：**
- `python main.py --backtest`（補齊後跑回測）
- dark/light 主題切換（低優先）
- 上市/上櫃分開顯示（低優先）

---

## 2026-06-23 — UI 大改版：廣度儀表板 + 緊湊卡片 Top10

### 改動內容
- **移除熱力圖**（太醜、與 Top10 重複）
- **新增廣度儀表板（breadth dashboard）**：上漲/下跌/持平進度條 + 最強/最弱 META
- **Top10/Bottom10 改成 10 列緊湊卡片網格**（原本是大型表格）
  - 每張卡：漲跌幅、族群名、漲跌家數，點擊展開個股明細
  - CSS: `mc-grid: repeat(10, 1fr)` — 一行排滿
- **移除頁面 max-width**，body padding 縮為 `12px 20px`，消除左右空白

### 涉及檔案
| 檔案 | 改動 |
|------|------|
| `export/html_generator.py` | `_breadth()` 新增、`_meta_card()` 重寫、`generate()` 調整 |

### 其他（同 session 先前）
- `stock_universe.csv`：37 支股票 META 重新分類（矽晶圓廠移至半導體材料、電信業者獨立成「電信」META 等）
- `config.py`：新增「電信」META 群組

---

## 2026-06-23 — 修正 universe 模式 HTML 未產生的 bug

- 問題：`stock_universe.csv` 模式下 `perf`（小族群列表）為空，導致 `if perf:` 跳過 HTML 產生
- 修法：`main.py` 改為 `if perf or meta_perf:`；`html_generator.py` 在 perf_df 為空時從 meta_perf 計算市場統計
- 今日行情更新成功：1040 支股票、37 META 族群、commit `3d459d9`

---

## 2026-06-19 — Top10 主族群卡片可展開個股細節

- `export/html_generator.py` 大幅擴充（+85 行）
- 主族群 Top10/Bottom10 卡片點擊後展開，顯示旗下個股細節
- commit: `14879a9`

---

## 2026-06-17 — META_SECTORS 主族群分組

### 問題
Top10/Bottom10 漲跌幅排行榜中，同類股票被拆成多個小族群重複出現
（例如 ABF載板、BGA基板 分開列，但本質都是「載板」族群）。

### 方案
在 `config.py` 新增 `META_SECTORS` 字典，把小族群（MoneyDJ 原始分類）歸併成主族群。
Top10/Bottom10 改用主族群加權平均排序，卡片顯示主族群名 + 小族群標籤。

### 涉及檔案
| 檔案 | 改動 |
|------|------|
| `config.py` | `META_SECTORS` dict、`get_meta_sector()` |
| `processors/performance.py` | `calc_meta_performance()` |
| `export/html_generator.py` | `_meta_card()`，`generate()` 新增 `meta_perf` 參數 |
| `main.py` | 串接 `calc_meta_performance` 並傳入 `generate_html` |

### 已修的 bug
`calc_meta_performance` 一開始只收集「有對應主族群」的小族群，
導致沒被收進 `META_SECTORS` 的族群（約 136 個）從 Top10/Bottom10 直接消失。
**修法**：無主族群對應的，fallback to itself（自己單獨成一組），不丟棄。

---

## 2026-06-16 — 籌碼資料（外資/融資）整合進股票卡片

- FinMind API 抓外資買賣超、融資餘額，存入 DuckDB
- `screener/duckdb_manager.py`：`chips` 表格 schema 與 upsert
- `export/html_generator.py`：個股卡片顯示外資/融資數字

---

## 專案背景（新電腦/新 session 速覽）

### 用途
台股產業族群（MoneyDJ 分類）每日漲跌幅追蹤，產出靜態 HTML 報表（`docs/index.html`）。
GitHub Pages 直接 serve，每日自動更新。

### 資料流
```
scrapers（twse / tpex / moneydj / finmind / chips）
  → processors（changes / performance）
  → storage（CSV）+ screener（DuckDB）
  → export（html_generator）
  → docs/index.html  →  git push  →  GitHub Pages
```

### 主要檔案
| 檔案/目錄 | 說明 |
|-----------|------|
| `main.py` | 入口，串接所有流程 |
| `config.py` | 設定、META_SECTORS 分組 |
| `scrapers/` | 各資料來源爬蟲 |
| `processors/` | 漲跌計算、族群績效彙總 |
| `screener/` | DuckDB 籌碼資料 |
| `export/html_generator.py` | HTML 產生 |
| `docs/index.html` | 輸出報表（GitHub Pages） |
| `scheduler_setup.bat` | Windows 排程設定 |

### 環境
- Python 3.x，Windows
- 每日排程跑 `python main.py`，自動 commit + push
- `docs/` 透過 GitHub Pages 對外公開
