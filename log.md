# 開發日誌

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

**假資料修復流程（二選一）**

方案 A（推薦，Yahoo Finance）：
```bash
python main.py --backfill-yf 18      # 直接抓乾淨資料 upsert DuckDB，約 15 分鐘
python main.py --reimport             # 清空重建（清除殘留假資料）
```

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
