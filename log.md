# 開發日誌

## 2026-08-31 — 官方基本面資料層 Phase 1

### 需求來源

- Cody：需要 EPS、各種財報數字與月增／年增，並指定只使用上市／上櫃官方資料，不使用 FinMind。
- Spec：`docs/superpowers/specs/2026-08-31-official-fundamentals-data-design.md`

### 預計範圍

- 新增 TWSE／TPEx 官方月營收、損益表與資產負債表 scraper。
- 新增 DuckDB `monthly_revenue`、`financial_facts` 與衍生 view。
- 新增 `main.py --update-fundamentals` 獨立更新命令。
- 補 parser、upsert、成長率與 CLI dispatch 的聚焦測試。

### 初步風險與決策

- 官方 OpenAPI 只提供最新一期、沒有日期參數；Phase 1 從現在開始累積快照，MOPS XBRL 歷史回補另列 Phase 2。
- TPEx 識別欄混用英文、TWSE 使用中文，必須分來源 mapping 後再合併。
- 損益表是累計值；EPS 不以累計相減推單季，避免配股／分割追溯調整造成錯值。
- 依 Developer 規則，本 session 不執行主程式抓資料、不跑 pytest、不修改 `.env`。

### 完成內容

- `scrapers/fundamentals.py`：新增 TWSE／TPEx 官方端點、ROC 日期轉換、兩市場欄位正規化、
  六種產業 schema 財報展開、重複主鍵衝突偵測及 DuckDB 原子 upsert。
- `screener/database.py`：新增 `monthly_revenue`、`financial_facts`、
  `monthly_revenue_growth`、`financial_fact_growth`。
- `main.py`：新增獨立 `--update-fundamentals` dispatch；同一市場的月營收及財報共用一個 transaction。
- `tests/test_fundamentals.py`：涵蓋 TWSE／TPEx parser、空值與負數、ROC 日期、重跑保留首次觀察時間、
  月份缺洞、Q2 缺 Q1、transaction rollback。
- `docs/fundamentals.md`：新增操作方式、查詢範例、資料口徑與目前限制。

### 驗證

- 已執行 AST 靜態語法解析：`scrapers/fundamentals.py`、`screener/database.py`、`main.py`、
  `tests/test_fundamentals.py` 均通過。
- 已執行 `git diff --check`（限定本次 tracked 檔案），無 whitespace error。
- 依 Developer 規則未執行 pytest、未呼叫官方 API 實跑、未執行 `python main.py --update-fundamentals`；
  這三項交由 Debugger／Cody 驗證。

### 尚未納入

- MOPS XBRL 歷史回補、現金流量表、申報版本與正式公告日屬 Phase 2。
- UI／選股分數尚未接入基本面資料，避免在資料完整性驗證前擴大範圍。

---

> 跨電腦開發用途。每次重要變更後更新並 push，在另一台電腦 pull 後先讀這裡。
> 記錄：進行中的工作、已知問題、重要決策、下一步行動。

---

## 2026-08-25 籌碼頁（chips.html）重構前置：訊號有效性稽核 — spec 已寫好，等 Cody review 分類

**起因：** Cody 想重構籌碼頁但不確定方向/程度，brainstorming 挖出更根本的問題——不確定籌碼
資料本身有沒有實際用得上的價值。與其找外部 paper，改用專案自己現成的回測框架
（`screener/backtest.py`）驗證，資料更貼近實際使用情境。

**進度：** spec 已寫好+commit：
`docs/superpowers/specs/2026-08-25-chips-page-signal-audit-design.md`。**尚未開始視覺/資訊架構
改版**，`ui-ux-pro-max` 還沒跑。

**做了什麼：**
1. 盤點發現 chips.html 9 個 tab 只有 5 個對應到 `CHIPS_RULES` 已定義的回測規則
2. 補上「越跌越買」「外資偷偷買」對應的 `dip_buy`/`stealth_buy` 規則（commit `92389fb`），
   讓 7 個 tab 有回測結果可查——族群層級訊號改用個股自己的 `price_cum_pct`(5日) +
   `foreign_streak`/`trust_streak` 做近似（回測需要買到具體個股，沒有可交易的族群標的）
3. review 過回測框架核心機制（進出場時序/成本處理/漲停剔除/regime分段），確認無前瞻偏誤，
   唯一 caveat 是「大盤基準」用的是等權平均而非真正 TAIEX（`docs/superpowers/plans/
   2026-07-14-backtest-framework.md` 記錄的刻意決定，非 bug）
4. 「董監持股」查證後資料只有 3 個月頻快照，樣本不足，本次不勉強補回測

