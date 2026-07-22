# 族群總覽頁（index.html）熱區格改版 — 實作技術設計

**日期**：2026-07-22
**狀態**：已與 Cody brainstorming 定案，待寫 plan
**視覺/互動設計來源**：`docs/superpowers/specs/2026-07-15-sector-overview-heatmap-redesign.md`
（下稱「視覺 spec」）——那份文件已經定案頁面結構（v16）跟個股展開互動方式（v18），本文件**不重複**
那份的 CSS token、mockup 描述、頁面文案，只補上「拿真實資料怎麼接進去」這塊視覺 spec 明確留白的
技術決策。實作時兩份文件要一起看：視覺/互動照視覺 spec，資料層/檔案結構/測試照這份。

**範圍決定**：視覺 spec 列的三個功能區塊（①熱區格主體+個股點開 ②異動族群快報 ③族群近況+轉折點）
**一次全部做完**，不像逆轟策略 v2 那樣拆多個 Plan 分批上線。

---

## 1. 檔案結構

新建 `export/index_generator.py`，取代 `main.py::run()` 現在呼叫 `export/html_generator.py::generate()`
的位置。

- **`export/html_generator.py` 保留、不刪、不改**：`grep` 確認除了 `main.py` 跟它自己的
  `tests/test_html_generator.py`，沒有其他模組（`chips_generator.py`/`patterns_generator.py`/
  `momentum_generator.py`）依賴它，切換乾淨、無副作用。
- 之後想刪除舊檔（含其測試）是**獨立的後續任務**，不在這次範圍——先讓新頁面上線穩定一陣子再說，
  保留舊檔案讓 rollback（main.py 改回呼叫 `generate_html`）永遠是一行改動就能做到。
- 走跟 `chips_generator.py`/`momentum_generator.py` 一樣的慣例：Python 算好資料 → f-string 產生
  完整 HTML + 內嵌 JSON 資料常數，**不是**照搬 mockup 那種「HTML 內嵌 JS 常數陣列，由瀏覽器現算
  `classifyTier`/`heatBg`」的寫法。mockup 裡的計算邏輯搬到 Python 端算好、序列化成資料，JS 只保留
  `selectGroup()` 展開/收合這類純前端互動（DOM 操作，不涉及業務邏輯），比照 `patterns_generator.py`
  「Python 算資料、JS 做互動」的既有分工。

## 2. 資料層

### 2.1 直接重用（`main.py::run()` 現在就已經算好、傳給舊 `generate_html()` 的資料，原封不動接給新函式）

| 資料 | 來源函式 | 用途 |
|---|---|---|
| 今日漲跌/家數 | `meta_perf`（`calc_meta_performance()`） | 熱區格 `.ht-top` |
| streak（連漲跌天數）、量比 | `calc_meta_signals()` | 熱區格 `.ht-streak`／`classifyTier` 輸入之一／爆量暴衝判斷 |
| 外資/投信連買天數 | `calc_meta_chips_signals()` | 熱區格 `.ht-badges` |
| cum3/cum5/cum7 | `calc_cumulative_meta()`（`cum_data`） | 輔助佐證數字 |
| 個股清單（stock_id/name/close/change_pct） | `prices_df` + `universe_df` join | 個股點開面板的 STOCKS 陣列，跟現有 `_stock_table()` 同套 join 手法 |

### 2.2 新增：`_calc_prior_window_pct(meta_name, as_of_date, windows_back)`

現有 `calc_cumulative_meta()` 只算「以 `as_of_date` 為終點、往前 5 個交易日」這一個窗口
（`windows_back=0`）。這支新函式泛化成可以指定「往前數第幾個 5 日窗口」：

```
windows_back=0 → [as_of_date-4 ~ as_of_date]        （今天的「本週」，等同現有 cum5 邏輯）
windows_back=1 → [as_of_date-9 ~ as_of_date-5]      （今天的「上週」）
windows_back=2 → [as_of_date-14 ~ as_of_date-10]    （上週的「上週」，供轉折點回推用）
```

輸入只需要 `daily_prices` 往前抓 15 個交易日（含 `as_of_date` 當天），DB 歷史深度遠遠夠用，
不需要新的 DB 表、不會有冷啟動問題。

**資料不足時的行為**：若某族群當下可用的交易日數不滿 15 天（理論上不會發生，因為 DB 歷史已有
超過半年，但要對「防禦性寫法」明確表態，不留給實作階段自己猜），`_calc_prior_window_pct()`
回傳 `None`，`classifyTier()` 遇到 `None` 輸入一律回傳 `None`（族群狀態顯示「資料不足」，
不強行湊一個等級），跟專案既有慣例一致（`processors/observation_scores.py` 對資料不足因子
一律回 `None` 而不是硬湊數字）。轉折點列表在 `tier_今天` 或 `tier_上週` 任一為 `None` 時，
該族群直接跳過、不出現在轉折點列表（不能顯示成「沒有翻轉」，那是誤導）。

### 2.3 轉折點回推算法（不開新表，見 brainstorming 討論定案）

`classifyTier(streak, lastWeekPct, thisWeekPct)` 的三個輸入全部可以用「同一套邏輯，換一個
`as_of_date`」重算，不需要每天存快照：

