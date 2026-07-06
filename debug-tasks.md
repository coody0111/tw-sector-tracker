## [2026-07-06] 角色文件加「工作流自檢」常駐 checklist（CLAUDE-developer.md / CLAUDE-debugger.md）

### 改了什麼
- 異動檔案：`CLAUDE-developer.md`、`CLAUDE-debugger.md`
- 兩份角色文件各加一節「## 工作流自檢（每次開工先跑一遍）」，把「怎麼確認 workflow 是正確的」
  變成常駐流程，不再靠口頭交代。內容：開工前自檢（分支/資料夾/角色/git status/merge 乾淨）、
  收工/驗證步驟、🚩 紅旗清單（身分檔又衝突、CLAUDE.md 又被追蹤、非預期 staged、ahead/behind 過大）、
  兩 session 別同時動 git 的提醒。

### 請 Debugger 驗證 / 採用
- [ ] 收乾淨身分檔移行後（見下一則），**以後每個 session 開工照 `CLAUDE-debugger.md` 的「工作流
  自檢」跑一遍**——特別是第 4 步 `git merge master` 應該乾淨、不再撞身分檔衝突（若還撞代表移行沒做完）
- [ ] 純文件，無程式邏輯改動，不影響測試

---

## [2026-07-06] 修 main.py::_push_html() 自動 push 的兩個地雷（local↔遠端協作穩定性）

### 改了什麼
- 異動檔案：`main.py`（`_push_html()`，148-163 行）
- 背景：今天早上 `python main.py --realtime` 撞上一連串 git 問題（`docs/data.json` 未合併
  衝突、筆電落後 origin 53 個 commit、自動 commit 掃到不相關的 staged 變更）。根因不是 gitignore，
  是 `_push_html()` 的兩個地雷：

**地雷 1：commit 沒限定範圍**
原本 `git commit -m ...`（無 pathspec）會把「當下所有 staged 的東西」一起 commit，不只那幾個
產出 HTML。之前（見 bug-reports 2026-07-05 React revert 那則）就發生過：某人 `git rm --cached`
到一半、`main.py` 剛好被跑，那些 staged 的刪除被一起 commit+push 上去。
→ 改成 `git commit -m ... -- <files_to_add>`，只 commit 指定的產出檔；`git diff --cached --quiet`
也加 `-- <files>` 限定範圍，不受其他 staged 變更影響判斷。

**地雷 2：push 前不同步 → 兩台機分岔**
原本直接 `git push`。兩台機（桌電/筆電）各自 push「update: sector performance」就會分岔，下次
pull 撞 merge 衝突（今天 data.json 那次就是）。
→ push 前先 `git pull --rebase --autostash`，把本機這筆接到遠端最新之後再推。**若 rebase 撞
衝突就 `git rebase --abort`、保持工作區乾淨、本機 commit 保留、log 警告請人工處理**——不讓自動
流程卡在半完成的 rebase（這是刻意的安全設計，寧可不自動推、也不要留一個壞掉的 rebase 狀態）。

### 資料來源相關（如有異動）
- 不適用——純 git 自動化流程的穩定性修復，不碰任何資料抓取/轉換邏輯。

### 請 Debugger 驗證
- [ ] `ast.parse` 語法檢查通過（我已跑：main.py 語法 OK）；全專案測試不受影響（沒有動到被測邏輯）
- [ ] **重點**：確認 commit 限定範圍有效——製造一個情境：先手動 stage 一個不相關變更
  （例如 `git add 某個別的檔`），再讓 `_push_html()` 跑，確認那個不相關變更**不會**被一起 commit
- [ ] 確認 `git pull --rebase` 撞衝突時真的會 `rebase --abort` 回乾淨狀態、不會卡在 rebase 中途
  （可用兩個 clone 製造分岔＋衝突情境測）
- [ ] **留給 Cody 決定**：push 前自動 `pull --rebase` 是行為改變。如果 Cody 偏好「push 前一律
  手動 pull、不要自動 rebase」，這段可以拿掉只保留地雷 1 的 commit 限定範圍。目前的版本是
  「安全的自動化」：常見情境自動接上，衝突時安全退出不卡住。

### 特別注意
- **沒有動 `.gitignore`**：因為 Debugger 那邊正在做 debug 分支的 CLAUDE.md/.gitignore 移行
  （見 bug-reports/口頭交接），避免兩邊同時改同一檔 race。`.gitignore` 追加 build 產物
  （`docs/data.json`、`docs/assets/`）那項留到 debug 移行收乾淨後再由 Developer 補。

---

## [2026-07-06] 大戶張數化+內部人持股計畫 Task 1：shareholder 表新增 lv12_15_shares（大戶實際張數）

### 改了什麼
- 異動檔案：`screener/database.py`、`scrapers/shareholder.py`、`tests/test_shareholder.py`
- 對照計畫 `docs/superpowers/plans/2026-07-06-shareholder-insider-breakdown.md` 的 **Task 1**（全程 TDD：寫失敗測試→跑紅燈→實作→跑綠燈）。

**背景**：`_fetch_one_stock()` 其實早就回傳 `lv12_15_shares`（大戶實際持股股數），但 `save_to_db()`
一直只存 `lv12_15_pct`/`lv12_15_cnt`/`total_shares` 三欄、把張數丟掉。這個 Task 把張數持久化，
供後續 Task 2/4/5 算「大戶張數變化」用。

**做了什麼**：
1. `screener/database.py::init_db()`：`shareholder` 表 CREATE TABLE 新增 `lv12_15_shares BIGINT`
   （放在 `lv12_15_cnt` 之後），並補一行 `ALTER TABLE shareholder ADD COLUMN IF NOT EXISTS
   lv12_15_shares BIGINT`（既有的 `data/screener.db` 已建過表，`CREATE TABLE IF NOT EXISTS`
   對它不生效，要靠 ALTER 補欄）。
2. `scrapers/shareholder.py::save_to_db()`：`df` 選欄加入 `lv12_15_shares`，INSERT 把它寫進 DB。
3. `tests/test_shareholder.py`：新增 `test_save_to_db_persists_lv12_15_shares`；同步更新既有
   `_make_table()`/`_insert()` helper 的 schema（7 欄→8 欄），維持一致。

### ⚠️ 我對計畫做的一個偏離（正確性修正，請 Debugger 特別確認）
計畫 Step 4 的 `save_to_db` 用**位置式** INSERT（`INSERT INTO shareholder SELECT col1, col2, ...`）。
我發現這在正式 DB 上會**靜默錯位**：
- 全新 DB 走 CREATE TABLE，`lv12_15_shares` 是**第 5 欄**（中間）。
- 既有 DB（如正式 `data/screener.db`）走 ALTER ADD COLUMN，`lv12_15_shares` 被 append 成**最後一欄**（第 8 欄）。
- 兩者欄位順序不同，位置式 INSERT 會把「張數」寫進 `total_shares`、其餘欄位整排位移。
  計畫的測試用全新表（中間順序）**會過**，但正式 DB 會被寫壞——正是「不報錯但給錯資料」那類。

修法：INSERT 改成**明列欄位名**（by-name 對應，不受欄位順序影響）：
`INSERT INTO shareholder (stock_id, date, lv12_15_pct, lv12_15_cnt, lv12_15_shares, total_shares,
week_chg, streak) SELECT ... FROM df`。

已額外寫一個獨立驗證腳本模擬「ALTER 把欄位加在最後」的正式 DB 情境，確認修法下 `shares=5,000,000`
正確進 `lv12_15_shares`、`total=25,000,000` 正確進 `total_shares`，沒有互換（若用位置式會錯位）。

### 資料來源相關（如有異動）
- 不適用——這是 DB schema 擴充＋既有 TDCC 回傳欄位的持久化，沒有改動 TDCC/TWSE/TPEx 抓取或口徑邏輯。
  `lv12_15_shares` 本來就在 `_fetch_one_stock()` 的回傳裡，只是之前被丟棄。

### 請 Debugger 驗證
- [ ] `tests/test_shareholder.py` 全過（我這邊：8 passed，7 既有 + 1 新）
- [ ] 全專案測試不受影響（我只跑了 shareholder 這檔，全專案回歸留給 Debugger）
- [ ] **重點**：確認上面那個 by-name INSERT 修正——找一份「schema 走過 ALTER」的 DB（或照我
  的做法建一個：先建舊 7 欄表、再 ALTER 加 lv12_15_shares 到最後），跑一次 `save_to_db`，確認
  `lv12_15_shares`/`total_shares` 沒有錯位。這是計畫原本會踩到、我主動修掉的坑。