**結論：** 11 條規則裡沒有一條展現穩定 edge。表現最不糟的是 `stealth_buy`（外資偷偷買）也只是
接近打平；唯一在做自己該做的事的是 `margin_bearish`（融資警示，它本來就是風險提示不是選股
訊號）。依證據強度分四級（🔴建議砍/🟡降級改觀察性語氣/🟢保留現有定位/⚪樣本不足待補），詳見
spec。

**下一步：** 等 Cody 逐項確認四級分類，確認後進 `ui-ux-pro-max` skill 做視覺/資訊架構設計。

---

## 2026-08-25 首頁（index.html）版面/視覺重設 — brainstorming 完成，等 Cody review spec

**進度：** `superpowers:brainstorming` 走完全程，spec 已寫好+commit：
`docs/superpowers/specs/2026-08-24-index-homepage-redesign-design.md`（commit `4744d19`）。
**尚未開始實作**，`writing-plans` 也還沒跑。

**定案的 6 項改動：**
1. 版面重排：熱區格滿版置頂當主角（現況「異動族群→熱區格→族群近況」順序跟優先序不符）；
   下方雙欄：異動族群（左）｜族群近況+轉折點合併（右）
2. 異動族群加排序：`find_anomaly_cards()`（`export/index_generator.py:191`）目前完全沒排序，
   卡片依 dict 插入順序輸出——改成 burst 優先、同 kind 內依 `abs(pct)` 降冪，卡片視覺大小不變
3. 視覺「深色進化版」：CSS 變數（配色/字型）完全不動，只加玻璃質感+微光暈到超強tier/警示狀態，
   spec 裡特別註記淺色主題（`:root[data-theme="light"]`）要另外處理色值，不能沿用深色寫死的
   rgba
4. 個股明細面板改錨定在熱區格區塊「下方」（`selectGroup()`，現況插進 tile 網格中間、打斷排列）
5. 面板內走勢/籌碼摘要/歷史進榜三區從垂直堆疊改並排三欄
6. 補齊 4 項已算好但沒接進面板的資料：自營商(`dealer_net`)、每週報酬%(`weekly_returns`)、
   大戶佔比+週變化(`shareholder`表)、外資/投信本週累計買賣超(新算法，近5交易日加總)

**明確排除（YAGNI，另立後續任務）：** 異動族群門檻（`vol_ratio>=1.5`/排名跳動`>=10`/
`streak>=5`）緊化需要回測數據支持，跟這次版面/視覺調整性質不同，不在這次範圍內。

**順便撿到的舊帳：** 2026-07-23 遺留的兩項驗證欠款（熱區格鍵盤操作 Tab/Enter/Space、手機版
responsive）已經寫進這次 spec 的測試策略，要求跟這次新排版一起補測，不是另開新欠款。

**下一步：** 等 Cody review `docs/superpowers/specs/2026-08-24-index-homepage-redesign-design.md`，
確認後續跑 `writing-plans` 拆成實作任務。

---

## 2026-07-22 族群總覽頁熱區格改版計畫 Task 1 完成

**完成內容：**
- 新增 `processors/performance.py::_streak_and_windows_as_of()` 純函式
- 功能：回推任意時間點（cutoff_index）的 streak/上週/本週 5 日窗口複利報酬
- 用途：族群總覽頁轉折點回推（不用存歷史快照，直接回推計算）

**測試覆蓋：**
- ✅ 5 個新單元測試（邊界條件、窗口重疊、streak 方向轉換、零值、insufficient history）
- ✅ 34 個 test_processors.py 全部通過（無回歸）
- ✅ 特別驗證：5 天前的 this_week == 今天的 last_week（窗口重疊邏輯保證）

**commit：** `5d1206f`

**下一步：** Task 2-10 待接續（詳見 docs/superpowers/plans/2026-07-22-sector-overview-heatmap.md）

---

## 待辦（2026-07-08 記錄，換平台後接續）

三件事，優先順序由上到下：

1. **`index.html`（族群總覽頁）UI 重新設計**
   - 已用 ui-ux-pro-max skill 產出設計系統建議，做成 Artifact mockup 給 Cody 看過外觀，方向已
     初步認可（扁平排行清單取代卡片、兩層點擊、統一訊號 chip、色票沿用現有深色系，細節見本檔
     `## 2026-07-07` 那則entry）
   - 還沒實際動手改 `export/html_generator.py`
   - 技術路線：不用 React，直接改 HTML/CSS/JS 生成邏輯，維持純靜態站架構
   - **新增優化項（2026-07-08，Cody 看 `data/photo_for_test/族群.png` 反映）**：族群卡片上的
     `↑20`／`↑36` 排名跳動 badge（`html_generator.py::_signal_badges()`，`delta = yesterday_rank
     - today_rank` 的裸數字）**Cody 看不懂、覺得沒有用途**，redesign 時這個訊號要嘛拿掉、要嘛
     換一種更好懂的呈現方式（例如明確寫「昨日#21→今日#1」而不是單獨一個數字），不要延用現在
     這種容易被誤認成百分比的裸數字格式

