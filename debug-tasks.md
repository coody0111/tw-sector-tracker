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
- 已 commit：`f4f3795`。後續 `--backfill-yf` 全量實跑已把 TWSE 歷史資料補到中位數 360 筆/檔，這道門檻理論上不太會再被觸發，但邏輯本身**還沒看到 Debugger 明確驗證通過的回報**，Cody 說還要再驗證一次

---

## [2026-07-02] 修復 Cody 實測回報：`python main.py` 跑完網站沒真的更新（日期又被誤切回前一天）

### 改了什麼
- 異動檔案：`scrapers/twse.py`、`main.py`、`tests/test_twse.py`
- 邏輯說明（兩個 bug 疊加才會發生，用 `logs/run.log` 14:58 那次執行的完整證據鏈追出來的）：
  - **Bug A（觸發點）**：`scrapers/twse.py::fetch_daily_prices()`（每日批次抓價用的路徑，不是 backfill 那條）沒有 TWSE 封鎖偵測。原本邏輯是「`resp.json()` 解析失敗就一律當成瀏覽器 UA 觸發的合法 CSV 回應」，但這次失敗其實是 TWSE 擋頁（HTML），被硬塞進 `pd.read_csv()` 解析，噴出 `Error tokenizing data. C error: Expected 1 fields in line 7, saw 2`，導致 TWSE 515 支資料整批消失、只剩 TPEx。
    修法：非 JSON 回應時，先檢查 content-type 是不是 html（是的話直接判定擋頁，重用 `scrapers/chips.py` 既有的 `TWSEBlockedError`，不重工定義新類別）；content-type 沒標 html 但 `pd.read_csv` 還是解析失敗（`pd.errors.ParserError`），同樣視為擋頁，不讓原始的 pandas 錯誤原封不動噴出去看起來像無關的資料格式 bug。
  - **Bug B（真正讓網站「沒更新」的原因）**：`main.py` 的「市場尚未更新」防呆檢查（`run()` 第 332-347 行附近）原本挑探測股是 `probe_id = "2330" if "2330" in prices_df["stock_id"].values else prices_df.iloc[0]["stock_id"]`——因為 Bug A 讓 TWSE（含 2330）整批消失，探測股退而求其次選了 `prices_df.iloc[0]`，一支隨機的 TPEx 股票，剛好那支股價跟昨天收盤一樣，就被誤判成「市場沒更新」，把 `trade_date` 切回前一天，將今天真實抓到的 TPEx 資料當成「昨天」的資料發布上網。
    修法：拿掉「退而求其次」的替代股票邏輯，只有 2330 真的在這次抓到的資料裡才執行這個防呆檢查；2330 不在的話（代表 TWSE 資料本身不完整）直接跳過整個檢查、記錄 warning，不再用任意股票的巧合來判斷「市場是否更新」。
  - 新增 `tests/test_twse.py` 三個測試：擋頁（html content-type）正確拋 `TWSEBlockedError`；content-type 沒標 html 但內容解析失敗（重現真實案例的 `ParserError` 情境）也拋 `TWSEBlockedError`；合法的非 JSON CSV 回應仍能正常解析（避免修過頭，把合法情況也擋掉）。
- **這次沒動測試的部分**：`main.py::run()` 是大型函式，沒有既有的 `test_main.py` 測試基礎設施（抓價/寫檔/git push 全部耦合在一起），要為 Bug B 這段邏輯加測試需要 mock 掉整個流程，超出這次修復範圍，沒有新增自動化測試——邏輯改動後純粹是條件判斷（`"2330" in ...`），建議 Debugger 用手動情境驗證（模擬 `prices_df` 缺少 2330，確認不會誤切日期）。

### 資料來源相關（如有異動）
- 上市資料（TWSE）：`fetch_daily_prices()` 現在能正確區分「TWSE 擋頁」跟「合法 CSV 回應」跟「合法 JSON 回應」三種情況，擋頁會清楚拋 `TWSEBlockedError`（在 log 裡看得出來是封鎖，不是別的資料格式 bug）
- 上櫃資料（TPEx）：無異動，這次修復完全在 TWSE 抓取路徑跟防呆檢查邏輯

### 請 Debugger 驗證
- [ ] `tests/test_twse.py` 三個新測試邏輯正確（html 擋頁拋錯、非 html 但解析失敗也拋錯、合法 CSV 正常解析）
- [ ] `main.py` 的「市場尚未更新」檢查：手動模擬 `prices_df` 不含 2330（例如只塞 TPEx 資料）時，確認不會誤切 `trade_date`，且會記錄 warning log
- [ ] 確認 `main.py` 正常情境（TWSE+TPEx 都抓到、2330 在資料裡）下，這段防呆檢查行為跟修復前一致，沒有破壞原本「TWSE 官方收盤資料還沒公布」的偵測能力
- [ ] 實際找一個時段重跑 `python main.py`（背景沒有其他程序同時打 TWSE），確認網站日期正確更新，不會再出現 commit 訊息日期跟實際執行日期對不上的情況

### 特別注意
- 觸發條件：這次是背景同時在跑 `--full-rebuild`／`--backfill-twse`，跟 `main.py` 自己的每日抓價同時打 TWSE，很可能是背景那個程序把 IP 打到被封鎖，`main.py` 自己這次抓價才會撞上擋頁。**建議之後不要讓 `--backfill-twse`／`--full-rebuild` 跟每日排程的 `python main.py` 同時跑**，這是操作面的提醒，不是這次程式修的範圍。
- 現狀：`docs/index.html` 目前還停留在被誤切的狀態（commit 訊息寫「2026-07-01」，但實際是 2026-07-02 14:58 執行產生的），這次修復不會自動回補——需要背景的 `--full-rebuild` 跑完之後，再重新跑一次 `python main.py`（或等下一次排程），才會用修好的邏輯重新產生正確日期的頁面
- 這個修復還沒 commit
