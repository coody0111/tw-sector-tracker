# 官方基本面資料層設計

日期：2026-08-31  
狀態：Phase 1 已實作，待 Debugger 驗證

## 1. 背景

`tw-sector-tracker` 目前有行情、法人、融資券、集保與內部人持股資料，尚無月營收及季報基本面資料。
本功能必須延續專案既有資料來源規則：上市走 TWSE、上櫃走 TPEx，基本面資料不使用 FinMind。

## 2. 目標

Phase 1 建立可重複執行的官方基本面更新流程：

1. 從 TWSE／TPEx 官方 OpenAPI 批次抓取最新月營收。
2. 從 TWSE／TPEx 官方 OpenAPI 抓取最新損益表及資產負債表。
3. 正規化兩市場及六種產業報表的欄位差異，寫入 DuckDB。
4. 保存原始申報值、來源、出表日期與首次觀察時間。
5. 提供月營收 MoM／YoY 與季報 QoQ／YoY 的查詢 view；比較基期不存在或為零時回傳 NULL。
6. 更新命令不得啟動行情抓取、HTML 生成或 git push。

## 3. 非目標

- Phase 1 不修改現有 HTML 頁面或選股分數。
- Phase 1 不把 FinMind、Yahoo Finance 或非官方網站當基本面 fallback。
- Phase 1 不解析 MOPS XBRL；官方 OpenAPI 只提供最新一期，因此部署前的完整歷史回補另列 Phase 2。
- Phase 1 不對金融、金控、保險、證券期貨業強算毛利率等不適用指標。
- 不從累計 EPS 直接相減或四季相加推算 TTM EPS。

## 4. 官方來源

### 4.1 月營收

- 上市：`https://openapi.twse.com.tw/v1/opendata/t187ap05_L`
- 上櫃：`https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O`

### 4.2 綜合損益表

- 上市：`t187ap06_L_{basi,bd,ci,fh,ins,mim}`
- 上櫃：`mopsfin_t187ap06_O_{basi,bd,ci,fh,ins,mim}`

### 4.3 資產負債表

- 上市：`t187ap07_L_{basi,bd,ci,fh,ins,mim}`
- 上櫃：`mopsfin_t187ap07_O_{basi,bd,ci,fh,ins,mim}`

產業 schema：`ci` 一般業、`basi` 金融業、`bd` 證券期貨業、`fh` 金控業、`ins` 保險業、
`mim` 異業。

## 5. 資料模型

### 5.1 `monthly_revenue`

主鍵：`(stock_id, revenue_month)`。

- `stock_id`, `stock_name`, `exchange`, `industry`
- `revenue_month`：統一存該資料月第一日
- `revenue`, `previous_month_revenue`, `previous_year_revenue`
- `reported_mom_pct`, `reported_yoy_pct`
- `ytd_revenue`, `previous_ytd_revenue`, `reported_ytd_yoy_pct`
- `note`, `report_date`, `first_seen_at`, `fetched_at`, `source`

金額以官方原始單位「新台幣千元」保存，不在 ingestion 時乘 1,000。

### 5.2 `financial_facts`

長表主鍵：`(stock_id, period_end, statement_type, metric_key, industry_schema)`。

- `stock_id`, `stock_name`, `exchange`
- `period_end`, `fiscal_year`, `quarter`
- `statement_type`：`income` 或 `balance`
- `industry_schema`, `metric_key`, `raw_name`
- `value`, `unit`, `is_ytd`
- `report_date`, `first_seen_at`, `fetched_at`, `source`

損益表為年初至本季累計值，`is_ytd=true`；資產負債表為期末快照，`is_ytd=false`。
EPS／每股淨值單位為元；名稱含「股數」的欄位單位為股；其餘金額預設為新台幣千元。

## 6. 正規化規則

1. 民國日期／年度一律加 1911 轉西元。
2. TPEx 可能使用 `Date`、`Year`、`Season`、`SecuritiesCompanyCode`、`CompanyName`；TWSE
   可能使用對應中文欄名，parser 必須同時接受。
3. 空字串、`-`、`--`、`N/A` 轉 NULL；逗號移除後轉數值。
4. 四碼股票代號以字串保存，不轉整數。
5. 同一市場不同產業 endpoint 若意外回傳重複 fact，完全相同值可去重；不同值視為資料衝突並中止，
   不可靜默覆寫。
6. OpenAPI 最新一期更新只能 upsert 同主鍵，不得刪除舊月份／季度。
7. `first_seen_at` 首次寫入後不可被後續更新覆蓋；`fetched_at` 每次成功抓取更新。

## 7. 衍生指標

### 7.1 月營收 view

- `calculated_mom_pct = (revenue / lag(revenue, 1 month) - 1) * 100`
- `calculated_yoy_pct = (revenue / lag(revenue, 12 months) - 1) * 100`
- 基期缺失、不是精確前一月／去年同月，或基期為 0 時回傳 NULL。
- 同時保留官方 `reported_*` 供完整性比對。

### 7.2 季報 view

- 損益表：Q1 單季值等於 Q1 累計；Q2/Q3/Q4 單季值為本期累計減同年度前季累計。
- 缺前季時，Q2/Q3/Q4 單季值為 NULL，不跨洞相減。
- 資產負債表直接以期末快照比較上一季及去年同季。
- `quarter_yoy_pct` 只比較同一 `metric_key`、同一季別及去年。
- EPS 不由累計數相減，Phase 1 只提供官方累計 EPS 與其累計 YoY。
- 比率的變化應以百分點表達，Phase 1 不預先物化比率。

## 8. 錯誤與完整性

- HTTP 非 200、非 JSON、空陣列或缺必要欄位時，該市場／報表更新失敗並拋出明確錯誤。
- 上市與上櫃分開抓取、分開記錄；單邊失敗不得把另一邊已存在資料刪掉。
- 一次 update 先完成抓取與正規化，再開 transaction 寫入，避免半張表更新。
- CLI 結束時回報各市場、各 statement 的抓取與寫入筆數。

## 9. CLI

新增：

```text
python main.py --update-fundamentals
```

命令只初始化 schema、抓最新官方基本面並 upsert，不執行平常的行情／籌碼／HTML／push 流程。

## 10. Phase 2：官方歷史回補

另行建立 MOPS XBRL spec，處理：

- 2019 Q1 起 Inline XBRL 與更早 XBRL 的格式差異。
- taxonomy 版本與六種產業的 concept mapping。
- instance context 的單季／累計期間辨識。
- 現金流量表、申報日期、更正版與歷史版本。
- 批次下載、WAF／限流、ZIP 完整性及斷點續傳。

完成 Phase 2 前，Phase 1 的 YoY／QoQ view 只會對已保存的歷史快照產生值，不偽造缺少的歷史。

## 11. 驗收條件

- TWSE、TPEx 月營收範例皆能轉成同一 schema。
- TWSE、TPEx 財報中英文識別欄皆可解析。
- 一般業與至少一種金融業 endpoint 可合併，且不產生重複主鍵。
- ROC 日期轉換、空值、負數、逗號及 EPS 單位有測試。
- 重跑同一期不增加重複列，且保留 `first_seen_at`。
- 月份中間有洞時 MoM 不跨洞計算。
- Q2 缺 Q1 時不推算單季數。
- `--update-fundamentals` 有獨立 CLI dispatch。
