# 官方基本面資料

基本面模組只使用官方資料：上市走 TWSE OpenAPI、上櫃走 TPEx OpenAPI，不使用 FinMind。

## 更新最新資料

```powershell
python main.py --update-fundamentals
```

此命令只更新基本面 DuckDB 資料，不抓行情、不產生 HTML，也不執行 git push。

## 回填完整歷史

```powershell
# IFRS 季報與上市／上櫃月營收從 2013 起；第一次執行時間與磁碟用量較大
python main.py --backfill-fundamentals 2013
```

此命令先回填 MOPS XBRL 季報，再回填 MOPS 上市／上櫃 Big5 月營收整批頁。季度只採官方下載頁
實際存在的 ZIP；月營收終點由兩市場最新官方 OpenAPI 回應決定，不猜未公布月份。原始檔保存在
`data/fundamentals/`。指令預設為斷點續跑：已完整提交到 `xbrl_archives` 的季度會略過，失敗並
rollback 的季度會重新處理；因此本次中斷後可直接執行同一行，不會重抓已完成季度。

若要主動檢查已完成季度的官方 ZIP 是否有更正版，可從 Python 呼叫
`backfill_mops_xbrl(..., refresh_existing=True)`；內容變更時會以新 SHA-256 另存，不覆蓋舊版本。
重跑相同內容不增加資料列。

MOPS 大型 ZIP 若發生短傳、擋頁、暫時性 HTTP 錯誤或 CRC／central-directory 驗證失敗，會以
5、20、60 秒退避，最多嘗試 4 次；只有完整通過 ZIP 驗證的內容才會寫入 cache。

寫入內容：

- `monthly_revenue`：最新月營收與官方 MoM／YoY／累計 YoY。
- `monthly_revenue_pages`／`monthly_revenue_versions`：歷史 Big5 頁面及 append-only 正規化版本。
- `financial_facts`：目前有效的損益、資產負債、現金流 canonical facts。
- `xbrl_archives`／`xbrl_filings`：官方 ZIP 與公司案例文件版本 manifest。
- `xbrl_facts`：包含 QName、context、unit、decimals、dimensions 的 append-only 原始 facts。
- `xbrl_canonical_facts`：每個申報版本可明確 mapping 的標準指標。
- `xbrl_current_facts`：同公司／報告期／指標目前最新抓到的版本。
- `monthly_revenue_growth`：依資料庫原始營收重算的 MoM／YoY view。
- `financial_fact_growth`：累計損益／現金流轉單季、QoQ／YoY 與資產負債快照比較 view。
- `financial_ratios`：累計毛利率、營益率與淨利率。

## 常用查詢

```sql
-- 最新月營收與自行重算的年增率
SELECT stock_id, stock_name, revenue_month, revenue,
       calculated_mom_pct, calculated_yoy_pct
FROM monthly_revenue_growth
QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY revenue_month DESC) = 1;

-- 最新累計 EPS（官方申報值）
SELECT stock_id, stock_name, period_end, value AS eps_ytd,
       calculated_ytd_yoy_pct
FROM financial_fact_growth
WHERE metric_key = 'eps'
QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY period_end DESC) = 1;

-- 一般業單季營收、QoQ、YoY
SELECT stock_id, stock_name, period_end, single_quarter_value AS revenue_q,
       calculated_qoq_pct, calculated_quarter_yoy_pct
FROM financial_fact_growth
WHERE statement_type = 'income' AND metric_key = 'revenue';

-- 營業現金流累計值、推算單季值及成長率
SELECT stock_id, period_end, value AS operating_cash_flow_ytd,
       single_quarter_value, calculated_qoq_pct, calculated_ytd_yoy_pct
FROM financial_fact_growth
WHERE statement_type = 'cash_flow' AND metric_key = 'operating_cash_flow';

-- 累計毛利率／營益率／淨利率
SELECT stock_id, period_end, gross_margin_pct, operating_margin_pct, net_margin_pct
FROM financial_ratios;

-- 稽核同一報告期抓到的不同申報內容版本
SELECT filing.stock_id, filing.period_end, filing.filing_sha256,
       filing.first_seen_at, COUNT(fact.fact_index) AS raw_fact_count
FROM xbrl_filings filing
JOIN xbrl_facts fact USING (filing_sha256)
GROUP BY ALL
ORDER BY filing.stock_id, filing.period_end, filing.first_seen_at;
```

## 口徑

- OpenAPI 月營收／財報金額保存官方「新台幣千元」；XBRL 原始 facts 保留官方值，投影到
  `financial_facts` 時統一換成新台幣千元。
- EPS／每股淨值單位為元；名稱含「股數」的資產負債表欄位單位為股。
- 損益表官方數值是年初至本季累計；Q2/Q3/Q4 單季值必須有同年度前一季才能相減。
- EPS 不做累計相減，避免配股或分割後追溯調整造成錯誤。
- 基期缺失或為零時，成長率回傳 NULL。
- 官方 instance 若同一 QName、context、unit 與精度出現不同數值，兩筆都保留在 `xbrl_facts`，
  但略過該指標的 canonical 投影並記錄 warning；不猜測哪一筆正確，也不因此中止整季。

## 限制與回測警告

- MOPS 批次 ZIP 沒有被官方保證包含精確申報時間或完整更正次序；`first_seen_at`／`retrieved_at`
  只是本系統看見檔案的時間，不是公司申報日。因此 `xbrl_current_facts` 適合目前查詢，尚不可宣稱為
  無前視偏誤的 point-in-time 回測資料。
- `exchange` 優先由官方最新月營收表對照；歷史下市且目前對照不到的公司標為 `UNKNOWN`，不猜上市或上櫃。
- Phase 2A 已處理 2013 Q1 起 IFRS 季報；TW-GAAP 不在範圍。
- Phase 2B 會嘗試回填 2013 年起官方月營收。MOPS 未公布靜態頁的完整歷史起點與缺頁格式；
  任一月份標題、11 欄表頭或公司明細不符時會停止並明確報錯，已完成月份仍保留，修正後可重跑續接。
