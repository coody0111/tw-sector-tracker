# 族群總覽頁（index.html）重新設計 — 熱區格＋族群近況＋個股點開版

**日期**：2026-07-15（2026-07-15 更新：個股清單展開方式定案 v18）
**狀態**：設計方向已定案（頁面結構 v16、個股清單展開方式 v18），尚未寫入 `export/html_generator.py`
**取代**：`2026-07-02-index-frontend-redesign-design.md`（見下方「跟舊 spec 的關係」）
**設計沿革**：`docs/superpowers/mockups/README.md` 第 7-18 版，最終參考檔
`docs/superpowers/mockups/2026-07-15-index-v18-inline-expand.html`（個股清單展開邏輯以此為準，
其餘頁面結構跟 v16 相同；v17 是比較過但未採用的備選方案，保留當紀錄）

## 跟舊 spec 的關係

`2026-07-02-index-frontend-redesign-design.md` 定的方向（React + Vite、編輯風格清單、
`data.json` + `npm run build`）**沒有被採用**。從 v6（米色 ledger 版）到 v16 的 9 輪 mockup
迭代中，實際收斂到的方向完全不同：

| 項目 | 舊 spec（07-02） | 這份 spec（07-15，實際方向） |
|---|---|---|
| 技術路線 | React + Vite，`data.json` + build 產物 | **維持純靜態站**，`export/html_generator.py` 直接產生完整 HTML（不用 React） |
| 排版邏輯 | 財經媒體式排行榜清單（單欄，拿掉卡片感） | **熱區格（heatmap grid）**——用底色深淺編碼漲跌幅，比清單更快掃描 41 個族群全貌 |
| 個股明細 | 桌機側欄／手機 inline 展開，兩層點擊 | 點熱區格卡片，在**熱區格下方展開 detail-panel**（單一版面邏輯，不分桌機/手機兩套） |
| 視覺風格 | 「不是這次重點，維持現有深色主題」 | **是這次的核心工作之一**——深藍底＋銅金 accent，紅綠飽和度、族群底色分級都是刻意設計 |

舊 spec 保留在 repo 當歷史紀錄，但**不要照它實作**。之後若要重啟 React 路線，需要重新開一份 spec
明確蓋過這份。

## 背景與目標

`docs/index.html`（現行 production 版）是卡片式版面，排名/訊號類資訊分散、Top10 跟主列表重複，
族群卡片點開才看得到子族群→個股，三層點擊。這次重做目標：

1. 把 41 個族群的今日漲跌一次呈現（熱區格），不用清單式一列列掃
2. 動能狀態不是只看「今天漲跌」，要能回答「這個族群還在噴，還是已經在弱掉」
3. 三種時間尺度的訊號分開陳列，不要互相污染：
   - **今日**（單日漲跌、家數）
   - **瞬間訊號**（今天 vs 昨天：爆量、排名跳動）→ 異動族群區塊
   - **週度趨勢**（這週 vs 上週：加速度、等級翻轉）→ 族群近況區塊
4. 點開族群要能看到成分股清單，不用先點子族群才看得到股票

## 技術路線

- **不用 React**。維持純靜態站：`main.py` 算好資料 → `export/html_generator.py` 直接產生完整
  `docs/index.html`（HTML/CSS/JS 內嵌，沿用現行架構）
- 沒有後端 API、沒有 `data.json` 中介層，跟現行 GitHub Pages 部署方式完全相容，不需要新增 CI/CD
- CSS custom properties 做主題 token（見下方「視覺設計」），JS 在 build 時把真實資料序列化成
  類似 mockup 裡 `GROUPS`/`STOCKS` 的陣列常數，直接內嵌進 HTML（不是 runtime fetch）

## 頁面結構（由上到下）

### 1. Topbar

族群總覽標題、更新時間戳、亮/暗主題切換按鈕。沿用現行邏輯。

### 2. ⚡ 異動族群（頁面最上方，橫向捲動快報）

**時間尺度：今天 vs 昨天，單日事件。**

顯示 5 張範例卡（實作時應改成「符合條件的族群」動態產生，不是固定 5 張），兩種訊號類型：

- **爆量暴衝**（`.anomaly-card.burst`）：今日量能 ≥ 門檻（mockup 用 1.5x，沿用
  `docs/superpowers/mockups/README.md` 已記錄的「經驗法則，沒有文獻依據，Cody 確認先這樣用」）
  於 5 日均量，且今日排名比昨日大幅跳動
