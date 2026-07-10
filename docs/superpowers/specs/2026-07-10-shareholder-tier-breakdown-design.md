# 大戶持倉分層追蹤（400張／1000張）＋ 修正週變化計算 Design

## Goal

把現有「大戶持倉」（TDCC 集保股權分散表 level 12-15 合計）拆出兩個獨立追蹤的分層：
- **400張大戶**（level 12：400,001~600,000股，剛達大戶門檻）
- **1000張大戶**（level 15：1,000,001股以上，真正的千張大咖）

每個分層各自顯示：現況張數、週張數變化、佔總股本百分比。

同時修正這次調查發現的兩個既有 bug（見下方「Background」）。

## Background / 問題

現況 `shareholder` 表只有 level 12-15 合計的 `lv12_15_pct`/`lv12_15_shares`，無法區分「剛達大戶門檻」跟「真正千張大咖」——兩者代表的籌碼意義完全不同。TDCC 回應本身逐 level 都有資料，現有 `_fetch_one_stock()` 只是把 12-15 加總後就把個別數字丟掉。

順便發現並要修正兩個既有 bug：

1. **`lv12_15_shares` 全表 NULL**：schema 用 `ALTER TABLE ADD COLUMN` 加了這欄，但加欄位不會回填歷史資料，且加欄位之後沒有任何一次 `--update-shareholder`/`--backfill-shareholder` 真的跑過，所以連最新一筆也是 NULL。這個 spec 不解決「跑資料」本身（那是 Cody 的事），但新增的 3 個 tier（合計＋400＋1000張）都要避免重蹕同樣的坑。

2. **歷史 `week_chg` 損毀**：實測 `2380`（虹光）從 2026-05-08 到 06-12 每一筆的 `week_chg` 都精確等於「自己的 lv12_15_pct − 100.0」，而不是跟真正前一週比較的差值；`100.0` 這個值只出現在更晚的 2026-06-26 那筆（疑似 TDCC 該週解析錯誤產生的離群值，一個正常在 ~44-45% 遊走的股票沒有理由一週內衝到 100%）。目前只有 `recompute_latest_streak()` 這個工具，但它只修「每支股票目前最新一筆」，不會動到已經寫壞的歷史列，所以這批壞資料一直留在表裡。

## Non-goals

- 不重新設計現有 `lv12_15_*` 合計欄位的用途或呈現方式
- 新的 400/1000 張分層本次不做 streak（連增/連減週數）追蹤，跟現有 spec「本次不做 streak」原則一致
- 不調查 TDCC 該週回應本身為何解析出 100.0%（需要對照原始 HTML，建議 Cody 之後人工核對 2380 那筆）
- 不會由我實際執行 `--update-shareholder`/`--backfill-shareholder`——`lv12_15_shares`（含新的 lv12_shares/lv15_shares）要有真實數字，仍需要 Cody 自己跑一次

## Architecture

沿用既有 `scrapers/shareholder.py` 的 fetch → save_to_db 模式，是既有資料源的欄位擴充，不是新資料源，不新增模組。

### 1. `scrapers/shareholder.py::_fetch_one_stock()` — 多留 level 12、15 個別數字

現有迴圈把 level 12-15 直接加總進 `lv_shares`/`lv_cnt`。改成在加總的同時，額外記錄 `level == "12"` 與 `level == "15"` 各自的 `shares`：

```python
lv12_shares = 0
lv15_shares = 0
...
elif level in _LARGE_HOLDER_LEVELS:
    lv_shares += shares
    lv_cnt += cnt
    if level == "12":
        lv12_shares = shares
    elif level == "15":
        lv15_shares = shares
```

回傳值新增：`lv12_shares`、`lv15_shares`，以及對應百分比 `lv12_pct = round(lv12_shares/total_shares*100, 4)`、`lv15_pct = round(lv15_shares/total_shares*100, 4)`（`total_shares == 0` 時整筆已經回 None，沿用既有防呆）。不新增 HTTP request——TDCC 回應本來就含所有 level，只是解析時多留兩個數字。

### 2. Schema（`screener/database.py::init_db()`）

`shareholder` 表只新增 4 個**現況快照**欄位（不存週變化——理由見下方第 3 節），比照現有 `lv12_15_shares` 的 `ALTER TABLE ADD COLUMN IF NOT EXISTS` 模式處理既有 DB：

```
lv12_shares      BIGINT,
lv12_pct         DOUBLE,
lv15_shares      BIGINT,
lv15_pct         DOUBLE,
```

### 3. 週變化計算 — 比照既有 `share_chg`，不存表、查詢時算

**修正一個設計草稿裡的不一致**：現有合計欄位的 `share_chg` 其實**不是**存在 `shareholder` 表裡的欄位，而是 `get_shareholder_top()` 用 self-join 在查詢當下算出來的（`latest.lv12_15_shares - prev.lv12_15_shares`）。真正持久化、會被 `_add_week_change_streak()` 寫入表裡的，只有合計欄位的 `week_chg`（百分點）跟 `streak`——這兩個是給「連增/連減週數」用的狀態，需要逐週累積，才需要落地存表。

