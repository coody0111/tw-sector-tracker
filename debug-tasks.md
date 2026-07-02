## [2026-07-02] 籌碼分析頁邏輯修復（4 項）

### 改了什麼
- 異動檔案：`main.py`、`processors/performance.py`、`export/chips_generator.py`、`screener/institutional.py`

**1. `main.py::_backfill_shareholder()` 集保回補日期順序反了（大戶持倉 Section 8 一直是空的根因）**
- `get_available_dates()` 回傳的日期是新到舊（`available[0]` = 最新週），但 `--backfill-shareholder` 直接用 `available[:weeks]` 依序寫入，等於先寫最新週、再寫較舊的週。
- `scrapers/shareholder.py::_add_week_change_streak()` 算 `week_chg`/`streak` 的邏輯是「跟 DB 裡目前最新一筆比」，這個邏輯本身沒問題，但假設呼叫端是照時間正序寫入。回補用反序寫入，會讓第二筆（較舊週）去跟第一筆（較新週，已經先寫進 DB）比較，算出方向相反、無意義的漲跌/連續週數。
- 修法：`target_dates = list(reversed(available[:weeks]))`，改成舊到新依序寫入。
- **這是 Section 8「大戶持倉」目前永遠空白的根本原因**：DB 裡目前只有 2026-06-26 單一週資料（`--backfill-shareholder` 從沒真的成功跑過或只跑了 1 週），`streak` 全部是 0，連增/連減 Top 榜單篩選 `streak>0`/`streak<0` 自然都是空的。修好日期順序後，麻煩 Cody 執行 `python main.py --backfill-shareholder 8`（抓 8 週歷史）才會開始有數據，我沒有自己跑。

**2. `processors/performance.py::calc_meta_chips_signals()` — Section 5 族群外資買超比例分母算錯**
- 原本 `meta_stock_count`（分母）用該族群「全部成分股數」（含上櫃），但 `institutional`/`margin` 兩張表**完全沒有上櫃資料**（T86／MI_MARGN 都是上市專屬 API）。分子只可能來自上市股票，分母卻含上櫃股票，比例被系統性低估，且各族群低估幅度不同（上櫃佔比高的族群失真更嚴重，最高驗證到 82%）。
- 修法：分母改成只算該族群「上市（TWSE）成分股數」。同步把 `chips_generator.py` Section 5 的表頭文字加註「上市成分股，三大法人資料無上櫃來源」，避免使用者誤讀。

**3. `export/chips_generator.py` — 上櫃篩選鈕沒有說明籌碼表格會是空的**
- 在「🏛 上市／🏪 上櫃」篩選鈕旁加一行提示文字，說明三大法人/融資融券資料只有上市來源，切換上櫃篩選時這些表格是空的（大戶持倉集保資料不受影響，TWSE/TPEx 都有）。

**4. `screener/institutional.py::scan_institutional()` docstring 單位標錯**
- docstring 寫「元」，但 `institutional` 表欄位實際單位是「股」（`_parse_num(row[4])` 直接存 T86 的買賣超股數）。目前沒人帶這幾個門檻參數，暫無實際影響，改成文件正確而已。

### 資料來源相關（如有異動）
- 上市資料（TWSE）：無邏輯改動，三大法人/融資融券本來就只有 TWSE
- 上櫃資料（FinMind）：**未處理**，見下方「特別注意」

### 請 Debugger 驗證
- [ ] `_backfill_shareholder` 修好順序後，實際跑 `--backfill-shareholder` 多週，確認 `shareholder` 表 `week_chg`/`streak` 方向正確（越新週 streak 應該累加，不是遞減）
- [ ] Section 5 族群外資買超比例，修復前後數字對照幾個上櫃佔比高的族群（例如「資通訊/工業電腦」），確認比例有明顯回升且合理
- [ ] 上市/上櫃資料來源沒有混用（這次改動本身是在修正混用，不是新增混用）
- [ ] 沒有影響其他模組（`universe` 這個 DataFrame 多帶一欄 `exchange`，確認沒有其他下游用到同名變數但欄位數量寫死的地方壞掉）

### 特別注意
- **範圍縮小說明**：這次掃描還發現一個更大的結構性缺口——三大法人（institutional）完全沒有上櫃資料來源，且 `scrapers/chips.py::fetch_margin`/`fetch_margin_all_today`（FinMind 版融資融券，理論上可以覆蓋上櫃）目前是死碼，沒有任何地方呼叫。這次只先修「用現有資料算出正確結果」（分母排除上櫃），**沒有**去接上 FinMind 補上櫃資料——因為那牽涉到：(a) FinMind 每日 600 次配額怎麼跟其他既有的抓取工作分配、(b) 三大法人的上櫃對應資料源要另外研究（FinMind 有沒有涵蓋上櫃的三大法人 dataset 還沒查證，融資融券已經有現成函式但沒接）。這塊如果要做是新功能規模，需要先 brainstorm 再動工，這次先不做。
- `bug-reports.md` 的「三大法人完全沒有上櫃來源」那則會保留在 open 狀態，不勾掉，等 Cody 決定要不要做這塊。

---

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