- **連續噴出**（`.anomaly-card.trend`）：上週→本週加速度（pt）達到門檻

點卡片會觸發跟熱區格一樣的 `selectGroup()`，展開個股清單（見下方「點開個股清單」）。

**跟族群近況的差異（頁面上要明講，避免使用者以為是重複資訊）**：異動族群是「現在正在發生」的
單日事件；族群近況是「這週 vs 上週」的持續趨勢。mockup 用 `.role-note` 提示框在族群近況區塊
開頭說明這個差異。

### 3. 族群排行（熱區格主體）

**時間尺度：今日。**

`.heatgrid`：`grid-template-columns:repeat(auto-fill,minmax(224px,1fr))`，41 個族群卡片。

每張卡（`.heat-tile`）由上到下：

1. **排名 + 族群名 + 今日漲跌%**（`.ht-top`）——族群名用 `text-overflow:ellipsis` + `title`
   屬性防止長名稱截斷後看不到全名
2. **動能狀態標籤 + 溫度變化**（`.ht-status-row`）：
   - **動能狀態五級**（超強/強/整理/弱/超弱）：規則見下方「動能狀態分類邏輯」
   - **溫度變化**（🔥增溫／❄️退燒）：`accel = 本週pt - 上週pt`，`|accel| >= 5pt` 才顯示徽章，
     3~5pt 之間算溫和變化不特別標（門檻是草案，未回測，見「已知限制」）
   - ⚠️ **溫度變化跟今日漲跌是刻意分開的視覺語言**（橙/藍 vs 紅/綠），因為這兩件事本來就不同：
     一個族群今天可能還是紅的，但已經在退燒
3. **連漲/連跌天數 + 上漲/下跌家數**（`.ht-streak`）：天數照漲跌色系上色（不用死板灰字）
4. **法人連買 / 量能異常 badge**（`.ht-badges`，有才顯示）：外資連買 ≥2 日、投信連買 ≥2 日、
   量比 ≥1.5x
5. **上週→本週原始數字**（`.ht-week`，輔助佐證，降到最下面）

卡片底色（`heatBg()`）用 `color-mix()` 依今日漲跌幅絕對值算飽和度（0.16~0.66），紅漲綠跌；
卡片頂部 3px 邊框顏色（`border-top-color`）用動能狀態五級的顏色，形成「底色=今日方向，頂色=
本週動能」的雙重編碼。

點卡片展開個股清單（見下方）。

### 4. 族群近況（族群排行下方，獨立區塊）

**時間尺度：這週 vs 上週，持續性趨勢。**

三塊組成：

- **①升溫/退燒雙欄排行**：按 `accel`（本週pt - 上週pt）排序 Top5，不用掃 41 格直接看到誰在
  加速誰在轉弱
- **②轉折點列表**：抓「上週等級」跟「這週等級」真的翻轉一級的族群（例如強→整理、弱→超強），
  比單純幅度排序故事性更強——代表趨勢方向可能真的變了，不是單純波動
- **③角色說明**（`.role-note`）：區分異動族群 vs 族群近況的時間尺度差異

## 點開個股清單（v16 新增，之前 v11/v12 做過又在 v13 弄丟；展開方式 v18 定案）

點任一族群卡片（熱區格或異動族群卡片皆可）觸發 `selectGroup(name)`：

- 已展開同一張卡再點一次 → 收合（移除動態插入的 `#detailPanel` 節點）
- 展開新族群 → 先移除舊面板節點，重新建立並插入新位置，`.heat-tile.active` 標記當前選中
  卡片（`outline` 樣式）

**展開位置（v18 定案，取代 v16/v17 的固定位置方案）**：面板動態插入到**被點卡片所在那一整排**
的正下方，不是固定接在整個熱區格最後面，也不是側邊滑出。理由：v16 把面板固定接在熱區格最後面，
點越前面排的卡片視線要滑過的距離越長，跟點擊位置完全脫節；比較過的另一個方案（v17，右側滑出
drawer）雖然視線移動距離一致，但會遮住/擠壓部分熱區格內容——v18 的「原地展開」空間錨定感最好，
點哪裡就在哪裡展開，不遮住任何內容，是最終選定方向。

