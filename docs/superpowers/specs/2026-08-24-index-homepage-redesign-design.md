# 首頁（index.html）版面／視覺重設 設計 (2026-08-24)

## 背景與問題

`docs/index.html` 由 `export/index_generator.py` 產生，2026-07-22 上線熱區格改版（41 族群 tile）。
Cody 這次反饋現況有幾個具體問題（brainstorming 逐項挖出根因）：

1. **順序跟優先序不符**：現況 HTML 由上到下是「異動族群 → 族群排行(熱區格) → 族群近況」。但
   Cody 打開首頁最想先看到的是「熱區格全局速覽」，不是異動族群卡片——熱區格才是主角，卻被排到
   第二順位。
2. **異動族群「沒有重點」**：`find_anomaly_cards()`（`export/index_generator.py:191`）完全沒有
   排序，卡片依 dict 插入順序輸出，不是依嚴重程度。好幾張卡並排時，看不出該先看哪張。
3. **個股明細面板打斷版面**：`selectGroup()`（`export/index_generator.py:1624`）把面板插進
   `tile.offsetTop` 所在列的最後一個 tile 後面，等於插入熱區格網格中間，打斷 41 格的排列；
   面板裡的 11 欄個股表格（股票/收盤/漲跌%/量比/融資佔比/融資維持率(估)/融券餘額佔比/
   融券維持率(估)/5-7-10-14日）又寬，擠在原本的格子縫裡更亂。
4. **面板內三區垂直堆疊太高**：走勢 sparkline → 籌碼摘要一行 → 歷史進榜週紀錄，三段垂直堆疊，
   面板整體偏高。
5. **有些已經算好的資料沒有顯示**：自營商（`dealer_net`，`screener/database.py:52` 早就抓了）
   沒進籌碼摘要；`weekly_returns`（`processors/performance.py:1055`，8/3 剛加）沒有進歷史週格；
   大戶持股佔比／週變化（`shareholder` 表，跟 chips.html 同一份資料）沒有進個股表格；外資／投信
   目前只有「今日」單日數字，沒有「本週累計」。

配色/字型（深色底+金色 accent+紅漲綠跌+ sans/serif/mono 三套字型分工）本身已經是刻意設計過的
系統，不是隨便套的樣板色，這次視覺調整**不換色票字型**，只加強關鍵層級的視覺深度。

## 目標

1. 版面重排：熱區格滿版置頂當主角，下方雙欄放次要資訊。
2. 異動族群加排序（爆量暴衝優先，同類再比幅度）。
3. 視覺深色進化版：延續現有配色/字型，關鍵層級（超強 tier、警示狀態）加玻璃質感+微光暈做出
   深度層次。
4. 個股明細面板改錨定在熱區格區塊「下方」，不再插進 tile 網格中間。
5. 面板內走勢／籌碼動向／歷史進榜三區從垂直堆疊改成並排三欄。
6. 補齊已經算好、但目前沒接進面板的資訊：自營商、週報酬%、大戶佔比＋週變化、本週累計買賣超。

## 非目標 (YAGNI)

- **不調整異動族群門檻**（`vol_ratio>=1.5` / 排名跳動`>=10` / `streak>=5`）。門檻緊化需要
  回測數據支持，跟這次的版面/視覺重設是不同性質的工作。列為**獨立後續任務**，需搭配
  `docs/superpowers/specs/2026-07-14-backtest-framework-design.md` 的回測框架，不在本次範圍。
- **不改個股明細表格既有的排序/收合互動**（`sortStockList()`）。
- **不換配色系統或字型系統本身**（CSS 變數不動），只加玻璃/光暈視覺層。
- **不做「回到熱區格頂部」按鈕**：面板搬到熱區格下方後頁面變長，先不加輔助導覽，之後真的有感
  再補。
- **不重新設計手機版每個細節**：沿用現行 responsive 慣例——並排欄在窄螢幕下改回垂直堆疊。

## 架構

### ① 版面結構重排（`export/index_generator.py::generate()`）

現況輸出順序：異動族群 → 族群排行(熱區格) → 族群近況。

改為：

```
族群排行（熱區格，滿版，主角）
  └─ 個股明細面板（若有 active 族群，錨定在熱區格區塊結束後——見④）
二欄：異動族群（左，已排序） | 族群近況＋轉折點（右，合併一欄）
```

「族群近況」與「轉折點列表」目前是 `_sector_recap_html()` 底下兩個獨立子區塊，這次只調整
外層容器變成右欄（灰底卡片），兩個子區塊內部渲染邏輯不動，堆在同一欄裡。

### ② 異動族群排序（`find_anomaly_cards()`，`export/index_generator.py:191`）

目前 `results.append(...)` 直接依 `pct_map` 的 dict 插入順序輸出。改為在 `return results` 前
新增排序：

```python
results.sort(key=lambda r: (r["kind"] != "burst", -abs(r["pct"])))
```

