## [2026-07-02] TWSE 封鎖偵測 + 熔斷機制 + TPEx 回補修正

### 改了什麼
- 異動檔案：`scrapers/backfill.py`, `scrapers/chips.py`, `main.py`, `tests/test_backfill.py`, `export/html_generator.py`, `.gitignore`, `.env`（新增，未進 git）, `.env.example`, `requirements.txt`
- 邏輯說明：
  - `backfill.py`：新增 `_looks_like_twse_block()` 偵測 TWSE 資安擋頁（307 + 非 JSON content-type），區別於合法的「該月無資料」回應。`_fetch_stock_months()` 加上跨 thread 共用的 `stop_event`，偵測到封鎖就讓所有 thread 立刻停止送新請求。
  - `backfill_twse_monthly()`：清空舊 CSV（`clean=True`）的動作改成只有在 Phase 1（TWSE）沒被封鎖時才執行，避免用不完整資料覆蓋掉現有歷史；Phase 2（TPEx via FinMind）改成跟 Phase 1 是否被封鎖脫鉤，一律照跑（FinMind 是不同服務，不受 TWSE 擋頁影響）。
  - `chips.py`：`fetch_institutional`（T86）、`fetch_margin_all_twse`（MI_MARGN）都加上同樣的擋頁偵測，新增 `TWSEBlockedError`（繼承 `RuntimeError`，不是 `ValueError`，避免被原本「今日尚未發布」的例外處理誤吞）；T86 補上原本缺少的 `headers`/`verify=False`。
  - `main.py`：`backfill_twse()`（`--backfill-twse` CLI）原本沒傳 `exchange_map`/`finmind_token` 給 `backfill_twse_monthly()`，導致 TPEx 股票全部被誤判走 TWSE-only 路徑、永遠補不到資料且不報錯——已修正為跟 `_full_rebuild()` 一致的呼叫方式。三大法人/融資融券的例外處理分開 `TWSEBlockedError`（記警告）跟 `ValueError`（正常 fallback 抓前一交易日）。
  - `html_generator.py`：修正 modal 裡外資/投信籌碼數字忘記除以 1000 的顯示 bug（股→張換算）；個股排排站表格、子族群 mini-card 字體放大兩輪。
  - FinMind token 從硬編碼搬到 `.env`（`python-dotenv`），`.gitignore` 加 `.env`；舊 token 已確認外洩在 public repo git history（commit `e993e3f`），已請 Cody 重新產生新 token 並更新。
  - 刪除確定沒人用的死碼：`_fetch_tpex_all_days`、`_fetch_twse_one_day`、`_fetch_twse_all_days` 及相關常數。
  - `tests/test_backfill.py`：原本 mock 的是舊版函式（`_fetch_twse_all_days`），沒攔到現在實際在跑的 `_fetch_stock_months`，導致每次跑測試都會打真實 TWSE API——已修正 mock 對象，並新增封鎖情境、TPEx 不受連累情境的測試。

### 資料來源相關（如有異動）
- 上市資料（TWSE）：STOCK_DAY（Phase 1 逐股月別）、T86（三大法人）、MI_MARGN（融資融券）都補上封鎖偵測，邏輯沒變，只是失敗時處理方式不同
- 上櫃資料（FinMind）：`--backfill-twse` 這個 CLI 路徑原本完全沒有補到 TPEx 歷史資料（silent bug），現在修正。已用 FinMind API 直接驗證過歷史資料本來就存在（3213 抓到 265 筆回溯至 2025-06-02），純粹是回補流程的問題

### 請 Debugger 驗證
- [ ] 主要功能邏輯正確（stop_event 熔斷、TPEx 脫鉤、--backfill-twse 修正）
- [ ] 上市/上櫃資料來源沒有混用
- [ ] 沒有影響其他模組
- [ ] 實際跑一次 `python main.py --full-rebuild --months 19 --workers 2`，確認 TWSE 跟 TPEx 歷史資料都補齊到位（TWSE 應回溯到 2025-06-02、TPEx 現在應該可以補到同樣深度）

### 特別注意
- 已 commit：`6993d36`（跟下面的 crash 修復合併成同一個 commit）
- FinMind token 已換新，`.env` 沒有進 git（正確行為）
- 前端 UI 重新設計（React + Vite，index.html 優先）目前在 brainstorming 階段，還沒開始寫程式碼，跟這批 bug fix 是分開的任務

