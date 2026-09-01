## [2026-07-29] 籌碼頁（chips.html）今日焦點 headline zone + 大戶持倉卡片化完成

### 背景
`docs/chips.html` 大戶持倉區塊原本是13欄密集表格，Cody 反饋「太亂了、抓不到重點」。改版
設計定案於 mockup `docs/superpowers/mockups/2026-07-23-chips-v3-final.html`（發布版
https://claude.ai/code/artifact/c5f948f5-3852-4a39-a385-d3598da65e33），拆成9-task plan
（`docs/superpowers/plans/2026-07-29-chips-headline-and-holder-redesign.md`），全部走
subagent-driven-development（implementer → spec-compliance review → code-quality review，
每個 Task 都過兩階段，發現問題就resume同一個implementer修完再review一輪，不是重派新的）。

### 改了什麼
- 新增檔案：`export/chips_headline.py`（候選觀察卡片 `build_candidate_cards()`、headline
  zone渲染 `render_headline_zone()`）、`tests/test_chips_headline.py`（6個測試）。
- 異動檔案：
  - `screener/database.py`：新增 `get_shareholder_trend(weeks=5)`，緊接在 `get_shareholder_top()`
    後面，沿用同一個 `ROW_NUMBER() OVER(PARTITION BY stock_id ORDER BY date DESC)` pattern，
    把 `rn` 上限從硬寫的2改成可設定的週數。
  - `export/chips_generator.py`：新增 `_calc_trend_svg()`（SVG viewBox座標計算，單一座標系統
    避免對不齊）、`_holder_card_html()`/`_holder_column_html()`（大戶持倉卡片渲染，取代
    `_shareholder_table()` 在 `_build_section8()` 的用途）；側欄9個分頁籤分成3組（法人動向/
    特殊型態/持股結構）；接線 `chips_headline.py` 的 headline zone 進 `generate()`，插在
    `<main>` 開頭、`exch_filter_btns` 之前。
  - `main.py`：呼叫 `get_shareholder_trend(weeks=5)`，合併進 `sh_rows` 每筆的 `"trend"` 欄位。
- 邏輯說明：
  - 候選觀察卡片資料源**完全沿用**既有 `rank_joint_buy_candidates()`（跟「法人同步觀察」分頁
    完整榜單同一份資料，同一次 `generate()` 呼叫內不重算兩次），不是重新設計排序邏輯。
  - **誠實揭露文案是強制項**：候選觀察卡片區塊固定顯示「條件篩選觀察名單，不是投資建議。
    排序邏輯尚未完成配對組／統計顯著性驗證，命中率無法保證優於隨機選股。」——因為籌碼策略的
    配對組/bootstrap/樣本外驗證都還沒做完（見下方「桌電待驗」條目），UI 不能暗示這是已證實
    有效的訊號。這段文字在 `render_headline_zone()` 裡是無條件渲染（不在任何 if 分支內），
    已用測試鎖住。
  - 大戶持倉維持「連增倉／連減倉」兩張獨立清單，不合併混排——跟現行 production 分組邏輯一致，
    只換渲染方式（表格→卡片+發散長條+近5週趨勢SVG走勢圖）。
  - `_shareholder_table()` 函式**故意保留、沒刪除**——`test_shareholder_table_*` 系列既有測試
    還在測這支函式，這次任務範圍是「新增卡片渲染路徑」不是「刪除舊表格函式」，死碼清理是獨立
    後續任務。已用 `grep -n "_shareholder_table(" export/chips_generator.py` 確認只剩函式自己
    的定義那一行，`_build_section8()` 內的呼叫已經在改用 `_holder_column_html()`。
- 這次 review 迴圈抓到並修好的問題（每個都是真的 bug，不是吹毛求疵）：
  1. **Task 3**：`_holder_card_html()` 的 `row.get('lv12_15_pct', 0)`/`row.get('close', '─')`
     用「有key就不補預設值」的 `.get(key, default)` pattern，但真實資料（`main.py`）這兩個
     欄位的值本來就可能是 `None`（key存在，值是None）——`.get(key, default)` 對這種情況完全
     沒防呆，會在 `:.1f` 格式化時 crash。已改用 `row.get(key) or 0` / 明確 `is not None` 判斷。
  2. **Task 4**：`_holder_column_html()` 的 `direction` 參數docstring聲稱「只影響空狀態文案」
     但實際空狀態文案不分方向都是同一句「無資料」——docstring跟行為不一致，已記錄但判定低風險
     延後修（只影響某一欄剛好全空的邊界情況）。
  3. **Task 5**：側欄分頁分成3組後，鍵盤導覽（ArrowLeft/Right/Home/End）用
     `document.querySelector('.tab-bar')` 綁定監聽器，分組前DOM裡只有1個`.tab-bar`所以正確，
     分組後變成3個`.tab-bar`（每組一個），`querySelector`只抓到第一組，導致另外6個分頁（特殊
     型態組+持股結構組）鍵盤導覽完全失效——已改綁 `.tab-groups`（分組後仍唯一的外層容器）。
     同時發現 mobile斷點（`max-width:1100px`）CSS沒隱藏新的分組標籤、沒把`.tab-groups`攤平成
     單一橫向卷軸列，導致手機版側欄變成3倍高、3個各自獨立卷軸的區塊——已修正CSS。這兩個都是
     code quality review抓到，不是spec review範圍（spec review只確認HTML結構符合規格，不會
     執行JS/檢查CSS視覺行為）。
  4. **Task 6**：`export/chips_headline.py` 的大戶持倉本週焦點迷你面板同樣有
     `row.get('lv12_15_pct', 0)` 的None-vs-missing bug（跟Task 3是同一類bug，不同檔案），且
     原本5個測試全部只測`holder_focus=[]`空清單，完全沒測到會踩到這個bug的populated資料分支
     ——已修正並補上用`lv12_15_pct: None`當測資的回歸測試。
  5. **Task 6 fix階段的git狀態插曲**：implementer修完bug、要commit前發現 `.git` 有進行中的
     merge（`MERGE_HEAD`存在、`tests/test_database.py`有衝突標記）——正確判斷「兩個session別
     同時動git」風險，回報BLOCKED而不是硬commit。查證後確認是Developer session的
     `git merge master`已經跑完（merge commit `109c1dd`乾淨落地，無殘留衝突），確認安全後才
     讓implementer繼續commit。沒有東西遺失或衝突。
- 全部9個Task（含2次因code review發現問題而resume修正）最終皆通過spec-compliance +
  code-quality兩階段review，判定"Ready to merge: Yes"。
- 最終 `tests/test_chips_generator.py`：**50 passed**；`tests/test_chips_headline.py`：
  **6 passed**；`tests/test_database.py`（含新增 `get_shareholder_trend()` 4個測試）；全 repo
  測試套件：**477 passed, 1 failed**（唯一failure是既有已知限制 `test_scan_patterns_returns_list`，
  需要本機 `data/screener.db`，這個debug worktree沒有，跟這次改動無關）。

### 資料來源相關（如有異動）
- 無新資料來源異動。純新增一支DB查詢函式（`get_shareholder_trend()`，讀既有 `shareholder` 表，
  沿用 `get_shareholder_top()` 已驗證過的離群值防護邏輯 `WHERE lv12_15_pct < _MAX_VALID_HOLDER_PCT`）
  + HTML/CSS/SVG組裝邏輯，不動 scrapers 層。

### 請 Debugger 驗證（桌電，這個debug worktree沒有 `data/screener.db`）
- [ ] `docs/chips.html` headline zone 是否正確顯示今日真實的候選觀察（跟「法人同步觀察」分頁
      的完整榜單前3名比對，應該一致，因為兩處資料源是同一支 `rank_joint_buy_candidates()`）
- [ ] 大戶持倉本週焦點迷你面板的5檔是否正確（依 `|week_chg|` 降冪排序前5名）
- [ ] 大戶籌碼分頁的卡片化渲染：連增倉/連減倉兩欄是否正確、發散長條方向跟數字對得起來、近5週
      趨勢走勢圖的Y軸/X軸文字是否對齊（不要只看程式碼，實際瀏覽器縮放看一次——這次開發過程中
      mockup階段真的踩過對不齊的bug，教訓是純程式碼審查抓不到視覺對齊問題）
- [ ] 側欄9個分頁分成3組（法人動向/特殊型態/持股結構）後，點擊切換分頁功能是否正常；**鍵盤
      導覽**（Tab focus到任一分頁按鈕後按ArrowLeft/ArrowRight/Home/End）在3組都要能正常切換
      （這是這次review抓到才修好的功能，麻煩實際測一次，不要只看程式碼）；手機寬度（或縮小
      瀏覽器視窗到1100px以下）確認側欄不會變成3倍高的樣子
- [ ] 誠實揭露文案「條件篩選觀察名單，不是投資建議」是否清楚可見，不會被其他元素遮住或不小心
      被使用者忽略
- [ ] `python -m pytest -q` 跑一次確認全數 PASS（除了已知限制的 `test_scan_patterns_returns_list`）

---

## [2026-07-22] 族群總覽頁（index.html）熱區格改版完成：新建 export/index_generator.py 取代 export/html_generator.py

### 背景
`docs/index.html` 從卡片式版面改成熱區格（heatmap grid）版面。視覺/互動設計定案於
`docs/superpowers/specs/2026-07-15-sector-overview-heatmap-redesign.md`（Cody 核准過的 mockup
v16/v18），這次補上技術落地決策（`docs/superpowers/specs/2026-07-22-sector-overview-heatmap-implementation-design.md`）並拆成 10-task plan（`docs/superpowers/plans/2026-07-22-sector-overview-heatmap.md`），全部走 subagent-driven-development（implementer → spec-compliance review → code-quality review，每個 Task 都過兩階段）。

### 改了什麼
- 新增檔案：`export/index_generator.py`（取代 `export/html_generator.py` 在 `main.py::run()` 的
  角色，但**舊檔案本身不刪**——沒有其他模組依賴它，保留當 rollback 用，之後想刪是獨立任務）、
  `tests/test_index_generator.py`（新檔，62 個測試）。
- 異動檔案：`processors/performance.py`（新增 `_streak_and_windows_as_of()` + 
  `calc_meta_heatgrid_windows()`，DB 查詢邏輯照專案既有分層慣例放這裡，不放 export/）、
  `main.py`（掛接新 generator，移除舊 generator 專用但現在沒人消費的死程式碼）、`DESIGN.md`
  （更新視覺規範/設計語言/版面結構反映新版面）、`screener/database.py`（修正一處過時的
  docstring）。
- 邏輯說明：
  - 轉折點偵測（族群近況「等級真的翻轉」）用**回推同一套算法**（`_streak_and_windows_as_of()`
    在「今天」跟「5個交易日前」兩個時間點各算一次），不開新的歷史快照表——這是 brainstorming
    階段跟 Cody 討論定案的技術決策。
  - `classify_tier()`（族群動能五級）是**第三套獨立分類邏輯**，跟 `scan_momentum_health()` 的
    `strength_tier`、`momentum_generator.py::classify_sector_state()` 都不共用計算依據（刻意
    設計，只吃 streak+5日窗口加速度，不查法人資料，換取41族群能快速全部算完）。
  - 異動族群快報改成**動態張數**（符合條件有幾檔顯示幾檔），不是舊 mockup 那種固定5張示範卡。
  - `generate()` 產生完整 `docs/index.html`（CSS/HTML/JS 一次組裝），個股點開面板走原生
    `<details>` 展開邏輯 + JS `selectGroup()` 原地插入到被點卡片那一整排正下方。
- 這次 review 迴圈抓到並修好的問題（比照逆轟策略 v2 的模式，每個都是真的 bug，不是吹毛求疵）：
  1. **Task 1**：`_streak_and_windows_as_of()` 只防「歷史太短」，沒防 `cutoff_index` 跟
     `daily_pcts` 長度對不上的情況，會悄悄回傳假資料而非 `None`——已補邊界防呆。
  2. **Task 2**：`calc_meta_heatgrid_windows()` 的 `fillna(0.0)` 會讓剛掛牌、視窗內有真實缺值
     的族群被當成「有平盤資料」算出看似有效但其實是假數字的 streak/window_pct——已補
     `_window_is_real()` 逐視窗真實性檢查；同時補上跟其他姊妹函式一致的 DB 查詢 fail-soft。
  3. **Task 3**：`classify_tier()` 的 `accel>=-2`（強）跟 `accel<-2`（弱）在 `accel==-2.0` 時
     依 streak 正負會產生不對稱結果——已補邊界值回歸測試鎖住這個行為，避免以後被誤「統一」
     運算子改壞。
  4. **Task 4**：implementer 自己抓到並回報一個我（規劃者）寫在 plan 裡的測試資料 bug（數字
     湊不出預期的 tier），已確認並修正測資，不是隱瞞硬過。同時補了「族群完全缺 signals/windows
     資料」的回歸測試。
  5. **Task 4→Task 6（跨 Task 提前發現）**：`build_sector_recap()` 原規格讓
     `turning_points` 吃未過濾的 `heatgrid_windows`，會跟已經用 `meta_perf` 過濾過的
     `hot_top5`/`cold_top5` 產生「同一個回傳值裡對『族群是否還在追蹤』認定自相矛盾」的情況——
     Task 6 開始實作前就先把 plan 規格修正掉，沒有等實作完才回頭補。
  6. **Task 8（最大、安全性最重要的 Task）**：
     - 一開始 implementer 正確擋下一個 plan 自己的測試 bug——`stock_name` 故意不做 Python 端
       HTML escape、只靠 `<script>` 標籤邊界安全 + JS 端 `escHtml()` 在真正插入 DOM 前才轉義
       （這是防禦層次正確的設計，跟 `chips_generator.py`/`html_generator.py` 既有慣例一致），
       但原本的測試斷言「這個字串完全不能出現在整份文件裡」，忽略了它安全地出現在
       `<script>` 內嵌 JSON 資料裡是預期行為——已確認並修正測試，不是改設計。
     - Code quality review 額外抓到 3 個真的問題：`.heat-tile`/`.anomaly-card` 只有
       `onclick` 沒有 `onkeydown`，鍵盤使用者對不到（跟 `html_generator.py` 既有的
       `role="button"+onkeydown` 慣例是倒退）——已補上；`-0.0`（浮點負零）手動組
       `"+"` 符號再讓 `:.2f` 格式化會產生 `"+-0.00%"` 這種語法矛盾的雙重符號——已改用
       Python 原生 `:+.2f` 格式旗標；6 個 `generate()` 測試全部只測「沒資料」空狀態分支，
       tier/temp/法人badge/週對比等 populated 分支完全沒被測到——已補測試。
  7. **Task 9**：main.py 接線後，`stock_sparklines`/`rolling_returns`/`vol_signals`
     三段計算變成沒人消費的死程式碼（舊 generator 的參數，新 generator 不吃）——已移除；
     `universe_df` 可能是 `None`（`data/stock_universe.csv` 不存在時），新 `generate()`
     沒有 None 防呆會直接 crash（舊版有）——已在呼叫端補 guard。
  8. **收尾 holistic review**：發現並修正 2 處文件不準確——`DESIGN.md` 的 border-2 hover
     色碼誤打成 `--down` 的綠色值；`get_rolling_returns()` docstring 宣稱 index.html 仍呼叫
     本函式，但新版 `build_stock_detail_data()` 已改用單日 `change_pct`，不再呼叫。
- 最終 `tests/test_index_generator.py`：**62 passed**；`tests/test_processors.py`：**40 passed**
  （含新增的 `_streak_and_windows_as_of`/`calc_meta_heatgrid_windows` 相關測試）；全 repo 測試
  套件：**385 passed**（1個既有跟這次改動無關的 pandas FutureWarning）。

### 資料來源相關（如有異動）
- 上市資料（TWSE）：無新資料來源異動，純計算邏輯+HTML組裝，讀既有 `daily_prices` 表。
- 上櫃資料（TPEx / FinMind）：同上，無異動。

### 請 Debugger 驗證
- [ ] `docs/index.html` 實際跑一次 `python main.py` 產生真實頁面後肉眼檢查（debug worktree
      沒有 `data/screener.db`，這步可能又要等桌電真實資料，跟逆轟策略 v2 那次一樣的限制）：
  - 41 個族群熱區格全部有卡片，點擊能正確展開個股清單
  - 動能五級標籤（超強/強/整理/弱/超弱）跟溫度變化徽章（🔥/❄️）看起來合理
  - 異動族群快報、族群近況（升溫/退燒Top5+轉折點）有沒有資料都不出錯
  - 鍵盤操作：Tab focus 到熱區格卡片後按 Enter/Space 能不能正確展開（這是這次 review 抓到
    才補上的功能，麻煩實際測一次，不要只看程式碼）
- [ ] 4 個頁面（index/chips/patterns/momentum）nav 互連是否還正常（這次沒動 nav，理論上不受
      影響，但改了 index.html 的 generator 保險起見確認一次）
- [ ] `python -m pytest tests/test_index_generator.py tests/test_processors.py -q` 跑一次確認
      62 + 40 passed
- [ ] `python -m pytest -q` 全套件確認 385 passed

### 特別注意
- **`export/html_generator.py` 保留、沒刪**：目前沒有任何程式碼路徑呼叫它了（`main.py` 已
  改呼叫新的 `index_generator.py`），純粹當 rollback 用。如果新版跑一陣子確認沒問題，之後
  可以開一個獨立任務把它跟 `tests/test_html_generator.py` 一起刪掉，這次沒做。
- `classify_tier`/`classify_temp`/異動族群三個門檻（量比≥1.5x、排名跳動≥10、streak≥5）全部
  是視覺 spec 定的經驗法則草案，**沒有回測驗證**，跟逆轟策略 v2 的草案門檻同一個立場——
  這次只驗證程式邏輯符合 spec，不代表門檻數值本身合理。
- 過程中發現一個第三方工具安裝的插曲（跟這次程式改動無關，純記錄）：桌電裝了 `claude-swap`
  （`cswap` 指令）方便切換多個 Claude Code 帳號，跟這次程式碼變動無關，不用管。

---

## [2026-07-20] 修 - TAIEX完全抓取失敗時market_permission()誤判selective（Debugger回報，已修）

### 背景
接續下方 2026-07-19 條目，Debugger 驗證回報了一個真的 bug（不是「是否可接受」的行為，
Debugger 明確建議修），Cody 授權直接修。

### 🔴 問題
- 位置：`export/momentum_generator.py::market_permission()`
- TAIEX 整支 API 抓取失敗時，`main.py` 的 `market_regime` 會是 `None`，呼叫
  `market_permission(market_regime or {}, index_date=None, ...)` 傳進去是空 dict。
- 原本邏輯：`index_date is None` 會跳過日期一致性檢查，接著落到
  `tier = market_regime.get("tier", "持平")`——空 dict 沒有 `"tier"`，套用預設值「持平」→
  `permission="selective"` → 誤輸出完整操作文案「只看條件完整的強勢候選；訊號不足的個股維持
  觀察，不追價。」
- 對照組：TAIEX**有**抓到、但日期跟個股行情對不上時，正確降級成 `unknown`、`advice_text=""`。
- 結果：資料**更不完整**（整支 API 失敗）反而比「日期部分不一致」**更寬鬆**、還會輸出一段
  像正常運作時才會出現的操作建議，方向跟保守設計相反。

### ✅ 修法
- `market_permission()` 開頭新增 guard：`market_regime` 為空或缺 `"tier"` 欄位時，一律直接
  回傳 `permission="unknown"`、`advice_text=""`，不落到 tier 預設值分支。
- 新增 2 個回歸測試：`test_market_permission_unknown_when_market_regime_empty`（空dict）、
  `test_market_permission_unknown_when_tier_key_missing`（非空但缺tier欄位）。
- `tests/test_momentum_generator.py`：43 passed（41→43）；全專案 `pytest -q`：**338 passed**
  （336→338，1個既有無關warning）。

### 請 Debugger 驗證
- [ ] 確認這個修法符合你原本建議的方向
- [ ] `python -m pytest tests/test_momentum_generator.py -q` 跑一次確認 43 passed

---

## [2026-07-19] 逆轟策略 v2 Plan 3/3（generator + UI 整合）完成：新增 docs/momentum.html

### 改了什麼
- 新增檔案：`export/momentum_generator.py`（新檔案，比照 `chips_generator.py`/`patterns_generator.py`
  自成一檔慣例；純函式業務邏輯層 + `generate()` 產生 `docs/momentum.html`）。
- 異動檔案：`export/html_generator.py`（`generate()` 新增可選參數 `observation_scores`，
  向後相容，缺值時退回原本 `avg_change_pct` 排序）、`export/chips_generator.py`／
  `export/patterns_generator.py`（各自 nav 加一行「逆轟策略」連結）、`main.py`（`run()` 掛接
  每日流程、`_push_html()` 納入 `docs/momentum.html`）。
- 邏輯說明：依 `docs/superpowers/plans/2026-07-19-momentum-strategy-v2-plan3.md`（6個Task，
  全部走 subagent-driven-development：implementer→spec-compliance review→code-quality
  review），設計依據 `docs/superpowers/specs/2026-07-16-momentum-strategy-page-v2-design.md`（v2，
  取代 2026-07-14/2026-07-15 兩份舊 spec）：
  - `index.html` 族群卡片排序改用 `calc_meta_observation_scores()`（首頁與逆轟頁共用同一份
    觀察分，同一次 `main.py` 呼叫只算一次，不重複開 DuckDB 連線）。
  - `momentum_generator.py` 業務邏輯：`market_permission()`（市場操作許可四級：
    normal/selective/defensive/unknown，指數與個股行情日期不同時降級 unknown、不輸出操作
    文案）、`classify_sector_state()`（族群狀態五級，草案門檻已標記待回測）、
    `determine_final_label()`（個股最終決策標籤六選一：進場候選/續強觀察/等待確認/風險升高/
    出場條件命中/跌停風險，全部非命令式文字，優先序：跌停風險 > 出場條件命中 > 進場候選六項
    閘門 > 風險升高 > 續強觀察 > 等待確認）、`selloff_risk_zone()`（急殺風險區，**用單日
    `daily_excess_pct` 不用5日 `rs_market_score`**，這是先前舊版 v1 plan 犯過的錯，這次特別
    寫回歸測試守住）、`build_streak_cards()`（連續收近漲停卡片，文案不稱「鎖死」）。
  - `generate()`：組裝成 `docs/momentum.html`，全部用原生 `<details>/<summary>` 展開列，
    不需要客戶端 JS。`BANNED_PHRASES` 常數 + 全頁回歸測試（`隨時加碼`/`一定續抱`/`直接出清`/
    `立刻砍`/`可換入`/`反手放空` 六個命令式字樣皆不得出現）。
  - `main.py::run()`：呼叫 `scan_momentum_health`/`scan_bullish_alignment_new_high`/
    `scan_consecutive_limit_up`/`calc_meta_observation_scores` 各一次，組出決策主表；
    momentum 相關程式碼整段包在 try/except，任何一步失敗只 log warning、不影響當天其餘流程
    （chips.html/patterns.html 正常產生、`_push_html` 照常執行）。
- 這次 review 迴圈額外抓到並修好 3 個問題：
  1. `determine_final_label()` 原本「風險升高」判斷式只檢查 `strength_tier=="弱"`，沒涵蓋
     `"超弱"`——目前之所以沒事是因為 `scan_momentum_health()` 目前一定讓「超弱」伴隨
     `exit_3_rule_triggered=True`（會被更高優先序的「出場條件命中」攔截），但這個函式本身
     不該依賴這個外部巧合。已修成同時涵蓋 `("弱","超弱")`，並補了假設這個巧合被打破時的
     回歸測試（commit `1aeecd8`）。
  2. `generate()` 產生的 `docs/momentum.html` 缺少 render 層級測試驗證 `rs_rank_pct=None`
     （RS樣本不足）與有值的股票混在同一張表時能正確 render 佔位符號、不會讓 `<tr>` 數量對不上
     ——已補測試（commit `8b45f61`）。
  3. `main.py` 的 momentum 區塊原本只在成功寫檔時 log info，「跑完沒出錯但 decision_table
     為空、實際沒寫檔」的情況完全沒有診斷 log——已比照既有 `chips_html_written` 慣例補上
     `elif observation_scores:` 的 warning log（commit `3ce3db9`）。
- 最終 `tests/test_momentum_generator.py`：**41 passed**；`tests/test_html_generator.py` 全部通過
  （含3個新增 observation_score 排序測試）；全 repo 測試套件：**336 passed**（1個既有跟這次
  改動無關的 pandas FutureWarning，在 `test_processors.py`，跟前兩個 Plan 完成時同一個）。
- 完成後額外做了一次全體整合review（跨9個commit的end-to-end檢查，不是逐task重複review）：
  confirm `observation_scores` 全量（不只首頁Top5）正確傳進 `build_decision_table()` 的
  `sector_states`、`BANNED_PHRASES`六個字樣全文掃描確認無漏網、`market_permission()`回傳的
  字串常值與`determine_final_label()`比對邏輯完全一致（兩邊沒有共用enum、只靠字串常值一致，
  但目前確實一致）、main.py呼叫點的參數順序/型別跟函式簽章逐一核對正確。

### 資料來源相關（如有異動）
- 上市資料（TWSE）：無新資料來源異動，純計算邏輯與HTML組裝，讀既有 `daily_prices`/
  `institutional`/`margin`（透過既有 `calc_meta_observation_scores()`/`scan_momentum_health()`
  等函式）。
- 上櫃資料（TPEx / FinMind）：同上，無異動。

### 請 Debugger 驗證
- [ ] 5因子觀察分排序 + 六級最終標籤決策邏輯是否合理（**全部標記為實驗性、待回測校準**，
      未回測驗證策略有效性，只驗證程式邏輯符合 spec）
- [ ] `docs/momentum.html` 全文搜尋確認真的沒有 `隨時加碼`/`一定續抱`/`直接出清`/`立刻砍`/
      `可換入`/`反手放空` 六個命令式字樣（`BANNED_PHRASES` 回歸測試已覆蓋，但建議實際跑一次
      `python main.py` 產生真實頁面後再肉眼複查一次，測試用的是假資料 fixture）
  - **一個需要 Debugger 特別確認的行為**（holistic review 提出，不是 bug，但需要確認是否為
    預期行為）：TAIEX 抓取完全失敗時 `market_regime=None`，此時 `market_permission()` 的
    `index_date` 也是 `None`，會跳過日期一致性檢查、直接落到預設 `tier="持平"` →
    `permission="selective"`，而不是 `"unknown"`。這代表「TAIEX完全抓不到」跟「大盤真的持平」
    在頁面上看起來一樣（都是 selective/持平），沒有明確區分「抓取失敗」的狀態。請確認這是否
    是可接受的降級行為，或是否需要額外處理。
- [ ] `index.html` 族群卡片排序改用 `observation_score` 後，實際跑一次確認排序結果符合預期
      （3個新增測試已驗證排序邏輯 + None 值處理 + 向後相容，但沒有用真實資料跑過）
- [ ] `python -m pytest tests/test_momentum_generator.py tests/test_html_generator.py -q` 跑一次
      確認 momentum_generator 41 passed、html_generator 全過
- [ ] `python -m pytest -q` 全套件確認 336 passed
- [ ] 3個既有頁面（index/chips/patterns）nav 都能正常連到 `momentum.html`，`momentum.html` 自己
      的 nav 也能連回其他3頁

### 特別注意
- 這是 v2 spec 的 **Plan 3/3（generator + UI 整合），至此 v2 spec 三個 Plan 全部完成**
  （Plan 1 資料層 `screener/signals.py`、Plan 2 觀察分 `processors/observation_scores.py`、
  Plan 3 這次）。
- v2 spec §7/§8 明確排除的項目本次**確認沒有誤做**（holistic review 已 grep 確認零殘留）：
  `scan_limit_up_unlocked()`（漲停打開階段性解讀）、紫圈／橘圈視覺徽章、任何回測驗證邏輯。
- 舊版 `docs/superpowers/plans/2026-07-16-momentum-strategy-page.md`（v2 spec 定案**前**寫的
  plan）已作廢、**這次完全沒有照那份舊 plan 實作**——那份用的是命令式文案（隨時加碼/反手放空
  等）且誤用5日 `rs_market_score`，跟這次新寫的 `momentum_generator.py` 函式名稱與邏輯完全不同、
  不相容，純粹當歷史紀錄保留，往後不要參考其程式碼。
- `calc_meta_observation_scores()` 呼叫端仍需要 `universe_df` 含 `exchange` 欄位（Plan 2 完成時
  就標注過的提醒，這次 `main.py` 接線時已確認 `data/stock_universe.csv` 實際有這個欄位、
  `usecols` 有明確列出）。

---

## [2026-07-18] 逆轟策略 v2 Plan 2/3（觀察分）完成：新增 processors/observation_scores.py

### 改了什麼
- 新增檔案：`processors/observation_scores.py`（新檔，非改既有 `processors/performance.py`——
  該檔已871行超過專案800行上限，且這次設計上完全獨立、不共用該檔任何既有函式，是自然新檔邊界）、
  `tests/test_observation_scores.py`（新檔）。
- 邏輯說明：依 `docs/superpowers/plans/2026-07-17-meta-observation-scores.md`（3個Task，全部走
  subagent-driven-development），設計依據 `docs/superpowers/specs/2026-07-17-meta-observation-scores-design.md`：
  - `_calc_price_based_factors()`：算相對強度（族群近3日累積報酬 vs universe整體，30%權重）、
    族群廣度（今日上漲比例，25%）、延續性（連漲天數封頂5天，20%）、成分股量能參與（族群集合
    量比，15%）4個因子原始值，只吃 `daily_prices`。
  - `_calc_chips_factor()`：算籌碼確認（外資買超檔數比例，10%）原始值，只吃 `institutional`/
    `margin`。**刻意獨立重寫**了 `processors/performance.py::calc_meta_chips_signals()` 裡的
    跨交易所涵蓋度判斷邏輯（`partial_coverage`），不呼叫該既有函式——換效能（單一連線）跟隔離性，
    代價是兩邊之後不會自動同步（已在檔案 docstring 明確註記）。
  - `calc_meta_observation_scores()`（公開函式，首頁+逆轟頁未來共用）：開一條 DuckDB 連線查完
    `daily_prices`/`institutional`/`margin`，呼叫上面兩支私有函式，把非0~1的因子（相對強度、量能
    參與）做「當日跨族群百分位排名」歸一化，加權算出 `observation_score`（0~100）。資料不足時
    `score_coverage` 按可用權重重算，5因子全不可用時該族群仍回傳（不從結果消失）、
    `observation_score=None`。
- 這次 review 迴圈額外抓到1個真實防呆缺口（`_calc_chips_factor()` 沒有像 `calc_meta_chips_signals()`
  原版一樣自我防呆「只用最新一天資料」，若未來呼叫端不小心傳超過一天的 institutional/margin 資料
  進去，`chips_raw` 會悄悄超過1.0、破壞0~100分數範圍的假設）——已修好並補測試（commit `cfd2bea`）。
- 最終 `tests/test_observation_scores.py`：**10 passed**；全 repo 測試套件：**285 passed**（1個既有
  跟這次改動無關的 pandas FutureWarning，在 `test_processors.py`，跟上次 Plan 1 完成時同一個）。

### 資料來源相關（如有異動）
- 上市資料（TWSE）：無新資料來源異動，純計算邏輯，讀既有 `daily_prices`/`institutional`/`margin`。
- 上櫃資料（TPEx / FinMind）：同上，無異動；`_calc_chips_factor()` 的跨交易所涵蓋度判斷邏輯有
  處理 TWSE/TPEx 資料不同步到齊的情況（沿用既有 `calc_meta_chips_signals()` 已驗證過的判斷邏輯）。

### 請 Debugger 驗證
- [ ] 5因子公式與權重是否合理（相對強度30%/廣度25%/延續性20%/量能參與15%/籌碼確認10%，
      這些數值全部標記為**實驗性、待回測校準**，見 spec §7 out of scope）
- [ ] `score_coverage` reweight 機制：缺某因子時分母是否正確排除（例如缺籌碼時應該是0.90不是1.0）
- [ ] `python -m pytest tests/test_observation_scores.py -q` 跑一次確認 10 passed
- [ ] `python -m pytest -q` 全套件確認 285 passed

### 特別注意
- 這是 v2 spec 的 **Plan 2/3（觀察分）**，Plan 3（generator+UI，把這支函式實際接進 `index.html`
  排序邏輯 + 新建 `export/momentum_generator.py`）還沒開始。
- **給 Plan 3 的重要提醒**（code review 明確標記）：`calc_meta_observation_scores(universe_df, ...)`
  的 `universe_df` 參數**必須含 `exchange` 欄位**，否則 `_calc_chips_factor()` 內部
  `universe_df[["stock_id", "meta_sector", "exchange"]]` 會直接 `KeyError` 炸掉整支函式（不只是
  籌碼那一項失效，是整個 `calc_meta_observation_scores()` 呼叫失敗）。Plan 3 接線時務必確認傳進去
  的 universe_df 來源（`data/stock_universe.csv` 讀出來的）有這個欄位。
- 沒有回測驗證這5個因子是否真的有效（跟 Plan 1 一樣，回測是獨立任務，這次全部數值都是實驗性）。

---

## [2026-07-17] 逆轟策略 v2 Plan 1/3（資料層）完成：signals.py 三支函式新增證據欄位

### 改了什麼
- 異動檔案：`screener/signals.py`、`tests/test_signals.py`
- 邏輯說明：依 `docs/superpowers/plans/2026-07-16-momentum-v2-data-layer.md`（3個Task，全部走
  subagent-driven-development：implementer→spec-compliance review→code-quality review），
  全部**只加欄位、不改既有回傳的股票集合／既有欄位語意**：
  - `scan_momentum_health()`：新增 `below_ma5`/`big_black_proxy`/`ma5_rising`/`ma10_rising`/
    `daily_excess_pct`（今日抗跈差，單日，修正原本誤用5日RS的問題）/`rs_sample_count`（族群
    RS樣本信心分母）。
  - `scan_bullish_alignment_new_high()`（B3）：新增 `volume_ratio_20d`/`volume_confirmed`
    （今日量≥前20日均量×1.5），純標記、不影響既有多頭排列+創新高的價格命中集合。
  - `scan_consecutive_limit_up()`（B5）：新增 `breakout_volume_confirmed`（連板起漲日量≥
    起點前20日均量×1.5），新增 `_LIMIT_DOWN_PCT = -9.5` 常數（暫未使用，留給 Plan 3）。
- 這次 review 迴圈**連續抓到4次同一類 bug**（nullable BIGINT/DOUBLE 欄位如 `volume`/
  `change_pct`，DuckDB→pandas NULL 有時變 `pd.NA`有時變float `NaN`，naive `float()`/`int()`/
  比較會悄悄產生錯值或直接 crash），全部修好並補了對應測試：
  1. `daily_excess_pct`：個股當日 `change_pct` 是 NaN 時洩漏成 `float('nan')` 而非 `None`
     （commit `ad1d933`）。
  2. `volume_ratio_20d`：今日 volume 是 `pd.NA` 時 `float(pd.NA)` 直接 `TypeError`（commit
     `6528bc1`，B3 amend）。
  3. `breakout_volume_confirmed`：對應位置主動預防（commit `92281b9`，B5 一開始就用同套
     pattern 防呆，含順手修掉同函式既有的 `int(today["volume"])` 未防呆問題）。
  4. `volume_declining_streak`（**既有欄位**，連板期間量能遞減判斷）：`all()` 對含 `pd.NA`
     的 list 取 `bool()` 直接 `TypeError`，會炸掉整支掃描（commit `c1ce680`）。
- 最終 `tests/test_signals.py`：25→**34 passed**；全 repo 測試套件：**275 passed**（1個既有
  跟這次改動無關的 pandas FutureWarning，在 `test_processors.py`）。

### 資料來源相關（如有異動）
- 上市資料（TWSE）：無新資料來源異動，純掃描邏輯加欄位。
- 上櫃資料（TPEx / FinMind）：同上，無異動。

### 請 Debugger 驗證
- [ ] 三支函式新增欄位的計算邏輯是否正確（尤其 `daily_excess_pct` 單日 vs 舊有 `rs_market_score`
      5日週期別搞混、B3/B5 量能門檻 1.5x／20日窗口）