400/1000 張這兩個新 tier **這次不做 streak**（見 Non-goals），所以不需要落地存 week_chg／streak，**比照 `share_chg` 的做法**：`lv12_shares`/`lv15_shares` 只存「現況快照」，週張數變化在 `get_shareholder_top()` 用 self-join 用「今值 − 前一週值」現算，命名 `lv12_chg`/`lv15_chg`（單位股，顯示時 /1000 轉張）。這樣不會多開一組「插入當下計算、可能被同週重跑或亂序寫入搞壞」的持久化欄位，從根源上避開這次發現的那種歷史資料損毀模式。

**為什麼週變化用張數差、不用百分點**：level 12（400-600張窄帶）樣本小，一個大戶從 590 張加碼到 610 張就會跨進 level 12、讓人數/股數「無中生有」多一筆，這是級距邊界跨越的雜訊，不是真正的加碼。用張數差呈現至少讓使用者看到「這個 bucket 的股數確實變了多少」；百分比（`lv12_pct`/`lv15_pct`，現況佔比，非其變化量）另外顯示供跨股票比較用，但不把「週變化」本身包成百分點。

### 4. 修復既有損毀資料 — `recompute_all_history()`

新增 `recompute_all_history(db_path=_DB_PATH) -> int`：對整張 `shareholder` 表，依 `stock_id` 分組、日期排序，逐週用**真正的前一週**重算現有合計欄位的 `week_chg`（百分點）與 `streak`，一次性覆蓋掉這次發現的所有歷史髒值（例如 2380 那 6 筆等於「自己 pct − 100.0」的錯誤資料）。跟只修「最新一筆」的既有 `recompute_latest_streak()` 分開保留（用途不同：latest 版本是 backfill 完的日常對齊，all-history 版本是這次的一次性除錯，之後若再發現類似資料損毀也能重跑）。這個函式**只處理合計欄位**（唯一有持久化 week_chg/streak 的欄位），跟第 3 節的新 tier 無關。

### 5. `save_to_db()`

`df` 的欄位選取清單、`INSERT` 的欄位清單都要加上這 4 個新欄位（比照現有 `lv12_15_shares` 已經處理過的「明列欄位名，避免 ALTER 加欄位位置跟 CREATE TABLE 不同導致位置式 INSERT 錯位」的教訓）。

### 6. `screener/database.py::get_shareholder_top()`

`SELECT`／self-join 多帶 `lv12_shares, lv12_pct, lv15_shares, lv15_pct`，並比照現有 `share_chg` 的算法新增 `lv12_chg`、`lv15_chg`（`latest.lv12_shares - prev.lv12_shares`／`latest.lv15_shares - prev.lv15_shares`）。

### 7. `main.py` 組裝 `sh_rows`

比照現有欄位原樣傳遞這 6 個新值（`lv12_shares, lv12_pct, lv12_chg, lv15_shares, lv15_pct, lv15_chg`）進 `sh_rows`，不需要額外查詢（已經在 `get_shareholder_top()` 一次查完）。

### 8. 顯示（`export/chips_generator.py::_shareholder_table()`）

新增兩欄「400張大戶」「1000張大戶」，樣式跟現有 `_insider_cell()` 一致（張數／變化／百分比三行），共用同一個 helper 或新增類似函式：

```
{shares/1000:,.0f}張
{sign}{chg_shares/1000:,.0f}張
{pct:.1f}%
```

（`chg_shares` 即第 6 節 `get_shareholder_top()` 算出的 `lv12_chg`/`lv15_chg`）缺值一律顯示「─」（沿用既有慣例）。

## 測試

- `_fetch_one_stock`：新增 level 12/15 解析測試案例，確認個別數字跟合計數字同時存在且一致（lv12+lv13+lv14+lv15 == lv12_15 合計）
- `save_to_db`：確認 4 個新欄位（`lv12_shares`/`lv12_pct`/`lv15_shares`/`lv15_pct`）有正確寫入
- `get_shareholder_top`：`lv12_chg`/`lv15_chg` 用真正前一週正確算出、只有一週資料時回 NULL 不報錯（比照現有 `share_chg` 的測試模式）
- 合計欄位既有的週變化邏輯（`_add_week_change_streak`）不受影響：正常前後週比較、同週重跑不洗成 0（沿用既有教訓）、無前值時回 None
- `recompute_all_history`：模擬一段「損毀」資料（歷史 week_chg 全部等於「自己 pct − 某離群值」），驗證重算後每筆都恢復成跟真正前一週的差值
- `_shareholder_table`：新兩欄有出現、正確格式化、缺值顯示「─」

## Out of scope

- 400/1000 張 tier 的 streak（連增/連減週數）追蹤
- TDCC 該週離群值（2380 100.0%）成因調查——建議 Cody 之後人工核對
- 實際執行 `--update-shareholder`/`--backfill-shareholder`（Cody 自己跑）