---

## [2026-07-02] 修復 Debugger 回報：`_merge_into_csv` 寫檔未處理 PermissionError 導致 full-rebuild crash

### 改了什麼
- 異動檔案：`scrapers/backfill.py`
- 邏輯說明：
  - `_merge_into_csv()` 的 `merged.to_csv(...)` 原本沒有 try/except，一旦目標 CSV 被鎖定（Debugger 實測是 `data/daily_prices/2025-06-02.csv`，懷疑是 OneDrive 同步中鎖檔，因為專案路徑在 `Desktop` 底下）就會拋出未攔截的 `PermissionError`，讓整個 `backfill_twse_monthly` 的寫入迴圈中斷，導致 `--full-rebuild` 整個 process crash。
  - 這次實際發生的狀況：Phase 1（TWSE）因封鎖只成功 4/515 支，Phase 2（FinMind）正常抓完 524/525 支（花掉當日 FinMind 免費額度），但因為所有資料先存在記憶體 `day_rows`、最後才一次性依日期排序寫檔，寫到某一天鎖住的檔案時直接 crash，524 支好不容易抓到的 TPEx 資料一筆都沒寫進去。
  - 修法：比照同一支函式裡「清除舊 CSV」那段本來就有的 `except PermissionError` 容錯模式，在 `to_csv` 外加 `try/except OSError`（比 `PermissionError` 更廣，涵蓋其他鎖檔/IO 類錯誤），失敗時記錄 warning 並回傳 `False`（跳過該日期），讓迴圈可以繼續處理其他日期，不會整批賠光。

### 資料來源相關（如有異動）
- 無（純粹是寫檔階段的例外處理，不影響 TWSE/FinMind 資料抓取邏輯本身）

### 請 Debugger 驗證
- [ ] `_merge_into_csv` 在檔案鎖定時會跳過該日期並記錄 warning，不會讓整個 process crash
- [ ] 其他日期的 CSV 仍正常寫入
- [ ] 建議之後重跑 `--full-rebuild` 前先確認 `data/daily_prices` 是否在 OneDrive 同步中，或暫停同步

### 特別注意
- Debugger 報告裡另外建議「Phase 2 邊抓邊寫」以降低單點失敗的損失範圍——這次先只修「crash」本身（try/except），沒有做邊抓邊寫的架構改動，因為範圍較大，先確認這次的最小修復夠不夠用
- 已 commit：`6993d36`

---

## [2026-07-02] 修復 Debugger 高優先級回報：`scan_volume_turnover` 歷史資料不足時算出誤導性量倍數

### 改了什麼
- 異動檔案：`screener/signals.py`、`tests/test_signals.py`（新增）
- 邏輯說明：
  - 根本原因（Debugger 查出來的，不是這次改動造成）：TWSE 逐股歷史回補持續被 IP 封鎖，515 支 TWSE 股票裡 509 支（98.8%）在 DB 裡只有 2 筆資料（一筆錨點日 2025-06-02、一筆今天）。`scan_volume_turnover()` 的 lookback 窗口檢查原本是 `if len(window) < 2: continue`，門檻太低——只有 2 筆資料也會通過檢查，導致「今日量 / 均量」變成「今天 vs 一年多前隨機一天」的無意義比值，卻被當成正常訊號輸出（同一天兩次執行結果不一致：5 檔 vs 3 檔，就是這樣來的）。
  - 修法：把門檻從 `< 2` 提高到 `< _MIN_WINDOW_DAYS`（新增常數，設 20），歷史資料不足 20 筆的股票直接跳過，不產生訊號，而不是用統計上沒有意義的資料算出一個看起來正常、實際上是雜訊的量倍數。
  - 新增 `tests/test_signals.py`：驗證只有 2 筆資料（錨點日+今天）的股票不會產生訊號、有 25 筆以上歷史資料且符合三條件的股票會正常產生訊號。

### 資料來源相關（如有異動）
- 上市資料（TWSE）：這個修復不解決「TWSE 歷史資料補不進來」的根本問題（那個要看 TWSE 封鎖何時解除、或評估要不要換抓取策略），只是讓資料不足時「優雅跳過」而不是「算出誤導性訊號」