實作邏輯（`grid-column:1/-1` + `offsetTop` 分組）：

```js
// 找出被點卡片所在那一整排：用 offsetTop 分組，不能假設固定欄數
// （CSS grid 用 auto-fill，欄數會隨螢幕寬度變，要用實際渲染後的位置分組才對任何寬度都準確）
const tiles = [...document.querySelectorAll('.heat-tile')];
const rowTop = clickedTile.offsetTop;
const rowTiles = tiles.filter(t => t.offsetTop === rowTop);
const lastInRow = rowTiles[rowTiles.length - 1];
lastInRow.insertAdjacentElement('afterend', detailPanel);  // detailPanel 需要 grid-column:1/-1
```

點異動族群卡片（在熱區格外面的橫向捲動列表）也會展開到熱區格裡對應那張卡片所在的排——因為
異動族群本來就是 41 個族群裡的其中幾個，兩區塊指向同一份資料，這個行為順便展示了這一點。

⚠️ **已知取捨**：連續點擊不同族群時，因為每次展開位置不同（不同排），版面高度會跟著跳動
（不像固定位置方案那樣穩定）。這是接受的取捨，不是 bug。

個股表格欄位：股號＋股名、收盤價、漲跌%（照色系上色）、幅度長條（`.mini-bar`，寬度依
`|漲跌%| / maxChg` 正規化）。

**沒有資料的族群**（見下方已知限制）顯示誠實的空狀態文字，不是空白或錯誤。

## 動能狀態分類邏輯（草案）

呼應 `screener/signals.py::scan_momentum_health()` 的五級分類邏輯（超強/強/整理/弱/超弱），
但這是**族群層級**的簡化版，用「連漲天數(streak) + 本週比上週加速度(accel)」判斷，跟個股層級的
`scan_momentum_health`（MA 排列/exit rule/相對強弱）不是同一套規則，也**沒有共用程式碼**：

```js
function classifyTier(streak, lastWeekPct, thisWeekPct){
  const accel = thisWeekPct - lastWeekPct;
  if (streak <= -5) return 'superweak';               // 超弱：連跌 ≥5 日
  if (streak > 0 && accel > 3) return 'super';         // 超強：連漲中 + 明顯加速
  if (streak > 0 && accel >= -2) return 'strong';      // 強：連漲中，動能穩定
  if (streak < 0 && accel < -2) return 'weak';         // 弱：連跌中 + 明顯減速
  return 'mid';                                         // 整理：其餘情況
}
```

⚠️ **這組門檻（3/-2/-5）是這次先訂的草案，沒有回測驗證**，之後接真實資料時建議：
1. 跑一段歷史資料看五級的分布是否合理（會不會大部分族群都落在「整理」，或某一級幾乎沒有族群）
2. 評估要不要讓族群層級真的重用 `scan_momentum_health` 的規則常數，而不是各寫一份

## 「上週→本週」的資料語意（容易誤解，务必保留這個說明）

「上週→本週」是**滾動 5 個交易日**的複利累積漲跌幅，**不是自然日曆週**。跟現有
`get_rolling_returns` / `cum5`（`screener/database.py:331`、`processors/performance.py`）的
5 日窗口慣例一致。例如今天週三，「本週」會往前吃到上上週四、五，不是只算這週一到週三。

正式版標籤文字容易被誤讀成日曆週，建議加 tooltip 或改標籤措辭（例如「近5日→前5日」）。

## 視覺設計（Design Tokens）

深藍底＋銅金 accent，維持深色為預設主題，`prefers-color-scheme` 不再作為切換依據（改用
`:root[data-theme]` 手動切換，避免 v11 曾踩過的「淺色 fallback 跟深色太像導致深色沒生效」的
bug）。

```css
/* 深色（預設） */
--bg:#080B12; --panel:#0F1420; --panel-2:#161D2C; --panel-3:#1E2738;
--border:#293346; --border-2:#37435C;
--ink:#DADFE8; --ink-2:#98A0B4; --ink-3:#636B80;
--up:#E6432F; --down:#37B25C;                          /* 紅漲綠跌，飽和度刻意調高 */
--accent:#F0BB55; --accent-dim:#B98A3A;                 /* 銅金 */
--burst:#F0BB55; --trend:#C77FBD;                       /* 異動族群兩種訊號類型 */
--tier-super:#F0BB55; --tier-strong:#4FC46A; --tier-mid:#8B94AC;
--tier-weak:#E08A3E; --tier-superweak:#E6432F;           /* 動能五級 */
--heat-hot:#FF7A3D; --heat-cold:#4FA8E8;                 /* 溫度變化，刻意跟 up/down 分開 */
--serif: Georgia,"Iowan Old Style","Source Serif 4","Noto Serif TC",serif;
--sans: "Public Sans",-apple-system,"PingFang TC","Microsoft JhengHei","Segoe UI",sans-serif;
--mono: ui-monospace,"IBM Plex Mono","Cascadia Code","Roboto Mono",monospace;
```