2. **族群個股表格新增 5/7/10/14 天累積漲跌幅欄位**
   - Cody 要求，現況只有「週漲跌%」（複利最近5日）一個欄位
   - `processors/performance.py::calc_stock_sparklines()` 目前 `lookback=11`（只抓11個交易日），
     撐不到14天，需要擴大查詢範圍
   - **複利公式已驗證正確**（不是bug）：用 8261 富鼎手動重算週漲跌 +26.44%，跟真實
     `daily_prices.change_pct` 複利結果對上（該股當週有3天接近/觸及漲停）
   - 待決定：這4個新欄位是直接加進現有表格，還是跟第1項一起重新設計版面時做（傾向後者，
     避免先加欄位、redesign時又要整個重排）

3. **查明 institutional/margin 資料為何卡在 07-07、沒跟上 daily_prices 的 07-08**
   - 族群頁外資/投信/融資欄位這次全部顯示「─」，查 DB 發現 `daily_prices` 最新到 2026-07-08，
     但 `institutional`／`margin` 兩張表最新只到 2026-07-07
   - 已確認 2026-07-07 全市場 0 檔股票有 `daily_prices` 資料（非交易日），但 institutional/
     margin 卻標著這天的資料，這點本身也需要覆查（究竟是「機構資料本來就晚一天發布」的正常
     現象，還是抓取失敗遺留的舊資料）
   - **需要 Cody 提供**：跑 `python main.py` 當下的 log，看有沒有出現「TPEx 三大法人寫入失敗」
     之類的警告（`main.py` 對 TPEx 抓取失敗目前只 log warning、不會擋住其他流程，之前 session
     就報告過這個行為，這次疑似又踩到同一種情況）

---

## 目前狀態（2026-07-01 更新）

### ⚠️ DuckDB 資料有假資料，需先修復再跑回測

| 指標 | 數值 |
|------|------|
| daily_prices 總筆數 | 214,435 |
| 涵蓋股票數 | 1,037 |
| 最新資料日期 | 2026-06-30 |
| 有假資料的股票數 | **~450 支**（同 close+vol 出現 >30% 天數） |

**假資料特徵**：初始化時 placeholder 被複製到多個日期，導致同一股票同一 close+volume 重複數十～數百次。  
**例**：2327 國巨 close 範圍 134.5 ~ 1140.0（1140.0 是 placeholder，134.5 是分割後真實值）。

---

### 資料來源一覽

| 來源 | 指令 | 涵蓋 | 備註 |
|------|------|------|------|
| **TWSE STOCK_DAY_ALL** | `--backfill-twse N --workers W` | 上市（Phase 1） | 逐日批次，平行，~1分/日 |
| **TPEx OpenAPI** | `--backfill-twse N --workers W` | 上櫃（Phase 2） | 同指令，Phase 2 自動跑 |
| **TWSE 逐股月別** | `--backfill-twse N` | Phase 3 补漏 | STOCK_DAY_ALL 漏掉的上市股 |
| **Yahoo Finance** | `--backfill-yf N` | 上市+上櫃 | 無需 token，含 OHLCV，直接 upsert DuckDB |
| **FinMind** | `--backfill N` | 上市+上櫃 | 需 token，每日 600 次上限 |

> **Yahoo Finance SSL 問題**：公司/企業網路可能出現 `SSL certificate problem: unable to get local issuer certificate`。  
> 已在 `backfill_yfinance()` 內加 `ssl._create_unverified_context` + `urllib3.disable_warnings` 繞過。  
> 若仍失敗，改用 `--backfill-twse 18 --workers 3` + `--reimport`。

---

### Import / 資料庫 Pipeline

```
CSV 檔案 (data/daily_prices/*.csv)
    ↑ 由 --backfill-twse 或 --backfill-yf 寫入（overwrite=True）
    ↓
DuckDB (data/screener.db → daily_prices 表)
    由 import_csv_prices() 讀 CSV upsert
    由 reimport_db() 清空重建（自動過濾假資料）
```

**假資料／缺交易日修復流程**

方案 A（推薦，Yahoo Finance）：
```bash
python main.py --backfill-yf 20 --workers 3   # 約 7 分鐘（1036 支），跑完自動 reimport
```
- ⚠️ **月數要蓋住全部有效歷史**：會先刪光 `data/daily_prices/` 的**所有** CSV 再重抓指定月數，
  填太小＝舊歷史被刪又不重抓。有效歷史目前從 2025-01 起 → 填 20，之後隨時間往上加。