### 請 Debugger 驗證
- [ ] `scan_volume_turnover` 對歷史資料 <20 筆的股票會跳過，不產生訊號
- [ ] 歷史資料充足且符合三條件的股票仍正常產生訊號（`tests/test_signals.py` 兩個測試案例）
- [ ] 確認這次同一天重複執行結果應該要一致了（不會再出現 3 檔 vs 5 檔這種因為歷史資料忽多忽少造成的不一致）

### 特別注意
- **這次沒動的部分**：Debugger 報告裡提到同樣的「歷史窗口不足」問題可能也影響 `calc_cumulative_meta`（3d/5d/7d 累積漲跌 badge）、`calc_meta_signals` 的量能異常 badge（量↑2.5x）、`screener/patterns.py` 的 Weinstein Stage 2 拐點偵測——這幾個是「🟡 建議改善」非阻擋項，這次只修了「🔴 需立刻修」的 `scan_volume_turnover`。這幾個之後應該要individually 檢查是否有一樣的資料不足問題，範圍較大，建議另開任務處理，不要漏掉
- 這個修復還沒 commit，等這批一起處理

---

## [2026-07-02] 新增 `--backfill-yf`：救回被誤刪的 Yahoo Finance 補齊功能（改良版）

### 改了什麼
- 異動檔案：`scrapers/backfill.py`、`main.py`
- 邏輯說明：
  - **背景**：追查 Cody 的記憶跟 git history 發現，今早 commit `d976dbb` 加過一個 `backfill_yfinance()`（不需要 token、TWSE+TPEx 都支援），但同一天稍晚 commit `2620c3a`（一次很大的重構，換成現在這套 TWSE 官方 API + FinMind 架構）把它整個刪掉了，沒人特別注意到。這個被刪的版本用 `yf.download()` 批次抓，Cody 確認這版「不行」（容易被 Yahoo 限流）。
  - Cody 提供了另一支個人腳本 `downloader_tw.py`（丟在專案根目錄，未整合進 pipeline），裡面驗證過一套有效的防封鎖手法：`Ticker.history()` 逐支抓（不是批次 `yf.download()`）+ 每支之間隨機延遲（0.5~1.2秒）+ 失敗重試退避（3~7秒）+ 每 100 支額外暫停（5~10秒）+ 降並發（3）。
  - 這次**沒有直接復原被刪的版本**（那版已知不行），也**沒有直接用 `downloader_tw.py`**（它的資料存法是一支股票一個檔案 `data/tw-share/dayK/{ticker}.csv`，跟現有 pipeline 用的「一天一個檔案」`data/daily_prices/YYYY-MM-DD.csv` 格式不相容），而是把 `downloader_tw.py` 驗證過的防封鎖手法，重新實作成一個新函式 `backfill_yfinance()`，輸出格式對齊現有的 `_merge_into_csv()` / `data/daily_prices/*.csv`，可以正常跟 DuckDB import、族群計算等既有邏輯接上。
  - 同時刪掉了原本就沒人呼叫的死碼 `_fetch_yfinance_history()`（批次版、只支援 TPEx，之前就已經沒有任何呼叫端在用）。
  - `main.py` 新增 `backfill_yf()` wrapper（同 `backfill_twse()` 的寫法）+ CLI flag `--backfill-yf MONTHS`（沿用既有的 `--workers`）。
  - **已驗證**：直接呼叫 `_fetch_yfinance_one_stock('2330', '2330.TW', ...)` 單股測試，成功抓到 8 筆 6/20~7/1 真實資料，沒有被限流擋掉（用 `Ticker.history()` 逐支抓，跟之前被限流的 `yf.download()` 批次抓不是同一條路徑）。

### 資料來源相關（如有異動）
- 這是**第三條**取得歷史行情的路徑，跟現有的「TWSE 官方 API（Phase 1）+ FinMind（Phase 2）」並存，不互相影響，也沒有修改 `backfill_twse_monthly()` 本身
- TWSE 用 `{sid}.TW`，TPEx 用 `{sid}.TWO`，對應規則跟 `exchange_map`（來自 `stock_universe.csv` 的 `exchange` 欄）一致

### 請 Debugger 驗證
- [ ] `backfill_yfinance()` 邏輯正確（逐支抓、隨機延遲、重試退避、每 100 支暫停）
- [ ] `_merge_into_csv` 呼叫方式跟 `backfill_twse_monthly()` 一致，輸出格式相容
- [ ] `--backfill-yf` CLI 有正確接上（`main.py --help` 看得到）
- [ ] 死碼 `_fetch_yfinance_history()` 確認移除前沒有其他呼叫者
- [ ] 建議 Cody 實際跑一次 `python main.py --backfill-yf 19 --workers 3`，觀察是否能真正把 TWSE 歷史資料補起來（單股測試通過，但完整跑 1040 支股票的長時間穩定性還沒驗證過）

