## [2026-07-02] 報告 - full-rebuild crash 分析（`python main.py --full-rebuild --months 19 --workers 2`）

### 🔴 程式問題（需立刻修）
- 問題：`_merge_into_csv()`（scrapers/backfill.py 第 64-88 行，實際拋錯在第 87 行 `merged.to_csv(...)`）沒有處理檔案被鎖定時的例外，導致整個 `--full-rebuild` 在資料都抓完、只差寫檔的最後階段直接 crash。
  重現方式：`python main.py --full-rebuild --months 19 --workers 2`。Phase 1（TWSE）因 IP 被封鎖只成功 4/515 支，Phase 2（FinMind）正常跑完 524/525 支（耗時約 7 分鐘）。寫入階段照日期排序逐檔 `to_csv`，寫到 `data/daily_prices/2025-06-02.csv` 時該檔案被其他程序鎖定，拋出未被攔截的 `PermissionError`，整個 process 中止。
  相關 log／traceback：
  ```
  File "scrapers\backfill.py", line 468, in backfill_twse_monthly
      if _merge_into_csv(output_path / f"{d_str}.csv", rows, overwrite=True):
  File "scrapers\backfill.py", line 84 (WIP)/87 (committed), in _merge_into_csv
      merged.to_csv(path, index=False, encoding="utf-8-sig")
  PermissionError: [Errno 13] Permission denied: 'data\daily_prices\2025-06-02.csv'
  ```
  影響：
  - Phase 2 FinMind 花約 7 分鐘、消耗掉當日 FinMind 免費額度（600 次/日）抓到的 524 支資料，因為是先全部存在記憶體 `day_rows`、最後才一次性排序寫檔，中途 crash 就整批遺失，一筆都沒寫進 CSV。
  - Step 2（`reimport_db` 重建 DuckDB）完全沒有機會執行。
  - 值得注意的不一致：同一支函式在「清除舊 CSV」那段（uncommitted 版 backfill.py 第 454-464 行）已經對 `f.unlink()` 加了 `except PermissionError` 容錯並記錄「跳過 %d 個（被鎖定）」，代表 Developer 已經知道這個資料夾會有檔案被鎖（本機路徑在 `Desktop` 底下，很可能是 OneDrive 同步造成），但同一種例外在後面真正「寫入」的地方（`to_csv`）卻沒有比照處理，是遺漏。
  - 補充：這是 uncommitted 的 WIP 程式碼（developer 資料夾 `tw-sector-tracker` 有大量未 commit 的改動：backfill.py、chips.py、main.py、html_generator.py 等），debug 分支當時對齊的 commit（`e471e74`）裡還是舊版邏輯（沒有 exchange_map 預分類、沒有 TWSE 封鎖偵測），此次 review 的是 Developer 本機正在跑的最新版本。

### 🟡 建議改善
- `_merge_into_csv` 對 `merged.to_csv(...)` 加 try/except（`PermissionError` 或更廣的 `OSError`），比照清除舊 CSV 那段的做法：記錄警告並跳過該日期，不要讓整個 batch crash。
- 目前架構是「全部抓完、最後才一次性排序寫入」，任何一檔寫入失敗就會賠上整批已抓資料。建議改成邊抓邊寫（至少 Phase 2 FinMind 部分，因為它本來就有每日配額限制、重跑成本最高），降低單點失敗的損失範圍。
- 確認 `data/daily_prices` 是否在 OneDrive／雲端同步範圍內（路徑在 `Desktop` 下很可能是）；若是，建議把長時間執行的 batch 輸出目錄移出同步範圍，或執行前暫停同步，避免檔案被鎖定。

### ✅ 驗證通過
- Phase 1 TWSE 封鎖偵測邏輯本身正確：`_looks_like_twse_block`／`_check_twse_response` 用 `status_code != 200 or content-type 非 json` 判斷擋頁（307 + text/html），跟合法的「該月無資料」JSON 回應（`stat != "OK"`）區分開，沒有誤判。
- Phase 1 被封鎖不會拖累 Phase 2：FinMind 走獨立服務，`stop_event` 只影響 TWSE thread，TPEx 524/525 支正常抓完，邏輯沒有交叉污染。
- exchange_map 預分類數字對得上：TWSE 515 + TPEx 525 = 1040，與 `stock_universe.csv` 股票數一致，沒有發現分類錯誤或遺漏股票的跡象。

### 🔒 額外發現（非本次任務範圍，但需記錄）
- `scrapers/chips.py` 當時 commit 歷史（含 HEAD）裡有一組寫死的 FinMind API token，此 repo 遠端為 public GitHub（`coody0111/tw-sector-tracker`），token 過去曾公開曝光。使用者已確認該 token 已更新/失效，風險已解除。Developer 已在 uncommitted 改動裡把 token 換成讀 `os.environ.get("FINMIND_TOKEN", "")`，方向正確。

### 結論
- [x] 需要修改後再確認 — `_merge_into_csv` 補上寫檔例外處理後，才建議再重跑 `--full-rebuild`

---

## [2026-07-02] 驗證 - commit 6993d36「TWSE 封鎖偵測 + 熔斷機制 + TPEx 回補修正 + 寫檔例外處理」