- `kind != "burst"` 讓 `burst` 排在 `trend` 前面（`False < True`）。
- 同 kind 內用 `abs(pct)` 降冪（幅度大的優先）——用 `pct` 而非 `vol_ratio`/`accel`，因為 `pct`
  是卡片上本來就顯示給人看的主要數字，排序依據跟畫面上看到的一致，使用者比較看得懂「為什麼
  這張排前面」。
- 卡片視覺大小不變（Cody 確認不用特別放大第1名），只調整 DOM 輸出順序。

### ③ 視覺：深色進化版

CSS 變數（`--bg`/`--panel`/`--accent`/`--tier-*` 等，`docs/index.html:8-22`）完全不動。新增：

- **超強 tier 的熱區格 tile**：加淡金漸層背景＋外光暈。作為起點（brainstorming 階段已用真實
  色票 mock 過，implementer 可微調到位）：
  ```css
  .heat-tile.tier-super{
    background:linear-gradient(160deg, rgba(240,187,85,.14), rgba(240,187,85,.04));
    border-color:rgba(240,187,85,.5);
    box-shadow:0 0 22px rgba(240,187,85,.18), var(--shadow-2);
  }
  ```
- **警示狀態**（融資維持率(估)／融券維持率(估) < 130% 的儲存格）：比照上面的玻璃感做法，用
  `--tier-superweak`/`--accent` 對應色的低透明度背景+邊框強調，不新增色票。
- **個股明細面板**：邊框用 `--accent`、`box-shadow:var(--shadow-2)`，讓面板在頁面上有明確的
  「浮起」層次感（呼應熱區格主角的視覺語言）。
- **雙主題相容**：`docs/index.html` 有 `:root[data-theme="light"]` 淺色主題（`--accent` 在深色
  是 `#F0BB55`、淺色是 `#93701E`，色相不同）。上面的 `rgba(240,187,85,...)` 是深色主題專用寫死值，
  **不能直接沿用到淺色主題**——玻璃/光暈效果要嘛改用 `color-mix(in srgb, var(--accent) 14%, transparent)`
  這類跟著 `--accent` 走的寫法，要嘛在 `:root[data-theme="light"]` 區塊另外訂一組淺色對應值。
  implementer 動手前先確認兩個主題切換後視覺都合理，不能只做深色。

### ④ 個股明細面板重新定位（`selectGroup()`，`export/index_generator.py:1624`）

現況：`const rowTiles = tiles.filter(t => t.offsetTop === rowTop); lastInRow.insertAdjacentElement('afterend', panel)`
——插在被點 tile 所在列的最後一格後面。

改為：插入整個 `#heatgrid` 容器之後（`heatgrid.insertAdjacentElement('afterend', panel)`），
不論點的是第幾列。`.heat-tile.active` 亮框標示邏輯不變（開頭的 `alreadyOpen`/toggle 判斷、
`tile.classList.add('active')` 都保留），只改面板的插入錨點，不影響既有 XSS 防護
（`escHtml()`/`_esc()` 雙層跳脫）與收合行為。

### ⑤ 面板內部三欄並排

`buildSparkline()` / `buildChipsSummary()` / `buildHistoryRecord()` 三個函式回傳的 HTML 片段
不變，只改外層容器：

```html
<div class="detail-three-col">
  <div class="tc-box">${{metaSpark}}</div>
  <div class="tc-box">${{chipsSum}}</div>
  <div class="tc-box">${{historyRecord}}</div>
</div>
```

```css
.detail-three-col{display:grid;grid-template-columns:1fr 1fr 1.3fr;gap:12px}
@media (max-width:768px){.detail-three-col{grid-template-columns:1fr}}
```

歷史進榜的權重多給一點（`1.3fr`）因為週格子是橫向 5 格，需要比另外兩欄多一點寬度才不會擠。

### ⑥ 補齊已算好但未顯示的資訊

**a. 自營商（`dealer_net`）**

- `calc_meta_chips_signals()`（`processors/performance.py:618`）目前 SQL 只 SELECT
  `foreign_net, trust_net`（`:646`），沒有 `dealer_net`——即使
  `screener/database.py::get_chips_today()` 早就抓了。加 `dealer_net` 到 SELECT，比照
  `foreign_pivot`/`trust_pivot` 的模式建 `dealer_pivot`，算出 `dealer_net_today` 放進
  `signals[meta_name]`。
- `card_meta`（`export/index_generator.py:1206`）加 `"dealer_net_today": chips.get("dealer_net_today", 0)`。
- `buildChipsSummary()`（JS，`:1387`）比照現有外資/投信 row 的寫法加一行「自營商」。

**b. 週報酬%（`weekly_returns`）**

- `calc_meta_rank_history()` 已回傳 `weekly_returns`（跟 `weekly_ranks` 平行對齊，
  `processors/performance.py:1162`），只是沒被放進 `card_meta`。
- `card_meta` 加 `"weekly_returns": rank_row.get("weekly_returns", [])`。
- `buildHistoryRecord()`（JS，`:1429`）的 `weekCells` 渲染，每格多加一行小字 pct
  （沿用 mock 的紅漲綠跌配色）。

**c. 大戶佔比＋週變化**