### 特別注意
- 這個修復還沒 commit，等這批一起處理
- `downloader_tw.py` 本身沒有被刪除或修改，還留在專案根目錄（未整合進 pipeline，Cody 自己的參考腳本）

---

## [2026-07-02] 修復 Debugger 回報：`backfill_yfinance()` 三個問題（clean 資料遺失風險、暫停機制無效、第一天假 0 值）

### 改了什麼
- 異動檔案：`scrapers/backfill.py`、`tests/test_backfill.py`
- 邏輯說明：
  - **🔴 clean 資料遺失風險（已修）**：跟稍早 `backfill_twse_monthly()` 修過的同一類 bug——`clean=True` 原本無條件執行。現在改成：算出 `ok/total` 成功率，低於 `_YFINANCE_MIN_SUCCESS_RATE = 0.5`（疑似被限流）就強制跳過清空舊 CSV，記錄 `logger.error`。跟 `backfill_twse_monthly()` 用 `stop_event` 判斷不同（yfinance 這邊沒有明確的「被擋」訊號，失敗是靜默回傳空 list），改用成功率門檻當替代判斷依據。
  - **🟡 暫停機制無效（已修）**：原本「每 100 支暫停 5-10 秒」寫在主執行緒的 `as_completed` 迴圈裡，`ThreadPoolExecutor` 一次把全部任務 submit 下去，worker 不會被主執行緒的 `time.sleep` 卡住，暫停完全沒作用。改成用跨 thread 共用的 `pause_state = {"lock": threading.Lock(), "count": 0}` 傳進 `_fetch_yfinance_one_stock()`，每支股票完成時自己在 lock 保護下遞增計數，滿 `pause_every`（預設100）的那個 worker 自己真的睡 5-10 秒，暫停才會真正卡住某個 worker 的下一次請求。
  - **🟡 第一天假 0 值（已修）**：原本抓取範圍就是 `start_date ~ end_date`，區間第一天沒有更早資料可算漲跌，`prev = close`（自己比自己）永遠得到 `change_pct=0`，看起來像正常數值但其實是缺值。改成往前多抓 5 個日曆天當緩衝（`buffer_start`），用緩衝天數算出區間第一天的真實漲跌，緩衝天數本身不放進輸出。已用真實資料驗證：`start=2026-06-26` 第一筆正確顯示 `change_pct=-2.09%`（6/25→6/26 真實跌幅），不再是假的 0。
  - **exchange_map 預設方向調整**：原本「非 TPEx 一律當 TWSE」，改成跟 `backfill_twse_monthly()` 的分類慣例一致——「明確標記 TWSE 才算 TWSE，其餘（含未知代號）一律當非 TWSE（.TWO）」。
  - 新增 5 個測試（`tests/test_backfill.py`）：緩衝天數不進輸出+第一天算出真實漲跌、pause_state 滿額真的暫停、正常寫入、**成功率低時跳過清空**（對應 Debugger 建議的最優先測試案例）、ticker 後綴對應規則。

### 資料來源相關（如有異動）
- 無新資料來源，純粹是既有 `backfill_yfinance()` 的邏輯修正

### 請 Debugger 驗證
- [ ] clean 成功率門檻（50%）判斷邏輯正確，且對應到新測試 `test_backfill_yfinance_skips_clean_when_success_rate_low`
- [ ] pause_state 真的讓 worker 暫停（不是只在主執行緒空轉），對應測試 `test_fetch_yfinance_one_stock_pauses_every_n_completions`
- [ ] 第一天 change_pct 不再是假 0，對應測試 `test_fetch_yfinance_one_stock_skips_buffer_day_fake_zero`（已用真實 yfinance 資料額外驗證過，不只是 mock）
- [ ] exchange_map 預設方向調整後，跟 `backfill_twse_monthly()` 的分類慣例是否真的一致

### 特別注意
- 這個修復還沒 commit
- 4 項 Debugger 建議的測試案例裡，「exchange_map 隱性風險」那項這次順手一起修了（改成跟既有分類慣例一致），其餘 3 項（clean、暫停、假0值）都有對應測試