淺色主題對應值見 mockup 檔案 `:root[data-theme="light"]` 區塊，色相對應但飽和度/明度調整過，
不是直接反色。

**色彩語意分層原則**（貫穿整個設計，之後加新指標要遵守）：今日漲跌（紅/綠）、動能五級
（金/綠/灰/橘/紅）、溫度變化（橙/藍）三組顏色系統故意互相區分，因為它們回答的是三個不同問題，
混用會讓使用者誤判是同一件事。

## 元件對應（實作到 `html_generator.py` 時的切分建議）

- 異動族群橫向捲動列表生成
- 熱區格生成（含底色/頂色雙編碼計算）
- 動能五級分類函式（`classifyTier`，建議跟 `scan_momentum_health` 共用規則常數）
- 溫度變化分類函式（`classifyTemp`）
- 族群近況：升溫/退燒排行 + 轉折點列表
- 個股點開面板（`selectGroup`，含個股表格 row 生成）

沿用純字串樣板產生 HTML（現行 `html_generator.py` 的既有寫法），不需要引入前端框架。

## 已知限制（誠實記錄，實作前必須解決或明確排除）

1. **個股層級資料完全沒接線**：`STOCKS` 目前是編造的展示資料，只有異動族群那 5 檔族群有範例。
   正式版要接 `calc_stock_sparklines()`（`processors/performance.py:284`）或等價查詢，
   算出每個族群的成分股清單＋今日漲跌%。**這是全部 41 個族群都要做，不是挑幾檔示範。**
2. **法人連買天數／量比是示範用的合理範例數值**，還沒接真實 `institutional` / `daily_prices`
   查詢。
3. **「上週等級」沒有歷史快照**：轉折點列表需要知道「上週的動能等級」，但目前系統沒有存
   每日/每週的 `classifyTier` 計算結果快照。正式版需要新增一個歷史快照機制（例如每天收盤後
   把當天的族群五級分類寫進 DB 一個新表），才能算出真正的「上週 vs 這週」翻轉，不是用
   mockup 裡的 `PREV_TIER_OVERRIDE` 手動指定。
4. **動能五級門檻、溫度變化門檻（±5pt）、異動族群門檻（量比≥1.5x、排名跳動≥10、streak≥5）**
   都是經驗法則草案，沒有回測驗證，需要用真實歷史資料跑過一輪確認鬆緊合理。
5. **異動族群目前固定顯示 5 張卡**，正式版應該是「符合條件的族群有幾檔就顯示幾檔」的動態結果，
   卡片數量會隨盤面波動（可能 0 檔、可能 15 檔），版面需要考慮空狀態跟過多時的呈現。

## 測試建議（實作階段）

- `classifyTier` / `classifyTemp` 邊界值單元測試（門檻值±1 的行為）
- 熱區格底色計算（`heatBg`）在極端值（漲跌幅接近 0 或達到當日最大值）下不出現非法 CSS 值
- 個股點開面板：無資料族群顯示空狀態、有資料族群表格排序穩定
- 視覺回歸：深色/淺色主題、桌機寬螢幕斷點（此頁目前沒有特別設計手機窄螢幕版面，需要另外評估
  熱區格在窄螢幕的 `auto-fill` 行為是否足夠，或要不要單獨设計手機版）

## 尚未定案 / 之後要討論

- 異動族群固定 5 張卡 → 動態數量的版面設計
- 歷史快照機制的具體 schema（新表？沿用現有表加欄位？）
- 手機窄螢幕版面（目前 mockup 全系列都只設計桌機寬螢幕）
- `DESIGN.md`（現行深色卡片系統規範）需要正式更新成這份 spec 的內容，避免兩份文件同時存在
  互相矛盾