- ⚠️ **不用再下 `--reimport`**：`backfill_yf()` 跑完自己會呼叫 `reimport_db()`。
  （2026-08-28 前這裡寫的是分兩步 + 填 18，兩點都已過時。）

方案 B（TWSE+TPEx 批次）：
```bash
python main.py --fix-stale --workers 3   # 重抓 CSV + 清空重建 DuckDB，約 15 分鐘
```

---

### Pattern 偵測器現況（2026-06-30 commit 5000f24）

| 型態 | EV | 止損率 | 訊號數（18M 回測） |
|------|-----|--------|-----|
| 頭肩底（新增） | +11.92% | 20% | 574 |
| 60日突破 | +9.1% | 24% | 682 |
| 雙底 | +7.3% | 28% | 1,205 |
| VCP突破 | +6.8% | 31% | 387 |
| 三角突破（MA50 filter 新增） | +5.2% | 35% | 493 |
| **整體 EV** | **+8.07%** | — | — |

**主要改進（本 session）**：
- `detect_inverse_hs`：頭肩底新型態，RR 最高
- VCP stop：改用最後一個 trough close（不再固定 3%）→ 止損率 71% → 31%
- 三角突破：加 MA50 uptrend filter（收盤需 > MA50 × 0.98）
- `backtest_patterns_rr`：新增 `--start-date` 參數，可模擬指定日期後的 walk-forward

---

### 待辦清單

- [ ] **修假資料**（最優先）：跑 `--backfill-yf 18` + `--reimport`
- [ ] **重跑回測**（資料乾淨後）：`--backtest-patterns-rr 350` + `--start-date 2026-01-01`
- [ ] **確認 2327 國巨**：修後應出現底部整理突破型態
- [ ] 型態訊號 active list 重掃（舊假資料可能產生虛假訊號）

---

## 目前狀態（2026-06-30 更新）

### Pattern 偵測器鮮度修正 ✅（2026-06-30，commit fe26e9a）

**問題根源（hit_target on day 0 — 21/21 訊號立即達標）**：
- `detect_double_bottom/top/inverse_hs` 只檢查「今日 > 頸線」，未確認昨日仍在頸線下方
- 數週前突破的股票每日仍觸發偵測器，signal_date=今日，close 遠超 target → 瞬間 hit_target
- 範例：2415 頭肩底 anchor=25.78, target=27.48，但 close=37.50（已高出46%）

**修法（`screener/patterns.py`）**：
1. `detect_double_bottom`：加 `if close[-2] > neckline: continue`（昨日已過頸線則非首日突破）
2. `detect_double_top`：加 `if close[-2] < neckline: continue`
3. `detect_inverse_hs`：計算昨日頸線值 `neckline_yesterday = pk1 + slope*(seg_n-1-pk1_idx)`，昨日已過則跳過
4. `scan_and_track` `days_held`：改用 `np.busday_count`（交易日數）取代 `timedelta.days`（日曆天數）

**清理作業**：
- 刪除 DuckDB `pattern_signals` 中今日（2026-06-30）全部舊 stale signals（60筆：39 active + 21 hit_target）
- 刪除假週六 CSV：`2026-06-06.csv`（23筆）、`2026-06-13.csv`（1033筆）
- 同步刪除 DuckDB `daily_prices` 對應週六資料

**結果**：重掃後 29 個 active 訊號，無 hit_target on day 0；50/50 tests 通過

---

### 三角突破 / 雙底 嚴格化 ✅（2026-06-30）

**問題根源（8049 晶采誤報）**：
- 8049 今日跌 -0.9%，但壓力線外推剛好在收盤下方 → 觸發「三角突破」
- 量縮要求缺失：整理期量能應遞減，但無驗證
- `_TRI_VOL_CONFIRM = 1.3` 太低（1.4x 弱訊號全通過）
- 雙底：5% 反彈太小、無最小間距、無前置下跌趨勢要求、1.2x 量確認太弱

**修改（`screener/patterns.py`）**：

`detect_triangle_up()` 新增：
1. 突破日必須是上漲日：`today['close'] > df['close'].iloc[-2]`（核心 bugfix）
2. 整理期量縮：後10日均量 ≤ 前10日均量 × 1.1
3. `_TRI_VOL_CONFIRM`: 1.3 → 1.8

`detect_double_bottom()` 新增：
1. 兩低點最小間距 ≥ 8 根
2. 第一底前有下跌趨勢（前高 ≥ 第一底 × 1.10）
3. `_DBL_BOUNCE`: 5% → 8%
4. `_DBL_PRICE_DIFF`: 3% → 5%（稍放寬允許自然差距）
5. `_DBL_VOL_CONFIRM`: 1.2 → 1.5

全 22 tests 通過。

---