### 驗證方式
- 靜態程式碼 review（`git show 6993d36` 完整 diff：scrapers/backfill.py、scrapers/chips.py、main.py、export/html_generator.py、.gitignore、.env.example、requirements.txt）
- 執行測試：`pytest tests/test_backfill.py -v`（7 個測試全過）與全專案 `pytest`（58 個測試，57 過 / 1 失敗，失敗項目為 pre-existing 環境問題，非本次改動造成，詳見下方說明）
- 使用者於 2026-07-02 01:25 左右自行實際執行 `python main.py --full-rebuild --months 19 --workers 2` 進行即時驗證（過程中 Phase 1 TWSE 仍處於 IP 封鎖狀態、Phase 2 FinMind 持續抓取中，觀察 log 進度未見 crash）

### ✅ 驗證通過（對照 debug-tasks.md 的「請 Debugger 驗證」清單）
- **`_merge_into_csv` 寫檔例外處理**：`to_csv(...)` 外層已加上 `try/except OSError`，失敗時 `logger.warning(...)` 並 `return False`（跳過該日期），呼叫端的 for 迴圈會繼續處理下一個日期，不會讓整個 process 中斷。範圍比原報告建議的 `PermissionError` 更廣（用 `OSError`），涵蓋其他鎖檔/IO 類錯誤，合理。
- **stop_event 熔斷機制**：`_fetch_stock_months()` 加上跨 thread 共用的 `stop_event`，偵測到封鎖（`_looks_like_twse_block`）就設起來，其餘 thread 在下一輪迴圈立即 break，不會繼續狂打已被封鎖的 TWSE API。
- **TWSE 封鎖偵測與合法「無資料」回應區分正確**：`_looks_like_twse_block()`／`_check_twse_response()` 用 `status_code != 200 or content-type 非 json` 判斷擋頁（307 + text/html），跟合法 JSON 回應但 `stat != "OK"`（該月無資料/假日）的情況分開處理，順序也對（先檢查擋頁，再解析 JSON、再檢查 stat），沒有誤判風險。
- **Phase 2（TPEx／FinMind）與 Phase 1（TWSE）封鎖脫鉤**：`twse_blocked` 只影響「是否清空舊 CSV」，不影響 Phase 2 是否執行；FinMind 是獨立服務，程式碼沒有交叉污染的痕跡。
- **`--backfill-twse` CLI 修正**：`main.py` 的 `backfill_twse()` 現在會建立 `exchange_map` 並傳入 `finmind_token`，跟 `_full_rebuild()` 呼叫方式一致，修正了原本 TPEx 股票被誤判走 TWSE-only 路徑、永遠補不到資料又不報錯的 silent bug。
- **上市/上櫃資料來源沒有混用**：`chips.py` 的 `TWSEBlockedError`（繼承 `RuntimeError`）跟原本「今日尚未發布」的 `ValueError` 分開處理，`main.py` 的 `_update_chips_db()` 對兩種例外分別處理正確，不會互相誤吞。
- **html_generator.py modal 籌碼數字 /1000 修正**：外資/投信淨買賣超（T86 原始單位是「股」）modal 顯示已改成除以 1000 換算成「張」；融資餘額（MI_MARGN 原始單位本來就是「張」）維持不除，兩處單位處理邏輯自洽，交叉比對其他卡片位置（`_fmt_chips_num` 用 K 為單位、`_fmt_margin` 不換算）沒有發現不一致。
- **FinMind token 移除硬編碼**：`chips.py` 改讀 `os.environ.get("FINMIND_TOKEN", "")`，`.gitignore` 已加 `.env`、新增 `.env.example` 佔位檔，方向正確（舊 token 已由 Cody 確認更新失效，git history 裡的舊字串仍建議之後找機會清掉）。
- **測試補強**：`tests/test_backfill.py` 原本 mock 錯函式（`_fetch_twse_all_days`，已被刪除的死碼）、每次跑測試都會打真實 TWSE API 的問題已修正，改 mock 實際在用的 `_fetch_stock_months`；新增封鎖情境、TPEx 不受連累情境的測試，全數通過。
- **即時驗證（完整跑到底，結果符合預期）**：使用者本機實跑 `--full-rebuild --months 19 --workers 2`。TWSE 仍處於 IP 封鎖狀態（Phase 1 只成功個位數支，行為符合預期、正確跳過清空舊 CSV），FinMind Phase 2 正常跑完 518/525（fail=7，屬正常範圍內失敗率）。**寫入階段再次踩到同一個鎖定檔案 `data/daily_prices/2025-06-02.csv`**（跟原始 bug report 一模一樣的檔案），這次被正確攔截：
  ```
  WARNING scrapers.backfill: 寫入 2025-06-02.csv 失敗（可能被鎖定，例如 OneDrive 同步中）：[Errno 13] Permission denied: 'data\daily_prices\2025-06-02.csv'，跳過該日期
  INFO scrapers.backfill: 補齊完成：寫入/更新 359 日，共 187474 筆
  INFO __main__: Step 1 完成：更新 359 個交易日 CSV
  INFO __main__: === Step 2：清空 DuckDB 並重建 ===
  INFO screener.database: reimport 完成：共 188555 筆
  INFO __main__: === full-rebuild 完成：DuckDB 共 188555 筆 ===
  ```
  沒有 crash，其餘 358 個日期正常寫入，Step 2 DuckDB 重建也正常跑完。這是修復前後最直接的對照：同一個鎖定檔案，修復前讓整個 process 中止、524 支資料全丟；修復後只跳過那一天、其他資料全部保留。確認修復有效。