- `build_stock_detail_data()`（`export/index_generator.py:527`）目前只用 `total_shares_df`
  算融資/融券佔比的分母，沒有帶入 `shareholder` 表本身的 `lv12_15_pct`/`week_chg`。
- 新增參數 `shareholder_df`（比照 `screener/database.py::get_shareholder_top()` 的資料源，
  同一張表、同一套離群值防護 `_MAX_VALID_HOLDER_PCT`），對每支股票補
  `"holder_pct": ...`、`"holder_week_chg": ...`（無資料時 `None`，前端顯示「—」，不補假資料）。
- 個股明細表格（`export/index_generator.py:1677` 起的 `<thead>`）新增兩欄「大戶佔比」「大戶
  週變化」，插在「量比」跟「融資佔比」之間（11→13欄），`sortStockList()` 的排序 key 集合
  同步加 `holder`/`holderchg`。

**d. 本週累計買賣超**

- 現況 `foreign_net_today`/`trust_net_today` 只是當天單日數字。`calc_meta_chips_signals()`
  已經有 `foreign_pivot`/`trust_pivot`（`:673-680`，`all_dates` 是近 `lookback=10` 天的每日
  pivot），可以直接在同一支函式內加總最近 5 個交易日（口徑對齊現有「近5日」滾動視窗，
  不是自然日曆週）：
  ```python
  last5 = all_dates[-5:]
  foreign_net_week = int(f_row[last5].sum())
  trust_net_week = int(t_row[last5].sum())
  ```
- `card_meta` 加 `foreign_net_week`/`trust_net_week`，`buildChipsSummary()` 底部加一行
  「本週累計 外資 xxx・投信 xxx」（比照 mock 樣式，跟今日數字用分隔線隔開）。

## 資料來源相關（CLAUDE.md 要求）

- ①③④⑤純屬前端版面/CSS/JS 調整，不碰任何抓取/資料來源。
- ⑥的四項新資訊全部沿用**現有**每日流程資料表（`institutional`/`margin`/`shareholder`，皆為
  TWSE/TPEx 官方來源，經 `main.py` 每日更新），不新增爬蟲、不涉歷史回補。
- ⑥c 的大戶佔比資料源（`shareholder` 表）跟 `chips.html` 的 `get_shareholder_top()` 同一張表、
  同一套離群值防護，口徑一致，不會有兩邊數字對不上的問題。
- ⑥d 沿用 `calc_meta_chips_signals()` 既有的「per-stock/per-meta fallback」精神：某天某交易所
  資料缺，反映在該週加總數字裡（比現況「今日」數字更平滑），不特別另外標記。

## 測試策略

- `find_anomaly_cards()`：新增測試涵蓋「burst 排在 trend 前面」「同 kind 內依 abs(pct) 降冪」，
  沿用既有 fixture 風格。
- `calc_meta_chips_signals()`：新增測試涵蓋 `dealer_net_today`／`foreign_net_week`／
  `trust_net_week` 計算正確性（5個交易日加總）、資料不足 5 天時的行為（有多少天就加多少天，
  不強制補齊，比照 `get_shareholder_trend()` 的既有慣例）。
- `build_stock_detail_data()`：新增測試涵蓋 `holder_pct`/`holder_week_chg` 有資料/無資料兩種
  情境、離群值防護正確排除。
- `selectGroup()`／面板三欄排版：既有 JS 邏輯無 pytest 覆蓋（inline script），沿用現行「無法
  自動化測試 JS」限制，標記待瀏覽器驗證——**這次要一併補測 2026-07-23 遺留的鍵盤操作
  （Tab focus + Enter/Space 展開）與手機版 responsive 驗證**（同一頁面，同一次瀏覽器驗證做完，
  不是新增的欠款）。
- 全套件 `pytest` 需維持現有 pass 數（400+ 已知基準），不能讓既有測試變紅。

## 分工

- **開發者（我）**：全部程式改動——⑥的計算/接線（`processors/performance.py`、
  `export/index_generator.py`）、①②④⑤前端結構、③CSS。
- **Debugger**：驗證邏輯正確、上市/上櫃資料來源沒混用、瀏覽器驗證鍵盤操作＋手機版（含
  2026-07-23 未完成項）＋這次新增的排版與資訊。

## 風險與注意

- 個股明細面板搬到熱區格外面後，頁面整體變長，展開時需要捲動一段——不加輔助導覽（YAGNI，
  見上）。
- ⑥d 週累計籌碼若某天資料缺（如 TWSE/TPEx 其中一邊未發布），沿用現有 per-stock fallback
  精神：缺資料反映在加總結果、不當作 0 處理。
- 異動族群門檻（`vol_ratio>=1.5`/排名跳動`>=10`/`streak>=5`）刻意不動，維持「經驗法則待回測」
  現狀；門檻緊化是獨立後續任務，見「非目標」。
- 個股明細表格從 11 欄變 13 欄，橫向捲動幅度略增，沿用既有「第一欄 sticky」設計即可，不另外
  處理（現況已有 `overflow-wrap` 容器）。