## 目前狀態（2026-06-29 更新）

### VCP 重寫：三波量縮突破 ✅（2026-06-29）

**問題根源（4503 金雨誤報）**：
- 舊版只看「15日平台振幅<10%+量縮+突破」，本質是「平台突破」，不是 VCP
- 4503 在下跌途中（40.15→36.75），15日偶然振幅4.5%、量縮6%、微突破 → 全過
- 完全不符合 Mark Minervini VCP 結構：三波幅度遞減回檔 + 前置上升趨勢

**新實作（`detect_vcp`，`screener/patterns.py`）**：
1. 在近 50 日視窗內找 peak→trough 波段（`_local_maxima` / `_local_minima`）
2. 每波回檔幅度 < 前一波 × 80%（三波約各半）
3. 每波均量收縮（後波 ≤ 前波 × 1.05）
4. **前置趨勢**：65日前收盤 < 第一個峰值 × 95%（確認是上漲後整理，非下跌途中）
5. 突破最後一波峰值 + 今日爆量 ≥ 整理均量 × 2.0

**測試**：22/22 通過，新增 `test_vcp_not_detected_downtrend` 和 `test_vcp_not_detected_pullback_not_contracting`

---

### 三角突破修復 ✅（2026-06-29）

**根本原因（雙重 bug）**：
1. `np.polyfit(all_20_bars)` 把整個 20 日 K 棒全迴歸，非峰值 bar 把壓力線往下拉 → 幾乎所有收盤都超過，從不觸發
2. TWSE 日 CSV 的 `high`/`low` 欄位全為 NaN → polyfit 直接得 nan

**修法**：
- 新增 `_pivot_trendline(arr, find_peaks, radius=2)` — 只找局部高/低點，連最後兩個 pivot 成線
- NaN fallback：`highs = np.where(np.isnan(highs_raw), close_arr, highs_raw)`
- 測試資料改為真實 zigzag（有局部峰/谷）

**結果**：2026-06-29 掃出 三角突破 12 支、三角跌破 8 支（之前 0）

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

## 2026-07-07 — 型態掃描邏輯驗證 + 三個小修復 + index.html 重新設計 mockup（待實作）

### 已完成
- 去重 `screener/patterns.py::_calc_streak()` / `processors/performance.py` nested closure `_streak()`
  → 新增 `streak_utils.py::calc_streak()` 共用函式
- `chips.html`／`patterns.html` 族群欄位文字顏色太暗 → `#475569`/`#64748b` 改成 `#94a3b8`
- `index.html` 族群層級外資/投信摘要單位標籤修正：`K` → `張`/`萬張`，跟 `chips.html::_fmt_net()` 一致
  （新增 `html_generator.py::_fmt_lots_text()` 共用 helper）
- 用真實歷史資料驗證型態掃描邏輯（`screener/patterns.py`）：2327 國巨、被動元件全族群 39 檔
  回放，確認邏輯有效——2026-04-13 單日 15 檔被動元件股同步突破雙底/頭肩底，`composite_score`
  普遍 87~96 分（滿分100），不是巧合雜訊，是真實產業循環轉折點

### 待辦：index.html（族群總覽頁）重新設計
- **現況問題**：三層點擊（主族群卡片 → 子族群 mini-card → 個股表格），排行榜跟獨立 Top10 區塊
  資訊重複，訊號呈現（排名變化/連漲連跌/量能異常）視覺形式分散不統一
- **設計方向**（已用 ui-ux-pro-max skill 產生設計系統建議，並做成 Artifact mockup 給 Cody 看過
  外觀，方向已初步認可，細節可能還會調整）：
  - 扁平化排行清單取代卡片格線；兩層點擊（點族群直接看個股，不用先點子族群）
  - 桌機：左側固定排行清單 + 右側明細面板（點擊更新，不跳頁不reflow）；手機：單欄 + inline 展開
  - 訊號統一收進每列左側色bar + 膠囊 chip（外資/投信連買連賣、排名跳動、量能異常）
  - 拿掉重複的獨立 Top10 區塊，排序方向切換（▲/▼）取代它
  - 數字改用等寬字體 + tabular-nums 對齊；中文明確加 PingFang TC/微軟正黑體字體堆疊
  - 配色**沿用**現有深色系（`#0b0f18` 背景等），不引入新顏色，維持三頁（index/chips/patterns）
    視覺一致
  - 技術路線：**不用 React**，直接改寫 `export/html_generator.py` 的 HTML/CSS/JS 生成邏輯，
    維持純靜態站架構（先前 2026-07-02 曾規劃 React+Vite 版本，後來 revert、移到
    `react-frontend-redesign` 分支未繼續——這次是全新方向，不接續那份舊規劃）