---

## [2026-07-02] 修復 Debugger CRITICAL 回報：`export/html_generator.py` `UnboundLocalError: cannot access local variable 'pd'` + 順手修正股票代號誤判 bug

### 改了什麼
- 異動檔案：`export/html_generator.py`、`scrapers/moneydj.py`、`tests/test_moneydj.py`、`data/stock_universe.csv`
- 邏輯說明：
  - **CRITICAL（Debugger 回報）**：`_stock_card_html()`、`_stock_table()`、`_meta_stock_cards()` 三個函式內都各自有一行多餘的區域 `import pandas as pd`（原第 196、331、515 行），模組頂部第 2 行本來就有 `import pandas as pd` 了。因為 Python 的作用域規則（函式內任何一處對某名稱賦值，包含區域 import，該名稱整個函式作用域內都視為區域變數），只要 `chips_df` 是空的、觸發 `chips_map = ... else pd.DataFrame()` 這個分支，就會在區域 `import pandas as pd` 那行執行到之前先踩到 `UnboundLocalError`，讓 `generate_html()` 整個中斷（`--realtime` 盤中三大法人/融資融券資料還沒公布時最容易踩到，但只要 `chips_df` 是空的，不限 `--realtime` 都會炸）。
  - 修法：三個函式內的區域 `import pandas as pd` 全部刪除，直接用模組層級已 import 好的 `pd`。純刪除，沒有動邏輯。
  - **順手修正（跟這次回報無關，是 Cody 貼截圖發現的另一個問題）**：`data/stock_universe.csv` 第 640 行 `674191,APP*-KY,TPEx,...` 代號錯誤（多打了 91），Cody 截圖確認 APP*-KY 實際代號是 4 碼 `6741`（目前正常交易中，60.6 +0.17%），不是 6 碼、也沒有下市——先前 debugger 回報「yfinance 查無 674191、疑似下市」其實是代號本身就是錯的，根本沒有 674191 這支股票。
    - 追查根本原因：`scrapers/moneydj.py::_parse_stock_table()` 用來從 MoneyDJ 產業分類頁面解析代號/名稱的正則式原本是 `r'^(\d{4,6})(.*)$'`，太寬鬆——當網頁該列的代號跟名稱之間沒有分隔符（例如 cell 文字是 `674191APP*-KY`，其中 `91` 疑似是名稱前綴的雜訊字元、不是代號的一部分），正則會貪婪吃掉前 6 碼當代號，把 `91` 誤併進代號、擠出正確的 4 碼 `6741`。
    - 已確認 `stock_universe.csv` 目前另外還有 4 支合法的 6 碼代號（`911868`／`912000`／`910861`／`911608`，都是 TDR 台灣存託憑證，固定以 `91` 開頭），所以不能簡單改成「只認 4 碼」，改成 `r'^(91\d{4}|\d{4})(.*)$'`——明確比對「91 開頭的 6 碼 TDR」或「一般 4 碼股票」兩種合法格式，其餘一律當 4 碼處理，不會再貪婪多吃。
    - 新增兩個測試（`tests/test_moneydj.py`）：驗證代號名稱無分隔符時會正確停在 4 碼（不會重演 674191 這個 bug）、TDR 的 6 碼代號不會被截斷。
    - `data/stock_universe.csv` 直接把 `674191` 改成 `6741`，已確認 `6741` 沒有跟其他既有代號重複。
  - `data/sectors/industry_sectors.csv`、`data/changes/changes_log.csv` 裡也有幾筆歷史 `674191` 記錄（scraper 產生的歷史資料/log），這次沒有動——屬於歷史留存資料，下次重新跑 sector 抓取應該會用修正後的正則式產生正確代號，舊記錄不影響現在的功能

### 資料來源相關（如有異動）
- 上市資料（TWSE）：無異動
- 上櫃資料（TPEx）：`6741`（APP*-KY）代號修正，這支股票本來就是 TPEx，分類沒有錯，只有代號數字打錯