- [ ] 確認 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 對「已經有 lv12_15_shares 欄的 DB」重複執行
  不會報錯（DuckDB 的 IF NOT EXISTS 應該冪等，但值得實跑一次 init_db 兩遍確認）

### 特別注意
- 這只是 Task 1（5 個 Task 的第一個）。Task 2（`get_shareholder_top` 回傳張數變化）、Task 3
  （新增 insider_holdings scraper）、Task 4（main.py 串接）、Task 5（chips 表格新增欄位）都還沒動。
- 目前**只本機 commit、還沒 push**（等 Debugger 驗證過再 push 到 origin），Cody 的決定。

---

## [2026-07-06] 形態掃描（screener/patterns.py）籌碼邏輯 review：修 margin_divergence 永遠 False + 拆重複載入邏輯

### 改了什麼
- 異動檔案：`screener/patterns.py`、`main.py`、`tests/test_patterns.py`

**背景**：Cody 問「籌碼面程式邏輯還有哪些」，發現 `screener/patterns.py`（`docs/patterns.html`
形態掃描複合評分）也有一整套自己的籌碼邏輯，但完全不在 2026-07-05/06 那兩次 review 的範圍內
（原本明確排除）。Cody 要求嚴格 review 後直接修。

**發現的問題**：
1. `scan_patterns()`（848行）跟 `scan_and_track()`（1078行）兩個函式呼叫
   `calc_composite_score()` 時，`margin_divergence` 參數**都寫死 `False`**，從
   2026-07-01 這個複合評分功能一開始寫的時候就是這樣，從來沒有真的算過。但
   `calc_composite_score()` 裡這個參數的懲罰是 -15 分（比 `margin_alert_pct>=10` 的
   -10 分還重），代表這個分支永遠不會被觸發，複合評分公式實際上一直是不完整的版本。
2. `scan_patterns()` 跟 `scan_and_track()` 有大約 70 行**幾乎一模一樣**的資料載入邏輯
   （同樣 4 條 SQL：`daily_prices`／`institutional`／`shareholder`／`margin`，同樣的
   lookup map 建構），複製貼上維護，容易改一處忘記改另一處。

**Cody 提醒**：`scan_patterns()` 主要是給 `backtest_patterns()` 逐日回放歷史用的，
`scan_and_track()` 才是 `main.py` 每日呼叫、`docs/patterns.html` 實際顯示資料的正式路徑——
這個提醒是對的，也是這次判斷「兩處要怎麼修」的關鍵：

- **`scan_and_track()`（正式路徑）**：改成接受新的 `margin_divergence_data: dict = None`
  參數（`processors/performance.py::get_margin_divergence()` 的回傳值），從裡面的
  `bearish` 清單算出 `bearish_ids` 集合，`margin_divergence=sid in bearish_ids` 取代
  寫死的 `False`。`main.py` 呼叫端（第 537 行）改傳 `margin_divergence_data=margin_div`——
  `margin_div` 這個變數 `main.py` 本來就已經在第 439 行為了 `chips.html` Section 7 算過
  一次，直接重用，不會多一次 DB 查詢。
- **`scan_patterns()`（backtest 路徑）**：**維持寫死 `False`，但加了說明註解**，不是漏改。
  `get_margin_divergence()` 只能查「margin 表裡最新 N 個日期」，沒有 `trade_date` 錨點
  參數，沒辦法拿來算「回測某個歷史日當天」的融資背離狀態——這是獨立的功能擴充（要先
  幫 `get_margin_divergence()` 加上指定日期錨點查詢的版本），不在這次修復範圍內，
  故意保留現況、只是把「為什麼」寫清楚，避免下次又被誤會成漏接。
- **拆重複載入邏輯**：新增 `_load_chips_context(con, date_str)`，回傳
  `{price_df, name_map, inst_by_stock, sh_map, margin_map}`，兩個函式都改成呼叫這個
  共用函式。不在裡面關閉 DB 連線（`scan_patterns()` 讀完就關，`scan_and_track()`
  後面還要用同一個連線寫 `pattern_signals`，關閉時機留給呼叫端決定）。

**驗證方式**：
- `scan_patterns()` 是唯讀函式，可以直接對本機真實的 `data/screener.db` 跑 —— 用
  `2026-07-03`（108 檔結果）重構前後各跑一次，輸出逐項比對（`json.dump` 後整個結構
  比較），**完全相同**，確認拆函式沒有改變行為
- `scan_and_track()` 會寫入 `pattern_signals` 表，不能拿真實 DB 測（避免污染正式的
  訊號追蹤歷史），改用 `tmp_path` 建最小 schema + 預先塞一筆 `active` 訊號繞過真的
  觸發形態偵測器的複雜度，驗證 `margin_divergence_data` 有正確接上：帶 bearish 名單
  的分數，比不帶的少 15 分，剛好符合 `calc_composite_score()` 的扣分公式
- 新增 `calc_composite_score()` 本身的單元測試（這個函式原本完全沒有測試）：驗證
  `margin_divergence=True` 扣 15 分、比 `margin_alert_pct>=10` 的 -10 分更重、且兩者
  是 `elif` 互斥關係（`margin_divergence=True` 時就算 `margin_alert_pct` 也很高也只
  扣一次 15 分）

### 資料來源相關（如有異動）
- 不適用——這是形態掃描複合評分的邏輯修復跟重構，不是資料抓取邏輯，
  TWSE/TPEx/FinMind 規則沒有變動

### 請 Debugger 驗證
- [ ] 全專案 96 個測試都過（原 92 + 新增 4 個：`calc_composite_score` 2 個、
  `scan_and_track` margin_divergence 2 個）
- [ ] 確認 `scan_patterns()` 拆函式前後對同一天真實資料輸出完全一致（我已經用
  `2026-07-03`（108 檔）逐項比對驗證過，Debugger 可以用同樣手法換一天再測一次）
- [ ] **建議找一天實際有融資背離個股**（`processors/performance.py::get_margin_divergence()`
  的 bearish 清單非空）的日子，用真實 `main.py` 跑一次，確認 `docs/patterns.html`
  上那些股票的 composite_score 真的比修復前低（可以對照同一天修復前的舊資料，如果
  有留存的話）
- [ ] 確認 `scan_patterns()`（backtest 用）維持寫死 `margin_divergence=False` 這個決定
  合理——如果之後真的想讓 backtest 也採用真實融資背離資料，需要先擴充
  `get_margin_divergence()` 支援指定日期錨點查詢，是後續獨立任務，這次沒有動它

### 特別注意
- `screener/patterns.py::_calc_streak()` 跟 `processors/performance.py::calc_meta_chips_
  signals()` 內部的 `_streak()` closure，兩邊演算法邏輯其實完全等價（都是「從最後一筆
  往前數，同號累加，變號就停」），但各自維護一份實作，這次沒有動——合併成單一共用函式
  風險/效益比不划算（`performance.py` 那份是 nested closure，要先拉成 module-level
  函式才能共用，牽動的呼叫端更廣），先記錄下來，之後如果剛好要改其中一處的邏輯，
  可以順便考慮要不要合併
- `screener/signals.py::scan_volume_turnover()` 的 `inst_confirmed`（外資+投信同日皆
  買超）邏輯也順便看過：資料源是單一表 SELECT（不是 FULL OUTER JOIN），`foreign_net`/
  `trust_net` 用 `.get()` 配 `is not None` 判斷，沒有 `pd.NA`/nullable-join 那類風險，
  確認沒問題，不需要修

---

## [2026-07-06] 籌碼面 code review 剩餘兩項：拆 chips_generator.py::generate() + exchange-aware 防呆

### 改了什麼
- 異動檔案：`export/chips_generator.py`、`processors/performance.py`、
  `tests/test_chips_generator.py`、`tests/test_processors.py`

**背景**：接續 2026-07-05 那次籌碼面 review 修復的三項，這次處理剩下範圍較大的兩項。