### 🟡 建議改善（非阻擋項，可後續處理）
- 死碼移除（`_fetch_tpex_all_days`、`_fetch_twse_one_day`、`_fetch_twse_all_days`）已確認在目前程式碼庫內沒有其他呼叫者，清理乾淨。
- 先前報告建議的「Phase 2 邊抓邊寫」架構改動這次沒有做（範圍較大），先確認這次的最小修復（try/except）夠不夠用，之後若還是常常遇到鎖檔問題可以再評估。
- 建議確認 `data/daily_prices` 是否在 OneDrive 同步範圍內，這次跑仍可能再遇到同樣的鎖檔情況（只是現在會被優雅跳過而不是 crash）。

### 已知非本次改動造成的問題
- 全專案 `pytest` 有 1 個失敗：`tests/test_patterns.py::test_scan_patterns_returns_list`，原因是 debug 工作目錄下沒有 `data/screener.db`（`_duckdb.IOException: database does not exist`）。已比對舊 commit（`e471e74`）在同一份 debug 工作目錄下跑一樣會失敗，確認是環境缺少資料庫檔案的既有問題，與本次 commit 無關，不影響本次驗證結論。

### 結論
- [x] 可以繼續下一個任務 — commit `6993d36` 的修復經靜態 review、單元測試、即時執行觀察三方驗證，邏輯正確、沒有發現新問題；上述 pytest 失敗為既有環境問題，非本次改動引入

---

## [2026-07-02] 報告 - 巨量換手訊號同一天兩次結果不同（5 檔 vs 3 檔）：TWSE 歷史資料幾乎全數缺失

### 🔴 數據問題（需立刻修，優先級最高）
- 問題：使用者反映 log 顯示「巨量換手訊號：3 檔」，但網頁報表顯示 5 檔。追查後發現兩者其實都是對的——只是**兩次不同的執行**（同樣掃描 2026-07-01 這天），結果不一致：
  - 舊報表（commit `e471e74`，已 push 過的版本）：5 檔 — 8021、3016、6862、2406、4958
  - 新報表（commit `a920829`，這次 review 過程中重新產生並已 push）：3 檔 — 8021、3016、**8046**（新出現）
  - 兩次都出現的 8021／3016，`change_pct` 完全相同（今天收盤價沒變），但 `vol_multiple`（量倍數）劇烈變動：8021 從 6.6x 掉到 1.7x，3016 從 2.9x 掉到 1.5x（剛好卡在篩選門檻 1.5x 邊緣）。
- 根本原因：`screener/signals.py::scan_volume_turnover()` 的「爆量」「量倍數」判斷依賴 `daily_prices` 裡最近 126 個交易日的歷史窗口（`lookback=126`）。實際查詢目前 DuckDB：
  ```
  TWSE 股票數：515，DB 裡有資料的：515
  中位數每檔僅 2 筆資料（25%/50%/75% 分位數都是 2）
  資料 <=5 筆的 TWSE 股票：509 / 515（98.8%）
  資料 >=100 筆的 TWSE 股票：只有 6 檔
  對照 TPEx：524 檔，中位數 359 筆，最少 96 筆（正常，FinMind 回補成功）
  ```
  也就是說，**515 檔 TWSE 股票裡有 509 檔（98.8%）在資料庫裡只有 2 筆歷史資料**（一筆是很久以前的錨點日期如 2025-06-02，一筆是今天 2026-07-01），根本不是真正的「過去 126 個交易日」視窗。`vol_avg`／`vol_max` 實際上只是「今天」跟「一年多前隨機一天」兩點的平均/最大值，統計上毫無意義。
  這是因為 TWSE 逐股歷史回補（`backfill_twse_monthly` Phase 1）**持續被 TWSE 官網 IP 封鎖**——今天已經連續看到至少 3 次 `--full-rebuild`／`--backfill-twse` 嘗試，每次都在幾秒到幾十秒內就被 307 擋頁擋下，只有極少數（4~6 檔，可能每次還不完全一樣）幸運在被封鎖前抓到資料，其餘 509 檔完全沒有真正的歷史資料可用。
  影響範圍不只 巨量換手 訊號：任何依賴 TWSE 歷史行情窗口的計算都受影響，包括但不限於 `calc_cumulative_meta`（3d/5d/7d 累積漲跌 badge）、量能倍數 badge（`量↑2.5x`）、`screener/patterns.py` 的多頭拐點偵測（Weinstein Stage 2）等——這些數字目前對 98.8% 的 TWSE 個股而言都是用「今天 vs 一年多前一個隨機日期」算出來的，看起來像正常數據，但實際上是雜訊，會誤導使用者的掃盤判斷。這正是 CLAUDE.md 裡最擔心的情況：不會報錯、但給出錯誤結果。
  重現方式：任何時候查詢 `SELECT stock_id, COUNT(*) FROM daily_prices GROUP BY stock_id`，篩選 `exchange == 'TWSE'` 即可看到中位數僅 2 筆。

### 🟡 建議改善
- 這不是這次 commit `6993d36` 造成的（它只是把「封鎖時的處理方式」做對了：偵測到封鎖就不清空舊 CSV、不覆蓋、寫檔失敗會跳過），但也還沒解決「TWSE 歷史資料補不進來」這個更根本的問題——封鎖偵測跟熔斷機制目前的效果是「優雅地什麼都不做」，而不是「成功回補資料」。
- 建議 Developer 評估：(1) TWSE 的 IP 封鎖是否需要換一個抓取策略（降低並發、加大 sleep、或申請正式 API）；(2) 在資料明顯不足（例如某股票 lookback window 內少於門檻天數，如 <20 筆）時，`scan_volume_turnover` 應該要跳過該股票或至少標記「歷史不足，結果僅供參考」，而不是照樣算出一個 1.x 倍的量倍數當作正常訊號；`vol_window_days` 欄位其實已經有記錄實際窗口天數，但目前沒有在畫面或篩選邏輯上使用這個資訊來過濾掉「窗口太短不可信」的結果。
- 同樣邏輯建議套用到其他依賴長天期歷史窗口的功能（累積漲跌 badge、多頭拐點偵測等），全部检查一次是否也在用不足的歷史窗口計算。

