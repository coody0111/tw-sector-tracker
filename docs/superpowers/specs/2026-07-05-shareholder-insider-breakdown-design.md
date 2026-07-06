# 大戶持倉張數化 + 內部人持股（公司派／大股東）— 設計文件

> 起因：Cody 反映「籌碼面大戶資料還是有問題」，釐清後發現不是既有邏輯錯誤，是現有 Section 8「大戶持倉」缺少三類重要資訊：(1) 大戶實際張數變化（目前只有比例%）(2) 內部人（董監事+經理人+關係人）持股 (3) 大股東(10%+)持股，以及對應的設質(質押)比例。過程中另外發現一個真正的既有 bug（`scrapers/shareholder.py` 重試機制形同虛設），已另外修復並記錄在 `debug-tasks.md`，不在本次 spec 範圍內。

---

## 背景與目標

現有 `shareholder` 表（`scrapers/shareholder.py`，TDCC 集保股權分散表，每週五更新）只追蹤「≥400張大戶」這一個級距的**比例%**，`lv12_15_shares`（大戶實際持有股數）在 scraper 裡已經算出來但沒有存進 DB，導致完全無法回答「大戶這週張數到底增加了多少」。

另外，董監事／經理人／大股東(10%+) 這類「內部人」持股資訊完全沒有資料源——TDCC 集保表只按持股張數級距分組，不知道帳戶身分，這是完全不同的資料源（公開資訊觀測站的內部人持股月報）。

本次設計目標：
1. 把 TDCC 大戶的實際張數變化補上（不只是比例%）
2. 新增內部人持股資料源，區分「公司派」（董事+監察人+經理人+關係人）跟「大股東」（10%以上，不一定是經營層）兩類，各自含設質(質押)比例
3. Section 8 表格同步校正「收盤價」對齊集保週期，並新增「週股價變化」，讓大戶動向跟股價表現可以直接對照

---

## 架構決策

**三個方案比較過**（大戶/內部人資料要怎麼串接呈現）：
1. **【採用】內部人持股獨立建一張新表（月頻），只在畫面渲染時 join 現有週頻的 `shareholder` 表** — 兩張表各自照原本頻率更新，不互相污染，渲染時各自抓「最新一筆」拼成同一列
2. 內部人欄位直接塞進 `shareholder` 表（週頻）— 會讓月資料在同一個月的 4-5 筆週資料裡重複儲存，日期意義混淆，不採用
3. 渲染當下即時打公開資訊觀測站 API、不落地存 DB — 無法計算月變化，也不符合本專案「先存 DuckDB 再算衍生欄位」的既有架構慣例，不採用

---

## 資料表結構

### 1. `shareholder` 表新增欄位

```sql
ALTER TABLE shareholder ADD COLUMN lv12_15_shares BIGINT;   -- 大戶(≥400張)實際持有股數
```

`scrapers/shareholder.py::_fetch_one_stock()` 已經算出 `lv12_15_shares`（見現有 `lv_shares` 變數），只是 `save_to_db()` 目前沒有寫入這欄，這次補上。

渲染時：`(本週 lv12_15_shares - 上週 lv12_15_shares) / 1000` 算出「張數變化」，跟現有 `week_chg`（%變化）並列顯示，不取代。

### 2. 新表 `insider_holdings`（月頻）

```sql
CREATE TABLE IF NOT EXISTS insider_holdings (
    stock_id                VARCHAR NOT NULL,
    report_date             DATE NOT NULL,
    company_shares          BIGINT,   -- 公司派（董事+監察人+經理人+關係人）合計持股股數
    company_chg             BIGINT,   -- 公司派股數月變化（跟上個月比較，本表自己算，來源不提供現成的變化值）
    company_pledge_pct      DOUBLE,   -- 公司派合計設質股數 / 合計持股股數 * 100
    major_holder_shares     BIGINT,   -- 大股東(10%+)合計持股股數
    major_holder_chg        BIGINT,   -- 大股東股數月變化
    major_holder_pledge_pct DOUBLE,   -- 大股東合計設質股數 / 合計持股股數 * 100
    PRIMARY KEY (stock_id, report_date)
)
```

「關係人」（配偶／未成年子女／利用他人名義持有）併入「公司派」計算，理由：關係人本質是幫內部人代持，不是獨立的股東類型。

`company_chg`/`major_holder_chg` 的計算方式比照 `shareholder.py::_add_week_change_streak`：跟 DB 裡該股「嚴格更舊月份」的最新一筆比較，同月重跑時排除同月資料當基準（避免同月重跑把變化洗成 0，這是既有 TDCC 邏輯已經踩過的坑，這次直接比照防呆）。**本次不做 streak（連增/連減月數）**——月頻資料要累積到有意義的連續月數門檻較高，範圍先縮小到「最新值＋月變化」，之後如果需要再獨立加。

`company_pledge_pct`/`major_holder_pledge_pct` 若該組別 `合計持股股數 == 0`（理論上不該發生，但防呆一下），存 `NULL`，避免除以零；渲染時比照其他缺值欄位顯示「─」。

---