- [ ] 確認**既有回傳的股票集合完全沒變**（B3/B5 新增欄位不該讓任何原本會命中的股票消失，或讓
      原本不會命中的股票冒出來）
- [ ] `python -m pytest tests/test_signals.py -q` 跑一次確認 34 passed
- [ ] `python -m pytest -q` 全套件確認 275 passed（那個 FutureWarning 是既有的，不用管）

### 特別注意
- 這是 v2 spec 的 **Plan 1/3（資料層）**，Plan 2（觀察分 `calc_meta_observation_scores()`）跟
  Plan 3（generator+UI）都還沒開始，`export/momentum_generator.py` 目前不存在，這次改動**沒有
  任何消費端**，純粹是資料層準備。
- 發現但**刻意沒動**的既有 bug（超出這次 3-task plan 範圍，留給後續獨立任務）：
  `scan_volume_turnover()`（同檔案，這次3個Task都沒碰它）的 `int(today["volume"])`
  完全沒有 NA 防呆，volume 若是 NULL 會直接讓整支 `--scan` 炸掉（比這次修的4個問題更嚴重，
  因為那4個頂多讓單一欄位變 `None`，這個是整支函式crash）。建議之後開一個小任務單獨修。
- Cody 這次明確要求「每一步驟都要 review 程式碼邏輯合不合理，不只是對照 spec 表面符合」，
  所以每個 Task 除了 spec-compliance review 外都多做了一輪聚焦邏輯正確性的 code-quality
  review，這也是為什麼能連續抓到4次同一類 bug——建議之後遇到「單一欄位新增/nullable DB欄位
  讀取」這類改動，都比照這次的兩階段 review 流程，不要只看 spec 對不對。

---

## [2026-07-16] 📋 回家再做：逆轟策略頁面 v2 實作計畫（討論定案，尚未拆 plan）

### 目標
依 **`docs/superpowers/specs/2026-07-16-momentum-strategy-page-v2-design.md`** 做出**整合版**逆轟策略頁
（每日 pipeline 產出、吃真實掃描資料）。v2 spec 為唯一準則，取代 v1（`2026-07-14` design +
`2026-07-15` visual-design）。

### ⚠️ 現況盤點（動手前先知道）
- **v2 spec 已在 master**（commit `9432e5e`，這次 pull 下來了）。
- `docs/momentum.html`（24922 行、標題「逆轟動能策略 V2」）是 **codex 手刻的靜態頁**——**沒有
  `export/momentum_generator.py`、沒接進 `main.py` pipeline、沒吃真實 scan 資料**，等於一個大 mockup。
  → **不是成品**，真正要做的是整合版 generator。視覺可參考但別當權威。
- `docs/superpowers/mockups/2026-07-16-momentum-strategy-v5-breakout-volume.html`（v5，codex 做的）
  **整份是 v1 命令式風格**（隨時加碼/直接出清/立刻砍/可換入/反手放空 全在，v2 非命令標籤 0 個）
  → **跟 v2 spec 完全對不上，丟掉不當參考**（Cody：「太爛」）。

### v2 vs v1 的核心差異（別做回舊的）
- **狀態≠命令**：拿掉所有命令文案；沒持股資料就不下「你該買賣」。§4.2 禁用字：隨時加碼/一定續抱/
  直接出清/立刻砍/可換入/反手放空（要有回歸測試掃全頁確認沒有）。
- **四層決策**：市場許可(normal/selective/defensive/unknown) → 族群優先序 → 個股技術狀態 → 
  最終非命令標籤（進場候選/續強觀察/等待確認/風險升高/出場條件命中/跌停風險）。
- **freshness**：指數/個股/法人資料日期不一致 → 許可降級 `unknown`、不輸出市場文案。
- 新增共用**觀察分** `calc_meta_observation_scores()`（30%RS+25%廣度+20%延續+15%量能+10%籌碼），
  **首頁＋逆轟頁共用**（＝先前討論的「今日重點族群」綜合分）。

### 建議拆成 3 個 plan（相依順序，回家用 writing-plans 拆）
1. **資料層**（`screener/signals.py`，全部只加欄位、向下相容 + 補測試）：
   - `scan_momentum_health()`：出場子欄位（`below_ma5`/`ma5_slope_down`/`big_black_proxy`）+
     `ma5_rising`/`ma10_rising` + **`daily_excess_pct`（今日抗跌差，單日，別再用 5 日 RS 代替）** + RS 樣本數。
   - `scan_bullish_alignment_new_high()`（B3）：加 `volume_ratio_20d` + `volume_confirmed`（≥1.5），
     **只加標記、不改既有價格命中集合**。
   - `scan_consecutive_limit_up()`（B5）：加 `breakout_volume_confirmed`（起點量≥前20日均量×1.5，
     不足回 `None`）。
   - 新增 `_LIMIT_DOWN_PCT = -9.5`（只給「跌停風險」標記，不生放空/立刻砍指令）。
2. **觀察分**（`processors/performance.py::calc_meta_observation_scores()`）：族群優先序，首頁+逆轟頁
   共用；籌碼涵蓋不完整時排除該項、不補零，顯示 `score_coverage`。可單獨驗。
3. **generator + UI**（`export/momentum_generator.py` 新建 + `main.py` 接線）：四層決策組裝、
   freshness 降級、無障礙（button/details/aria-expanded、狀態不只靠顏色）、禁用命令文案回歸測試。
   **UI 視覺用 `ui-ux-pro-max` skill 依 v2 非命令 IA 重做一版 mockup**，不沿用 v5/codex 靜態頁。

### 驗收重點（v2 spec §7 有完整清單，摘要）
- `daily_excess_pct` 用單日、不誤用 5 日 RS；小族群顯示低樣本信心（<5 檔=C，不能單靠百分位升「進場候選」）。
- B3/B5 量能 True/False/None 測試；出場子欄位與 `exit_3_rule_triggered` 完全一致。
- 全頁無 §4.2 禁用命令文案（回歸測試）；日期不一致顯示 `unknown`。
- 所有計算以 `trade_date` 截止、no look-ahead。

### 特別注意
- 回測驗證是**另一個獨立任務**（v2 spec §5、§8 明列 out of scope），別跟頁面實作綁一起。
- 動手寫 plan 前先 `git pull`（v2 spec 已在 master，但 origin 這幾天 codex/cron 很活躍，先同步）。

---

## [2026-07-16] 🖥️ 桌電待驗：籌碼策略是否真的有增益（不要只看回測平均報酬）

### 背景
- 遠端 `master` 已有 `python main.py --backtest-chips all`，會分開回測：
  `joint_buy`、`foreign_continuation`、`trust_continuation`、`margin_bearish`、
  `tdcc_accumulation`。
- 前四條中除 `margin_bearish` 是偏空風險警示外，其餘是偏多觀察；目前沒有被
  `--backtest-chips all` 納入的正式盤整策略。
- 籌碼頁已有「外資偷偷買」篩選（外資連買、近 5 日價格 -1%~+1%），但它目前只有 UI／候選清單，
  **尚未接入回測**，也沒有 `stealth_accumulation` CLI 規則。

### 請桌電端 Cody／Codex 驗證
- [ ] 先同步：`git pull origin master`，確認至少包含 commit `09ba0f4`。
- [ ] 用桌電的真實 `data/screener.db` 跑：
  `python main.py --backtest-chips all`，完整保存五條規則輸出。
- [ ] 每條規則都核對訊號筆數、**獨立訊號日數**、股票數與日期範圍；不要把同一天大量股票誤認成
  大量獨立樣本。訊號日太少或集中在單一行情時，只能標「觀察」，不能宣稱有效。
- [ ] 偏多規則檢查 D+5／D+10／D+14 的平均超額、中位數、P25/P75、勝率是否大致同方向；
  `margin_bearish` 要用「超額 < 0」的避險命中率與後續下行風險判斷，不能拿偏多勝率解讀。
- [ ] 確認偏多規則已按 D+1 開盤進場、剔除隔日漲停買不到、扣 0.6% 來回成本；
  `margin_bearish` 是持股風險警示，不模擬放空、不扣交易成本。
- [ ] 分多頭／盤整／空頭檢查穩定性；若只在多頭有效，標記為行情濾網，不算獨立籌碼優勢。
- [ ] 特別複查 no-lookahead：每個訊號日只能使用當時已發布的法人、融資與 TDCC 資料；
  法人 fallback 不得把前一發布日快照重複算成新的訊號。

### 必做的「籌碼增益」對照（這才回答籌碼是否有用）
- [ ] 為每條偏多規則做消融／對照：
  **僅價格條件** vs **僅籌碼條件** vs **價格＋籌碼完整規則**。
- [ ] 再加入同日期、同族群、相近市值／流動性／近期漲幅的配對股票；只有完整規則穩定優於
  價格-only 與配對組，才能說籌碼資訊有額外參考價值。
- [ ] 統計須按「訊號日」做 clustered bootstrap／信賴區間，避免同日股票高度相關造成假顯著。
- [ ] 用未參與訂門檻的期間做 out-of-sample 或 walk-forward；門檻小幅改動後結果若翻轉，
  應判定可能過度配適。
- [ ] 回測通過後先做 1~3 個月 paper tracking，記錄真實訊號、可成交價、滑價及 D+5/10/14，
  再決定是否提供實盤參考。

### 外資偷偷買後續缺口
- [ ] 若要驗證真正的盤整吸籌，新增 `stealth_accumulation` 回測時必須直接共用籌碼頁同一個
  eligibility helper，禁止 UI 與回測各寫一份門檻。
- [ ] 至少比較「外資連買＋盤整」vs「只有盤整」vs「只有外資連買」，確認效果不是單純低波動
  或市場 regime 造成。

### 驗收結論格式
- 每條規則最後只能標成：**有效候選／僅特定 regime 有效／樣本不足／無增益／疑似過度配適**。
- 在完成對照組、樣本外與 paper tracking 前，不得寫成「已證實可交易策略」。

---

## [2026-07-15] ✅ 追加：`print_accumulation_calibration()` 分數分桶依大盤 regime 再拆分

Cody 實跑 `python main.py --backtest-accumulation` 後看真實數字，分數分桶勝率/超額報酬幾乎打平、
看不出「分數越高越好」——討論後認為這可能是把不同大盤 regime（多頭/盤整/空頭）的訊號攤在一起看，
蓋掉了只在特定 regime 才成立的分數效應（呼應 2026-07-14 進貨分 spec「大盤 regime 相依」caveat）。
`run_backtest()`（既有、未改動）本來就有輸出 `regime` 欄位，只是 `print_accumulation_calibration()`
之前沒用到。這次補上：每個分數桶底下，若 df 有 `regime` 欄位，再依多頭/盤整/空頭各印一次。

範圍小（`screener/patterns.py` 一個函式內加約20行、`tests/test_patterns.py` 加一個測試），沒有走
完整 subagent-driven-development 流程（沒派 review subagent），只有我自己手動核對邏輯 + 語法檢查。
新測試 `test_print_accumulation_calibration_breaks_down_by_regime` 驗證了兩筆不同 regime 的訊號會
被拆成 `[60-100分/多頭]`／`[60-100分/空頭]` 分開印。既有測試（沒有 regime 欄位那筆）不受影響，
因為 `"regime" in sub.columns` 這個 guard 會讓沒有 regime 欄位時完全跳過新邏輯，行為不變。

### 請 Debugger 驗證
- [ ] `python -m pytest tests/test_patterns.py -q` 全過，尤其新增的 `test_print_accumulation_calibration_breaks_down_by_regime`
- [ ] 因為範圍小、沒走完整 review 流程，麻煩這次稍微多看一眼 `print_accumulation_calibration()` 改動的那段（分數分桶迴圈裡新增的 regime 巢狀迴圈），確認沒有把既有的「全部」彙總行邏輯弄壞

### 特別注意
- 這個改動不影響 `富鼎型邊界案例` 那段報告——只有分數分桶那段加了 regime 拆分，邊界案例維持原樣（現在因為大戶資料只有7-9週，n=0，跟這次改動無關，是資料量問題，見上面主要那則記錄）。

---

## [2026-07-15] ✅ 進貨分回測校準（plan: docs/superpowers/plans/2026-07-15-accumulation-score-backtest-calibration.md，spec: docs/superpowers/specs/2026-07-15-accumulation-score-backtest-calibration-design.md）

把 `screener/patterns.py::calc_accumulation_score()`（進貨分，2026-07-14 完成但從未被驗證過切點準不準）接進
`screener/backtest.py::run_backtest()`（2026-07-14 完成的通用回測框架），讓 Cody 能實際跑出「進貨分高的股票，
後續超額報酬是否真的比較好」的真實數字。全部用 subagent-driven-development 執行（每個 Task 一個全新
implementer subagent，做完各跑一輪 spec compliance review + code quality review，最後再跑一輪全體整合 review）。

### 4個 Task，全部 commit 到 master
1. **`_shareholder_history_index`/`_shareholder_as_of`/`_recent_return_index`/`_recent_return_as_of`**
   （`screener/patterns.py`）——大戶連增週數/當週張數變化、近5日報酬的「任意歷史日期」查詢 helper。
   既有的 `get_shareholder_top()`/`get_rolling_returns()`（`screener/database.py`）都只能查「最新」，
   回測需要查任意歷史日期，所以另寫一版（讀一次全表建索引，跟 `backtest.py::_build_price_index` 同手法，
   不是逐股逐日查 DB）。
2. **`scan_accumulation_score(db_path) -> (scanner, cache)`**（`screener/patterns.py`）——scanner 工廠。
   每天呼叫既有 `scan_institutional()` 拿外資/投信 streak，查 Task 1 的索引拿大戶/報酬，餵進既有
   `calc_accumulation_score()`。`run_backtest()` 本身只認 `sig["stock_id"]`，不會把 score 等欄位帶進輸出，
   所以用 `cache` dict（side-effect 快取）事後把完整明細 merge 回結果——**刻意不修改 `screener/backtest.py`**
   （它剛做完 Task 1-6、還在等這批一起驗）。
3. **`print_accumulation_calibration(df, cache, horizons)`**（`screener/patterns.py`）——校準報告。印兩塊：
   分數分桶（0-19/20-39/40-59/60-100）看超額報酬是否隨分數遞增；「富鼎型邊界案例」
   （`weakening=True` 但大戶當週淨增>0，之前討論過的已知懸而未決問題）單獨拉出來跟其餘樣本對照。
4. **`main.py`**——順便修好一個既有 bug：`--backtest` 呼叫 `run_backtest()` 零參數會直接 `TypeError`
   （Task 1 重構 `run_backtest` 簽章時的遺留回歸，這次順便補，不是本次新增的問題）。新增
   `--backtest-accumulation` 指令，串起上面三個新函式。

### 過程中抓到並修掉的問題
- **Task 1**：第一次 spec review 發現 subagent 的檔案 append 把新測試碼插進前一個既有測試函式中間，
  切斷它、還讓新測試多一行參照不存在變數的斷言（`NameError`）。已修復，改用真的 `pytest` 跑過確認
  （`43 passed`），不是只靠 hand-trace。
- **Task 3**：code quality review 抓到 `print_accumulation_calibration()` 裡三次分開的 `df.apply(axis=1)`
  是可測到的效能問題（合成 50萬列 benchmark 約慢20倍），已改成一次 zip-based 查表。過程中撞到跟另一個
  並行 session（debug→master 合併）的 git 分岔小插曲，該 session 自己已經 reconcile 掉
  （commit 訊息就寫「reconcile duplicate debug-merge artifact」），我事後直接讀 code 確認修復內容完好，
  沒有遺失或覆蓋任何東西。
- **最終整體 review**：抓到一個非本次新增、但值得標注的既有行為——`scan_institutional()`（既有函式）
  法人資料缺漏時會沿用前一有資料日的舊快照，導致回測報告裡的 `n`（訊號筆數）可能包含好幾天重複的
  近似分數，不是真的獨立樣本。已在 `print_accumulation_calibration()` 加一段印出的提醒文字 + docstring
  說明，避免看報告時把 `n` 偏高誤讀成樣本真的那麼獨立。

### 測試
全部 4 個 Task 都沒有自己跑 pytest 做「開發階段驗證」（照專案規則留給 Debugger），但每個 Task 的
**review 階段**（由獨立 reviewer subagent，不是實作者本人）都有真的執行 `pytest` 確認：
- Task 1 review：`43 passed`
- Task 2 review：`44 passed`（`test_patterns.py`），全專案 `242 passed`
- Task 3 review：`45 passed`（初版）；效能修復後 review 過程也用 `pytest` 確認測試仍過
- 最終整體 review：全專案 `python -m pytest tests/ -q` → **243 passed, 1 warning**（那個 warning 是
  `tests/test_processors.py` 既有的、跟這次無關的 `FutureWarning`）

### 請 Debugger 驗證
- [ ] `python -m pytest tests/ -q` 全過（243 passed 是我這邊 review 階段跑到的數字，麻煩重新確認一次）
- [ ] `screener/backtest.py` 全程沒有被這批改動碰到（已用 `git log --oneline -- screener/backtest.py` 確認過範圍內是空的，麻煩複查）
- [ ] `main.py --backtest` 修復後、`--backtest-accumulation` 新指令，語法檢查過(`py_compile`)但沒有真的跑過真實資料——**這步牽涉真的執行程式跑 `data/screener.db`，照規則留給 Cody 自己開 terminal 跑**，不是 Debugger 的驗證範圍，但麻煩留意 `python main.py --backtest-accumulation` 第一次真的跑起來的速度（`scan_institutional()` 逐日全表掃描，多年資料可能偏慢，這是已知、接受的風險，不是這次要修的東西）
- [ ] `_shareholder_as_of()`/`_recent_return_as_of()` 的「as of 歷史日期」邏輯（forward-fill 方向、no-lookahead）——這是整個功能正確性的地基，麻煩特別覆查

### 特別注意
- 這次全程用 subagent-driven-development 模式執行（4個獨立 implementer + 8輪 spec/quality review + 1輪整體 review），過程中兩次撞到跟另一個並行 session 共用 `.git` 的小狀況（都已妥善處理、沒有遺失任何東西），再次印證 CLAUDE.md「兩個 session 別同時動 git」的提醒不是空穴來風。
- `calc_accumulation_score()` 公式本身這次**沒有被修改**——這個 Task 的產出是「校準管線」本身，實際切點要不要調整，要等 Cody 用 `python main.py --backtest-accumulation` 看過真實數字之後再決定，不在本次範圍。

---

## [2026-07-15] 搜尋族群「點了沒反應」修復（export/html_generator.py）

### 改了什麼
- 異動檔案：`export/html_generator.py`（`selectSearchMeta` JS）、`tests/test_html_generator.py`（新增回歸測試）
- 邏輯說明：搜尋下拉點「族群」項目 → `selectSearchMeta(name)`，`name` 是 **meta_sector 名稱**（來自 `META_INDEX`）。
  舊 handler 卻去查 `details.group-block[data-gname="..."]`，但 `data-gname` 存的是 **SECTOR_GROUPS 大分類**名稱
  （不同 DOM 層級）→ selector 永遠命中不到 → `block=null` → 點了沒反應。
  改成委派給同檔**已驗證可用**的 `openMetaByName(name)`（鎖 `.mc-card[data-meta-name]`），跟 chips.html 連結／
  URL hash 進來走同一條路：展開該族群面板、標記 active、捲動置中。順帶清掉搜尋框＋收下拉。
- 根因跟 2026-07-09「chips.html 連買/連賣族群連結靜默失敗」同源（openMetaByName 找不到卡片），當時只修了
  連結路徑、**漏改搜尋框的 selectSearchMeta**，這次補上。

### 資料來源相關
- 無（純前端 JS handler，與 TWSE/TPEx/FinMind 資料流無關）。

### 請 Debugger 驗證
- [ ] 搜尋股票代號/名稱 → 點「族群」項目，能正確展開該族群面板並捲動定位（真瀏覽器點一次）
- [ ] 搜尋點「個股」項目仍正常開個股 modal（沒被我改壞）
- [ ] `pytest tests/test_html_generator.py`：新測試 `test_search_select_meta_selector_matches_mc_card` 通過，
      既有測試（selectSearchStock、每族群都有卡片等）不回歸
- [ ] 我**沒跑 pytest**（照專案規則留給你）；上面測試邏輯是照既有 `test_search_select_stock_selector_matches_st_row` 對稱寫的

### 特別注意
- ⚠️ **git 現況（重要）**：commit `a013e8a` 只含我這 2 個檔。工作區還有**一批不是我的、未 commit 的原始碼變更**
  （`main.py` logging 容錯、`scrapers/backfill.py`、`screener/backtest.py` scanner 可選、`processors/performance.py`、
  刪 `fix_2321.py` + 一堆 LF/CRLF 行尾雜訊）——Cody 說那是你/Debugger 的在製工作，我**完全沒動**，原封留在工作區。
- ⚠️ 期間偵測到 **main.py 自動 commit 持續在跑**（parent 從 b6e60d1→1bf4941 一直變），共用 `.git` 有並發寫入。
  我**沒 push**（等你回報 ✅ 再推）；也**沒同步 debug worktree**（避免跟你的 session 撞 git）。

---

## [2026-07-14] ✅ 回測框架 Task 4/5/6：扣成本 + regime 分段 + print_summary 升級（plan: docs/superpowers/plans/2026-07-14-backtest-framework.md Task 4-6）

一次做完剩下三個 Task（都是小改動、彼此接續，分開三個 commit 但一起送驗）：

- **Task 4**：`run_backtest(..., cost_pct: float = 0.6)`——`ret_H` 算完後扣一次來回成本（四捨五入到小數2位），
  `excess_H` 用「已扣成本的 ret」再減 `bench_H`。
- **Task 5**：新增 `_regime_at(idx_map, sorted_dates, d_ts, lookback=20, up=3.0, down=-3.0)`，用大盤等權指數
  回看 20 個交易日的累積報酬分「多頭/盤整/空頭」（資料不足回 `"?"`）；`run_backtest` 每列多一個 `regime` 欄位。
- **Task 6**：整個重寫 `print_summary()`——舊版是綁死「巨量換手」單一 scanner 的欄位（`vol_days`/`vol_multiple`/
  `entry_close`/`change_pct`/`ret_d1`...），新版改吃 Task 1-5 產出的通用欄位（`ret_H`/`excess_H`/`no_fill`/
  `regime`），預設 `skip_no_fill=True` 會先剔除漲停買不到的訊號再統計，並依 `多頭/盤整/空頭` 分段各印一次
  勝率(超額>0)/平均超額/平均報酬/期望值。空 DataFrame 安全處理，不 crash。

三個 Task 全部照 plan 裡已經寫好的程式碼實作，沒有偏離設計。

### 範圍
- **plan 到此全部做完**（Task 1-6 都已落地），剩下的是「實跑驗收」（plan 文件最後一節，拿
  `scan_volume_turnover` 包成 scanner 對真實 `data/screener.db` 實際跑一次，看巨量換手在各 regime 的
  超額報酬），這不是 Task、是驗收步驟，而且**牽涉真的跑資料**——照 CLAUDE.md「不要自己執行程式跑資料」，
  這步留給 Cody 自己開 terminal 跑。
- `screener/backtest.py` 頂部 `from screener.signals import scan_volume_turnover` 這行 import 目前在檔案內
  沒有任何地方使用（是 Task 1 就留著、給「實跑驗收」示範用的），是刻意保留、不是遺漏，plan 裡有明講。

### 測試
沒有自己跑 pytest（照專案規則留給 Debugger）。三個 Task 各自對應的測試邏輯有手動過一次：
- Task 4：`test_run_backtest_deducts_cost`——2330 D+1→D+1+5 原始報酬 10.0%，扣 0.6% 成本後應為 9.4%，
  跟斷言一致。也確認了既有的 `test_run_backtest_excess_return_vs_market`（Task 2 的測試，只驗相對關係
  不驗絕對數值）在預設 `cost_pct=0.6` 下**仍然成立**，不會因為這次改動而回歸。
- Task 5：`test_regime_at_classifies_market_trend`——大盤連續 25 天每天 +0.5%，回看 20 日累積約 +10.5%
  ≥ up(3.0) 門檻，應判「多頭」，跟斷言一致。
- Task 6：`test_print_summary_runs_with_new_columns`——兩筆訊號（一筆 no_fill=True 應被預設剔除），輸出
  應含「超額」字樣與「多頭」分段字樣；空 df 呼叫不噴例外。手動推演過整個資料流，兩個 assert 跟空 df case
  都對得上。

### 請 Debugger 驗證
- [ ] `python -m pytest tests/test_backtest.py -q` 全過（累計到這裡整個檔案應該有 9 個測試）
- [ ] 全專案 `pytest -q` 沒有其他消費端因為 `run_backtest`/`print_summary` 簽章變動而壞掉（目前搜尋沒有其他
  程式碼呼叫這兩個函式，應該無影響，但麻煩複查，尤其 `print_summary` 是**整個重寫**、舊呼叫端如果假設
  `vol_days`/`vol_multiple` 等舊欄位會直接壞）
- [ ] `cost_pct` 扣成本的時機是否合理：目前是「先扣成本得到最終 `ret_H`，`excess_H` 用扣完成本的 `ret_H` 減
  `bench_H`」，即 bench（大盤基準）本身不扣成本——這是 plan 裡的既定設計（「注意：ret 先扣成本，excess = 已扣
  成本的 ret − bench」），如果覺得不合理麻煩提出來討論，不要當 bug 直接回報
- [ ] `_regime_at` 的 `lookback=20`/`up=3.0`/`down=-3.0` 是草案切點（跟大盤分級儀表板的邏輯類似但獨立一份），
  尚未跟 `screener/patterns.py` 或既有的 `classify_market_regime`（如果有的話）比對是否該共用同一套門檻，
  這點值得跟 Cody 確認要不要統一，不算本次範圍內的 bug

### 特別注意
- `print_summary` 是**破壞性改寫**（不是加欄位）：舊版用的欄位（`vol_days`/`entry_close`/`change_pct`/
  `ret_d1`/`ret_d3`/`ret_d5`/`win_d1`...）新版完全不認得。如果現在或未來有其他程式碼手動組 DataFrame 塞給
  `print_summary()` 用舊欄位格式，會直接壞掉或印不出東西（`_block()` 對缺欄位是靜默 `continue`，不會噴例外，
  但也不會印出任何東西，容易誤以為「沒訊號」）。目前搜尋全專案沒有其他呼叫端，風險應該只存在於之後手動跑
  `print_summary` 時要記得餵新格式。
- Task 4-6 完成後，`docs/superpowers/plans/2026-07-14-backtest-framework.md` 的 Task 1-6 checkbox 都還是
  `[ ]` 未勾（跟 Task 1/2/3 之前的慣例一致，這個專案沒有回頭勾 plan 文件裡的 checkbox 的習慣，純粹用
  `debug-tasks.md` 追蹤，不是漏勾）。

---

## [2026-07-14] ✅ 回測框架 Task 3：漲停買不到剔除 no_fill（plan: docs/superpowers/plans/2026-07-14-backtest-framework.md Task 3）

`run_backtest()` 新增 `limit_up_skip: bool = True` 參數，每列多一個 `no_fill` bool 欄位：
訊號日 D 收盤 → D+1 開盤若 ≥ D 收盤 ×1.095（代表一開盤就鎖漲停，實際上根本買不到），
標記 `no_fill=True`，主結果統計時可以用這欄剔除，避免回測把「看得到但買不到」的漲停鎖死
股當成真實可執行的訊號。完全照 plan 裡 Task 3 已寫好的程式碼實作，未偏離設計。

### 範圍
- 只做 Task 3。Task 4（扣交易成本）、Task 5（regime 分段）、Task 6（`print_summary` 升級）都還沒動工。
- `no_fill` 只是**標記**，`run_backtest()` 本身**不會**自動把這些列從 DataFrame 濾掉——濾除邏輯留給呼叫端（未來 Task 6 `print_summary` 或實際校準時）決定要不要排除。

### 測試
沒有自己跑 pytest（照專案規則留給 Debugger）。手動推演測試案例：訊號日 05-01 收盤100、
D+1(05-02) 開盤110（110 ≥ 100×1.095=109.5）→ `no_fill=True`，跟 `test_run_backtest_flags_limit_up_no_fill`
的斷言一致。

### 請 Debugger 驗證
- [ ] `python -m pytest tests/test_backtest.py -q` 全過，尤其新增的 `test_run_backtest_flags_limit_up_no_fill`
- [ ] `no_fill` 判斷用的是 D 收盤（訊號日當天），不是訊號日以外的日期，跟 `_forward_return` 的 D+1 進場邏輯一致，沒有 off-by-one
- [ ] 1.095 這個漲停門檻切點是否合理（台股現制普通股漲停 10%，這裡抓 9.5% 當「幾乎鎖死」的保守門檻，plan 裡是既定切點，非本次新增判斷，如需調整麻煩另外提出不要當 bug）

### 特別注意
- `d_close`/`d1_open` 若缺值（`None`/`NaN`/新股剛掛牌），`no_fill` 直接短路成 `False`（`bool(limit_up_skip and d_close and d1_open and ...)`，任一個 falsy 就整體 False），跟既有「缺資料不 crash」慣例一致，不會誤判成鎖漲停。

---

## [2026-07-14] ✅ 回測框架 Task 2：大盤等權指數 + 超額報酬（plan: docs/superpowers/plans/2026-07-14-backtest-framework.md Task 2）

`screener/backtest.py` 新增 `_market_index()`（`daily_prices.change_pct` 逐日平均、`(1+avg/100)` 連乘出等權指數）與
`_bench_return()`（該股 D+1→D+1+horizon 同進出區間，指數同期報酬%）。`run_backtest()` 每個 horizon 多出
`bench_H`（大盤同期報酬%）、`excess_H`（`ret_H - bench_H`）兩欄。完全照 plan 裡 Task 2 已經寫好的程式碼實作，
沒有偏離設計。

### 範圍
- 只做 Task 2，plan 裡 Task 3（扣交易成本）、Task 4/5（regime 分段）都還沒動工。
- `tests/test_backtest.py` 新增 `test_run_backtest_excess_return_vs_market` + `_make_prices_with_change` helper（plan 裡原本就寫好的測試，逐字照抄，未修改）。

### 測試
沒有自己跑 pytest（照專案規則留給 Debugger）。有手動推演過測試案例數字：2330 訊號日 05-01、
D+1(05-02)開盤100進、D+1+5(05-07)收110出 → ret_5=10.0；大盤等權指數只在 05-07 被 2330 自己的
+10% 拉抬（另一檔 9999 全程不動）→ bench_5=5.0、excess_5=5.0，跟測試斷言（`bench_5>0`、
`excess_5<ret_5`、`excess_5 == ret_5-bench_5` 誤差<1e-6）對得上。

### 請 Debugger 驗證
- [ ] `python -m pytest tests/test_backtest.py -q` 全過，尤其新增的 `test_run_backtest_excess_return_vs_market`
- [ ] 全專案 `pytest -q` 沒有因為 `run_backtest()` 多了 `bench_H`/`excess_H` 欄位而破壞其他消費端（目前搜尋沒有其他程式碼呼叫 `run_backtest`，應該無影響，但麻煩複查）
- [ ] `_market_index()` 的 SQL（`AVG(change_pct) GROUP BY date`）在真實 `data/screener.db` 上跑起來不會太慢（純合成小 DB 測試沒測到效能）

### 特別注意
- 這次沒有改 `_forward_return()` 的對外行為/簽章，`test_forward_return_enters_next_day_open` 這種舊測試不受影響。
- `bench_H`/`excess_H` 在資料不足（entry/exit 指數查不到）時回 `None`，不會 crash，沿用既有「缺資料回 None」慣例。

---

## [2026-07-14] ✅ 進貨分 calc_accumulation_score() 完成（spec: docs/superpowers/specs/2026-07-14-accumulation-score-design.md）

新增純函式 `screener/patterns.py::calc_accumulation_score()`，把外資/投信連買日數、
大戶持股連增週數與當週張數變化、近5日股價報酬，綜合成 0-100 進貨分 + 狀態旗標
（`price_confirmed`/`weakening`/`label`）。只算進貨不倒扣連賣分數、價格閘門讓
「法人買但價格沒動」的分數打對折——依據逆轟動能派筆記「籌碼是配角、只給50分」的
設計原則。

### 範圍
- 只做這個純函式本身，**不整合進任何消費端**（`export/html_generator.py`、
  `export/chips_generator.py` 都未修改）——spec 明確排除 UI/視覺整合，那是後續
  `ui-ux-pro-max` 的另一關。
- 純函式不連 DB、不依賴任何全域狀態，單元測試用合成值即可涵蓋所有分支。

### 測試
`tests/test_patterns.py` 新增約 14 個測試，涵蓋：只算進貨不倒扣、價格閘門（含
`recent_return=None` 視為未 confirm）、外資來源封頂、weakening 兩種觸發條件
（外資投信皆非正 / 大戶轉負）、label 四種導出情境、`sh_streak`/`holder_net_lots` 為
None 或 NaN 不 crash。全專案 `pytest -q`：231 passed。

### 開發過程中的重要調整（跟原計畫略有出入，如實記錄）

1. **投信/大戶封頂測試覆蓋不足，只測了外資**：Task 2 code review 發現
   `test_calc_accumulation_score_caps_foreign_trust_holder_points` 這個測試名字說要測三個
   來源的封頂，但實際上 `trust_streak`/`sh_streak` 全部用預設值 0，只有外資封頂（40分）
   真的被驗證到。這是原計畫寫的測試本身的範圍限制，不是實作偏離，已知但未在這次補上
   （trust 封頂 30 分、holder 封頂 20 分尚未有專屬測試），留給之後有動這塊時一併補上。

2. **NaN guard 的兩個測試原本沒有真正驗證到防呆，事後修正**：Task 4 的
   `test_calc_accumulation_score_handles_none_sh_streak_without_crash` 跟
   `test_calc_accumulation_score_handles_nan_sh_streak_without_crash` 原始寫法（照抄計畫
   文字）用 `_base_acc_kwargs()` 預設值（`foreign_streak=0, trust_streak=0`），這剛好讓
   `weakening` 恆為 True，導致 `holder_pts` 在 NaN 值流到 `round()` 之前就被歸零短路——
   兩個測試即使拿掉 NaN guard 本身也會通過，沒有真正驗證到防呆邏輯。兩輪 code review
   都抓到這個問題，已修正（加 `foreign_streak=3` 讓 `weakening=False`），修正後獨立驗證
   過 pre-guard 版本確實會對修正後的輸入拋 `ValueError`。這是 plan 裡寫的測試輸入本身
   有缺陷，不是實作犯的錯——記錄下來避免以後看到類似「照抄 plan 但測試沒測到重點」的
   情況又重演。

3. **weakening 規則的一個真實邊界案例，Cody 已決定暫不調整**：討論這個 spec 時，Cody
   拿 spec 裡「三族群個案研究」的真實股票（富鼎 8261）當例子提出疑慮——這檔外資/投信
   都沒連買、但大戶當週實際在買（+920張），現有的 `weakening` 判斷條件
   `(foreign_streak<=0 and trust_streak<=0) or (holder_net_lots<0)` 完全沒把「大戶方向」
   納入第一個 OR 分支的判斷，導致這種「純大戶進貨、法人沒動」的情境會被判「轉弱」，
   不管分數多高都被蓋掉。**Cody 明確決定這次不改公式**——他的原則是「做任何事都要回測」，
   要等 `docs/superpowers/plans/2026-07-14-backtest-framework.md`（另一個目前完全沒動工的
   plan，通用「任意訊號 → 查後續報酬」回測框架）做出來後，才用真實歷史資料驗證這個
   weakening 規則對不對，不要憑感覺先改。這個 plan 的 `screener/patterns.py::calc_accumulation_score()`
   目前的 `weakening` 邏輯維持跟 Task 1 committed 時完全一致，全程沒有被動過。