**1. 拆 `chips_generator.py::generate()`（原本約 360 行的單一函式，整個檔案卡在 800 行上限）**
把 Section 1/2/3/3.5/4/5/6/7/8 全部拆成獨立的 `_build_section1()`～`_build_section8()`
（外加 `_build_exchange_ui()` 處理交易所篩選 UI），`generate()` 現在只剩下呼叫這些函式
組裝最終 HTML，本體約 100 行（含 HTML 樣板字串）。
- **純重構，沒有改變任何邏輯**：用同一組合成測試資料，分別餵給重構前（git HEAD 版本）
  跟重構後的 `generate()`，逐 byte 比對輸出 HTML，結果**完全相同**，確認這次只是搬動
  程式碼、沒有動到行為
- 拆出來的函式全部維持模組層級（不是巢狀 closure），只有 `_streak_row`／`_trust_row`／
  `_dip_buy_row`／`_pct_cell`／`_is_stock` 這幾個仍是各自 section 函式內的區域 closure
  （因為只在該 section 用得到，拆出去反而增加不必要的參數傳遞）

**2. 族群層級籌碼數字的 exchange-aware 防呆（`partial_coverage` 旗標）**
之前只修過「外資買超比例」的分母（`foreign_buy_ratio`，動態排除當天缺資料的交易所），
但 `foreign_net_today`／`trust_net_today`／`foreign_streak`／`trust_streak`／
`margin_change_today`／`margin_balance_today` 這些數字本身沒有比照辦理——TPEx 抓取
失敗時，這些數字會悄悄變成「只反映 TWSE 那一半」，頁面上完全看不出來。
- `processors/performance.py::calc_meta_chips_signals()` 新增 `meta_all_exchanges`
  （每個族群「實際橫跨」的交易所，來自 universe 本身的成分股分布，不是憑空假設全部
  族群都有 TWSE+TPEx）跟 `margin_covered_by_meta`（today 這天 margin 表實際有資料的
  交易所），跟 institutional 既有的 `covered_exchanges` 一起比較。任一邊「族群應該有
  的交易所」缺席，就標記該族群 `partial_coverage: True`
  - **特別處理單一交易所族群**：如果某族群本來就只有 TWSE 成分股（沒有任何 TPEx
    個股），`meta_all_exchanges` 只會是 `{"TWSE"}`，今天只有 TWSE 資料是正常狀態，
    不會被誤判成「涵蓋不足」——這跟「族群明明橫跨兩所、但當天某一所資料源失敗」是
    兩種不同情況，分開測試驗證過
- `export/chips_generator.py` 新增 `_coverage_flag(data)` helper，`partial_coverage`
  為真時在族群名稱旁加一個 ⚠ icon（hover 顯示提示文字），套用到 Section 1（外資連買/
  連賣）、Section 3（投信加碼彙總）、Section 3.5（越跌越買）、Section 5（籌碼集中度）
  四個會顯示這些數字的表格
- 新增測試：`processors/performance.py` 4 個（全涵蓋/TPEx institutional 缺失/TPEx
  margin 缺失/單一交易所族群不誤判），`chips_generator.py` 3 個（flag 本身邏輯 + 
  實際 generate() 輸出驗證，含驗證「正常族群不會被誤標」）
- **注意**：`calc_meta_chips_signals()` 原本完全沒有任何測試（這次順便補上第一批），
  這次新增的 4 個測試也涵蓋了既有的「分母動態排除」行為，不是只測新功能

### 資料來源相關（如有異動）
- 不適用——這次是籌碼資料呈現層的防呆修復跟純重構，不是資料抓取邏輯，
  TWSE/TPEx/FinMind 規則沒有變動

### 請 Debugger 驗證
- [ ] 全專案 92 個測試都過（原 85 + 新增 7 個：`test_processors.py` 4 個、
  `test_chips_generator.py` 3 個）
- [ ] 確認 `chips_generator.py` 拆函式前後輸出完全一致（我已經用逐 byte 比對驗證過，
  Debugger 可以用同樣手法：checkout 前一版 `export/chips_generator.py` 到另一個檔名，
  餵同一組測試資料分別呼叫兩邊的 `generate()`，比對輸出字串是否相同）
- [ ] 確認 `partial_coverage` 的判斷邏輯：族群本來就只有單一交易所成分股時
  **不會**被誤標（這是我特別加測試驗證的邊界情況，避免把「正常狀態」誤判成
  「資料缺失警示」，反而製造出新的誤導性警示噪音）
- [ ] 建議找一天 TPEx 資料真的有缺失/延遲的實際情境，用真實 `data/screener.db`
  跑一次 `main.py`，確認 `docs/chips.html` 上真的會出現 ⚠ icon（我這邊只能用合成測試
  資料驗證邏輯，沒辦法在本機重現真實的 TPEx 抓取失敗情境）

### 特別注意
- `partial_coverage` 目前只是「有沒有缺」的布林值，沒有進一步區分「institutional 缺」
  還是「margin 缺」（兩者合併成同一個旗標）。如果之後想要更精細的提示文字（例如區分
  「外資/投信數字可能不完整」vs「融資數字可能不完整」），要拆成
  `inst_partial_coverage`/`margin_partial_coverage` 兩個獨立欄位，目前的實作已經內部
  算出這兩個中間值（`inst_partial`/`margin_partial`），只是最後合併輸出，要拆分不難
- 這次的 `_coverage_flag()` 沒有套用到 Section 6（法人持續買進個股，`inst_scan` 個股
  層級資料）跟 Section 8（大戶持倉），因為這兩個 section 的資料結構跟來源不同
  （個股層級 `inst_scan`、集保週資料 `shareholder_data`），沒有現成的 `partial_coverage`
  欄位可用，這次範圍只涵蓋族群層級（`meta_chips`）的四個 section

---

## [2026-07-05] 籌碼面 code review 三項修復：XSS 跳脫、chips.html 靜默失敗、week_chg NaN

### 改了什麼
- 異動檔案：`export/chips_generator.py`、`export/html_generator.py`、`main.py`、
  `tests/test_shareholder.py`；新增 `tests/test_chips_generator.py`、
  `tests/test_html_generator.py`

**背景**：Cody 要求對籌碼面（三大法人/融資融券/大戶持倉）程式碼做 review，同時跑了
code-reviewer 跟 security-reviewer 兩個 agent。挑出其中 3 項優先修復：

**1. Stored XSS：`chips.html`／`index.html` 對外部字串完全沒有 HTML escape**
`export/chips_generator.py` 全檔案原本沒有任何 `html.escape()`，`stock_name`／
`meta_sector` 等來自 TWSE/TPEx API 回應的字串直接被塞進 f-string HTML。這兩個檔案
產生的頁面都會發布到 GitHub Pages，如果哪天 API 回應被竄改（中間人攻擊，配合 repo 裡
既有的 `verify=False` 關閉 TLS 憑證驗證），就能把 `<script>` 注入到公開頁面。
- 新增 `_esc()` helper（`html.escape()` 包一層，處理 `None`/空字串），套用到：
  - `chips_generator.py`：`_meta_link()` 的族群名稱、6 個表格函式的 `stock_id`／
    `stock_name`（`_stock_rank_table`／`_inst_strong_table`／`_inst_streak_table`／
    `_margin_alert_table`／`_margin_divergence_table`／`_shareholder_table`）
  - `html_generator.py`：`_stock_card_html()`／`_meta_card()`／`_stock_table()`／
    `_sector_row()`／`_sector_mini_card()`／`_top10_card()`／`_meta_stock_cards()` 等
    處的 `stock_name`／`sector_name`／`meta_name` 文字節點跟屬性；原本 3 處手動
    `.replace('"', "&quot;")`（只擋雙引號，不是完整跳脫）統一改成 `_esc()`
  - `html_generator.py` 額外發現一個更嚴重的變體：`STOCK_INDEX`／`META_INDEX` 是直接
    用 `json.dumps()` 內嵌進 `<script>` 標籤（不是走 `innerHTML`），`json.dumps` 預設
    不會跳脫 `</`，如果股票名稱剛好含 `</script>` 會提前結束該 script 區塊、讓後面
    內容被當成新 HTML 解析——比純文字節點注入更嚴重（可以直接執行任意 JS）。修法：
    `json.dumps(...).replace("</", "<\\/")`
  - **注意**：`verify=False`（TLS 憑證驗證關閉）**沒有動**——這是 2026-07-01 commit
    `2620c3a` 為了修 Windows 上 TWSE SSL handshake 失敗刻意加的，我沒辦法在這裡驗證
    拿掉會不會讓 Cody 實際的爬蟲又壞掉（需要真的連線測試），所以只把可測試、能確定
    安全的「跳脫」這部分修掉，TLS 驗證要不要重新啟用留給 Cody 自己決定/測試