## Scraper 模組（`scrapers/insider_holdings.py`）

比照 `shareholder.py` 既有模式：

- `fetch_insider_holdings_monthly(stock_ids, year_month=None) -> list[dict]`：逐股查詢公開資訊觀測站「董事、監察人、經理人及大股東持股餘額彙總表」，依身份別分組加總算出 `company_shares`/`company_pledge_pct`、`major_holder_shares`/`major_holder_pledge_pct`。
- `save_to_db(rows)`：upsert 進 `insider_holdings` 表，並算出 `company_chg`/`major_holder_chg`。

**Open Item（實作階段第一步要做）**：這份資料源實際的 HTTP 請求格式（是否跟 TDCC 一樣需要一次性 SYNCHRONIZER_TOKEN、實際回傳 HTML/table 結構、身份別欄位怎麼標示）目前只有透過網路搜尋確認資料**存在**且欄位範疇正確（董事/監察人/經理人/大股東(10%+)/關係人 + 持股數/設質股數/設質比例），沒有實際打過真實請求驗證格式。實作階段的第一個 step 必須先用小腳本打一次真實請求、存一份真實回應當 fixture，確認欄位解析方式，才能寫 `_fetch_one_stock` 等價函式，不能用猜的直接寫解析邏輯（比照當初 TDCC scraper 的驗證方式）。

**CLI**：新增 `--update-insider-holdings`，跟 `--update-shareholder` 一樣手動觸發（月頻，不排進每日流程），Cody 大約每月跑一次。

---

## 價格對齊修正（連帶發現的既有落差）

現況：`main.py` 組 `sh_rows` 時，「收盤」欄位抓的是 `daily_prices` 裡**最新一個交易日**的價格/漲跌%，不是跟集保資料同一天——兩者日期可能對不上（集保通常是上週五，但主程式可能是幾天後才重新產生頁面）。

修正：
- `get_shareholder_top()` 改成同時回傳「本週」與「上週」的集保日期（用 `ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC)` 取 rn=1/rn=2，比照 `recompute_latest_streak()` 已有的模式）
- `main.py` 改成用這兩個日期去 `daily_prices` 查對應的收盤價，算出：
  - `close`：本週（集保日期當天）收盤價，取代現在的「最新交易日」價格
  - `price_week_chg`：本週收盤 vs 上週收盤的漲跌%
- 若集保日期當天 `daily_prices` 查無資料（例如缺資料），`close`/`price_week_chg` 顯示「─」，不做往前找最近交易日的複雜邏輯（YAGNI）

---

## Section 8 呈現（`export/chips_generator.py::_shareholder_table`）

欄位變成：

`# | 股票 | 族群 | 收盤（週漲跌%） | 大戶持倉%（週變化） | 大戶張數變化 | 連增週 | 公司派持股（月變化／質押%） | 大股東持股（月變化／質押%）`

- 新增的欄位（大戶張數變化、公司派、大股東）比照現有「收盤」欄位的雙行呈現方式（數字＋下面一行變化量），質押%用小字附註在同一格，不另開新欄，避免表格爆寬
- 配色沿用現有 `_pct_color`/既有紅漲綠跌慣例（漲/增=紅、跌/減=綠），新欄位（含設質比例的月變化）一律套同一套配色規則，不特別做語意判斷或警示色（例如不因為「設質比例上升」就用不同的配色邏輯）
- 排序/篩選邏輯維持不變：還是用 TDCC 大戶 `streak` 分「Top 30 連增倉」／「Top 20 連減倉」，新欄位（張數變化、公司派、大股東、週股價變化）純資訊呈現，不影響誰上榜
- 若某股票還沒有 `insider_holdings` 資料（新股、當月還沒申報、或還沒手動跑過 `--update-insider-holdings`），該欄顯示「─」

---

## 測試

`tests/test_shareholder.py` 新增：
- `lv12_15_shares` 有正確存入 DB、週張數變化計算正確

`tests/test_insider_holdings.py`（新檔）：
- `company_chg`/`major_holder_chg` 的月度比較邏輯正確（比照現有 streak 測試的「排除同月重跑」case）
- 只有一個月資料（無前值可比）時不報錯，`chg` 為 `None`
- 質押比例計算正確（`合計設質股數 / 合計持股股數 * 100`）

`tests/test_database.py`（或現有對應測試檔）新增：
- `get_shareholder_top()` 正確回傳本週/上週日期
- 價格對齊：`close`/`price_week_chg` 對應到集保日期而非「最新交易日」

---

## Out of scope（本次不做，列為後續任務）

- 內部人持股／設質資料的 streak（連增/連減月數）追蹤——先做「最新值＋月變化」，之後有需要再加
- 內部人持股歷史回補（backfill）——公開資訊觀測站這份月報是否有歷史查詢端點還沒確認，這次只做「往前每月手動更新累積」，沒有一次補齊過去的路徑（比照 TDCC 目前也沒有 backfill 的現況）
- Section 8 之外其他頁面（`index.html`／`patterns.html`）的呈現調整——這次範圍限定在 `chips.html` Section 8