- **下一步**：Cody 確認 mockup 細節後，實際改寫 `export/html_generator.py`（範圍較大，建議先
  `superpowers:brainstorming` 或直接列 TDD 任務拆解，不要一次全部重寫）

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

---

## 2026-09-01：MOPS 官方基本面歷史 Phase 2A＋2B

- 使用者核准 IFRS 2013 Q1 起、append-only 版本、EPS 不相減、先季報後月營收的方案。
- 新增 `python main.py --backfill-fundamentals 2013`，從 MOPS 官方整批下載頁探索實際存在的
  `tifrs-YYYYQn.zip`，依序回填，不自行拼出未公布季度。
- 原始 ZIP 以 SHA-256 版本化保存於 gitignored `data/fundamentals/xbrl/`；同 URL 內容改變時保留舊版。
- 新增 XML／Inline XBRL parser，保存 QName、context、unit、decimals、dimensions、raw value；
  支援 ZIP 內最多兩層巢狀 ZIP，且不 extract 到磁碟。
- 新增 `xbrl_archives`、`xbrl_filings`、`xbrl_archive_entries`、`xbrl_facts`、
  `xbrl_canonical_facts` 與 `xbrl_current_facts`。
- canonical 指標包含常用損益、資產負債、基本／稀釋 EPS 與三大現金流；未知 QName 仍保存 raw。
- `financial_fact_growth` 修正季末邊界（6/30 的前季是 3/31），現金流可算單季與累計 YoY；
  基本／稀釋 EPS 只算官方累計同期 YoY。新增 `financial_ratios` 毛利率／營益率／淨利率 view。
- MOPS 批次 ZIP 未提供可確認的官方申報時序，`reported_at` 保持 NULL，禁止把抓取時間冒充申報日；
  目前有效值可查，但尚不可宣稱 point-in-time 無前視偏誤回測。
- Phase 2B 使用 MOPS 官方 `nas/t21/sii|otc` Big5 11 欄整批頁回填上市／上櫃月營收；
  保存 `monthly_revenue_pages`／`monthly_revenue_versions`，排除合計列，頁面標題或表頭不符即失敗。
- 月營收回填終點由各市場官方最新 OpenAPI 決定；同一指令依序完成季報與月營收，不混用 parser。
- 依 Developer 規則未跑 pytest、初始化 DuckDB 或真實 MOPS 下載；8 個 Python 檔 AST 與
  102 個常數 DuckDB SQL statements 靜態解析通過，待 Debugger 實測。

### 2026-09-01 真實 2013 Q1 parser 修正

- Cody 首次執行回填時，4712 同時出現 IASB 損益表與 `tifrs/scf` 現金流調節項的
  `ProfitLossBeforeTax`，local name mapping 將兩者都誤認為 `pretax_income` 而中止。
- 修正 canonical ranking：`sci`／`sfp`／`scf`／`sce` namespace 只能進對應報表；
  `notes` 附註 namespace 僅保留 raw facts，不直接投影主表。
- 第二個真實衝突 2882 的 IASB `RetainedEarnings` 與附註同名 concept 也由同一規則正確區分。
- 新增兩個 namespace regression cases；沒有跑 pytest，但已直接執行兩個最小案例並通過。
- 使用已下載的官方 `tifrs-2013Q1.zip` 完整重播 parser，整包成功，臨時診斷 harness 已刪除。

### 2026-09-01 真實 2014 Q1 inconsistent duplicate 修正

- 2013 Q1～Q4 已成功提交；2014 Q1 的 3356 在同一 QName、`AsOf20140331` context、TWD unit、
  `decimals=-3` 下，同時申報現金及約當現金 `1,064,951,000` 與 `0`，官方 instance 本身不一致。
- 無可驗證依據選其中一值：兩筆繼續 append-only 保存於 raw facts，該公司的
  `cash_and_equivalents` canonical 投影略過並 warning；其他 metric 與整季不再被單欄位阻斷。
- 新增 inconsistent duplicate regression case；最小案例由原本 raise 轉為保留 2 筆 raw、
  不產生該 canonical metric。
- 完整重播 cached `tifrs-2014Q1.zip` 成功：1,569 filings、1,781,144 raw facts、44,105 canonical facts。
- 回填新增斷點續跑：`xbrl_archives` 已提交季度預設跳過，rollback 的失敗季度仍會重試；
  本機查詢確認 2013 Q1～Q4 都會跳過。歷史更正版稽核可明確指定 `refresh_existing=True`。
- `xbrl_current_facts` 改以季度最新完整 archive 為版本邊界；新版若略過衝突 metric，會同步移除
  舊 `mops_xbrl` projection，不會悄悄沿用舊 archive 的值。