- 新增 `tests/test_chips_generator.py`、`tests/test_html_generator.py`（這兩個產生器
  原本完全沒有測試），涵蓋惡意字串注入、`</script>` 提前結束攻擊

**2. `docs/chips.html` 產生失敗會被靜默記成成功**
`generate_chips_html()` 原本無論「真的寫檔」還是「meta_chips/stock_chips 皆空所以
不寫檔」都回傳 `None`，`main.py` 呼叫後無條件 log 成功。改成 `generate()` 回傳
`bool`（`True`=有寫檔，`False`=靜默跳過），`main.py` 依回傳值決定 log 成功還是警告。

**3. `week_chg` 的 `NaN`（不是 `None`）繞過 `main.py:517` 的 `is not None` 檢查**
跟先前修過的 `pd.NA or 0` 那個 bug 同一類，只是這次是 DuckDB DOUBLE `NULL` 經
pandas `.df()` 轉換後變成 `float('nan')`，不是 `None`。`week_chg is not None` 誤判
成「有值」，會讓 `nan` 流到 `chips_generator.py`，可能渲染出字面上的 `"nan%"`。改成
`None if pd.isna(row["week_chg"]) else float(row["week_chg"])`，跟專案已建立的
`pd.isna()` 慣例一致。新增測試直接驗證 DuckDB NULL DOUBLE 的真實 round-trip 行為，
並證明舊寫法真的會讓 `nan` 流過去（不是臆測）。

### 資料來源相關（如有異動）
- 不適用——這次是 HTML 產生層的安全性/正確性修復，不是資料抓取邏輯，TWSE/TPEx/FinMind
  規則沒有變動

### 請 Debugger 驗證
- [x] 全專案 85 個測試都過（原 75 + 新增 10 個：`test_chips_generator.py` 5 個、
  `test_html_generator.py` 4 個、`test_shareholder.py` 新增 1 個）
  - ✅ Debugger 2026-07-05：84 過、1 個既有環境限制（`test_scan_patterns_returns_list` 需要
    本機真的有 `data/screener.db`，debug 資料夾沒有，跟這次修復無關，前幾則任務都碰過同一個）。
- [x] 確認 `export/chips_generator.py`、`export/html_generator.py` 產生的頁面視覺上
  沒有變化（`_esc()` 只影響含特殊字元的輸入才會改變輸出，正常股票/族群名稱沒有
  `<`/`>`/`&`/`"` 字元，輸出應該完全一樣）
  - ✅ Debugger 2026-07-05：直接呼叫 `_esc()` 實測：正常字串（台積電、2330、半導體設備）原樣
    輸出不變；`None`/`""` 正確轉空字串；`<script>alert(1)</script>` 正確跳脫成
    `&lt;script&gt;...`。`json.dumps(...).replace("</", "<\/")` 那個修法也實測過：正常資料
    JSON 結構不變，惡意 `</script>` 序列正確變成 `<\/script>`，不會提前結束 script 區塊。
    🟡 小發現：`_esc()` 用 `if value else ""` 判斷，如果哪天被拿去處理整數 `0`／`False`
    這種合法但 falsy 的值會被誤轉成空字串——目前所有呼叫端都只餵字串（stock_id/stock_name/
    族群名），不會踩到，純粹提醒以後擴充用途時注意。
- [x] `main.py::_push_html()` 之後，確認 `docs/chips.html` 正常產生（`chips_html_written`
  分支邏輯沒有反過來）
  - ✅ Debugger 2026-07-05：讀過 `main.py:528-532`，`if chips_html_written: log 成功 else: log
    警告`，方向正確沒有反過來；`chips_generator.py::generate()` 也確認兩空提前 `return False`、
    正常寫檔 `return True`，跟 docstring 描述一致。
- **留給 Cody 決定**：`verify=False`（TLS 驗證關閉）這個殘留風險要不要處理——如果
  要修，需要 Cody 自己在有真實網路環境的機器上測試拿掉 `verify=False` 後
  TWSE/TPEx/TDCC 的請求還會不會成功（2026-07-01 加上去是為了修 Windows SSL handshake
  失敗，不確定現在還需不需要）

### 特別注意
- `chips_generator.py`／`html_generator.py` 這兩個函式裡都已經用 `html` 當本地變數名
  （組 HTML 字串的累加器），所以不能直接 `import html`，改用
  `from html import escape as _html_escape` 避免命名衝突，這是刻意的寫法不是筆誤
- 這是「同一類 nullable 資料」問題第三次出現（`pd.NA or 0`、`get_chips_today` FULL
  OUTER JOIN、現在這個 DuckDB DOUBLE NULL → NaN）。以後任何從 DuckDB 讀出來、可能是
  NULL 的欄位，一律用 `pd.isna()` 判斷，不要用 `is not None` 或 `x or default`

---

## [2026-07-05] 修 TDCC 集保抓取的重試機制形同虛設（`scrapers/shareholder.py`）

### 改了什麼
- 異動檔案：`scrapers/shareholder.py`、`tests/test_shareholder.py`（commit `e52d085`）
- Cody 反映「大戶持倉那邊資料來源邏輯有 bug」，照 `superpowers:systematic-debugging` 走完整
  流程（沒有直接猜答案）：
  1. **Phase 1 根因調查**：仔細讀 `_fetch_one_stock()` 跟 `fetch_shareholder_weekly()` 的
     控制流程，發現 `_fetch_one_stock()` 內部自己包了一層 `try/except Exception: return
     None`，把 POST 階段的例外（`ConnectionError`/`SSLError`/`Timeout`/`HTTPError`）整個吞掉。
  2. **Phase 2 模式比對**：對照同一份檔案註解裡提到的參考模式（`scrapers/backfill.py`
     `_fetch_yfinance_one_stock`），發現參考實作是「重試迴圈跟實際網路請求在同一層」，
     中間沒有吞例外的 try/except——`shareholder.py` 沒有正確比照這個模式。
  3. **Phase 3 假設驗證**：外層 `fetch_shareholder_weekly()` 的 `for attempt in
     range(_MAX_RETRIES)` 重試迴圈，靠 `except Exception` 接住 `_fetch_one_stock()` 拋出
     的例外才會觸發重試。但因為內層已經把例外吞掉變成 `return None`，外層的 try 區塊永遠
     不會拋例外、`ok=True` 在第一次嘗試就成立、`break` 直接跳出——重試機制對 POST 階段的
     暫時性失敗**完全沒有作用**，等同於當初這個重試機制要修的「零重試，穩定失敗
     ~2.4%/週」問題原封不動地還在，只是被表面上看起來「有重試」的程式碼掩蓋住了。
  4. **Phase 4 修復**：拿掉 `_fetch_one_stock()` 內部那層 try/except，讓例外正常往上冒給
     外層重試迴圈接住重打。解析階段（`<2 tables`／`no rows`／`total_shares==0`）維持回傳
     `None`（這些是真的沒資料，不是暫時性失敗，不需要重試）。
- 新增回歸測試 `test_transient_post_failure_is_retried`：模擬第一次 `s.post()` 拋
  `ConnectionError`、第二次成功回傳合法 HTML，驗證重試迴圈真的會打第二次（`call_count
  == 2`），不是被內層默默吞掉直接判定「無資料」放棄（修復前這個測試會在 `call_count==1`
  時就失敗，正確重現原始 bug）。

### 資料來源相關（如有異動）
- 上櫃／上市：不適用——這是 TDCC 集保資料抓取的網路層重試邏輯，不是資料轉換或口徑問題

### 請 Debugger 驗證
- [ ] 全專案測試（含新增的 `test_transient_post_failure_is_retried`）都過——我只用邏輯
  推演＋`ast.parse` 語法檢查驗證過，沒有實際跑 pytest（照分工這是 Debugger 職責）