```
tier_今天 = classifyTier(
    streak(截止到 T0 的連漲/連跌天數),
    lastWeek = window(windows_back=1, as_of=T0),
    thisWeek = window(windows_back=0, as_of=T0),
)

tier_上週 = classifyTier(
    streak(截止到 T-5 的連漲/連跌天數),   ← 序列截到 5 個交易日前重算，不是今天的 streak
    lastWeek = window(windows_back=2, as_of=T0),
    thisWeek = window(windows_back=1, as_of=T0),  ← 剛好等於 tier_今天 算過的 lastWeek，不重算
)
```

`tier_今天 != tier_上週` 即為轉折點。`streak(截止到某日)` 的計算方式比照 `calc_meta_signals()`
既有 streak 邏輯，只是改成吃一個「截止日期」參數（把族群每日平均漲跌序列截到該日期為止再算連漲/
連跌天數），不是永遠算到最新一天。

## 3. 頁面結構（照視覺 spec 順序，這裡只標註跟資料層/範圍相關的落地決策）

1. **Topbar**：沿用現行邏輯。
2. **異動族群**：因為選擇一次做完，直接做視覺 spec 明講的正確版本——**動態張數**（符合條件的
   族群有幾檔顯示幾檔，不是固定 5 張示範卡），0 檔時顯示誠實空狀態文案，不留空白區塊。
3. **熱區格主體**：41 張卡片全數 render（照視覺 spec 排列的五層內容），底色/頂色雙編碼公式
   直接搬視覺 spec 的 `heatBg()`/`classifyTier` 邏輯（Python 版本）。
4. **族群近況**：升溫/退燒雙欄 Top5（按 accel 排序）+ 轉折點列表（§2.3 算法）+ 角色說明提示框。
5. **個股點開面板**：`selectGroup()` 的 DOM 插入邏輯（`offsetTop` 分組、插入到被點卡片所在那一
   整排正下方）**直接照抄視覺 spec 給的 JS**，這段是純前端展開/收合，不涉及業務邏輯，不用重寫成
   Python。

### 3.1 技術債聲明：`classifyTier()` 是第三套獨立的五級分類邏輯

專案裡現在會有三套「五級動能狀態」分類邏輯，輸入完全不同、判斷結果不保證一致：

| 分類函式 | 層級 | 輸入 |
|---|---|---|
| `screener/signals.py::scan_momentum_health()` 的 `strength_tier` | 個股 | MA5/10/60 排列、出場三原則、族群內RS |
| `export/momentum_generator.py::classify_sector_state()` | 族群 | `calc_meta_observation_scores()` 的 5 因子觀察分（含法人資料） |
| `export/index_generator.py::classifyTier()`（這次新增） | 族群 | 純 `daily_prices` 的 streak + 5日窗口加速度，不查法人資料 |

這是視覺 spec 原本就接受的設計（熱區格要輕量、只吃股價資料、不能因為要查法人資料拖慢 41 格全部
render 的速度），這次**不重構統一**，但要在 `classifyTier()` docstring 跟 `DESIGN.md` 明確標注
「這是第三套獨立邏輯，跟另外兩個標籤字面看起來像但完全不共用計算依據」，避免以後有人誤以為
`index.html` 跟 `momentum.html` 對同一個族群的五級標籤是同一套判斷、混用來源。

## 4. 測試方式

- `classifyTier`/`classifyTemp` 邊界值單元測試（門檻 ±1 的行為）
- `heatBg` 極端值（漲跌幅接近 0 或達當日最大值）不出現非法 CSS 值
- `_calc_prior_window_pct` 正確性；轉折點回推邏輯要驗證「今天的 lastWeek 等於上週的 thisWeek」
  這個窗口重疊關係確實生效（不是巧合對到，是程式邏輯保證）
- 資料不足（可用交易日數不滿 15 天）時 `_calc_prior_window_pct`/`classifyTier` 回傳 `None`，
  轉折點列表正確跳過該族群，不誤顯示成「沒有翻轉」
- **41 個族群全部要有卡片**——沿用 2026-07-09 那次教訓的回歸測試精神
  （`test_generate_renders_card_for_every_meta_sector_not_just_top_bottom_10`），確認新版
  generator 不會重蹈「只 render 部分族群、其餘點不進去」的舊 bug
- 個股點開面板：無資料族群顯示誠實空狀態、有資料族群正確渲染
- XSS 防護：股票/族群名稱一律過 `_esc()`，這頁會發布到 GitHub Pages，比照
  `chips_generator.py`/`momentum_generator.py` 既有防護慣例

## 5. Out of scope

- 手機窄螢幕版面（視覺 spec 全系列 9 輪 mockup 都只做桌機寬螢幕，沒有可以照抄的設計，這次不生出
  新設計）
- 動能五級門檻（`classifyTier`）、溫度變化門檻（±5pt）、異動族群門檻（量比≥1.5x、排名跳動、
  streak≥5）的回測驗證——維持「經驗法則草案，待回測校準」標記，跟專案其他地方（`momentum_generator.py`
  的草案門檻等）同一慣例
- `export/html_generator.py` 整檔刪除（含其測試）——留給之後獨立任務

## 6. 這次順手一起做

- **`DESIGN.md` 更新**：把現行深色卡片系統規範換成這份 spec + 視覺 spec 的內容，避免兩份文件
  同時存在互相矛盾（視覺 spec 自己的「尚未定案」清單已列出這項）。
