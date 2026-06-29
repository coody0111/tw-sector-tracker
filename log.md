# 開發日誌

> 跨電腦開發用途。每次重要變更後更新並 push，在另一台電腦 pull 後先讀這裡。
> 記錄：進行中的工作、已知問題、重要決策、下一步行動。

---

## 目前狀態（2026-06-29）

### 代辦清單（依優先順序）

**P1 — 資料補齊（先做，其他任務的前置依賴）**
- [x] `python main.py --backfill-institutional` — 補齊至 2026-06-29，寫入 1328 支（2026-06-29）
- [ ] `python main.py --backfill-twse 6` — 每日收盤後（17:00+）跑，避免 TWSE rate limiting
- [ ] `import_csv_prices()` 全量匯入 — DuckDB 只有最近 134 天，CSV 有 2017 年至今，需全量匯入讓 backtest 能用完整歷史

**P1 — 回測（已完成）**
- [x] `python main.py --backtest` — 巨量換手 393訊號（2026-01-06~06-29），D+5勝率47%/+1.71%（資料更完整後改善）
- [x] `python main.py --backtest-patterns 120` — 雙底5248次(D+10:43%/-1.1%)、雙頂905次(D+10:60%/+4.3%)、60日突破582次(D+10:21%/-5.5%)
  - 注意：雙底勝率大幅下滑（前53%→43%），原因是TWSE補齊後市場覆蓋更廣，2026H1空頭環境假突破多
  - 60日突破在下跌市表現極差，需加市場廣度過濾條件

**P1/P2 — UI 改版**
- [x] chips.html Tab 切換：8 個表格 → [🔥強力訊號][外資/投信][⚠融資警示][META分析] 4 個 Tab (2026-06-29, commit a7a1757)
- [x] patterns.html SVG 走勢縮圖 + 勝率標籤：雙底 D+10 53% / 雙頂 D+5 61% (2026-06-29)
- [x] chips.html 新增「🏦 大戶持倉」Tab — 集保 ≥400張 連增/連減倉排行 (2026-06-29)

**P1/P2 — 新功能：大戶持倉**
- [x] 新增 `scrapers/shareholder.py` — TDCC 集保 API，每週更新，計算大戶持股比例週變化
  - 修正：每次 POST 前重新取 token（CSRF token 一次性）
  - 修正：合計行偵測改為搜尋「合」字（部分股票有差異數調整使合計變第17行）
  - 全量跑 1040 支：成功率 ~97%（約 30 支 SSL EOF 失敗，屬 TDCC 間歇性問題）
- [x] `screener/database.py` 新增 `get_shareholder_top()` 查詢函式
- [x] chips.html 新增大戶增倉區塊（tab-holder，連增/連減倉各顯示 30/20 支）
- [x] 綜合評分系統 0-100：外資25+投信20+形態25+量能15+大戶15，融資扣分 — `calc_composite_score()` in screener/patterns.py（2026-06-29）

**每週執行（週五盤後）**
- `python main.py --update-shareholder` — 集保大戶持倉更新（~1040 支，35min）

**P3 — 低優先**
- [x] 上市/上櫃分開顯示 — exchange 欄位 + [全部/上市/上櫃] 過濾按鈕（chips.html + patterns.html）（2026-06-29）

---

## 目前狀態（2026-06-26）

### Working tree 乾淨。commit f71232a

### backfill partial_twse bug 完整修復 ✅
- **根本原因（二次 bug）**：2302 在 TWSE Phase 1 取得 Jan+Feb 資料後 `is_twse=True`，但 Mar-May 403 失敗 → `months_ok < len(month_starts)` → 原本不加進 non_twse，Phase 2 不補 → 舊壞資料（50.2）留存
- **修法**：新增 `months_ok` 回傳值 + `partial_twse` list；Phase 2 補齊 partial_twse，`twse_covered` set 防覆蓋已有 TWSE 資料
- **結果**：2302 全 6 個月覆蓋正確（Jan 17.35~21.35 → Jun 31.5~50.2 真實行情）；回測 392 訊號，0 筆虛假 2302 訊號
- **6907 Jan 只有 2 天**：2026-01-29 掛牌新上市，正常

### 回測狀態（392 訊號，2026-01-06 ~ 2026-06-26）
- 資料完整，無虛假訊號

### 已完成功能（META 四件組）✅
- **sparkline**：展開面板頂部 10 日 SVG bar chart
- **連漲/連跌 badges**：連漲N日/連跌N日（≥2 才顯示）
- **成交量異常 badge**：量↑Nx（vol_ratio ≥ 1.5 顯示）
- **排名升降 badge**：↑N / ↓N（vs 昨日排名）
- 全部在 `calc_meta_signals()` (performance.py) + `_meta_card()` (html_generator.py) 實作完成

### 下一步
- chips.html 強化（法人連買排行、融資警示）詳見先前 /plan 規劃

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