- [ ] 確認拿掉內層 try/except 後，「真的沒資料」的情境（`<2 tables`／`no rows`／
  `total_shares==0`）還是不會被誤判成需要重試——這些分支我沒有動，維持回傳 `None`
- [ ] 如果方便，實際跑一次 `--update-shareholder` 或 `--backfill-shareholder`，觀察 log
  裡「重試」相關訊息是否真的在遇到暫時性錯誤時觸發（這個修復理論上應該會讓每週實際失敗率
  比之前更低，但我這邊沒有真的重現一次 TDCC 端的暫時性失敗來驗證效果）

### 特別注意
- 這個 bug 很隱蔽：外層重試迴圈的程式碼「看起來」完全正確（`_MAX_RETRIES`、退避重試、
  註解都寫得很清楚），唯一的問題是內層把例外攔截掉了，讓外層的 except 分支永遠不會被
  觸發。以後如果又遇到「重試機制寫了但好像沒生效」的情況，第一件事是檢查**呼叫鏈中每一層
  是不是都有 try/except**，只要中間有任何一層把例外吞掉變成正常回傳值，上層的重試/例外
  處理邏輯就會失效但不會報錯，非常容易被忽略
- 這次沒有動 `main.py` 的兩個呼叫端（`_update_shareholder()`／`_backfill_shareholder()`），
  它們都只是消費 `fetch_shareholder_weekly()` 的回傳 list，介面沒有變

---

## [2026-07-05] 小重構：`html_generator.py::_na()` 抽成 module-level 共用函式

### 改了什麼
- 異動檔案：`export/html_generator.py`（commit `ed7ce57`）
- 對照 bug-reports.md 2026-07-05 那則 🟡 建議：`_na(v): return 0 if (v is None or pd.isna(v)) else v` 原本在檔案裡 3 個地方（196/330/513 行附近）各自重複定義成 nested function，內容完全一樣。改成跟 `_pct_color`/`_pct_cell`/`_heatmap_bg` 同一種寫法的 module-level 函式（檔案開頭），3 處呼叫端直接沿用，刪掉重複定義。
- 純重構，沒有改變任何邏輯或輸出結果。

### 資料來源相關（如有異動）
- 不適用——純程式碼整理，不碰資料抓取或轉換邏輯

### 請 Debugger 驗證
- [ ] 確認 3 處呼叫端（原本 196/330/513 行附近）行為跟修改前完全一致（`fn`/`tn`/`mb`/`mc` 的計算結果不變）
- [ ] 全專案測試通過（我只做了 `ast.parse` 語法檢查，沒有實跑測試——照分工這是 Debugger 的職責）

### 特別注意
- 這台機器（`liuyantingdeMacBook-Pro`）沒有找到 `../tw-sector-tracker-debug` worktree，無法照流程主動 merge 過去，麻煩 Debugger 端自己 `git merge master` 同步

---

## [2026-07-05] 首頁改回舊版 html_generator 產生，React 前端整個移到獨立分支（Cody 決定復原）

### 改了什麼
- 異動檔案：`main.py`、`processors/performance.py`、`tests/test_processors.py`；刪除
  `frontend/`、`export/data_generator.py`、`tests/test_data_generator.py`、`docs/data.json`、
  `docs/assets/`；`docs/index.html` 重新用舊版產生器產生

**背景**：Cody 實際打開新版 React 首頁後，覺得視覺比舊版陽春很多（Task 14 當初只做了最基本的
版面 CSS，沒有移植舊版的字體/卡片質感/hover 效果），且 React 需要多一道 `npm run build` 才能
部署，覺得不划算，決定整個復原成舊版 `export/html_generator.py` 直接產生 `docs/index.html` 的
方式。

**怎麼做的**：
1. 先把當時做到一半、還沒 commit 的視覺調整（字體/配色移植）commit 起來，確保不遺失
2. 從 master 當下的狀態切一個 `react-frontend-redesign` 分支，**完整保留**這次前端重構的所有
   歷史（Task 1-14 全部 commit、我做的視覺調整 wip），沒有任何東西被刪除或遺失，只是不再是
   master 的一部分
3. master 上：
   - `main.py` 恢復呼叫 `generate_html()`（舊版單檔 HTML 產生器），移除
     `generate_data_json()`／`calc_weekly_rank` 的接線和 `_push_html()` 對 `docs/data.json`／
     `docs/assets` 的處理
   - 刪除 `frontend/`、`export/data_generator.py`、`tests/test_data_generator.py`、
     `docs/data.json`、`docs/assets/`（全部在 `react-frontend-redesign` 分支上還在）
   - `processors/performance.py` 移除只有前端在用的 `calc_weekly_rank()`，一併移除對應測試
   - `docs/index.html` 用舊版產生器重新產生一份有效內容（避免殘留參照到已刪除 JS/CSS 資產的
     破損版本）

**過程中的意外插曲（結果是好的，但記錄下來避免以後誤會）**：
在我改到一半、`git rm --cached` 已經把 `frontend/`／`docs/assets` 等的刪除**暫存**在 git index
但還沒 commit 的當下，Cody 在另一個 terminal 剛好也跑了 `python main.py`。因為 Python 是直接讀
磁碟上的檔案（不是讀 git 已 commit 的版本），那次執行用的是我當下已經改好、但還沒 commit 的新版
`main.py`（已經改回呼叫 `generate_html()`），所以順利用舊版產生器重新產生了 `docs/index.html`。
但 `_push_html()` 的 `git commit` 沒有限定檔案、會把當下 git index 裡「所有」已暫存的變更一起
提交——結果就是 Cody 那次的 `update: sector performance 2026-07-03` 自動 commit，意外地把我
`git rm --cached` 暫存的刪除也一起帶進去 push 上去了。事後檢查確認結果是對的（`frontend/`／
`data_generator.py`／`docs/data.json`／`docs/assets` 確實被刪除，`docs/index.html` 確實是用舊
版產生器產生的新內容），但這提醒了一件事：**`_push_html()` 的 `git commit` 沒有限定檔案範圍，
只要 index 裡當下有任何暫存變更（不管是誰、什麼時候 staged 的），下一次 `python main.py` 跑完
都會被一起打包 commit+push**，如果之後又遇到類似「手動 `git add`/`git rm --cached` 到一半、
main.py 剛好被跑」的情況，要注意這個副作用。

### 資料來源相關（如有異動）
- 不適用——這是首頁呈現方式的復原，不是資料抓取邏輯，TWSE/TPEx/FinMind 規則沒有變動

### 請 Debugger 驗證
- [x] 確認 `docs/index.html` 現在是舊版單檔 HTML（有 `mc-card`／`stock-card` 等舊版 class），
  不再參照任何 `docs/assets/*.js`／`*.css`
  - ✅ Debugger 2026-07-05：`grep` 確認有 `mc-card`／`stock-card`，沒有任何 `docs/assets` 參照。
- [x] 確認 `docs/chips.html`、`docs/patterns.html` 沒有受影響（這次改動不動它們）
  - ✅ Debugger 2026-07-05：`git show --stat 71aa41e` 這兩個檔案完全沒出現在 diff 裡，確認沒動到。
- [x] 全專案 75 個測試都過（移除 `calc_weekly_rank` 相關 2 個測試後，78→75，屬預期減少，不是
  漏測）
  - ✅ Debugger 2026-07-05：74 過、1 個既有環境限制（需要本機 `data/screener.db`，debug 資料夾
    沒有，跟這次改動無關），詳見下方 `--realtime crash` 那則任務的同項驗證。
- [x] 確認 `react-frontend-redesign` 分支確實完整保留了 Task 1-14 的所有歷史（`git log
  react-frontend-redesign --oneline` 應該看得到完整的 scaffold/元件/測試 commit 序列），沒有
  任何東西真的遺失
  - ✅ Debugger 2026-07-05：該分支（本機＋遠端都有）log 裡數到 30 個對應 Task/feat commit，完整
    保留，隨時可以切回去繼續。

### 特別注意
- 如果以後想重啟 React 前端這個方向，`react-frontend-redesign` 分支就是完整的起點，不用重做
- `main.py::_push_html()` 的 `git commit` 沒有限定檔案範圍這件事本身不是這次改動引入的新問題
  （原本就這樣寫），只是這次意外暴露出來；如果覺得這個行為本身有風險（例如以後又不小心把不相關
  的暫存變更一起 commit 上去），可以考慮改成 `git commit -- <files_to_add 的內容>` 限定範圍，
  但這次沒有動它，只是先記錄下來