- 修正上述 view 的 DuckDB binder regression：`filing` 與 `xbrl_archive_entries` 都有
  `archive_sha256`，不可再用歧義的 `JOIN ... USING (archive_sha256)`；改為明確以
  `latest_archive.archive_sha256 = entry.archive_sha256` 連接。聚焦 regression 與記憶體
  `init_db()` 均通過。
- 2020 Q3 真實回填暴露 MOPS 大型 ZIP 偶發短傳：HTTP 200、ZIP MIME 且內容以 `PK` 開頭，
  但官方回應沒有 `Content-Length`／Range 支援，只有 central-directory 驗證能發現不完整。
- `download_archive()` 新增下載後 ZIP 驗證重試：5／20／60 秒退避（共 4 次），重試時禁用快取、
  關閉舊連線並要求 identity encoding；warning 顯示實收 bytes、Content-Type／Length，壞內容永不進 cache。
- 新增第一次截斷、第二次正常的聚焦 regression，確認第二次成功且重試 header 正確。
- 以修正後路徑直接下載官方 2020 Q3 到記憶體並完成 ZIP/CRC 驗證，成功取得 80,635,246 bytes；
  未寫入 DB 或 cache，確認官方檔本身並非永久損壞。

---

## 2026-09-01：Index 桌面工作區精簡規格

- 需求來源：Cody 與 Codex 的 grilling 設計訪談。
- 新增 spec：`docs/superpowers/specs/2026-09-01-index-desktop-workspace-simplification-design.md`。
- 本次只整理規格，尚未依最終 spec 實作；`export/index_generator.py` 已存在訪談前的 WIP 版面修改，正式實作時需依新 spec 重新對照，不能把 WIP 視為已完成。
- Index 主流程確定為：精簡 Header、目前市場、完整寬度巨量換手、族群 Top 10、三組研究摘要、原地展開全部族群、右側個股詳情抽屜。
- 首頁移除轉折點、悄悄佈局、重複量能排行與長篇方法說明，但底層資料保留。
- 盤中每 15 分鐘更新；14:00 產生正式快照並保留 60 個交易日。更新失敗保留最後成功資料並顯示 stale 狀態。
- Oliver Kell 型態階段與自選股工作區拆成後續獨立 spec；等待使用者提供講義後再討論型態定義。
- 驗證：本次為文件工作，已檢查既有首頁 spec、`export/index_generator.py` 主要入口與目前 worktree 狀態；未執行 pytest。

---

## 2026-09-01：Index 桌面工作區精簡實作

- 使用者以「繼續」核准 `docs/superpowers/specs/2026-09-01-index-desktop-workspace-simplification-design.md` 進入實作。
- 預計修改：`export/index_generator.py`、`tests/test_index_generator.py`，以及 `main.py` 的盤中／收盤模式透傳；不手動修改產生檔 `docs/index.html`。
- 先移除訪談前 WIP 的 280px sticky 左欄，依 spec 改為市場現況 → 完整寬度巨量換手 → Top 10 → 三組研究摘要。
- 主要風險：既有測試仍鎖定舊版 secondary-row 與 inline detail panel；JavaScript 的 XSS escaping、deep link、鍵盤操作及完整個股欄位不可退化。
- `docs/CONTEXT.md` 新增即時異動、研究分類、巨量換手、盤中資料／收盤快照的正式詞義；保留同檔既有基本面未提交內容。
- 驗證遵循 repo Developer 規則：本 session 不執行 pytest 或真實資料流程；完成後做 AST／靜態檢查並交由 Debugger 驗證。
- 已完成互斥 `build_research_buckets()`：值得研究最多 10、先觀察／避開各最多 5；短線強但週度退燒保留「週度仍退燒」衝突標記，巨量換手不參與分類。
- 首頁已改為市場現況 → 完整寬度巨量換手 → 族群 Top 10 → 今日研究順序；移除 WIP sticky 左欄、常駐五級圖例、轉折點、排名進出榜與重複 recap。
- 卡片收合態只保留族群、排名／變化、今日漲跌、動能與增溫／退燒；完整週期、量能、法人、排名歷史與個股欄位移入右側 drawer。
- 新增 Top 10／全部、研究分類、族群名稱、四種排序與進階條件；狀態使用 `tw-sector-index-view-v1` 寫入 localStorage，排行與三組摘要共用條件。
- drawer 支援卡片／摘要／搜尋／`#meta=` 共用入口、Esc、關閉按鈕、focus restoration；窄螢幕退回 100vw。
- `main.py` 只在原 index generator 呼叫點增加 `data_mode`，盤中顯示「盤中資料，尚未收盤確認」與「疑似巨量換手」，收盤顯示「收盤快照」。未碰同檔既有基本面 WIP。
- UI Pro Max 檢查採用：5×2 desktop grid、漸進式進階篩選、可見 focus、44px 近似操作高度、reduced-motion 與 1180／820／520 responsive；配色與字體依 spec 沿用既有系統。
- 靜態驗證：`compile()` 通過 `export/index_generator.py`、`tests/test_index_generator.py`、`main.py`；`git diff --check` 無 whitespace error。
- 未在 Developer session 執行 pytest、真實 `main.py` 或重產 `docs/index.html`；已寫入 `debug-tasks.md` 交由 Debugger 用可寫 basetemp 與瀏覽器驗證。
- 尚未實作排程層的 60 交易日快照保存／更新失敗時重寫 stale banner；本輪 generator 已預留 `update_error` 顯示能力，排程生命週期依 plan 拆開處理。