### 請 Debugger 驗證
- [ ] `UnboundLocalError` 修復：`chips_df` 為空（例如盤中三大法人/融資融券還沒公布）時 `_meta_stock_cards()`／`_stock_table()`／`_stock_card_html()` 不會再 crash，`generate_html()` 能正常跑完
- [ ] 確認三處刪除的區域 import 沒有遺漏（`grep -n "import pandas as pd" export/html_generator.py` 應該只剩模組頂部第 2 行）
- [ ] `scrapers/moneydj.py` 正則式修正：`test_scrape_industry_sectors_stops_at_4_digit_code`、`test_scrape_industry_sectors_keeps_6_digit_tdr_code` 兩個新測試邏輯正確
- [ ] `stock_universe.csv` 674191 → 6741 修正後，`--backfill-yf` 之類的流程會不會正常抓到這支股票的資料了（之前是因為代號錯誤查無此代號，不是下市）

### 特別注意
- 已 commit（`8e61d71`）並 push 到 origin/master
- 這次「順手修正」的 stock_universe.csv 代號 bug 不在 Debugger 這次回報範圍內，是 Cody 直接貼截圖發現的，之後如果要追溯可以參考這則記錄
- 建議之後找機會重新跑一次 sector 抓取（`scrape_industry_sectors`），確認正則式修正後不會再產生類似的代號污染，並可以順便清一下 `data/sectors/industry_sectors.csv`／`changes_log.csv` 裡的舊錯誤記錄（非急迫）

---

## [2026-07-02] 修復 Cody 實測回報：`--realtime` 執行後首頁日期被切回前一天

### 改了什麼
- 異動檔案：`main.py`
- 邏輯說明：
  - **背景**：Cody 跑 `python main.py --realtime`（13:05），log 顯示完全正常、`docs/index.html` 正確產生並 push（commit `38f5afa`，日期 2026-07-02）。但 5 分鐘後（13:10）又有一次執行，把 `docs/index.html` 的日期切回 2026-07-01（commit `216c332`），蓋掉剛才正確的版本。整個過程沒有任何錯誤訊息，純粹是邏輯誤判。
  - **根本原因**：`run()` 第 328-344 行有一段「防重複寫入」檢查——比對這次抓到的探測股（2330）價格跟前一交易日收盤價是否相同，相同就判定「市場尚未更新」，把 `trade_date` 切回前一天、不寫入今日資料。這段邏輯是設計給**批次收盤模式**（`fetch_prices_for_stocks`）用的，用來偵測「TWSE 官方收盤資料還沒公布」，但原本寫法沒有排除 `--realtime` 模式，兩種模式共用同一段判斷。
    `--realtime` 抓的是當下即時快照，即使探測股價格剛好等於前一天收盤（可能尚未成交、API 延遲等情況），仍然是「今天當下」合法的即時資料，不代表「市場沒更新」，不應該被切回前一天。
  - 修法：把這段檢查限制成 `if not realtime and prices_df is not None and not prices_df.empty:`，`--realtime` 模式完全跳過這道防呆，永遠信任自己抓到的即時快照、用今天的日期寫入。批次模式（`--realtime` 未指定）行為不變。

### 資料來源相關（如有異動）
- 無資料來源變更，純粹是 `--realtime` 模式下 `trade_date` 判斷邏輯的修正

### 請 Debugger／Cody 驗證
- [ ] 連續跑兩次以上 `--realtime`（間隔幾分鐘），確認不會再把 `docs/index.html` 的日期切回前一天
- [ ] 批次模式（不加 `--realtime`）在 TWSE 官方資料還沒公布時，仍然會正確切換回前一交易日（沒有被這次改動影響到）
- [ ] 確認這次修法沒有影響 `writer.write_daily_prices()` 之後的下游流程（族群績效、HTML 產生等），`prices_are_new` 在 realtime 模式下永遠是 `True`，行為符合預期

### 特別注意
- 還沒 commit，Cody 說要自己先驗證
- 額外發現（非 bug，記錄一下）：`main.py::_push_html()` 執行 `git commit` 時是提交「當下所有已 staged 的檔案」，不是只提交它自己 `git add` 的那三個 docs/*.html。如果之前手動 `git add` 過其他檔案但還沒 commit，下次跑 `main.py`（會自動收盤/即時 commit+push）時會被一起帶進去，commit message 卻是自動產生的「update: sector performance {date}」，訊息跟實際內容對不上。這次意外把 4 個角色/協作 md 檔案（`CLAUDE-developer.md` 等）跟著 sector performance 一起進了 commit `4dadc23`，就是這樣發生的。不算 bug，但操作上要注意：手動 `git add` 之後如果不馬上 commit，最好記得跑 main.py 前先確認 staging area 是乾淨的。
