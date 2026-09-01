# 0005：XBRL 申報以內容雜湊保存版本，最新值只是投影

日期：2026-09-01

## Status

Accepted

## Context

MOPS 官方提供按季整批 XBRL ZIP，但官方頁面未保證 ZIP 會保留原始申報、如何編列更正版次序，
也未保證 HTTP `Last-Modified` 或下載時間等於公司申報時間。若直接以
`(stock_id, period_end, metric_key)` 覆蓋舊值，之後無法判斷數值何時改變，也無法重新解析舊 taxonomy。

## Decision

1. 原始 ZIP 與每個案例文件都以 SHA-256 識別；新內容只追加，不刪除舊內容。
2. 保存來源 URL、檔名、抓取時間、檔案雜湊、QName、context、unit、decimals 與原始值。
3. 一般查詢使用「目前有效基本面值」投影：同一公司、報告期與標準指標，選本專案最新抓到的申報版本。
4. 抓取時間只稱 `retrieved_at`；官方申報時間未取得時保持 NULL，不以抓取時間替代。
5. 無前視偏誤回測必須等官方申報／更正時間資料接入，不能直接使用目前有效值投影。

## Consequences

- 可以稽核數值變動、重跑 parser 與 taxonomy mapping，且不會因更正版失去舊證據。
- 原始檔與 facts 會占用較多磁碟空間，但放在 gitignored `data/`，不增加 repository 體積。
- 當下畫面能使用最新投影；歷史回測則會明確降級，不假裝具有尚未取得的 point-in-time 語意。
- 若未來取得官方申報時間，可在不重抓原始 XBRL 的前提下補上版本時序。