### ✅ 驗證通過
- 這次 docs/index.html 顯示的「3 檔」跟 log 一致，不是快取或部署延遲問題——已確認新舊兩個版本都已正確 commit（`a920829`）並 push 到 origin/master，是資料本身在兩次執行間真的變了。
- TPEx（FinMind 回補）歷史資料完整度正常（中位數 359 筆），這次 review 的範圍限定在 TWSE。

### 結論
- [ ] 需要修改後再確認 — TWSE 歷史資料回補持續失敗是比 `_merge_into_csv` crash 更根本的問題，建議列為高優先級追蹤；在此之前，任何依賴 TWSE 歷史窗口的訊號（巨量換手、累積漲跌、拐點偵測等）都應該視為不可靠

---

## [2026-07-02] 報告 - commit d761406「救回 yfinance 歷史補齊功能，新增 --backfill-yf」review

### 審查方式
- 靜態 review：`git show d761406`（scrapers/backfill.py、main.py 完整 diff）
- 死碼確認：全專案 `grep -rn "_fetch_yfinance_history"` 確認無殘留呼叫者
- CLI 驗證：`python main.py --help` 確認 `--backfill-yf MONTHS` 有正確接上、說明文字正常
- Mock 測試：對 `_fetch_yfinance_one_stock()` 用 `unittest.mock.patch("yfinance.Ticker")` 手動驗證 4 種情境（成功／重試後成功／重試耗盡／靜默回傳空 DataFrame），目前**沒有任何自動化測試檔案**涵蓋這支新程式碼（`tests/` 底下沒有 yfinance 相關測試）

### 🔴 程式問題（需立刻修，優先級最高）
- 問題：`backfill_yfinance()`（scrapers/backfill.py）的 `clean=True` 步驟是**無條件執行**，跟這次 session 稍早才修好的 `backfill_twse_monthly()`（`clean and not twse_blocked`）不一樣——沒有「大部分股票都失敗就跳過清空」的保護。
  ```python
  logger.info("yfinance 完成：成功 %d / 共 %d 支", ok, total)   # ← ok/total 比例已經知道了
  ...
  if clean:                                                      # ← 但完全沒用到 ok/total，無條件清空
      old_csvs = list(output_path.glob("*.csv"))
      ...
      f.unlink()
  ```
  這個功能存在的理由，正是因為**舊版 yfinance 批次抓取會被 Yahoo 限流**（見 commit message 說明，`2620c3a` 就是因為這樣把舊版刪掉）。這版改成逐支抓 + 隨機延遲降低風險，但沒有完全消除被限流的可能——如果對全部 1040 支股票跑 `--backfill-yf 19 --workers 3`，中途被 Yahoo 限流（例如只成功 50~100 支就開始大量失敗），程式仍然會：
  1. 先把 `data/daily_prices/` 底下**所有現有 CSV 全部刪掉**（包含這次 session 稍早才驗證過、品質良好的 TPEx FinMind 回補資料，中位數 359 筆/檔）
  2. 只用這次 yfinance 抓到的少少幾十支資料重寫 CSV
  結果是資料量不增反減、比執行前更差——而且這正好是 Debugger 這次 session 最早發現、也是目前優先級最高、還沒解決的問題（TWSE 歷史資料只有 2 筆），若不慎執行這支未加保護的函式，有可能連現有還算完整的 TPEx 資料都一起賠上。
  位置：`scrapers/backfill.py`，`backfill_yfinance()` 的 clean 區塊（約第 336-345 行）。
  重現方式：目前無法輕易重現實際的 Yahoo 限流（要跑到真的被擋），但邏輯上只要 `ok/total` 明顯偏低時執行就會觸發，屬於程式邏輯層面就能判斷出來的缺陷，不需要真的被限流也能看出風險。
  建議修法：比照 `backfill_twse_monthly()` 的模式，例如「`ok` 低於某個門檻（如 `total` 的 50~80%）就跳過清空」，或者更保守地一律不要在這個函式裡做無條件清空、改成只 merge（`overwrite=True` 但不刪除其他檔案，這本來就是 `_merge_into_csv` 的行為），把「要不要先清空重建」的決定權留給呼叫端在確認資料量足夠之後才手動觸發。