---

## [2026-07-05] 修 `python main.py --realtime` crash：`TypeError: boolean value of NA is ambiguous`

### 改了什麼
- 異動檔案：`export/data_generator.py`、`tests/test_data_generator.py`

**Cody 回報的 crash**：
```
File "export\data_generator.py", line 89, in generate
    mb = int(c.get("margin_balance") or 0)
TypeError: boolean value of NA is ambiguous
```

**根因**：`screener/database.py::get_chips_today()`（第 237-253 行）用 `FULL OUTER JOIN` 合併
`institutional` 跟 `margin` 兩張表。當某支股票當天只有其中一邊有資料（例如三大法人資料進來了
但融資融券還沒更新，或反過來），缺的那一邊 DuckDB 回傳 `NULL`，轉成 pandas DataFrame 後這些
BIGINT 欄位變成 **nullable `pd.NA`**（不是 `float('nan')`）。`data_generator.py::generate()`
第 84-90 行原本寫 `int(c.get("margin_balance") or 0)`，這個寫法對 `float('nan')`（真值）沒問題，
但 `pd.NA` 的 `__bool__` 被 pandas 刻意設計成 ambiguous（拋 TypeError），`pd.NA or 0` 直接炸掉，
不是走到 `or` 的右邊而是在做真值判斷那一步就死掉。

這不是罕見 edge case——只要當天 `institutional`／`margin` 兩張表的股票清單沒有完全對齊（新上市、
下市、停止信用交易等任何原因），就會有 stock_id 只出現在其中一邊，FULL OUTER JOIN 就會產生這
種缺值列，隔天就可能再炸一次。

**修法**：新增 `_safe_int(value, default=0)` helper，用 `pd.isna(value)` 明確判斷缺值再轉型，
取代所有 `int(c.get(...) or 0)` 的寫法（`foreign_net`／`trust_net`／`margin_balance`／
`margin_change` 四個欄位全部改用同一個 helper，不是只修觸發 crash 的那一個，避免其他三個欄位
哪天也遇到同樣的缺值組合再炸一次）。
- 新增回歸測試 `test_generate_handles_na_margin_from_outer_join`：直接用 `pd.array([pd.NA],
  dtype="Int64")` 建構跟 `get_chips_today()` 實際回傳型別一致的缺值欄位，修復前會重現原始
  crash，修復後驗證缺值正確補 0、不影響有值的欄位。
- 已用獨立腳本驗證 `pd.NA or 0` 確實拋出跟 Cody 回報一模一樣的 `TypeError: boolean value of
  NA is ambiguous`，不是臆測的根因。

### 資料來源相關（如有異動）
- 不適用——這是資料層 JSON 序列化的防呆修復，不是資料抓取邏輯，TWSE/TPEx/FinMind 規則沒變動

### 請 Debugger 驗證
- [x] 全專案測試（79 個，含新增的 1 個）都過，Debugger 端建議重跑一次確認
  - ✅ Debugger 2026-07-05：現在是 75 個（`data_generator.py` 隨前端 revert 一起被刪，少的 4
    個測試是預期減少）。74 過、1 個既有環境限制（`test_scan_patterns_returns_list` 需要本機真
    的有 `data/screener.db`，debug 資料夾沒有，跟本次修復無關）。
- [x] 建議 Cody 重新跑一次 `python main.py --realtime` 確認不再 crash、`docs/data.json` 正常產出
  - ✅ Debugger 2026-07-05：不需要真的重跑去賭——`export/data_generator.py`（原本會炸的檔案）
    已經隨 commit `71aa41e`（首頁前端 revert）整支刪除，`--realtime` 現在跟平常模式共用同一個
    `run()`，都是呼叫 `generate_html()`，程式碼裡已經沒有任何地方會走到原本的 crash 路徑。
- [x] 檢查 `screener/database.py::get_chips_today()` FULL OUTER JOIN 是否還有其他呼叫端用同樣
  `... or 0` 寫法處理這張表的欄位（目前只查到 `data_generator.py` 這一處用到 `margin_balance`
  等欄位，但如果之後有新呼叫端消費這張表，要留意同樣的陷阱）
  - ✅ Debugger 2026-07-05：`get_chips_today()` 現在唯一消費端是 `main.py:430 → generate_html()`
    （`export/html_generator.py`），本來就用安全的 `_na(v): return 0 if (v is None or
    pd.isna(v)) else v`（196/330/513 行，三處重複定義但邏輯正確），沒有沿用危險寫法。另外查了
    `chips_generator.py:638`、`institutional.py:247` 類似的 `or 0`，但那邊資料源是單一表查詢、
    欄位經 `_parse_num()`/`int(...) if ... is not None else None` 保證是 plain int，不是
    FULL OUTER JOIN 產生的 nullable 型別，風險不同，不用比照修改。🟡 `_na()` 重複定義 3 次可以
    抽成共用函式，屬非阻擋建議。

### 特別注意
- 一般寫法上 `x or default` 對「缺值」的防呆假設是「缺值會是 falsy 的東西（`None`/`0`/
  `float('nan')` 沒踩到、空字串等）」，但 pandas 的 nullable 型別（`pd.NA`、`Int64`/`Float64`
  dtype）刻意讓 `bool(pd.NA)` 直接拋例外，不是回傳 `True`/`False`。以後只要資料來源可能經過
  DuckDB/pandas 的 outer join 或 nullable dtype，缺值防呆一律用 `pd.isna(x)` 明確判斷，不要用
  `x or default`。

---

## [2026-07-04] index 首頁前端重構完成（Vite + React + TypeScript，取代舊版 html_generator 產出）

### 改了什麼
- 對照 `docs/superpowers/plans/2026-07-02-index-frontend-redesign.md` Task 1-14，全部 Step 1-4（TDD：寫測試→跑失敗→實作→跑通過）已完成並逐一 commit。Task 14 Step 5（瀏覽器手動驗證）刻意留給 Cody/Debugger，不是自動化步驟。
- **資料層**：
  - `processors/performance.py::calc_weekly_rank()`（新增）— 滾動 5 日族群排名比較，供「排名升降」訊號使用
  - `export/data_generator.py`（新增）— 產生 `docs/data.json`，取代舊版直接產 `docs/index.html` 的 `html_generator.generate()` 呼叫
  - `main.py` 改呼叫 `data_generator` 而不是舊版 index HTML 產生邏輯；`_push_html()` 一併把新產出的 `docs/data.json`、`docs/assets/*` 納入 push 範圍
  - **注意**：`docs/chips.html`、`docs/patterns.html` 這兩個頁面**沒有動**，仍走舊版 `html_generator` 路徑，只有首頁 `docs/index.html` 改走新的 React 產出
- **前端（`frontend/` 目錄，全新專案）**：
  - Vite + React + TypeScript + Vitest scaffold（`frontend/package.json`、`tsconfig*.json`、`vite.config.ts`）
  - `types.ts` + `useSectorData` hook：抓 `data.json` 並轉型別
  - 純函式：`sortMetaSectors`（族群排序）、`sortStocksWithinGroups`（子族群內個股排序）
  - 元件：`SignalChips`（日/週排名升降 + 連漲連跌 + 量能異常 badge + sparkline）、`RankList`（左側族群列表，含訊號色條強度）、`SectorDetail`（依子族群分組列出個股）、`StockModal`（點個股彈窗，沿用原本 sparkline + 籌碼明細）、`SearchBar`（依族群名或任一子族群個股 id/名稱過濾）
  - `App.tsx` 用 `useMediaQuery` 做響應式雙模式（桌機左右分欄／手機單欄）串起以上所有元件
  - `App.css` 補齊基本版面 CSS（沿用 `DESIGN.md` 既有配色，沒有重新設計視覺風格）
  - 中途有一段是從 `worktree-frontend-redesign` 分支 merge 回來的 Task 4-7 部分進度（commit `50054e4`），取代本地重複 scaffold，過程中沒有邏輯衝突

### 資料來源相關（如有異動）
- 不適用 — 這次改動是「資料怎麼呈現」（HTML 產生方式），不是「資料怎麼抓」，TWSE/TPEx/FinMind 資料來源規則沒有變動

