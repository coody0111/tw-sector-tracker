## [2026-07-02] 即時行情零成交股 close=0 防呆補強

### 改了什麼
- 異動檔案：`scrapers/realtime.py`
- 邏輯說明：`fetch_realtime_prices()` 內部 `_best_price()` 其實已經對「z(最近成交價)/五檔買賣價/今高/今開」逐層做過 `>0` 檢查，理論上不會回傳 0；呼叫端原本只判斷 `if price is None: continue`，沒有在 call site 明確擋 `price <= 0`。這次補上 `if price is None or price <= 0: continue`，把「這一支不寫入」的不變量明確寫在呼叫端，避免以後 `_best_price()` 內部邏輯調整時，任何一個 fallback 分支不小心漏做 `>0` 判斷就會直接把 0 寫進 `daily_prices`。
- 這次沒能在目前這份 `data/screener.db` 重現 bug-reports.md 描述的 `2321 close=0.0, volume=1` 那筆（本機查到的 `2321` 今天實際收 `13.7`），研判當時 Debugger 是在他自己另一份 debug 快照資料夾看到的，屬於單次快照、無法回溯重現；程式碼邏輯這邊算是補強而非復現後修復，之後如果又遇到同樣情況麻煩附上當下的 `data/daily_prices/<date>.csv` 該筆原始內容方便對照。

### 資料來源相關（如有異動）
- 上市資料（TWSE）：不影響（`fetch_realtime_prices` 同時處理 TWSE `tse_`／TPEx `otc_` 前綴，這次改動是共用的價格防呆邏輯，非交易所專屬）
- 上櫃資料（FinMind）：無關（即時行情走 mis.twse.com.tw，不經過 FinMind）

### 特別注意
- 未寫測試（照 CLAUDE-developer.md：測試交給 Debugger），麻煩驗證时可以用假造 `item`（`z="0"`, 五檔／今高／今開皆 `"-"` 或 `"0"`）confirm `fetch_realtime_prices` 不會產生該筆 row
- `stock_universe.csv` `生物辨識` 只有 2 檔（5203/6910）那項還沒處理，需要 Cody 確認是否為完整清單，不是程式 bug，先留著

---

## [2026-07-02] 修正 3114 離群資料

### 改了什麼
- 異動檔案：`data/daily_prices/2025-04-25.csv`、`data/daily_prices/2025-04-28.csv`（資料檔，非程式碼，已 gitignore）
- 邏輯說明：`3114`（好德，TPEx）在 `2025-04-25` 的 `close` 是 `2118.96`（前後幾天約 NT$20），確認是 FinMind API 當時吐出的髒值（非我方程式轉換錯誤，`_fetch_finmind_history()` 直接用 API 回傳值，沒有做單位換算；現在重打 FinMind API 該日資料已是乾淨的 22.3，代表是他們資料源當時的一次性錯誤）。用 `2118.96 / 100 = 21.19` 校正，跟前後兩天內插估算值吻合。同步修正 `2025-04-28` 的 `change`/`change_pct`（原本是拿髒值 2118.96 當前一天收盤算出 -98.98%，改成用校正後的 21.19 重算為 1.79%）。
- 已執行 `python main.py --reimport` 重建 DuckDB，`daily_prices` 表已同步校正值，驗證過 `3114` 前後幾天 `change_pct` 恢復正常區間。

### 資料來源相關（如有異動）
- 上市資料（TWSE）：無異動
- 上櫃資料（FinMind）：修正 `3114` 單一離群值，非程式邏輯改動，不影響其他股票

### 特別注意
- 這不是程式碼修復，純資料修正，git 不會有 diff（`data/` 已 gitignore）
- bug-reports.md 對應的 🟡 建議改善（`2321` 即時行情 close=0 瑕疵、`生物辨識` 族群僅 2 檔）尚未處理