### 🟡 建議改善
- **「每 100 支暫停 5~10 秒」實際上沒有生效**：`backfill_yfinance()` 用 `ThreadPoolExecutor(max_workers=3)` 把全部 1040 個 stock 的 fetch 任務一次全部 submit 下去（`futures = {executor.submit(...): sid for sid in stock_ids}`），暫停邏輯寫在**主執行緒**的 `as_completed` 迴圈裡（`if done % 100 == 0: time.sleep(...)`）。但 3 個 worker thread 是獨立從佇列裡拉下一個任務執行，不會因為主執行緒在 `sleep` 就跟著停下來——主執行緒睡覺的當下，3 個 worker 仍然持續處理佇列裡排隊的下一批股票。真正在節流的只有每支股票各自函式內的 `time.sleep(random.uniform(0.5,1.2))`（這個有效，因為是在 worker 內部執行）。跟 `downloader_tw.py`（單執行緒、循序執行）的行為不同，「每 100 支額外暫停」這個防封鎖設計目前形同虛設，如果要真的達到效果，需要改成分批 submit（每 100 支 submit 一批、等這批全部完成才 submit 下一批並在中間 sleep），而不是把主迴圈的 sleep 當作全域節流。
- **每支股票回補視窗的第一天，`change`/`change_pct` 永遠是 0**：`_fetch_yfinance_one_stock()` 用「視窗內自己跟自己比」算漲跌（`prev = closes[i-1] if i > 0 else close`），視窗第一筆沒有更早的資料可比，所以固定得到 `change=0, change_pct=0`。已用 mock 測試證實（第一筆 `close=100.0` 時 `change` 確實是 `0.0`）。19 個月回補只影響每支股票最早那一天（例如 2025-01-01 附近），範圍很小，但那天的漲跌幅是錯的（不是真正 0），不是「無資料」也不是「假日」，是被算錯的數字，建議至少要註記或跳過該筆，不要當正常資料寫入。
- **`exchange_map.get(sid) == "TPEx"` 的判斷方式**：只要不是明確等於 `"TPEx"`（包含 `None`、缺值、任何拼字不同的值）都會被當作 TWSE、組成 `.TW` ticker。目前 `stock_universe.csv` 的 `exchange` 欄位很乾淨（只有 `TWSE`=515、`TPEx`=525 兩種值，無缺漏、無重複 `stock_id`），所以現在沒有實際影響，但這種「預設當作 TWSE」而非「明確比對兩種合法值、其餘報錯或跳過」的寫法，是隱性風險，未來資料若混入第三種分類或缺值會被默默誤判，不會有任何警告。
- `main.py::backfill_yf()` 的 `exchange_map` 缺欄位時 fallback 用 `{}`，`backfill_twse()` 對應情況用 `None`——兩者對 `_ticker_for()`/`backfill_twse_monthly()` 內部邏輯結果一樣（都變成全部當 TWSE 處理），純粹風格不一致，非阻擋項。

### ✅ 驗證通過
- **死碼確認**：`_fetch_yfinance_history()`（批次版）已完全移除，全專案 `grep` 確認沒有任何殘留呼叫者（`main.py`、`tests/` 都沒有引用）。
- **輸出格式相容**：`backfill_yfinance()` 產生的 row 欄位（`stock_id, close, change, change_pct, volume, _date`）跟 `_fetch_stock_months()`（TWSE Phase 1）完全一致，用同一個 `_merge_into_csv(overwrite=True)` 寫入 `data/daily_prices/*.csv`，可以正常跟 DuckDB `reimport_db()` 銜接；純新增函式，沒有修改 `backfill_twse_monthly()` 本身，兩者互相獨立，不影響既有 Phase 1/Phase 2 邏輯。
- **CLI 正確接上**：`python main.py --help` 確認 `--backfill-yf MONTHS` 存在、說明文字正常；`elif args.backfill_yf:` 分支正確呼叫 `backfill_yf(months=..., workers=...)`，跟 `backfill_twse()` 走同樣的 `init_db()` → `reimport_db()` 收尾模式。
- **重試/退避邏輯**：用 `unittest.mock.patch("yfinance.Ticker")` 手動驗證 4 種情境，全部正確：
  - 正常回傳：格式正確（`stock_id/close/change/change_pct/volume/_date` 齊全）
  - 前 2 次拋例外、第 3 次成功：確實重試了 3 次（`max_retries=2` → 共 3 次嘗試）後拿到資料
  - 全部拋例外：耗盡重試後正確回傳空列表，不會讓整體流程崩潰
  - 一直回傳空 DataFrame（模擬 Yahoo 靜默限流、不拋例外）：一樣會重試、耗盡後回傳空列表，沒有誤判成功
- **exchange_map 對應規則**（TWSE→`.TW`、TPEx→`.TWO`）在目前資料狀態下運作正確；已確認 `stock_universe.csv` 的 `exchange` 欄位只有 `TWSE`/`TPEx` 兩種值，1040 筆無缺漏、無重複 `stock_id`。

### 測試建議（目前完全沒有測試覆蓋，建議至少補以下案例）
1. `_fetch_yfinance_one_stock()`：mock `yfinance.Ticker(...).history(...)`，涵蓋成功／重試後成功／重試耗盡／靜默回傳空 DataFrame 四種情境（此次 review 已手動驗證過，建議直接轉成正式測試寫進 `tests/test_backfill.py` 或新檔）。
2. `backfill_yfinance()`：mock `_fetch_yfinance_one_stock`（比照 `test_backfill.py` 既有 mock `_fetch_stock_months` 的寫法），驗證：(a) 輸出格式與 `_merge_into_csv` 呼叫正確；(b) `exchange_map` 對應正確組出 `.TW`／`.TWO` ticker 傳給 `_fetch_yfinance_one_stock`。
3. **最優先**：針對上面 🔴 的 `clean=True` 風險，補一個「大部分股票失敗（例如 mock 1040 支只成功 10 支）」的測試案例，驗證這種情況下**不應該**清空舊 CSV。目前這個測試會失敗（因為 bug 還沒修），等 Developer 修完可以直接拿來當驗收依據。
4. 第一天 `change_pct` 固定為 0 的情況：可以補一個測試明確記錄這個已知限制（避免之後被誤以為是迴歸），或者等 Developer 決定要不要修正後再補對應測試。

