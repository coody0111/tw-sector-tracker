# MOPS 官方 XBRL 歷史基本面 Phase 2

日期：2026-09-01  
狀態：Phase 2A 已實作，待 Debugger／真實資料驗證

## 1. 決策

使用者核准 `1A 2A 3A 4A`：

1. IFRS 歷史從 2013 Q1 起，不在本階段解析 TW-GAAP。
2. 保存每次抓到的原始 ZIP、案例文件雜湊與版本；另提供最新有效值。
3. EPS 只保存官方累計值並做同期間 YoY，不相減推算單季或直接加總 TTM。
4. 先完成季度 XBRL 四大表，再接官方月營收歷史回填。

## 2. 官方來源

- 批次下載清單：`https://mopsov.twse.com.tw/mops/web/t203sb02`
- 批次 ZIP：清單頁公布的 `/server-java/FileDownLoad?...tifrs-YYYYQn.zip...`
- Taxonomy：`https://mopsov.twse.com.tw/mops/web/t203sb03`
- 單一公司人工核對：`https://mopsov.twse.com.tw/mops/web/t203sb01`

下載器必須從官方清單頁發現已存在的連結，不自行假設尚未公布的季度。免費網站沒有官方 SLA／限流數字；
採單工、低頻、timeout、有限重試與退避，不並行轟炸 MOPS。

## 3. 範圍

### 3.1 本階段包含

- 官方批次清單解析與 2013 Q1 起 IFRS ZIP 回填。
- ZIP 完整性檢查、SHA-256、版本化原始檔保存與重跑跳過。
- XBRL XML 與內容偵測後的 Inline XBRL 基礎解析。
- context、unit、QName、decimals、dimensions、原始值與正規化數值保存。
- 資產負債、綜合損益、現金流量、權益變動四大表的 canonical mapping 基礎。
- 目前有效值投影與既有 `financial_facts` 成長 view 串接。
- `python main.py --backfill-fundamentals 2013` 獨立命令。

### 3.2 不包含

- TW-GAAP 2009 Q4–2012 Q4。
- 以未公開 POST 格式大量抓單一公司頁。
- 把 `retrieved_at` 宣稱為官方申報日。
- 可用於無前視偏誤的 point-in-time 回測。
- 單季 EPS／TTM EPS 推估。
- UI、選股分數與自動排程。
- 月營收歷史；另接 Phase 2B，避免把 MOPS HTML 流程混入 XBRL parser。

## 4. 原始檔與版本

原始檔放在：

```text
data/fundamentals/xbrl/<year>/<archive-name>/<archive-sha256>.zip
```

相同 URL 若內容改變會產生新的 SHA-256 路徑；舊檔保留。資料庫保存 archive 與 instance 兩層 manifest。
ZIP 必須通過 `zipfile.testzip()`；路徑解壓僅在記憶體讀 entry，不把不可信 entry path 直接解到磁碟。

## 5. XBRL 解析

### 5.1 格式偵測

- XML XBRL：存在 `xbrli:context` 與帶 `contextRef` 的 facts。
- Inline XBRL：存在 `ix:nonFraction`／`ix:nonNumeric`；解析 `name`、`contextRef`、`unitRef`、
  `decimals`、`scale`、`sign`。
- 不以副檔名單獨判定格式；無 context 的 XML/XHTML 視為 taxonomy/support file 而跳過。

### 5.2 Context

保存 entity identifier、instant 或 start/end date、所有 explicit/typed dimensions。報告期：

- 資產負債表取 `instant == quarter_end`。
- 損益、現金流、權益變動取 `end_date == quarter_end`。
- canonical 累計值只取從該會計年度開始到 quarter_end 的 duration context。
- consolidated member 優先，其次無 dimensions；其他分部／地區 dimension 不投影為公司總值。

### 5.3 單位

- 原始 unit 與 decimals 永久保存。
- TWD 金額投影到既有 `financial_facts` 時除以 1,000，單位為 `TWD_thousands`。
- EPS 保持 `TWD_per_share`；股數保持 `shares`；比率保持 `percent`。
- XBRL `decimals` 是精度，不是倍率；Inline XBRL 的 `scale` 才套用十進位倍率。

## 6. Canonical 指標

第一版至少涵蓋：