### 請 Debugger 驗證
- [ ] `calc_accumulation_score()` 公式對照 spec（`docs/superpowers/specs/2026-07-14-accumulation-score-design.md` 第 57-96 行）逐項核對，特別是封頂數字（40/30/20）跟 weakening 的兩個觸發條件
- [ ] NaN guard 邏輯正確（`pd.isna` 對 None 也會回 True，這裡刻意先判斷 `is None` 再判斷 `pd.isna` 是因為 `pd.isna(None)` 本身也是合法的，純粹是防禦性寫兩層判斷，確認沒有邏輯上的遺漏）
- [ ] 沒有影響其他既有的 `screener/patterns.py` 函式（`calc_composite_score`、`_calc_streak` 等），這次是純新增函式，不動既有程式碼
- [ ] 上面第 3 點記錄的 weakening 邊界案例（富鼎型：純大戶進貨、法人沒動）——這不是 bug，是刻意保留待回測的已知行為，麻煩 review 時不要當成問題回報，除非有新的資料/理由

### 特別注意
- 這次**沒有消費端整合**，`calc_accumulation_score()` 目前沒有任何呼叫端在用它——這是刻意的（spec 範圍如此），之後要接進畫面時（個股卡片 payload、籌碼進貨排行）需要另開 plan，不在本次範圍。
- 公式裡的封頂數字（8/6/7 分、40/30/20 封頂、0.5 閘門）都是 spec 標注的「草案切點」，之後要用 `screener/backtest.py`（另一個尚未開工的 `2026-07-14-backtest-framework` plan）對真實歷史資料驗證校準，不是最終定論。這也是上面第 3 點 weakening 邊界案例最終要一起驗證的地方。

---

## [2026-07-14] 🔀 Merge 說明：#7/#8/#9 兩邊各自獨立修過，衝突已收斂

master 分支跟 origin 各自獨立修了下面這兩則 #7/#8/#9（不同機器/session，換機沒同步到）。
Merge 時逐項比對兩邊差異後決定：**scrapers/shareholder.py 整體採用 origin 版本**（它的 #8
清洗步驟更徹底——`recompute_all_history()` 開頭直接 `UPDATE...SET NULL` 把 DB 裡的歷史離群值
永久洗掉，不只是計算時略過），**但把本地版本 `recompute_latest_streak()` 裡的 #9 缺週/離群值
防護移植回去**（origin 版本把這段連同對應測試一起刪掉了，只靠 `recompute_all_history()` 的
上游清洗防護，但 `recompute_latest_streak()` 也可能被單獨呼叫，需要獨立防護，defense in depth）。
main.py 採用 origin 版本（`plan_backfill_dates`/`get_existing_shareholder_dates`），本地版本
新增的 `_missing_shareholder_dates`（main.py 本地私有函式）功能重複，已移除，測試一併移除。

以下兩則是兩邊各自的原始記錄，保留供歷史對照：

---

## [2026-07-14] ✅ 籌碼分頁三指標定義修正 + 外資持股% 新資料源（spec: `docs/superpowers/specs/2026-07-14-chips-metric-definitions-design.md`）

Cody 看完新版「大戶籌碼」tab 覺得數字奇怪（許多股票 80-90%），調查後發現是排序 bug + 指標
定義跟 Cody 心中的標準定義有落差，一起修正。

### 1. 排序 bug：大戶連增/連減榜改比 |week_chg|
`_build_section8()` 原本 `(-streak, -lv12_15_pct)`——同樣連增/連減週數時比「持倉百分比絕對
值」，因為現況資料才剛修復兩週幾乎每檔 streak 都打平在 2，導致整個榜單被絕對百分比主宰，
外資保管銀行持股天生就高的股票（如台積電 87.77%）沖到榜首，即使當週實際變動只有 0.01-0.03%
這種無意義雜訊。改成 `(-streak, -abs(week_chg))`，同樣週數下優先顯示變動幅度最大的。

### 2. 大戶籌碼表兩層指標修正：400張以上（累計）+ 1000張以上（單獨）
調查中發現既有「400張大戶」欄位（Task 5/6 做的）是錯的——用 `lv12_shares`/`lv12_pct`，那其實
只是 TDCC level 12 單一級距（400,001~600,000股窄band），不是累計≥400張。真正「≥400張大戶」
累計是 `lv12_15_pct`（level 12-15 合計），也就是原本顯示成主指標「大戶持倉%」的那個欄位。
修法：拿掉錯誤的窄band欄位，主指標改名「400張以上大戶%」（資料不變，仍是 `lv12_15_pct`，
streak/週變化/連增週都維持這個基礎不動），保留「1000張大戶」不變（`lv15_pct`，這個原本就對）。

### 3. 新增外資籌碼%資料源（TWSE MI_QFIIS + TPEx tpex_3insti_qfii）
現有「外資籌碼」tab 原本只有三大法人「今日買賣超」（流量），沒有「外資總共持有多少%」
（存量）。已用真實請求驗證新資料源格式（TSMC 2330 在 TWSE 端測得 69.59%）：
- `scrapers/chips.py` 新增 `fetch_foreign_holding_twse()`/`fetch_foreign_holding_tpex()` +
  `_parse_pct()`（處理 TWSE 純數字字串跟 TPEx 帶 % 字串兩種格式）
- 新表 `foreign_holdings(stock_id, date, foreign_pct)`（`screener/database.py::init_db()`）
- `main.py::_update_chips_db()` 新增兩段抓取，套用既有 `_retry_fetch()`（#6 建的重試機制）
- `processors/performance.py::get_stock_chips_ranking()` 合併 `foreign_pct` 進
  `foreign_top_buy`/`foreign_top_sell` 每一列；**這張新表獨立包一層 try/except**——
  `foreign_holdings` 表可能還沒建立（例如尚未跑過任何一次 `_update_chips_db`），缺這張表
  不該讓整個籌碼排行連 institutional/margin 都一起壞掉，已補回歸測試驗證這個情境。
- `export/chips_generator.py::_stock_rank_table()` 新增「外資持股%」欄，缺值顯示「─」

### 已知限制（誠實揭露，spec 已記載）
「400張以上大戶%」「1000張以上大戶%」對外資持股極重的股票仍然會顯示偏高數字（TDCC 集保
分層資料源本身不分帳戶屬性，外資保管銀行的巨額集保帳戶本來就會落在這些高級距）——Cody 已
確認接受，不做「扣除外資」的近似計算（會引入日期對齊的複雜度跟精確度爭議）。外資籌碼%（新
資料源）跟三大法人買賣超是兩個獨立資料源/更新頻率，不互相校驗一致性，並排顯示。

### 測試
新增/調整測試涵蓋：大戶籌碼表兩層指標顯示、缺值處理、`_parse_pct` 格式解析、外資持股%欄位
顯示與缺值、`foreign_holdings` 表缺失時的降級（不連累其他既有資料）。全專案 **204 passed**。

未 push（等 Debugger ✅）。**這批需要 Cody 實際跑一次 `python main.py` 才會有 `foreign_holdings`
真實資料**（純程式碼修正不會生資料，`init_db()` 是 `CREATE TABLE IF NOT EXISTS`，正常跑一次
就會建表+開始累積資料）。

---

## [2026-07-14] ✅ #7/#8/#9 全部修好（根治方案，比照 Debugger 建議的選項 2）

### #7：`_backfill_shareholder` 改成只補 DB 實際缺的那幾週
`main.py::_backfill_shareholder()` 新增純函式 `_missing_shareholder_dates(available, existing, weeks)`：
先查 DB 現有日期集合，從 TDCC 最近 `weeks` 筆可查週別裡只挑 DB 沒有的那幾週抓（不是無腦
`available[:weeks]` 全部重抓）。同一個 weeks 視窗內的任何缺口（像 06-18）現在都會被抓到；
DB 已有的週不會被重複覆蓋，等於是「無害的冪等操作」——重跑同一個 `--backfill-shareholder N`
不會浪費 API 額度重抓已有資料。**視窗外的缺口仍然抓不到**（例如 06-18 若在 weeks=2 視窗外，
要調大 weeks 才會涵蓋），這是取捨不是 bug，跟 Debugger 建議的「根治方案」一致。

### #8：`recompute_all_history`/`recompute_latest_streak` 都加離群值 guard
新增共用常數 `_OUTLIER_PCT_THRESHOLD = 99`（原本 `_fetch_one_stock` 寫入端門檻是寫死的 99，
現在跟 `screener/database.py::get_shareholder_top()` 的 SQL 門檻共用同一個常數，不會之後
改一邊忘了改另一邊）。兩個 recompute 函式現在都把 `pct >= 99` 的歷史列視同 NaN 處理：
- `recompute_all_history`：該筆自己 `week_chg` 為 NULL，且不會被設成下一筆的 `prev_pct`
  繼續污染（真實案例：2380 2026-06-26=100.0 讓 07-03 算出假 `week_chg=-63.59`）。
- `recompute_latest_streak`：一致地把 `pct`/`prev_pct` 任一為離群值的情況視為無法計算，
  跳過（維持原狀），不寫入假值。

**⚠️ 這只是程式修好，真實 `data/screener.db` 裡 2380 那筆 07-03 的 `week_chg=-63.59` 假值
還沒被覆蓋**——麻煩 Cody 跑一次 `python -c "from scrapers.shareholder import recompute_all_history; recompute_all_history()"`
讓正式資料庫套用這次修復（不用手動改 `lv12_15_pct` 原始值，程式修好後重算就會自動排除
100.0 離群值，不需要 debug-tasks.md 原本提議的「資料面：手動改 NULL」那個選項）。

### #9：`recompute_latest_streak` 補齊缺週防護（原本不對稱的洞）
SQL 查詢加回 `prev.date`，跟 `recompute_all_history` 一樣判斷「次新一筆」跟「最新一筆」間隔
是否超過 `_MAX_WEEK_GAP_DAYS`，超過就跳過（不當基準硬算）。

### 測試
`tests/test_shareholder.py` 新增 4 個測試（缺週防護、離群值防護 in `recompute_latest_streak`；
離群值不污染下一週 in `recompute_all_history`）；`tests/test_main.py` 新增 4 個測試涵蓋
`_missing_shareholder_dates` 的邊界情況。原本 `test_recompute_latest_streak_fixes_week_frozen_before_backfill`
的 fixture 日期從隔 14 天改成隔 7 天（原本剛好會被新的 #9 缺週防護擋掉，不是這次要測的東西）。
全專案 **199 passed**。

未 push（等 Debugger ✅）。

---

## [2026-07-14] 📋 回家接續清單（籌碼面重構 / 回測）— Cody 回家照這個做

> 今天下班前的完整交接。回家：`git pull`（強制版：`git fetch && git reset --hard origin/master`），
> `data/` 拉不到（gitignored、在原本那台）。所有 spec/plan 都已 push、在 git 裡看得到。

### ✅ 今天已完成（都在 origin，可放心）
- **大戶持倉待修 #1–#8 全數完成**（缺週防護 / 離群值 / NaN guard / 缺週回補 / recompute 開頭清髒值），全專案 **195 passed**。
- **籌碼面重構 brainstorming → 產出設計文件**（見下）。

### 📄 新產出的 spec / plan（回家先 review）
1. `docs/superpowers/specs/2026-07-14-accumulation-score-design.md` — **進貨分**（含三族群實證校準 + 大盤 regime caveat）
2. `docs/superpowers/specs/2026-07-14-backtest-framework-design.md` — **回測地基**（含 regime 分段）
3. `docs/superpowers/plans/2026-07-14-backtest-framework.md` — **回測地基 plan（6 Task，待執行）**

### 🎯 回家開工順序（建議）
1. **review 上面 3 份文件**（有要改先改）。
2. **執行「回測地基」plan**（6 Task，`docs/superpowers/plans/2026-07-14-backtest-framework.md`）：
   Task1 一般化 scanner+D+1進場 → Task2 大盤等權指數+超額報酬 → Task3 漲停剔除 → Task4 扣成本 →
   Task5 regime 標記 → Task6 print_summary 升級。建議 **subagent 驅動**（每 Task 一個）。
   - 做完「實跑驗收」：拿真實 8 年 `data/screener.db` 跑巨量換手，看各 regime 有沒有 edge。
3. **拆「進貨分」plan**（accumulation-score spec 還沒拆 plan）→ 再實作。

### 🧠 今天釘死的關鍵洞見（實證，影響設計）
- **籌碼 = 配角（逆轟 50 分）**：三族群個案（功率/被動/載板）報酬龍頭（統懋+149/華容+81/百容+114）**法人籌碼幾乎全 0**；投信重壓的反而平庸；大戶補到部分法人漏的（富鼎）但抓不到最猛的。
- **→ 進貨分絕不單獨選股/亮燈**，價格/動能為主、籌碼加分確認；三來源都留；不倒扣連賣；多邊同買加權（待回測）。
- **⚠️ 但這是單一 regime**（5/26→7/14 全市場+0.8% 輪動市、無空頭樣本）→ 籌碼在空頭可能更值錢；回測要按 regime 分段。

### ❓ 待決定 / 未查
- `momentum-health-signal`（07-02 spec+plan）**到底做了沒**？那是筆記 B2「出場三原則」（CP 值最高的保命側），待查。
- 逆轟藍圖**個股層 B1–B5**（均線 5/10/60、出場、RS、連續漲停）整片還沒動。
- `open` 開盤價還被 import 丟掉（`screener/database.py:179` `NULL::DOUBLE AS open`）→ 回測 D+1 開盤進場暫用收盤退路；要真實開盤需 `CAST(open AS DOUBLE)` + reimport。

**✅ 上面「待決定」第一項已有答案（Debugger 同一天在另一個 worktree 做完，merge 進來了）**：
`momentum-health-signal`（07-02 spec+plan）+ 逆轟藍圖個股層 **B1–B5 今天已經全部做完**——
`screener/signals.py` 新增 `scan_momentum_health()`（B1 均線排列+B2 出場三原則+B4 相對強弱
含 rs_market_score+五級分類）、`scan_consecutive_limit_up()`（B5）、
`scan_bullish_alignment_new_high()`（B3）。整合進 `docs/superpowers/specs/
2026-07-14-momentum-strategy-page-design.md` 統整 spec（取代原本三份各自獨立的 design spec）。
19 個新測試全過，真實 DB smoke test 三支函式都正常運作。**還沒串頁面**（照 Cody 拍板順序，
等資料層全部驗證完才開「逆轟策略」頁面 brainstorming，跟這份清單提的「進貨分/回測」是平行的
兩條線，動工前建議先對一下兩邊會不會互相影響版面/資料流）。

---

## [2026-07-14] ✅ #7 缺週回補根治 + #8 清洗步驟寫進 code（Developer，收 Debugger 建議）

### #7：`--backfill-shareholder` 改成「只補視窗內缺的那幾週」
- 異動：`scrapers/shareholder.py`（新增 `get_existing_shareholder_dates()`、`plan_backfill_dates()`）、
  `main.py::_backfill_shareholder()`。
- 舊：`list(reversed(available[:weeks]))` 固定往回數 N 週、連 DB 已有的也重抓，中間缺的一週
  （06-18）不在最新 N 週內就漏。新：`plan_backfill_dates(available, existing, weeks)` 只回傳
  「視窗內 DB 還缺的那幾週」（由舊到新），06-18 只要落在視窗內就會被抓回、已有的不重抓。
- 收尾改用 `recompute_all_history()`（原本只 `recompute_latest_streak`）——因為填的是**中間缺口**，
  缺口後那週（06-26）要重新對到新補的 06-18，只重算最新週修不到它。
- 新增測試 `test_plan_backfill_dates_only_missing_weeks_in_window`、`test_get_existing_shareholder_dates`。

### 收 Debugger 建議（bug-reports.md）：清洗步驟寫進 code，不靠人工 SQL
- `recompute_all_history()` **開頭先就地清髒值**：`UPDATE shareholder SET lv12_15_pct=NULL WHERE
  lv12_15_pct >= _MAX_VALID_HOLDER_PCT`——不只計算時略過，**離群值本身也清成 NULL**。換機重跑
  recompute 就自動洗乾淨、不用記得人工下 SQL。#8 測試加驗「100.0 那筆的 lv12_15_pct 被清成 NULL」。
- 順帶移除迴圈裡多餘的 `>=99` guard（清洗後讀回是 NaN，既有 NaN guard 已涵蓋）。

### 驗證 / 全專案
- **全專案 195 passed**（+#7 兩個測試；#8 測試多一條清洗斷言）。純 code、機器無關。
- ⚠️ 真正把 production DB 的 06-18 補回、假訊號洗掉，仍需在**有真實 DB 的那台**跑
  `--backfill-shareholder 8`（現在會只補缺的、收尾自動全表重算＋清髒值）。

### 大戶持倉待修清單全數收斂
#1 缺週防護 ✅、#2/#4 NaN/離群值防護 ✅、#5 ✅、#6 ✅、Task5/6 ✅、**#7 ✅、#8 ✅（含清洗）**。
剩下純資料操作（在有 DB 的那台跑 backfill/recompute）不是 code 問題。

---

## [2026-07-14] ✅ #8 離群值 code 根治完成（Developer）