### 結論
- [ ] 需要修改後再確認 — 特別是 `clean=True` 無條件清空的資料遺失風險（🔴），建議在真正拿去對 1040 支股票跑 `--backfill-yf` 之前先修掉；「每 100 支暫停」沒有實際生效（🟡）也建議一併處理，否則這個新路徑很可能重演舊版 `yf.download()` 批次抓取被限流的問題

---

## [2026-07-02] 驗證 - commit 511ff1b「backfill_yfinance() clean 資料遺失風險 + 暫停機制無效 + 第一天假0值」

### 驗證方式
- 靜態程式碼 review（`git show 511ff1b` 完整 diff：scrapers/backfill.py、tests/test_backfill.py）
- 執行測試：`pytest tests/test_backfill.py -v`（12 個測試全過，含 5 個新增測試）與全專案 `pytest`（65 個測試全過——先前 `test_scan_patterns_returns_list` 的失敗是因為缺 `data/screener.db`，這次在 `tw-sector-tracker` 開發者資料夾底下跑、DB 已存在，不再失敗）
- 手動追蹤程式邏輯，逐項核對 debug-tasks.md 的驗證清單

### ✅ 驗證通過（對照 debug-tasks.md 的「請 Debugger 驗證」清單）
- **clean 成功率門檻邏輯正確**：`success_rate = ok/total`，`< _YFINANCE_MIN_SUCCESS_RATE(0.5)` 時把 `clean` 強制設為 `False` 並記錄 `logger.error`，位置在「知道 ok/total」之後、「執行清空」之前，順序正確。對應測試 `test_backfill_yfinance_skips_clean_when_success_rate_low`：4 支股票只成功 1 支（25% < 50%），驗證預先寫好的錨點檔案 `2025-01-01.csv` 沒有被清空邏輯刪掉，通過。
- **pause_state 真的讓 worker 暫停，不是主執行緒空轉**：暫停邏輯搬進 `_fetch_yfinance_one_stock()` 內部、在函式即將 return 前執行，靠跨 thread 共用的 `pause_state["lock"]` 保護計數器遞增，滿 `pause_every` 的那個 worker 自己 `time.sleep(random.uniform(5,10))`。因為這段程式碼是在 **worker thread 內部**執行（不是主執行緒的 `as_completed` 迴圈），確實會卡住該 worker 撿下一個任務的時間，跟舊版「主執行緒睡覺、worker 完全不受影響」的無效實作不同。對應測試 `test_fetch_yfinance_one_stock_pauses_every_n_completions` 手動把 `pause_state["count"]` 設成 1、`pause_every=2`，驗證這支呼叫後 `count` 變 2 且確實觸發了一次 5~10 秒區間的 sleep，通過。
- **第一天假 0 值已修正，且不只用 mock 驗證**：往前抓 `start_date - 5 天` 當緩衝，用 `if i==0: continue` 跳過緩衝區間裡沒有 `prev` 可用的最早一筆（避免 `closes[i-1]` 在 `i=0` 時發生 Python 負索引取到最新一筆的錯誤比較），再用 `if d_str < start_date: continue` 把其餘緩衝天數（有正確 `prev` 但屬於緩衝範圍）排除在輸出之外，只有 `start_date` 當天（或該區間第一個真正交易日）用緩衝天的收盤價正確算出 `change_pct`。逐步手算過對應測試 `test_fetch_yfinance_one_stock_skips_buffer_day_fake_zero` 的資料（6/27 緩衝、6/29 起始、6/30），105 vs 100 → `change_pct=5.0`，跟斷言一致，邏輯正確；commit message 也提到用真實 yfinance 資料額外驗證過（2026-06-26 顯示 -2.09%），非純 mock。
- **exchange_map 方向調整跟 `backfill_twse_monthly()` 一致**：新版 `_ticker_for()` 改成「明確 `== "TWSE"` 才是 TWSE，其餘（含未知代號）一律 `.TWO`」，對照 `backfill_twse_monthly()` 內的 `tpex_stocks = [sid for sid in stock_ids if exchange_map.get(sid) != "TWSE"]`，判斷方向確實一致。對應測試 `test_backfill_yfinance_ticker_suffix_mapping` 額外驗證了「不在 exchange_map 裡的未知代號（`9999`）」會被歸類成 `.TWO`，符合「預設非 TWSE」的新慣例，通過。
- 沒有引入新的資料來源混用風險：這次修改完全侷限在 `backfill_yfinance()`／`_fetch_yfinance_one_stock()` 內部，沒有動到 `backfill_twse_monthly()`／Phase 1／Phase 2 邏輯本身。

### 🟡 小提醒（非阻擋項）
- 緩衝天數固定寫死 5 個日曆天：如果遇到連續假期超過 5 天（例如農曆春節），緩衝範圍內可能完全沒有真正的交易日，屆時 `i==0` 那筆可能已經是 `start_date` 當天或之後，會被誤跳過（少算一天）。機率低、影響範圍極小（一年最多一兩次、每次只少一天），不阻擋這次修復，但值得記一筆，之後若要更嚴謹可以考慮把緩衝天數放寬或改成動態抓到有資料為止。
- `_YFINANCE_MIN_SUCCESS_RATE = 0.5` 這個門檻是新加的常數，目前沒有看到來源根據（不像 `_CONSECUTIVE_FAIL_LIMIT`／`_MIN_WINDOW_DAYS` 那樣有明確理由或既有慣例可循），50% 是一個合理但主觀的預設值，之後如果實際跑起來發現太嚴或太鬆，可以再調整，不影響這次修復方向的正確性。