### 請 Debugger 驗證
- [ ] **Task 14 Step 5 手動驗證**（plan 裡明確留給 Cody/Debugger 的步驟，不是我漏做）：
  1. `python main.py`（確認會產生新的 `docs/data.json`）
  2. `cd frontend && npm run build`
  3. 瀏覽器打開 `docs/index.html`（或 `python -m http.server` 在 `docs/` 下起本機伺服器），確認：
     - 桌機寬度看得到左右分欄、縮小視窗看得到單欄模式
     - 點族群能看到個股、點個股能開 modal
     - 搜尋能正確過濾族群/個股
- [ ] 確認 `docs/chips.html`、`docs/patterns.html`、`docs/data.json` 這幾個舊版產出檔案沒有被新流程誤動到（Task 14 Step 2 的預期行為是「這三者不應變動」，但沒有自動化測試鎖住這件事，建議人工抽查一次 git diff）
- [ ] 全專案 78 個 Python 測試 + 前端 Vitest 套件都過（Developer 端已確認過，Debugger 端建議重跑一次確認環境一致）

### 特別注意
- 這是**新的資料流分岔點**：首頁不再是 Python 直接產生 HTML 字串，而是 Python 產 JSON → 前端 build 產靜態頁。以後改首頁視覺/互動，要改 `frontend/src/` 底下的 React 元件，不是 `export/html_generator.py`（那支現在只服務 `chips.html`/`patterns.html`）
- `frontend/` 底下有自己的 `package.json`／`node_modules`，跟專案原本的 Python 依賴（`requirements.txt`）是分開的兩套環境，Debugger 驗證時記得 `cd frontend && npm install`（如果還沒裝過）

---

## [2026-07-03] GitHub Pages 一直沒更新：改用 GitHub Actions 部署，取代卡死的舊版 Jekyll build

### 改了什麼
- 異動檔案：`docs/.nojekyll`（新增）、`.github/workflows/pages.yml`（新增）
- 另外用 `gh api -X PUT repos/coody0111/tw-sector-tracker/pages -f build_type=workflow` 把 repo 的 Pages 部署來源從「Deploy from a branch」切成「GitHub Actions」（這是 repo 設定，不是程式碼，git 不會有紀錄，特別寫在這裡備查）。

**問題現象**：Cody 反映 `https://coody0111.github.io/tw-sector-tracker/index.html` 一直沒更新，內容卡在 2026-07-01。

**排查過程**：
1. 用 `gh api repos/coody0111/tw-sector-tracker/pages/builds` 查 build 歷史，發現從 2026-07-01 17:39（commit `a920829`）最後一次成功後，之後每一次 push（含這次 session 的所有 commit）build 全部失敗，錯誤訊息只有一句無細節的「Page build failed.」。
2. 一開始懷疑是 `docs/superpowers/plans/` 底下新加的大型規劃文件（`2026-07-02-index-frontend-redesign.md` 2124 行）觸發 Jekyll 誤判 Liquid 語法，加了 `docs/.nojekyll` 試圖跳過 Jekyll 處理 → 手動觸發 build 後**仍然失敗**，證明這個假設是錯的。
3. 改用 GitHub Actions 部署（`actions/upload-pages-artifact` + `actions/deploy-pages`），觸發後又卡在 "Deploy to GitHub Pages" 步驟 in progress 好幾分鐘不動。
4. 查 `https://www.githubstatus.com/api/v2/components.json` 發現 **GitHub Pages 服務當下本身就是 `degraded_performance`**（GitHub 官方回報的服務異常，不是我們設定的問題）。等 GitHub 那邊恢復後，Actions 部署順利跑完，網站更新成功（curl 驗證內容日期變成 2026-07-03）。

**結論**：真正卡住的原因是 GitHub Pages 服務當時本身有異常（舊版 legacy build 卡死、部署鎖死），跟我們的程式碼或設定無關；`.nojekyll` 這個修正本身沒錯但不是這次的解方。順手把部署方式換成 GitHub Actions 是有價值的副產品——以後如果又卡住，Actions log 會有完整錯誤訊息可查，不會再像舊版 Jekyll build 只有一句沒有細節的錯誤。

### 資料來源相關（如有異動）
- 不適用（這是部署基礎設施，不是資料抓取邏輯）

### 請 Debugger 驗證
- [~] 下次 `python main.py` 正常執行、push 之後，確認 GitHub Actions 的 `Deploy Pages` workflow 有自動觸發並成功（`gh run list --workflow=pages.yml`），網站內容有跟著更新
  - ✅ Debugger 2026-07-03（設定）：`pages.yml` 觸發條件（push master + `docs/**`）、標準 actions、permissions 都正確。⏳ **workflow 實際執行紀錄無法在本機驗證**（`codyliu` 筆電未裝 `gh` CLI），需 Cody 在有 gh 的機器跑 `gh run list --workflow=pages.yml` 或下次 push 後看 Actions 頁。
- [x] 確認 `docs/.nojekyll` 沒有造成任何非預期副作用（理論上只是讓 GitHub 不要用 Jekyll 處理，純靜態 HTML 站不需要 Jekyll，應該無風險）
  - ✅ Debugger 2026-07-03：`docs/.nojekyll`（0 bytes）存在，純靜態 HTML/JSON 站不需 Jekyll，無風險。

### 特別注意
- workflow 觸發條件是 `push` 到 `master` 且改到 `docs/**`（見 `.github/workflows/pages.yml`），`python main.py` 每次執行完都會自動 push `docs/` 底下的產出檔案，所以正常流程下這個 workflow 會自動觸發，不需要手動介入
- 如果之後又遇到「push 了但網站沒更新」，第一步先查 `gh run list --workflow=pages.yml` 看 Actions 有沒有跑、有沒有失敗，比查舊版 `pages/builds` API 有用得多

---

## [2026-07-03] 補上櫃三大法人／融資融券資料源（TPEx OpenAPI，取代原本要接 FinMind 的規劃）

### 改了什麼
- 異動檔案：`scrapers/chips.py`、`main.py`、`processors/performance.py`、`export/chips_generator.py`

**背景**：上一則任務發現三大法人（institutional）完全沒有上櫃來源，原本規劃是要接 FinMind 補上。後來查證 TPEx 自己就有官方 OpenAPI 對應端點，比 FinMind 更好（不吃 FinMind 每日 600 次配額，資料源更直接），改用這個。

**1. `scrapers/chips.py` 新增兩支 TPEx 抓取函式**
- `fetch_institutional_tpex()`：打 `https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading`，回傳欄位對齊現有 `fetch_institutional()`（TWSE 版）：`stock_id, date, foreign_net, trust_net, dealer_net, total_net`。
  - 口徑對齊細節：TPEx 這支 API 把「外資自營商」獨立列出，TWSE T86 是併在自營商（dealer）類別下，所以 `dealer_net = ForeignDealers-Difference + Dealers-Difference`，`foreign_net` 只用不含外資自營商那個欄位，這樣兩邊 `foreign_net`/`dealer_net` 定義才一致，不會上市/上櫃資料混用出不同意義的同名欄位。已用當天全量 930 筆資料驗證 `foreign_net+trust_net+dealer_net == total_net`，0 筆誤差。
- `fetch_margin_all_tpex()`：打 `https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance`，回傳欄位對齊 `fetch_margin_all_twse()`：`stock_id, date, margin_balance, margin_change, short_balance, short_change`，單位（張）跟 TWSE MI_MARGN 一致，不用換算。已用 910 筆即時資料實測跑過，格式正確。
- 兩支 API 都**沒有日期參數，只能查「TPEx 認定的當下」**，不像 TWSE 那兩支可以帶 `date` 往前查歷史。日期用回應本身的 `Date` 欄位（民國年字串，例如 `1150702`）換算，不強塞呼叫端傳入的 `trade_date`。

**2. `main.py::_update_chips_db()` 串接**
- 在原本 TWSE 三大法人/融資融券寫入之後，各自加一段呼叫 TPEx 版函式、寫入同一張 `institutional`/`margin` 表。
- 因為 TPEx 回應的日期可能跟 TWSE 端抓到的日期對不上（TPEx 還沒更新時），兩段互相獨立，只 log 提示不對齊，不阻擋彼此。
- DELETE 語句刻意加上 `AND stock_id IN (SELECT stock_id FROM <tpex_df>)`，只刪這批 TPEx 股票 ID，避免跟同一天的 TWSE 資料互相覆蓋刪除。