- 異動：`scrapers/shareholder.py` + `tests/test_shareholder.py`
- 做法：`recompute_all_history()` 迴圈加離群值 guard——`lv12_15_pct >= _MAX_VALID_HOLDER_PCT`(99)
  視為當週不可信、比照 NULL（本筆 week_chg=NULL、streak=0，也不當下一週比較基準）。抽共用常數
  `_MAX_VALID_HOLDER_PCT`，寫入端 `_fetch_one_stock`(#2) 與重算端(#8) 共用，避免兩個魔術數 99 漂移。
- 效果：**2380 06-26=100.0 這類歷史髒值不用人工追殺**——任何一台重跑 `recompute_all_history()`，
  它的 week_chg 自動變 NULL、07-03 那筆假 -63.59% 假訊號連帶消失。
- 新增測試 `test_recompute_all_history_outlier_pct_treated_as_null`（驗收：全表 `|week_chg|>20` = 0）。
  **全專案 193 passed**。
- ⚠️ 這是 **code 修復**，機器無關（單元測試驗）。真正把 production DB 的假訊號洗掉，仍需在**有真實
  DB 的那台**重跑一次 `recompute_all_history()`（本機沒跑法人/集保資料，不在這台跑）。

### 還開著：#7（06-18 缺週補抓）
`--backfill-shareholder N` 是往回數 N 週、不是補缺的那幾週，06-18 缺口未解。短期你在有 DB 的那台
跑 `--backfill-shareholder 8` 蓋過去；根治要改 `_backfill_shareholder` 成「比對缺哪幾週補哪幾週」。

---

## [2026-07-13] 🔧 Debugger → Developer：大戶持倉 backfill 後續 2 個問題（Cody 已跑完 `--backfill-shareholder`）

背景：Cody 得知 TDCC 已有 07-03/07-09 新資料、06-18 漏抓後，自行執行了
`python main.py --backfill-shareholder N`。Debugger 對正式 `data/screener.db` 做了跑前跑後檢查，
完整證據見 `bug-reports.md` 今天「Cody 跑完 `--backfill-shareholder` 後續檢查」那則。

✅ 07-03（1038 檔）、07-09（1037 檔）成功補進，`get_shareholder_top()` 排行榜資訊量恢復正常
（1040 檔裡 1038 檔有非 NULL `week_chg`）。以下兩項需要處理：

---

### 🔴 #7：`--backfill-shareholder N` 是「往回數 N 週」，不是「補缺的那幾週」，06-18 缺口仍未補
**位置**：`main.py::_backfill_shareholder()`
**問題**：這次跑完，06-18（TDCC 真實有這週資料，不是沒發布）依然沒進 DB，06-12→06-26 的
14 天缺口沒解決，06-26 那批 1037 檔的 `week_chg` 會持續被缺週防護標成 NULL（正確但資訊量損失）。
**修法**（擇一）：
1. 短期：這次先手動用更大週數（例如 `--backfill-shareholder 8`）蓋過 06-18 補一次即可，不用改 code。
2. 根治（可排後）：`_backfill_shareholder` 改成先讀 DB 既有日期序列、比對 TDCC `get_available_dates()`
   算出真正缺的那幾週去補，而非固定往回數 N 週——這樣以後任何一週漏抓都會被自動抓回來，不用每次
   人工判斷該填多少週數。
**驗收**：補完後 `SELECT date, COUNT(*) FROM shareholder GROUP BY date ORDER BY date` 應該看到
06-18 那筆，且 06-12→06-18→06-26 間隔都 ≤ 10 天。

### 🔴 #8：歷史離群值（2380 / 06-26 / `lv12_15_pct=100.0`）從未被追溯清除，這次污染了下一週
**位置**：資料本身（`shareholder` 表該筆列）+ `scrapers/shareholder.py::recompute_all_history()`（沒有
離群值 guard，只認 NULL/NaN，100.0 是合法浮點數不會被擋）
**問題**：#2 離群值防護（`_fetch_one_stock` 寫入端擋 `>=99`）**只防未來新抓的資料**，2380 這筆
100.0 髒值本來就已經在 DB 裡，從沒被追溯清掉。這次 backfill 補進 07-03 後，
`recompute_all_history()` 拿 07-03（36.4108）減 06-26（100.0）算出 **`week_chg=-63.5892`、
`streak=-1`**——跟一週前記錄過的同一種「假大戶減持」訊號一樣，只是這次污染的是歷史列
（07-03），不是當時的最新一筆。目前不影響現況排行（07-09 才是 2380 最新一筆，數值正常），但
任何查 2380 歷史趨勢的地方會看到這筆假的；全表目前只有這 1 筆離群值、造成 1 筆下游污染
（`ABS(week_chg) > 20` 全表僅此一筆命中，範圍很小）。
**修法**（擇一，Cody 尚未拍板，Debugger 已詢問是否要直接動手改資料）：
1. 資料面：把 2380 那筆 06-26 的 `lv12_15_pct` 手動改成 `NULL`，改完重跑一次
   `recompute_all_history()`，07-03 那筆假訊號會連帶消失。一次性操作，不用改 code。
2. 程式面（更根治，建議跟 #7 的根治方案一起排）：`recompute_all_history()` 的迴圈也比照 #2 加一個
   離群值 guard（`pct >= 99` 視為當週不可信，等同 NULL 處理，不要拿它當 `prev_pct`/`cur_pct`
   參與計算）——這樣以後任何歷史列出現類似髒值，不用等 Debugger 人工發現才追殺一筆。
**驗收**：修完後全表 `SELECT * FROM shareholder WHERE ABS(week_chg) > 20` 應該回空（或至少
2380 那筆消失）。

### 🟡 #9：`recompute_latest_streak()` 沒有跟 `recompute_all_history()` 一樣的缺週防護，是不對稱的洞
**位置**：`scrapers/shareholder.py::recompute_latest_streak()`（`--backfill-shareholder` 結尾會呼叫）
**問題**：這次 backfill 過程中實測到 2 檔（6236、8291）一度被它拿 14 天前的 06-12 當基準寫出
非 NULL `week_chg`——**這次剛好因為那 2 檔期間 `lv12_15_pct` 數值沒變，算出 `chg=0.0` 沒被看穿**，
但機制本身不設防，換一檔數值有變動的股票踩到同樣情境就會重演 06-26 那個「跨 14 天當單週」的舊 bug
（Debugger 事後重跑 `recompute_all_history()` 已覆蓋掉這 2 筆，現況是乾淨的，純粹記錄一個沒被
現有測試涵蓋的 code 邊界）。
**修法**：比照 `recompute_all_history()` 的 `_MAX_WEEK_GAP_DAYS` guard，抽成共用 helper 讓兩個函式
一起用，避免以後改一邊忘了改另一邊（這正是這次踩到的成因）。
**優先度**：低於 #7/#8，這次沒有造成實際錯誤資料，但建議跟 #7/#8 一起做（同一批程式碼、同樣的
「缺週/離群值」防護主題）。

---

## [2026-07-13] ✅ #6 修好——TWSE/TPEx 籌碼抓取單邊失敗加重試

**現行犯抓到**：實作前先查了現況，`data/screener.db` 今天（07-13）`institutional`/`margin`
兩張表都是**只有 TWSE、TPEx 完全沒資料**；當場直接打 TPEx 三大法人 API 驗證，**當下完全
正常**（200、922 檔、日期就是今天）——證實今天稍早 `main.py` 跑的時候是暫時性失敗，因為
沒有重試機制，失敗一次就整批漏了，且 TPEx 這兩支端點沒有歷史回補路徑，永久補不回來。

**位置**：`main.py`，新增 `_retry_fetch(fn, *args, retries=3, backoff=(1.0,3.0), retry_on, **kwargs)`
（接在 `_prev_trading_day` 之後），比照 `scrapers/shareholder.py` 既有的 TDCC 抓取重試模式
（3 次、1-3 秒隨機退避，已驗證穩定）。

**套用方式**（`_update_chips_db()` 4 個抓取呼叫）：
- **TWSE**（`fetch_institutional`/`fetch_margin_all_twse`）：只對 `TWSEBlockedError` 跟
  `requests.exceptions.RequestException`（涵蓋逾時/連線錯誤/HTTPError）重試，**刻意不重試
  `ValueError`**——那是 TWSE「今日尚未發布」的既有信號，main.py 靠它觸發日期回退到前一
  交易日，這個邏輯完全沒動，重試機制不會延誤或吃掉它。
- **TPEx**（`fetch_institutional_tpex`/`fetch_margin_all_tpex`）：對任何例外都重試——TPEx
  沒有「尚未發布」這種需要保護的合法信號，每次失敗不是暫時性問題就是真的還沒更新，重試
  成本低（最多 3 次、退避 1-3 秒）。

**測試**：新增 `tests/test_main.py`（首次為 `main.py` 建測試檔），5 個測試涵蓋
`_retry_fetch`：成功不重試、失敗幾次後成功、重試耗盡後拋出最後一次例外、**排除在
`retry_on` 外的例外型別不重試**（保護 TWSE 的 ValueError 回退邏輯）、args/kwargs 正確傳遞。
全專案 **190 passed**（原 185 + 5）。

**未涵蓋**：這次沒有改 `scrapers/chips.py` 本身，重試邏輯只包在 `main.py` 呼叫端外層——
維持 fetch 函式單一職責（抓取+解析），重試是編排層的關心事。也沒有處理「TPEx 真的整天
都沒更新」的情境（3 次快速重試無法解決，需要的話要另外設計排程重跑，這次範圍不含）。

未 push（等 Debugger ✅）。

---

## [2026-07-13] ✅ #5 修好——section 標題標自己的資料日期（整批一致落後不再無跡可尋）

**位置**：`export/chips_generator.py`，新增 `_section_date_suffix(rows)`，接在既有
`_latest_data_date()` 之後。

**修法**：不論區塊內是否混用交易日，section/半版標題旁一律附加該區塊自己最新一筆的
資料日期（例如「融資擴張警示（增幅 > 5%）· 資料日 07/08」）。跟既有逐列徽章
`_data_date_badge()` 是兩個獨立機制：
- 逐列徽章：區塊內**混用**不同交易日時，標出落後那幾列的實際日期（既有行為不變）。
- 新的標題標籤：不論混不混用，都標出這個區塊**整體**最新到哪天——這樣「整批一致
  落後 headline 一天」時（區塊內同日、逐列徽章全部不標）也有跡可尋，不會被誤讀成
  跟 headline 同一天。

**套用範圍**：`_build_section2`（外資大買/大賣，兩個半版**各自獨立**算自己的資料日期，
不共用同一個基準）、`_build_section4`（融資擴張警示）。沒動 headline 語意、沒動個股
徽章邏輯，跟 debug-tasks.md 原本記載的建議修法一致。

**測試**：新增 3 個測試（`_build_section4` 整批落後時標題有日期、個股徽章不標；
`_build_section4` 無資料時不標日期；`_build_section2` 兩個半版各自獨立標日期）。
全專案 **185 passed**（原 182 + 3）。

**#6**（TWSE/TPEx 單邊失敗）還沒動——那個要改抓取層的重試/補抓邏輯，範圍較大，先留著。

未 push（等 Debugger ✅）。

---

## [2026-07-13] ✅ 大戶持倉分層 Task 5/6 完成（400張/1000張大戶欄位上畫面）

`docs/superpowers/plans/2026-07-10-shareholder-tier-breakdown.md` 最後兩個 Task，照已核准的
plan 逐步做完：

### Task 5：`main.py` sh_rows 組裝加 6 個新 key
`lv12_shares`/`lv12_pct`/`lv12_chg`/`lv15_shares`/`lv15_pct`/`lv15_chg`，餵給
`generate_chips_html`。純資料組裝，跟 plan 內容一致，無偏離。

### Task 6：`export/chips_generator.py::_shareholder_table()` 顯示新欄位
- 表格新增「400張大戶」「1000張大戶」兩欄，重用 `_insider_cell()` render 格式。
- `_insider_cell()` 第三參數改名 `pledge_pct`→`pct`，加 `pct_label: str = "質押"`（預設值
  維持既有「公司派/大股東」兩欄行為不變），大戶分層兩欄呼叫時傳 `pct_label="持股"`
  （避免「持股占比」被誤標成「質押」字樣）。
- TDD：先在 `tests/test_chips_generator.py` 補 `_SAMPLE_SH_ROW` 的 lv12/lv15 欄位 + 2 個新測試，
  確認紅了才動 production code。

### 驗證
全專案 `pytest`：**182 passed**（原 180 + Task 6 新增 2 個測試）。
`test_shareholder_table_row_td_count_matches_header`（既有防雙重 `<td>` 回歸測試）維持通過，
新增的 2 個 `<th>` 跟每列 2 個 `_insider_cell()` 回傳的 `<td>` 數對得上。

### 資料來源相關
不涉及資料源，純顯示層——組裝/渲染 Task 1-4 已經寫入 DB 的 `lv12_shares`/`lv12_pct`/
`lv15_shares`/`lv15_pct` 欄位。

### 特別注意（debug-tasks.md 之前記載的已知限制，還沒解）
- **`lv12_chg`/`lv15_chg` 目前多數股票仍是 NULL**：這兩欄要跟「前一週」比較才有值，
  Task 1/2 是這次 session 才開始把 `lv12_shares`/`lv15_shares` 寫進 DB，歷史週沒有這兩欄資料。
  Cody 剛跑完 `python main.py --backfill-shareholder 2`（補 07-03、07-09 兩週），跑完後
  07-09 這週應該就有值可比（07-03 這批本身就已經寫入 lv12/lv15，兩週都有資料）；再更早的
  歷史週仍會是 NULL，要等之後每週例行更新累積。畫面上顯示「─」是預期行為，不是 bug。
- 未 push（等 Debugger ✅，照專案規則）。

---

## [2026-07-13] ✅ 大戶持倉待修清單 #1/#2/#4 全部完成（Developer，桌電接手 WIP 收尾）

對應下面那份 Debugger 待修清單，目前進度：

### ✅ #2/#4 收尾（接續筆電 WIP，2 測試轉綠，全專案 180 passed）
- **真正根因**：`recompute_all_history()` 的迴圈只判斷 `prev_pct is None`，但 SQL NULL
  經 DuckDB→pandas 讀回是 `NaN`（不是 `None`），這個判斷從沒抓到過。且原本沒檢查**當週自己**
  的 `lv12_15_pct` 是否為 NULL/NaN（例：2380 被 #2 改寫成 NULL 那週）。結果 `nan - prev`／
  `prev - nan` 算出 Python `nan`（不是 `None`）寫回 DB，`nan != SQL NULL`，下游
  `WHERE week_chg IS NULL` 抓不到——這才是 2 個測試紅的真正原因，不是 WIP 筆記猜測的
  `executemany` 型別轉換問題（有另外寫小腳本重現排除這個猜測）。
  修法：兩個條件都改用 `pd.isna()`，並新增當週 `cur_pct` 的 isna 檢查。
- **test_add_week_change_streak_handles_null_prev 紅的真正原因是測試 fixture 過期**：
  `_make_table()`（`tests/test_shareholder.py`）還是舊的 8 欄 schema，沒跟上
  `2052451`（`lv12_15 分層`）新增的 `lv12_shares/lv12_pct/lv15_shares/lv15_pct` 4 欄，
  導致 `save_to_db()` 明列這些欄位的 INSERT 直接 `BinderException`，根本沒跑到 NaN 判斷那段。
  修法：`_make_table` 補齊 12 欄對齊 `screener/database.py` 正式 schema；連帶把該檔案裡
  所有位置式 `INSERT INTO shareholder VALUES (...)`（8 個值）改成明列欄位名，避免欄位數對不上。
- 全專案測試：**180 passed**（原本 176 + 新增的缺週/NaN guard 測試）。

### 請 Cody 執行 #3（重算正式 DB，我不自己跑資料）
`#1/#2/#4` code 都綠燈了，輪到 `#3`：對 `data/screener.db` 跑一次
`recompute_all_history()` 修全表 66% 損毀的 `week_chg`（缺週防護 #1 已在裡面，會一併生效）。
建議在 Python shell 或臨時腳本跑：
```python
from scrapers.shareholder import recompute_all_history
recompute_all_history()
```
跑完麻煩簡單抽查一下 `week_chg` 用 `LAG(lv12_15_pct)` 對拍應該零不一致（debug-tasks.md #3 驗收標準），我這邊沒有正式 DB 不能替你跑。

### 請 Debugger 驗證
- [ ] `recompute_all_history()` 的 `pd.isna` 修法邏輯正確（W1 無前值/W2 自身 NULL/W3 前筆 NULL 三種情況都應該是真 NULL）
- [ ] `tests/test_shareholder.py::_make_table` schema 補齊後，其他既有測試沒有因為欄位變多而被影響（已跑全專案 180 passed，但麻煩交叉確認）
- [ ] 上市/上櫃資料來源沒有涉及（這次改動只在集保 shareholder 表的衍生欄位計算，不碰 TWSE/TPEx 資料源）

---

### ✅ #1 缺週防護（已 commit `408cc0d`、已 push、全綠）
- `scrapers/shareholder.py::recompute_all_history()`：迴圈追蹤 `prev_date`，間隔 >
  `_MAX_WEEK_GAP_DAYS`(10) 天視為缺週 → 該筆 `week_chg=NULL`、`streak=0`，prev 照常前進
  （缺口後相鄰週恢復正常，不傳染）。
- 新增缺週測試；更新既有 `test_recompute_all_history_fixes_corrupted`（05-22→06-26 隔 35 天，
  現為 NULL，順帶讓 2380 的 100.0 離群值不再算 week_chg）。全專案 **176 passed**。

### 🚧 #2 離群值防護 + #4 NaN guard（**WIP、已 push 供桌電接手**、有 2 測試紅）
> ⚠️ **這是未完成的 WIP commit**（回家換機交接用）。2 個測試還是紅的，**resume 點見下方「下一步」**。
> 接手前先 `pytest tests/test_shareholder.py tests/test_database.py` 確認紅在哪，修綠再往下。
- **#2 已寫**：寫入端 `_fetch_one_stock` 把 `lv12_15_pct >= 99` 視為異常寫 None；讀取端
  `get_shareholder_top()` 加 `WHERE latest.lv12_15_pct < 99`（排除離群值/NULL）。
- **#4 寫了但踩到真 bug**：`recompute_all_history` / `_add_week_change_streak` 加了
  `pd.isna` guard，但實測發現 **`con.executemany(UPDATE...)` 會把 Python `None` 寫成 NaN
  而不是真 NULL**（除第一列外）——這**正是 #4 要修的症狀本身**（`WHERE week_chg IS NULL`
  抓不到）。所以 #4 的核心不只是 guard，還要**改寫入方式讓 None 真的落成 SQL NULL**。
- 目前紅的 2 測試：`test_recompute_all_history_null_pct_gives_null_not_nan`（IS NULL 只數到 1
  應為 3）、`test_add_week_change_streak_handles_null_prev`。
- **下一步（resume 點）**：兩條寫入路徑都要讓 `None`→真 SQL NULL：
  1. `recompute_all_history`：`con.executemany("UPDATE...")` 對 DOUBLE 欄會把 None 寫成 NaN
     （除第一列）→ 改逐列 `con.execute`，或先把 updates 建成 nullable/object dtype 的 df 再
     `UPDATE ... FROM df`。
  2. `_add_week_change_streak` → `save_to_db` 的 `INSERT ... SELECT FROM df`：df 的 `week_chg`
     是 float64、None 變 NaN → 同樣要讓它落成 NULL（確認 DuckDB 對 df NaN 的處理，必要時用
     object dtype）。
  綠了（`test_recompute_all_history_null_pct_gives_null_not_nan` 用 `IS NULL` 數到 3、
  `test_add_week_change_streak_handles_null_prev` 的 `a[0] is None`）再結案。
- ⚠️ 桌電接手後，在 #2/#4 修綠之前**別把它當完成品**——它是 WIP。

---

## [2026-07-13] 🔧 Debugger → Developer：待修清單（Cody 拍板繼續改，依序做）

Debugger 今天在真實資料上驗出來的，完整證據在 `bug-reports.md` 今天那三則。
**優先序照下面排**——#1~#3 是「畫面現在就在顯示錯的數字」，#5 只是未來風險。

---

### 🔴 #1（先做，卡住其他人）：`recompute_all_history()` 加缺週防護
**位置**：`scrapers/shareholder.py::recompute_all_history()`（第 329-343 行的迴圈）
**問題**：TDCC 週別序列缺了 **6/12、6/19 兩週**（6/05 直接跳到 6/26，隔 21 天），而該函式
只按「日期排序後跟前一筆比」，**不檢查間隔** → 現在跑下去會把「跨三週的累積變化」寫成 6/26 的
`week_chg`，把問題從「部分損毀」固化成「全表都有值、但語意錯」，比現況更難察覺。
**⚠️ 所以在這項修好之前，`recompute_all_history()` 不能對真實 `data/screener.db` 跑。**
**修法**：算 `chg` 前先判斷 `date - prev_date`，超過一週（建議 > 10 天）就寫 `NULL`、
`streak` 歸 0，不要硬算成「本週變化」。
**驗收**：造一個缺週的 fixture（W1, W2, 缺 W3, W4）→ W4 的 `week_chg` 應為 `NULL` 而非 W4−W2。

### 🔴 #2：離群值防護（2380 髒值現在是「大戶減持」榜首）
**位置**：`scrapers/shareholder.py`（寫入端）＋ `screener/database.py::get_shareholder_top()`（讀取端）
**問題**：2380（虹光）2026-06-26 的 `lv12_15_pct = 100.0`（大戶持股 100%，不可能，TDCC 該週
解析異常）。它現在讓 2380 以 **`week_chg = -63.59%` 排在大戶減持第 1 名**，而第 2 名只有 -5.52%
——差一個量級的假訊號，直接汙染排行榜。全表 `pct >= 99 或 <= 0` 的離群值就這 1 筆。
`get_shareholder_top()` **完全沒有離群值過濾**。
**修法**：寫入端把 `lv12_15_pct >= 99`（或其他合理上限）視為解析異常 → 寫 `NULL` 而非硬存；
讀取端排行也濾掉。⚠️ 若改成寫 `NULL`，就會真的觸發下面 #4 的 NaN guard，**#4 要一起做**。
**驗收**：修完 2380 不再出現在減持榜首；榜首應是 8112（-5.52%）那個量級。

### 🔴 #3：跑 recompute 修 `week_chg` 全表損毀（#1、#2 做完才跑）
**問題**：全表約 **66%（4707 / 7128 列）** 的 `week_chg` 是錯的——3724 列基準不是真正的前一週，
另外 5/08 是**第一週、根本沒有前一週可比，卻有 983 列有非 NULL 的值**（憑空的數字）。
逐週損毀率 5/15~6/05 都在 92% 左右，只有最新的 7/03 那批是乾淨的。
（更正舊記載：「自己的 pct − 100.0」只有 4 筆、全是 2380，解釋不了那 3724 筆。真正的兇手不在
現行程式碼裡，`_add_week_change_streak` 的邏輯本身是對的 → 不用考古，重算即可。）
**驗收**：重算後用 `LAG(lv12_15_pct)` 對拍，不一致列數應為 0；缺週那幾筆應為 `NULL`（見 #1）。

### 🟡 #4：NaN guard（跟 #2 綁在一起做）
**位置**：`scrapers/shareholder.py::recompute_all_history()`；同一個洞也在
`_add_week_change_streak()` 第 251-252 行（**寫入路徑，每次 `--update-shareholder` 都會跑**）
**現況**：真實 DB 的 `lv12_15_pct` NULL 數 = **0**（`_fetch_one_stock` 在 `total_shares == 0`
時整筆跳過），所以這個 guard **目前不會觸發、是純 defensive** → 優先度低於上面三個。
**但 #2 一旦把髒值改寫成 NULL，它就會立刻觸發，所以必須跟 #2 一起做。**
**實測更正**（原 review 說「一路往後傳染、後續所有週永遠算不出來」是高估）：中段 NULL 實際只
汙染 **2 筆**（NULL 那筆＋下一筆），第 3 筆起自動恢復——因為 `_streak_step(NaN, ...)` 兩個比較
都是 False、回 0，不會傳出怪值。**但核心危害成立**：寫進 DB 的是 **NaN 而不是 NULL**，
下游 `WHERE week_chg IS NULL` 抓不到。
順帶：`_add_week_change_streak` 第 252 行 `int(prev.get("streak", 0))`——`prev` 是 pandas Series，
key 存在時 default 不生效，若 `streak` 是 NULL 會變成 `int(NaN)` → `ValueError` crash
（目前 DB 沒有 NULL streak，不觸發，但要修 NaN 就一起修）。

### 🟡 #5：section 標題帶自己的資料日期（`data_date` 修復的殘留洞）
**位置**：`export/chips_generator.py`（`bd11c2b` 新增的 `_data_date_badge` 附近）
**問題**：徽章基準是 section-relative，所以「整個 margin 區塊**一致地**落後 headline 一天」時，
區塊內同日 → **一個徽章都不標**，但 headline `chips_date` 仍標較新的那天 → 原本那個
🔴（前一天的數字被謊報成同一天）以「整批版」原封不動留著，且更難察覺。
實測（把 49 檔 `data_date` 全設成 07-08）：徽章 **0** 個、headline 仍是 `2026-07-09`。
**不是假想**：今天 `margin` 表 7/09 已經只剩 TPEx（TWSE 整批抓取失敗），只要哪天 TPEx 也沒
發布，兩所一起停在 7/08 就觸發。
**建議修法**：每個 section 標題旁標該區塊自己的資料日期（例如「融資擴張警示 · 資料日 07/08」），
個股徽章維持現狀處理區塊內混日。兩種情況都涵蓋，不用動 headline 語意，也沒有你擔心的誤判。

### 🟡 #6（背景，非阻塞）：TWSE/TPEx 籌碼抓取經常單邊失敗
`institutional` 7/07、7/08 **TPEx 整批缺**；`margin` 7/09 **TWSE 整批缺**（其餘日子兩邊各 ~500）。
這是 #5 和「跨日混用」的根因。建議單邊失敗時能重試/補抓，否則 per-stock 取最新會持續產生跨日混排。

### 補充：`share_chg` / `lv12_chg` / `lv15_chg` 目前 1040 檔全 NULL（畫面整欄空白）
`lv12_15_shares` 只有 7/03 那批（1038 列）有值、其餘 6090 列 NULL（Task 1/2 之前沒寫入這欄）
→ 相減時 prev 是 NULL。**純改程式修不好**，要等下一批 TDCC 資料進來、或 backfill 補寫 shares 欄。
Task 5/6 把這幾欄搬上畫面前要先確認這件事，否則畫面會是空的。

---

## [2026-07-13] 修 🔴 - 融資/外資榜跨交易日混用，每列補真實資料日期 data_date（修你端到端驗證新發現的 🔴）

### 改了什麼
- 異動檔案：`processors/performance.py`、`export/chips_generator.py` + 對應測試
- 邏輯說明：你 07-13 端到端驗證發現「融資警示混用兩交易日、畫面卻只標一個日期」（32 檔上市用
  7/08、17 檔上櫃用 7/09，但 chips_date 統一標 7/09）。根因是 `get_stock_chips_ranking` 的
  per-stock `QUALIFY ROW_NUMBER()=1` 各取自己最新一筆時，兩所進度不同會靜默混用不同交易日、
  且 SQL 沒帶回 date，資訊被丟掉。
- 修法（誠實標示，不是硬統一成一天）：
  1. **後端**：inst/margin 兩個 query 都 `SELECT ... , date`，`foreign_top_buy/sell` 與
     `margin_alerts` 每一列新增 `data_date`（該檔那筆的真實日期，YYYY-MM-DD）。
  2. **前端**：新增共用 `_data_date_badge(data_date, latest)` + `_latest_data_date(rows)`，
     `_stock_rank_table`（外資大買/大賣）與 `_margin_alert_table`（融資警示）對**落後該表最新日**
     的個股，在股名後標一個橘色「📅07/08」徽章（同日/缺值不標，保持乾淨）。

### 資料來源相關
- 純顯示/資料溯源修復，沒動抓取口徑。上市走 TWSE、上櫃走 TPEx 不變；問題正是兩所「發布進度
  不同步」時 per-stock 取最新造成的跨日混排，現在每列誠實帶自己的日期。

### 設計取捨（請你 review 時特別看這點）
- 徽章比較基準是**「該表自己最新的一天」**（section-relative），不是 headline `chips_date`。
  理由：margin 的資料日期跟 institutional 各自獨立，若拿 institutional 的 chips_date 當基準，
  會誤判「比 headline 新的 margin 列」為落後。section-relative 自成一致、不耦合。
- **已知未涵蓋**：若整個 margin 區塊「一致地」比 headline 舊一天（全 7/08、header 7/09），
  section 內同日 → 不標徽章。這是刻意取捨（避免上面那個誤判）。若你覺得這情境也要示警，
  再討論要不要把 headline 也跟著誠實化。

### 請 Debugger 驗證
- [ ] 融資警示/外資榜：真實跨日情境下，落後那一天的個股有標「📅MM/DD」、同日的乾淨無徽章
- [ ] `data_date` 是純日期字串（不是 Timestamp 帶 00:00:00）
- [ ] 沒影響其他表（Section 6 inst_strong 走不同函式、不在本次範圍）

### 特別注意
- 全專案 `pytest`：**175 passed**（原 171 + 本次 4 個新測試：後端 per-row date、前端落後標示/
  同日不標/缺 data_date 不報錯）。
- 未 push（等你 ✅）。同一批要驗的還有下面那筆死碼清理（你已回報 ✅、可 push）。

---

## [2026-07-13] 清理 - 刪除 chips.py FinMind 版融資死碼（Cody 拍板刪除）

### 改了什麼
- 異動檔案：`scrapers/chips.py`（−59 行）、`HANDOFF.md`（doc 一行）
- 邏輯說明：刪掉 `fetch_margin()` / `fetch_margin_all_today()` 兩個 FinMind 版融資融券死函式
  （全專案零呼叫，早已被官方 API 版 `fetch_margin_all_twse` / `fetch_margin_all_tpex` 取代，
  2026-07-10 就標記過死碼、這次 Cody 確認可刪）。順手刪掉只剩死函式在用的孤兒常數 `FINMIND_URL`。
- **保留**：`FINMIND_TOKEN`（`main.py:210/320` 回補流程仍 import 使用）、`requests`/`os` import
  （官方 API 函式仍在用）。
- HANDOFF.md 檔案結構那行過時的 `fetch_margin_all_today()` 改成實際在用的官方函式名。

### 資料來源相關
- 不涉及抓取口徑變動——刪的是「改用官方 API 之前」的舊 FinMind 實作，每日流程/回補都沒在走它。
  每日融資融券仍是上市 TWSE 官方 API、上櫃 TPEx 官方 API，不變。

### 請 Debugger 驗證
- [ ] 全專案 `pytest` 通過（確認刪除沒打到任何隱藏引用）
- [ ] `import scrapers.chips` 不報錯（`FINMIND_URL` 已無任何 import 端）
- [ ] `main.py` 的 `from scrapers.chips import FINMIND_TOKEN`（210/320）仍正常

### 特別注意
- 已本機 `py_compile scrapers/chips.py` 通過、grep 確認 tests/main.py/backfill.py 無引用死函式。
- 未 push（等 Debugger ✅）。⚠️ 若 Cody 這期間跑 `python main.py`，其自動 push 會把此 commit 一起
  推到 origin——理想上先讓 Debugger 跑一次 pytest 再跑 main.py。

---

## [2026-07-13] 進行中 - 大戶持倉 400張/1000張分層追蹤 + 修正歷史 week_chg 損毀（換平台交接）

### 背景
Cody 回報「大戶持倉」畫面數字看起來不對（截圖貼出的資料），調查後發現：
1. `lv12_15_shares`（大戶實際張數）全表 NULL——schema 有加欄位但從沒被真的寫入過資料
2. 歷史 `week_chg` 損毀：`2380`（虹光）好幾筆歷史週變化都是「自己的 pct − 100.0」而非跟真正前一週比較，`100.0` 疑似 TDCC 該週解析錯誤的離群值
3. 順帶討論後決定新增 400張(level 12)/1000張(level 15) 分層追蹤，不只看合計

已走完 brainstorming → spec（`docs/superpowers/specs/2026-07-10-shareholder-tier-breakdown-design.md`）→ plan（`docs/superpowers/plans/2026-07-10-shareholder-tier-breakdown.md`，共 6 個 Task）→ subagent-driven 實作，全程 Cody 已授權在 master 上直接做。

### 已完成（Task 1-3，各自都過 spec review + code quality review，皆 Ready to merge）
- **Task 1**（commit `c2975f5`）：`scrapers/shareholder.py::_fetch_one_stock()` 多留 level 12/15 個別股數與占比
- **Task 2**（commit `3be0ee9`）：`shareholder` 表新增 `lv12_shares`/`lv12_pct`/`lv15_shares`/`lv15_pct` 4 欄，`save_to_db()` 寫入
- **Task 3**（commit `2052451`）：`get_shareholder_top()` 回傳這 4 欄現況 + 查詢時現算的 `lv12_chg`/`lv15_chg`（張數週變化，比照既有 `share_chg` 模式不落地存表）

### 進行中，有 1 個待修（Task 4）
- **Task 4**（實作在 commit `0682d92`，跟 Cody 另一個並發的 TAIEX_HEAVYWEIGHTS 修復意外綁在同一個 commit——內容沒問題，純粹是 commit 訊息不乾淨，已跟 Cody 說明過）：新增 `recompute_all_history()` 一次性修復整表歷史 `week_chg`/`streak` 損毀。
  - 已過 spec compliance review（✅ 完全符合）
  - Code quality review 發現 1 個 **Important** 問題還沒修：`lv12_15_pct` 若在某支股票歷史中段出現 NULL（schema 允許），目前只防第一筆、沒防中段——會讓 `chg` 變成 `NaN`（不是正確的 `NULL`）並一路往後傳染，讓該股後續所有週的 `week_chg` 永遠算不出來、且寫進 DB 的是 `NaN` 不是 `NULL`（下游 `WHERE week_chg IS NULL` 抓不到）。修法：比照第一筆的 `prev_pct is None` guard，中段也要判斷 `pd.isna(row["lv12_15_pct"])`，該筆跳過/清空、且不要把 NaN 往後傳給 `prev_pct`。
  - **⚠️ 這個函式目前還不能拿去對 `data/screener.db` 真的跑**，要先補上面這個 guard。
  - 位置：`scrapers/shareholder.py`，`recompute_all_history()` 函式（`recompute_latest_streak()` 之後）

### 尚未開始
- **Task 5**：`main.py` 組 `sh_rows` 迴圈加入 6 個新欄位（`lv12_shares`/`lv12_pct`/`lv12_chg`/`lv15_shares`/`lv15_pct`/`lv15_chg`）
- **Task 6**：`export/chips_generator.py::_shareholder_table()` 顯示「400張大戶」「1000張大戶」兩欄，`_insider_cell()` 加 `pct_label` 參數

### 換平台後接續方式
1. 讀 `docs/superpowers/plans/2026-07-10-shareholder-tier-breakdown.md`，Task 4 先補 NaN guard + 一個新測試（NULL 出現在歷史中段），過 review 後再繼續 Task 5、6
2. 全部做完後：Cody 需要實際跑一次 `--update-shareholder`/`--backfill-shareholder` 讓 `lv12_shares`/`lv15_shares`/`lv12_15_shares` 真的有非 NULL 資料（這幾個函式本身不會自動跑，純程式碼修正不會生資料）
3. `2380`（虹光）2026-06-26 那筆 `lv12_15_pct=100.0` 本身是否為真實資料異常，建議人工核對 TDCC 原始回應，不在這次範圍內

### 其他發現、待 Cody 決定
- `scrapers/chips.py::fetch_margin`/`fetch_margin_all_today`（FinMind 版融資融券）已標記為死碼（全專案零呼叫，已被 `fetch_margin_all_twse`/`fetch_margin_all_tpex` 官方 API 版本取代），待確認後可整段刪除

---

## [2026-07-12] 修 🔴 - `TAIEX_HEAVYWEIGHTS` 移除中信金（2891），daily_prices 從未有它的資料

### 改了什麼
- 異動檔案：`config.py`

### 為什麼
驗證 `docs/superpowers/specs/2026-07-09-momentum-notes-scan-mapping.md` 附錄裡對大盤分級
儀表板的兩個 🔴 pre-review 風險點（Debugger 稍早在該文件裡寫下、尚未驗證的）：
1. 資金集中度的「非權值股」母體要排除權值股本身，否則落差會被稀釋算錯
2. `change_pct` 的 NULL/NaN 污染

**驗證結果：這兩點在 `processors/performance.py::calc_capital_concentration()`/
`calc_market_breadth()` 都已經正確處理**（`~is_hw` 排除邏輯實測 `overlap check=False`；
`pd.to_numeric(errors="coerce")` + `dropna` 有濾掉 NaN）——原本以為的兩個高風險點，程式碼
其實都寫對了。

驗證過程中用真實 DB 交叉比對 `TAIEX_HEAVYWEIGHTS` 清單跟實際抓到的資料，**額外發現一個真
問題**：`2891`（中信金）在 `daily_prices` 表裡**從未有任何一筆資料**（`COUNT(*)=0`，不是
單日缺漏）。追出根因：`stock_universe.csv`（這個 app 的族群追蹤名單）從一開始就沒收錄金融
股，`main.py` 每日抓價流程的股票清單來源就是這份 CSV，`2891` 不在清單裡、永遠不會被抓到。
`TAIEX_HEAVYWEIGHTS` 清單「看起來 10 檔、實際只有 9 檔生效」，這比少一檔更危險——不誠實。

### 邏輯說明
直接移除 `2891`，不替換成別支股票。理由：換股票需要重新判斷「哪支才是正確替代」，會再度
踩進 2026-07-09 debug-tasks.md 已經記錄過、還沒定案的「金融股邏輯跟成長權值相反、要不要納
入」的哲學問題——但這次發現的其實不是哲學問題，是**技術上從未被追蹤、不可能有資料**，跟
「要不要」無關，移除是唯一正確答案。原本那則「🟡 待討論」的備註也一併改寫，說明這不用再糾
結了。

### 資料來源相關
- 不適用——純設定檔常數修正，不影響任何抓取邏輯

### 請 Debugger 驗證
- [ ] 全專案測試都過（無新增測試——`main.py`/`config.py` 都沒有硬編碼假設清單一定是 10 檔，
  改動本身不需要新測試，`grep` 過 `tests/`、`main.py` 確認沒有依賴清單長度的隱性假設）
- [ ] 用真實 DB 確認：`config.TAIEX_HEAVYWEIGHTS` 現在 9 檔，全部都在 `daily_prices` 抓得到
  （不會再有「清單有但資料沒有」的落差）
- [ ] 確認 `calc_capital_concentration()` 用新清單算出來的 `heavyweight_avg_pct` 前後數字
  差異合理（少了中信金一檔，權值股籃平均可能會有小幅變動，屬預期）

### 特別注意 🚩
- 這是 Debugger 角色本 session 依 Cody 指示驗證 `momentum-notes-scan-mapping.md` 附錄裡的
  pre-review 風險點時，過程中額外發現、Cody 當場授權直接修的
- 如果之後真的要把金融股（含中信金）納入分析，需要先把它加進 `stock_universe.csv` 的抓取
  範圍，是獨立的範圍擴充決策，不是這裡改個 `stock_id` 就能解決；`config.py` 的註解已經寫清楚

---

## [2026-07-09] 改進 - 外資/投信連買榜改用 Composite Score（連買天數+漲幅 percentile rank 加總）

### 改了什麼
- 異動檔案：`export/chips_generator.py`
- 新增測試：`tests/test_chips_generator.py`（3 個）

### 背景
接續同日稍早的「外資連買榜改用漲幅排序」修復。Cody 追問：如果外資連買到 10 天，會不會
還是排在上面？查了真實資料發現不一定——純用漲幅排序（前一版做法）會讓「連買很久但漲幅
普通」的股票被擠出 Top 15（實測案例：6834 連買 8 天但漲幅只有 9.22%，排到第 17 名，完全
不會顯示在畫面上）。查了量化多因子排名的文獻（CANSLIM 的機構認同+價格確認雙重驗證、
factor investing 的 composite score / index-of-indices 方法論），跟 Cody 討論後採用
Composite Score：連買天數、股價累積漲幅各自轉成百分位排名（percentile rank，0~1），加總
當綜合分數排序。

### 邏輯說明
- 新增 `_percentile_ranks(values)`：回傳每個值在清單中的百分位排名，同值取平均名次，
  只有 1 個值時給 1.0（避免除以 0）
- 新增 `_composite_sort(candidates, streak_key)`：連買天數（`foreign_streak`/`trust_streak`）
  跟 `price_cum_pct` 各自算百分位排名相加，依總分排序。外資榜、投信榜都改用這個共用函式
  （原本各自 `sorted(key=lambda x: -price_cum_pct)`）
- 篩選條件（`foreign_streak>=3`／`trust_streak>=5` 且 `price_cum_pct>=5%`）沒有變，只有
  「篩選之後怎麼排序」改變

### 資料來源相關（如有異動）
- 不適用——純排序方法調整，沒有新增資料源

### 請 Debugger 驗證
- [ ] 全專案測試都過（新增 3 個：`_percentile_ranks` 同值/單值邊界、`_composite_sort`
  驗證「兩因子都強」穩居第一、「兩因子都弱」敬陪末座，且不等同純漲幅或純天數排序、
  空清單不報錯）
- [ ] 用真實 DB 驗證：之前被純漲幅排序擠出 Top15 的長連買股票（例如連買 8 天但漲幅個位數
  的），現在應該有機會進入 Top15；同時漲幅暴衝的股票（百容）也不該被擠掉
- [ ] 確認 Composite Score 沒有把篩選門檻本身弄壞（`price_cum_pct>=5%` 這個 AND 條件還是
  在排序之前先過濾，不是排序邏輯的一部分）

### 特別注意 🚩
- Percentile rank 是相對排名（0~1，最大值→1），**不是**原始數值的正規化——好處是不同量綱
  的因子（連買天數是整數幾天、漲幅是浮點百分比）可以直接相加比較，不用煩惱單位換算；
  壞處是候選股票數少時容易同分（例如只有 3-4 檔候選時，percentile rank 的可能值有限，
  容易撞出並列名次），這是這個方法論本身的已知限制，不是實作 bug
- 這次的研究/決策過程：先用 WebSearch 查了量化多因子排名文獻（CANSLIM、factor investing
  的 composite score vs index-of-indices 做法），跟 Cody 討論兩個方向的取捨後才動手，
  不是憑感覺選的排序公式

---

## [2026-07-09] 修 🔴 - index.html 只 render 21/41 個族群卡片，21 個族群完全點不進去

### 改了什麼
- 異動檔案：`export/html_generator.py`
- 新增測試：`tests/test_html_generator.py`（1 個回歸測試）

### 為什麼（Cody 實跑回報）
從 `chips.html` 點「▲ 外資連買族群」「▼ 外資連賣族群」裡的族群連結，畫面直接跳回空白
`index.html`，什麼反應都沒有。

**查證過程**：一開始懷疑是 XSS 跳脫（`_esc()`）造成 `data-meta-name` 屬性值跟連結解碼後的
名稱不一致，實測用 headless Chrome（`chromium.exe --headless --dump-dom`）驗證 `AI伺服器`
這類無特殊字元的族群連結完全正常，排除跳脫比對問題。改用 chips.html 裡一個真實連結
（`機器人/自動化`，含 `/` 字元）實測，headless Chrome 顯示對應卡片**完全不存在於 DOM**。
比對 `docs/index.html` 全部 `data-meta-name` 屬性，只有 **21 個**（`stock_universe.csv`
實際有 **41 個** meta_sector）。

**根因**：`export/html_generator.py::generate()` 的 `meta_perf` 分支只
`render meta_sorted[:10]`（今日漲幅前10名）+ `reversed(meta_sorted)[:10]`（跌幅前10名，
即後10名），中間表現平平、非當日極端漲跌的 **21 個族群完全沒有 `.mc-card`/`.mc-panel`**，
`data-meta-name` 屬性根本不存在於 DOM。任何指向這些族群的連結（`chips.html` 的外資
連買/連賣族群、頁面內建搜尋框）打開 `openMetaByName()` 都會 `querySelector` 找不到、
直接 `return`，畫面完全無反應——不是連結壞掉，是卡片從頭到尾沒被產生過。

這是舊版（前端 React 重構被 revert 回這支 legacy generator 之後）沿用的 Top10/Bottom10
限制，之前的 React 重構 spec 裡其實已經明確判斷過這個設計是問題（`2026-07-02-
index-frontend-redesign-design.md`：「原本首頁最上方有獨立的 Top10 區塊，內容跟主列表前段
重複...拿掉這個獨立區塊，排行榜清單本身＋排序方向切換就取代了它的功能」），只是 revert 回
legacy generator 後這個舊限制又跟著回來，沒有人注意到「拿掉 Top10 限制」這個決定也該一併
帶回 legacy 版本。

### 邏輯說明
`top_source`/`bot_source`（各自 `[:10]`）+ 兩組獨立 render 迴圈，改成單一 `meta_sorted`
（全部 41 個，不 slice）+ 單一 render 迴圈，卡片 `id` 統一用 `t{i}` 前綴（原本 top 用
`t{i}`、bottom 用 `b{i}`，現在只有一組列表不需要再分兩種前綴）。標籤從「▲ 漲幅 Top 10」
+「▼ 跌幅 Top 10」兩個區塊合併成「族群排行（漲幅由高到低）」一個區塊——全部族群已經照
漲跌幅排序，最上面自然是今日漲幅最大、最下面自然是跌幅最大，不需要再切成兩個獨立區塊。

### 資料來源相關（如有異動）
- 不適用——純呈現層 bug 修復，`calc_universe_performance()` 本來就正確算出全部 41 個
  META groups（log 可查證），問題是渲染層漏 render，不是資料計算錯誤

### 請 Debugger 驗證
- [ ] 全專案測試都過（新增 1 個：25 個族群〔刻意 > 10+10〕情境下驗證全部都有卡片）
- [ ] 用真實 DB 驗證：`docs/index.html` 應該有 41 個（不是 21 個）`data-meta-name`
- [ ] 用 headless Chrome 或手動瀏覽器測試：從 `chips.html` 點幾個非當日極端漲跌的族群
  連結（例如中段表現的族群），確認能正確跳轉並展開對應卡片，不再是空白畫面
- [ ] 確認 `.dn-label` CSS 已經跟著刪掉（`up-label` 還在用、`dn-label` 因為 bottom10 區塊
  移除已經是死 CSS，順手一起清了，Debugger 可以順便確認沒有其他地方引用到 `dn-label`）

### 特別注意 🚩
- 這是 Debugger 角色本 session 在 Cody 明確要求下切換 Developer 身分直接查出並修復的——
  過程中用了 headless Chrome 實際載入頁面驗證（不是只看程式碼推測），排除了一開始懷疑的
  XSS 跳脫比對問題後才找到真正根因（Top10/Bottom10 截斷），避免誤修錯地方
- 如果之後又想把「Top10/Bottom10 快速瀏覽」這個功能加回來，可以做成**額外**的摘要區塊
  （不是取代全族群列表），兩者不衝突，但這次沒有做，純粹修復「族群點不進去」這個回歸

---

## [2026-07-09] 功能 - 「外資連買」榜改用股價累積漲幅排序/篩選（Cody 實跑發現百容漏掉）

### 改了什麼
- 異動檔案：`screener/institutional.py`、`export/chips_generator.py`
- 新增測試：`tests/test_institutional.py`（3 個）、`tests/test_chips_generator.py`（2 個）

### 為什麼（Cody 實跑回報）
百容（2483）10 日內大漲、外資連買 3 天，但 `docs/chips.html`「外資連買」榜完全沒看到它。
查證：`scan_institutional()` 有正確算出 `foreign_streak=3`，但榜單只顯示前 15 名、排序依據是
**累積買超股數（絕對值）**——符合條件的股票共 222 檔，百容排第 37 名，被小型股天生的低股數
擠出榜外（第 1 名累積 2.1 億股，百容只有 23 萬股，差 900 多倍）。這是排序方法論的系統性缺陷，
不是抓取/掃描漏掉。

Cody 提議：搭配股價連續漲勢一起篩選，呼應 `notes/動能派學習筆記.md`「股價先說話」的核心邏輯——
外資買超如果沒有推動股價，可能只是被動式資金流入（ETF 調倉之類），訊號意義不大；外資買超
+ 股價確實走強，才是真正有效的訊號，這樣篩出來的名單也會自然把小型股的顯著訊號撈出來。

### 邏輯說明
- `screener/institutional.py`：新增 `_calc_cum_pct()`（複利計算累積漲幅，不是連續上漲天數——
  百容案例是「兩週漲快一倍但中間有拉回」，用嚴格連漲天數會漏掉）。`scan_institutional()` 新增
  `price_window`（預設 10 個交易日）、`min_price_cum_pct` 參數與 `price_cum_pct` 回傳欄位、
  排序選項。
- `export/chips_generator.py`：「外資連買」榜（Section 6b）改成 `foreign_streak>=3 且
  price_cum_pct>=5%`，排序依據從 `cum_foreign`（絕對股數）改成 `price_cum_pct`（漲幅）。
  `_inst_streak_table()` 新增「10日漲幅」欄位顯示（正紅負綠，缺行情顯示「─」）。投信榜
  （Section 6b 右側）這次沒動，維持原本排序，因為問題是 Cody 針對外資連買提出的，投信要不要
  比照辦理留給 Cody 決定。

### 資料來源相關（如有異動）
- 不適用——這次是既有 `daily_prices`/`institutional` 資料的呈現/排序邏輯調整，沒有新增資料源，
  TWSE/TPEx/FinMind 規則沒有變動

### 請 Debugger 驗證
- [ ] 全專案測試都過（新增 5 個：`_calc_cum_pct` 複利計算、price_cum_pct 反映真實區間、
  min_price_cum_pct 濾掉外資買超但股價沒動的雜訊、`_inst_streak_table` 新欄位渲染、
  雙重 `<td>` 回歸檢查）
- [ ] 用真實 DB 驗證：百容（2483）現在應該出現在「外資連買」榜前段（我實測是第 4 名，
  price_cum_pct=57.39%），而不是被擠到 37 名之後
- [ ] 確認 `min_price_cum_pct=5` 這個門檻合不合理——這是隨手訂的草案數字，沒有回測過，
  如果榜單看起來太空或太滿，可能要調整

### 特別注意 🚩
- **投信榜沒有比照修改**：只改了外資連買榜，投信持續買進榜（Section 6b 右側）還是用原本
  `trust_net`（今日金額）排序，沒有套用股價累積漲幅篩選。如果 Cody 也想要投信榜比照辦理，
  需要另外討論（用法邏輯應該一樣，但 Cody 這次只針對外資連買提出）
- `price_window=10`、`min_price_cum_pct=5%` 都是這次順手訂的草案數字，跟大盤分級儀表板那次
  一樣沒有回測，Debugger／Cody 實際看過榜單效果後可能需要調整
- 這是 Debugger 角色（本 session）在 Cody 明確要求下切換 Developer 身分直接動手做的，過程
  完整走過 brainstorming（先跟 Cody 確認方向：cumulative 漲幅 vs 連續上漲天數、要不要濾掉
  股價沒反應的雜訊）才動手，不是跳過討論直接寫 code

---

## [2026-07-09] ⏳ 待桌電端到端驗證 - 籌碼面 5 個 🔴 修復（真實資料）

Debugger 已修好籌碼面 review 的 5 個 🔴（commit 已進 master，見 bug-reports.md 同日「修復」那則），
**邏輯層已驗**（155/156 pytest + 7 個回歸測試 + 行為實測），但**真實 production 數字的端到端驗證
Debugger 這台做不了**——debug 機的 `data/screener.db` 只有單日資料，重現不了「歷史累積漏股」
「跨表/交易所日期不同步」這些情境。

**需要在桌電（有完整多日/多交易所 data/screener.db）做一次**：
- `python main.py`（或 `--realtime`），開 `docs/chips.html` + 看 log
- 逐項對照：
  1. **#1 漏股**：法人篩選/Section 6 的檔數，是否比修復前多（尤其高號 TPEx 4xxx-8xxx 股有回來）。
     修復前隨歷史累積會漸進漏掉高號股，修復後應完整。
  2. **#3/#5 跨表 skew**：找一天 margin 比 institutional 晚一天（或 TWSE/TPEx 不同步）的情境，
     確認「融資擴張警示」「族群 margin 數字」沒有整批消失/歸零。
  3. **#4 NaN close**：若當天有停牌/全額交割股（close 為 NULL），確認 chips.html 正常產出、
     沒有因 int(nan) crash 停更。
  4. **#2 假融資訊號**：留意 log 有無「融資大減」異常大的離群值（修復後餘額解析失敗會跳列，
     不再用 0 相減造假；正常情況看不出差異，但若曾出現過離群值應消失）。
- 數字明顯不對或有 crash → 回報，Debugger 再查。

（這是資料重現的物理限制，不是漏驗；邏輯層已由回歸測試涵蓋。）

---

## [2026-07-09] 功能 - batch 股價改用 realtime 同源（與 --realtime 一致，杜絕看到昨日數據）

### 改了什麼
- 異動檔案：`main.py`（`run()` 的 batch `else` 分支股價抓取）、新增 spec
  `docs/superpowers/specs/2026-07-09-batch-realtime-price-source.md`
- 邏輯：batch（`python main.py`）股價改為 **realtime 同源（`fetch_realtime_prices`）為主、
  官方 `fetch_prices_for_stocks` 為退路**（realtime 回空/失敗才退，涵蓋盤前/假日）。

### 為什麼（Cody 一整天實跑的痛點）
- 官方 TPEx endpoint 盤後有定案延遲 → 太早跑抓到昨日殘留值（其陽 3564 顯示昨日 +10%
  漲停、實際今天 −3.57%）；盤中跑 batch 又會被「市場尚未更新」防呆切回昨天。
- realtime（mis.twse.com.tw）盤後回收盤集合競價價（實測 17:55 仍撈得到、time=13:30、
  其陽正確 54.1），無定案延遲。改用它 → 股價/族群與 --realtime 一致、永不看到昨天。

### 資料來源相關（重點）
- **只改股價**。籌碼（法人/融資/TAIEX）**完全沒動**，仍走官方（`_update_chips_db` 無條件
  執行，realtime 與 batch 都會抓、來源相同 → 兩指令籌碼一致，但受官方盤後發布時間限制）。
- realtime 來源本來就沒有籌碼資料，籌碼不可能改成 realtime，此為資料源本質。

### 請 Debugger 驗證
- [ ] batch 主走 realtime：mock `fetch_realtime_prices` 回正常 df → 用它、不呼叫官方
- [ ] realtime 回空/丟例外 → 退回 `fetch_prices_for_stocks`（官方）
- [ ] 完整性保險絲仍有效：realtime df 缺 2330 → 中止（跟前一則保險絲互動）
- [ ] 全專案 pytest 沒被弄壞

### 特別注意 🚩
- 這讓 `python main.py` 與 `--realtime` 幾乎等價（差別只剩 batch 多保險絲+防呆）。
- daily_prices 歷史檔：盤中跑會寫即時價（與現行 --realtime 相同行為，非新風險），盤後那次
  跑覆蓋成收盤價，近5/7/10/14日/回測以盤後為準。

---

## [2026-07-09] 修 🔴 - batch 完整性保險絲 + 搜尋點選個股連不到 modal + HTML no-cache

### 改了什麼（3 個獨立小修，都是 Cody 實跑遇到的問題）
1. **batch 完整性保險絲**（`main.py`，commit 59baf3b）
   - 根因：一次盤後跑 TWSE 連線 timeout，只抓到 TPEx 518 支（所有上市股缺失），
     舊流程照樣**覆蓋完整檔案 + 寫 DuckDB + push GitHub Pages** → 族群個股大量消失、
     巨量換手掃不出、線上壞版。
   - 修法：batch 模式寫入前檢查探測股 2330（最大權值股必在）在不在結果，不在即
     `return` 中止，保留既有完整資料。realtime 走即時來源、不套用。
2. **搜尋點選個股連不到個股資訊**（`export/html_generator.py`，commit 6a07285）
   - 根因：個股呈現早改成 `.st-row` 表格列，但 `selectSearchStock` 還找舊的 `.stock-card`
     → querySelector 回 null → 點搜尋結果無反應。改成相容兩者、找到即 openStockModal。
   - 加迴歸測試 `test_search_select_stock_selector_matches_st_row`。
3. **HTML no-cache meta**（index/chips/patterns 三個 generator，commit 96a17f0）
   - 大檔被瀏覽器啟發式快取，普通 F5 看到舊資料、要 Ctrl+F5。三頁 head 加
     Cache-Control/Pragma/Expires no-cache。

### 資料來源相關（重要，Cody 這輪踩到的坑）
- **TPEx `tpex_mainboard_quotes` 有盤後定案延遲**：盤後太早跑（如 15:33），TPEx 這個
  endpoint 還沒把今日收盤定案，會回**前一交易日的殘留價量**（其陽 3564 一度顯示昨天的
  漲停 +10%，實際今天是跌的）。傍晚（~17:00 後）定案。**這不是 bug、非停牌**——是資料源
  時間差。我一度誤診成「停牌」寫了偵測碼，查 TPEx openapi 真實值後**已回退**（沒進 commit）。
- realtime（mis.twse.com.tw）是獨立來源、不受 TPEx 定案延遲影響，所以 Cody 觀察到
  「realtime OK、batch 舊」完全合理。

### 請 Debugger 驗證
- [ ] 保險絲：mock「prices_df 缺 2330」→ `run()` 中止、不寫檔不 push；有 2330 → 正常跑
- [ ] 搜尋 modal：`test_search_select_stock_selector_matches_st_row` 過；產出 HTML 的
      selectSearchStock 用 `.st-row` selector 且呼叫 openStockModal
- [ ] no-cache：三頁 head 都有 3 個 no-cache meta
- [ ] 全專案 pytest 沒被弄壞

### 特別注意 🚩
- **保險絲的 2330 探測**跟既有「市場尚未更新」防呆是**兩個不同檢查**（那個是價格=昨天才切日期；
  這個是 2330 根本不在就中止）。兩者可共存，確認沒打架。
- TPEx 定案延遲的根本解（TPEx 定案偵測，比照 2330 探測做一個 TPEx 探測股）**還沒做**——
  要在「TPEx 未定案的時間窗」才重現得了，留待之後（Cody 已知）。

---

## [2026-07-09] 新功能 - 大盤分級儀表板 Phase 1（依桌電 spec/plan 實作，TDD）

### 改了什麼
- 異動檔案：
  - 新增 `scrapers/taiex.py`（+ `tests/test_taiex.py`）
  - `config.py`：新增 `TAIEX_HEAVYWEIGHTS`（權值股清單常數）
  - `processors/performance.py`：新增 `calc_market_breadth` / `calc_capital_concentration` /
    `classify_market_regime`（+ `tests/test_processors.py` 追加測試）
  - `export/html_generator.py`：新增 `_market_regime_section()` + `generate()` 多一個
    `market_regime` 參數，區塊插在族群排行之上（+ `tests/test_html_generator.py` 追加測試）
  - `main.py`：`run()` 串接 `fetch_taiex_index` + 三個計算函式，組 `market_regime` 傳給 `generate_html`
- 邏輯說明：兩條獨立軸線——(1) 五級大盤方向（TAIEX 漲跌 + 個股廣度綜合判斷，門檻見設計文件
  §軸線一）(2) 資金集中度（權值股 vs 非權值股平均漲跌落差 ≥ 2pt 標記集中）。每一級對應逆轟筆記
  操作提示（hard-code 在 `_REGIME_TIERS`，因為來源 `notes/` 是 gitignored、不會發布到產出頁那台）。
- 設計/計畫依據：`docs/superpowers/specs|plans/2026-07-09-market-regime-dashboard*`

### 資料來源相關
- TAIEX 指數：**TWSE 官方 FMTQIK**（`www.twse.com.tw/rwd/zh/afterTrading/FMTQIK`，2026-07 實測格式）。
  發行量加權股價指數=收盤、漲跌點數=change、change_pct 用 prev_close=close-change 反推。
  民國日期 `115/07/01` → +1911 轉西元。封鎖偵測沿用 `scrapers/chips.py::TWSEBlockedError`
  （content-type 非 json / stat!=OK / 缺欄位一律當擋頁）。fetch 取「<= trade_date 的最新一筆」，
  當天未發布自動退前一交易日。
- 廣度/集中度：對**個股** `prices_df.change_pct` 算（不是族群平均），batch 與 realtime 兩條路的
  prices_df 都有 change_pct 欄，確認過。

### 請 Debugger 驗證（我只寫測試沒跑，全部 pytest 交給你）
- [ ] `tests/test_taiex.py`：FMTQIK 解析（close/change/change_pct/民國日期）、擋頁→TWSEBlockedError、
      fetch 日期挑選 + fallback、缺欄位當擋頁
- [ ] `tests/test_processors.py` 新增：廣度 ratio/邊界、集中度兩方向+缺邊回 None、五級邊界值、
      「小漲區間但廣度<50%→持平」、集中度方向判斷
- [ ] `tests/test_html_generator.py` 新增：區塊渲染 tier/集中度/提示、五級各自提示、缺邊隱藏集中度、
      `market_regime=None`→回空字串（整頁不 crash）
- [ ] 全專案 pytest 沒有被我這次改動弄壞（generate() 新參數 default None，既有 caller 不受影響）
- [ ] 上市/上櫃資料來源沒有混用（這功能只讀 TAIEX 大盤指數 + prices_df，不碰個股上市櫃來源）

### 特別注意 🚩
- **權值股清單**：`config.TAIEX_HEAVYWEIGHTS` = 0050 真實前 10（2026-07 對 0050 持股頁實測），
  Cody 拍板不手動補額外金融股（避免等權平均下金融佔比超過真實指數權重）。中信金保留（真的是市值前10）。
  🟡 待討論：金融股本質是「風險資金逃難處」、跟成長權值邏輯相反，是否移出中信金/另做逃難所訊號，
  之後再定，本版先照 0050 前 10。門檻數字（五級切點、集中度 2pt）也都是**草案、未回測**。
  Task 6 建議桌電跑真實 `main.py` 開 index.html 對一下當天新聞的大盤漲跌是否合理，明顯不對就回頭校門檻。
- **realtime 語意提醒**（非 bug）：`--realtime` 盤中跑時，廣度來自即時股價、但 TAIEX 走 FMTQIK
  只有盤後收盤 → 盤中會退到昨天的指數 change，與今天即時廣度不同步。每日 batch 流程（盤後）
  兩者一致、無此問題。要不要為 realtime 另接盤中即時指數，留給 Cody 決定（Phase 1 不做）。
- Phase 2（個股五級強弱分類，筆記§三十）不在本次範圍。

---

## [2026-07-08] ⏳ 待桌電目視 - Section 6 兩所同時顯示（scan_institutional 修復的真實頁面驗證）

Debugger 已用合成 temp DB 驗過 `scan_institutional` anchor 邏輯（同步/差一天/陳舊/單天退化全對，
121 passed，見 bug-reports.md 對應那則）。但**「兩所發布日不同步時 Section 6 同時有 TWSE+TPEx
股」的真實頁面渲染，Debugger 這台重現不了**——debug 機的 `data/screener.db` 只有 07-01 單日，
沒有 07-07/07-08 那種分裂日期的資料（data/ 是 gitignored、不同步）。

**需要在桌電（有真實多日資料）做一次目視確認**：
- `python main.py`
- 開 `docs/chips.html` → Section 6（法人持續買進個股）
- 確認清單**同時有 TWSE 股和 TPEx 股**（對照修復前 Developer 報的「917 全 TPEx、TWSE 0 檔」→
  修復後 TWSE 應回來，他報 509 檔）
- 看到兩所股票都在 = 修復在真實頁面生效，這項就能正式收掉。

（這是資料重現的物理限制，不是漏驗；邏輯層已由合成測試涵蓋。）

---

## [2026-07-08] 修 🔴 - scan_institutional 在 TWSE/TPEx 發布日不同步時漏掉整個交易所

### 改了什麼
- 異動檔案：`screener/institutional.py`（`scan_institutional`）、新增 `tests/test_institutional.py`

**Cody 實跑 log 發現**：`法人篩選 2026-07-08：917 檔`（07-06 那次是 2274）。實測 917 檔
**全是 TPEx、0 檔 TWSE**。

**根因**：今天 TPEx 三大法人比 TWSE 早發布 → institutional 表分裂日期（TWSE 停 07-07、
TPEx 停 07-08）。`scan_institutional` 原本用整表 `MAX(date)=07-08` 當單一錨點
（`target`），逐股要求 `grp["date"] == target`；TWSE 股最新只到 07-07 → `today_rows.empty`
→ 全被 `continue` 跳掉。**這是 get_chips_today 那個 bug 的反向版**（那次 TPEx 落後、
這次 TPEx 領先），scan_institutional 沒跟著改成 per-stock。
- 影響：`docs/chips.html` Section 6（法人持續買進個股）在「兩交易所發布日不同步」的日子
  會靜默只顯示其中一個交易所的股票。平常兩邊同一天就不會觸發。

**修法**：
- 新增 `anchor_dates = 表裡最近兩個交易日`；逐股取自己最新一筆（`grp.iloc[-1]`），
  最新日落在 anchor_dates 內才算「今日」。→ TWSE 退 07-07、TPEx 用 07-08，各取各的、
  兩邊都不漏；又因為限定「最近兩個交易日」，停牌/下市（最新資料好幾天前）的股票不會被
  陳舊資料拉進來。
- `window` 從 `grp[grp["date"]<=target]` 改成 `grp.tail(lookback)`（到該股自己最新日為止）。
- 輸出 `"date"` 從單一 `trade_date` 改成每股自己的 `stock_date`。

**驗證**：
- TDD 新增 `tests/test_institutional.py` 2 測試（不同步時兩所都入選、陳舊股被排除），
  修復前第一個紅、修復後綠。全專案 121 passed。
- 真實 DB `scan_institutional('2026-07-08')`：**917（全 TPEx）→ 2246 檔，TWSE 0→509**。

### 資料來源相關
- 不適用抓取——讀取/篩選層對「TWSE/TPEx 發布日不同步」的 per-stock fallback，跟
  get_chips_today 同一類修法、同一個慣例。

### 請 Debugger 驗證
- [ ] 全專案 121 passed（原 119 + 新 2）
- [ ] anchor_dates 用「最近兩個交易日」的邊界：兩所同一天發布時行為不變（都入選）；
  差一天時兩邊都入選；差超過兩個交易日的陳舊股被排除
- [ ] Section 6 實際渲染：找一天兩所發布不同步（或用今天 07-08 的 DB）跑 main.py，
  確認 chips.html Section 6 同時有 TWSE + TPEx 股，不再只剩一個交易所

### 特別注意
- 這是 institutional 版的 per-stock fallback。**margin 的 get_chips_today 已在稍早修過**
  （commit 9d82a3a），兩者現在對「交易所發布日不同步」的處理一致了。
- `scan_institutional` 的行情（close/change_pct）仍用 trade_date→latest_inst_date 的
  daily_prices fallback，沒改（daily_prices 兩所都是當天就有，不受此問題影響）。

---

## [2026-07-08] ⚠️ 給 Developer：把 debug 統一進 master（一個 fast-forward 就好）

Cody 決定「所有東西統一到 master」，不要 remote debug 分支（Debugger 已把誤推的
`origin/debug` 刪掉，以後不會再有）。Debugger 已在 debug 分支把 master 最新（含你剛做的
`290df9e` #3 調查）merge 進來，**debug 現在是 master 的完整超集**（`git rev-list --count
debug..master` = 0），全專案 119 passed。

Debugger 在 debug worktree 沒辦法 checkout master（被你的 worktree 佔用），也不該在你 session
活著時同時動 master（會撞 index）。所以最後這步請你在 **master worktree（tw-sector-tracker 資料夾）**
執行：

```bash
git merge debug          # debug 是超集 → 乾淨 fast-forward，把 Debugger 29 個 commit 帶進 master
git push origin master   # 更新 origin，GitHub Pages 重新部署
```

**合進來的內容**（都在 bug-reports.md 有對應驗證紀錄）：
- 大戶張數化+內部人持股 Task 1-5 驗證、insider MOPS 封鎖偵測
- chips.html Section 8 近5/7/10/14 日累積漲跌幅
- **共用函式 `screener/database.py::get_rolling_returns()`**（收盤價比值法）
- index 族群個股表也改用同一函式（近5/7/10/14，取代舊複利 `_weekly_pct`）→ 兩頁一致
- get_chips_today per-stock fallback 的 Debugger 驗證紀錄

### ⚠️ 合之前/之後注意兩點（Debugger review 時標的 🟡）
1. **`html_generator.py` 這批動到你要 redesign 的檔**：index 族群個股表的「數值呈現」已改成
   近5/7/10/14（Cody 指定「數值先在筆電改、UI 版面回家弄」）。你 redesign 版面時是在這個基礎上改，
   不是空白重來。`_stock_table` / `_meta_stock_cards` 現在各 11 欄。
2. **`_weekly_pct()` 合進 master 後變成死碼**：debug 這邊已無 caller，你 master 端原本的 2 個 caller
   （338/520 行）也被這批新版取代。**合完就可以安全刪 `_weekly_pct`**（現在刪之前會 crash，合完才行）。

### 資料傳遞小改動（redesign 時可留意）
- `get_rolling_returns` 的結果經 `generate()` 塞進 module 級 `_ROLLING_RETURNS`，供 `_stock_table` /
  `_meta_stock_cards` 直接讀（避免穿 8 層渲染呼叫鏈的參數）。是刻意的取捨，redesign 若重整這條鏈
  可改回正規傳參。

---

## [2026-07-08] 調查結論 - TPEx 融資 07-07 缺席：官方發布延遲，抓取端無 bug（不用再追）

### 調查方式
- 讀 `main.py:125-145`（TPEx 融資寫入）+ `scrapers/chips.py::fetch_margin_all_tpex()`；
  對照 Cody 07-08 實跑的 log

### 結論：抓取端沒有可修的 bug，是 TPEx 官方資料源的發布延遲
- `fetch_margin_all_tpex()` 用 TPEx OpenAPI `tpex_mainboard_margin_balance`，docstring 明載
  **「只回傳當天，無法查歷史日期」**——它只給 TPEx 官方當下發布的最新一天，沒有日期參數。
- Cody 07-08 的 log 實證：`TPEx 融資融券目前是 2026-07-03（跟 TWSE 端不同天，可能尚未更新）`
  → 抓取當下 TPEx 最新只發到 07-03，程式**誠實寫進 07-03**（不是 crash、不是寫錯日期）。
  TWSE 融資盤後當天就發、TPEx 融資明顯更慢，這是兩個來源的天性差異。
- 為什麼「不能靠 retry 讓它當天就有」：資料還沒被 TPEx 發布，重試也生不出來；API 也不收
  指定日期。唯一補歷史 TPEx 融資的路是別的來源（FinMind），那屬 `--backfill` 範疇、
  不是每日流程該做的。

### 正解 = 顯示層 fallback（已於上兩則 commit 完成）
- `get_chips_today` 的 per-stock fallback（commit 9d82a3a）讓 TPEx 個股退到自己最新一筆
  （07-06/07-03），族群頁不再「─」。這就是面對「外部源延遲」的正確處理，抓取端不需改動。

### 請 Debugger
- [ ] 認同此結論即可，**不需要再追 TPEx 融資抓取端**（除非哪天發現 TPEx OpenAPI 其實有
  歷史日期參數、或 log 出現真正的抓取例外而非「尚未更新」提示）。

---

## [2026-07-08] 修(續) - get_chips_today 改 per-stock fallback：修好 TPEx 個股融資仍「─」

### 改了什麼
- 異動檔案：`screener/database.py`（`get_chips_today`）、`tests/test_database.py`（+1 測試）

**背景**：上一則的 fallback（整張表取單一 `MAX(date)`）**只修了一半**。實測發現 TPEx 個股的
**融資**仍全是「─」（501 支全 0）：
- margin 的整表最新日 = 07-07，但**07-07 那天 margin 只有 TWSE、沒有 TPEx**（TPEx 融資最新在 07-06）。
- 用整表單一最新日，就會漏掉「最新日剛好缺席的那個交易所」的個股。

**修法**：改成 **per-stock fallback**——`WHERE date <= ? QUALIFY ROW_NUMBER() OVER
(PARTITION BY stock_id ORDER BY date DESC)=1`，institutional / margin **各自、逐股**取自己
<= today 的最新一筆。TWSE 股退到 07-07、TPEx 股退到 07-06，各拿各的。

**驗證**：
- 新增測試 `test_get_chips_today_per_stock_fallback_not_table_wide`（兩支股票 margin 停不同天，
  整表 MAX 會漏一支、per-stock 不漏）。全專案 115 passed。
- 真實 DB `get_chips_today('2026-07-08')`：TPEx 個股融資 **0 → 489 支有值**；外資覆蓋也更完整
  （TWSE 515、TPEx 516）。

### 請 Debugger 驗證
- [ ] 全專案 115 passed（原 112 + get_chips_today fallback 系列共 3 個新測試）
- [ ] per-stock fallback：TWSE/TPEx 個股各退到自己最新一筆、不會因整表最新日缺某所而漏
- [ ] 邊界：某股完全無 institutional 或無 margin → 該側 NULL、FULL OUTER JOIN 仍回另一側

### 特別注意
- 這是 fallback 顯示層的完整修復。**根本的「TPEx 融資 07-07 為何沒抓到」仍是獨立的抓取問題**
  （TPEx 融資融券發布較慢/偶爾失敗，見下方調查）——顯示層現在會優雅退到最近一筆，但若要
  「當天就有 TPEx 融資」還是得從抓取端解決（retry / 確認 TPEx OpenAPI 發布時間）。

---

## [2026-07-08] 修 - 族群頁外資/投信/融資顯示「─」：get_chips_today 加 fallback（接續下方調查）

### 改了什麼
- 異動檔案：`screener/database.py`（`get_chips_today`）、`tests/test_database.py`（+2 測試）

**根因（比下方調查更精確）**：下方調查說「族群頁用今天日期對不到就顯示─」方向對，但真正的
兇手定位到 `get_chips_today()`（database.py:246）——它對 institutional **和** margin 都用
`WHERE date = ?`（嚴格 trade_date=今天），**沒有 fallback**。institutional/margin 盤後才發布、
正常停在前一交易日，就查不到 → index.html（族群頁）全顯示「─」。
- **對照**：chips.html 走的 `calc_meta_chips_signals()` 用 `today = all_dates[-1]`（institutional
  表裡最新存在的日期）**本來就會 fallback**——我實跑驗過本機 41/41 族群都有值。所以是**兩條路徑
  行為不一致**：chips.html 會退、index.html 不會退。

**修法**：`get_chips_today` 的兩個子查詢改成
`WHERE date = (SELECT MAX(date) FROM <表> WHERE date <= ?)`，institutional / margin **各自**
fallback 到 <= 今天的最新可用日期（比照 `screener/institutional.py:118` 的做法）。兩張表獨立退，
因為某天可能只有一邊發布。

**驗證**：
- TDD：新增 2 測試（單純 fallback、institutional/margin 各停不同天各自退），全專案 114 passed。
- 本機真實 DB 實測：`get_chips_today('2026-07-08')`（institutional/margin 只到 07-07）修復前回
  **0 筆**、修復後回 **2268 筆**（2245 有外資、1279 有融資），族群頁不再全「─」。

### 資料來源相關
- 不適用抓取邏輯——這是「讀取層對正常資料延遲的 fallback」，跟下方調查結論一致：
  **institutional/margin 晚一天是正常的（盤後發布），不是抓取失敗**。

### 請 Debugger 驗證
- [ ] 全專案 114 passed（原 112 + 新 2）
- [ ] fallback 邏輯：institutional/margin 各自 `MAX(date) WHERE date <= today` 正確、兩表獨立
- [ ] 邊界：某表完全無資料時 `MAX(date)` 為 NULL → 該側空、FULL OUTER JOIN 仍回另一側（不 crash）

### 仍未處理（獨立問題，非這次範圍）
- **margin 07-07 只有 1279 筆（約半，缺 TPEx）**：那天 TPEx 融資融券疑似抓取失敗只寫了 TWSE。
  fallback 正確顯示「現有的」，但根本的「TPEx 那天為何沒抓到」要另外查（對照下方調查提的
  「main.py 對 TPEx 抓取失敗只 log warning 不擋流程」）。
- 族群個股表格 5/7/10/14 天累積漲跌幅欄位（log.md 待辦#2）、index.html UI 重設計（待辦#1）未動。

---

## [2026-07-08] 調查 - 族群頁「累積漲跌幅」疑似錯誤 + 外資/投信/融資全部無資料

### 調查方式
- Cody 提供具體例子（8261 富鼎等 7-8 檔功率半導體股，今日跌 -2.84%~-9.24%，但週漲跌顯示
  +8.71%~+26.44%），直接查 `data/screener.db` 對照 `html_generator.py::_weekly_pct()` 手動重算

### ✅ 「累積漲跌幅」（週漲跌%）驗證結果：算法跟資料都正確，不是 bug
- `_weekly_pct()`（`html_generator.py:140-148`）複利最近 5 個交易日 `change_pct`，用 8261 富鼎
  實際資料手動重算：`07-01 +9.98% / 07-02 +9.92% / 07-03 -2.14% / 07-06 +10.00%(漲停) /
  07-08 -2.84%(今日)` → 複利 `1.0998×1.0992×0.9786×1.10×0.9716=1.2641` → **+26.41%**，跟頁面
  顯示 +26.44% 對得上（四捨五入誤差）
- 這批股票（富鼎/百徽/統懋/強茂/虹揚-KY/大中/台半/尼克森，皆功率半導體/二極體）是真實的
  族群級行情：這週連續多天接近/觸及漲停噴出，今天集體獲利了結拉回，複利公式正確反映了這個
  真實走勢，不是計算錯誤

### 🔴 外資/投信/融資全部顯示「─」：資料源落後一天，需 Cody 確認
- 查 DB：`daily_prices` 最新到 **2026-07-08**，但 `institutional`／`margin` 兩張表最新都卡在
  **2026-07-07**（且 2026-07-07 經確認全市場 0 檔股票有 `daily_prices` 資料，代表當天不是
  交易日——`institutional`/`margin` 標成 07-07 這件事本身也值得覆查，不確定是正常的「機構
  資料本來就晚一天發布」還是抓取失敗遺留的舊資料）
- 族群頁的外資/投信/融資欄位用「今天」日期去對 `institutional`/`margin`，對不到 07-08 的資料
  就全部顯示「─」
- **需要 Cody 確認**：今天跑 `python main.py` 時，log 裡有沒有出現「TPEx 三大法人寫入失敗」
  或 institutional/margin 抓取失敗的警告（`main.py` 對 TPEx 抓取失敗目前只 log warning、不會
  擋住 daily_prices 繼續更新，之前 session 就報告過這個行為，這次疑似又踩到）

### 待辦（尚未動工，等 Cody 確認方向）
- [ ] 新增族群個股表格 5/7/10/14 天累積漲跌幅欄位（`calc_stock_sparklines()` 目前
  `lookback=11`，撐不到 14 天，需要擴大查詢範圍）——待確認是要直接加進現有表格，還是跟
  「族群績效 UI 重新設計」一起做
  
---

## [2026-07-07] 兩個 UI 小修復：族群欄位顏色太暗 + 外資/投信單位 K→張

### 改了什麼
- 異動檔案：`export/chips_generator.py`、`export/patterns_generator.py`、`export/html_generator.py`

**1. `chips.html`／`patterns.html` 族群欄位顏色太暗（Cody 反映）**
- `chips_generator.py` 的 `.ct-meta` class：`#475569` → `#94a3b8`（套用到所有用到族群欄位的表格：
  Section 3/3.5/4/6/7/8）
- `patterns_generator.py` 個股列族群欄 inline style：`#64748b` → `#94a3b8`
- 純顏色值調整，不影響任何邏輯

**2. `index.html` 族群層級外資/投信摘要單位標籤錯誤（Cody 反映「感覺多一個K」）**
- 根因：`html_generator.py::_fmt_chips_num()`（個股 modal）跟 `_chips_summary()`（族群層級外資/
  投信摘要）都把原始股數 `// 1000` 換算成張數後，標籤寫成 `K`；但 `chips_generator.py::_fmt_net()`
  對完全一樣的換算標籤是 `張`/`萬張`（≥10000張時）。數字本身沒有算錯（只除了一次1000），是三個
  頁面對同一種換算用了不一致的單位標籤，容易誤以為要再乘一次1000。
- 修法：新增 `html_generator.py::_fmt_lots_text(k, sign)` 共用 helper，比照 `_fmt_net()` 的
  `張`/`萬張`（≥10000張）邏輯，`_fmt_chips_num()`／`_chips_summary()`（外資/投信兩處）都改用它。
- 手動驗證換算：`1,234,567`股→`+1,234張`、`123,456,789`股→`+12.3萬張`，數字跟 chips.html 的
  `_fmt_net()` 輸出一致。

### 請 Debugger 驗證
- [ ] 全專案測試（我這邊：112 passed，純 UI 調整沒有新增/刪除測試）
- [ ] 實際跑 `python main.py` 後開 `docs/index.html`，確認族群層級外資/投信摘要顯示「張」/「萬張」
  不是「K」，且數字跟同一天 `docs/chips.html` 的個股籌碼數字換算一致（同一支股票、同一天，兩頁
  單位換算後數字量級應該一致）
- [ ] 確認 `chips.html`/`patterns.html` 族群欄位文字在深色背景下可讀性改善（`#94a3b8` vs 原本
  `#475569`/`#64748b`）

### 特別注意
- 這次沒有動 `chips_generator.py::_fmt_net()` 本身（它的 `張`/`萬張` 邏輯本來就是對的，是
  `html_generator.py` 兩處對齊過去）

---

## [2026-07-06] 去重 `_calc_streak`/`_streak`：新增 `streak_utils.py` 共用函式

### 改了什麼
- 異動檔案：新增 `streak_utils.py`；`screener/patterns.py`、`processors/performance.py`

**背景**：Cody 之前 review 籌碼邏輯時就記錄過「`screener/patterns.py::_calc_streak()` 跟
`processors/performance.py` 裡 nested closure `_streak()` 邏輯完全等價但各自維護一份」，這次
要求直接去重。

**做了什麼**：
- 新增 `streak_utils.py::calc_streak(values)`：合併兩邊完全等價的「末端連買(正)/連賣(負)天數」
  邏輯（正負號代表方向），內部 `list(values)` 正規化，同時接受 `pd.Series`（patterns.py 原本
  的呼叫方式）跟 `list`（performance.py 原本的呼叫方式）。
- `screener/patterns.py`：刪掉本地 `_calc_streak()` 定義，改成
  `from streak_utils import calc_streak as _calc_streak`（維持原本呼叫端名稱，`tests/test_patterns.py`
  的 `from screener.patterns import _calc_streak` 不用改）。
- `processors/performance.py`：刪掉 nested closure `_streak()` 定義，改成
  `from streak_utils import calc_streak as _streak`，呼叫端（`foreign_streak = _streak(...)`／
  `trust_streak = _streak(...)`）不用改。
- **沒有動** `screener/institutional.py::_calc_streak()`——那支是不同語意（只算連續正值天數、
  不處理負值方向、對 `None` 容錯），跟前兩支不是真的重複，合併有行為改變風險，故意保留。

### 資料來源相關（如有異動）
- 不適用——純內部去重，不影響任何資料抓取/來源邏輯。

### 請 Debugger 驗證
- [ ] 全專案 109 個測試都過（我這邊已確認，數量不變，這次沒新增/刪除測試案例，純重構）
- [ ] 確認 `screener/patterns.py`、`processors/performance.py` 兩處呼叫端行為跟修改前完全一致
  （可用 `2026-07-03` 之類的日期跑一次 `scan_patterns()`／`calc_meta_chips_signals()`，逐項比對
  `streak` 相關欄位輸出跟重構前相同）
- [ ] 確認 `screener/institutional.py::_calc_streak()` 維持不變的判斷合理（不同語意，不該合併）

---

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

## [2026-07-06] 修 Task 5 的 🔴 雙重 <td> + 收 Task 4 的 🟡 close/prev_close nan

### 改了什麼
- 異動檔案：`export/chips_generator.py`、`main.py`、`tests/test_chips_generator.py`
- 收 Debugger Task 5 報告的 🔴 + Task 4 帶下來的 🟡。

**🔴 修：`_insider_cell` 雙重 `<td>`（Section 8 欄位錯位）**
- `_insider_cell()` 回傳完整 `<td>...</td>`，但列組裝又外包 `f"<td>{company_html}</td>"` →
  `<td><td>...</td></td>`，一列 12 td vs 表頭 10 th。
- 修法：比照 `_price_cell` 的用法，把 `company_html`/`major_html` 改成 `f"{company_html}"`（不外包）。
- **這是計畫原碼就有的不一致**（`_price_cell` 不外包、`_insider_cell` 被外包），照抄跟著錯，非我新寫錯。
- 新增結構測試 `test_shareholder_table_row_td_count_matches_header`（資料列 `<td>` 數 == 表頭 `<th>`
  數）——正是 Debugger 建議的、substring 測試抓不到的那種結構斷言。修正後一列剛好 10 td。

**🟡 收：`close`/`prev_close` 的 nan（latent crash）**
- `daily_prices.close` 為 NULL → pandas `nan` → 洩漏進 `sh_rows['close']` → `_price_cell` 的
  `int(close)`（chips_generator.py:72）對 nan 會 `ValueError: cannot convert float NaN to integer`。
- 修法：main.py 組 sh_rows 時，`close`/`prev_close` 取值後用 `pd.isna()` 洗成 `None`（跟專案
  「DuckDB nullable 一律 pd.isna」慣例一致）。本機 0 筆 NULL close 未觸發，屬 latent，先修起來。

### 請 Debugger 驗證
- [ ] 全專案（我這邊：109 passed，含新結構測試）；`main.py` ast.parse OK
- [ ] **重驗結構**：`_shareholder_table` 一列的 `<td>` 數 == 表頭 `<th>` 數（=10），不再雙重 `<td>`
  （我加的結構測試已驗，Debugger 可再用 regex 數一次真實 HTML）
- [ ] `close`/`prev_close` 為 NULL 的股票（若找得到）不再讓 `_price_cell` crash、顯示「─」

### 特別注意
- 這是 Task 5 的修正（fix-forward），計畫 Task 1-5 本體不變，補上結構正確性 + latent crash 防護。

---

## [2026-07-06] 大戶張數化+內部人持股計畫 Task 5：Section 8 表格新增張數變化+內部人欄位（計畫完成）

### 改了什麼
- 異動檔案：`export/chips_generator.py`（`_shareholder_table()` + 新增 `_insider_cell()`）、
  `tests/test_chips_generator.py`（+3 測試、import 補 `_shareholder_table`）
- 對照計畫 Task 5（TDD）。依賴 Task 4✅。**這是計畫最後一個 Task。**

**做了什麼**：
- `_shareholder_table()` 表頭/列新增 3 個顯示：
  - **大戶張數變化**（`share_chg` 股數 ÷1000 → 張，紅漲綠跌，缺值「─」）
  - **公司派持股**、**大股東持股**（各用新的 `_insider_cell()`：張數 + 月變化張數 + 質押%）
  - 「收盤」欄標題改成「收盤(週漲跌)」對應 Task 4 把 change_pct 語意改成集保週期週漲跌。
- `_insider_cell(shares, chg, pledge_pct)`：`shares is None` → 顯示「─」（對應 Task 2/4 報告的
  🟡：缺值顯示「—」而非 0，避免把「資料缺」誤導成「零變化」）；有值則張數 +（有月變化才顯示）
  月變化張數 +（有質押才顯示）質押%。

### 資料來源相關（如有異動）
- 不適用——呈現層，資料源不變。

### 請 Debugger 驗證
- [ ] `tests/test_chips_generator.py`（我這邊：11 passed，含新增 3 個）；全專案（我這邊：108 passed）
- [ ] **股→張換算**：`share_chg`/insider 的股數都 ÷1000 顯示成「張」（台股 1 張=1000 股），確認換算對、
  數字方向（紅漲綠跌）對。
- [ ] **缺值顯示**：沒有 insider_holdings 資料的股票，公司派/大股東欄顯示「─」不是「0張」（我加測試驗過）。
- [ ] **建議實跑**：跑過 `--update-insider-holdings` + `python main.py` 後，開 `docs/chips.html`
  Section 8，確認新三欄有正確渲染、版面沒跑掉（我只用合成資料驗邏輯，沒有真實頁面）。

### 特別注意
- **整個計畫（Task 1-5）到此完成**：大戶實際張數持久化 → get_shareholder_top 回傳張數變化 →
  內部人持股 scraper + 表 → main.py 串接 + 資料組裝 → Section 8 表格顯示。
- `lv12_15_shares`（大戶張數絕對值）有帶進 sh_rows 但表格只顯示「張數變化」（`share_chg`），
  沒有獨立顯示絕對張數欄——與計畫一致（絕對值目前用不到，先備著）。

---

## [2026-07-06] 大戶張數化+內部人持股計畫 Task 4：main.py 串接 --update-insider-holdings + sh_rows 組裝（含收 Task 3 的 🟡）

### 改了什麼
- 異動檔案：`main.py`、`scrapers/insider_holdings.py`（收 🟡）、`tests/test_insider_holdings.py`（+2 測試）
- 對照計畫 Task 4。依賴 Task 2✅ + Task 3✅。

**1. `main.py` 串接**：
- 新增 `_update_insider_holdings()`（先 `init_db()` 再抓再 save，確保表存在——對應 Debugger Task 3
  報告的提醒）。
- 新增 CLI flag `--update-insider-holdings` + dispatch。
- **改寫 sh_rows 組裝**：
  - 股價對齊改成「**對齊集保週期**」——查本週(`date`)/上週(`prev_date`)各自對應日期的收盤價，
    算 `price_week_chg`（放進既有 `change_pct` key，語意從「最新交易日漲跌」變「集保週期週漲跌」）。
    **不再**用「最新交易日」單一股價。
  - join `insider_holdings`（每股最新一筆月資料）→ 新增 company_*/major_holder_* 六個欄位。
  - 新增 `lv12_15_shares`、`share_chg`。

**2. nullable 處理（對應 Debugger Task 2 報告的 🟡）**：
- `share_chg`/`lv12_15_shares`/insider 六欄一律用 `pd.notna()` 判斷，缺值帶 `None`（不是 0、不是
  `<NA>`）。**顯示成「—」是 Task 5 的事**，Task 4 只保證帶乾淨的 None 下去。
- ⚠️ **保留** `week_chg` 的 `None if pd.isna(...) else float(...)`（2026-07-05 修過的 NaN fix）——
  計畫 Task 4 的範例碼把它寫回舊的 `is not None`（會漏 NaN），我沒退回。

**3. 收 Task 3 的 🟡（`_to_int` 脆弱性）**：
- `scrapers/insider_holdings.py::_to_int()` 改成無法解析（`-`／`－`／`N/A`）回 0，不再拋 ValueError
  讓整支股票靜默消失。新增 2 測試（`_to_int` 直接測 + `_parse_response` 帶 `-` cell 仍能解析）。

### 資料來源相關（如有異動）
- 不適用——串接與資料組裝，資料源規則不變。

### 請 Debugger 驗證
- [ ] 全專案（我這邊：105 passed，含新增 2 個 _to_int 測試）；`main.py` ast.parse OK
- [ ] **我已 smoke-test 過價格對齊**（臨時 DB）：DuckDB `date IN (SELECT UNNEST(?))` 接受
  numpy.datetime64 綁定、`_price_map` 的 `str(Timestamp)` key 兩邊對得上、週漲跌算對
  （950/900=+5.56%）。**建議用真實 `data/screener.db` 跑一次確認**（我沒真實多週集保+對應股價資料）。
- [ ] **建議實跑一次串接**：`python main.py --update-insider-holdings`（會實際打 MOPS ~1040 支、
  較久）確認寫入 `insider_holdings`；再跑 `python main.py` 確認 sh_rows 有帶新欄位、不 crash。
- [ ] 確認 `share_chg`/insider chg 缺值時帶的是 `None`（Task 5 會把它顯示成「—」）。

### 特別注意
- **Section 8 表格還沒顯示新欄位**——Task 5 才改 `_shareholder_table()` 加「大戶張數變化/公司派/
  大股東」欄。Task 4 只是把資料備妥在 sh_rows 裡，跑 `main.py` 目前 chips.html 外觀不變。

---

## [2026-07-06] 大戶張數化+內部人持股計畫 Task 3：新增 scrapers/insider_holdings.py（內部人持股月頻）

### 改了什麼
- 異動檔案：新增 `scrapers/insider_holdings.py`、`screener/database.py`（新增 `insider_holdings` 表）、
  新增 `tests/test_insider_holdings.py`
- 對照計畫 Task 3（TDD）。這是**獨立新資料源**，不依賴 Task 1/2。

**做了什麼**：
- `scrapers/insider_holdings.py`：抓公開資訊觀測站 `ajax_stapap1`（POST，不需 session token），
  逐列解析董事/監察人/經理人（→公司派桶）與大股東/未分類（→大股東桶）的持股與設質股數。
  - `_parse_response()`：regex 逐列（`<TR class='odd'/'even'>` + 9 個 `<TD>`），`資料年月:11505`
    → 民國轉西元 `2026-05-01`；「查無」→ None。
  - `fetch_insider_holdings_monthly()`：retry 迴圈，`_fetch_one_stock()` **不吞例外**（比照
    shareholder.py 修過的教訓，讓例外冒給外層重試）。
  - `save_to_db()`：算 `company_pledge_pct`/`major_holder_pledge_pct` 與 `company_chg`/
    `major_holder_chg`（跟前一個月比），upsert 進 `insider_holdings` 表。
- `insider_holdings` 表 schema（8 欄，PK: stock_id+report_date）。

### 資料來源相關（如有異動）
- **新資料源**：公開資訊觀測站（MOPS）`ajax_stapap1`，月頻。跟 TWSE/TPEx、TDCC、FinMind/yfinance
  都不同來源，各自獨立。
- 「公司派」= 董事＋監察人＋經理人＋相關（職稱含 董事/監察人/經理/協理/主管）；
  「大股東」= 職稱含「大股東」或未分類（如「其他」）。
- `verify=False`：沿用專案既有慣例（Windows SSL），配 `warnings.filterwarnings("ignore")`。

### 請 Debugger 驗證
- [ ] `tests/test_insider_holdings.py` 3 個測試過（我這邊：3 passed）；全專案（我這邊：103 passed）
- [ ] **重點（我沒辦法在本機驗的）**：`_parse_response()` 的 regex 是對照計畫作者實際打過的真實
  HTML 格式寫的，但我只用合成 `_SAMPLE_HTML` 測。**建議實際打一兩支股票的真實回應**（例如 2330），
  確認 (a) `<TR class='odd'/'even'>` + 9 欄格式沒變、(b) 職稱分類正確、(c) 民國年月解析對。
  regex 對 HTML 格式敏感，格式一變就會靜默解析不到（回 0 或 None）。
- [ ] `insider_holdings` 位置式 INSERT：全新表（只走 CREATE TABLE、無 ALTER），欄位順序固定，
  跟 Task 1 的 ALTER-append 情境不同，位置式安全——請確認這個判斷。
- [ ] `save_to_db` 月變化：跨月 chg 正確、首月無前值為 NULL。

### 特別注意
- 這個 scraper 還沒接進 `main.py`（Task 4 才做 `--update-insider-holdings` CLI 跟資料組裝），
  目前只是獨立模組 + 表，跑 `main.py` 不會用到它。

---

## [2026-07-06] 大戶張數化+內部人持股計畫 Task 2：get_shareholder_top() 回傳 prev_date + 張數變化

### 改了什麼
- 異動檔案：`screener/database.py`（`get_shareholder_top()`）、新增 `tests/test_database.py`
- 對照計畫 Task 2（TDD：寫失敗測試→紅→實作→綠）。依賴 Task 1 的 `lv12_15_shares`（已完成）。

**做了什麼**：
- `get_shareholder_top()` 從「MAX(date) 只取最新一筆」改成 `ROW_NUMBER() OVER (PARTITION BY
  stock_id ORDER BY date DESC)`，取 rn=1（本週）LEFT JOIN rn=2（上週），新增回傳三個欄位：
  `prev_date`（上週日期）、`lv12_15_shares`（本週大戶張數）、`share_chg`（= 本週 − 上週股數差）。
- 只有一週資料時，LEFT JOIN 無 rn=2 → `prev_date`/`share_chg` 為 NULL（pandas NaT/NaN），不報錯。
- 既有回傳欄位（date/lv12_15_pct/lv12_15_cnt/week_chg/streak）都保留，main.py 現有消費端不受影響
  （Task 4 才會用到新欄位）。

### ⚠️ 我對計畫測試做的一個小修正（請 Debugger 確認）
計畫 Task 2 的測試斷言 `str(row["date"]) == "2026-07-03"`，實測**過不了**——DuckDB DATE 經
pandas `.df()` 轉出來是 `datetime64[us]`（Timestamp），`str()` 是 `"2026-07-03 00:00:00"`。
- 我實測確認：**舊版 `get_shareholder_top`（MAX(date) 那版）也是回傳 Timestamp**，不是我改壞的，
  是計畫測試對型別的假設有誤。
- **我沒有在實作裡把日期正規化成乾淨 date 字串**，因為 Task 4 的股價對齊是用 `str(row["date"])`
  當 key 去比對 `daily_prices`（那邊 `.df()` 也是 Timestamp）。若只把這裡改乾淨、`daily_prices`
  還是 Timestamp，key 會對不上、股價查不到。**保持兩邊都 Timestamp 才一致。**
- 修法：把測試斷言改成 `str(row["date"])[:10] == "2026-07-03"`（只比日期部分、型別無關）。

### 資料來源相關（如有異動）
- 不適用——DB 讀取層查詢改寫，不碰資料抓取。

### 請 Debugger 驗證
- [ ] `tests/test_database.py` 2 個測試過（我這邊：2 passed）；全專案（我這邊：100 passed）
- [ ] 確認 `share_chg` 計算正確（本週 − 上週股數差）、單週資料時 `prev_date`/`share_chg` 為 NULL 不報錯
- [ ] 確認上面那個「保持 date 為 Timestamp」的決定合理——特別是 Task 4 會用 `str(row["date"])`
  跟 `daily_prices` 的 `str(r["date"])` 做 key 比對，兩邊型別要一致（都 Timestamp）才對得上

---

## [2026-07-06] 收 _push_html 的 🟡：只在真的有 rebase 進行中才 abort（消 log 雜訊）

### 改了什麼
- 異動檔案：`main.py`（`_push_html()` 的 pull 失敗分支）
- 背景：Debugger 在上一輪驗證回報的 🟡——`pull --rebase` 若因**非衝突原因**失敗（無 upstream／
  網路斷），後面無條件的 `git rebase --abort` 會噴「沒有進行中的 rebase」的無害 log 雜訊。
- 修法：新增 `_rebase_in_progress()`（用 `git rev-parse --git-path rebase-merge/rebase-apply`
  判斷，worktree-safe），**只有真的有 rebase 卡住才 abort**；非衝突失敗改印另一句「可能無
  upstream 或網路問題」的警告。兩種情況都一樣：本機 commit 保留、不 push。

### 資料來源相關（如有異動）
- 不適用——純 git 自動化流程的 log 清理，行為（commit 保留、不 push）不變。

### 請 Debugger 驗證
- [ ] `ast.parse` 通過（我已跑：main.py 語法 OK）
- [ ] 模擬「非衝突失敗」（例如把 remote 拔掉／無 upstream）跑 `_push_html`，確認**不再**出現
  「no rebase in progress」那句雜訊，改印「可能無 upstream 或網路問題」
- [ ] 模擬「衝突」情境，確認仍會正確 `rebase --abort` 回乾淨（跟上一輪驗過的行為一致）

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

## [2026-07-22] 個股決策主表收合「等待確認/風險升高」噪音

### 改了什麼
- 異動檔案：export/momentum_generator.py, tests/test_momentum_generator.py
- 邏輯說明：
  - Cody 實跑 `python main.py` 看到今天真實 momentum.html 後回報「個股決策那個有超級多檔」——
    實際統計全表 1036 檔：等待確認 646（62%）+ 風險升高 334（32%）= 94.6% 是非行動訊號的噪音，
    真正有意義的只有進場候選 8 + 出場條件命中 18 + 續強觀察 28 + 跌停風險 2 = 56 檔（5.4%）。
  - 新增 `_DECISION_TABLE_COLLAPSED_LABELS = {"等待確認", "風險升高"}`，`_decision_table_section_html()`
    把 decision_table 拆成 highlighted（4個有意義標籤，一律顯示）+ collapsed（這兩個標籤，預設收合）。
  - 用原生 `<button>` + `hidden` 屬性 toggle 第二個 `<tbody id="decision-collapsed">`（table 結構下
    details/summary 不能合法包住 tbody，改用 button 較簡單；button 天生鍵盤可達，不用額外
    role/onkeydown）。按鈕文字顯示實際收合檔數（例：「顯示其餘982檔（等待確認／風險升高）▾」）。
  - 資料完全不丟，只是預設不佔版面；collapsed 為空時（例如全部都是有意義標籤）不產生
    toggle 按鈕與空 tbody，避免多餘 DOM。
  - 排序邏輯（族群排序 avg_change_pct）Cody 確認維持現狀不變，不用改。

### 資料來源相關（如有異動）
- 上市資料（TWSE）：無異動，純前端渲染邏輯
- 上櫃資料（TPEx / FinMind）：無異動

### 請 Debugger 驗證
- [ ] 全部45個momentum_generator測試 + 全專案387個測試通過（已本機跑過，全綠）
- [ ] 實際瀏覽器測試：點擊「顯示其餘N檔」按鈕能正確展開，再點一次能收合，文字正確切換
- [ ] 鍵盤可達性：Tab到按鈕、Enter/Space觸發（原生button預期沒問題，但要實際測試不只看code）
- [ ] 全部標籤都是有意義標籤時（沒有等待確認/風險升高）不會產生多餘的收合按鈕
- [ ] 收合狀態下畫面不應該有大量空白/版面跳動

### 特別注意
- 這次改動範圍限定在 momentum_generator.py 本身，沒有動 export/index_generator.py 或排序邏輯
- 對應今天稍早 `python main.py` 已經 push 到 origin 的 `0e9304d`——這次的收合修正**還沒有**
  重新產生頁面，`docs/momentum.html` 目前線上還是未收合的舊版，下次跑 main.py 時才會套用

## [2026-07-22] 籌碼頁/型態頁視覺配色對齊熱區格改版

### 改了什麼
- 異動檔案：export/chips_generator.py, export/patterns_generator.py
- 邏輯說明：
  - Cody 反映 chips.html/patterns.html 的 UI 設計要對齊 index.html（熱區格改版後的新視覺）。
    核對發現全站原本有3套視覺語言：index.html+momentum.html（新版 #080B12 深色+金色accent）、
    chips.html（舊版 #08101c 藍色accent）、patterns.html（另一套舊版 #0b0f18 藍色accent，
    還是寫死hex沒用CSS變數）。
  - chips_generator.py：只改 `:root{}` 這行 CSS 變數的值（bg/surface/border/text/accent/
    up/down），變數名稱不動，然後把散落在檔案各處、源自舊配色的少數寫死hex（topbar/
    section-nav背景、table邊框/斑馬紋等）一併對齊。紅漲綠跌(#f87171/#4ade80→#E6432F/
    #37B25C)跟琥珀警示(#fbbf24→#F0BB55金色accent)是全域替換(共39處)，量最大、視覺影響也最大。
  - patterns_generator.py：沒有CSS變數系統，全部用python字串全域替換寫死的hex（bg/surface/
    border/text/muted/accent/up/down，共15組替換）。有踩到一個坑：`#60a5fa`同時被用在
    "tab-btn.active的accent" 跟 "TWSE市場徽章文字色" 兩種不同語意上，全域替換後TWSE徽章
    變成「金色文字配藍色邊框」的不協調組合——修正成跟chips.html一致的TWSE/TPEx徽章配色
    (`#9bc7ff`/`#416d9f`、`#cabaff`/`#6e5999`)，兩頁徽章色也順便對齊了。
  - **刻意不動**的部分：TWSE/TPEx市場徽章、pattern類型色碼字典（雙底/頭肩底/VCP突破等8種
    圖形各自的顏色）、少數低頻率的分類用色（如投信連賣的藍色徽章）——這些是分類用途的色碼，
    不是品牌強調色，跟其他頁面不用強求完全一致。

### 資料來源相關（如有異動）
- 上市資料（TWSE）：無異動，純CSS/顏色調整
- 上櫃資料（TPEx / FinMind）：無異動

### 請 Debugger 驗證
- [ ] 全部387個測試通過（已本機跑過，全綠，包含chips_generator 36個+patterns_generator 3個）
- [ ] 實際瀏覽器開 chips.html/patterns.html，視覺上跟 index.html/momentum.html 感覺像同一個網站
- [ ] chips.html 的 TWSE/TPEx 徽章、紅漲綠跌數字、投信/外資連買連賣徽章顏色顯示正常
- [ ] patterns.html 的 TWSE/TPEx 徽章顏色正確（這次修正的重點，不應該是金色文字配藍色邊框）
- [ ] patterns.html 的8種圖形類型色碼（雙底/頭肩底等）維持原本沒動過

### 特別注意
- 這次改動範圍限定在這兩個檔案的CSS/顏色，沒有動任何邏輯/資料處理
- 這是 Cody 明確指示「不用brainstorming直接改」略過的一次，範圍相對單純（純視覺配色替換）

## [2026-07-22] index.html個股卡片恢復（含sparkline）

### 改了什麼
- 異動檔案：export/index_generator.py, main.py, tests/test_index_generator.py
- 邏輯說明：
  - Cody 反映「個股的卡片怎麼不見？」——熱區格改版把個股展開面板從舊版的
    `.stock-card` 卡片格（含sparkline走勢圖）簡化成純 `<table>`，且 Task 9 清理
    main.py 時把 `calc_stock_sparklines()` 的呼叫當死碼移除了。
  - main.py：補回 `calc_stock_sparklines(universe_df)` 呼叫（獨立 try/except fail-soft，
    比照 heatgrid_windows 慣例），傳進 `generate_index_html(..., stock_sparklines=...)`。
  - `build_stock_detail_data()` 新增 `stock_sparklines` 參數，每支股票的 dict 多了
    `pcts`/`dates`（沒有資料時是空 list，不會 crash）。
  - 前端 `selectGroup()` 的個股清單從 `<table class="stocktable">` 改成
    `.stock-cards-wrap` 卡片格，每張卡新增 `buildSparkline()` 產生的 inline SVG
    走勢圖（用 var(--up)/var(--down) 上色，跟全站配色一致）。

### 資料來源相關（如有異動）
- 上市資料（TWSE）：無異動
- 上櫃資料（TPEx / FinMind）：無異動，`calc_stock_sparklines()` 讀的是 DuckDB
  `daily_prices`（每日流程既有資料），沒有新增資料源

### 請 Debugger 驗證
- [ ] 全部391個測試通過（已本機跑過，全綠）
- [ ] 實際瀏覽器點開族群卡片，個股清單顯示卡片格（不是表格），每張卡有走勢圖
- [ ] sparkline hover能看到日期+漲跌%的title tooltip
- [ ] 某族群完全沒有sparkline資料時（例如新股）不會crash，只是卡片沒有走勢圖

### 特別注意
- 沒有恢復舊版 `_stock_card_html()` 的完整功能（外資/投信/融資籌碼摘要、
  openStockModal彈窗）——這次只補「卡片格式+sparkline」，範圍比舊版簡單

## [2026-07-22] 全面稽核補回熱區格改版遺漏功能 + 族群近況分類重構

### 改了什麼
- 異動檔案：export/index_generator.py, main.py, tests/test_index_generator.py
- 對應 commit：adcd801（功能補回）、bb0f80f（族群近況重構）
- 背景：Cody跑過`python main.py`看到真實頁面後，陸續回報一系列「以前有的東西不見了」，
  最後要求全面稽核export/html_generator.py(舊版)跟export/index_generator.py(新版)的
  功能落差。稽核結果見這次對話記錄，共13項落差，逐一處理如下。

### 補回的功能（commit adcd801）
1. **修復真正的bug**：chips.html的`#meta=`深連結因為新版`selectGroup()`沒有讀取
   `location.hash`而失效（chips_generator.py:_meta_link()還在產生這種連結），補回
   IIFE在載入時自動展開對應族群面板。
2. 個股搜尋框(#stock-search)+下拉搜尋結果(STOCK_INDEX/META_INDEX)，可搜股票代號/
   名稱/族群名，點擊直接跳轉展開對應族群。
3. 個股卡片補回近5/7/10/14日累積漲跌(get_rolling_returns())、外資/投信/融資摘要
   (get_chips_today())、排序控制(漲跌%/代號/收盤/近N日)。
4. 無行情個股不再從清單消失，改成no_data=True灰階佔位卡。
5. 族群展開面板補回族群層級sparkline(複用個股sparkline的buildSparkline())跟籌碼
   摘要(外資/投信淨額+連買賣天數+融資變動警示)。
6. 熱區格卡片補回3/5/7日累積漲跌badge(calc_cumulative_meta())跟排名升降箭頭。
7. 補回大盤分級儀表板(五級方向+資金集中度診斷+操作提示)跟巨量換手訊號區塊
   (前日漲停→今日爆量收跌+法人確認)，main.py新增對應資料計算+傳遞(全部fail-soft)。
- **刻意沒恢復**：個股彈窗(openStockModal)——這次改用把sparkline/籌碼/量比直接放上
  卡片本身取代，不需要額外點擊開modal。

### 族群近況分類重構（commit bb0f80f）
Cody回報實際案例：**功率半導體今日排名#40→#1、+5.66%，卻被歸類成「退燒」**。
根因：accel(週對週5日滾動窗比較)回答的是趨勢問題，跟「今天是不是正在發生大事」
是兩個不同問題，兩者合法地可以背離；異動族群區塊的burst判定又同時要求量比>=1.5，
這次案例量比不夠高，兩邊都漏接。

修法：
- `build_sector_recap()`簽名改吃`build_heatgrid_cards()`算好的cards（不再重算）。
- 新增「今日爆發」：只看排名跳動(>=10)+今日上漲，不要求量比。
- cold_top5排除掉「今日爆發」的族群——不能同時講「退燒」又「爆發」。
- 新增「外資悄悄佈局」「投信悄悄佈局」：股價還沒明顯反應(±1%內)但法人連買>=3天。
- 新增「量能異常」：量比>=1.5x但股價還沒反應(±2%內)。
- 族群近況從2欄(升溫/退燒)擴充成6欄，版面改用auto-fit responsive grid。

### 資料來源相關（如有異動）
- 上市資料（TWSE）：無異動
- 上櫃資料（TPEx / FinMind）：無異動，全部沿用main.py既有的DB查詢函式，只是這次
  接上index.html而已（get_rolling_returns/get_chips_today/scan_volume_turnover/
  calc_cumulative_meta都是main.py本來就有的既有函式）

### 請 Debugger 驗證
- [ ] 全部401個測試通過（已本機跑過，全綠）
- [ ] 實際瀏覽器測試：搜尋框、#meta=深連結（從chips.html點連結進來）、個股卡片排序
- [ ] 族群近況6個分類版面正常顯示，手機版(auto-fit grid)不跑版
- [ ] 大盤分級儀表板+巨量換手訊號區塊有資料時正常顯示，沒資料時不顯示空區塊
- [ ] 確認功率半導體這類「今日爆發」族群不再出現在「退燒」清單

### 特別注意
- 這是一次範圍很大的改動(3個檔案+667行/189行)，建議Debugger花多一點時間實測，
  不只看code review
- main.py新增了4個新的資料計算呼叫(rolling_returns/index_chips_df/vol_turnover_signals
  /沿用既有的cum_data)，都各自獨立try/except，理論上不會互相影響，但實測時留意log
  有沒有異常warning

## [2026-07-23] 個股卡片回到card格式+補量價，emoji全拿掉

### 改了什麼
- 異動檔案：export/index_generator.py, export/momentum_generator.py, export/patterns_generator.py, tests/test_index_generator.py
- 邏輯說明：
  - **emoji/icon全部拿掉**（Cody要求「專業一點」）：index.html的大盤情緒圖示、族群近況6欄
    標題icon、溫度徽章(🔥❄️)、搜尋框placeholder(🔍)、法人確認符號(✓)；momentum.html決策
    證據清單的✓/✗（顏色已區分pass/fail，不需要符號）；patterns.html形態徽章跟分頁籤icon。
    chips.html本來就沒有裝飾性emoji。`classify_temp()`/`_REGIME_TIERS`/`_PATTERN_LABEL`
    的icon/emoji欄位移除或留空字串，call site不用大改。
  - **個股列表格式來回調整**：卡片→表格→又改回卡片（Cody中途多次修正方向），最終定案是
    **卡片格式**，不是表格。過程中一度做了表格版本又整個revert掉（commit `fad7c39`已
    revert），純表格版沒有留下來。
  - **補回真正遺漏的量價資料**：Cody回報「個股相關量價都不見了」——確認全面恢復時漏了
    舊版`_stock_card_html()`的「今日成交量」+「量比」徽章，這次從`calc_stock_sparklines()`
    既有的`volumes`/`vol_ratio`欄位補上（`build_stock_detail_data()`新增`volume`/
    `vol_ratio`兩個欄位）。同時補上融資摘要（融資餘額變動%），排序選單加了「量比」選項。
  - **走勢圖改成點擊展開**：sparkline不再永遠顯示在卡片上，改成「走勢▾」按鈕點擊才展開/
    收合（`toggleCardSpark()`），減少卡片預設資訊量。

### 資料來源相關（如有異動）
- 無異動，volume/vol_ratio都是`calc_stock_sparklines()`既有算好的欄位，只是接上而已

### 請 Debugger 驗證
- [ ] 全部403個測試通過（已本機跑過，全綠）
- [ ] 個股卡片：今日成交量+量比徽章正確顯示，量比>=1.5x要有強調色
- [ ] 點擊「走勢▾」按鈕能正確展開/收合sparkline，再點一次能收合
- [ ] 排序選單新增的「量比」選項能正確排序
- [ ] 確認四個頁面視覺上沒有裝飾性emoji（大盤情緒/族群近況/溫度徽章/形態徽章等）

### 特別注意
- 這次個股列表格式反覆調整（卡片→表格→revert回卡片），**最終確定是卡片格式**，
  不是表格。如果之後又聽到「表格」的需求，要先跟Cody確認是不是要推翻這次的決定，
  不要直接照字面做，避免又跑一輪來回

## [2026-07-23] 追記：個股列表/個股卡片正確拆成兩層

### 改了什麼
- 異動檔案：export/index_generator.py, tests/test_index_generator.py

### 邏輯說明（推翻上一則追記的做法）
上一則(2026-07-23稍早)把sparkline/量價/籌碼全部塞進列表格子本身，用「走勢▾」按鈕
展開——Cody後來說明「卡片」的正確意思是：**點擊個股才彈出來的東西**，不是列表格子
本身。正確架構應該是：

- **個股列表**（`.stock-item`）：只顯示基本資訊——代號/名稱/收盤/漲跌%，一直都是
  精簡的清單，不會因為點擊以外的操作變得資訊爆炸。
- **個股卡片**（`.stock-card-modal`）：點擊列表項目才彈出的**彈窗**，裡面才放走勢圖
  (sparkline)、量價（今日成交量+量比）、近5/7/10/14日、外資/投信/融資摘要——這些是
  「列表之外的資訊」，符合Cody原話「裡面有其他除了列表之外的資訊」。

`openStockCard(sid)`/`closeStockCard()` 用 `_panelStocks`（`selectGroup()` 已經設定好的
當前族群股票清單）查資料，不需要重新從STOCKS查表。支援點背景遮罩或按Escape關閉；
`selectGroup()` 切換族群時也會呼叫 `closeStockCard()` 順便關掉還開著的個股卡片，
避免殘留孤兒彈窗。

### 請 Debugger 驗證
- [ ] 全部404個測試通過（已本機跑過，全綠）
- [ ] 個股列表格子只顯示代號/名稱/收盤/漲跌%，沒有其他資訊
- [ ] 點擊個股格子會跳出彈窗（卡片），裡面有走勢圖+量價+近N日+籌碼摘要
- [ ] 點擊彈窗背景遮罩、或按Escape，彈窗會關閉
- [ ] 切換族群（點另一個熱區格）時，還開著的個股卡片彈窗會自動關閉

### 特別注意
- **這是本次會話第三次調整個股列表/卡片的呈現方式**（卡片內嵌sparkline→表格→
  revert回卡片內嵌+按鈕展開sparkline→現在這版：列表+點擊彈窗）。這次的版本是根據
  Cody明確澄清「卡片＝點擊才出現的東西」定案，如果之後還有相關回饋，麻煩先跟Cody
  確認是否要推翻這個定案，避免再跑一輪來回

## [2026-07-23] 修正真正的bug：個股列表要點欄位排序才會出現

### 改了什麼
- 異動檔案：export/index_generator.py, tests/test_index_generator.py

### 邏輯說明
Cody回報在GitHub Pages線上版本點族群卡片後「根本沒有列表，列表要點欄位才會出現」。
這次**用jsdom實際模擬瀏覽器點擊重現了問題**（不是只看程式碼猜），確認是真的bug：

`selectGroup()` 裡 `renderPanelStocks()` 原本在 `panel.insertAdjacentElement()` 
**之前**呼叫——這時 `panel` 還是離線節點（沒掛進 `document`），`renderPanelStocks()`
內部用 `document.getElementById('panelStocksWrap')` 找 tbody，因為 panel 還沒掛進
document，這個ID全域查詢找不到東西，`wrap===null` 的 guard 直接擋掉，表格永遠是空的。
直到使用者點擊欄位標題觸發 `sortStockList()` 重新呼叫 `renderPanelStocks()`，這時
panel 已經在 document 裡了，才第一次真的 render 出東西——完全符合「要點欄位才會出現」
的回報現象。

**修法**：把 `renderPanelStocks()` 的呼叫移到 `insertAdjacentElement()` 之後。

**驗證方式**：用 jsdom 建立真實 DOM 環境，實際 `dispatchEvent` 模擬點擊熱區格 tile，
確認修正前 tbody 是空的、修正後 tbody 立即有正確股票列；接著模擬點擊股票列，確認
個股卡片彈窗正確跳出。新增原始碼順序的 pytest 回歸測試守住這個修正順序。

### 請 Debugger 驗證
- [ ] 全部406個測試通過（已本機跑過，全綠）
- [ ] **這項務必用瀏覽器實測**：點任一族群熱區格，個股列表要立即出現，不需要先點
      欄位標題（這是這次修的bug，之前所有report都只看code沒有真的點過，這次我自己
      用jsdom點過確認修好了，但麻煩實際瀏覽器再測一次）
- [ ] 點欄位標題排序、點股票列開個股卡片，都要正常運作

### 特別注意
- 這個bug存在的原因是：先前這個功能經過好幾輪修改（卡片→表格→revert→列表+彈窗→
  排序改欄位標題），過程中沒有人用瀏覽器/jsdom實際執行過JS，只靠靜態程式碼審查跟
  pytest字串比對測試，這類「DOM插入順序」的bug完全不會被這些方法抓到。以後如果
  牽涉到DOM操作順序的改動，建議至少用jsdom簡單跑一次實際互動再回報「已修好」

## [2026-07-23] 族群分類調整：工業電腦從電腦周邊獨立拆出

### 改了什麼
- 異動檔案：config.py

### 邏輯說明
Cody要求把工業電腦相關獨立成新的META族群，不要再併在「電腦周邊」裡。拆出的關鍵字：
`工業電腦`、`掌上型工業電腦`、`自動資料收集產品`、`條碼掃描器`（確認過MoneyDJ沒有
"Edge AI"這個產業分類可以拉，唯一AI相關的是「AI伺服器」，本來就已經是獨立族群）。

**兩處都改了，缺一不可：**
- `META_PRIORITY_LIST`（config.py:249）：`scripts/build_universe.py` 建
  `stock_universe.csv` 時用，決定每支股票的 `meta_sector` 欄位。
- `META_SECTORS`（config.py:446）：`calc_meta_performance()`/`get_meta_sector()`
  每日流程用，把 MoneyDJ 抓到的小族群名即時併進主族群。

筆電/桌機/鍵鼠/滑鼠/儲存設備/印表機/KIOSK/POS機系統等維持在「電腦周邊」，只拆
IPC 本業直接相關的關鍵字，沒有連 KIOSK/POS 一起拉（Cody 選的是精簡範圍）。

### 資料來源相關（如有異動）
- 上市資料（TWSE）/上櫃資料（TPEx）：無異動，純分類邏輯調整

### ⚠️ 需要 Cody 手動執行的後續步驟
`META_PRIORITY_LIST` 的改動**不會自動生效**——`data/stock_universe.csv` 是
`scripts/build_universe.py` 一次性建出來的靜態檔案，個股的 `meta_sector` 欄位在
這次改動前就已經寫死是「電腦周邊」了。**要重跑 `python scripts/build_universe.py`
重建 `stock_universe.csv`**，工業電腦相關個股才會真的被歸到新族群。這是一次性
build 指令，不在每日 `main.py` 流程裡，需要 Cody 自己在 terminal 執行。

`META_SECTORS` 那邊不用額外動作，下次 `python main.py` 跑的時候就會直接生效
（因為那是每日流程即時查表，不是靜態建檔）。

### 請 Debugger 驗證
- [ ] 全部406個測試通過（已本機跑過，全綠，純config.py改動沒有動到任何邏輯）
- [ ] `python -c "import config; print(config.get_meta_sector('工業電腦'))"` 
      應該輸出 `工業電腦`
- [ ] Cody重跑`build_universe.py`後，確認樺漢/研華/凌華等IPC股的meta_sector
      欄位變成「工業電腦」，不再是「電腦周邊」

## [2026-07-23] 工業電腦資料落地 + build_universe.py 過時警告 + 列表新增5/7/10/14日欄位

### 改了什麼
- 異動檔案：data/stock_universe.csv, export/index_generator.py, tests/test_index_generator.py

### ⚠️ 重要發現：scripts/build_universe.py 已過時，不要直接重跑
Cody要工業電腦分類落地，照原本計畫要跑 `python scripts/build_universe.py` 重建
`stock_universe.csv`。**實際執行後發現這支腳本產出的檔案有兩個嚴重問題**：
1. **完全沒有 `exchange` 欄位**——正式版是6欄(`stock_id,stock_name,exchange,
   meta_sector,sub_sector,note`)，腳本產出只有5欄，少了`exchange`。
   `calc_meta_observation_scores()`內部`_calc_chips_factor()`依賴這個欄位，
   沒有會直接KeyError。
2. **洗掉手動修正的分類override**——例如「廣宇」原本被手動改成「連接器」
   (note寫「廣宇主業連接器/線材，手動移出AI伺服器」)，腳本重跑後打回「AI伺服器」；
   「奇鋐」也一樣被打回錯誤分類。

**已避開這個問題**：沒有採用腳本產出的檔案（已用`git checkout`撤銷），改用針對性
更新——只把`meta_sector='電腦周邊'`且`sub_sector`屬於新工業電腦關鍵字
(工業電腦/掌上型工業電腦/自動資料收集產品/條碼掃描器)的38列改`meta_sector`，
其餘欄位(`exchange`、手動override的note)完全不動。已驗證`exchange`欄位完整、
廣宇/奇鋐等手動override保留。

**這支腳本本身沒有修**——如果之後又有人直接重跑`build_universe.py`不做防呆，
會再次踩到同樣的坑。建議之後找時間讓這支腳本：(a) 補上exchange欄位計算邏輯，
(b) 重跑前備份既有note/手動override並在重建後套用回去，或乾脆改成「只新增
新股、不動既有分類」的incremental腳本。這次先手動繞過，沒有動腳本本身。

### 個股列表新增5/7/10/14日欄位
Cody要求近5/7/10/14日不要只藏在個股卡片(彈窗)裡，要直接顯示在族群個股列表上。
列表從3欄(股票/收盤/漲跌%)擴充成7欄，新增的4欄一樣可以點標題排序。同時補上
一個潛藏的CSS bug：`.overflow-wrap`這個class從巨量換手訊號區塊(`vt-table`)
就在用，但這個檔案本來沒有定義對應的CSS規則(`overflow-x:auto`)——這次一併補上。

### 資料來源相關（如有異動）
- data/stock_universe.csv：38檔個股meta_sector改成工業電腦，其餘欄位不動
- 上市資料（TWSE）/上櫃資料（TPEx）：無異動

### 請 Debugger 驗證
- [ ] 全部407個測試通過（已本機跑過，全綠）
- [ ] `data/stock_universe.csv` 確認exchange欄位存在、廣宇=連接器、奇鋐=散熱
      （這兩個手動override沒有被誤動）
- [ ] 個股列表顯示7欄(股票/收盤/漲跌%/5日/7日/10日/14日)，4個新欄位都能點
      標題排序
- [ ] 巨量換手訊號區塊(vt-table)如果曾經跑版，這次補的.overflow-wrap應該
      修好了，確認寬螢幕/窄螢幕都正常

### 特別注意
- **千萬不要在沒有防呆的情況下重跑`scripts/build_universe.py`**——會洗掉
  exchange欄位跟手動override，這次已經吃過一次虧（好在還沒commit就發現撤銷了）

## [2026-07-23] 個股走勢圖升級：量比欄位+爆量徽章+成交量疊圖+K棒

### 改了什麼
- 異動檔案：processors/performance.py, export/index_generator.py, tests/test_index_generator.py, tests/test_processors.py

### 邏輯說明（4個連續小改動，同一批一起交接）
1. **個股列表新增量比欄位**：Cody問「量能表現」，說明白是想知道「是否有爆大量」——
   加一欄量比，>=1.5x顯示強調色+粗體+「爆量」文字徽章，可點標題排序。
2. **量比算法澄清**：確認是跟「前10個交易日平均量」比，不是MA20（跟patterns.html
   的量比算法不同，那邊用20日均量），已修正docstring原本誤寫「5日均量」的錯誤。
3. **個股卡片走勢圖疊加成交量**：buildSparkline()新增選填volumes參數，價格bar
   下方疊一排半透明量能柱狀圖。
4. **價格走勢改用K棒(candlestick)**：新增buildCandlestick()，`calc_stock_sparklines()`
   新增opens/highs/lows/closes近11日OHLC歷史（daily_prices本來就有這些欄位，只是
   原本SQL沒撈）。個股卡片彈窗改叫buildCandlestick()取代buildSparkline()，影線畫
   最高/最低、實體畫開盤/收盤，紅漲綠跌。族群層級(沒有OHLC概念)維持用原本的
   buildSparkline()%漲跌bar，不受影響。

### 資料來源相關（如有異動）
- 上市資料（TWSE）/上櫃資料（TPEx）：無異動，OHLC本來就在daily_prices表裡，
  這次只是SQL查詢多撈這4個欄位，沒有新增資料源

### 請 Debugger 驗證
- [ ] 全部411個測試通過（已本機跑過，全綠）
- [ ] 個股列表「量比」欄位可以點標題排序，>=1.5x的股票有「爆量」徽章
- [ ] 點開個股卡片，走勢圖是K棒(蠟燭圖)不是長條圖，紅漲綠跌方向要對
- [ ] K棒下方有成交量柱狀圖疊圖，hover有日期+成交量tooltip

### 特別注意
- 這4項改動都用jsdom實際模擬過瀏覽器互動驗證(不只看程式碼)，包含：量能徽章
  正確依門檻顯示、K棒實際render出正確的影線+實體+顏色、成交量疊圖正確render

## [2026-07-23] 族群總覽頁mockup：v27補全41族群真實資料（純設計稿，非正式程式碼）

### 改了什麼
- 異動檔案：docs/superpowers/mockups/2026-07-23-index-v27-full-41-sectors.html（新增）,
  docs/superpowers/mockups/README.md
- 這是**mockup探索**，不是`export/index_generator.py`的正式改動，不影響任何production邏輯，
  Debugger不用跑測試，純粹備查/之後正式化時參考

### 邏輯說明
- 延續v26（官方色票+DESIGN.md違規修正）的樣式，v27把原本只做5檔示範的熱區格
  換成當天`docs/index.html`實際生成的全部41個族群真實排名/漲跌%/動能分級
- 熱區格欄位收斂成4個能確認為真的欄位（排名+排名變化箭頭、族群名、漲跌%、動能分級），
  拿掉v23~v26示範用的法人連買天數/量能倍數badge、週比較行——因為抓取腳本對這些欄位
  解析失敗，選擇41檔統一呈現而非部分有示範內容部分沒有

### 請 Debugger 驗證
- 不需要驗證，純mockup探索，已直接跟Cody來回確認過

### 特別注意
- ⚠️ 這條mockup探索路線跟另一個平行session（筆電）正在推進的
  `docs/superpowers/specs/2026-07-23-sector-override-layer-design.md`（族群分類校正層）
  是不同的兩件事，彼此獨立，本次會話沒有動`data/sector_overrides.csv`
- mockup README（`docs/superpowers/mockups/README.md`）內的「技術路線提醒」寫的是要接
  進舊的`html_generator.py`——這個檔案已經被`index_generator.py`取代，如果之後要把mockup
  概念正式化，要接的是`index_generator.py`，不是README寫的那個舊檔名

## [2026-07-23] v27 mockup修正：族群數量41→42+補回法人/量能badge（純mockup，非正式程式碼）

### 改了什麼
- 異動檔案：docs/superpowers/mockups/2026-07-23-index-v27-full-41-sectors.html,
  docs/superpowers/mockups/README.md
- 一樣是mockup探索，不影響production，Debugger不用驗證測試

### 邏輯說明
- Cody發現上一版v27漏抓了「功率半導體」（第一版抓取腳本regex對真實`.heat-tile`巢狀結構
  切割錯誤），實際目前是42個族群不是41個（`工業電腦`拆出後的總數）——已重寫抓取腳本用
  `data-meta-name`屬性切分，補回完整42檔
- Cody反饋「除了這些標籤 還要像是大戶買多少 外資 投信 量能等」——第一版抓取腳本因為找錯
  class名稱，抓不到真實`ht-badges`區塊（外資/投信連買天數、量能倍數），這次修正後42檔中
  22檔有真實badge資料，CSS也補上`.badge.foreign`/`.badge.vol`專屬色對齊正式版
- 「大戶」（大戶持股/籌碼集中度）目前族群層級**沒有這個資料**，已在README誠實註明是
  `chips.html`籌碼頁在探索的獨立概念（debug worktree上有一版「大戶持倉」mockup），
  沒有假造大戶數字

### 特別注意
- 同前一則，純mockup非production code，不需要驗證

## [2026-07-24] 🔴 修復K棒功能完全失效的root cause：scraper抓不到OHLC+DB匯入寫死NULL

### 背景
Cody要求v27 mockup補上個股列表的K棒/走勢/量能。查證時發現**這個功能在正式站根本沒在運作**：
`docs/index.html`點開任何一檔個股卡片，走勢圖固定顯示「走勢資料不足」，不是暫時沒資料，是
結構性壞掉——`data/screener.db`裡`daily_prices`表**全部383,583筆的open/high/low欄位都是NULL**。

### 找到2層根因
1. **`scrapers/twse.py`/`scrapers/tpex.py`（每日盤後流程）**：TWSE官方API(CSV跟JSON兩種格式)、
   TPEx官方API實際上都有回傳開盤/最高/最低價，程式碼卻只抓收盤/漲跌/成交量，完全沒抓這3欄
   （用curl實測過兩個官方API當下回應，確認欄位真的都在）。
2. **`screener/database.py::import_csv_prices()`（CSV→DuckDB匯入）**：這支是真正的root cause——
   不管CSV裡有沒有open/high/low欄位，SQL寫死`NULL::DOUBLE AS open`。連`scrapers/realtime.py`
   （`--realtime`即時流程）明明已經有在抓真實OHLC並寫進CSV（`data/daily_prices/*.csv`裡實測
   有10,310筆真的有open值），也在這一關被砍成NULL，等於白抓。

### 改了什麼
- 異動檔案：scrapers/twse.py, scrapers/tpex.py, screener/database.py,
  tests/test_twse.py, tests/test_tpex.py, tests/test_database.py
- `scrapers/twse.py`：`_parse_csv()`跟`_parse_json()`(10欄新格式+16欄舊格式，兩種都改)都補
  抓開盤/最高/最低價，回傳DataFrame新增`open`/`high`/`low`三欄
- `scrapers/tpex.py`：補抓API既有的`Open`/`High`/`Low`欄位
- `screener/database.py::import_csv_prices()`：`NULL::DOUBLE`改成`TRY_CAST(open AS DOUBLE)`
  真的讀CSV裡的值；`read_csv_auto`加`union_by_name=true`，讓「舊格式CSV完全沒有這3欄」跟
  「新格式CSV有這3欄」混在同一批glob讀取時能正確處理（缺欄位的檔案自動補NULL，不會因為
  schema不一致而出錯或把新格式也弄成NULL）

### 資料來源相關
- 上市資料（TWSE）：`_parse_csv`/`_parse_json`新增open/high/low欄位抓取，欄位來源是TWSE
  官方API本身既有的欄位，沒有新增資料源
- 上櫃資料（TPEx）：同上，`Open`/`High`/`Low`是TPEx官方API既有欄位
- 這次修改**不影響**歷史回補（FinMind/yfinance）路徑，那條路本來就沒有OHLC，這次沒動

### 請 Debugger 驗證
- [ ] 全部415個測試通過（本機已跑過全綠，含新增的10-field OHLC測試+import_csv_prices
      混合schema回歸測試）
- [ ] 下次`python main.py --reimport`後，`daily_prices`表的open/high/low欄位應該開始有真實值
      （現有383,583筆歷史資料本身沒有OHLC，這次修的是「以後」讓新資料能正確存進去，不會
      回填過去缺的部分）
- [ ] 之後個股卡片的K棒走勢圖應該能真的顯示蠟燭圖，不再固定顯示「走勢資料不足」

### 特別注意
- ⚠️ **這是找到即修的production bug，不是mockup**——candlestick功能本身（`buildCandlestick`/
  `calc_stock_sparklines`）程式碼邏輯是對的，問題出在上游資料根本沒送到，這次修的是資料
  管線最前面兩關
- 歷史累積的383,583筆daily_prices資料open/high/low永遠是NULL（TWSE/TPEx官方API不提供
  「補發歷史OHLC」），K棒圖表要等新資料進來才會慢慢有東西可畫，不會馬上滿版
- 🔴 **這批commit已經Cody明確指示提前push到origin，沒有等這裡回報✅**（正常流程是等
  Debugger驗證過才push）。程式碼已經在public repo上了，麻煩優先驗證這條，若發現問題
  用一般bug-reports.md流程回報即可，不影響已經push這件事本身。

## [2026-07-23] 族群分類校正層（sector_overrides 機制）+ 光通訊4檔

### 改了什麼
- 異動檔案：scripts/build_universe.py, scripts/__init__.py(新), tests/test_build_universe.py(新),
  data/sector_overrides.csv(新, git add -f), data/stock_universe.csv(interim 4檔)
- 邏輯說明：在 build_universe.py 自動分類「算完 rows 後、寫出前」加一層人工校正——
  讀 data/sector_overrides.csv，命中 stock_id 就覆蓋 meta/sub(皆非空才蓋)、note 標
  「手動校正:<source_note>」並清掉 ⚠️，並把已校正股從「需人工 review」爭議清單移除。
  缺輸入檔(industry_sectors.csv)時改成明確 SystemExit(提示先跑 --update-sectors)。
- 光通訊 4 檔(2455全新/3081聯亞/4991環宇-KY/6442光聖)：對照財報狗「題材=光通訊」，
  從晶圓代工/連接器改歸光通訊。interim 已直接手改 stock_universe.csv 生效；同內容
  也寫進 sector_overrides.csv 種子，重建後由機制自動接手。
- 對應 spec/plan：docs/superpowers/specs|plans/2026-07-23-sector-override-layer*

### 資料來源相關
- 只動 universe 建置階段，不碰每日 TWSE/TPEx 行情/籌碼來源，不涉歷史回補。
- 上市/上櫃無混用。exchange 欄未動(interim 保留)。

### 請 Debugger 驗證
- [x] tests/test_build_universe.py 全綠(本機 9/9 pass)
- [x] override 只動清單內股號，未列入不受影響；sub/meta 留空保留自動值；命中清 ⚠️
- [x] 光通訊 4 檔 meta=光通訊(stock_universe.csv 現況)
- [x] 缺輸入檔給明確錯誤而非裸例外

### ✅ Debugger 驗證完成（2026-07-24，見 bug-reports.md 同日 3 則）
- 初驗(master afe9538)：9/9 綠、4 項驗收全過。
- 續驗(master 733e31c，種子擴充 55 檔)：13→仍 9 綠(該版)、BOM/56 行、55 檔 override 對回
  universe **零不一致**、死股 3426/4987=0。
- 續驗(master c6f98dd，build 保留 exchange)：**13 綠**、load_existing_exchange 防禦與 6 欄序
  正確。掉欄地雷已根除。
- 結論：**全數通過，Developer 可 push origin**。（我未在 debug 這台重建，照 gated 規則，
  單元測試 + code 審查已足。）

### 特別注意（⚠️ Task 3 重建尚未執行、且目前不安全）
- **Task 3(重爬 MoneyDJ + build_universe.py 重建)是 gated、還沒跑**。跑之前有兩個坑：
  1. build_universe.py 只輸出 5 欄，**重建後必須接著跑 scripts/update_exchange.py 補回
     exchange 欄**，否則 main.py 每日流程會斷(計畫 Task 3 已補上這步)。
  2. **種子 sector_overrides.csv 目前只有光通訊 4 檔，不含既有手動 override**
     (廣宇=連接器、奇鋐=散熱、38 檔工業電腦…)。直接重建會沖掉這些。→ 重建前需先把
     所有既有手動 override 遷進 sector_overrides.csv，機制才能真正保住它們。
  → 在完成上述遷移之前，**請勿執行 build_universe.py 重建**。

## [2026-07-24] sector_overrides 種子補全(遷移既有手動 override) — Task 3 現已安全

### 改了什麼
- data/sector_overrides.csv：4 檔光通訊 → 擴充為 55 檔。
- 做法：跑 `--update-sectors` 重建 industry_sectors.csv → 用現行 config 純自動分類 →
  跟現況 stock_universe.csv 比對 meta → 差異者(規則產不出來的真手動 override)全部
  遷入 override 檔(source_note=既有手動校正遷移)。涵蓋 半導體材料矽晶圓群、電信4檔、
  工業電腦群、先進封裝設備群、記憶體(旺宏/華邦/南亞科)、廣宇/奇鋐、消費電子(東元系)等。

### 驗證(已本機做)
- 用暫存目錄跑 build+overrides，跟現況 stock_universe.csv 比對：
  **重建後 META 與現況不一致 = 0**（1037 檔全對）→ 重建可完整重現現況分類。
- 真實 stock_universe.csv 未被動(驗證走 temp)。

### ⚠️ 仍需人工確認(2 檔)
- 3426 台興(電子通路)、4987 科誠(電腦周邊)：不在最新 MoneyDJ industry_sectors，
  **重建會直接移除**(override 救不了)。可能是 MoneyDJ 分類移除或該股狀態變動。
  重建後若要保留，需在 build 後手動補回，或確認是否該下架。

### Task 3 狀態更新
- 種子已完整 → Task 3(重建)不再有「沖掉既有 override」的風險。
- 仍須遵守：重建後接著跑 `scripts/update_exchange.py` 補 exchange 欄；跑完 diff review。

## [2026-07-24] 補處理：台興(3426)/科誠(4987) 確認下市 → 已移除
- 前一則標記「需人工確認」的 2 檔，查證結果：
  - 科誠(4987)：2026-05-29 起終止上櫃(已下市)。
  - 台興(3426)：近 10+ 交易日零行情、不在 MoneyDJ industry → 已停止交易/下市。
- 兩檔近期 daily_prices 皆無資料 → 屬死股。已從 data/stock_universe.csv 移除
  (1038→1036 檔)。重建本來就不會含它們，這次讓現況與重建一致。
- override 檔不需處理這 2 檔(它們不該被保留)。

## [2026-07-24] 根除 exchange 掉欄地雷：build 重建自動保留 exchange
- 回應 Debugger 再次點名的坑：build_universe.py 重建會丟 exchange 欄。
- 改法：新增 load_existing_exchange()，build() 重建時從既有 stock_universe.csv 帶回
  每檔 exchange，並輸出 6 欄正確欄序(stock_id,stock_name,exchange,meta,sub,note)。
- 端到端驗證(真實資料，暫存build)：重建 META 差異=0、**exchange 遺失=0**；僅 3 檔
  新上市股(6236/7839/8291)exchange 留空，交給 update_exchange.py 補。
- 測試：tests/test_build_universe.py 13 綠(新增 load_existing_exchange 3 測 + build
  保留 exchange 整合測 1)。
- Task 3 更新：exchange 不再會被整欄清掉，update_exchange.py 降為「補新股」用途、
  漏跑也不再打斷每日流程。
- ✅ **Debugger 驗證通過(2026-07-24)**：13 綠、`load_existing_exchange()` 缺檔/缺欄回空 dict
  防禦正確、輸出 6 欄序正確、掉欄地雷確認根除。Developer 可 push。（詳見 bug-reports.md 同日
  「驗證(續2)」那則。）

## [2026-07-29] 族群排名歷史：排名進出榜＋歷史出現紀錄

### 改了什麼
- 異動檔案：processors/performance.py, export/index_generator.py, main.py,
  tests/test_processors.py, tests/test_index_generator.py
- 邏輯說明：新增calc_meta_rank_history()即時從daily_prices全歷史算族群週排名
  (5交易日滾動視窗一週，不存快照表，用目前族群分類回推)。族群近況新增「排名
  進出榜」子類別(這週vs上週跨過前10門檻的族群)，跟既有轉折點列表並存不合併。
  單一族群詳細面板新增「歷史出現紀錄」(近5週精確排名軌跡+文字摘要)。
  設計討論見CONTEXT.md、docs/adr/0001-*.md、docs/adr/0003-*.md，spec見
  docs/superpowers/specs/2026-07-29-sector-rank-history-design.md，實作計畫見
  docs/superpowers/plans/2026-07-29-sector-rank-history.md。
- 這是走過完整grill-with-docs討論→spec→writing-plans→TDD實作的功能，8個task
  逐一TDD完成(每個新函式都先寫失敗測試、確認失敗、再實作、確認通過、才commit)，
  另外用jsdom實際模擬點擊驗證過HTML/JS的render行為(不只看程式碼)，確認：
  頁面層級排名進出榜區塊正確渲染、點開族群面板「歷史出現紀錄」正確顯示連續
  進榜週數/上次進榜週次與名次/5格排名軌跡的in-top10樣式。

### 資料來源相關（如有異動）
- 上市/上櫃資料：無異動，純粹是daily_prices既有change_pct欄位的新用法(即時算
  週排名)，沒有新增資料源或改變抓取邏輯。

### 請 Debugger 驗證
- [ ] 全部428個測試通過(pytest -q全綠，本機已跑過)
- [ ] 族群近況區塊新增「排名進出榜」，位置在轉折點列表下面，左右兩欄剛進榜/
      剛掉出榜
- [ ] 點進任一族群詳細面板，走勢圖/籌碼摘要之後有「歷史出現紀錄」，顯示5格
      排名軌跡+一句文字摘要
- [ ] 沒有進前10的族群面板要顯示「上次進榜是W-x第Y名」或「近N週都沒有進前10」
- [ ] 族群分類異動(例如工業電腦)的歷史排名要能正確反映目前分類，不是卡在舊分類

### 特別注意
- 這個功能完全是即時計算，不需要等待資料庫累積新資料——上線當天就有完整5週
  歷史可看(資料庫回溯到2025-01-02，遠超過5週所需天數)
- 這批commit尚未push到origin，等Cody指示

## [2026-07-29] 個股列表新增融資/融券佔比與維持率(估)

### 改了什麼
- 異動檔案：screener/database.py, processors/performance.py, export/index_generator.py,
  main.py, tests/test_database.py, tests/test_processors.py, tests/test_index_generator.py
- 邏輯說明：新增get_latest_total_shares()(集保已發行股數，per-stock fallback)+
  calc_avg20_close()(20日均收盤價)兩支資料函式，接進build_stock_detail_data()算出
  四個新欄位：融資佔比、融資維持率(估)(現價/20日均價/融資成數*100%，<130%警示)、
  融券餘額佔比、融券維持率(估)(20日均價/現價/融資成數*100%，方向跟融資相反，
  同樣<130%警示)。個股列表新增這四欄可排序，緊接在量比後面，多空方各自分組相鄰。
  設計討論見CONTEXT.md、docs/adr/0002-margin-maintenance-ratio-is-an-estimate.md，
  spec見docs/superpowers/specs/2026-07-29-stock-margin-metrics-design.md，實作計畫見
  docs/superpowers/plans/2026-07-29-stock-margin-metrics.md。
- 6個task用subagent-driven-development逐一執行，每個task獨立TDD(先寫失敗測試、
  確認失敗、再實作、確認通過、才commit)。過程中subagent自己抓到並修正2個小問題：
  一次是插入位置意外把前一個函式的return statement吃掉(靠全套測試發現)、一次是
  測試程式碼漏了一個既有慣例的import(跟同檔案其他測試風格對齊後補上)。

### 資料來源相關（如有異動）
- 融資佔比/融券餘額佔比：來源是集保股權分散表(shareholder表total_shares)，每週更新，
  比其他每日欄位新鮮度較低，個股列表上方會顯示「集保資料：YYYY-MM-DD」實際日期。
- 融資維持率(估)/融券維持率(估)：兩者都是估算值，不是真實維持率(真實維持率是帳戶
  層級資料，交易所不公布)，用20日均價當成本基準是業界慣例做法。
- 上市/上櫃資料：無異動，都是既有daily_prices/margin/shareholder表的新用法。

### 請 Debugger 驗證
- [ ] 全部測試通過(pytest -q全綠，本機已跑過，438個)
- [ ] 點進任一族群的個股列表，新增4欄：融資佔比/融資維持率(估)/融券餘額佔比/
      融券維持率(估)，位置在量比後面
- [ ] 四欄都可以點欄名排序
- [ ] 融資維持率(估)/融券維持率(估)低於130%時要有警示色+「追繳risk」徽章
- [ ] 個股列表上方要有「集保資料：YYYY-MM-DD」的日期提示
- [ ] 融資餘額=0的股票，融資佔比/融資維持率(估)兩欄顯示「─」；融券餘額=0時，
      融券餘額佔比/融券維持率(估)兩欄顯示「─」——兩組各自獨立判斷

### 特別注意
- 這兩個維持率都是**估算值**，不是真實維持率——UI上「(估)」是刻意標註，不能被誤會
  成精確數字
- 融資成數固定用交易所預設值(上市6成/上櫃5成)，沒有處理注意股/處置股等可能有不同
  融資成數的例外情況(見spec Out of Scope)
- 這批commit尚未push到origin，等Cody指示
- ⚠️ 目前master領先origin 19個commit、落後19個commit(分岔)——是另一台機器的
  main.py自動commit累積出來的，不是這次改動造成的。push前需要先git pull --rebase
  處理，照CLAUDE.md的防分岔鐵律，不要force push

## [2026-07-30] 大戶持倉本週焦點：拿掉長條圖

### 改了什麼
- 異動檔案：export/chips_headline.py, export/chips_generator.py
- 邏輯說明：籌碼頁(docs/chips.html)首頁「今日焦點」的「大戶持倉本週焦點」子區塊，
  拿掉發散長條圖(.hm-divbar)，改成股票名稱｜週變化%pill｜目前水位% 純文字一行式。
  Cody反饋長條圖沒有比旁邊數字多傳達資訊，是視覺雜訊。排序邏輯（依|週變化%|絕對值
  排序前5，不分方向）完全沒動。
- spec: docs/superpowers/specs/2026-07-30-holder-focus-remove-bar-chart-design.md
- plan: docs/superpowers/plans/2026-07-30-holder-focus-remove-bar-chart.md

### 資料來源相關（如有異動）
- 無資料來源異動，純呈現層調整（HTML/CSS）

### 請 Debugger 驗證
- [ ] 全部測試通過(pytest -q全綠，本機已跑過，479個)
- [ ] 「大戶持倉本週焦點」區塊視覺上正確顯示3欄（名稱/週變化%pill/目前水位%），沒有長條
- [ ] 週變化%的紅漲綠跌pill樣式跟頁面其他地方(連買/連賣天數)視覺一致
- [ ] 沒有影響「候選觀察」卡片（同一個headline zone的另一半，這次沒有動）
- [ ] 沒有影響完整「大戶籌碼」分頁（Section8，本來就沒有長條圖）

### 特別注意
- debug worktree的 docs/superpowers/mockups/2026-07-23-chips-v3-final.html 裡有一段
  解釋「為什麼改用發散長條」的註解，前提現在已經不成立，是歷史紀錄不用改，但對照時
  別誤以為現行程式碼還在用發散長條

## [2026-07-30] 統一四頁導覽列位置到右上角

### 改了什麼
- 異動檔案：export/chips_generator.py, export/patterns_generator.py
- 邏輯說明：Cody反饋族群/籌碼/型態/策略四頁的導覽列(nav-links)位置不一致——
  index.html跟momentum.html是靠右上，chips.html跟patterns.html是靠左上(緊接標題旁)。
  確認統一成右上(跟index.html/momentum.html一致，多數頁面已是這樣，改動量較小)。
  - chips.html：把`<nav class="nav-links">`移到`<div class="data-status">`後面
    (跟著data-status的`margin-left:auto`一起被推到右邊)，CSS沒改，手機版768px以下
    本來就用`order:3`明確排序，不受這次HTML順序調整影響。
  - patterns.html：本來連`<header>`都沒有，只是純block排版的標題div+獨立的nav-links
    div。新增`.page-head{display:flex;align-items:baseline;gap:16px;flex-wrap:wrap}`
    包住標題+nav，並把`.nav-links`的`margin:8px 0 0`改成`margin-left:auto`讓它被推到
    右側，跟其他三頁視覺一致。
  - index.html/momentum.html本來就是右上，沒有改動。

### 資料來源相關（如有異動）
- 無資料來源異動，純呈現層調整（HTML結構+CSS）

### 請 Debugger 驗證
- [ ] 全部測試通過(pytest -q全綠，本機已跑過，479個，這次改動沒有新增/刪除測試，
      因為現有測試都不斷言header/nav的HTML結構)
- [ ] 四個頁面(index/chips/patterns/momentum)桌面版導覽列都在右上角，视覺一致
- [ ] chips.html手機版(<=760px)導覽列還是維持原本的完整寬度、排在最下面那一行
      的響應式行為，沒有被這次HTML順序調整影響
- [ ] patterns.html新增的.page-head flex容器沒有把標題或日期的樣式弄亂

### 特別注意
- 這批commit尚未push到origin，等Cody指示

## [2026-08-04] 排名進出榜加上絕對報酬閘門（修誤導性呈現，非資料錯誤）

### 背景
Cody要求review籌碼頁資料，過程中連帶發現index.html「排名進出榜」有個呈現問題：
「散熱」上週排名#24（跌9.6%）、本週排名#1（但自身仍跌1.21%，只是跌最少），被列進
「剛進榜」。數字驗證過是對的（複刻calc_meta_rank_history()邏輯手動重算，結果一致），
但這種全市場走弱時「跌最少」被標成「剛進榜」的呈現方式會誤導人（看起來像在噴，其實
只是相對沒那麼差）。經過幾輪確認：不是資料錯誤，是這個訊號的定義需要調整。

### 改了什麼
- 異動檔案：processors/performance.py, export/index_generator.py
- spec: docs/superpowers/specs/2026-08-03-rank-crossing-absolute-return-gate-design.md
- ADR: docs/adr/0004-rank-crossing-gets-absolute-return-gate.md
- 邏輯說明：
  1. `calc_meta_rank_history()` 新增 `weekly_returns` 欄位（跟 `weekly_ranks` 平行對齊，
     回傳排名依據的原始5日複利報酬%本身，先前排完名這個數值就被丟棄）
  2. `find_rank_crossings()` 加上絕對報酬閘門：剛進榜除了原本「跨過前10名門檻」，還需要
     本週自身5日複利報酬 > 0%；剛掉出榜則需要 < 0%。閘門值固定0%，不通過閘門的跨榜
     從清單消失（不算誤判、也不另外歸類）
  3. 排名進出榜的說明小字文案跟著更新，反映新定義（原本寫「不是自身動能」，現在文案改
     成「且自身報酬方向一致」）

### 資料來源相關（如有異動）
- 無資料來源異動，純計算邏輯調整（不動 daily_prices 讀取方式、不動5日滾動窗口定義本身）

### 請 Debugger 驗證
- [ ] 全部測試通過(pytest -q全綠，本機已跑過，482個)
- [ ] index.html「排名進出榜」實際跑出來的清單，每一筆「剛進榜」自身5日報酬都應該是正的，
      每一筆「剛掉出榜」都應該是負的（可以挑幾筆對照calc_meta_rank_history()重算驗證）
- [ ] 單一族群點進去看的「歷史出現紀錄」不受影響（那邊的in_top10_this_week/
      consecutive_weeks_in_top10維持純排名判定，沒有加絕對報酬閘門——這是刻意的，Cody
      這次的反饋只針對排名進出榜這個子區塊）
- [ ] 全市場單邊大漲或大跌的日子，排名進出榜有可能兩個清單都是空的（閘門生效），這是
      預期行為，不是bug（見ADR-0004「代價」段落）

### 特別注意
- 這是繼「族群排名歷史」功能上線後的第一次真實資料review發現的定義問題，過程中還討論到
  「5個交易日≠自然週」這個更大的架構問題（熱區格cum5/roll5全站共用同一套滾動交易日慣例），
  Cody確認這次先不動週定義，只做絕對報酬閘門這個範圍較小的修正——自然週的討論留待之後
  另開一輪，不要誤以為這次順便處理掉了
- 這批commit尚未push到origin，等Cody指示
- 這批commit尚未push到origin，等Cody指示

---

## [2026-08-25] 環境交接：桌電要補跑的 plugin/skill 設定（在筆電做的，git 帶不過去）

### 改了什麼
- 異動檔案：`CLAUDE-developer.md`（commit `409a4e3`）
- 邏輯說明：設計原則的 brainstorming 規則，從 `mattpocock-skills:grill-with-docs`
  改成直接點名 `mattpocock-skills:grilling` ＋ `mattpocock-skills:domain-modeling`。
  原因：`grill-with-docs` 標了 `disable-model-invocation`，只能人手動打 slash command，
  規則寫它等於流程永遠要 Cody 先下指令；它本體只有一行「呼叫 grilling 和 domain-modeling」，
  而這兩個都沒鎖 → 拆開點名，行為完全一樣但 Claude 可以自動觸發。
- 本機（筆電）另外做了 plugin 增減，見下方⚠️。

### ⚠️ 桌電必須手動補跑（git 同步不到）
今天的改動有三項，只有一項會跟著 git 走：

| 改動 | 存在哪 | git 帶得過去嗎 |
|---|---|---|
| 裝 `mattpocock-skills` v1.2.3（user scope） | `~/.claude/settings.json` + `~/.claude/plugins/` | ❌ |
| 移除 `superpowers`（project scope） | 專案 `.claude/settings.json` | ❌ 該檔沒進 git（`git ls-files .claude/` 為空） |
| `CLAUDE-developer.md` 規則 | git tracked | ✅ |

→ **桌電 pull 之後，會拿到一條叫它用 `mattpocock-skills:grilling` 的規則，但那台上面沒有這個 skill。**
桌電請依序跑：

```bash
git pull --rebase
claude plugin marketplace add mattpocock/skills          # 若尚未加過
claude plugin install mattpocock-skills@mattpocock --scope user
claude plugin uninstall superpowers@superpowers-marketplace --scope project
claude plugin marketplace add nextlevelbuilder/ui-ux-pro-max-skill
claude plugin install ui-ux-pro-max@ui-ux-pro-max-skill --scope user
cp CLAUDE-developer.md CLAUDE.md                          # ← 最容易漏的一步
```

### 追記：`ui-ux-pro-max` 找回來了（2026-08-25 稍晚）
- 盤點時發現 `CLAUDE.md:107` 指定的 `ui-ux-pro-max` skill **本機根本不存在**，
  三個已註冊的 marketplace 也都沒有 → 跟 `superpowers:brainstorming` 同一種病：
  規則指向不存在的 skill，等於整條是空的。而它在 `debug-tasks.md`、
  `docs/superpowers/plans/`、`specs/` 裡被引用多處（「這段留到下一階段用
  ui-ux-pro-max 設計」），影響範圍不小。
- 查到出處是 `nextlevelbuilder/ui-ux-pro-max-skill`（GitHub 120,680 stars /
  12,950 forks，MIT，2026-08-24 仍在更新），已裝 v2.13.0（user scope）。
- **文件不用改**：規則本來就寫 `ui-ux-pro-max`，裝回來之後所有既有引用自動生效。
- 內容檢查：23MB，含 92 個 .py / 14 個 .cjs 腳本（風格/配色/字體 CSV 資料庫的查詢工具）。
  **無 hooks、不會自動執行**，腳本只在 skill 主動呼叫時才跑。唯二會連網的是
  `design-system/scripts/fetch-background.py`（抓 Pexels 簡報背景圖，URL 寫死）與
  `brand/scripts/sync-brand-to-tokens.cjs`（`execFileSync` 呼叫同包本地腳本）。
- ⚠️ **名稱衝突**：這個 plugin 另外夾帶 7 支 skill，其中一支叫 `design`，
  跟 Claude Code 內建的 `design`（畫布式設計）同名。要用哪個要講清楚。

### 順帶修掉的舊缺口
- `bf93ab0`（2026-07-23，桌電做的）把規則改成 `grill-with-docs` 並 push，
  筆電雖然 pull 到了 `CLAUDE-developer.md`，但**沒人補跑 `cp`** →
  筆電的 `CLAUDE.md` 停在 `superpowers:brainstorming` 停了一個多月才被發現。
  這次已 `cp` 補上。**教訓：每次 pull 到 `CLAUDE-*.md` 的改動，該台就要重跑一次 `cp`。**

### 資料來源相關（如有異動）
- 無。純環境/文件設定，沒碰 scrapers/processors/screener，TWSE(上市)/TPEx(上櫃) 流程完全未動。

### 請 Debugger 驗證
- [ ] `CLAUDE.md` 與 `CLAUDE-developer.md` 內容一致（`diff` 應為空）——**兩台各自確認**
- [ ] 桌電上 `superpowers` 已移除、`mattpocock-skills` 已安裝
- [ ] `docs/superpowers/specs/` 與 `plans/` 兩個資料夾**沒有被動到**
      （那是專案自己的設計文件，只是剛好同名，跟被移除的 plugin 無關）

### 特別注意
- `domain-modeling` 不只問問題，會主動維護 `CONTEXT.md` 和 ADR。本 repo 目前沒有
  `CONTEXT.md`，第一次觸發時它可能提議新建，屆時由 Cody 決定要不要。
- **debug worktree 尚未同步**：`../tw-sector-tracker-debug` 有未 commit 的 untracked 檔
  `options-bearish-hedging.md`，依規則先問 Cody、未擅自 merge。
  另發現該 worktree 的 `origin/debug` 已是 `[gone]`（遠端分支被刪、追蹤關係斷了），
  下次 Debugger 要 push 會出事，建議一併處理。
- 這批 commit 已 push 到 `origin/master`（2026-08-25，Cody 指示）。桌電直接 `git pull --rebase` 即可拿到。

---

## [2026-08-25] 新增 dip_buy/stealth_buy 籌碼回測規則（籌碼頁重構前置調查）

### 背景
Cody 想討論籌碼頁重構，範圍/程度都還沒定案。討論中發現 `screener/backtest.py` 的
`CHIPS_RULES` 只覆蓋 chips.html 9 個 tab 裡的 5 個（法人同步觀察/外資籌碼/投信籌碼/
融資警示/大戶籌碼），另外 3 個 tab（越跌越買/外資偷偷買/董監持股）從未被回測驗證過
訊號有沒有 edge。這次先補上「越跌越買」「外資偷偷買」兩個，湊齊全貌後再跟 Cody
一起決定重構方向（用「訊號有沒有用」當資訊架構優先順序的依據，不是純美感重排）。
「董監持股」查過資料量後判斷暫時無法回測（見下方特別注意）。

### 改了什麼
- 異動檔案：`screener/backtest.py`、`tests/test_backtest.py`
- 邏輯說明：
  1. `scan_chips_rule()` 新增 `dip_buy`/`stealth_buy` 分支，`CHIPS_RULES`/
     `CHIPS_RULE_CONFIG` 對應加入這兩條規則
  2. chips.html 原版「越跌越買」「外資偷偷買」門檻是**族群層級**（族群5日累計報酬 +
     族群層級外資/投信連買，見 `export/chips_generator.py::_build_section35`/
     `_build_section_stealth`）。回測需要買到具體個股才有價格可查後續報酬，沒有可交易的
     「族群」標的，這裡改用**個股自己的** `price_cum_pct`（`scan_institutional(...,
     price_window=5)`，5日累計漲跌）+ **個股自己的** `foreign_streak`/`trust_streak`
     做近似——語意略窄於原版族群訊號，但方向一致，足以驗證「跌時法人還連買」「盤整時
     外資偷偷買」這兩個假設本身有沒有 edge
  3. `dip_buy`：`(foreign_streak>0 或 trust_streak>0) 且 price_cum_pct<=-1.0`，跌最多排前面
  4. `stealth_buy`：`foreign_streak>0 且 -1.0<=price_cum_pct<=1.0`，連買天數排前面

### 資料來源相關（如有異動）
- 無新資料源，沿用既有 `institutional`/`daily_prices` 表，跟既有 `foreign_continuation`/
  `trust_continuation` 規則共用同一批資料，只是換了篩選條件

### 已跑過的驗證
- **本機已用 `python main.py --backtest-chips dip_buy` / `stealth_buy` 各跑過一次**，
  兩個都能正常產出回測摘要（無例外、格式跟其他規則一致），這次是我（Developer）直接跑的
  ——因為這是純讀取 `data/screener.db` 算統計、不抓即時資料、不寫入、不觸發 commit/push
  的分析指令，跟每日更新流程性質不同，Cody 這次也有在對話中明確要我直接跑並回報數字，
  不是我自己判斷的例外
- **新增的兩個 unit test（`test_dip_buy_rule_...`/`test_stealth_buy_rule_...`）我沒有自己
  跑 pytest**，照規矩留給 Debugger

### 請 Debugger 驗證
- [ ] `pytest tests/test_backtest.py -q` 全綠，尤其兩個新測試
      `test_dip_buy_rule_requires_streak_and_five_day_drop`/
      `test_stealth_buy_rule_requires_foreign_streak_and_flat_price`
- [ ] 全專案 `pytest -q` 沒有因為 `CHIPS_RULES` tuple 新增兩個成員而連帶壞掉其他測試
      （例如任何寫死 `len(CHIPS_RULES)` 或逐一枚舉規則名稱的地方）
- [ ] `scan_chips_rule()` 新分支的資料可用性 guard（`_table_date_range`/`_table_dates`
      對 `institutional` 表）邏輯跟既有 `joint_buy`/`foreign_continuation` 分支一致，
      沒有漏掉「法人資料尚未發布時 fallback 到前一天，可能重複計數同一批資料」這個既有雷區
      （既有分支用 `if not any(r.get("date") == date_str for r in rows): return []` 擋掉，
      新分支照抄了同一段，確認邏輯抄對）

### 特別注意
- `dip_buy`/`stealth_buy` 只是**回測用的近似版**，跟 chips.html 上線頁面實際顯示的族群
  層級「越跌越買」「外資偷偷買」表格是兩套不同的計算（頁面本身沒有動），這次沒有改頁面
  顯示邏輯，純粹是新增獨立的回測驗證路徑
- 「董監持股」(`insider_holdings` 表) 查過 `report_date` 只有 3 筆相異值
  （2026-05-01/06-01/07-01，月頻），樣本量太小（不到 3 個月變化量可用），這次**沒有**
  幫它補回測規則——跟 Cody 討論後的判斷是資料累積不夠前硬做回測會產出不可信的假結論，
  比沒有回測更糟，等資料再累積幾個月後再議
- 這批 commit（`92389fb`）尚未 push 到 origin，等 Cody 指示（且等 Debugger 跑完 pytest
  回報 ✅）

## [2026-08-25] 首頁（index.html）版面/視覺重設 — 13個Task全部完成

### 改了什麼
- 異動檔案：export/index_generator.py, processors/performance.py, main.py,
  tests/test_index_generator.py, tests/test_processors.py
- 邏輯說明：
  1. 版面重排：熱區格滿版置頂當主角；異動族群(已排序)+族群近況併成二欄次要區
  2. 異動族群加排序(burst優先,同kind比abs(pct))
  3. 視覺：超強tier熱區格加玻璃光暈(color-mix跟著--accent走,雙主題自動適配)，
     個股明細面板邊框改accent色
  4. 個股明細面板改錨定#heatgrid容器之後，不再插進tile網格中間打斷排列
  5. 面板內走勢/籌碼動向/歷史進榜三區改並排三欄(detail-three-col)
  6. 補齊4項已算好但沒接進面板的資料：自營商(dealer_net_today)、
     每週報酬%(weekly_returns)、大戶佔比+週變化(個股表格11→13欄)、
     外資/投信本週累計買賣超(近5交易日加總)

### 資料來源相關（如有異動）
- 上市資料（TWSE）：無異動，institutional/margin/shareholder表既有資料，未新增爬蟲
- 上櫃資料（TPEx）：同上，calc_meta_chips_signals()的per-stock/per-meta fallback邏輯未變動

### 驗證紀錄（Developer 自行執行）
- `python -m pytest -q`：**501 passed, 1 warning**（0 failure）。baseline 482 + 本計畫
  12個task新增測試 + `dip_buy`/`stealth_buy` 這個不相關功能自己的新測試，合計 +19。
  唯一的 warning 是 `test_calc_market_breadth_ignores_nan_change_pct` 既有的
  pandas `FutureWarning`（concat all-NA columns），跟本次改動無關，非新增。
- 手動 smoke test（`generate()` 端到端跑一次，比單一 unit test 更豐富的 fixture）：
  成功寫出 60980 bytes 的 HTML，無 traceback。

### 請 Debugger 驗證
- [ ] 主要功能邏輯正確（尤其：dealer_net的SELECT修改是否影響production的institutional表查詢；
      shareholder_df在main.py是否正確接線，實際跑一次main.py確認docs/index.html有大戶佔比/週變化欄）
- [ ] 上市/上櫃資料來源沒有混用
- [ ] 沒有影響其他模組（chips.html/momentum.html/patterns.html的nav互連、既有功能）
- [ ] 瀏覽器實測（這台debug worktree可能沒有瀏覽器工具，若無工具請如實回報跳過）：
  - 熱區格41格排列完整、點擊展開的個股明細面板出現在熱區格下方(不再插進tile中間)
  - 三欄並排(走勢/籌碼動向/歷史進榜)版面正確、窄螢幕會改回垂直堆疊
  - 異動族群卡片排序正確(爆量暴衝排前面)
  - 深色/淺色主題切換，超強tier熱區格光暈兩個主題都合理(不是只深色能看)
  - **順便補測 2026-07-23 遺留的兩項舊欠款**：Tab focus + Enter/Space 鍵盤展開熱區格tile；
    手機版窄螢幕的secondary-row/三欄排版responsive行為

### 特別注意
- `docs/index.html` 是 generated artifact，不要手動編輯——下次 `python main.py` 跑過會被
  `export/index_generator.py` 重新產生的版本覆蓋。這次的所有改動都在 `export/index_generator.py`。
- `tests/test_processors.py::_seed_chips_db()` 的 institutional mock schema多加了 dealer_net
  欄位(預設0)，是backward-compatible的改動，所有既有呼叫端不用改。
- main.py 新增了第二次 `get_shareholder_top()` 呼叫(index.html用)，跟chips.html既有那次呼叫
  各自獨立，這是刻意的取捨，不是遺漏。
- 這批 commit 尚未 push 到 origin，等 Cody 指示（且等 Debugger 跑完驗證回報 ✅）。

---

## [2026-08-25] 籌碼頁證據分級改版實作（4個Task，Subagent-Driven Development執行完成）

### 背景
接續同日稍早的「dip_buy/stealth_buy籌碼回測規則」跟「證據分級spec/mockup」，這次是實際動
`chips_generator.py`把9個tab依回測證據強度重新設計。全程用`superpowers:subagent-driven-development`
skill執行：4個Task各自獨立implementer+task reviewer（1個Task修復1輪、其餘3個Task零修復一次過），
最後跑了最高階模型的全分支review，抓到2個Important+多個Minor（見下），已修復並過scoped re-review，
全部確認clean。

### 改了什麼
- 異動檔案：`export/chips_generator.py`（CSS/tab nav/hero移除/證據卡+banner）、
  `tests/test_chips_generator.py`（新增/更新測試）、`export/chips_headline.py`（僅加1行狀態註解，
  邏輯不變）
- 邏輯說明：
  1. CSS新增4級證據徽章(`.evid-verified`/`.evid-observe`/`.evid-unproven`/`.evid-weak`)+證據卡
     (`.evid-card`)+2種banner(`.caution-banner`/`.weak-banner`)，全部沿用既有CSS變數，沒有新增色相
  2. 9個tab按鈕加證據徽章、組內依證據強度重排（分組結構不變：法人動向/特殊型態/持股結構，只是
     特殊型態組移到最前面，因為它含唯一的🟢已驗證項目），`_tabs` JS陣列跟預設分頁(從法人同步觀察
     改成融資警示)同步更新
  3. 拿掉「候選觀察」開頁hero（joint_buy/tdcc_accumulation回測皆無edge，不該再佔全頁最顯眼位置）
     ——`chips_headline.py`模組本身沒刪，只是`generate()`不再呼叫，保留可能的重用
  4. 9個tab面板頂部各加一張證據卡/banner，數字/文案抄自
     `docs/superpowers/specs/2026-08-25-chips-page-signal-audit-design.md`回測總表（靜態文案，
     不是即時計算）

### 資料來源相關（如有異動）
- 無資料來源異動，純樣板/資訊架構調整，不動`screener/`/`processors/`/`scrapers/`任何計算邏輯

### 請 Debugger 驗證
- [ ] 全部測試通過（本機Subagent已跑過pytest -q：507 passed，含2個新增/更新測試檔）
- [ ] 實際產生一次`docs/chips.html`（或直接看瀏覽器），確認：
  - 9個tab按鈕徽章顯示正確、組內順序符合證據強度（特殊型態組：融資警示→外資偷偷買→越跌越買）
  - 預設進頁看到的是「融資警示」tab，不是「法人同步觀察」
  - 開頁不再有「候選觀察」大卡片區塊
  - 每個tab面板頂部證據卡/banner數字讀起來合理、跟該tab的nav徽章等級一致
- [ ] Global-branch review有2個Minor留著沒修（刻意決定，不是遺漏）：badge文字「融資警示已驗證」
  這種label+等級文字中間沒有分隔符號（中文語境下影響小，已裁定不修）；tab按鈕文字沒有超長截斷
  防護（目前沒有任何label會超長，已裁定不修）——如果之後真的改了某個tab名稱變超長，記得補上
  `min-width:0;overflow:hidden;text-overflow:ellipsis`

### 特別注意
- **這批 commit 尚未 push 到 origin**，等 Cody 指示（且等 Debugger 跑完驗證回報 ✅）
- **debug worktree 同步這次卡住了**：`git merge master`在`export/chips_generator.py`跟
  `tests/test_chips_generator.py`撞到**真的**衝突（不是平常append型檔那種），我已經
  `git merge --abort`安全退出、沒有硬解，debug worktree目前狀態沒變（乾淨可回溯，只是
  master的這批commit還沒同步過去）。懷疑是debug worktree這邊也有session在跑
  `python main.py`（看到一筆`7ba5168 update: sector performance 2026-08-25`是Cody帳號在今天
  22:17產生的，同時`bug-reports.md`目前也有未commit的異動）——建議先確認debug端沒有其他
  session在動，再手動處理這次的merge conflict，我這邊沒有硬蓋過去。

---

## [2026-08-28] 公開 repo 機敏資訊稽核：內部文件不再上 Pages + 移除寫死本機路徑

### 改了什麼
- 異動檔案：`.github/workflows/pages.yml`, `start-desktop.bat`, `start-laptop.bat`,
  `end-work.bat`, `bug-reports.md`；刪除 `scheduler_setup.bat`
- 邏輯說明：
  1. **Pages 只發布 dashboard**：原本 `upload-pages-artifact` 的 `path: 'docs'` 把整個
     `docs/` 上線，代表 `docs/superpowers/`（81 個 specs/plans/mockups）、`docs/adr/`、
     `CONTEXT.md`/`DESIGN.md`/`backtest.md`/`factor.md`/`scheduler.md` 這些內部開發文件
     都能從 `coody0111.github.io/tw-sector-tracker/...` 直接讀到、被搜尋引擎索引。
     改成新增一個 `Prepare public site` step，只把 `docs/*.html`（4 個 dashboard）+
     `docs/.nojekyll` 複製到 `_site`，`path` 改指 `_site`。
     已確認 4 個 html 完全自包含（互相連結之外沒有引用任何本地資源、沒有 fetch 外部檔），
     所以不會少檔。
  2. **觸發條件加上 workflow 自身**：`paths` 補 `.github/workflows/pages.yml`，
     這樣 push 後會立刻重新發布、把已上線的舊內容（含內部文件）換掉，
     不用等下一次 `main.py` 更新 `docs/*.html`。
  3. **.bat 去識別化**：三支 bat 原本寫死 `C:\Users\Cody\...` / `C:\Users\codyliu\...`，
     public repo 等於公開兩台機器的 Windows 帳號名。改用 `%~dp0` 取 bat 自身所在目錄；
     `start` 開出的視窗改為繼承工作目錄（不再在 `cmd /k "..."` 內巢狀引號），
     Debugger 視窗用相對路徑 `cd /d ..\tw-sector-tracker-debug`。
     兩支 start bat 現在內容一致（只差標題文字），桌電/筆電共用同一份邏輯。
  4. 刪 `scheduler_setup.bat`（寫死桌電路徑的舊排程腳本，已被
     `scripts/install_scheduler.ps1` 取代）。
  5. `bug-reports.md` 3 處（L796 / L989 / L2522）本機絕對路徑 → `<專案根目錄>`。

### 資料來源相關（如有異動）
- **無資料來源異動**。完全沒動 `scrapers/`、`processors/`、`screener/`、`export/`、
  `main.py`、`config.py`，上市（TWSE）／上櫃（TPEx）流程與回補流程都不受影響。

### 金鑰稽核結果（本次順帶做，無異動）
掃了三個範圍，**沒有發現任何外露的 API key / token**：
- `origin/master` 全部 183 個檔（`git grep`）
- **全部 git 歷史的所有 blob**（`git rev-list --all --objects` → `cat-file --batch`）
- 檢查格式：Telegram bot token（`\d+:AA...`）、GitHub PAT（`ghp_`/`github_pat_`/`gho_`）、
  `sk-ant-`/`sk-`、Google `AIza`、AWS `AKIA`、Slack `xox*`、JWT（`eyJ*.eyJ*`）、
  `-----BEGIN * PRIVATE KEY`；另外掃賦值型硬編（`token = "..."` 等）
- 唯一命中是 `tests/test_telegram_notifier.py:43` 的假值 `token="bot-token-abc"` ✅
- `.env` **從未被 commit 過**（歷史上 `--diff-filter=A` 只有 `.env.example`），`.gitignore` 有擋
- `notifications/telegram.py` 寫法正確：token 只從 `os.environ` 讀、缺少時拋
  `TelegramConfigError` 安全失敗、log 只印 HTTP status 與 `type(exc).__name__`，
  不印含 token 的 URL、也不印 API 回應內文

### 請 Debugger 驗證
- [ ] `pages.yml` 語法正確、`Prepare public site` step 的 `cp` 不會漏檔（4 個 html + `.nojekyll`）
- [ ] push 後確認 Pages 部署成功，且 `<site>/superpowers/...`、`<site>/CONTEXT.md` 等
      內部文件路徑回 404（dashboard 四頁與頁間連結仍正常）
- [ ] 三支 `.bat` 實際跑一次（桌電/筆電各一）：`%~dp0` 有正確切到專案、
      Developer/Debugger 兩個視窗都能開起來並 copy 對應角色檔
- [ ] 沒有影響其他模組（本次未動任何 Python 邏輯，`pytest` 應與上一批結果相同）

### 特別注意
- **這筆 commit（`52b5666`）尚未 push**，等 Cody 指示。
  ⚠️ 但這次改動要 **push 之後才會生效** —— 在 push 前，內部文件仍在 Pages 上公開可讀。
- **上一批的 debug worktree merge 衝突還沒解**（見上一則交接）。這次的改動一樣還沒同步到
  debug worktree，要等那邊的衝突處理完再一起 merge，我沒有硬蓋。
- 使用者選定的處理範圍是「**只擋 Pages、repo 維持 public**」：內部文件仍留在 repo 內
  （clone 或在 GitHub 上點進去仍看得到），只是不再從 Pages 網址直接對外曝光。
  若之後要更徹底（從追蹤中移除或轉 private repo），是另一件事。

---

## [2026-08-28] 修復「近N日漲跌幅失真」+ backfill 匯入炸掉/丟失OHLC

### 起因
Cody 肉眼發現金居 8358「5日漲 100 多%」不合理。核實後不是計算公式錯，是資料缺交易日，
且牽出另外兩個相扣的問題（其中一個當場把 `daily_prices` 打成 0 筆）。

### 改了什麼
- 異動檔案：`screener/data_integrity.py`（新）、`screener/database.py`、
  `scrapers/backfill.py`、`main.py`、`tests/test_data_integrity.py`（新）、
  `tests/test_database.py`、`tests/test_backfill.py`
- 邏輯說明：

**① 近N日窗口跨越資料斷層（主 bug）**
`get_rolling_returns()` 等處的 `ORDER BY date DESC LIMIT N` 數的是「daily_prices 裡實際
存在的資料列」不是真實交易日。DB 缺 8/07~8/24 共 15 個交易日時，「5交易日前」跨到 7/30，
8358 顯示 +100.37%（實為 7/30→8/28 近一個月）。當時全市場 **1040 檔有 1035 檔（99.5%）**
窗口被拉長，中位數跨 29 個日曆天，「5日>30%」有 219 檔。
→ 新增 `screener/data_integrity.py`：不需外部交易日曆，用「窗口實際跨了幾個日曆天」判斷
（`max_span_days(N) = N + ceil(N/5)*2 + 9`）。`get_rolling_returns()` 接上後，跨度異常的
窗口回 `None`（頁面顯示「—」）並記一筆 warning 統計；`main.py` 步驟 6.5 加行情連續性體檢，
有斷層時寫 log 並塞進 `_run_warnings`（→ 進 summary → Telegram）。

**② `import_csv_prices()` 在所有 CSV 都缺某欄時直接炸（破壞力最大）**
`TRY_CAST(open AS DOUBLE) AS open` 在來源表沒有 `open` 欄位時，DuckDB 會把它解讀成同名
別名的自我參照 → `BinderException`。`union_by_name` 只能在「有些檔案有」時補 NULL，全部
都沒有就救不了。**而這步發生在 `reimport_db()` 已清空 `daily_prices` 之後**，炸掉 = 整表 0 筆。
（實際踩到：`--backfill-yf 20` 刪光 402 個含 OHLC 的舊 CSV、重抓成無 OHLC 格式後重現。）
→ 改成先 `DESCRIBE` 來源表取實際欄位，缺的用 `CAST(NULL AS ...)` 補，並對缺 OHLC 發警告。

**③ `backfill_yfinance` 把抓到的 OHLC 丟掉**
`yf.Ticker().history()` 本來就回 Open/High/Low，但 `_fetch_yfinance_one_stock()` 只把
close/change/volume 寫進 row → 每次 backfill 都讓 K 棒失去 OHLC。這跟 2026-07 那次
「K棒功能失效」是同一個病，當時只修了 daily_prices scraper，backfill 這條沒修到。
→ 新增 `_ohlc_value()`（NaN／None／非正值一律 None，避免 K 棒畫出假實體），寫進 row。

### 資料來源相關
- **上市（TWSE）／上櫃（TPEx）每日流程完全沒動**，不涉及來源切換。
- 動到的是**歷史回補**這條：`backfill_yfinance()`（yfinance，雙市場都支援、不需 token）
  多寫 open/high/low 三欄；`import_csv_prices()` 對缺欄位的容錯。
- ⚠️ 注意 yfinance 是**還原股價**（除權息調整過），跟每日流程存的成交價本來就有落差，
  這是既有的已知取捨（memory：3114 髒值來源），本次沒有改變這個行為。

### 驗證狀態（我這邊已跑過）
- `pytest -q` → **590 passed**（原 507 + 本次新增，無回歸）
- 新增 3 組回歸測試：`test_data_integrity.py`（13 個，含金居實況、連假不誤判、空表）、
  `test_import_csv_prices_survives_when_every_csv_lacks_ohlc`、
  `test_fetch_yfinance_one_stock_keeps_ohlc` + `test_ohlc_value_rejects_nan_and_non_positive`
- Cody 已在**筆電**重跑 `--backfill-yf 20 --workers 3` → `daily_prices` 413,232 筆 /
  402 個交易日 / 1036 檔 / 2025-01-02~2026-08-28 連續無洞、OHLC 各 413,225 筆有值
- 金居 8358 五日：+100.37% → **+24.54%**；「5日>30%」219 檔 → 11 檔（抽驗 6103 為連續
  6 根漲停、8/26 `O=H=L=C=38.9` 一價鎖死，屬真實資料非髒值）

### 請 Debugger 驗證
- [ ] `max_span_days()` 的緩衝 `_HOLIDAY_BUFFER_DAYS = 9` 是否合理——**這是我知道的弱點**：
      緩衝取 9 天是為了不把農曆春節誤判成斷層，代價是「只缺 1~2 天」的小洞抓不到
      （`find_gaps` 對真實 DB 只抓到 8/06→8/25 那個大洞，7/17、7/21~22 那種小缺漏漏掉了）。
      要更嚴謹得引入真實交易日曆（TWSE 有開放 API），值得評估是否要做
- [ ] `get_rolling_returns()` 擋下窗口後回 `None`，下游（chips.html Section 8 大戶持倉表）
      顯示是否正常降級成「—」，不會變成 `NaN`／`undefined`／排序爆掉
- [ ] `main.py` 步驟 6.5 的體檢不會拖慢每日流程、例外有被吞住不影響產出
- [ ] `import_csv_prices()` 的 `DESCRIBE` 前置查詢對 402 個 CSV 的效能可接受
- [ ] 上市/上櫃資料來源沒有混用（本次未動每日流程）

### 特別注意
- **還沒做完的部分**：其餘 **16 處**同樣「用資料筆數當交易日」的地方尚未接上防護——
  `processors/performance.py`（96/202/296/974/1208）、`observation_scores.py:256`、
  `flow_watch.py:56`、`screener/backtest.py:289`、`institutional.py:239/276`、
  `patterns.py:863/1642`、`database.py:333/370`。目前只有 `get_rolling_returns()` 有。
  資料補齊的狀態下它們不會出錯，但同一個陷阱還在。
- **桌電的 DB 是獨立的**（`data/` gitignored），那台要 `git pull` 拿到本次修復後，
  再跑一次 `python main.py --backfill-yf 20 --workers 3`，否則會重現同樣的斷層與炸掉。
- 回補指令與兩個踩雷點已寫進 `CLAUDE-developer.md`「🚑 資料跑掉時」一節，
  `log.md` 兩處過時說明（月數填 18、要另外下 `--reimport`）已修正。
## [2026-08-31] 官方基本面資料層 Phase 1

### 改了什麼

- 異動檔案：`scrapers/fundamentals.py`、`screener/database.py`、`main.py`、
  `tests/test_fundamentals.py`、`docs/fundamentals.md`、
  `docs/superpowers/specs/2026-08-31-official-fundamentals-data-design.md`、`log.md`
- 新增 `python main.py --update-fundamentals`：只更新官方基本面 DuckDB，不跑行情、HTML 或 push。
- 新增月營收、財報 facts 兩張表，以及自行重算 MoM／YoY／QoQ 的兩個 view。
- 同一市場的月營收＋財報使用同一 DuckDB transaction；任一寫入失敗會整體 rollback。

### 資料來源相關

- 上市資料（TWSE）：`openapi.twse.com.tw/v1/opendata/t187ap05_L`、
  `t187ap06_L_*`、`t187ap07_L_*`。
- 上櫃資料（TPEx）：`www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O`、
  `mopsfin_t187ap06_O_*`、`mopsfin_t187ap07_O_*`。
- 基本面不使用 FinMind；官方 OpenAPI 無歷史參數，MOPS XBRL 歷史回補另列 Phase 2。

### 請 Debugger 驗證

- [ ] `pytest tests/test_fundamentals.py -v` 全綠。
- [ ] `pytest tests/test_database.py tests/test_main.py -v` 無 regression。
- [ ] 使用 mock 確認 24 個季報 endpoint（2 市場 × 2 報表 × 6 schema）網址正確。
- [ ] 真實執行一次 `python main.py --update-fundamentals`，確認 TWSE／TPEx 都有寫入且重跑不增重複列。
- [ ] 抽查 1101、2330、1240 的官方月營收、EPS、資產總計與 DB 一致。
- [ ] `monthly_revenue_growth` 在缺月時不跨洞；`financial_fact_growth` 在缺前季時不硬算單季。
- [ ] 模擬財報寫入失敗，確認同市場月營收一起 rollback。

### 特別注意

- 金額保存官方原始單位「新台幣千元」，EPS／每股淨值為元。
- 官方損益表是累計值；EPS 刻意不做累計相減。
- 本次沒有改 UI、排程或選股分數。
- Developer 未跑 pytest 或真實資料，只有 AST／diff 靜態檢查。

---

## [2026-09-01] MOPS 官方基本面歷史 Phase 2A＋2B

### 改了什麼

- 異動檔案：`scrapers/mops_xbrl.py`、`scrapers/mops_monthly_revenue.py`、
  `screener/database.py`、`main.py`、`tests/test_mops_xbrl.py`、
  `tests/test_mops_monthly_revenue.py`、`docs/fundamentals.md`、`docs/CONTEXT.md`、
  `docs/adr/0005-xbrl-filings-are-append-only-versions.md`、
  `docs/superpowers/specs/2026-09-01-mops-xbrl-phase2-design.md`、
  `docs/superpowers/specs/2026-09-01-mops-monthly-revenue-phase2b-design.md`、
  `docs/superpowers/plans/2026-09-01-mops-xbrl-phase2.md`、`log.md`。
- 新增 `python main.py --backfill-fundamentals 2013`，只執行官方 XBRL 歷史回填，
  不跑行情、HTML 或 git push。
- 官方清單探索、ZIP SHA-256 版本化、XML／iXBRL context parser、raw facts、canonical facts、
  current projection 與 `financial_facts` 串接皆以 archive transaction 寫入。
- 原始申報版本 append-only；同季度新 SHA 更新 current projection，但不刪舊 filing/facts。
- 基本／稀釋 EPS 不做累計相減；現金流可使用既有單季／QoQ／YoY 邏輯。
- Phase 2B 解析 Big5 月營收 11 欄整批頁，保存 page SHA／normalized versions，排除合計列；
  同一 `--backfill-fundamentals` 在 XBRL 後接續回填月營收。

### 資料來源相關

- 季報歷史：MOPS 官方 `https://mopsov.twse.com.tw/mops/web/t203sb02` 公布的 IFRS 季度 ZIP，
  2013 Q1 起；不使用 FinMind、Yahoo 或其他第三方 fallback。
- 上市／上櫃不由 parser 猜測：投影時用官方最新月營收表對照 exchange；歷史公司無對照時標 `UNKNOWN`。
- 月營收歷史：MOPS 官方 `nas/t21/sii`（上市）與 `nas/t21/otc`（上櫃）靜態頁；
  parser 與 XBRL 分開。Phase 1 TWSE／TPEx OpenAPI 每期更新流程維持不變。

### 請 Debugger 驗證

- [ ] `pytest tests/test_mops_xbrl.py tests/test_mops_monthly_revenue.py tests/test_fundamentals.py -v` 全綠。
- [ ] `pytest tests/test_database.py tests/test_main.py -v` 無 regression。
- [ ] mock 官方下載頁同時含 IFRS、TW-GAAP、外站 URL 時，只接受 MOPS IFRS ZIP。
- [ ] XML 與 Inline XBRL 的 context/unit/scale/sign/decimals 正確，`decimals=-3` 不會被當倍率。
- [ ] 外層 ZIP 直接放 instance 與 ZIP 內再包公司 ZIP 都能解析，且 `../` entry 不會寫到磁碟。
- [ ] 同 archive SHA 重跑 idempotent；同季度新 SHA 保留兩版 raw facts並更新 `xbrl_current_facts`。
- [ ] `financial_facts.report_date` 對 MOPS XBRL 為 NULL，不等於 retrieved_at。
- [ ] Q2 累計值能精確以 3/31 前季推回單季；缺前季保持 NULL。
- [ ] 基本／稀釋 EPS 的單季值、QoQ、單季 YoY 為 NULL，累計同期 YoY 正確。
- [ ] 在小範圍真實執行，抽查 2330、1101；確認 ZIP 真實目錄結構、taxonomy local names、
      金額除以 1000 與現金流方向。
- [ ] 確認真實 MOPS archive 若含 parser 尚未涵蓋的 XML support file，會安全跳過而非整批誤判。
- [ ] Big5 上市／上櫃月營收中文正常、11 欄對位、產業別正確、合計列未寫入。
- [ ] HTTP 200 擋頁、錯誤年月、無 11 欄公司資料時不寫入空頁。
- [ ] `monthly_revenue_pages` 同 SHA idempotent，新 SHA 保留舊 versions 並更新目前營收。
- [ ] 歷史頁的 NULL report_date 不會覆蓋既有 OpenAPI 官方出表日期；完整 13 個月後 YoY 正確。

### 特別注意

- Developer 依規則沒有跑 pytest、初始化 DuckDB 或下載真實資料；8 個 Python 檔 AST 與
  102 個常數 DuckDB SQL statements 靜態解析通過。
- MOPS 官方未確認 ZIP 更正版順序與精確申報時間；目前資料不可宣稱為無前視偏誤回測。
- 首次從 2013 回填會下載多季大型 ZIP；請先用 Debugger 小範圍驗證真實結構，再跑完整歷史。
- `data/fundamentals/` 被 `.gitignore` 排除，不會進 commit；不同電腦各自需要回填。
- MOPS 未官方確認靜態月營收的完整歷史起點與缺頁行為；從 2013 小範圍驗證後再跑完整歷史。

### 2026-09-01 首次真實回填追加修正

- [x] 已重現 4712 `pretax_income` 衝突：IASB 主損益表 `-514,600,000` 與 `tifrs/scf`
      現金流調節項 `-515,173,000` 被 local-name-only mapping 錯併。
- [x] 已重現下一筆 2882 `retained_earnings` 衝突：IASB 主表與 `tifrs/notes` 附註局部值錯併。
- [x] 修正後兩個最小 regression cases 直接執行通過，且完整 cached `tifrs-2013Q1.zip` parser 重播成功。
- [ ] Debugger 仍需正式執行 `pytest tests/test_mops_xbrl.py -v`，確認新增案例與全部既有案例。
- [ ] Cody 可重新執行 `python main.py --backfill-fundamentals 2013`，確認 DB transaction 寫入與後續季度。

### 2026-09-01 2014 Q1 inconsistent duplicate 與斷點續跑

- [x] 已最小化 3356 同 QName/context/unit/decimals 的兩個衝突值；無語意依據可安全擇一。
- [x] 修正為保留兩筆 raw、warning 並略過該 canonical metric，完整 cached 2014 Q1 parser 重播成功。
- [x] 回填預設略過已有 committed `xbrl_archives` manifest 的季度；確認本機 2013 Q1～Q4 均被辨識完成。
- [ ] 驗證新版 archive 的 metric 發生衝突時，`xbrl_current_facts` 與 `financial_facts` 不會殘留舊版值。
- [ ] Debugger 執行 `pytest tests/test_mops_xbrl.py -v`，特別確認 inconsistent duplicate 與 resume cases。
- [ ] Cody 重跑同一 backfill 指令，log 應先顯示 2013 Q1～Q4「已完成，跳過」，再從 2014 Q1 寫入。
- [x] 修正 `xbrl_current_facts` view 的 ambiguous `archive_sha256` join；新增
      `test_init_db_binds_xbrl_current_facts_view`，聚焦執行與記憶體 `init_db()` 已通過。
- [x] 2020 Q3 官方回應偶發 `PK` 開頭但 ZIP central directory 不完整；新增 4 次下載驗證與
      5／20／60 秒退避、no-cache／close 重試，壞內容不寫 cache。截斷→成功 regression 已通過。
- [x] 修正後直接下載官方 2020 Q3 至記憶體並完成 CRC 驗證：80,635,246 bytes，官方檔非永久損壞。
- [ ] Debugger 以 mock 驗證 4 次皆壞時錯誤訊息含 attempts、bytes 與 Content-Type／Length。

---

## [2026-09-01] Index 第二輪：抽屜、固定色階、導覽與 TradingView K 線

### 改了什麼

- Index 右側族群抽屜改為 `min(1180px, 80vw)`；820px 以下維持 100vw。
- 抽屜中的族群／股票名稱與一般文字改用無襯線，代號與數值維持等寬字。
- Top 10 卡片改成固定絕對漲跌幅級距：0–1%、1–2%、2–4%、4%以上；紅漲綠跌且強度對稱。
- Index／籌碼／形態／逆轟四頁主導覽統一字型、padding、border、radius 與 active 樣式。
- 首頁內容順序改為市場現況 → Top 10 → 三組研究分類 → 巨量換手。
- 個股詳情改用鎖定 `lightweight-charts@5.2.0` 的 TradingView Lightweight Charts；
  第一次點個股才下載，使用本專案 ISO 日期＋OHLC＋成交量，關閉時移除 chart 並 disconnect ResizeObserver。
- 未加入 MA10／20／50 或 Oliver Kell 訊號；本輪仍沿用既有 11 個交易日資料視窗。

### 請 Debugger 驗證

- [ ] `pytest tests/test_index_generator.py tests/test_processors.py -q --basetemp <可寫路徑>` 全綠。
- [ ] 產生 mock HTML 後確認順序為市場現況 → Top 10 → 今日研究順序 → 巨量換手。
- [ ] 固定色階邊界 0、1、2、4% 與負值鏡像正確；同一 1.5% 不因當日最大漲幅不同而變色。
- [ ] 1440px 點族群後抽屜約佔 80vw、最大 1180px；820px 以下為 100vw，表格只在抽屜內橫向捲動。
- [ ] 抽屜名稱／個股文字為 sans，代號／數值仍為 monospace，14 欄表格與排序未退化。
- [ ] 四個頁面的導覽尺寸一致，只有目前頁 active；鍵盤 focus 與窄螢幕橫向捲動正常。
- [ ] 第一次點個股時 Network 才請求 `lightweight-charts@5.2.0`，第二次不重複插入 script。
- [ ] 個股 modal 同時顯示日 K 與成交量，紅漲綠跌、日期順序與本地 OHLC 一致，TradingView attribution 可見。
- [ ] 關閉個股 modal 後 chart canvas／ResizeObserver 已清理；重複開關、切族群、Esc 與 backdrop close 無錯誤。
- [ ] 斷網或阻擋 jsDelivr 時顯示「K 線載入失敗，請重新開啟個股詳情」，其餘個股資料仍可閱讀。
- [ ] 1440／1180／820／520px 實際瀏覽器 layout 無重疊、溢位或 loading 狀態雙倍高度。

### 特別注意

- Developer 只完成 Python compile 與 `git diff --check`，沒有執行 pytest、`main.py`、真實資料或產生／發布 `docs/*.html`。
- 工作區仍混有 Cody 的 fundamental-data WIP；測試、commit 或 stage 時只能挑本任務相關 hunk。
- `docs/index-preview.html` 是既有未追蹤預覽檔，本輪沒有覆寫或納入交付。

---

## [2026-09-01] Index 桌面工作區精簡＋右側研究抽屜

### 改了什麼
- 異動檔案：`export/index_generator.py`、`tests/test_index_generator.py`、`main.py`（只新增 `data_mode` 透傳）、`docs/CONTEXT.md`。
- 首頁順序改為市場現況 → 完整寬度巨量換手 → Top 10 → 值得研究／先觀察／避開。
- 新增互斥研究分類、衝突標記、Top 10／全部、排序、篩選、localStorage 與右側個股 drawer。
- 移除可見轉折點、排名進出榜、悄悄佈局、重複量能排行、常駐五級圖例與 WIP 左側 sticky rail。
- 盤中／收盤模式由 `main.py` 透傳，盤中顯示暫定資料與「疑似巨量換手」。

### 資料來源相關
- 未變更 TWSE／TPEx 行情、法人、族群績效或巨量換手 scanner；只重組既有 generator 輸入與 UI。
- `scan_volume_turnover()` 既有 9.5%／126 日最大量／1.5x／20 日歷史門檻未改。

### 請 Debugger 驗證
- [ ] 使用可寫 `--basetemp` 執行 `tests/test_index_generator.py`，確認新舊純函式與產生器契約全綠。
- [ ] 以真實資料重產後確認 1440px 恰為 5×2 Top 10，市場現況與巨量換手皆為完整寬度。
- [ ] Top 10／全部、研究分類、名稱搜尋、四種排序、進階條件與重設會同步影響排行／摘要且 reload 後保留。
- [ ] 三組研究摘要互斥；短線異常跳升但週度退燒時顯示衝突標記；巨量換手不進「避開」。
- [ ] 卡片、摘要、Header 搜尋與 `index.html#meta=<族群>` 都開同一右側 drawer，不造成 heatgrid reflow。
- [ ] drawer 的 Esc、關閉按鈕、切換族群與 focus restoration 正常；個股表格所有 14 欄、排序與個股 K 線 modal 未退化。
- [ ] 375／820／1180／1440px 無整頁水平破版；窄螢幕 drawer 為全寬，表格只在 drawer 內橫向捲動。
- [ ] 盤中頁顯示「盤中資料，尚未收盤確認」「疑似巨量換手」；收盤頁顯示「收盤快照」「巨量換手」。
- [ ] Header 無主題切換；首頁看不到常駐五級圖例、轉折點、排名進出榜與舊 secondary-row。
- [ ] 檢查惡意族群／個股名稱的 HTML／DOM escaping 未退化。

### 特別注意
- Developer 依 repo 規則未執行 pytest、真實資料流程或重產 `docs/index.html`；只完成 Python compile 與 `git diff --check`。
- `main.py`、`docs/CONTEXT.md`、`log.md` 同時有 Cody 的官方基本面 WIP；驗證／commit 時只能挑本任務相關 hunk，不可覆蓋或整批 stage。
- 60 交易日快照保存與更新失敗 stale banner 的排程生命週期尚未接線，不列為本次 UI 驗證失敗。