### 結論
- [x] 可以繼續下一個任務 — commit `511ff1b` 針對 Debugger 稍早回報的 3 個 `backfill_yfinance()` 問題都做了對應修復，邏輯正確、測試齊全（5 個新測試 + 全專案 65 個測試全過），沒有發現新問題。建議 Cody 可以照 debug-tasks.md 上一個任務的建議，找機會實際跑一次 `--backfill-yf 19 --workers 3` 驗證長時間穩定性（尤其想看 clean 保護機制在真實限流情境下是否會觸發）

---

## [2026-07-02] 驗證 - 實跑 `python main.py --backfill-yf 19 --workers 3`（1040 支股票全量）

### 執行結果
```
yfinance 完成：成功 1039 / 共 1040 支
清除舊 CSV：刪除 360 個，跳過 0 個（被鎖定）
補齊完成：寫入/更新 361 日，共 372167 筆
reimport 完成：共 372163 筆
```
耗時約 6 分鐘，全程沒有被 Yahoo 限流擋下，只有 1 支股票失敗。

### ✅ 驗證通過 — 這是這次 session 追了一整天的 TWSE 歷史資料缺失問題，第一次真正被解決
- **成功率 99.9%（1039/1040），遠高於 50% 門檻，`clean` 正確執行**，不是誤觸發保護機制、也不是該保護但沒保護——這次是「資料夠好，可以放心清空重建」的正常情況，跟先前驗證過的「資料不夠、跳過清空」是同一組邏輯的兩種正確分支。
- **實測資料深度**（直接查 DuckDB，不是看 log）：
  ```
  TWSE 515 檔：中位數 360 筆（原本是 2 筆），<=5 筆的 0 檔（原本是 509 檔，98.8%）
  TPEx 525 檔：中位數 360 筆，維持健康（跟先前 FinMind 回補的品質一致）
  全市場日期範圍：2025-01-02 ~ 2026-07-02，共 361 個交易日，覆蓋完整 19 個月
  ```
  抽查先前造成「巨量換手訊號 5 檔 vs 3 檔」誤判的 8021，現在有 360 筆歷史（原本 2 筆）。**這代表 `scan_volume_turnover()`／`calc_cumulative_meta()`／拐點偵測等所有依賴 TWSE 歷史窗口的功能，現在總算有真正的 126 天／126 個交易日資料可以算，不再是「今天 vs 一年多前隨機一天」的雜訊。**
  - 補充：`f4f3795`（`scan_volume_turnover` 資料不足 <20 筆跳過）這道防線這次沒有被觸發（因為資料現在充足了），但仍建議保留，作為未來 TWSE 又被封鎖時的最後防線。
  - 也建議提醒 Developer：debug-tasks.md 先前提到的「`calc_cumulative_meta`、量能異常 badge、Weinstein Stage 2 拐點偵測」這幾個當時列為🟡非阻擋、還沒個別檢查的功能，現在資料補齊了，之前的隱患自然消失，但如果之後 TWSE 又被封鎖、資料又退化，仍然只有 `scan_volume_turnover` 有防護，其餘幾個沒有——這個技術債還在，只是暫時不會發作。
- **`--merge_into_csv` 沒有鎖檔問題**：`跳過 0 個（被鎖定）`，這次沒有重現先前的 `2025-06-02.csv` OneDrive 鎖檔情況。
- **pause_state／重試機制在真實 1040 支股票規模下運作良好**：log 顯示全程速度穩定（每 50 支約 17-19 秒，沒有中途明顯變慢或大量失敗的跡象），唯一的失敗（`674191`）有正確重試（log 可見對同一 symbol 重試了 3 次才放棄），沒有拖累其他股票或整體流程。

### 🟡 資料完整性提醒（非程式 bug，但符合 CLAUDE.md「資料完整性」檢查項目）
- 唯一失敗的 `674191`（`APP*-KY`，TPEx）在 yfinance 回傳 `404 Quote not found` / `possibly delisted`。查 `stock_universe.csv`：股名帶 `*`（台股慣例上 `*` 通常標示特殊交易狀態，例如全額交割/處置股），加上 Yahoo 端直接查無此代號，研判這支股票目前可能已經下市、全額交割或長期停牌。
  建議 Developer／Cody 確認一下 `674191` 是否還應該留在 `stock_universe.csv` 的掃盤名單裡——如果它已經不是正常交易狀態，讓它繼續留在 universe 裡會導致這支個股在所有掃盤/族群計算裡持續呈現「無資料」，雖然不會造成計算錯誤（現有程式碼都有正常處理無資料的情況），但population 裡有一支僵屍股票，長期來看值得清理。這不是這次 review 範圍要修的程式 bug，純粹是資料維護提醒。

### 結論
- [x] 可以繼續下一個任務 — `--backfill-yf` 全量實跑驗證通過，TWSE 歷史資料缺失的根本問題已解決（98.8% 缺資料 → 0% 缺資料），前面幾輪修復（clean 保護、pause 節流、緩衝天算真實漲跌、scan_volume_turnover 資料門檻）在真實情境下都發揮了預期效果。剩下唯一提醒是 `674191` 這支疑似下市股票的資料維護問題，非阻擋項

---

## [2026-07-02] 報告 - `python main.py --realtime` crash：`UnboundLocalError: cannot access local variable 'pd'`（CRITICAL，全站生成會中斷）