## 2026-09-04：Oliver Kell 個人自選股 MVP

- 依 `docs/superpowers/specs/2026-09-04-personal-watchlist-design.md` 實作個人自選股：scanner 只提供候選，使用者從首頁手動加入，資料以 `tw-sector-watchlist-v1` 存在瀏覽器 localStorage。
- 新增 `export/watchlist_generator.py` 與 `docs/watchlist.html` 產出流程；保留未知／暫無行情的自選股，顯示最新價格、漲跌、5/7/10/14 日報酬、法人淨買賣與 Oliver 欄位預留狀態。
- `export/index_generator.py` 加入「＋自選／★ 已在自選」按鈕；`main.py::_push_html()` 納入 `docs/watchlist.html`。
- 新增自選股 generator 測試，並更新 index generator 契約測試確認按鈕、localStorage key 與導覽連結存在。
- 驗證：`pytest -q tests/test_index_generator.py tests/test_watchlist_generator.py --basetemp .pytest-basetemp-watchlist`，104 passed；`py_compile` 與 `git diff --check` 通過。
- 尚未以真實資料重產 `docs/*.html`，也尚未實作 Oliver 的實際週線 Market Structure／日線 Price Cycle 判斷；本輪只建立可承接這些判斷的 watchlist 介面。
## 2026-09-01 Index 第二輪視覺與個股 K 線調整（開工）

- 需求來源：Cody 檢視 `python main.py` 產生並發布的新版 Index 後提出五項修正。
- 開發依據：`docs/superpowers/specs/2026-09-01-index-desktop-workspace-simplification-design.md`。
- 已確認範圍：
  1. 右側族群抽屜加寬至 `min(1180px, 80vw)`；個股文字改用無襯線，數字保留等寬。
  2. Top 10 卡片改用固定漲跌幅區間的紅／綠強度色階，不用當日相對最大值放大。
  3. 四個主頁導覽統一字型與元件規格，只以 active 狀態區分頁面。
  4. 巨量換手移到首頁內容最下方。
  5. 個股詳情使用 TradingView Lightweight Charts 繪製本地 OHLC 日 K＋成交量，lazy create／close cleanup，保留 attribution；MA 與 Oliver Kell 標記留待後續規格。
- 初步風險：Lightweight Charts 是外部前端依賴，必須鎖版本並提供載入失敗 fallback；`docs/*.html` 是 generated artifact，不直接修改；工作區另有 fundamental-data WIP，這次不碰。
- 驗證限制：依 `CLAUDE.md` Developer 不執行 pytest、`main.py` 或真實資料流程；完成後只做 compile／diff 靜態檢查並交給 Debugger。

### 實作完成

- `heat_bg()` 改採 18／30／46／62% 固定強度，移除 Top 10 對當日最大漲跌幅的相對縮放。
- `calc_stock_sparklines()` 新增 `iso_dates`，既有短日期、OHLC、成交量與 11 日視窗不變。
- 族群 drawer 改為 `min(1180px, 80vw)`，股票名稱與標題改 sans；個股 modal 擴至 920px。
- Index、chips、patterns、momentum 四個 generator 的主導覽改成一致的 sans pill 元件。
- 巨量換手移至研究分類之後，成為 Index 主內容最後一區。
- 移除個股 modal 舊手刻 SVG candlestick，改為 lazy-load `lightweight-charts@5.2.0`，
  以本地 `iso_dates`／OHLC／volume 建立 CandlestickSeries＋HistogramSeries；包含 loading、error、
  attribution、ResizeObserver 與 close cleanup。
- 測試契約已更新固定色階、ISO 日期、資訊順序、drawer 尺寸、CDN 鎖版、量價 series 與清理生命週期。
- 靜態驗證通過：以暫存 pycache 執行 7 個異動 Python 檔 `py_compile`，`git diff --check` 無錯誤。
- 依 repo 規則未跑 pytest、`main.py`、真實資料或重產／發布 `docs/*.html`；Debugger 清單已追加至 `debug-tasks.md`。
