# MOPS 官方月營收歷史 Phase 2B

日期：2026-09-01  
狀態：已實作，待 Debugger／真實資料驗證

## 1. 目標

以 MOPS 官方上市／上櫃整批靜態 HTML 回填 2013 年起月營收，讓既有
`monthly_revenue_growth` 第一次回填後即可計算精確 MoM／YoY。與季度 XBRL parser 分開，
但由同一 `--backfill-fundamentals` 指令依序執行。

## 2. 官方來源

```text
https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_<ROC_YEAR>_<MONTH>_0.html
https://mopsov.twse.com.tw/nas/t21/otc/t21sc03_<ROC_YEAR>_<MONTH>_0.html
```

- `sii` 是上市，投影為 `TWSE`；`otc` 是上櫃，投影為 `TPEx`。
- 靜態 GET，不需 POST／cookie／JavaScript。
- HTML meta 宣告 Big5；HTTP Content-Type 沒有 charset，必須以 Big5 解碼。
- 單位數月份命名未獲官方確認，下載器依序嘗試不補零與補零 URL，並以內容驗證決定。

## 3. 內容驗證

成功頁必須同時符合：

1. HTTP 200。
2. Big5 可解碼。
3. 標題文字含預期市場、民國年及月份。
4. 至少一個產業別。
5. 找到完整 11 欄表頭與至少一筆合法公司代號明細。

HTTP 200 但為擋頁、錯誤頁、錯誤年月或沒有公司資料，一律失敗，不寫入空頁。網路錯誤不記成永久無資料。

## 4. 正規化

11 欄依序為公司代號、公司名稱、當月營收、上月營收、去年當月營收、上月比較增減%、
去年同月增減%、當月累計營收、去年累計營收、前期比較增減%、備註。外層產業別帶入每筆公司資料。

- 合計列與不符合 4–6 位數公司代號的列排除。
- 金額移除千分位後保存為官方單位「新台幣千元」。
- 百分比保留官方值；`monthly_revenue_growth` 另依精確月份自行重算。
- 靜態頁沒有可確認的申報日，`report_date` 為 NULL，不以抓取日替代。
- 同頁重複公司且值衝突時整頁失敗。

## 5. 版本與保存

原始 HTML 以 SHA-256 保存：

```text
data/fundamentals/monthly_revenue/<exchange>/<year>/<month>/<sha256>.html
```

- `monthly_revenue_pages`：頁面 manifest。
- `monthly_revenue_versions`：每個 page SHA 的正規化公司列，append-only。
- `monthly_revenue`：目前有效投影，沿用 Phase 1 查詢介面。

相同內容重跑 idempotent；同年月內容改變時保留舊 page/version，並以最新抓到的版本更新目前投影。
若既有 OpenAPI row 有官方 `report_date` 而歷史頁沒有，保留既有 report_date。

## 6. 回填範圍

- 預設從 2013 年 1 月開始。
- 每個市場的結束月份由該市場官方最新月營收 OpenAPI 回應決定，不猜發布截止月。
- 月份按市場逐月單工抓取，有限重試與低頻延遲，不並行轟炸 MOPS。
- 完整歷史起點未獲官方確認；中途缺頁或格式錯誤時明確失敗，已成功月份保留，重跑可續接。

## 7. 驗收條件

- Big5 中文公司名／備註正確。
- 產業合計列被排除，11 欄公司列正確解析。
- TWSE／TPEx 不混用。
- 200 擋頁／錯誤年月／空表被拒絕。
- 同 SHA 重跑不增列；新 SHA 保留舊版本並更新 current。
- 既有 OpenAPI report_date 不被 NULL 覆蓋。
- 缺一個月時 MoM 不跨洞；完整 13 個月後 YoY 可計算。
- Developer 不跑真實資料或 pytest；交由 Debugger 小範圍實測後才跑完整歷史。