### 🔴 程式問題（需立刻修，CRITICAL）
- 問題：`export/html_generator.py` 裡 `_meta_stock_cards()`（第 461 行起）跟 `_stock_table()`（第 283 行起）這兩個函式，各自在迴圈內部有一行**多餘、不必要的** `import pandas as pd`（分別在第 515 行、第 331 行），是拿來配合一個 `_na()` helper（`pd.isna()` 檢查）用的。
  問題在於：Python 的函式作用域規則是「整個函式內，只要有任何一處對某個名稱賦值（包含區域 `import`），這個名稱在整個函式作用域內都會被視為區域變數」——不管那行程式碼實際上有沒有被執行到。這兩個函式在**更早的地方**（迴圈開始之前）就有：
  ```python
  prices_map = prices_df.set_index("stock_id") if not prices_df.empty else pd.DataFrame()
  chips_map = chips_df.set_index("stock_id") if chips_df is not None and not chips_df.empty else pd.DataFrame()
  ```
  平常這兩行的 `else pd.DataFrame()` 分支不會被執行到（因為三元運算子是短路求值，只要 `prices_df`/`chips_df` 有資料，`pd.DataFrame()` 就永遠不會被觸發，也就不會踩到「區域變數 `pd` 還沒賦值」的問題），**但只要 `chips_df` 是空的或 `None`**，`chips_map = ... else pd.DataFrame()` 這個分支就會執行到，此時 Python 嘗試存取的是「這個函式作用域內的區域變數 `pd`」（因為函式後段有 `import pandas as pd`），但這個區域變數在函式一開始還沒被賦值過，於是拋出 `UnboundLocalError: cannot access local variable 'pd' where it is not associated with a value`。
  這次實際重現：`python main.py --realtime` 在盤中執行，當天三大法人／融資融券資料還沒公布，`main.py` 讀 `get_chips_today(trade_date.isoformat())` 對「今天」這個日期查不到資料，回傳空的 `chips_df`（或觸發 `except Exception: chips_df = pd.DataFrame()` 的 fallback），一路傳進 `generate_html()` → `_meta_card()` → `_meta_stock_cards()`，第一張卡片（`i=0`）就直接炸掉，完整 traceback：
  ```
  File "main.py", line 421, in run
      generate_html(trade_date, ...)
  File "export/html_generator.py", line 872, in generate
      c, p = _meta_card(r, i+1, f"t{i}", sectors_df, prices_df, chips_df, universe_df, ...)
  File "export/html_generator.py", line 706, in _meta_card
      detail_inner = _meta_stock_cards(...)
  File "export/html_generator.py", line 484, in _meta_stock_cards
      chips_map = chips_df.set_index("stock_id") if chips_df is not None and not chips_df.empty else pd.DataFrame()
  UnboundLocalError: cannot access local variable 'pd' where it is not associated with a value
  ```
  影響範圍：
  - **這是一個未被 catch 的例外，會讓整個 `run()` 直接中斷**——不只 HTML 沒產生，連 push to GitHub Pages 那步都不會執行，當天網站完全不會更新（比起「顯示過期資料」更糟，是「整個流程直接崩潰」）。
  - 觸發條件不是只有 `--realtime`：任何一天只要 `chips_df` 是空的（三大法人/融資融券資料抓取失敗、`get_chips_today()` 對當天查無資料、或 `main.py` 第 380 行左右 `except Exception: chips_df = pd.DataFrame()` 被觸發），不管是不是 `--realtime` 模式，都會踩到同一個崩潰。今天稍早這個 session 看到的好幾次成功執行（`HTML generated → docs/index.html`），都是剛好那次 `chips_df` 有資料（三大法人/融資融券當天或前一交易日的資料抓取成功），純粹僥倖沒踩到這個地雷，不代表這個路徑是安全的。
  - `_stock_table()` 一樣有這個問題（第 297-298 行的 `pd.DataFrame()` fallback + 第 331 行的區域 `import`），呼叫端包含 `_sector_row()`（第 387、416 行）、`_top10_card()`（第 441 行）——只要 `chips_df` 是空的，這幾個函式全部都會踩雷，不只是 `_meta_stock_cards`。
  位置：`export/html_generator.py` 第 515 行、第 331 行（兩處多餘的 `import pandas as pd`）。
  這個 bug 是這次 session 稍早 review 過的 commit `6993d36`（TWSE 封鎖偵測那批）引入的——當時新增 `_na()` helper 是為了修「chips 數字忘記除以 1000」那個問題順便把 `int(c.get(...) or 0)` 改成 `pd.isna()` 判斷（原本的 `or 0` 寫法對 NaN 也有潛在問題：`float('nan') or 0` 因為 NaN 是 truthy，結果還是 `nan`，`int(nan)` 會丟 `ValueError`），但改的時候誤用了「函式內區域 import」而不是直接用模組層級已經 `import` 好的 `pd`，反而引入了更嚴重的崩潰。這一點在稍早 review `6993d36` 時我沒有抓到，這次趁 crash 回報才補上，記錄一下避免以後犯同樣的遺漏。
  建議修法：直接刪掉第 515 行、第 331 行這兩個多餘的 `import pandas as pd`（模組頂部第 2 行已經 `import pandas as pd`，函式內完全不需要重複 import）。順手也可以清掉第 196 行（`_stock_card_html` 內）那個雖然目前沒有造成 bug、但同樣多餘的區域 import，避免以後有人在它前面加類似的 `pd.DataFrame()` fallback 又重演一次。

### 結論
- [ ] 需要修改後再確認 — CRITICAL，會讓整個每日更新流程崩潰（不只是資料不準確，是完全不會更新），建議優先於其他項目盡快修