**3. 回頭撤掉上一則任務的暫時性修正**
- `processors/performance.py::calc_meta_chips_signals()` 的 `meta_stock_count` 分母改回算整個族群（不再排除上櫃），因為現在上櫃資料源已經補上，不需要再靠排除分母來避免比例失真。
- `export/chips_generator.py` Section 5 表頭文字、上櫃篩選鈕旁的警語都改回去（不再是「無上櫃來源」）。

### 資料來源相關（如有異動）
- 上市資料（TWSE）：無異動，T86／MI_MARGN 原樣保留
- 上櫃資料（來源從「無」→「TPEx 官方 OpenAPI」，不是 FinMind）：新增，欄位口徑已對齊 TWSE 版本，見上方細節

### 請 Debugger 驗證
- [x] `_update_chips_db()` 實際跑一次 — 2026-07-03 已用 `python main.py` 實跑驗證（Cody 執行，我協助跑並確認結果）：
  ```
  三大法人寫入 1325 筆（TWSE，2026-07-02）
  TPEx 三大法人寫入 930 筆（2026-07-02）
  融資融券寫入 1279 筆（TWSE，2026-07-02）
  TPEx 融資融券寫入 910 筆（2026-07-02）
  ```
  查 DB 交叉比對 `stock_universe.csv`：`institutional` 表 2026-07-02 這天已同時有 511 檔 TWSE + 501 檔 TPEx（掃盤名單內），`margin` 表 499 檔 TWSE + 488 檔 TPEx。已 commit `ee09b2e` 並 push 上 GitHub Pages。
- [x] 上市/上櫃資料來源沒有混用（這次最容易出錯的地方：確認 `foreign_net`/`dealer_net` 的口徑在兩個交易所是同一個定義，不是同名不同義）——**這項我只用當天全量資料驗證了數學恆等式（見上方 commit 說明），沒有交叉比對 TPEx 官網或第三方資料源確認數字本身正確，麻煩 Debugger 額外抽查**
  - ✅ Debugger 2026-07-03 抽查：實測 TWSE T86（1325檔）+ TPEx（930檔）欄位語意。`foreign_net`/`trust_net`/`total_net` 口徑**一致**。**但 `dealer_net` 不一致**（🟡）：TWSE dealer 不含外資自營商、TPEx code 併入外資自營商，差額=外資自營商（測試日兩邊都=0）。只在 institutional.py 顯示欄位消費、不進彙總，影響小。詳見 bug-reports.md。
- [x] Section 5 族群外資買超比例，這次改回全族群分母，確認上櫃佔比高的族群（例如「資通訊/工業電腦」）比例有沒有反映出上櫃股票的買超狀況（而不是仍然被當成缺資料跳過）——今天剛好三大法人「今日尚未發布，改抓前一交易日」，`docs/chips.html` 已經是用有 TPEx 資料的 2026-07-02 產生，可以直接看現在的頁面
  - ✅ Debugger 2026-07-03：實跑 `calc_meta_chips_signals` 對正式 DB，高上櫃佔比族群買超檔數合理（軟體/雲端 49/83、MCU/嵌入式 22/27、遊戲/電競 5/17）→ TPEx 確實計入分子。🟡 但發現「TWSE/TPEx 日期不同步時買超比例會被低估」的隱患（Developer 沒測到的情境），詳見 bug-reports.md。
- [x] TPEx 回應日期跟 TWSE 對不上時（log 會印出提示）的行為是否符合預期，不會互相覆蓋或報錯中斷——這次實跑兩邊剛好都是同一天（2026-07-02），沒有實際測試到不對齊的情境
  - ✅ Debugger 2026-07-03（靜態）：`_update_chips_db` TWSE/TPEx 各寫自己日期分區，TPEx DELETE 加 `stock_id IN (...)` 範圍限定 + 兩所代號不重疊 → 不會互相覆蓋；日期不同只 `logger.info` 提示、兩段互相獨立不阻擋，行為符合預期。

### 特別注意
- **歷史資料還是有落差**：TPEx 這兩支 API 只能抓「當下」，`institutional`/`margin` 表裡今天以前的舊日期還是只有 TWSE 資料，要等每天正常執行、慢慢累積才會補齊上櫃的歷史。沒有回補（backfill）路徑可以一次補齊過去——TPEx 官方沒有提供歷史日期查詢的 openapi 端點，只能考慮之後另外找 TPEx 網站上的歷史頁面解析（非 openapi），這次沒做。
- 這則發現（三大法人完全沒有上櫃來源）本身沒有寫進 `bug-reports.md`，是這次 session 對話裡臨時發現直接動手修的，所以沒有對應的項目要勾。

---

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
- [~] `_backfill_shareholder` 修好順序後，實際跑 `--backfill-shareholder` 多週，確認 `shareholder` 表 `week_chg`/`streak` 方向正確（越新週 streak 應該累加，不是遞減）
  - ✅ Debugger 2026-07-03（程式碼）：`target_dates = list(reversed(available[:weeks]))`（main.py:260）由舊到新寫入，配合 `save_to_db` 「跟 DB 最新一筆比」的假設正確。⏳ **實跑 streak 方向待 Cody 執行 `--backfill-shareholder 8`**（逐股 2 請求×1.2s×8週≈3hr，Cody 2026-07-03 執行中）。
  - 🔧 **順帶修好 going-forward 隱患（Cody 授權）**：`_add_week_change_streak` 原本沒排除同一週，導致「每日 cron／同週重跑」時 streak 會被自己洗成 0。已加 `date < 本次週` guard + 新增 `tests/test_shareholder.py`（3 測試全過）。詳見 bug-reports.md。→ 回答 Cody「以後同資料來源 OK 嗎」：歷史+每週更新兩條路現在都正確。
- [x] Section 5 族群外資買超比例，修復前後數字對照幾個上櫃佔比高的族群（例如「資通訊/工業電腦」），確認比例有明顯回升且合理
  - ✅ Debugger 2026-07-03：實跑確認高上櫃族群買超檔數合理（見上一則 Task 的同項驗證），分母已改回全族群。
- [x] 上市/上櫃資料來源沒有混用（這次改動本身是在修正混用，不是新增混用）
- [x] 沒有影響其他模組（`universe` 這個 DataFrame 多帶一欄 `exchange`，確認沒有其他下游用到同名變數但欄位數量寫死的地方壞掉）
  - ✅ Debugger 2026-07-03：`calc_meta_chips_signals` 對正式 DB 實跑無 crash、41 族群正常回傳，`exchange` 欄沒弄壞下游。

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
  - ✅ **Debugger 2026-07-03 驗證通過**：假造 4 種零值 item（`z="0"`／五檔全 `-`／`0_0_0`／今高今開 `0`）呼叫 `_best_price` 全回 `None`→呼叫端 `price<=0` 跳過；正常盤（900.0）、漲停鎖死只有買方五檔（50.5）都正確取值。防呆有效。
  - ✅ **順帶清掉殘留髒點**：`2321` 2026-07-02 的 `close=0.0`（防呆上線前寫入的舊值）已由 Cody 授權修成 `13.9` 並 reimport。附帶發現 🟡：**FinMind 對 2321 這幾天普遍回 `close=0`**（06-26/06-29/07-01/07-02，成交量卻非零），故不能用 FinMind 值，改用其穩定真實價 13.9；建議 batch/backfill 路徑也比照 realtime 加 `close<=0` 防呆（見 bug-reports.md）。
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
  - ⚠️ **Debugger 2026-07-03 複驗發現此修正在 `codyliu` 筆電上從未生效**：`data/daily_prices/2025-04-25.csv` 仍是髒值 `2118.96`（`data/` gitignored 不隨 git 同步，修正只做在桌電）。已由 Cody 授權在筆電重修（close→`21.19`、change/pct 重算、reimport 完成），兩台現在一致。**`2321` close=0 已一併修好（見 Task ③ 註記）**。全表資料品質稽核（37 萬筆）確認硬錯誤僅 3114+2321、均已修，詳見 bug-reports.md。