- 損益：營收、營業成本、毛利、營業費用、營業利益、稅前淨利、所得稅、本期淨利、
  歸屬母公司淨利、基本 EPS、稀釋 EPS。
- 資產負債：流動／非流動／總資產、流動／非流動／總負債、股本、保留盈餘、母公司權益、總權益。
- 現金流：營業、投資、籌資活動淨現金流、匯率影響、現金淨增減、期初／期末現金。
- 權益變動：先保存 raw facts；僅在 QName mapping 明確時投影標準指標，不強行用中文 label 猜測。

Mapping 以 namespace URI + local name 的歷史 alias 表為基礎；不能只靠中文 label。
未知 QName 仍保存 raw fact，供日後擴充，不因 mapping 未涵蓋而遺失。

早期 TIFRS taxonomy 可能在 `sci`（損益）、`sfp`（資產負債）、`scf`（現金流）、
`sce`（權益變動）重複使用同一 local name。namespace 已明示報表時只能投影到對應 statement；
`notes` namespace 屬附註局部揭露，只保存 raw，不直接投影成主表 canonical 值。

## 7. 資料表與 View

- `xbrl_archives`：每個 archive SHA-256 一列。
- `xbrl_filings`：每個案例文件 SHA-256 一列，連回 archive。
- `xbrl_facts`：append-only raw facts，主鍵為 `(filing_sha256, fact_index)`。
- `xbrl_canonical_facts`：可投影的版本化標準 facts。
- `xbrl_current_facts`：只從該季度最新抓到的完整 archive 投影；不讓新版已略過／移除的 metric
  回退沿用舊 archive 值，也不宣稱 point-in-time。
- `financial_facts`：維持既有查詢介面，將目前有效 XBRL 投影 upsert 進去；source 標示 `mops_xbrl`。

## 8. 衍生數據

- 損益與現金流：Q1 單季等於累計；Q2/Q3/Q4 必須有同年度精確前季才相減。
- 資產負債：直接比較相鄰季末與去年同期。
- QoQ／YoY 基期缺失或為 0 時回 NULL。
- 基本／稀釋 EPS：`single_quarter_value`、QoQ、單季 YoY 一律 NULL；只算官方累計 EPS 的同季累計 YoY。
- 毛利率、營益率等比率由同公司、同版本、同 context 的分子分母計算；缺任一項回 NULL。

## 9. 錯誤處理

- 清單頁非成功回應、無任何 IFRS 連結或 XML 解析錯誤時明確失敗。ZIP 短傳、非 ZIP 擋頁、
  HTTP 暫時錯誤、CRC／central-directory 錯誤先以 5／20／60 秒退避重試；4 次均失敗才明確中止，
  且錯誤回應不得寫入 cache。
- 同一 instance 若同優先序 canonical 候選有不同數值，因無可靠依據選值，保存所有 raw facts、
  warning 並略過該 metric 的 canonical 投影；同一公司的其他 metric 與 archive 繼續處理。
- 單一 support file 無 context 可跳過；單一案例文件解析失敗時整個 archive transaction rollback，
  避免 manifest 顯示成功但 facts 不完整。
- archive 寫入與目前有效投影在同一 transaction 完成。
- 重新執行相同 SHA 不增加 raw facts；不同 SHA 追加新版本並更新目前投影。
- 回填預設略過已有已提交 manifest 的季度；archive transaction rollback 的失敗季度不算完成，
  同一指令會由該季續跑。需要主動檢查歷史更正版時使用 `refresh_existing=True`。

## 10. 驗收條件

- 清單 parser 只接受官方 `tifrs-YYYYQn.zip`，正確排除 TW-GAAP 與非 ZIP 連結。
- ZIP traversal entry 不會被寫到 cache 之外；損壞 ZIP 被拒絕。
- XML XBRL 能解析 instant/duration、unit、dimensions、nil、負數與 decimals。
- Inline XBRL 能處理 scale/sign，且不把 decimals 當倍率。
- 同 SHA 重跑 idempotent；同季度新 SHA 保留舊版本並更新 current view。
- context 不精確對齊時不推算單季。
- EPS 不相減；累計 EPS YoY 可查。
- Developer 只做 AST／編譯與 diff 靜態驗證；pytest 與真實 MOPS 回填交由 Debugger／Cody 執行。
