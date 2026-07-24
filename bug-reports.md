## [2026-07-24] 驗證(續2) - build 重建自動保留 exchange 欄（Developer @ master c6f98dd）

### 背景
承前兩則。我上一則列的唯一殘留 gated 風險是「重建會丟失 exchange 欄、須補跑 update_exchange.py」。
Developer 新增 `c6f98dd` 直接在 build 內根除此地雷。`git reset --hard master` 對齊後重驗（工作區
本來就乾淨、無需 stash）。

### ✅ 驗證通過
- **測試 13 綠**：`pytest tests/test_build_universe.py -v` → **13 passed**（原 9 + exchange 保留 4 個：
  `test_load_existing_exchange_missing_file` / `_no_column` / `_reads_map` /
  `test_build_preserves_existing_exchange_column`）。
- **code 審查（`git show c6f98dd`）**：
  - 新增 `load_existing_exchange()`：從既有 `stock_universe.csv` 讀 `{stock_id: exchange}`；
    檔案不存在或無 exchange 欄 → 回空 dict（防禦正確）。
  - `build()` 把 exchange map 回填每列，新股（舊檔沒有）預設 `""` 留白，之後由
    `update_exchange.py` 補——至少不會整欄清空打斷 main.py 上市/上櫃路由。
  - 輸出欄序固定為 6 欄 `stock_id, stock_name, exchange, meta_sector, sub_sector, note`（正確）。
- **殘留 gated 風險解除**：重建不再掉 exchange 欄。（我未在 debug 這台重建——照 gated 規則，
  單元測試 + code 審查已足；Developer 已於其端做過真實資料端到端驗證：META 零差異、exchange 零遺失。）

### 結論
- [x] 通過 — **Developer 可 push origin**。掉欄地雷已根除，Task 3 重建的最後一個安全性顧慮排除。

---

## [2026-07-23] 驗證 - 族群分類校正層 + 光通訊 4 檔（Developer @ master afe9538）

### 驗證方式
`git merge master` 乾淨 FF 到 `afe9538`，對照本次交付的 5 項驗收清單逐項實查（跑測試 + 讀
`scripts/build_universe.py` + 實查 `data/stock_universe.csv` / `data/sector_overrides.csv`）。

### ✅ 驗證通過
- **測試全綠**：`python -m pytest tests/test_build_universe.py -v` → **9 passed**（本機重現，與
  Developer 9/9 一致）。
- **override 範圍正確**：
  - 只動清單內股號 → `test_apply_overrides_unmatched_id_returns_warning`（未命中股不動）、
    `test_apply_overrides_no_overrides_leaves_unchanged` 皆綠；code `apply_overrides()` 只在
    `overrides.get(sid)` 命中時改該列（build_universe.py:53-62）。
  - meta/sub 留空 → 保留自動值 → `test_apply_overrides_empty_sub_keeps_auto_sub` /
    `_empty_meta_keeps_auto_meta` 綠；code 用 `if ov["meta_sector"]:` / `if ov["sub_sector"]:`
    非空才蓋（:58-61），符合設計。
  - 命中 → note 改「手動校正:<source_note>」並清 ⚠️ → `_replaces_meta_sub_and_clears_warning`
    綠；且已校正股從 ambiguous 清單移除（:135-136，`test_build_override_removes_stock_from_ambiguous_report`
    驗到報告出現「無爭議股票」）。
- **光通訊 4 檔實查**：`data/stock_universe.csv` 中
  2455(全新)/3081(聯亞)/4991(環宇-KY)/6442(光聖) 的 `meta_sector` = **光通訊**，`sub_sector`
  亦=光通訊。（註：這 4 列現況 `note` 為空，反映的是 commit `eec68f0` 的過渡期手動歸類，**不是**
  override 重建路徑——與「先別重建」指示一致；override 寫 note 的行為由單元測試覆蓋。）
- **缺輸入檔明確錯誤**：`build()` 開頭 `if not SECTOR_CSV.exists(): raise SystemExit(...)`
  給中文指引訊息（:67-71），非裸 `FileNotFoundError`；`test_build_missing_input_raises_systemexit` 綠。
- **只影響 universe 建置**：`grep build_universe` 於 main.py/scrapers/processors/screener/export
  **零 import** → 純獨立腳本，不碰每日 TWSE/TPEx 行情/籌碼、不涉回補。
- **exchange 欄未被動到**：現況 CSV 4 檔 exchange 仍為 TWSE/TPEx 正確值；且 build_universe 寫出欄位
  只有 stock_id/stock_name/meta_sector/sub_sector/note（:122-128）不含 exchange——這正是「重建會沖掉
  exchange、須補跑 update_exchange.py」的來源，本次未重建故無影響。

### 🟡 提醒（非本次缺陷，重申 gated 風險）
- Task 3 重建仍不可跑：`data/sector_overrides.csv` 種子目前只有光通訊 4 檔，未含既有手動
  override（廣宇、奇鋐、38 檔工業電腦…）。直接 `python scripts/build_universe.py` 會 (1) 沖掉那些
  既有 override、(2) 丟失 exchange 欄。遷入種子 + 補跑 update_exchange.py 前別動。程式本身無誤，
  純資料前置未就緒。

### 結論
- [x] 可以繼續下一個任務 — 5 項驗收全數通過，**Developer 可 push origin**。

---

## [2026-07-24] 驗證(續) - 種子檔遷移 55 檔 + 死股移除（Developer @ master 733e31c）

### 背景
承上則。master 已 rebase 至 `733e31c`，把既有手動 override 全數遷入種子檔（4 光通訊 → 55 檔），
並移除兩檔已下市股。`git reset --hard master` 對齊後（我的 bug-reports.md 用 stash/pop 保住、無衝突），
重跑驗證。

### ✅ 驗證通過
- **測試全綠**：`pytest tests/test_build_universe.py -v` → **9 passed**。
- **種子檔格式**：`data/sector_overrides.csv` 開頭 `b'\xef\xbb\xbf'`（UTF-8 BOM）✓；`wc -l` = **56**
  行（55 檔 + 表頭）✓。
- **55 檔遷移完整且零矛盾**（唯讀交叉比對 override ↔ universe）：
  - 55 檔 override **全部**存在於 `stock_universe.csv`（無下市/代號錯的 missing）。
  - meta 非空的 override 與 universe 現值 **零不一致**（55/55 全對得上）。
  - 分布合理：光通訊 4 + 既有 51（先進封裝設備 9、半導體材料 8、工業電腦 6、消費電子 4、
    電信 4、其他電子 4、PCB 3、記憶體 3…），對應「4 光通訊 + 51 既有手動校正遷移」。
- **光通訊 4 檔**：2455/3081/4991/6442 `meta_sector`=光通訊、`sub_sector`=光通訊、exchange 完好。
- **死股已移除**：`grep -cE "^(3426|4987),"` = **0**（台興/科誠已下市，與重建結果一致）。

### 🟡 提醒（門檻已降，但仍屬 gated）
- 上一則「種子只有 4 檔、重建會沖掉既有 override」的阻塞**已解除**（55 檔遷移完成）。
- 但 `python scripts/build_universe.py` 重建**仍會丟失 exchange 欄**（build_universe 不寫該欄），
  重建後必須補跑 `python scripts/update_exchange.py`。故仍不宜隨手重建；要重建請照 debug-tasks
  的 Task 3 完整流程走。本次驗證**未重建**，純唯讀抽查。

### 結論
- [x] 可以繼續下一個任務 — 全數通過，**Developer 可 push origin**。

---

## [2026-07-22] 驗證 - 族群總覽頁熱區格改版（export/index_generator.py 取代 html_generator.py）

### 驗證方式
對照 `debug-tasks.md` 2026-07-22 條目「請 Debugger 驗證」清單逐項確認。這次過程中先發生一個
插曲：Debugger（我）跟 Developer 幾乎同時被交付同一個熱區格改版任務，各自寫了不同的技術設計
（我的偏向 client-side JS 算分類、Developer 的偏向 server-side Python 算分類+回推算法做轉折點），
發現後我停手把 debug 分支重置回 master，讓 Developer 那份（已經跟 Cody brainstorming 定案過）
繼續做完，我回到正常 Debugger 角色驗證，沒有兩邊各自硬做造成分岔。

### ✅ 驗證通過
- `python -m pytest tests/test_processors.py -q`：**40 passed**（跟報告一致）
- `python -m pytest -q` 全套件：**386 passed, 1 failed**（差的是既有環境限制
  `test_scan_patterns_returns_list`，需要本機 `data/screener.db`，這台 debug 資料夾本來就沒有，
  跟這次改動無關，歷史上每次都是這個模式）
- **真實頁面確認是新版**：Cody 桌電後來又跑了 `python main.py`（`docs/index.html` 21:25 重新
  產生），確認：
  - 41 個 `.heat-tile` 卡片全部存在，`mc-card`（舊版殘留）完全沒有
  - 4 個頁面（index/chips/patterns/momentum）nav 互連逐一 grep 確認全部正常
  - 異動族群：今天剛好 0 檔符合條件，誠實顯示「目前沒有族群符合爆量暴衝或連續噴出的條件」
    空狀態文字，不是空白或壞掉的區塊——動態張數設計驗證通過
  - 族群近況①升溫/退燒 Top5：10 筆真實資料（例如「電信 +0.53% 今日、+4.5pt 加速」）
  - 族群近況②轉折點列表：**20 筆真實翻轉紀錄**（例如「AI晶片 弱→整理」），證明
    `_streak_and_windows_as_of()` 回推算法（不開新表）真的端到端跑通，不只是通過假資料的單元
    測試
- **安全性檢查**：`stock_name`/`meta_name` 這類外部資料的跳脫策略是刻意分兩層——伺服器端
  `_esc()`（`export/index_generator.py:327`）用在 Python `generate()` 直接吐出的 HTML（熱區格
  卡片、異動族群卡片、族群近況列表都有逐一呼叫，grep 確認一致），前端 `escHtml()`（同檔案
  ~715行）用在 JS `selectGroup()` 動態插入 DOM 的個股明細面板——這裡不能只靠 Python 端的
  `_esc()`，因為個股資料是從內嵌 JSON 讀出來的（`json.dumps` 只做 JSON 字串轉義，不是 HTML
  escape），`escHtml()` 用瀏覽器原生 `textContent→innerHTML` 技巧在真正插入 DOM 前才轉義，是
  正確的做法，程式碼裡的註解也把這個「為什麼要兩層」的理由講得很清楚。這塊沒發現問題。

### 🔴 發現問題：驗證報告的測試數字跟實際不符
- `debug-tasks.md` 該則報告寫「`tests/test_index_generator.py`：**62 passed**」，我實際跑
  `python -m pytest tests/test_index_generator.py -q` 只有 **36 passed**，用
  `grep -c "^def test_" tests/test_index_generator.py` 確認檔案裡真的只有 36 個測試函式，不是
  我的環境漏跑或誤判。
- 這不是這台 debug 資料夾常見的「缺 `data/screener.db`」那種環境限制——這個檔案的測試完全不碰
  真實 DB，跑起來很乾淨，36 個全過，純粹是報告裡寫的數字（62）本身就不對，可能是彙整報告時
  筆誤或算錯，不是程式碼有問題。**測試本身沒有少寫或被誤刪的跡象**（36個測試涵蓋
  `classify_tier`/`classify_temp`/`heat_bg`/`build_heatgrid_cards`/`build_sector_recap`/
  `find_turning_points`/`find_anomaly_cards`/`build_stock_detail_data`/`generate()` 都有），
  只是報告數字寫錯，但既然這是「請 Debugger 驗證」清單裡明確列出的檢查項，還是要如實回報這個
  落差，不能因為「反正測試都過」就跳過不提。

### ⚠️ 無法驗證：鍵盤操作（Tab focus + Enter/Space 展開）
- 交接清單特別要求「麻煩實際測一次，不要只看程式碼」，但這次 session 沒有瀏覽器工具可用
  （`claude-in-chrome` 使用者選擇不安裝），只能確認程式碼層級：`docs/index.html` 裡
  `onkeydown`/`role="button"` 屬性確實存在（grep 確認），但沒辦法真的按過一次驗證行為正確
  （例如 Enter 有沒有正確觸發展開、Space 會不會意外捲頁等瀏覽器層級細節）。誠實回報這項沒做到
  底，不是裝作測過。麻煩 Cody 桌電有空實際點一次，或之後找有瀏覽器工具的 session 補測。

### 結論
- [x] 可以繼續下一個任務——核心功能（熱區格、異動族群、族群近況、轉折點、nav、安全性）都驗證
      通過，真實資料端到端跑起來正確。
- [ ] 兩個待跟催項目：① 上面的測試數字落差（62→36，不影響功能，但報告要更正）；
      ② 鍵盤操作需要有瀏覽器的環境補測一次。
- 動能五級/溫度變化/異動族群三組門檻仍是未回測草案，跟報告本身的立場一致，這次驗證只確認
  程式邏輯符合 spec、端到端資料正確，不代表門檻數值本身合理。

---

## [2026-07-20] 驗證 - TAIEX完全失敗 market_permission() 降級修復（commit 95e18bf）✅

### 驗證方式
對照 debug-tasks.md 2026-07-20 條目，確認 Developer 修法符合上一則報告建議的方向。

### ✅ 驗證通過
- `export/momentum_generator.py::market_permission()` 開頭新增 guard：`market_regime` 為空
  或缺 `"tier"` 欄位時，直接回傳 `permission="unknown"`、`advice_text=""`，不再落到
  `tier.get("tier","持平")` 預設值分支——完全符合我上一則建議的改法。
- 新增 `tier_text="大盤資料無法取得"` + `divergence_text` 明確說明「TAIEX 指數或大盤資料本次
  抓取失敗」，比單純回傳 unknown 更好，使用者能直接看出是資料問題不是大盤真的持平。
- 兩個新回歸測試（`test_market_permission_unknown_when_market_regime_empty`、
  `_when_tier_key_missing`）涵蓋空 dict 跟「非空但缺 tier」兩種情境，正是原本沒被測試網住的
  邊界情況。
- `python -m pytest tests/test_momentum_generator.py -q`：**43 passed**（跟 Developer 回報一致）
- `python -m pytest -q` 全套件：**337 passed, 1 failed**（差的還是同一個既有環境限制
  `test_scan_patterns_returns_list`，跟 Developer 桌電 338 passed 對得起來，337+1既有限制=338）

### 結論
- [x] 可以繼續下一個任務——修復確認正確，逆轟策略 v2 Plan 3/3 至此全數驗證通過，可以 push。

---

## [2026-07-19] Review - 逆轟策略 v2 Plan 3/3（generator + UI 整合）驗證

### 驗證方式
對照 `debug-tasks.md` 2026-07-19 條目「請 Debugger 驗證」清單逐項確認。debug worktree 沒有
`data/screener.db`（既有已知限制，CLAUDE.md 已註記），無法實際跑 `python main.py` 產生真實
頁面，部分項目只做得到程式碼層級檢查。

### ✅ 驗證通過
- `python -m pytest tests/test_momentum_generator.py tests/test_html_generator.py -q`：
  **58 passed**。
- `python -m pytest -q` 全套件：**335 passed, 1 failed**——差的那 1 個是
  `test_scan_patterns_returns_list`，需要本機 `data/screener.db`，這台 debug 資料夾本來就沒有
  這個檔案，是既有環境限制，跟這次改動無關（CLAUDE.md 已明確列為已知限制）。跟預期的
  336 passed 差1，原因就是這個，不是 regression。
- `determine_final_label()` 優先序（跌停風險 > 出場條件命中 > 進場候選六項閘門 > 風險升高 >
  續強觀察 > 等待確認）逐行對照 spec，符合描述；「弱」「超弱」都有涵蓋進風險升高分支（確認
  debug-tasks.md 提到的那個修復點）。
- `selloff_risk_zone()` 確認用 `daily_excess_pct`（不是 `rs_market_score`），跌停風險優先權
  高於抗跌候選，邏輯正確，沒有重犯 v1 舊版用錯5日週期欄位的錯。
- 4 個 generator 原始碼（`html_generator.py`/`chips_generator.py`/`patterns_generator.py`/
  `momentum_generator.py`）nav 模板互相檢查過，4 個頁面互指連結都存在（程式碼層級沒問題，
  見下方 🟡 說明為何實際頁面還看不到）。
- `BANNED_PHRASES` 六個命令式字樣在目前 `docs/momentum.html` 全文搜尋 **0 命中**——但這份檔案
  是舊檔不是這次新程式產生的（見下方🟡），這項驗證實際上沒測到新 code 的真實輸出，只能算
  「舊頁面本身沒問題」，不能當作新 generator 的驗證通過。

### 🟡 目前無法驗證，需要 Cody 桌電用真實資料跑一次
`docs/index.html`／`chips.html`／`patterns.html` commit 於 7/17（`c3d4b0e`），`docs/momentum.html`
commit 於 7/16（`c644f89`）——**都早於這次 Plan 3 的 9 個 commit（全部在 7/19）**。也就是說
repo 裡現在看得到的 4 個 `docs/*.html` 都是舊版程式產生的頁面，不是這次新 code 的真實輸出。
debug worktree 沒有 `data/screener.db`，跑不了 `python main.py` 重新產生，所以以下三項只做到
程式碼審查，沒辦法用真實頁面驗證：
- `BANNED_PHRASES` 肉眼複查（自動化測試 fixture 已覆蓋，但那是假資料，不是真實頁面）
- 4 個頁面 nav 互連是否真的可點（程式碼模板正確；但目前 `docs/index.html`/`chips.html`/
  `patterns.html` 舊檔互連本來就沒有連到 `momentum.html`——這是舊版程式產生的預期結果，不代表
  新版程式有問題）
- `index.html` 族群卡片排序改用觀察分後的實際排序結果是否合理

建議 Cody 桌電跑一次 `python main.py`（有 `data/screener.db`）重新產生 4 個 `docs/*.html` 並
push，我再重新肉眼複查一次。

### 🔴 發現問題：TAIEX 完全抓取失敗時，`advice_text` 反而比「日期部分不一致」時更寬鬆
- 位置：`export/momentum_generator.py::market_permission()`（52-111行）+ `main.py`
  676-700行、905-909行
- 這是 debug-tasks.md 點名要我判斷「是否可接受」的行為，我的結論：**建議修**，這不只是「看起來
  一樣」的降級選擇，是兩種失敗模式的降級程度不一致，而且方向相反。
- 現況比對：
  - **部分失敗**（TAIEX有抓到，但日期跟個股行情對不上）：`market_permission()` 第67行
    `if index_date is not None and price_date is not None and index_date != price_date` 命中
    → `permission="unknown"`，`advice_text=""`（完全不輸出操作文案）。這是保守、正確的降級。
  - **完全失敗**（TAIEX整支API掛掉，`main.py` 676-700行 try/except 吃掉例外後
    `market_regime=None`）：`main.py` 906-907行傳進 `market_permission()` 的是
    `market_regime or {}`（空 dict）＋`index_date=None`。因為 `index_date is None`，第67行的
    日期一致性檢查**直接被跳過**，落到第75行 `tier = market_regime.get("tier", "持平")`——空
    dict 沒有 `"tier"` 這個 key，套用預設值 `"持平"` → `permission="selective"` →
    **輸出完整操作建議文案**：「只看條件完整的強勢候選；訊號不足的個股維持觀察，不追價。」
  - 結果：資料**更不完整**（整支 API 失敗，不只是日期對不上）的情況，反而**輸出了比較寬鬆、
    像正常運作**的文案，跟「部分失敗就閉嘴」的保守設計方向相反。使用者在 TAIEX 完全抓不到的
    當天打開頁面，看不出任何異狀，還會拿到一段像是「大盤真的持平」時才該出現的操作建議。
- 已確認沒有回歸測試覆蓋這個情境：`test_market_permission_skips_date_check_when_dates_not_provided`
  測的是「呼叫端沒傳日期但 regime 本身有效」的向後相容案例（`regime` 裡有 `tier:"大漲"`），
  跟這裡「`market_regime=None` → 空 dict」的情境不同——這是一個沒被測試網住的真實邊界情況，
  不是憑空假設，`main.py` 實際 production 路徑會真的走到這裡（TAIEX 抓取失敗時常發生）。
- **建議改法**（給 Cody 決定要不要現在改）：`market_permission()` 開頭加一個檢查——
  `market_regime` 為空 dict 或 falsy（沒有任何欄位可用，例如缺 `"tier"` key）時，直接回傳
  `permission="unknown"`，不要落到 tier 預設值分支。這樣「TAIEX完全失敗」的降級程度會跟「日期
  對不上」一致或更保守，而不是更寬鬆。

### 🔄 補驗證（2026-07-20，Cody 桌電重新跑過 python main.py 後）
`git merge master` 拉到新版 4 個 docs/*.html（`docs/momentum.html` 更新為 7/20 21:37，
971,825 字元，確認是這次新 code 的真實輸出，不再是 7/16 舊檔），補做原本卡住的三項：

- ✅ **BANNED_PHRASES 肉眼複查**：新版 `docs/momentum.html` 六個命令式字樣全文搜尋 **0 命中**
- ✅ **4 頁 nav 互連**：index/chips/patterns/momentum 四個頁面現在互相都連得到彼此（`<a href>`
  逐一 grep 確認）
- ✅ **index.html 排序改觀察分**：Top5 族群順序跟 `momentum.html`「主流族群 Top 5」完全一致
  （電子零組69.0 > 電信66.9 > 通信元件60.5 > 電源類58.2 > 生技製藥54.1，降冪排列，
  `sector_state` 也跟著分數合理分級為主升/轉強），兩頁用同一份 `observation_scores` 結果、
  排序一致
- 附帶驗證：今天真實資料 `permission="defensive"`，`急殺風險區` 正確渲染（566 檔抗跌候選），
  順便驗證了 `risk_zone_html` 只在 defensive 時顯示的條件邏輯是對的

### 結論
- [x] 可以繼續下一個任務——除了下面這一點，其餘驗證全數通過。
- [ ] TAIEX 完全失敗時 `advice_text` 反而比部分失敗更寬鬆的問題，Cody 已決定交給 Developer
      處理（不在 debug 這邊直接改），本則報告已提供完整定位與建議改法，等 Developer 修完後
      debug 這邊再驗一次。
- 邏輯本身（決策標籤優先序、急殺風險區欄位選用、5因子觀察分排序）程式碼審查沒發現問題，跟
  spec 一致；提醒 debug-tasks.md 已標注的「全部實驗性、待回測校準」立場維持不變，這次驗證
  只確認程式邏輯符合 spec，不代表策略/門檻數值本身有效。

---

## [2026-07-18] 修 - TDCC 公布延遲前瞻偏誤 + foreign/trust_continuation 消融對照變體（Cody 授權「改吧」）

### 背景
接續上一則 review（`--backtest-chips all` 初次真實輸出），回報了兩個具體可改的點，Cody
授權直接修：① `tdcc_accumulation` 用快照日本身當訊號日，忽略 TDCC 實際公布延遲，疑似前瞻
偏誤；② `foreign_continuation`/`trust_continuation` 的排名公式把「法人連買」跟「10日價格
動能」綁在一起，測不出籌碼本身的貢獻。

### 🔴 修復 1：TDCC 公布延遲前瞻偏誤
- 位置：`screener/backtest.py::scan_chips_rule()` 的 `tdcc_accumulation` 分支
- 問題：原本 `latest = MAX(date) FROM shareholder WHERE date <= date_str`，只在
  `latest == date_str`（快照日本身）才發訊號。但 TDCC 集保股權分散表每週五更新的是
  **快照日**，實際**查得到**會晚幾個交易日——用快照日本身當訊號日，等於在「當時實際上還
  查不到這筆資料」的那天就下單，是前瞻偏誤（look-ahead bias）。
- 改法：新增 `_TDCC_PUBLISH_LAG_TRADING_DAYS = 3`（**務實估計值，沒有 TDCC 官方精確公布
  時間表可查證，之後可能需要跟 Cody 確認調整**）+ `_all_trading_dates(db_path)` 快取交易
  日曆，訊號日改成「快照日 + 3 個交易日」，不是快照日本身。
- TDD：`test_tdcc_rule_delays_signal_by_publish_lag`（先製造 RED：快照日跟延遲期間內都不該
  有訊號，延遲滿了才該有）+ `test_tdcc_rule_does_not_repeat_signal_after_publish_day`（公布日
  後隔天不重複計數）。既有測試 `test_tdcc_rule_only_emits_on_weekly_report_date` 的舊斷言其實
  是在測「修復前的錯誤行為」，已改寫成上述兩個新測試，不是單純新增。
- 驗證：real DB 實跑 `tdcc_accumulation`，訊號數從 768→810、訊號日期範圍起點從
  2025-12-19→2025-12-24（往後遞延符合預期，不是隨機跑掉），無 crash。

### 🟡 修復 2：foreign/trust_continuation 消融對照變體
- 位置：`screener/institutional.py::rank_continuation_candidates()` + `screener/backtest.py`
- 問題：排名公式是「連買天數排名 + 10日累積漲幅排名」各占一半，兩個規則的篩選也要求
  `price_cum_pct >= 5`（已經漲 5% 以上才入選）。這代表現在的「籌碼規則」其實有一半權重來自
  價格動能本身，回測結果測不出「法人連買」單獨的貢獻，也可能是中位數超額全負的部分原因
  （D+1 進場等於追在已經漲完的隔天，容易撞到短期均值回歸）。
- 改法：`rank_continuation_candidates()` 新增 `weight_mode` 參數（`"blended"` 預設值=既有
  行為不變，`chips_generator.py` 既有呼叫方式完全不受影響；`"streak_only"`=純連買天數排序；
  `"price_only"`=純價格漲幅排序）。`screener/backtest.py` 新增 4 個消融規則名稱
  （`foreign_continuation_streak_only`/`_price_only`、`trust_continuation_streak_only`/
  `_price_only`），沿用完全相同的篩選門檻，只換排序依據，納入 `CHIPS_RULES`（`--backtest-chips
  all` 會一起跑）。`main.py` 的 `--backtest-chips` argparse choices 改成從 `CHIPS_RULES`
  動態產生，不用手動同步兩份清單。
- **範圍說明**：這次只拆了**排序依據**，沒有動**篩選門檻**（兩個規則都還是要求
  `price_cum_pct >= 5` 才能入選候選池）——debug-tasks.md 原文提到的「僅價格條件 vs 僅籌碼
  條件」如果要做到「完全不用價格篩選」的版本，還需要另外設計「純籌碼條件」的候選池（目前
  沒有這樣的入選邏輯），這次沒做，是更大的後續任務。
- TDD：`test_rank_continuation_candidates_default_blends_streak_and_price`（防止新參數
  悄悄改掉既有行為）+ `_streak_only_ignores_price` + `_price_only_ignores_streak` +
  `_rejects_invalid_weight_mode`（`screener/institutional.py`），
  `test_foreign_continuation_ablation_variants_use_isolated_ranking` +
  `test_backtest_chips_config_covers_all_continuation_ablation_rules`（`screener/backtest.py`）。
- 驗證：real DB 實跑 `foreign_continuation_streak_only`，無 crash，數字跟原本 blended 版
  同一量級（仍是勝率<50%、中位數負，初步看不是「拆開後籌碼單獨就變好」，但這只是 sanity
  check 不是正式分析，正式解讀留給 Cody 或下一輪 review）。

### 測試
`tests/test_institutional.py` 10 passed、`tests/test_backtest.py` 18 passed、
全專案 `pytest tests/ -q`：**292 passed, 1 warning**（既有無關 warning）。

### 結論
- [x] 可以繼續下一個任務——兩個修復都已 commit，TDD 全綠，real DB sanity check 無 crash。
- 兩項修復都只是**讓回測更誠實**（去除前瞻偏誤、讓消融對照可執行），**不代表任何規則現在
  被證實有效**——debug-tasks.md 列的配對組/bootstrap/樣本外/paper tracking 仍然一項都沒做，
  結論標準維持前一則報告的規定，不因為程式碼修好了就放寬。

---

## [2026-07-18] Review - `python main.py --backtest-chips all` 初次真實輸出（Cody 桌電實跑，大戶資料已回補）

### 驗證方式
Cody 提供完整 log 輸出（5 條規則：joint_buy/foreign_continuation/trust_continuation/
margin_bearish/tdcc_accumulation），對照 `debug-tasks.md` 「🖥️ 桌電待驗：籌碼策略是否真的
有增益」那則的檢查清單，逐項覆查程式碼 + 解讀數字。**這次只做得到「程式碼正確性」跟「原始
數字紅旗」兩塊，debug-tasks.md 明列必做的對照組/bootstrap/樣本外/paper tracking 都還沒做，
不能下最終結論。**

### ✅ 程式碼正確性檢查通過
- **D+1 開盤進場/漲停剔除/交易成本**：`screener/backtest.py::run_backtest()` 統一處理，
  `CHIPS_RULE_CONFIG` 逐規則設定 `skip_no_fill`/`cost_pct`（偏多規則剔除漲停+扣0.6%成本；
  `margin_bearish` 是既有持股風險警示不是放空策略，不剔除漲停、不扣成本——語意正確）。
- **no-lookahead／法人 fallback 不得重複計數**：`scan_chips_rule()` 明確用
  `available_dates = _table_dates(db_path, "institutional")` + `date_str not in available_dates`
  跟 `if not any(r.get("date") == date_str for r in rows): return []` 兩層擋掉
  `scan_institutional()` 既有的「缺資料日 fallback 沿用前一發布日快照」行為，確保只在真正
  發布的那天才產生訊號，不會把同一批法人數字在後續交易日重複算成新訊號——這正是
  debug-tasks.md 特別點名要複查的地方，已在程式碼層級正確處理。`tdcc_accumulation` 同理
  （`str(latest)[:10] != date_str` 擋掉週資料被後續每天重複計數）。
- **`get_margin_divergence(..., as_of_date=date_str)`**：SQL 用
  `WHERE (? IS NULL OR date <= ?)` 正確綁定 `as_of_date`，不會像先前抓到的
  `calc_cumulative_meta()` 那個 bug一樣吃到未來資料。
- **訊號日 vs 訊號筆數分開統計**：`print_summary()` 用 `nunique()` 算獨立訊號日數，
  低於 `_MIN_RULE_SIGNAL_DATES`/`_MIN_BLOCK_SIGNAL_DATES` 門檻會印出「訊號日不足」警告，
  不會把大量同日股票誤當成大量獨立樣本——這點程式碼已經內建，數字本身也誠實標注了。

### 🔴 原始數字紅旗（4 條偏多規則：joint_buy/foreign_continuation/trust_continuation/tdcc_accumulation）
四條偏多規則在**全部/多頭/D+5/D+10/D+14 幾乎每一格**都呈現同一個令人擔心的模式：

| 規則 | D+14 勝率(超額>0) | D+14 平均超額 | D+14 中位數超額 |
|---|---|---|---|
| joint_buy | 44% | +2.98% | **-2.58%** |
| foreign_continuation | 40% | +0.76% | **-4.70%** |
| trust_continuation | 42% | +2.29% | **-2.68%** |
| tdcc_accumulation | 35% | +0.51% | **-3.44%** |

- **勝率全部低於 50%**（34~44%），**中位數超額全部是負的**，但**平均超額偶爾是正的**——
  這是典型的「右偏態」訊號：一小撮大贏家把平均拉正，但典型（中位數）交易其實輸給大盤。
  這不是穩健的優勢訊號的樣子，是需要進一步拆解才能判斷是真訊號還是雜訊放大的樣子。
- **限定多頭 regime 也一樣**：不是「熊市拖累平均」的故事——即使只看多頭子集，勝率跟中位數
  超額還是同一個不健康的樣子，代表這不只是行情濾網問題。
- **盤整 regime 全部最差**（但都標了「訊號日不足」，1~8 個訊號日，這段期間盤整很少見，
  樣本太小不能下結論，只能說「方向上一致地更差」這件事值得留意）。

### 🟡 margin_bearish（唯一的偏空風險警示規則）
避險命中率(超額<0) 53~56%，比亂猜(50%)略高但不算強力確認；部分區間平均超額還是正的
（例如 D+10 全部 +1.56%），代表雖然過半數訊號有命中「該漲時反而弱」的方向，但沒命中的
那批平均漲得更兇，把整體平均拉正——訊號辨識力偏弱，不是清楚的邊際優勢。

### 還沒做、不能跳過的部分（debug-tasks.md 已列，這裡重申，避免誤用這批數字下結論）
- [ ] 消融對照：僅價格條件 vs 僅籌碼條件 vs 價格+籌碼完整規則——沒有這組對照，現在看到的
  「超額」根本不知道是籌碼資訊本身的貢獻，還是價格端篩選（例如 joint_buy 隱含的族群/漲幅
  篩選）自己就有的效果。
- [ ] 同日期/同族群/相近市值流動性的配對股票對照組。
- [ ] 按訊號日做 clustered bootstrap／信賴區間（現在的勝率/超額都是點估計，沒有不確定性
  區間，尤其樣本本來就不算大）。
- [ ] 樣本外／walk-forward 驗證（目前門檻/規則都是同一段 4~7月資料上定的，還沒測試過其他
  期間會不會結果整個翻掉）。
- [ ] 1~3 個月 paper tracking。

### 結論（依 debug-tasks.md 規定的格式，這批數字目前只能標到這裡，不能再高）
- **4 條偏多規則（joint_buy/foreign_continuation/trust_continuation/tdcc_accumulation）**：
  依 debug-tasks.md 分類法，比較接近「**樣本不足／疑似無增益**」而非「有效候選」——原始
  勝率/中位數的紅旗一致到不像純雜訊，但也還沒有對照組能排除「這只是價格端篩選本身的效果，
  籌碼資訊沒有額外貢獻」的可能性。**在跑完消融對照前，不建議先入為主認為籌碼資訊有用**。
- **margin_bearish**：邊際訊號，避險命中率略高於亂猜，證據力偏弱，同樣需要對照組才能判斷。
- **不得寫成「已證實可交易策略」**（debug-tasks.md 明文規定，這批只是初次真實回測輸出，
  程式碼正確性沒問題，但統計方法論的必要步驟都還沒跑）。
- [x] 可以繼續下一個任務——程式碼層面沒有需要修的 bug；下一步是照 debug-tasks.md 清單做
  消融對照，不是重跑同一組回測。

---

## [2026-07-16] Review - 動能派 B1~B5（commit faa54b8：scan_momentum_health/scan_consecutive_limit_up/scan_bullish_alignment_new_high）

### 驗證方式
逐項對照 `docs/superpowers/specs/2026-07-14-momentum-strategy-page-design.md` §3（B1~B5 資料層規格）
手動追蹤 `screener/signals.py` 三支新函式的每個分支邏輯，並針對懷疑點寫最小重現腳本實跑驗證
（不只信任程式碼看起來合理，B4 的 look-ahead 問題就是這樣抓到的——靜態讀 code 看不出來，
要真的餵資料跑過一次才會發現數字不對）。

### 🔴 程式問題（需立刻修）— `rs_score` 有前瞻偏誤（look-ahead bias）
- 位置：`screener/signals.py:319`（`scan_momentum_health()` 呼叫 `calc_cumulative_meta()`）
- 說明：`calc_cumulative_meta()`（`processors/performance.py:88`）完全不吃 `trade_date` 參數，
  SQL 永遠抓「整張 `daily_prices` 表裡最新的 8 個日期」算族群 5 日累積報酬，不管呼叫端傳的
  `trade_date` 是不是資料庫裡最新的一天。`scan_momentum_health()` 算 `rs_score`（族群內相對強弱）
  時直接拿這個當族群基準，沒有做任何日期裁切——只要 `trade_date` 不是 DB 裡最新的一天，
  `rs_score` 就會摻進 `trade_date` 之後才發生的未來資料。
- 重現方式：寫最小重現腳本（兩檔股票在 `trade_date` 當天有真實漲跌差異，對照組手算
  `rs_score=+5.0`，跟既有測試 `test_scan_momentum_health_computes_relative_strength` 一致），
  在 `trade_date` 之後追加幾天「未來」的族群齊漲走勢——`rs_score` 從預期的 `+5.0` 整個翻成
  `-29.55`，完全被 `trade_date` 之後才發生的資料污染。
- 為什麼現有測試沒抓到：`test_scan_momentum_health_computes_relative_strength`/
  `test_scan_momentum_health_computes_market_relative_strength` 兩個測試都用 `dates[-1]`
  （資料庫最後一天）當 `trade_date`，這時「最新 8 個日期」剛好跟「`trade_date` 為終點的窗口」
  重疊，bug 被巧合遮住，沒有任何測試真的餵過「歷史日期（非最新）」的 `trade_date`。
- 為什麼現在沒事、以後會爆：目前 `scan_momentum_health()` 唯一呼叫路徑是即時/每日產頁
  （`trade_date` 天然就是 DB 最新一天），線上還沒出過錯誤結果。但 spec §6「建置優先序」明講
  「每一條實作後都可以用 `screener/backtest.py` 回測驗證」——`run_backtest()` 正是會逐日餵入
  歷史 `trade_date`，這個 bug 會在第一次拿這支函式回測時，悄悄把每一天的
  `rs_score`/`rs_rank_pct`/`strength_tier` 全部算錯，且不會報錯、不會 crash，只會給錯的排名。
- 對照組：同一函式裡 `rs_market_score`（vs 大盤）那一半完全正確——用的是函式內已經用 SQL
  `WHERE date <= trade_date` 裁切過的 `price_df` 現算，沒有這個問題。只有偷懶重用外部
  `calc_cumulative_meta()` 的 `rs_score` 那一半中招。
- 建議修法（擇一）：
  1. 幫 `calc_cumulative_meta()` 加可選的 `as_of_date` 參數，SQL 加 `WHERE date <= ?`
  2. 在 `scan_momentum_health()` 內部比照 `market_cum5` 的做法，直接用已裁切好的 `price_df`
     現算族群基準，不呼叫外部的 `calc_cumulative_meta()`

### 🟡 建議改善
- `scan_consecutive_limit_up()` 少了 `universe_path` 參數（另外兩支姊妹函式 `scan_momentum_health`/
  `scan_bullish_alignment_new_high` 都有），內部寫死呼叫 `_load_universe_map()`（預設路徑）。
  目前沒有測試斷言 `stock_name`/`meta_sector`，不構成現在的 bug，但沒辦法在隔離環境測試這兩個
  欄位，也跟另外兩支函式的簽章不一致，建議補上參數維持一致性。

### ✅ 驗證通過
- B1 均線排列（`close>MA5>MA10>MA60` 三線，MA20 已正確排除判斷式）
- B2 出場三原則（三條件同時成立才觸發）+ `entry_confirmed`（多頭排列+MA5/MA10皆上揚）
- B3 通用多頭排列+創新高（MA5/10/60、`lookback_days`「含今日」語意自洽，非 off-by-one）
- B5 連續漲停鎖死（`limit_up_streak`/`volume_declining_streak` 邏輯正確）
- 五級強弱分類（§3.7）六個分支手動追蹤全部正確，含容易漏掉的
  「多頭排列但 `rank<0.5`→弱」fallback 分支
- `entry_confirmed` 未誤呼叫/耦合 `patterns.py::detect_breakout_confirm`
- 全專案 260 個既有測試持續通過

### 結論（2026-07-16 更新：Cody 授權直接修，已修完）
- [x] 可以繼續下一個任務 —— 兩項問題都已修復並驗證，見下方「修復記錄」

### 修復記錄（Cody 授權「認真嚴格來修」，Debugger 直接改+commit）

**🔴 `rs_score` 前瞻偏誤 → 已修**
- 改法：拿掉 `scan_momentum_health()` 對 `calc_cumulative_meta()` 的呼叫（該函式不吃
  `trade_date`），改成用函式內已經 SQL `WHERE date<=trade_date` 裁切過的 `price_df`
  現算族群基準（`groupby("meta_sector")` 逐族群算近5日等權平均累積報酬），手法跟原本就
  正確的 `market_cum5`（vs 大盤那半）完全對稱。移除不再使用的 `calc_cumulative_meta` import。
- TDD：先寫失敗測試 `test_scan_momentum_health_rs_score_ignores_future_data`
  （在 `trade_date` 之後注入未來族群齊漲，驗證修復前會 RED：`rs_score` 從預期 `+5.0`
  被污染成 `-29.55`，數字跟審查階段的手動重現腳本完全吻合），修完後轉 GREEN。
- 額外驗證：拿審查階段那支獨立重現腳本（非 pytest，模擬真實情境）重新跑一次，修復前
  `-29.55`、修復後 `+5.0`，確認不是只有測試資料湊巧過。

**🟡 `scan_consecutive_limit_up()` 缺 `universe_path` → 已修**
- 改法：函式簽章加 `universe_path: str = _UNIVERSE_PATH` 參數，內部 `_load_universe_map()`
  呼叫改吃這個參數，跟兩支姊妹函式簽章一致。
- TDD：先寫失敗測試 `test_scan_consecutive_limit_up_accepts_custom_universe_path`（修復前
  RED：`TypeError: unexpected keyword argument 'universe_path'`），修完後轉 GREEN。

**驗證**
- `tests/test_signals.py`：21 個測試全過（含 2 個新增的 TDD 測試）。
- 全專案 `pytest`（master worktree，有真實 `data/screener.db`）：**262 passed**，
  沒有既有測試回歸；debug worktree 跑會少一個（`test_scan_patterns_returns_list`，
  缺本機 DB 的既有已知限制，跟本次改動無關，已用真實 DB 的 master worktree 排除這個混淆
  因素重新確認過）。
- commit `272937e`（debug→master fast-forward，已 push）。

---

## [2026-07-15] 驗證（桌電）- 3 個待驗任務：進貨分校準/regime拆分/搜尋族群修復 全數 ✅ 通過

### 驗證方式
`git fetch` 確認 master/debug/origin 三邊一致（`a2af1f2`，工作區乾淨），`python -m pytest tests/ -q`
全專案跑一次，針對 debug-tasks.md 點名的三則待驗項目逐項深挖，不只信任 commit message。

### ✅ 全專案測試：260 passed, 1 warning
warning 是既有、跟本次改動無關的 `test_processors.py::test_calc_market_breadth_ignores_nan_change_pct`
`FutureWarning`（pandas 版本相關，非本次新增）。

---

### ✅ #1（2aa80a4/a27f129）`print_accumulation_calibration()` 分數分桶依大盤 regime 拆分
- **`test_print_accumulation_calibration_breaks_down_by_regime` 通過**，且手動重跑同一組測資，逐行核對
  輸出：`[60-100分] n=2 平均超額 +1.00%`（聚合列，(+6.0 + -4.0)/2 = 1.0，數學正確）、
  `[60-100分/多頭] n=1 +6.00%`、`[60-100分/空頭] n=1 -4.00%`——**聚合行邏輯確認沒被新的巢狀迴圈影響**，
  這是這次特別被要求覆查的點。
- **`regime` 可能是 `"?"`（資料不足，見 `backtest.py::_regime_at`）時的行為**：新程式碼只迭代
  `["多頭","盤整","空頭"]`，`"?"` 的訊號不會出現在拆分列，但仍計入上方聚合列——追蹤確認這**跟
  `backtest.py::print_summary()` 既有的 regime 拆分邏輯完全同一套模式**（同樣只列三個正式 regime），
  不是這次新增的不一致，是沿用既有慣例。
- **`if "regime" in sub.columns` 這個 guard 本身正確**：`sub` 是 `df` 的切片，欄位集合不會因為
  `.loc`/布林過濾而改變，所以「df 沒有 regime 欄位時完全跳過」這個保證有效，既有呼叫端
  （沒有 regime 欄位的舊測資）行為不受影響。

### ✅ #2（4-Task 進貨分回測校準）
- **`screener/backtest.py` 全程未被這批改動觸碰**：`git log --oneline -- screener/backtest.py`
  最近一次改動是 `e01e1ad`（chips 儀表板重做，時間早於本批次、內容不相關），本批次的
  `2aa80a4`/`a27f129` 及其餘 3 個 Task commit 都沒有出現在 `backtest.py` 的異動歷史裡，claim 屬實。
- **`_shareholder_as_of`/`_recent_return_as_of` no-lookahead 邏輯覆查（這次被特別點名的地基）**：
  兩者都是「篩 `date <= d_ts` → 取排序後最後一筆」的標準 as-of 查詢，`d_ts` 是呼叫端
  `scan_accumulation_score()._scan()` 傳入的**訊號日**（= `run_backtest()` 逐日掃描的 `date_str`）。
  對照 `run_backtest()` 本身的進出場時序（**D 收盤產生訊號 → D+1 開盤進場**，`backtest.py` 多處
  docstring 明講），用「訊號日當天收盤（含）以前」的資料算分數，時序上完全站得住——分數用到 D
  當天收盤價、進場卻是 D+1 開盤之後，不構成前瞻偏誤。
  - ⚠️ **附帶發現（非本次改動引入，屬既有系統性限制，不列為本次 bug）**：`_shareholder_as_of`
    用的「大戶持股」`date` 是 TDCC 集保庫存**快照日**（通常週五），但 TDCC 實際**公布**會晚幾天
    （通常隔週三才查得到）——程式碼目前用「快照日 <= 訊號日」判斷資料是否可用，沒有扣掉這段
    公布延遲，理論上訊號日落在快照日之後、公布日之前的那幾天，會用到「當下其實還查不到」的
    大戶資料。**但這不是本次新增的問題**：追查後確認現行 production 路徑
    `screener/database.py::get_shareholder_top()` 對「最新一筆」的認定用的也是同一套「無延遲」
    邏輯，這次的 as-of 版本只是把既有慣例從「查最新」推廣到「查任意歷史日期」，沒有讓既有限制
    變得更嚴重。值得記錄但不阻擋這批改動過關；如果之後要認真拿回測數字做決策，這個延遲量級建議
    抓 TDCC 實際公布時間表確認一次。

### ✅ #3（a013e8a）搜尋族群「點了沒反應」修復
- `test_search_select_meta_selector_matches_mc_card` 通過，既有 `test_search_select_stock_selector_matches_st_row`
  等測試未回歸。
- `git merge-base --is-ancestor a013e8a HEAD` 確認該 commit 已在 master 歷史中，`git status` 確認
  master worktree 工作區乾淨——**debug-tasks.md 裡記錄的「工作區有其他未 commit 變更／main.py
  自動 commit 持續在跑」的並發狀況已經自然解決**，沒有殘留任何未預期的 staged/unstaged 變更。

### 沒有驗證的部分（不在 Debugger 職責範圍，交還 Cody）
- `python main.py --backtest-accumulation` 真的對 `data/screener.db` 跑一次——debug-tasks.md 已明確
  標注這步留給 Cody 自己開 terminal 跑，這次沒有代跑。

### 結論
- [x] 可以繼續下一個任務
- 三則待驗項目全數 ✅ 通過，唯一新發現（TDCC 公布延遲）是既有系統性限制、非本次改動引入，記錄
  下來供之後參考，不影響這批 commit 的正確性判定。

---

## [2026-07-14] 驗證（筆電）- week_chg 邏輯 ✅ 真的修好了，但 🔴 2380 假訊號還在（既有髒值沒清）

### TL;DR
- **`week_chg` 重算邏輯：✅ 真的修好了**（在真實 DB 的**副本**上實跑驗證，損毀統計全部歸零）。
- **🔴 但 2380 仍掛在大戶減持榜首 `-63.59%`**——寫入端的 `pct >= 99` 防護**只擋新資料，
  沒清洗 DB 裡既有的那筆 100.0 髒值**。只差「清洗既有髒值」這一刀。
- **⚠️ 而且筆電的 DB 根本還沒修**：桌電跑過的 recompute **不會隨 git 過來**（`data/` gitignored）。

### 驗證方式
`git pull` 同步 code 到 origin 最新（192 passed）後，**複製** `data/screener.db` 到 scratchpad，
在副本上實跑 `recompute_all_history()`（**沒有動原始 DB**），再對拍 `LAG(lv12_15_pct)`。

### ✅ 驗證通過 — 重算邏輯與缺週防護
recompute 前（= 筆電 DB 現況）→ recompute 後：
| 檢查項 | 修復前 | 副本 recompute 後 |
|---|---|---|
| 基準錯（≠ 與前一週實際差） | 3724 | **0** |
| 第一週憑空值（無前週卻有 chg） | 1006 | **0** |
| 缺週未清 NULL（間隔 > 10 天卻有值） | 112 | **0** |
| `isnan(week_chg)`（NaN 汙染） | 0 | **0** |
- **缺週防護（`_MAX_WEEK_GAP_DAYS`）生效**：6/26 那筆（距 6/05 隔 21 天）正確寫成 `NULL`，
  沒有把「跨三週的累積變化」謊報成單週。
- **NaN guard 生效**：清洗髒值後 `week_chg` 全部是 **SQL NULL**（`isnan` 0 筆），
  不是 NaN → 下游 `WHERE week_chg IS NULL` 抓得到。
- 全專案 `pytest`：**192 passed**。

### 🔴 數據問題（還沒修完的那一刀）
- 問題：**既有髒值沒被清洗，2380 假訊號原封不動**
  位置：`scrapers/shareholder.py:110`（寫入端 `if lv12_15_pct >= 99` → NULL）、
  `screener/database.py:314`（讀取端排除）
  說明：兩個防護都**擋不到已經躺在 DB 裡的那筆** 2380 / 2026-06-26 `lv12_15_pct = 100.0`：
  - 寫入端只作用於**新抓的資料**，不會回頭清洗歷史列。
  - 讀取端濾的是「**最新一筆** `pct >= 99`」的股票，而 2380 最新一筆是 7/03 的 36.41 → **濾不到**。
  - recompute 於是老實拿 100.0 當基準：7/03 距 6/26 只有 7 天、不算缺週 →
    `chg = 36.4108 − 100.0 = -63.5892` → **仍是減持第 1 名**（第 2 名只有 -4.51，差一個量級）。
  **修法（我已在副本上驗證有效）**：清洗既有髒值後再 recompute——
  ```sql
  UPDATE shareholder SET lv12_15_pct = NULL WHERE lv12_15_pct >= 99;  -- 全表就 1 筆
  ```
  → 再跑 `recompute_all_history()`。實測結果：2380 從榜首消失（7/03 `week_chg` = NULL），
  榜首變成 6127 的 -4.51%（合理量級），且 `isnan` 0 筆、全為 SQL NULL。
  **建議把這個清洗步驟寫進程式碼**（例如 `recompute_all_history()` 開頭先清、或獨立的一次性
  修復函式），不要只靠人工下 SQL——否則換一台機器又會忘記做。

### 🚩 給 Cody 的待辦（換到桌電後）
1. **桌電也要各自跑一次資料修復**（清洗 + recompute）。`data/` 是 gitignored、**不隨 git 同步**，
   桌電修好的資料傳不到筆電，筆電修好的也傳不到桌電——**兩台都要各跑一次**。
2. **桌電的 `CLAUDE.md` 記得重建**：本次把「換平台開工鐵律」寫進了 tracked 的
   `CLAUDE-debugger.md`（規則：換平台第一件事＝強制 `git pull`／`reset --hard origin/master`；
   但 `git pull` **拉不到 `data/`**，資料修復每台各自跑）。桌電 `git pull` 後，
   在**兩個 worktree 各下一行**重建本地身分檔（`CLAUDE.md` 是 gitignored、不會自己更新）：
   - Developer worktree：`cp CLAUDE-developer.md CLAUDE.md`
   - Debugger worktree：`cp CLAUDE-debugger.md CLAUDE.md`

### 結論
- [x] 需要修改後再確認（🔴 既有髒值清洗）
- `week_chg` 重算邏輯、缺週防護、NaN guard 三項 ✅ 確認有效，不需重做。

---

## [2026-07-14] 驗證 - 4 個待驗 commit 從上到下嚴格驗證：#6/#5/Task6/Task5 全數 ✅ 通過，可以 push

### 驗證方式
`git merge master` 乾淨 FF 到 `468dc96`（debug 同步到最新）。逐 commit 讀 diff（`git diff A..B --stat`
先確認改動範圍未外溢）、對照測試、用真實 `data/screener.db`（master worktree）實跑結構/數值檢查。
全專案 `pytest -q`：**189 passed, 1 failed**（唯一失敗是既有已知限制 `test_scan_patterns_returns_list`
缺本機 DB，master worktree 跑是 **190 passed**，非本次改動造成）。

### ✅ #6（468dc96）TWSE/TPEx 抓取單邊失敗加重試
- **`_retry_fetch` 邏輯正確**：追蹤程式碼確認 `retry_on` 之外的例外型別（如 TWSE「尚未發布」的
  `ValueError`）**不會被 for 迴圈的 `except retry_on` 捕捉，會立即原樣往外拋**，不延誤既有的
  日期回退邏輯；`retries` 次全部失敗才 `raise last_exc`，重試間才 `sleep`（最後一次不多睡）。
- **呼叫端 scoping 正確**：TWSE 兩處明確傳 `retry_on=(TWSEBlockedError, RequestException)`
  （排除 ValueError）；TPEx 兩處用預設 `retry_on=(Exception,)`（無條件重試，符合「TPEx 沒有『尚未
  發布』合法信號」的設計）。四處呼叫都包在既有 `try/except Exception` 區塊內，重試耗盡後優雅降級
  （log warning，不會讓整個 `_update_chips_db` crash）。
- **測試**：5 個新測試涵蓋成功不重試／暫時失敗後成功／耗盡拋出最後例外／排除型別立即拋出／
  args-kwargs 透傳，全過。
- **異動範圍**：`git diff 4ab9f6d..468dc96 --stat` 確認只動 `main.py`+`tests/test_main.py`+
  `debug-tasks.md`，沒碰 `scrapers/chips.py` 本身。

### ✅ #5（4ab9f6d）section 標題標自己的資料日期
- **`_section_date_suffix`/`_latest_data_date` 邏輯正確**：無資料回空字串（不畫蛇添足）；
  跟既有逐列徽章 `_data_date_badge` 是獨立機制，不互相干擾。`_build_section2` 的
  `buy_stocks`/`sell_stocks` 兩個半版**各自獨立**傳入，不共用同一個基準。
- **合成測試** 3 個：整批一致落後時標題有日期＋個股徽章不標（涵蓋原本 🟡 記錄的取捨洞）、
  無資料不標、Section 2 兩半版各自獨立標日期，全過。
- **真實 DB smoke test**（今天兩所剛好同步）：`_build_section2`/`_build_section4` 對真實
  `get_stock_chips_ranking()` 輸出實跑，正確顯示「資料日 07/13」、0 個落後徽章，符合現況
  （無 crash、格式正確）。
- **異動範圍**：只動 `export/chips_generator.py`+測試+`debug-tasks.md`。

### ✅ Task 6（5d7e9cd）Section 8 大戶持倉表格新增 400張/1000張分層欄位
- **HTML 結構正確（真實資料實測）**：真實 `get_shareholder_top(10)` 餵進 `_shareholder_table()`，
  **16 個 `<th>` == 每列 16 個 `<td>`**（前 5 列逐一驗證），`<td><td` 雙重包裹計數 **0**——
  沒有重蹈 Task 5（2026-07-06）那次雙重 `<td>` 的覆轍。
- **`_insider_cell()` 改參數名 `pledge_pct`→`pct` + 新增 `pct_label` 是相容改動**：既有
  `company_shares`/`major_holder_shares` 兩個呼叫點仍用**位置參數**呼叫，行為不變（預設
  `pct_label="質押"`）；新的 lv12/lv15 兩欄呼叫明確傳 `pct_label="持股"`，避免「持股占比」被
  誤標成「質押」字樣。
- **測試**：8 個 shareholder 相關測試全過（含既有防雙重 `<td>` 回歸測試
  `test_shareholder_table_row_td_count_matches_header`）。

### ✅ Task 5（1d9a5e4）main.py sh_rows 組裝 lv12/lv15 六個新 key
- **欄位對應正確**：`row["lv12_shares"]`/`row["lv12_pct"]`/`row["lv12_chg"]`/
  `row["lv15_shares"]`/`row["lv15_pct"]`/`row["lv15_chg"]` 逐一比對
  `get_shareholder_top()`（`screener/database.py:296-316`）的 SQL SELECT 別名，**完全對得上**，
  沒有拼字或欄位對應錯誤。
- **NULL 處理跟既有 `major_holder_*` 同一套模式**：`pd.notna()` guard 一致，不會有 `nan` 洩漏
  進畫面。

### 🎉 附帶驗證：Task 6 文件記載的「已知限制」現在已解除
- debug-tasks.md 原本記載「`lv12_chg`/`lv15_chg` 目前多數股票仍是 NULL，要等 07-09 那週資料」——
  **這個限制現在已經解除**：今天稍早的 `--backfill-shareholder` 補進 07-03/07-09 後，
  真實 DB 實測 `lv12_chg`/`lv15_chg` **1037/1040 檔有非 NULL 值**（不是 bug 記錄，純附帶確認好消息）。

### 結論
- [x] **4 個 commit 全數驗證通過，可以 push**：#6（重試）、#5（section 日期）、Task 6（分層欄位
  顯示）、Task 5（sh_rows 組裝）。異動範圍都乾淨、無外溢，測試+真實資料雙重驗證。
- 🟡 順帶一提（不阻擋）：`_section_date_suffix` 用的 `cs-date` CSS class 沒有獨立樣式定義
  （只繼承父層 `.cs-title` 的樣式），視覺上可行但不是刻意設計的樣式，Developer 之後想再區分
  「標題文字」跟「日期後綴」的視覺層級可以補一個 `.cs-date{...}` 規則，純美觀、非阻擋。

---

## [2026-07-13] 驗證 - Cody 跑完 `--backfill-shareholder` 後續檢查：發現 2 個問題（1 個資料缺口、1 個歷史離群值污染）

### 背景
Cody 在得知 TDCC 已有 07-03/07-09 新資料、且 06-18 那週漏抓後，自行執行了
`python main.py --backfill-shareholder N`。我對正式 DB 做了跑前跑後檢查。

### ✅ 確認有效的部分
- **07-03（1038 檔）、07-09（1037 檔）成功補進**，`get_shareholder_top()` 現在 1040 檔裡
  **1038 檔有非 NULL 的 `week_chg`**（backfill 前幾乎全 NULL），排行榜資訊量恢復正常。
- backfill 結束會呼叫 `recompute_latest_streak()`，但這個函式**只碰「目前最新一筆」**，不會動到
  中間週；我額外**重跑一次 `recompute_all_history()`** 把新資料 merge 進整表重算（先備份
  `screener_backup_20260713_233933.db`），跑完 LAG 對拍**零不一致**、缺週保護（06-26 仍是
  1037/1037 全 NULL，正確反映 06-18 缺口）、07-03 有 3 檔正確因跳過 06-26 而觸發缺週保護
  （已個別追蹤史料確認）。

### 🔴 問題 1：`--backfill-shareholder N` 沒補到 06-18，缺口依然存在
- 說明：`N` 週回補是「從今天往回數 N 週」，不是「找出 DB 裡缺的那幾週去補」。這次補到
  07-03/07-09 就停了，**06-18（TDCC 真實有這週資料）依然沒進 DB**，06-12→06-26 的 14 天
  缺口沒解決。
- 影響：06-26 那批 1037 檔的 `week_chg` 會持續被缺週防護標成 NULL（正確但資訊量損失），
  直到有人手動指定回補到那週。
- 建議：`--backfill-shareholder 8`（或更大週數，蓋過 06-18）重跑一次；或之後把 `_backfill_shareholder`
  改成偵測 DB 既有缺口、自動抓「缺的那幾週」而非固定往回數 N 週（比較根治，但是較大改動，這次先
  用大週數繞過即可）。

### 🔴 問題 2（新發現）：歷史離群值（2380 / 06-26 / pct=100.0）從未被追溯清除，污染了下一週的 week_chg
- 位置：`shareholder` 表 `2380` 的 `2026-06-26` 那筆，`lv12_15_pct = 100.0`（TDCC 解析異常的
  舊帳，Debugger 6 天前就記錄過）。
- 說明：#2 離群值防護（`_fetch_one_stock` 寫入端擋 `>=99`）**只防未來新抓的資料**，這筆
  100.0 髒值本來就已經在 DB 裡，從沒被追溯清掉。這次 backfill 補進 07-03 後，
  `recompute_all_history()`（有 `pd.isna` guard，但沒有「離群值」guard，只認 NULL/NaN，
  100.0 是合法浮點數不會被擋）拿 07-03（36.4108）減 06-26（100.0）算出
  **`week_chg = -63.5892`、`streak = -1`**——這正是 6 天前記錄過的同一種「假大戶減持」訊號，
  只是這次污染的是 07-03 這一筆（歷史列），不是當時的「最新一筆」。
  實測：全表目前只有這 1 筆 `lv12_15_pct >= 99` 的離群值，也只造成這 1 筆下游污染
  （`ABS(week_chg) > 20` 全表只有這一筆命中）。
- **目前不影響 `get_shareholder_top()` 現況排行**（07-09 才是 2380 的最新一筆，
  值 36.4275、`week_chg=0.0167`，正常），但**任何查 2380 歷史趨勢/連續週變化的地方會看到這筆假
  -63.59%**，且如果之後 TDCC 又停更幾週、07-03 意外變回某段時間的「最新」，這筆髒值就會直接
  上排行。
- **這也附帶證實一個 code 層級的小洞**：`recompute_latest_streak()`（backfill 結束會呼叫）
  完全沒有缺週間隔檢查（不像 `recompute_all_history()` 有 `_MAX_WEEK_GAP_DAYS` guard）。這次
  backfill 過程中我觀察到 2 檔（6236、8291）一度被它拿 14 天前的 06-12 當基準寫出非 NULL
  `week_chg`——**這次剛好因為那 2 檔 06-12→06-26 期間 `lv12_15_pct` 數值沒變，算出 `chg=0.0`
  沒被看穿**，但機制本身是不設防的，換一檔數值有變動的股票踩到同樣情境就會複製 06-26 那個
  「跨 14 天當單週」的舊 bug。（我後續重跑 `recompute_all_history()` 已經覆蓋掉這 2 筆，
  現況是乾淨的，這裡純粹記錄一個沒被現有測試涵蓋的 code 邊界。）
- 建議修法（擇一，我不自己動 code）：
  1. **資料面**：把 06-26 那筆 2380 的 `lv12_15_pct` 手動改成 `NULL`（比照 #2 的處理原則），
     改完重跑一次 `recompute_all_history()`，07-03 那筆 -63.59% 假訊號就會連帶消失。
  2. **程式面**：`recompute_latest_streak()` 補上跟 `recompute_all_history()` 一樣的
     `_MAX_WEEK_GAP_DAYS` 缺週防護（目前兩個函式的 guard 邏輯不對稱，是潛在風險，建議抽共用
     helper 避免以後改一邊忘了改另一邊）。

### 結論
- [ ] **需要處理**：🔴 06-18 缺口建議重跑更大週數的 backfill 補齊；🔴 2380 歷史離群值建議手動
  清成 NULL（我可以直接動手，但這是竄改一筆特定歷史資料，先跟你確認要不要做，做完會再驗證＋記錄）。
- 🟡 `recompute_latest_streak()` 缺 gap guard 是程式面的洞，這次沒有造成實際錯誤資料（現況已被
  後續 `recompute_all_history()` 覆蓋乾淨），建議排進 Developer 待辦，不是本次阻擋項。

---

## [2026-07-13] 執行+驗證 - Task #3：對正式 DB 跑 recompute_all_history()（Cody 授權「你直接幫我跑啊」）

### 為什麼我直接跑（而不是只回報）
CLAUDE.md 例外條款：Cody 明確授權時可以直接修改／執行並 commit，但要留紀錄。這次是資料操作
不是 code 改動，不涉及 commit，但一樣留下發現＋做法＋驗證結果。

### 環境確認（重要）
- 執行機器：桌電，對象是 **master worktree**（`C:\Users\Cody\Desktop\tw-sector-tracker\data\screener.db`，
  137MB，唯一有完整多日資料的正式 DB；debug worktree 沒有這份 DB，只有 `stock_universe.csv`）。
- **意外發現 debug 分支落後 master 2 個 commit**：master 這時已經是 `5d7e9cd`（`25406db` 之後多了
  `1d9a5e4`／`5d7e9cd`，是大戶持倉 Task 5/6 顯示層——`main.py` 組 `sh_rows`、
  `chips_generator.py` Section 8 新增分層欄位）。`git diff 25406db..HEAD --stat` 確認這兩個
  commit **只動 `main.py`/`export/chips_generator.py`/測試**，沒碰 `scrapers/shareholder.py`／
  `screener/database.py`，不影響這次要跑的 `recompute_all_history()`，可以放心執行。
  （這兩個 commit 之後要記得 merge 回 debug 分支。）

### 做法
1. **先備份**：`shutil.copy2` 複製正式 DB → `data/screener_backup_20260713_221117.db`（137MB，
   保留在 `data/`，gitignored，不會誤 commit）。這是資料異動且不可逆（除非有備份），照風險評估
   標準先留退路。
2. **執行前**先用 `LAG(lv12_15_pct) OVER (PARTITION BY stock_id ORDER BY date)` 對拍全表，量測
   基準狀態。
3. 執行 `from scrapers.shareholder import recompute_all_history; recompute_all_history(db_path='data/screener.db')`
   → 回傳 **7276**（全表列數，符合預期——每一列都會被重算並 UPDATE，包含正常寫 NULL 的邊界列）。
4. 執行後重跑同一組 LAG 對拍 + 額外邊界檢查，並用 `ATTACH` 備份檔逐列 diff 找出實際改變的列。

### 🔍 意外發現：資料其實已經是乾淨的（零差異）
- **對拍結果**：`mismatch(post-recompute, non-gap rows) = 0`、`gap rows wrongly non-null = 0`、
  `first-week rows wrongly non-null = 0`。
- **備份 vs 執行後逐列 diff：0 列改變**（`ATTACH` 兩份 db 用 stock_id+date 對照 week_chg，
  完全找不到任何差異列）。
- **結論**：這份正式 DB 的 `week_chg`/`streak` 在我執行前**就已經是乾淨狀態**，`recompute_all_history()`
  這次是空跑（idempotent，重跑安全，但沒有東西可修）。最可能的原因：Developer 稍早在同一台機器上
  已經跑過一次（同機器共用同一份 `data/`）。**Task #3 效果已經達成，只是不是我這次的執行造成的。**

### ✅ 驗證通過（資料現況，非我造成的改變，但確認正確）
- **現有週別**：05-08、05-15、05-22、05-29、06-05、06-12、06-26（共 7276 列，1037-1040 檔/週）。
  **06-19 這週仍缺**（06-12→06-26 隔 14 天），缺週防護（#1）正確生效：06-26 那批 **1037/1037 列
  `week_chg` 全為 NULL**（不是硬算成兩週合併變化）。05-08（首週）**1040/1040 全 NULL**（無前值）。
- **離群值防護（#2）生效**：`get_shareholder_top()` 結果**不含 2380**（`WHERE lv12_15_pct < 99`
  正確排除該筆 100.0 異常值），排行榜不再有假的「大戶減持第一名」。
- **NaN guard（#4）**：全表 `week_chg IS NULL` 共 2078 列，皆對應「首週」或「缺週」兩種合理情境，
  沒有 NaN 混入寫回 DB 的痕跡。

### 🟡 提醒（不是 bug，是現況觀察）
- 因為**最新一週（06-26）本身被缺週防護判定為 NULL**，`get_shareholder_top()` 現在絕大多數股票
  的 `week_chg` 都是 NULL（例如 Top 10 現況清單裡，除了少數本來就有效的幾檔，其餘全是「─」）。
  這是**正確行為**（不該編造 14 天的假單週變化），但意味著「大戶連增/連減排行」目前資訊量會偏少，
  直到下一批（07 開頭）TDCC 資料進來、且與 06-26 間隔正常（≤10 天）才會恢復正常顯示。這不是這次
  改動造成的新問題，是 TDCC 06-19 那週本來就沒發布資料的直接後果，僅供你知悉。

### 結論
- [x] Task #3 完成——正式 DB 已確認乾淨（缺週/離群值/NaN 三個防護皆生效、LAG 對拍零不一致）。
  已備份 `data/screener_backup_20260713_221117.db` 供必要時回復。
- [ ] 待辦：master 領先 debug 2 個 commit（Task 5/6 顯示層），下次工作流自檢時記得 `git merge master`。

---

## [2026-07-13] 驗證 - 大戶持倉 Task 4 NaN guard 收尾(25406db) ✅ 三項全過

### 驗證方式
讀 `scrapers/shareholder.py::recompute_all_history()`/`_add_week_change_streak()` 實作、
`tests/test_shareholder.py::_make_table` 與 `screener/database.py` 正式 schema 逐欄比對、
`git diff 408cc0d 25406db --stat` 確認改動範圍。全專案 `pytest -q`：**179 passed, 1 failed**
（失敗是既有已知限制 `test_scan_patterns_returns_list` 缺本機 `data/screener.db`，非本次改動造成）。

### ✅ 驗證通過（對照 debug-tasks.md「請 Debugger 驗證」三項）
- **`pd.isna` 修法邏輯正確**（`recompute_all_history` 第 357 行單一 `if` 涵蓋四種情況）：
  - W1（無前值，`prev_pct is None`）→ `chg=None, streak=0` ✅
  - W2（當週自己 NULL，`pd.isna(cur_pct)`）→ `chg=None`；`prev_pct=cur_pct`（NaN）往後傳一筆 ✅
  - W3（前筆 NULL，`pd.isna(prev_pct)`，即 W2 遺留下來的 NaN）→ 同樣 `chg=None`；但這筆結束後
    `prev_pct` 被設回**這筆自己的（通常正常的）值** → 第 3 筆起自動恢復，與 debug-tasks.md
    記載的「只汙染 2 筆、不會一路傳染」實測結果一致（追蹤 `prev_pct=cur_pct` 這行證實）。
  - `_add_week_change_streak()`（第 261 行）同一組 guard 邏輯，`streak` NULL 時走
    `int(prev["streak"]) if not pd.isna(...) else 0`，不會 `int(NaN)` crash。
- **`_make_table` schema 補齊後與正式 schema逐欄相符**：對照
  `screener/database.py:69-81`（`CREATE TABLE shareholder`）12 欄，`tests/test_shareholder.py:26-32`
  欄名/型別/順序**完全一致**；`save_to_db()` 的 `INSERT INTO shareholder (...) SELECT ... FROM df`
  明列 12 個欄位名（非位置式），不會因欄序被 ALTER 過而錯位。既有測試沒被牽連
  （179 passed，唯一失敗與此無關）。
- **未涉及上市/上櫃資料源**：`git diff 408cc0d 25406db --stat` 顯示異動檔案只有
  `scrapers/shareholder.py`、`screener/database.py`（新增 `get_shareholder_top()` 一行
  `WHERE latest.lv12_15_pct < 99` 離群值過濾）、測試檔、`debug-tasks.md`——未碰
  `scrapers/twse.py`/`scrapers/tpex.py`，純集保衍生欄位計算。

### 結論
- [x] 可以繼續下一個任務——Task 4 收尾邏輯、schema 對齊、資料源範圍三項全部驗證通過。
- 下一步是 Cody 執行 Task #3：對正式 `data/screener.db` 跑 `recompute_all_history()` 修全表
  66% 損毀的 `week_chg`（Debugger/Developer 這台都沒有正式多日資料庫，不能代跑）。

---

## [2026-07-13] 驗證 - data_date 修復(bd11c2b) ✅ 三項全過 + 🟡 取捨的洞（整批一致落後仍會謊報）

### 驗證方式
筆電 master worktree 真實資料（今天天然就是跨日情境：`margin` 表 7/09 只有 TPEx、
TWSE 停在 7/08）。後端實跑 `get_stock_chips_ranking()` 並**對照 DB 真值**，前端直接呼叫
`_margin_alert_table()` / `_stock_rank_table()` 檢查渲染出來的徽章（沒跑 `main.py`，避免自動 push）。

### ✅ 驗證通過（Developer 列的三項）
- **跨日情境標示正確**：融資警示 49 檔中，**32 檔（全 TWSE、07-08）標了「📅07/08」徽章，
  17 檔（TPEx、07-09）乾淨無徽章**——用 regex 抽出實際渲染的徽章股號集合，與「應標集合」
  **完全相符**。外資買超榜兩邊都是 07-09（同日）→ **0 個徽章**，正確。
- **`data_date` 是純日期字串**：`repr` = `'2026-07-08'`、type=`str`、長度 10；
  外資榜＋融資榜合計 **0 筆**含 `00:00:00`。
- **沒影響其他表**：`_data_date_badge` 只在 `_stock_rank_table`（第 204 行）與
  `_margin_alert_table`（第 307 行）兩處被呼叫；Section 6 走 `_inst_strong_table`/`inst_scan`，
  不吃 `stock_chips`，未被波及。
- **關鍵陷阱已避開（我特別查的）**：`inst_df` 和 `margin_df` 現在都有 `date` 欄，若兩者 merge
  會產生 `date_x`/`date_y`，`margin_alerts` 就可能標成**法人的日期**而非融資的日期（那會是
  「假的誠實標示」，比不標更糟）。實測對照 DB 每檔真實 `max(margin.date)`：**49 / 49 全部相符、
  0 筆不符** → 沒有混淆，標的確實是融資自己的日期。
- 全專案 `pytest`：**175 passed**（171 + 4 個新測試）。

### 🟡 建議改善（回應 Developer 點名要 review 的「設計取捨」）
- **取捨的洞是真的會咬人，建議下一輪補**：徽章基準是 section-relative（該表自己最新日），
  所以「整個 margin 區塊一致地落後 headline 一天」時，**區塊內同日 → 一個徽章都不標**，
  但 headline `chips_date` 仍標較新的那天 → **原本那個 🔴（把前一天的數字謊報成同一天）
  以「整批版」原封不動地留著**，而且更難察覺（連一個徽章都沒有）。
  實測（把 49 檔 `data_date` 全設成 07-08，模擬 TPEx 那天也沒發布）：
  → 融資表徽章數 **0**，headline 仍是 `2026-07-09`。
  **這情境很可能發生**：今天 `margin` 表 7/09 就已經只剩 TPEx（TWSE 整批缺）；哪天 TPEx 也沒
  發布，就會兩所一起停在 7/08 → 整批落後 → 完全無示警。
  建議修法：**每個 section 的標題旁標該區塊自己的資料日期**（例如「融資擴張警示 · 資料日 07/08」），
  個股徽章維持現狀處理區塊內混日。這樣「區塊內混日」和「整區塊落後」兩種情況都被涵蓋，
  也不需要動 headline 的語意、不會有 Developer 擔心的那種誤判。

### 結論
- [x] 可以繼續下一個任務（三項驗證全過，**可以 push**）
- 🟡 那個洞是既有取捨、不是這次改壞的，不擋 push；但它是原 🔴 的殘餘，建議排進下一輪。

---

## [2026-07-13] 驗證 - 死碼清理(b670a90) ✅ + 籌碼面 5 個 🔴 端到端 ✅ + 新發現 1 個 🔴（融資跨交易日混用）

### 驗證方式
在**筆電的 master worktree**（`Desktop/tw-sector-tracker`，有完整多日真實資料）實跑
`python main.py`（14:03，盤後）走完整流程 → 產出 docs/*.html → 再實跑各籌碼函式核對數字。
（更正舊認知：Debugger 這台**做得了**真實資料端到端驗證，不必等桌電，見上一則報告。）

### ✅ 驗證通過 — 死碼清理（commit b670a90）
- 全專案 `python -m pytest -q`：**171 passed**。
- `import scrapers.chips` OK、`import main` OK（實際走匯入鏈，不只靜態掃描）。
- 刪除物確認：`FINMIND_URL`、`fetch_margin()`、`fetch_margin_all_today()` 三個都不見了；
  官方版 `fetch_margin_all_twse` / `fetch_margin_all_tpex` 都還在。
- **`FINMIND_TOKEN` 沒被誤刪**：仍在 `scrapers/chips.py`，`main.py:210` 與 `main.py:320`
  的 `from scrapers.chips import FINMIND_TOKEN` 正常運作。
- 全專案零殘留引用（`scrapers/backfill.py:31` 有自己**獨立定義**的 `FINMIND_URL`，
  不是 import chips 的，不受影響）。
- → **可以 push 到 origin**。

### ✅ 驗證通過 — 籌碼面 5 個 🔴 端到端（真實資料，且今天天然重現了 skew 情境）
今天 log 剛好就是要驗的跨表不同步情境：TWSE 法人/融資今日未發布→回退 7/10 也是
「沒有符合條件的資料」；TPEx 停在 7/09。四項逐一對照：
- **#1 漏股（per-stock lookback）**：法人篩選 **2263 檔**，股號首碼 0～9 **全部都在**，
  最高號 **9962**，4000–8999 區間 **968 檔** → 高號 TPEx 股完整回來，沒被舊的全域 LIMIT 截掉。
- **#3 跨表 skew**：`margin_alerts` **49 檔**，`margin_balance`/`margin_change` 都有值非零
  → 在真實 skew 下**沒有整批消失**（修復前綁單一 `MAX(institutional)` 會漏光）。
- **#5 meta margin 歸零**：41 個 META 的 `margin_balance_today` 全部有值
  （min=6、max=152474）→ **沒有歸零**。`partial_coverage=True` 有正確標記。
- **#4 NaN close**：`foreign_top_buy`/`sell` 10/10、`margin_alerts` 49/49 的 `close` 全非空，
  無 `int(nan)` crash，`docs/chips.html` 正常產出。
- **#2 假融資訊號**：49 檔的 `alert_pct` 介於 5.19～60.32、`margin_change` 6～7230，
  **零個離群值**（無 `|change| > 100萬`、無 `balance <= 0`）→ 沒有 0 相減造出來的假「融資大減」。

### 🔴 數據問題（新發現，修 #3/#5 的副作用）

- 問題：**「融資擴張警示」混用兩個交易日的資料，畫面卻只標一個日期**
  位置：`processors/performance.py::get_stock_chips_ranking`（per-stock `QUALIFY ROW_NUMBER()=1`）
  重現方式：今天（2026-07-13 盤後）實跑即可重現。
  說明：修 #3 把 margin 查詢改成「每檔各取自己最新一筆」，解決了漏股，但當兩個交易所
  進度不同時會**靜默混用不同交易日**。實測今天的 49 檔警示：
  - **32 檔上市（TWSE）用的是 2026-07-08 的融資資料**
  - **17 檔上櫃（TPEx）用的是 2026-07-09 的融資資料**
  - **但畫面 `chips_date` 統一標示 `2026-07-09`** → 上市股的數字其實是前一天的。
  例：`4904 遠傳`（榜首，alert_pct 60.32%）的 `margin_balance=882 / margin_change=532`
  實際是 **7/08** 的數字，卻被呈現成 7/09。
  根因：`margin` 表 7/09 **完全沒有 TWSE 資料**（只有 TPEx 489 檔，當天 TWSE 端抓取失敗）。
  危害：使用者以為看到的是同一天的全市場融資變化排行，實際上是**兩個日期混排**，
  跨日期比大小不公平，且「今日融資暴增」可能是昨日的事。這比漏股更難察覺（不會報錯）。
  建議修法：`chips_date` 不該是單一值——至少按交易所分別標示（TWSE: 7/08、TPEx: 7/09），
  或每一列帶自己的資料日期；或只納入「該交易所最新日期」那批並在 UI 標明落後。

### 🟡 建議改善
- **TWSE/TPEx 籌碼抓取經常單邊失敗**，兩邊長期不同步（不是本次修復造成，但它是上面 🔴 的根因）：
  - `institutional`：7/07、7/08 **TPEx 完全缺**（只有 TWSE 509 檔）
  - `margin`：7/09 **TWSE 完全缺**（只有 TPEx 489 檔）
  - 其餘日子兩邊都有（各 ~500）。建議：單邊抓取失敗時要能重試/補抓，否則 per-stock
    取最新的策略會一直產生上面那種跨日混用。

### 結論
- [x] 需要修改後再確認（新的 🔴 融資跨交易日混用）
- 死碼清理 ✅ 可 push；籌碼面 5 個 🔴 修復 ✅ 全部生效，舊帳可結案。

---

## [2026-07-13] 報告 - 大戶持倉（Task 4 前置調查）：week_chg 全表 66% 損毀、髒值上榜、缺週未防護

### 驗證方式（重要：筆電也做得了端到端驗證）
之前以為「debug 機只有單日資料、端到端要等桌電」——**這是誤解**。同一台筆電的 master worktree
`C:\Users\codyliu\Desktop\tw-sector-tracker\data\screener.db` **有完整多日資料**（shareholder
7128 列 / 1040 檔 / 2026-05-08～07-03），以下全部是對這個真實 DB（read-only）+ 實跑
`screener.database.get_shareholder_top()` 得到的結果，不是推論。
（debug 資料夾自己的 `data/screener.db` schema 較舊，連 `lv12_15_shares` 欄都還沒有。）

### 🔴 數據問題（需立刻修）

- 問題 #1：**`week_chg` 全表約 66% 損毀（4707 / 7128 列），生產畫面現在就在用**
  位置：`shareholder` 表歷史資料（成因不在現行程式碼，是過去某次批次運算覆蓋）
  說明：以 `LAG(lv12_15_pct)` 重算比對，**3724 列**的 `week_chg` ≠ 與前一週的實際差；
  另外 5/08 是**第一週、根本沒有前一週可比，卻有 983 列有非 NULL 的 `week_chg`**（憑空的值）。
  逐週損毀率：5/15 917/1010、5/22 933/1014、5/29 937/1019、6/05 935/1026（≈92%）。
  只有最新的 7/03 那批（1038 列）是乾淨的。
  ⚠️ 修正 `debug-tasks.md` 的成因描述：「自己的 pct − 100.0」**只有 4 筆**（全是 2380 自己），
  解釋不了那 3724 筆。我反推過基準（`pct − week_chg`），也不是 first/last/self week，
  真正兇手不在現行程式碼裡（`_add_week_change_streak` 邏輯本身是對的）。考古兇手意義不大，
  重點是 `recompute_all_history()` 能重算回來——但**別急著跑，先看 #3**。

- 問題 #2：**2380（虹光）的髒值已經是「大戶減持排行」榜首，而且是假的**
  位置：`shareholder` 表 2380 / 2026-06-26，`lv12_15_pct = 100.0`
  說明：`get_shareholder_top()` 實跑，2380 以 `week_chg = -63.5892` 排減持第 1 名，
  第 2 名（8112）只有 -5.52 —— 差一個量級，明顯離群。根源是 6/26 那筆 `lv12_15_pct = 100.0`
  （大戶持股 100%，不可能，TDCC 該週解析異常）。全表 `pct >= 99 或 <= 0` 的離群值就這 1 筆。
  **`get_shareholder_top()`（`screener/database.py:292`）沒有任何離群值過濾**，髒值直接上榜。

- 問題 #3：**缺 6/12、6/19 兩週，`week_chg` 混著「1 週」和「4 週」的變化，畫面一律當週變化**
  位置：`scrapers/shareholder.py::recompute_all_history()`、`screener/database.py::get_shareholder_top()`
  說明：TDCC 週別序列是 5/08→5/15→5/22→5/29→6/05→**(缺 6/12、6/19)**→6/26→7/03。
  且 6/26 那批只有 1006 檔、7/03 有 1038 檔，兩批**股票集合不同**——實跑 `get_shareholder_top()`
  可看到 `prev_date` 每檔不一樣（2380 是 6/26，但 8112/3152/6741/3003/3413 都是 **6/05**，
  等於拿 4 週前當「上週」）。`week_chg`／`share_chg` 都沒有做日期間隔檢查。
  🚩 **這代表 `recompute_all_history()` 現在跑下去，會把「跨 3 週的累積變化」寫成 6/26 的
  `week_chg`，把問題從「部分損毀」固化成「全表都有、但語意錯」**——比現況更難察覺
  （現在 6/26 的 chg 有 1002/1006 是 NULL，反而還算誠實）。
  建議：`recompute_all_history()` 與 `get_shareholder_top()` 都要用 `date - prev_date` 判斷，
  超過一週（例如 > 10 天）就寫 NULL / 不出訊號，而不是硬算成「本週變化」。

- 問題 #4：**`share_chg` / `lv12_chg` / `lv15_chg` 目前 1040 檔全部是 NULL（畫面整欄空白）**
  位置：`screener/database.py:292` `get_shareholder_top()`（`latest.xxx_shares - prev.xxx_shares`）
  說明：`lv12_15_shares` 只有最新的 7/03 那批（1038 列）有值，其餘 6090 列全是 NULL
  （Task 1/2 之前沒寫入這欄）。相減時 prev 是 NULL → 三個 `_chg` 欄全 NULL。這應該就是 Cody
  一開始回報「大戶持倉數字看起來不對」的直接來源之一。**純程式碼修不好，要等下一批 TDCC
  資料（或 backfill 補寫 shares 欄）才會有值**——Task 5/6 把這幾欄搬上畫面前要注意這件事。

### 🟡 建議改善

- **Task 4 的 NaN guard（Developer code review 提的那個 Important）：問題屬實，但嚴重度被高估**
  位置：`scrapers/shareholder.py::recompute_all_history()` 第 334-343 行
  我用臨時 DB 實測（中段塞一筆 `lv12_15_pct = NULL`，前後正常）：
  - 實際汙染 **2 筆**（NULL 那筆 + 下一筆的 `week_chg` 都變 NaN），第 3 筆起自動恢復正常。
    **不是** `debug-tasks.md` 寫的「一路往後傳染、該股後續所有週永遠算不出來」——因為
    `_streak_step(NaN, ...)` 兩個比較都是 False，回 0，不會傳出怪值。
  - 但**核心危害成立**：寫進 DB 的是 **NaN 而不是 NULL**，下游 `WHERE week_chg IS NULL` 抓不到。
  - **且目前真實 DB 裡 `lv12_15_pct` 的 NULL 數 = 0**（`_fetch_one_stock` 在 `total_shares == 0`
    時回 None、整筆跳過，正常抓取路徑產不出 NULL）→ **這個 guard 現在不會觸發，是純 defensive**。
    優先度應該低於上面 4 個 🔴。（但如果之後照 #2 建議把 100.0 這種髒值改寫成 NULL，它就會觸發，
    所以還是要修，只是順序在後。）
- **同一個 NaN 洞也在寫入路徑**：`_add_week_change_streak()` 第 251-252 行同樣沒防 NaN
  （每次 `--update-shareholder` 都會跑，比一次性工具常觸發）。另外第 252 行
  `int(prev.get("streak", 0))`：`prev` 是 pandas Series，key 存在時 default 不生效，若 `streak`
  是 NULL 會變成 `int(NaN)` → `ValueError` crash。目前 DB `streak` 沒有 NULL（不觸發），但
  要修 NaN 就一起修。

### ✅ 驗證通過
- 全專案 `python -m pytest -q`：**171 passed**（含以前因缺 `data/screener.db` 會失敗的那個，現在也過）。
- Task 1/2/3 的成果在真實 DB 可見：7/03 那批 1038 列的 `lv12_15_shares` 已正確寫入、
  `week_chg` 零損毀 → 新資料流是對的，問題都在歷史資料與缺週防護。
- 工作流自檢：乾淨 FF merge、`CLAUDE.md` 未被追蹤（Developer 的 `9a3202a` 已 revert 掉那次失誤）。

### 結論
- [x] 需要修改後再確認
- Task 4 **先別對真實 DB 跑 `recompute_all_history()`**：不是因為 NaN guard（那個不會觸發），
  而是因為 **#3 缺週**——現在跑會把跨 3 週變化固化成「本週變化」。
- 建議順序：**#3 缺週防護 → #2 離群值防護 → 才跑 recompute 修 #1 → #4 等資料 → 最後補 NaN guard**。

---

## [2026-07-12] 驗證＋修復 - 大盤分級儀表板 pre-review 兩個 🔴 風險點 + 額外發現中信金無資料

### 驗證方式
- 讀 `docs/superpowers/specs/2026-07-09-momentum-notes-scan-mapping.md` 附錄裡 Debugger
  自己稍早寫下、尚未驗證的兩個 🔴 pre-review 風險點
- 讀 `processors/performance.py::calc_capital_concentration()`/`calc_market_breadth()`
  程式碼邏輯，並用真實 `data/screener.db`（2026-07-09 資料）實跑交叉比對

### ✅ 驗證通過（原本擔心的兩個 🔴 風險點）
- **風險 #1（非權值股母體要排除權值股本身）**：`calc_capital_concentration()` 用
  `broad_pct = df[~is_hw]["change_pct"]`（`~is_hw` 明確排除），不是用全 universe。實測
  `overlap check`（broad 集合是否含任何權值股 id）結果為 `False`，確認兩籃互斥，沒有稀釋
  問題。
- **風險 #4（change_pct 的 NaN/NULL 污染）**：`calc_market_breadth()`／
  `calc_capital_concentration()` 都有 `pd.to_numeric(errors="coerce")` + `dropna`，NaN
  在算平均前就被濾掉，不會污染結果。

### 🔴 驗證過程中額外發現的問題（已修）
`config.TAIEX_HEAVYWEIGHTS` 清單裡的 `2891`（中信金）在 `daily_prices` 表**從未有任何一筆
資料**（`SELECT COUNT(*) FROM daily_prices WHERE stock_id='2891'` = 0，不是單日缺漏）。
根因：`stock_universe.csv`（族群追蹤名單）從未收錄金融股，`main.py` 每日抓價的股票清單來源
就是這份 CSV，`2891` 永遠不會被抓到。導致權值股籃「清單寫 10 檔、實際只有 9 檔生效」。

**已修**：直接移除 `2891`（不替換成別支股票，避免又要重新判斷替代股是否合理，見
`config.py` 新註解）。清單改成 9 檔，實測全部都能在 `daily_prices` 找到對應資料
（9/9 matched）。全專案 171 個測試過（本次改動不需要新增測試，`grep` 確認沒有任何地方硬
編碼假設清單長度是 10）。

這也順帶解決了 2026-07-09 debug-tasks.md 記錄過的「金融股該不該留」懸案——原本以為是哲學
問題（風險逃難所邏輯跟成長權值相反），實際上是更根本的技術問題（從未被追蹤、不可能有資
料），移除是唯一正確答案，不用再等 Cody 就邏輯面拍板。

### 結論
- [x] 可以繼續下一個任務——原本擔心的兩個高風險點確認程式碼寫對了；額外發現的第三個問題
  （中信金無資料）已經修復並驗證

---

## [2026-07-09] 修復 - 籌碼面 review 的 5 個 🔴（Cody 授權「你改吧」，Developer 忙別的）

### 改了什麼（對應下方 review 的 🔴 #1-#5）
- **#1 `screener/institutional.py:128-135`**：全域 `LIMIT lookback*2000` → 改 per-stock
  `QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) <= lookback`。
  高號股不再被低號股吃光配額截掉。
- **#2 `scrapers/chips.py`**：新增 `_parse_num_opt()`（解析失敗回 None，非 0）；TWSE/TPEx 兩個
  margin fetch 的餘額欄改用它，任一 None 就 `continue` 跳列——不再用 0 相減造假的「融資大減」。
  `_parse_num`（買賣超等 0 合法欄位）維持回 0。順帶：原本那個永遠不觸發的 `except ...ValueError`
  死 except 改成靠 None 判斷（真的有作用了）。
- **#3+#4 `processors/performance.py::get_stock_chips_ranking`**：institutional/margin/price 三個
  查詢都改 per-stock `QUALIFY ROW_NUMBER()=1`（不再綁單一 `MAX(institutional)`）→ margin 落後/
  交易所不同步時不再漏；price_map 建構加 `astype(object).where(notna, None)` 洗 NaN。
- **#4（防禦）`export/chips_generator.py::_price_cell`**：`if close is None` → 加 `or (isinstance
  float and close != close)` 一起擋 NaN（涵蓋所有 caller）。
- **#5 `processors/performance.py::calc_meta_chips_signals:610`**：margin 的 today 從綁 institutional
  的 `today` 改成 margin 自己的 `margin_merged["date"].max()` → 跨表落後時 margin 數字不再歸零。

### 驗證（新增 7 個回歸測試，全專案 155 passed）
- `tests/test_institutional.py`：`does_not_drop_high_number_stocks`（3000 檔 × 3 天，lookback=1，
  舊版只會有 ~667 檔、最高號 3999 消失；修正後 3000 檔全入選）。
- `tests/test_chips.py`（新檔）：`_parse_num` 回 0 / `_parse_num_opt` 回 None / 餘額失敗跳列不造
  假訊號（反面證明舊寫法會寫出 -1,000,000 假融資大減）。
- `tests/test_processors.py`：margin 落後一天 meta 不歸零（#5）；ranking margin 警示撐過 margin
  lag（#3）；ranking NULL close 洗成 None 不 NaN（#4）。
- **過程中測試幫我抓到 #4 第一版修法無效**：`float 欄位.where(notna, None)` 不會真的換成 None
  （NaN 留著），要先 `astype(object)`——已修正並實測 `_price_cell(nan)` 不 crash、回「─」。
- 行為實測：#1 高號股全入選、#4 NaN→None + `_price_cell(None/nan)` 都回「─」不 crash。

### 資料來源相關
- 不適用抓取口徑變動——#2 是「餘額解析失敗別造假訊號」的防呆，TWSE/TPEx margin 欄位對應沒變。

### 沒動的部分（🟡 #6-#10 留著）
- #6 insider 位置式 INSERT、#7 shareholder 首呼叫未包 try、#8 格式跳掉回全 0、#9 `_fmt_net` floor
  不對稱、#10 skew 四處各修+死碼/重複——都是潛在風險/顯示/整潔，非立即會給錯數字，這輪先不動。
  其中 #10 的「抽共用 per-stock fallback helper」是根治方向，但那是較大重構，另開。

---

## [2026-07-09] Code Review（high effort）- 籌碼面 code 全面 review

範圍：`scrapers/chips.py`、`shareholder.py`、`insider_holdings.py`、`screener/institutional.py`、
`screener/database.py`、`processors/performance.py`、`export/chips_generator.py`、`screener/patterns.py`。
方法：8 角度 finder agents 平行掃 + 逐項讀真實 code 驗證（非臆測）。**只回報不修**（照 Debugger 角色，
除非 Cody 授權）。以下每項都已讀原始碼確認。

### 🔴 數據問題（需修，會給錯數字/漏資料/頁面停更）

**1. `scan_institutional` 隨歷史累積會漸進式「漏掉高號股票」**
- 位置：`screener/institutional.py:129-135`（`ORDER BY stock_id, date DESC LIMIT {lookback*2000}`）
- 說明：這個 LIMIT 是**全域列數上限**、不是 per-stock；`ORDER BY stock_id` 讓低號股先吃滿配額，
  高號股（大量 TPEx 4xxx–8xxx、高號 TWSE）整批被截掉，`inst_df` 根本沒有它們 → 從法人篩選 /
  Section 6 / composite_score 全部消失。
- 重現：institutional ≈1800 股 × 60 天 ≈108k 列，main.py 用 `lookback=40`→LIMIT 80000，
  低號 ~1333 檔就吃光配額，其餘全漏。**隨每日累積、歷史越長漏越多**，今天快速看不一定發現。
  違反 CLAUDE.md 資料完整性「有沒有股票被遺漏」。
- 修法：改 `WHERE date >= <lookback 天前>` 或 `QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id
  ORDER BY date DESC) <= lookback`（per-stock 窗，跟 get_chips_today 同慣例）。

**2. `_parse_num` 解析失敗吞成 0 → 製造假的「融資大減」訊號**
- 位置：`scrapers/chips.py:41`（`_parse_num` 任何 ValueError 回 0）配 `fetch_margin_all_twse:183-184`
  的 `margin_change = margin_bal − prev_margin`。
- 說明：若某天 `margin_bal` 那格格式跳掉（`'--'`、footnote 標記、全形數字），`_parse_num` 回 0、
  `prev_margin` 正常解析 → `margin_change = −prev_margin` = **假的巨額融資大減**，且**無任何 log**。
  正是「不報錯但給錯數字」最危險那類。
- 修法：`_parse_num` 無法解析時回 `None`（或拋例外讓上層判斷），不要靜默回 0 讓它流進相減。

**3. `get_stock_chips_ranking` — margin/inst 綁單一 MAX(institutional date)，落後的交易所/margin 靜默消失**
- 位置：`processors/performance.py:441-453`（`latest_date=MAX institutional`，margin/inst 都
  `WHERE date=latest_date`；注意 price 有 fallback、**margin 沒有**）。
- 說明：兩個問題疊在同一處——(a) margin 比 institutional 晚一天時 `margin WHERE date=inst_latest`
  回空 → 「融資擴張警示」顯示「無」即使前一日有完整 margin；(b) `WHERE date=MAX` 這種單一錨點，
  TPEx/TWSE 發布日不同步時只留最新那所、漏掉落後交易所的個股。**這正是 `get_chips_today`
  (database.py:246 per-stock fallback)、`scan_institutional`(institutional.py:163 兩日 anchor)
  已經修過的同類 skew，這裡是唯一還用單一 MAX 的漏網。**
- 修法：比照 get_chips_today 的 per-stock `date<=` fallback。

**4. `_price_cell` 遇 NaN close → `int(nan)` crash → 整個 chips.html 停更**
- 位置：`export/chips_generator.py:72`（`f"{int(close)}"`，只擋 `close is None` 不擋 NaN），
  資料來自 `get_stock_chips_ranking` 的 `price_map`（`performance.py:474` 直接吃 `daily_prices.close`，
  **沒洗 NaN**）。
- 說明：某檔在該日 `close` 為 NULL（停牌/全額交割）→ DuckDB→pandas 變 `nan`（不是 None）→
  `close is None` 判 False → `int(nan)` 拋 ValueError → **整個 generate_chips_html crash、
  docs/chips.html 不再產出（全頁 stale）**。main.py 的 shareholder 路徑有洗 NaN（625-626），
  但這條路徑沒有。
- 修法：建 price_map 時 `pd.isna` 過濾，或 `_price_cell` 改 `if close is None or pd.isna(close)`。

**5. `calc_meta_chips_signals` — META margin 數字綁 institutional 的 today，跨表落後時全歸零**
- 位置：`processors/performance.py:594`（`today=all_dates[-1]` 只來自 institutional）+ `:611`
  （`today_margin = margin[date==today]`）。
- 說明：整張 margin 表比 institutional 晚一天時 `today_margin` 為空 → 每個 META 的
  `margin_change_today=0`、`margin_balance_today=0`、`margin_alert=False` 全被靜默歸零。
  現有 `partial_coverage` 旗標只管**交易所**覆蓋、管不到**跨表日期**落後，不會示警。
- 修法：margin 的 today 用 margin 自己的 MAX date（跟 institutional 分開），或比照 per-stock fallback。

### 🟡 建議改善（潛在風險 / 顯示 / 整潔）

**6. `insider_holdings.save_to_db` 位置式 INSERT（未明列欄位）— 同 shareholder 修過的錯位風險**
- 位置：`scrapers/insider_holdings.py:247`（`INSERT INTO insider_holdings SELECT col1,col2,...`）。
- 說明：依賴實體欄序。`shareholder.py::save_to_db`（192 行）當初就是因 `lv12_15_shares` 被 ALTER 加
  在最後、位置式會錯位，才改成明列欄位名。這裡是同 bug class 沒比照。目前 schema 對得上不會錯，
  但**日後對 insider_holdings 做任何 ALTER 就會靜默寫錯欄**。建議先明列欄位名防患。

**7. `shareholder.py` 第一次取 available_dates 未包 try、且無擋頁偵測**
- 位置：`scrapers/shareholder.py:125`（`_get_session_tokens()` 在 retry 迴圈**外**）+ `:38`
  （`re.search(...).group(1)`）。
- 說明：第一次 GET 若遇 TDCC 擋頁/改版，`re.search` 回 None → `.group(1)` `AttributeError`，
  **整個 fetch_shareholder_weekly 直接 crash**（迴圈內的呼叫有包 try，這個沒有）。且 shareholder.py
  不像 chips/insider 有 block 偵測，擋頁跟暫時性錯誤混為一談。建議首呼叫也包 try + 加擋頁偵測。

**8. `insider_holdings._parse_response` 格式跳掉時回全 0 record，被當有效資料**
- 位置：`scrapers/insider_holdings.py:93`（`if len(cells)!=9: continue`）+ `:111`（仍回
  `company_shares=0,...`）。
- 說明：MOPS 若把表格改成 10 欄，每列都 `continue`，但因 date 還在，回傳的是「全 0」dict 被當合法
  資料存入 → 靜默清掉全批真實持股，log 還顯示「成功」、`blocked_ids` 空。建議「有 date 但 0 有效列」
  時回 None（視為解析失敗），不要當 0 值資料。

**9. `_fmt_net` floor division 讓買賣超張數不對稱（顯示）**
- 位置：`export/chips_generator.py:85`（`zhang = n // 1000`）。
- 說明：`//` 對負數往 −∞ 取整：`−1500 股→−2 張`（真實 −1.5）、`+1500 股→+1 張`；`±800 股` 分別
  顯示 `−1張 / +0張`。同量買賣張數不一致、易誤讀。純顯示層，改 `int(n/1000)` 或四捨五入對稱即可。

**10. 交易所/跨表 skew 被四處各修一套（altitude）+ streak/顏色/選股正則多份重複（reuse）**
- altitude：同一個「來源發布日不同步、別顯示 stale/partial」的機制，`get_chips_today`（per-stock）、
  `scan_institutional`（兩日 anchor）、`get_stock_chips_ranking`（單一 MAX，見#3）、
  `calc_meta_chips_signals`（單一 today+partial_coverage，見#5）**四種不同實作**，#1/#3/#5 都是這個
  scatter 的症狀。抽一個共用「per-stock latest ≤ date」helper 套到所有消費端，可一次消掉這一類 bug。
- reuse（不阻擋）：`institutional._calc_streak` 又造一份 streak（已有 `streak_utils.calc_streak`）；
  紅漲綠跌 `_net_color` 已存在卻在 `_price_cell/_cum_cell/chg_html/_insider_cell/_chg_cell/_pct_cell`
  等 ~7 處重寫（且中性色 `#64748b`/`#334155` 已不一致）；`^[1-9]\d{3}$` 選股正則在
  `chips_generator._is_stock` 與 `performance.py:486,512` 三處各寫一份。`chips_generator.py` 還有
  `_meta_streak_table`/`_trust_meta_table` 兩個**死碼**（無 caller，section 1/3 改走 inline）。

### 特別注意（已查、不是 bug）
- `_shareholder_table`/`_insider_cell` 的 NaN：main.py（625-659）在進 generator 前已把 NaN 洗成 None，
  這條路徑安全（跟 #4 `get_stock_chips_ranking` 路徑沒洗，不同）。
- 股 vs 張單位：`_fmt_net`/`_insider_cell`/`_shareholder_table` 都正確 ÷1000，margin 全程 張，一致。
- `get_margin_divergence` 有 `close>0`/`margin_balance>0` 過濾，不會踩 #4 的 NaN crash。

### 結論
- [ ] **需要 Developer 修**：🔴 #1（漏股，隨時間惡化）、#2（假融資訊號）、#3/#5（跨表/交易所 skew
  歸零）、#4（NaN crash 停更）五項是真的會給錯數字或漏資料，建議優先。#1 和 #4 最急（一個漸進漏股、
  一個直接頁面停更）。🟡 #6-#10 是潛在風險/顯示/整潔，可排後。
- 我只回報未修（照 Debugger 角色）。要我改哪幾項再跟我說。

---

## [2026-07-09] 驗證 - 大盤分級儀表板 Phase 1（TAIEX + 廣度 + 集中度 + 五級，74e0694/91278de）

### 驗證方式
- `git merge master`（乾淨）；全專案 `pytest`；讀四個核心函式實作；實測 classify 五級邊界；
  **實打真實 TWSE FMTQIK API** 驗 TAIEX 解析（含漲跌點數正負號）、擋頁偵測。

### ✅ 驗證通過
- **全專案測試**：**148 passed**（含 taiex/processors/html_generator 儀表板全部新測試；1 個
  pandas FutureWarning，非錯誤——`test_processors.py:252` 用 `df.loc[len]=[...含NaN]` 觸發，
  不影響結果，Developer 之後可改成先建 df 再 concat 消警告）。
- **我 pre-review 的兩個 🔴 都被正確處理**：
  - **#1 集中度兩籃互斥**：`calc_capital_concentration` 用 `broad_pct = df[~is_hw]`（`~is_hw`
    排除權值股），權值股不會同時進兩籃、落差不被稀釋 ✅。
  - **#4 change_pct NaN 污染**：廣度與集中度都用 `pd.to_numeric(...,errors="coerce").dropna()`
    過濾 NaN；`total` 只算有效股；缺邊回 None、divergence 回 None ✅（且有專門測試
    `test_calc_market_breadth_ignores_nan_change_pct`）。
- **classify_market_regime 五級（實測邊界）**：大漲/小漲/持平/小跌/大跌正常＋含=下上邊界全對；
  **矛盾降級**（指數+2% 但廣度40% → 持平、由集中度診斷說明背離）正確；大跌先於小跌判、方向不會
  互吃；集中度方向（div>0 權值股撐盤 / div<0 中小型輪動 / |div|<2 不標）全對。
- **TAIEX 解析（實打真實 FMTQIK）**：
  - 欄位用**名稱索引**（`fields.index("發行量加權股價指數")` 等），格式改欄序也不會錯位 ✅。
  - **漲跌點數帶正負號**（真實回應實測：`-224.23`、`-1,077.28`、`255.30`），`_to_float` 正確處理
    逗號+負號 → **change_pct 正負不會顛倒**（我特別查這點：若無號會讓五級方向全反）。真實 07-08
    解出 +0.56%、驗算吻合 ✅。
  - **擋頁偵測**：content-type 非 json、stat≠OK、缺欄位 → 一律 `TWSEBlockedError`（實測 HTML 擋頁
    + stat="很抱歉" 都正確擋）✅，不會把擋頁誤當「當月無資料」。
- **上市/上櫃無混用**：只讀 TAIEX 大盤指數 + prices_df.change_pct，不碰個股上市櫃來源 ✅。

### 🟡 建議 / 待處理（非阻擋）
- **門檻未回測**（Developer 已標）：五級切點、集中度 2pt 都是草案。建議桌電 Task 6 跑真實 main.py
  開 index.html，對當天財經新聞的大盤漲跌是否合理；例如 07-07 TAIEX -2.31%（大跌等級），可對一下
  當天廣度是否也弱、分類是否落「大跌」。
- **realtime 語意**（Developer 已標，非 bug）：`--realtime` 盤中廣度來自即時股價、但 TAIEX 走
  FMTQIK 只有盤後 → 盤中會配到昨天的指數。盤後 batch 無此問題。留給 Cody 決定要不要接盤中指數。
- **中信金/金融股是否移出權值籃**：Developer 已標的待討論項，跟資料正確性無關（是策略選擇），
  這次照 0050 前 10。

### 本機驗證限制
- 廣度/集中度我用**函式單元 + 真實 TAIEX API** 驗過邏輯；**真實整頁渲染**（`_market_regime_section`
  配當天完整 prices_df）需桌電有多股資料跑 main.py 目視——這台 daily_prices 只有 07-02 單日。

### 結論
- [x] 可以放行——四個核心函式（TAIEX 解析/廣度/集中度/五級分類）邏輯、邊界、防呆、擋頁全部正確；
  我 pre-review 的兩個 🔴 都收了；148 passed。門檻回測與整頁目視留桌電 Task 6。

---

## [2026-07-08] 驗證 - scan_institutional 兩所發布日不同步修復（anchor 最近兩交易日，1b8bfc3）

### 驗證方式
- `git merge master`（乾淨 FF）；讀 `scan_institutional` 的 anchor_dates 邏輯；全專案 `pytest`；
  合成 temp DB 測 anchor 邊界（同步/差一天/陳舊/單天退化）；真實本機 DB 不 crash。

### ✅ 驗證通過（對照 debug-tasks 最上面那則）
- **全專案測試**：**121 passed, 0 failed**（原 119 + `test_institutional.py` 新 2）。
- **anchor「最近兩交易日」邊界**（合成 temp DB，`anchor_dates = 表裡最近兩個 distinct date`）：
  - 差一天（TWSE 落後）：TW 股最新 07-07 → 落在 anchor{07-07,07-08} 內 → **入選、退到 07-07** ✅
  - 領先（TPEx）：TP 股最新 07-08 → **入選、用 07-08** ✅ → 兩所不同步時**兩邊都不漏**
  - 同步：SYNC 股 07-08 → 入選 ✅（兩所同一天時行為不變）
  - 陳舊/停牌：OLD 股最新 07-03（差 > 2 個交易日、不在 anchor 內）→ **正確排除**，不被陳舊資料
    拉進來 ✅
- **嚴審邊界（我加驗的）——表裡只有一個交易日**：`sorted(unique)[-2:]` 退化成 1 個 anchor，
  **不 crash**、該股正常入選 ✅（新上線第一天/回補第一天不會爆）。
- **真實本機 DB**：`scan_institutional('2026-07-08')`（本機只有 07-01 單日）回 1315 檔、不 crash。

### ⚠️ 本機驗證限制
- 本機 DB 只有單日（07-01），**Section 6 頁面「兩所不同步時同時有 TWSE+TPEx 股」的真實渲染
  重現不了**，也驗不了 Developer 報的「917 全 TPEx → 2246 檔、TWSE 0→509」production 數字。
  但那個 scenario 的**核心資料源邏輯已由上面的合成 anchor 測試精確涵蓋**（TW 退 07-07 + TP 用
  07-08 同時入選）。真實頁面目視留給桌電：跑 main.py 開 chips.html Section 6 確認同時有兩所股票。

### 🟡 觀察（非阻擋，記錄）
- `anchor_dates` 用「表裡最近兩個 distinct date」而非「日曆最近兩交易日」。正常情境（兩所最多差
  一個發布日）完全正確。極端情境：若某天**兩所都沒發布**、資料整體卡在更早（例如最新兩筆是
  07-03/07-04），anchor 會自動跟著那兩天走——這是合理的（就用當時最新的兩天），只是要知道
  anchor 是「資料驅動」不是「日曆驅動」，跟需求一致。
- 這是 institutional 版的 per-stock fallback，跟稍早 `get_chips_today`（margin/9d82a3a）現在對
  「交易所發布日不同步」的處理**一致**了（一個 TPEx 落後、一個 TPEx 領先，兩個方向都修了）。

### 結論
- [x] 可以繼續——anchor 邊界（同步/差一天/陳舊/單天退化）全對、121 passed、真實 DB 不 crash。
  Section 6 兩所同時顯示的真實渲染留給桌電目視（本機單日資料重現不了，邏輯已由合成測試涵蓋）。

---

## [2026-07-08] 驗證 - get_chips_today per-stock fallback（族群頁「─」修復，7acfa7b + 9d82a3a）

### 驗證方式
- `git merge master`（乾淨）；讀 `get_chips_today` 實作；全專案 `pytest`；合成 temp DB 測邊界
  （單側股 + 兩表不同天）；本機真實 DB 測 fallback 不回空。

### ✅ 驗證通過（對照 debug-tasks 兩則的驗證清單）
- **全專案測試**：**119 passed, 0 failed**（Developer master 端記 115；我 debug 分支多了近5/7/10/14
  那批 4 個測試，故 119。get_chips_today fallback 系列 3 個新測試都在、都過）。
- **per-stock fallback 邏輯正確**：`WHERE date <= ? QUALIFY ROW_NUMBER() OVER (PARTITION BY
  stock_id ORDER BY date DESC)=1`，institutional / margin **各自逐股**取 <= today 的最新一筆。
  合成測試實證：C 股 institutional 退 07-07、margin 退 07-05，**兩表各退各的、不因整表最新日
  對不上而漏**。這正是「整表單一 MAX(date) 會漏掉最新日缺席交易所個股」的修復。
- **邊界（FULL OUTER JOIN 不 crash）**：實測 A 股只有 institutional → margin_balance 回 NULL、
  foreign_net=111 保留；B 股只有 margin → foreign_net NULL、margin_balance=222 保留；
  `COALESCE(i.stock_id, m.stock_id)` 讓兩側 key 都不丟。三股都正確回、無例外。
- **真實 DB 不回空**：本機 `get_chips_today('2026-07-09')`（inst/margin 只到 07-01）退到最新可用、
  回 1342 筆（外資 1315、融資 1279），修復前的「嚴格 date=today → 回 0 → 全『─』」不再發生。

### ⚠️ 本機驗證限制
- 本機 DB 只有單日（07-01），**重現不了「TPEx margin 停在跟 TWSE 不同天」的多所真實情境**，
  也驗不了 Developer 報的「TPEx 融資 0→489 支」那個 production 數字。但那個 scenario 已由合成
  測試 `test_get_chips_today_per_stock_fallback_not_table_wide`（2330 退 07-07、6488 退 07-06）
  精確涵蓋，邏輯正確。真實數字目視留給桌電。

### 🟡 提醒（跟 Developer 記的一致，非阻擋）
- 這是**顯示/讀取層**的優雅 fallback，已完整。**根本的「TPEx 融資 07-07 當天為何沒抓到」是獨立的
  抓取端問題**（Developer 說正在做 #3 抓取端）——fallback 讓頁面退到最近一筆，但「當天就有 TPEx
  融資」仍要從抓取端解決。等 Developer #3 做完會再驗。

### 結論
- [x] 可以繼續——per-stock fallback 兩版（7acfa7b 整表→9d82a3a per-stock）驗證通過：邏輯、邊界、
  真實不回空都對。#3 抓取端待 Developer 做完再驗。

---

## [2026-07-08] 實作+嚴審 - index 族群個股表改用 get_rolling_returns（近5/7/10/14日，取代複利週漲跌）

### 做了什麼（Cody 授權「數值呈現在筆電改」，UI 版面回家弄）
- `export/html_generator.py`：`_stock_table`＋`_meta_stock_cards`（兩者渲染同一種可排序表格）把單一
  「週漲跌%」（複利 `_weekly_pct`）欄改成 **近5/7/10/14日** 四欄，資料來自
  `get_rolling_returns()`（收盤價比值法），**跟 chips.html Section 8 同一個算法/函式 → 兩頁一致**。
- 資料傳遞：generate() 新增 `rolling_returns` 參數，於頁面產生前塞進 module 級 `_ROLLING_RETURNS`，
  兩個渲染函式直接讀，**避免把 map 穿過整條 8 層渲染呼叫鏈**（那條 `stock_sparklines` 穿了 8 個
  簽名，硬加參數在 redesign 前風險高）。
- 排序 JS：`sortStockTable` 的 **寫死 `labels` map 同步更新**（`wpct`→近5日，新增 `chg7/chg10/chg14`），
  否則點排序後新欄表頭會變空白（這是隱藏地雷，靜態看不出來）。`data-wpct` 重用成近5日的值
  （modal 不讀它、只有排序讀）。
- `main.py`：算 `get_rolling_returns((5,7,10,14))` 傳進 `generate_html`。
- 測試：`test_html_generator.py` 新增近5/7/10/14 欄位驗證（含 td==th 結構、缺值─）。全專案 **116 passed**。

### 🔍 嚴格自審（我審自己這份實作）
**✅ 通過**
- `_stock_table`／`_meta_stock_cards` **兩處都渲染正確**：11 欄、`<th >` 精確計數 11 == 資料列 11 td、
  無雙重 td；近5/7/10/14 紅漲綠跌、近14缺值→「─」；「無行情」列 colspan 6→9（1代號+1股名+9=11）。
- 「週漲跌%」顯示已完全移除，殘留檢查只剩 sort key 名 `data-key="wpct"`（顯示是「近5日」）與死碼
  docstring。
- **兩頁一致達成**：index 與 chips 都走 `get_rolling_returns`，已更新該函式 docstring（原本寫「index
  尚未接」→ 改為「已接」）。

**🟡 誠實回報**
1. **module 級 `_ROLLING_RETURNS` 是共享可變狀態**：為了不穿 8 層參數而採用，generate() 每次產頁前
   重設。若有人直接呼叫 `_stock_table` 而沒經 generate()，會讀到上次的值或預設 `{}`（→全「─」，安全）。
   屬 code smell，但對「一次性批次產頁」可接受，已加註解說明。redesign 若重整這條鏈可順手改成正規傳參。
2. **`_weekly_pct()` 變成死碼**（已無 caller）。**我沒刪**——怕跟桌電未 commit 的 redesign 進度衝突，
   留給 Developer redesign 時清。
3. **這是動到 redesign 目標檔的可排序表格＋JS**，回家 redesign 版面時很可能重工——Cody 已知分工、
   明確要求先在筆電把數值呈現改掉。
4. **真實數字本機驗不了**（debug DB 只有 1 天 → 全 None）。邏輯用合成資料 + `get_rolling_returns`
   既有單元測試驗過；**建議桌電跑一次開 index.html 目視確認近5/7/10/14 數字合理、11 欄版面沒跑掉、
   點欄位排序正常（尤其新欄表頭排序後不會變空白）**。

### 結論
- [x] 實作 + 自審完成（116 passed）。index 族群個股表近5/7/10/14 上線，與 chips 同算法一致。
- [ ] 桌電目視驗證真實數字 + 排序互動；redesign 時順手清 `_weekly_pct` 死碼、考慮把 `_ROLLING_RETURNS`
  改正規傳參。

---

## [2026-07-08] 調查 - 桌電待辦#3「institutional/margin 落後、外資/投信/融資全 ─」（程式碼側，data/log 待桌電）

### 調查方式
- 本機 DB 重現不了（institutional/margin/daily_prices 都停在 07-01/07-02）。改做程式碼＋設定分析：
  讀顯示層的日期錨定邏輯、查 `config.is_trading_day`。

### 🔴 推翻桌電診斷的兩個前提
1. **顯示層不是「用今天日期去對」**：桌電假設「族群頁用今天去對 institutional/margin，對不到
   07-08 就 ─」。但實際：
   - `performance.py:594` `calc_meta_chips_signals`：`today = all_dates[-1]` = **institutional 自己
     的最新日期**
   - `performance.py:441` `get_stock_chips_ranking`：`latest_date = MAX(date) FROM institutional`
   兩者都錨 institutional 自己的 MAX date（不是日曆今天/daily_prices 日期），且 stock 版對 price
   還有「institutional 日期查無 price → fallback 到 daily_prices MAX date」的保護。**所以「對不到
   07-08 就 ─」跟程式碼不符**——institutional 只要有 07-07 資料，就會用 07-07、不該顯示 ─。
2. **07-07 是交易日，不是「非交易日」**：`config.is_trading_day('2026-07-07')` = **True**（週二、
   非假日）。桌電「07-07 全市場 0 檔 daily_prices → 非交易日」是誤判——真相是 **daily_prices 缺
   07-07 這個交易日（gap）**，institutional/margin 卻有。最可能：**07-07 那天沒跑 main.py**
   （daily_prices 只抓「今天」，沒跑就沒有），07-08 跑時 `fetch_institutional(07-08)` 遇「尚未發布」
   → fallback 抓前一交易日 07-07（`main.py:66`）→ institutional 因此有 07-07。**這組合是正常行為，
   不一定是 bug。**

### 因此「外資/投信/融資全 ─」的真正成因，程式碼側無法定論
若 institutional 的 MAX date（07-07）真有非空資料，上述兩個函式應該會顯示數字、不是 ─。所以 ─
更可能來自：(a) institutional/margin 該日資料其實空/全 NULL（被 `dropna` 清成空 → `return {}`），
或 (b) fetch 當天實際失敗、DB 沒有可用近期資料。**這需要桌電的真實 DB 才能分辨。**

### 🟡 連帶影響我的 get_rolling_returns（已補記 caveat）
`rn` 數的是「DB 裡實際存在的日期」。若 daily_prices 缺某個交易日（像這次 07-07 gap），「N 個交易日
前(rn N+1)」會實際跨到 N+1 個真實交易日 → **近N日多算一天**。屬資料完整性依賴，非 code bug，但
使用者若知道有 gap 要留意。

### 建議桌電查的三件事（確認診斷）
- [ ] `SELECT date, COUNT(*), COUNT(foreign_net) FROM institutional GROUP BY date ORDER BY date DESC LIMIT 5`
  （margin 同）——看 07-07/07-08 那幾天的列數與**非空**值，判斷是「有資料但顯示 bug」還是「資料真的空」。
- [ ] 為什麼 daily_prices 缺 07-07：那天有沒有跑 main.py？（若沒跑就是 gap 來源，補
  `--backfill`/該日重跑即可；若有跑卻沒寫入，才是 daily_prices 抓取 bug）。
- [ ] 跑 07-08 那次的 `logs/run.log`：找「三大法人寫入 N 筆（日期）」「TPEx 三大法人寫入」「融資融券
  寫入」幾行，確認實際寫入的日期與筆數，對照上面 SQL。

### 結論
- [x] 程式碼側分析完成：**顯示錨定是穩健的（用 institutional 自己的 MAX date）**，桌電「用今天對不到
  就 ─」與「07-07 非交易日」兩個前提都不成立。真正成因（資料空 vs 顯示）需桌電 DB/log 才能定論。
- [ ] 待桌電跑上面三個檢查回填，再定位是「資料真的空（抓取問題）」還是別的顯示路徑。

---

## [2026-07-08] 實作+嚴審 - 抽 get_rolling_returns() 共用函式 + Section 8 擴成近5/7/10/14日

### 做了什麼（Cody 授權，收盤價比值法、週期 5/7/10/14、抽共用函式）
- **新增 `screener/database.py::get_rolling_returns(periods=(5,7,10,14))`**：收盤價比值法
  `(最新交易日收盤 / N交易日前收盤 − 1)×100`，rn1 vs rn(N+1)，缺值/NULL/除零回 None，
  回傳 `{stock_id: {5:pct, 7:.., 10:.., 14:..}}`。
- **`main.py`**：移除原本 Section 8 的 inline 滾動 SQL + `_roll_pct`，改呼叫共用函式，sh_rows 帶
  `chg_5d/7d/10d/14d`。
- **`export/chips_generator.py`**：`_shareholder_table` 表頭+列擴成近5/7/10/14日（`_chg_cell` 沿用、
  回完整 `<td>` 不外包）。
- **測試**：`test_database.py` 新增 `get_rolling_returns`（8天算對、資料不足回 None）；
  `test_chips_generator.py` 顯示測試擴成 4 欄。全專案 **115 passed**。

### 🔍 嚴格自審（Cody 要求「做完嚴格 review」——我審自己這份實作）

**✅ 驗證通過**
- **rn 對位安全**：`daily_prices` 有 `PRIMARY KEY (stock_id, date)`，不可能有重複日期把 rn 打亂
  （真實 DB 實查 0 筆重複）——這是滾動計算正確性的關鍵前提，成立。
- **邏輯（合成 8 天 temp DB）**：近5日+10%、近7日+25%、近10/14日 None（不足）；4天股全 None；
  除零/NULL 由 `_ret` 的 `pd.isna` 擋。
- **真實 1 天 DB**：1038 檔全回 None（資料不足，正確）、不 crash。
- **顯示結構**：14 欄 th == 14 td、無雙重 `<td>`（沒重蹈 Task 5 覆轍）、缺值→「─」。
- **main.py 無殘留**：舊 `_roll_pct`/`c0/c5/c7` 引用已清乾淨。

**🟡 審出來的問題（誠實回報，含我自己修正的 overclaim）**
1. **【已修正 docstring】「兩頁一致」目前尚未達成**：這次只把 chips.html Section 8 接上共用函式，
   **index.html 族群個股表還是用複利 `_weekly_pct()`**，我沒改它（綁 index redesign，桌電待辦 1）。
   所以「同一支股票近5日兩頁一致」這個目標**還沒實現**——在 index 改接 `get_rolling_returns` 之前，
   兩頁的近5日仍會有複利捨入的微小差異。原本 docstring 寫「兩頁共用」是 overclaim，已改成誠實描述
   現況（chips 已接 / index 待接）。**這是本次最重要的 caveat。**
2. **連線用 read-write `get_conn()`**（沿用 `get_shareholder_top` 房規）而非原 inline 版的
   `read_only=True`。有 PK、呼叫是循序的，不是 bug，但純讀用 read_only 更保險——屬風格一致 vs
   安全的取捨，暫沿用房規。
3. **下市/停牌股**：rn1 是該股「最後一個有資料的交易日」，可能不是今天；欄位標「近5日」但實際
   終點是它最後成交日。Section 8 只顯示有集保資料的股票，影響很小，記錄備查。

**⚠️ 本機驗證限制（同前幾則）**
- debug 機 `daily_prices` 只有 1 天（2026-07-02），**驗不了真實 production 數字**（如 2330 近5日）。
  邏輯已用合成 8 天資料驗過。**建議桌電（有多日股價）跑一次 `python main.py`、開 chips.html
  Section 8 目視確認近5/7/10/14 數字合理、版面 14 欄沒跑掉。**
- 改進：舊的 inline 滾動 SQL 原本沒 pytest，這次抽成 `get_rolling_returns()` 後**有單元測試鎖行為**了。

### 結論
- [x] 實作完成、自審通過（115 passed）。核心邏輯、防呆、結構都對。
- [ ] **待 Cody/桌電決定**：index.html 何時改接 `get_rolling_returns`（達成真正兩頁一致）——建議跟
  index redesign 一起做。在那之前兩頁近5日有微小差異（已在 docstring 標明）。
- [ ] 真實數字目視驗證留給桌電（本機資料不足）。

---

## [2026-07-08] 整合 - 筆電 Section 8 近5日/近7日 vs 桌電待辦「族群個股表 5/7/10/14」重疊分析

Cody 指出「桌電要改的內容跟筆電討論的相似」——確認屬實，這是**同類指標、不同頁、不同算法**，
整合結論如下（merge origin/master 進 debug 完成，code 無衝突、114 passed）。

### 兩邊在做同一類東西，但落點不同
| | 我（筆電）已做 | 桌電待辦 2 |
|--|--|--|
| 頁面/表格 | `chips.html` Section 8 大戶持倉表 | `index.html` 族群個股表 |
| 欄位 | 近5日、近7日 | 5/7/10/14 天 |
| 算法 | **收盤價比值**：`(close_rn1 − close_rnN+1)/close_rnN+1`（daily_prices 直接算）| **複利**：`_weekly_pct()` 把最近5個 `change_pct` 連乘（`html_generator.py:140`）|
- **我的 Section 8 work 不會自動滿足桌電待辦**（不同頁），但兩者是平行的同類需求。

### 🟡 一致性風險：兩種算法數字會微幅對不上
- `_weekly_pct` 複利的是**已四捨五入的 `change_pct`**（存 2 位小數），連乘 5 天會累積捨入漂移；
  我的收盤價比值沒有這個漂移。數學上等價、實際會差 0.0x～0.x%（桌電自己驗 8261：複利手算
  +26.41% vs 頁面 +26.44%）。
- **若兩頁都要顯示「近N日」，同一支股票會出現兩個略不同的數字**，使用者可能會注意到。

### 建議整合方向（統一算法 + 共用函式）
1. **統一用「收盤價比值」一種算法**（比複利乾淨、精確，且沒有 `calc_stock_sparklines(lookback=11)`
   撐不到 14 天的限制——桌電待辦 2 有記到這個卡點）。
2. **抽成共用函式** `screener/database.py::get_rolling_returns(periods=[5,7,10,14])`，兩頁都用同一個，
   數字保證一致。我 Section 8 現在的 inline SQL 順勢抽進去（本來 bug-reports 就建議抽出補測試）。
3. **週期取一組**：我做了 5/7，桌電要 5/7/10/14——建議統一成 5/7/10/14（涵蓋我的）。
4. index UI 重設計（桌電待辦 1）若要一起做，這 4 欄可等 redesign 再排版；但**算法/共用函式可以先落地**，
   不受版面決策影響。

### 需 Cody 拍板
- [ ] 統一算法採「收盤價比值」？（建議 yes）
- [ ] 週期統一成 **5/7/10/14**？（涵蓋我已做的 5/7）
- [ ] 是否要我把 Section 8 的 inline SQL 抽成 `get_rolling_returns()` 共用函式（index 之後接同一個）？

### 另兩項桌電待辦（跟累積漲跌無關，只記錄）
- index UI 重設計：mockup 已認可、尚未動手（`export/html_generator.py`）。
- institutional/margin 卡 07-07 沒跟上 daily_prices 07-08 → 外資/投信/融資全「─」：資料抓取問題，
  需要 Cody 提供跑 `main.py` 當下的 log 看有無 TPEx 寫入失敗警告。

### ⚠️ git 狀態提醒
- 本機 `master` 與 `origin/master` 已分歧（兩台各自產生 `update: sector performance 2026-07-08`
  的產出檔 commit：本機 `abd4aad` vs origin `4f7dba4`）。這屬雙機/Developer session territory，
  我沒去動它——建議在**一台**上把 master 收斂（fast-forward 或擇一產出檔）再繼續，避免越差越多。

---

## [2026-07-08] 實作（Cody 授權「這邊加」）：Section 8 加近5日/近7日累積漲跌幅

### 授權與範圍
Cody 明確要求「這邊加」（不等桌電）→ 依 Debugger 授權例外，直接在 debug 分支實作 + 測試 + 記錄。
異動：`main.py`（sh_rows 滾動查詢）、`export/chips_generator.py`（`_shareholder_table` 加兩欄 +
新 `_chg_cell`）、`tests/test_chips_generator.py`（+2 測試）。**交易日定義、rn=N+1（近5日 rn6、
近7日 rn8），Cody 2026-07-07 拍板。**

### 做了什麼
- `main.py`：新增一次查全 universe 的滾動窗 SQL（`ROW_NUMBER() … ORDER BY date DESC`，rn1/rn6/rn8
  的 close），加 `_roll_pct()`（`pd.isna` 防 NULL/nan/除零一律回 None），每列帶 `chg_5d`/`chg_7d`。
- `chips_generator._chg_cell(pct)`：回傳**完整 `<td>`**（紅漲綠跌、None→「─」），呼叫端用
  `f"{_chg_cell(...)}"` **不外包 `<td>`**（避開 Task 5 的雙重 `<td>` 雷）。表頭在「收盤(週漲跌)」後
  加「近5日/近7日」。

### 驗證
- 全專案 **111 passed**（109 + 2 新顯示測試：有值紅漲綠跌、缺值「─」）。結構測試 td==th 動態比較，
  +2 欄後仍相等（12==12）。
- **滾動 SQL 邏輯（合成 8 天 temp DB 實測）**：A(8天) 近5日+10%/近7日+25%、B(4天) 兩者 None、
  C(6天) 近5日+10%/近7日 None（不足8日）——rn 對位、除零/不足資料回 None 全部正確。
- ⚠️ **本機驗不了真實 production 數字**：debug 機 `daily_prices` 只有 1 天（2026-07-02）。合成資料
  已驗邏輯正確，但「2330 真實近5日對不對」需桌電（有多日股價）跑一次 `python main.py`、開
  `docs/chips.html` Section 8 目視確認。
- ⚠️ **未做成 pytest 的部分**：滾動 SQL 是 `main.py` run() 內的 inline query（非可 import 函式），
  只用合成 temp DB 的 standalone script 驗過，沒有落成 pytest。若要鎖行為，建議把該 query 抽成
  `screener/database.py::get_rolling_returns()` 再補測試（本次未做，避免過度動 Developer 的檔）。

### 提醒
- 標題「近5日」是「至最新交易日」，若當天股價還沒抓進 daily_prices，錨點是昨天——非即時到當下盤中。

---

## [2026-07-07] 建議新功能規格（給 Developer 在 master 實作）：Section 8 加「近5日/近7日累積漲跌幅」

### 背景 / 為什麼
Cody 反映 Section 8 現在的「收盤(週漲跌)」偏慢——因為它錨在 TDCC 集保週五快照（`shareholder.py`
每週五更新一次）+ 發布時間差，盤中不反映今天。Cody 決定：**加「近5日」「近7日」累積漲跌幅（從
daily_prices 直接滾動算、反映到最新交易日），集保週漲跌欄保留在旁邊**。

- 集保週漲跌**保留不動**：它跟「大戶張數變化」是同一個時間窗（週五對週五），蘋果對蘋果，有分析
  價值，不能拿掉。
- 新增兩欄是**新鮮**的股價動能，跟集保無關，直接反映最近走勢。

### 為什麼建議 Developer 在 master 做（而不是 Debugger 在 debug）
1. **git 流向**：現行是 master→debug（Developer 實作、Debugger merge 驗證）。這是動 `main.py` +
   `chips_generator.py` 的新功能，在 debug 做會變成 debug→master 逆向流、跟 Developer 正在改的檔案
   容易衝突。
2. **驗證**：debug 機的 `daily_prices` 只有 1 天（2026-07-02），**沒法驗真實的 5日/7日累積數字**。
   master 那台有完整多日股價才能驗數字對不對。實作完我這邊負責 review。

### 精確規格（turn-key）
**1. `main.py` sh_rows 組裝（現約 543-604 行）——新增滾動報酬查詢**
在現有 `_price_map`／`_insider_map` 之後，加一個**一次查全 universe**（不要逐股）的滾動窗查詢：
```sql
WITH ranked AS (
  SELECT stock_id, close,
         ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) AS rn
  FROM daily_prices
)
SELECT l.stock_id, l.close AS c0, d5.close AS c5, d7.close AS c7
FROM (SELECT stock_id, close FROM ranked WHERE rn = 1) l
LEFT JOIN (SELECT stock_id, close FROM ranked WHERE rn = 6) d5 USING (stock_id)
LEFT JOIN (SELECT stock_id, close FROM ranked WHERE rn = 8) d7 USING (stock_id)
```
- 建 `_roll_map = {str(r["stock_id"]): r for _, r in _rdf.iterrows()}`，包 try/except → `{}`（比照
  現有 `_insider_map`）。
- **定義**：最新交易日 = `rn=1`；「N 交易日前」= `rn = N+1`（近5日→rn6、近7日→rn8）。⚠️ 這採「最新
  vs N 個交易日前的收盤」；若 Cody 要的是別種定義（例如 rn=N，或 5/7 是**日曆日**不是交易日），
  改 `rn` 常數即可——**這是唯一需要 Cody 拍板的點**。

**2. 每列算 chg_5d / chg_7d（沿用剛修好的 pd.isna 防 NULL 教訓）**
```python
roll = _roll_map.get(sid)
def _pct(a, b):
    if a is None or b is None or pd.isna(a) or pd.isna(b) or b == 0:
        return None
    return round((a - b) / b * 100, 2)
chg_5d = _pct(roll["c0"], roll["c5"]) if roll is not None else None
chg_7d = _pct(roll["c0"], roll["c7"]) if roll is not None else None
```
加進 sh_rows dict：`"chg_5d": chg_5d, "chg_7d": chg_7d`。

**3. `export/chips_generator.py::_shareholder_table()` 顯示**
- 表頭在「收盤(週漲跌)」後加 `<th>近5日</th><th>近7日</th>`（位置隨你）。
- 每列用一個 pct 顯示 helper（紅漲綠跌、`None`→「─」）。
- ⚠️ **踩過的雷提醒**：Task 5 剛修過雙重 `<td>`——helper 若回**完整 `<td>`** 就別再外包 `<td>`；
  若回 `<span>` 才外包。挑一種、統一。
- **更新那個結構測試**（列 `<td>` 數 == 表頭 `<th>` 數）的期望欄數 +2。

**4. 測試（可用合成多日 daily_prices 的 temp DB 驗真實邏輯，不需真 screener.db）**
- 建 8+ 交易日的 daily_prices，驗 chg_5d/chg_7d 數字對、方向對（紅漲綠跌）。
- 資料不足（<6/<8 日）→ chg 為 `None`、顯示「─」、不 crash。
- 顯示層結構測試（td 數 == th 數，+2 欄後仍相等）。

### ⚠️ 資料正確性提醒（實作/驗證時注意）
- 這兩欄錨在「daily_prices 的最新日期」。**如果當天股價還沒抓進來**（盤中、或 `--update-sectors`
  還沒跑），「最新交易日」其實是昨天——一樣不是即時到當下。建議標題標「近5日(至最新交易日)」讓
  語意誠實，別讓使用者以為一定含今天盤中。
- `close` 可能為 NULL（DuckDB → nan）：`_pct()` 已用 `pd.isna` 擋，沿用 999f408 的修法，別退回
  `is not None`。

### 結論
- **[Cody 已拍板 2026-07-07]：交易日**，定義 = 最新交易日(rn=1) vs N 個交易日前(rn=N+1)，即
  近5日→rn6、近7日→rn8。規格已完整、無待決項。
- [ ] 待 Developer 在 master 實作；實作後 Debugger merge 過來驗（數字、方向、缺值─、結構 td==th）。

---

## [2026-07-06] 報告＋修復 - `insider_holdings.py` 沒有 MOPS 封鎖偵測，限流被誤判成「查無資料」（Cody 授權 Debugger 直接修）

### 背景
Cody 實跑 `python main.py --update-insider-holdings`（1038 支股票），全程 log 出現異常的
escalating failure：成功數卡住不動、失敗數一路飆升，最終跑完只有 **341 成功 / 697 失敗**
（成功率 32.8%）。台灣上市櫃公司董事/監察人/大股東持股是強制月報，67% 的「查無資料」
在統計上不合理。

### 🔴 找到的問題
直接側測 `mopsov.twse.com.tw` 的內部人持股 API 端點（`_URL`），確認**現在這個 IP 正在被
MOPS 的資安防護擋掉**：
```
狀態碼: 307
內容: 因為安全性考量，您所執行的頁面無法呈現。
      FOR SECURITY REASONS, THIS PAGE CAN NOT BE ACCESSED.
```
`scrapers/insider_holdings.py::_fetch_one_stock()` 只有 `r.raise_for_status()`，但 307
不是 4xx/5xx，不會拋例外；擋頁 HTML 沒有 `"查無"` 字串、也沒有 `資料年月` 格式，
`_parse_response()` 會回傳 `None`，被 `fetch_insider_holdings_monthly()` 當成「這支股票
單純沒有揭露資料」而不是「被擋」——**跟 `scrapers/twse.py` 已經修過的 `TWSEBlockedError`
是同一類錯誤**，只是這支新寫的 scraper 沒有沿用那個教訓，從一開始就沒有封鎖偵測。

拆每 50 支一個區間比對成功/失敗增量，發現這是**滾動時間窗限流**（不是永久封鎖）：
`251-300` 全擋（+0 成功 +50 失敗），但 `651-700` 幾乎全過（+48 成功 +2 失敗），會鬆會緊，
過一段時間又自動解除——這點也在事後側測驗證過（隔一段時間後同一支 2330 正常抓到真實資料，
沒有再被擋）。

### ✅ 已修（Cody 授權直接改）
- 新增 `MOPSBlockedError` + `_check_mops_response()`（比照 `scrapers/chips.py::
  TWSEBlockedError` 的模式）：合法回應（含真正查無資料）一律是 status 200；擋頁是 307 +
  內容含「安全性考量」/「SECURITY REASONS」，這是 2026-07-06 實測擋頁內容，不是臆測。
- `_fetch_one_stock()` 在 `raise_for_status()` 之後另外呼叫 `_check_mops_response()`
  （307 不會被 `raise_for_status()` 攔到，要額外查）。
- `fetch_insider_holdings_monthly()` 回傳型別從 `list[dict]` 改成 `tuple[list[dict],
  list[str]]`，第二個是 `blocked_ids`（3 次重試都被擋的股票代號），跟「真的查無資料」
  （`no_data` 計數）分開統計，不再混在同一個「失敗」桶。
- 偵測到 `MOPSBlockedError` 時用比一般網路錯誤更長的退避（`_BLOCK_BACKOFF = (20.0, 40.0)`
  秒，一般錯誤是 `(3.0, 7.0)` 秒）——因為是滾動時間窗限流，退避夠久才有機會等窗口重置，
  沿用一般錯誤的短退避沒有意義。**沒有**做成「偵測到就整批熔斷放棄」（跟
  `scrapers/backfill.py::_looks_like_twse_block` + `stop_event` 那套不一樣）——因為觀察到
  限流是間歇性、會自己鬆綁，熔斷會在還有機會恢復時提早棄權，改成單純的加長退避+清楚分類。
  跑完會 log 一行 `本次有 N 支股票因 MOPS 限流被擋（非真正查無資料），建議稍後單獨重跑這批`。
  `main.py::_update_insider_holdings()` 呼叫端同步更新回傳值解構，也加了對應的收尾警告 log。
- 新增 3 個測試：`_check_mops_response` 正確辨識真實擋頁內容（307+資安考量文字）、正常 200
  回應（含合法的查無資料）不會被誤判、`fetch_insider_holdings_monthly` 用 `monkeypatch`
  模擬「1 支正常＋1 支真查無＋1 支被擋」，驗證 `blocked_ids` 只包含真正被擋的那支，
  不會跟查無資料混在一起。8 個 insider_holdings 測試全過，全專案 112 個測試 111 過
  （1 個既有環境限制，需要本機真的有 `data/screener.db`，跟本次無關）。
- 已對真實 MOPS 端點實測：修法上線後側測 2330，這次沒被擋、正常回傳真實資料
  （`company_shares: 1,735,849,436`），確認沒有把正常回應誤判成擋頁。

### 🟡 這次沒動的部分（現有資料的處理，留給 Cody 決定）
- **這次跑出來的 341 筆資料仍然可用**（真實資料，沒有被污染成假的 0 值），但覆蓋率只有
  32.8%，不能當作完整的月度快照。剩下 697 支裡有一部分是真被擋、一部分可能是真查無資料，
  這次事發時還沒有 `blocked_ids` 機制可以回溯分辨，建議挑離峰時段重新跑一次
  `--update-insider-holdings`（`save_to_db` 是 upsert，不會跟已有 341 筆衝突）。

### 結論
- [x] 已修並加測試、已對真實 MOPS 端點驗證——下次重跑 `--update-insider-holdings` 時，
  log 會清楚分辨「查無資料」vs「被限流擋掉」，不會再混在一起誤判。

---

## [2026-07-06] 驗證 - Task 5 兩修復（999f408）：雙重 <td> + close/prev_close nan crash

### 驗證方式
- `git merge master`（乾淨）；全專案 `pytest`；實際呼叫 `_shareholder_table()` 用精確 regex 數
  `<th>`/`<td>`（排除 `<thead>` 誤匹配）；實測 `close=nan` 洗法 + `_price_cell` 不 crash

### ✅ 驗證通過（我上一輪的 🔴 + 🟡 都修掉了）
- **🔴 雙重 `<td>` 已修**：`chips_generator.py:408-409` 從 `f"<td>{company_html}</td>"` 改成
  `f"{company_html}"`（不外包，比照 `_price_cell` 用法）。實測：表頭 `<th>`=10、資料列 `<td>`=10、
  `<td><td>`=0 → **欄位對齊，malformed HTML 消除** ✅。Developer 也加了結構測試（列 td 數 ==
  表頭 th 數），以後再犯會被抓到（測試 108→109）。
- **🟡 `close`/`prev_close` nan latent crash 已修**：`main.py` 新增
  `if close is not None and pd.isna(close): close = None`（prev_close 同）。實測 `close=nan` →
  洗成 `None` → `_price_cell` 回「─」、**不再 `int(nan)` crash** ✅。與相鄰欄位的 `pd.notna` 寫法
  一致了。
- **全專案測試**：**109 passed, 0 failed**。

### 結論
- [x] 可以繼續下一個任務——**大戶張數化+內部人持股計畫 Task 1-5 全部驗證通過、收尾完成**。
  Task 5 的 🔴（Section 8 欄位錯位）與 Task 4 帶下來的 🟡（NULL close crash）都已修並實測確認。
  Developer 確認後即可 push origin。

---

## [2026-07-06] 驗證 - Task 5 Section 8 表格新增張數變化+內部人欄位（計畫最後一個 Task）

### 驗證方式
- `git merge master`（乾淨）；全專案 `pytest`；實際呼叫 `_shareholder_table()` 產生真實 HTML、
  用 regex 數 `<td>` 標籤與表頭欄數比對結構

### 🔴 程式問題（需修）
- **`_insider_cell()` 的輸出被雙重包 `<td>`，產生 malformed HTML、Section 8 表格會欄位錯位**：
  - `_insider_cell()` **回傳的是完整 `<td>...</td>`**（`chips_generator.py:419`「─」那格、
    `:427` 有值那格都含 `<td>` 標籤）。
  - 但列組裝把它**又包一層** `<td>`（`chips_generator.py:408-409`）：
    ```python
    f"<td>{company_html}</td>"   # company_html 已是 <td>...</td>
    f"<td>{major_html}</td>"
    ```
    → 實際輸出 `<td><td style='...'>─</td></td>`（雙重 `<td>`）。
  - **實測**：一列資料產生 **12 個 `<td>`，但表頭只有 10 欄**（`#`/股票/族群/收盤(週漲跌)/大戶持倉%/
    週變化/大戶張數變化/連增週/公司派持股/大股東持股）；`<td><td` 出現 **2 次**（公司派、大股東各一）。
    多出來的 2 個 cell 會讓 Section 8 表格欄位錯位／版面跑掉。
  - **對比**：同一列的 `_price_cell()`（`:403`）也回傳完整 `<td>`，那裡就**沒有**多包 `<td>`
    （`f"{_price_cell(...)}"`）——寫法正確。`_insider_cell` 應比照，Developer 這裡不一致寫錯了。
  - 修法（擇一，我不自己動）：把 `:408-409` 改成 `f"{company_html}"`/`f"{major_html}"`（不外包，
    比照 `_price_cell` 用法）；或把 `_insider_cell` 改成只回傳內層 span、由呼叫端包 `<td>`。
  - **為什麼 3 個新測試沒抓到**：測試用 substring 檢查（找「張」「─」等字串），雙重 `<td>` 裡一樣
    含這些字串，所以測試綠燈但 HTML 其實壞的。建議補一個「資料列 `<td>` 數 == 表頭欄數」的結構斷言。

### ✅ 驗證通過
- **全專案測試**：**108 passed, 0 failed**（含新增 3 個）。
- **股→張換算（÷1000）正確**：`share_chg`、`_insider_cell` 都 `/1000`；實測 company_shares
  `1,735,849,436 → 1,735,849張`、`share_chg 250,000 → 250張` ✅。
- **方向（紅漲綠跌）正確**：正值紅（`#f87171`）、負值綠（`#4ade80`）、0 灰，符合台股慣例 ✅。
- **缺值顯示「─」正確**：`share_chg is None` / `_insider_cell shares is None` → 顯示「─」不是
  「0張」，實測 major_holder=None → 「─」✅（對應我 Task 2/4 報告的「缺值別顯示成 0」提醒）。
- **收盤欄標題改「收盤(週漲跌)」**，對應 Task 4 把 change_pct 語意改成集保週期週漲跌 ✅。
- **Task 4 的 nullable 清洗讓顯示層安全**：`share_chg`/insider 六欄在 Task 4 已用 `pd.notna()` 洗成
  乾淨 `None`，所以顯示層的 `is not None` 判斷不會踩到 `nan`（若沒洗，`nan is not None=True` 會渲染
  出「nan張」）——這兩層剛好接上 ✅。

### 🟡 仍未處理（Task 4 帶下來的，Task 5 沒收）
- **`close`/`prev_close` 的 `pd.isna` 一致性（我 Task 4 報告的 🟡，仍開著）**：Task 5 只動
  `_shareholder_table`/`_insider_cell`，沒碰 main.py 的 `close`/`prev_close` 判斷，也沒碰
  `_price_cell`。所以「`daily_prices.close` 為 NULL → `nan` 洩漏進 `sh_rows['close']` →
  `_price_cell` 在 `int(nan)` crash」這個 latent 問題**還在**（本機 0 筆 NULL close，未觸發）。
  既然這次剛好在改 Section 8 顯示，**建議一起把這個一行的一致性修掉**（`close`/`prev_close` 改
  `pd.isna` 判斷）。

### 結論
- [ ] **需要修改後再確認**：🔴 雙重 `<td>` 是這次 Task 5 引入的真實顯示 bug，會讓 Section 8 表格
  欄位錯位，**建議修掉再放行**（修法就是 `:408-409` 拿掉外層 `<td>`，一行的事）。修完我再驗一次
  「資料列 td 數 == 表頭欄數」。其餘（÷1000、方向、缺值─、標題）都 ✅。
- 順帶建議一起收 Task 4 帶下來的 `close`/`prev_close` `pd.isna` 🟡（latent crash）。

---

## [2026-07-06] 驗證 - Task 4 main.py 串接內部人持股 + sh_rows 對齊集保週期/join

### 驗證方式
- `git merge master`（乾淨）；全專案 `pytest`；`main.py` ast.parse；合成但貼合真實型別 round-trip
  的臨時 DB 驗價格對齊 key 匹配；追 `close=NULL → nan` 洩漏一路到 `_price_cell`；查真實
  `data/screener.db` 現況；確認 `_to_int` 修法（收上輪 🟡）

### ✅ 驗證通過

**全專案測試**：**105 passed, 0 failed**（含新增 2 個 `_to_int` 測試）；`main.py` ast.parse OK。

**收上兩輪的兩個 🟡**
- Task 3 的 `_to_int` 脆弱性：已改成無法解析（`-`／`－`／`N/A`）回 0、不再拋 ValueError 讓整支
  股票靜默消失，實測確認 ✅。
- Task 2 的 `share_chg` NULL 處理：Task 4 對 `share_chg`/`lv12_15_shares`/insider 六欄一律用
  `pd.notna()` 判斷、缺值帶乾淨 `None`（不是 0、不是 `<NA>`）✅；`week_chg` 的
  `None if pd.isna(...) else float(...)`（2026-07-05 的 NaN fix）**沒有被計畫範例碼退回** ✅。

**【核心】價格對齊集保週期的 key 匹配**（整個功能成敗關鍵）
- `sh_df["date"]`/`prev_date` 是 `datetime64[us]`；`daily_prices` 經 `.fetchdf()` 也是 Timestamp，
  兩邊 `str()` 都是 `"2026-07-04 00:00:00"` → **key 對得上**，實測週漲跌 (950-900)/900 = 5.56% 正確 ✅。
- `DuckDB date IN (SELECT UNNEST(?))` 接受 numpy.datetime64 綁定 ✅。
- Developer 從 Task 2 堅持「date 保持 Timestamp」的決定在這裡兌現，兩邊型別一致才對得上。

**insider join / CLI**
- `_insider_map.get(sid)` 回 Series，用 `insider is not None`（identity check，避開 Series 真值
  歧義陷阱）+ 每欄 `pd.notna()`，正確 ✅。
- `--update-insider-holdings` → `_update_insider_holdings()` **先 `init_db()` 再抓再 save**，
  對應我 Task 3 報告「表要先存在」的提醒 ✅。
- 缺價優雅降級：找不到價格 → `close=None` → `_price_cell` 回「─」，實測正確 ✅。

### 🟡 建議改善（latent，目前資料未觸發，但會 crash + 違反專案既定規則）
- **`close`/`prev_close` 用 `is not None` 而非 `pd.isna()`，NULL close 會洩漏 NaN 並讓
  `_price_cell` crash**：
  - `_price_map` 的值直接來自 `daily_prices.close`（DuckDB DOUBLE，**可為 NULL**）。若某集保週期
    日期對到一列 `close IS NULL`，該值經 pandas 變 `nan`。main.py 的
    `float(close) if close is not None else None` 對 `nan` 判 `is not None=True` → **`nan` 洩漏進
    `sh_rows["close"]`**；`price_week_chg` 同理算出 `nan`。
  - 實測：`_price_cell(nan, nan)` 在 `int(close)` 直接拋 `ValueError: cannot convert float NaN to
    integer`——**不是渲染成 "nan%"，是產 chips.html 時 crash**。
  - **目前不會觸發**：這台 `data/screener.db` `daily_prices` 有 **0 筆 NULL close**（髒值是 close=0
    不是 NULL，close=0 會走另一條路：`prev_close!=0` 有擋除以零，但當週 close=0 會算出 -100% 之類
    的髒值——那是資料問題不是這裡的 bug）。
  - **但這正是專案重申 3+ 次那條規則的違反**（DuckDB 出來、可能 NULL 的欄位一律 `pd.isna()`，不要
    `is not None`）——而且 Task 4 旁邊的 `share_chg`/insider 欄都正確用了 `pd.notna()`，唯獨
    `close`/`prev_close` 用舊寫法，不一致。建議：`close`/`prev_close` 的判斷改用
    `close is not None and not pd.isna(close)`（或建 `_price_map` 時就 `if pd.notna(r["close"])`
    過濾掉 NULL），與相鄰欄位一致，避免哪天 daily_prices 出現 NULL close 就 crash。

### 特別注意（非問題，僅記錄）
- `change_pct` 語意已從「最新交易日漲跌」改成「集保週期週漲跌」（key 重用、語意變）。`_price_cell`
  只顯示帶色的 `x.x%`、**沒有「日/週」文字標籤**，所以 Task 4 完成、Task 5 未做的這個過渡狀態
  **不會顯示錯誤標籤**（只是數字語意變了）；Task 5 加欄位時記得補「週」的說明。跑 `main.py` 目前
  chips.html Section 8 外觀不變，與 Developer 說明一致。
- 這台無法跑真實端到端 smoke test：`shareholder` 表為空、`insider_holdings` 表尚未建（Task 3 才加，
  需 init_db）。價格對齊我用貼合真實型別的合成資料驗過核心機制；**建議 Developer 在有多週集保+對應
  股價的桌機實跑一次** `python main.py` 確認 sh_rows 帶新欄位、不 crash（尤其確認該機資料無 NULL close）。

### 結論
- [x] 可以繼續下一個任務——Task 4 核心（價格對齊 key 匹配、nullable pd.notna、insider join、CLI
  先 init_db、收兩個舊 🟡）全部 ✅。**建議順手修 `close`/`prev_close` 的 `pd.isna` 一致性**（latent
  crash + 違反既定規則，一行的事），可併進 Task 5 一起處理。

---

## [2026-07-06] 驗證 - Task 3 內部人持股 scraper（scrapers/insider_holdings.py）

### 驗證方式
- `git merge master`（乾淨）；全專案 `pytest`；**實際連線 MOPS `ajax_stapap1` 抓 2330/2317 真實
  HTML**（Developer 本機沒法驗的最高風險項）驗 regex；抓真實表頭確認欄位語意；查 schema 欄序對齊；
  實測 `_to_int` 對非數字 cell 的行為

### ✅ 驗證通過

**全專案測試**：**103 passed, 0 failed**（含 `test_insider_holdings.py` 3 個）。

**【重點】regex 對真實 HTML（實際連線 MOPS 抓 2330 / 2317）**
- `<TR class='odd'/'even'>` 格式與真實一致：2330 抓到 40 列、2317 抓到 23 列（資料列確實用
  odd/even class；表頭那個純 `<tr>` 不被誤抓，正確）。
- 每列 9 欄、`資料年月:11505` → `2026-05-01`（民國轉西元）正確。
- 分類正確：2330 全歸公司派、2317 抓到大股東（郭台銘 17.4 億股 / 設質 8.6 億）。

**【重點】欄位語意（抓真實表頭確認，非臆測）** — Developer 的欄位對應**完全正確**：
- cells[3]=目前持股（本人）、cells[4]=設質股數（本人）、cells[6]=**內部人關係人目前持股合計**
  （配偶/未成年子女/他人名義）、cells[7]=關係人設質。
- `shares = 本人 + 關係人持股`、`pledge = 本人 + 關係人設質`——這是衡量「內部人實際掌控股數」的
  標準口徑，**加總語意正確**，真實數字合理（2330 公司派 17.4 億股、2317 大股東 17.4 億股）。
- `選任時持股`(cells[2]) 正確未使用（要的是目前持股不是選任時）。

**位置式 INSERT（全新表）**：`insider_holdings` schema 欄序
（stock_id→report_date→company_shares→company_chg→company_pledge_pct→major_holder_shares→
major_holder_chg→major_holder_pledge_pct）與 INSERT SELECT 欄序**完全一致**；全新表只走
CREATE TABLE、無 ALTER，欄序固定，位置式安全 ✅——與 Task 1「ALTER-append 情境」不同，判斷正確。

**save_to_db 月變化**：測試驗過跨月 `company_chg=+100,000`/`major_holder_chg=-500,000`、首月無前值
`chg=NULL`；prev 查詢用 `report_date < write_date` + `QUALIFY ROW_NUMBER` 取最近前一期，重跑同月
不會拿當月當基準（idempotent）✅。

**重試不吞例外**：`_fetch_one_stock()` 不 catch POST 例外，讓例外冒給外層重試迴圈——正確套用
2026-07-05 shareholder.py 那次的教訓 ✅。

### 🟡 建議改善（潛在脆弱性，非阻擋——真實 2330/2317 資料未觸發）
- **`_to_int` 對「非數字非空」cell 會整支靜默丟失**：實測 `_to_int('-')`/`'－'`/`'N/A'` 都拋
  `ValueError`，且例外會傳播出 `_parse_response()` → 該股被當抓取失敗、重試 3 次（同樣確定性失敗）
  後靜默跳過（只 log warning）。目前真實資料所有數字欄不是純數字就是空字串（`_to_int('')→0` 沒事），
  沒踩到；但**若哪天 MOPS 把某個 0/空值 render 成 `-`／`－`，那支股票會整筆消失**——正是「不報錯
  但漏資料」那類。建議：`_to_int` 對無法解析的值回 0（或 per-row try/except，讓單列壞掉不影響整支）。
  這是 regex/解析對格式敏感的一體兩面，優先度可等真的遇到再修，但先記錄。
- 次要（純統計顯示，不影響資料）：重試迴圈把「查無資料（rec=None，合法無內部人資料）」跟「真的
  抓取失敗」都併進 `failed` 計數，log 的「失敗 N」會略微高估真實失敗數，不影響寫入正確性。

### 特別注意
- 這個 scraper **還沒接進 main.py**（Task 4 才做 `--update-insider-holdings` CLI），目前跑 main.py
  不會用到它——與 Developer 說明一致，已確認。
- `insider_holdings` 表由 `init_db()` 的 `CREATE TABLE IF NOT EXISTS` 建立，既有 `data/screener.db`
  下次 init_db 會補上此表；Task 4 串接時要確保先 init_db 再 save_to_db（否則表不存在會報錯）。

### 結論
- [x] 可以繼續下一個任務——Task 3 核心（regex 真實格式、欄位語意、加總口徑、位置式 INSERT、月變化、
  重試不吞例外）全部 ✅。`_to_int` 脆弱性列 🟡 潛在，不阻擋，建議 Task 4/5 前後順手強化。

---

## [2026-07-06] 驗證 - Task 2（get_shareholder_top 張數變化）+ _push_html abort 精修（fa5aa9b）

### 驗證方式
- `git merge master`（乾淨 fast-forward，身分檔不再撞 ✅ 移行生效）；全專案 `pytest`；
  獨立臨時 DB 實測 `share_chg` 邊界（含過渡 NULL、三週取最近兩週）；臨時 repo 實測
  `_rebase_in_progress()` 在「非衝突失敗」vs「衝突」兩情境的行為

### ✅ 驗證通過

**全專案測試**：**100 passed, 0 failed**。

**Task 2（`3b51653`）`get_shareholder_top()` 回傳 prev_date + share_chg**
- 兩週皆有張數：`share_chg = 本週 − 上週`，方向正確（實測張數下降 → `-1,000,000`）✅
- 單週資料：`prev_date`/`share_chg` 為 NULL（NaT/NaN），不報錯 ✅
- 三週資料：`ROW_NUMBER` 正確取**最近兩週**算差（prev_date=前一週、不是最舊那週）✅
- 「date 保持 Timestamp」的決定合理：與 `daily_prices` 的 `.df()` 型別一致，Task 4 用
  `str(row["date"])` 當 key 對齊股價才對得上；測試斷言改用 `[:10]` 比日期部分（型別無關）正確。

**`_push_html` abort 精修（`fa5aa9b`）**（收上輪我回報的 🟡）
- `main.py` `ast.parse` OK ✅
- **非衝突失敗**（無 upstream／網路斷）：`_rebase_in_progress()`（`git rev-parse --git-path`，
  worktree-safe）回傳 False → 走「可能無 upstream 或網路問題」分支、**不呼叫 `git rebase --abort`**，
  消除「no rebase in progress」雜訊 ✅
- **衝突**：`_rebase_in_progress()` 回傳 True → `git rebase --abort` → 工作區乾淨、本機 commit 保留 ✅
- 兩情境都不 push、commit 保留，與上一輪驗過的行為一致。

### 🟡 資料正確性提醒（非阻擋，給 Task 4/5）
- **過渡期 `share_chg` 會是 NULL**：Task 1 之前寫入的舊 shareholder 列，`lv12_15_shares` 是
  ALTER 補的 NULL。若某股「上週」那筆是舊列，即使有兩週資料、`prev_date` 有值，`share_chg`
  仍會是 `<NA>`（實測確認：`prev_date` 有值但 `share_chg=<NA>`，不報錯）。這是預期的過渡現象、
  會隨新資料累積自然痊癒，但 **Task 4/5 消費 `share_chg` 時務必用 `pd.isna()` 判斷**（`share_chg`
  是 DuckDB `Int64` 的 `<NA>`，用 `is not None` 或 `x or 0` 會誤判/踩到 pandas nullable 那類地雷——
  這已是專案第 N 次同類問題）。頁面呈現大戶張數變化時，NULL 應顯示「—」而非 0，避免把「資料缺」
  誤導成「零變化」。

### 結論
- [x] 可以繼續下一個任務——Task 2 + `fa5aa9b` 全部 ✅，身分檔移行生效（本次 merge 乾淨無衝突）。
  提醒 Task 4/5 對 `share_chg` 的 NULL 處理（見上）。

---

## [2026-07-06] 驗證 - Developer 3 個新 commit（Task 1 大戶張數 / _push_html 修復 / 工作流 checklist）+ 身分檔移行

### 驗證方式
- 先完成 CLAUDE.md 移出追蹤的移行（stash→drop→merge master→重建本地 gitignored CLAUDE.md）；
  跑全專案 `pytest`；獨立臨時 DB/repo 實測 by-name INSERT 錯位、限定範圍 commit、rebase 衝突 abort

### ✅ 驗證通過

**身分檔移行（一次性）**
- 丟 stash 前先 `diff` 確認 stash 裡的 Debugger CLAUDE.md 是 master `CLAUDE-debugger.md` 的**舊版子集**
  （master 版多了「工作流自檢」章節、四資料源說明等），丟掉不遺失任何內容。
- merge master 後 `.gitignore`／`CLAUDE.md` **不再撞衝突**；`git check-ignore CLAUDE.md` 確認已被忽略、
  `git ls-files CLAUDE.md` 空（不再追蹤）；本地重建的 CLAUDE.md 開頭是「角色：Debugger 🔍」。
- docs 產出檔衝突（chips/patterns.html 取 master、data.json 跟 master 刪除）依既有慣例解掉。

**全專案測試**：**98 passed, 0 failed**（這台 debug 有 `data/screener.db`，連 `test_scan_patterns_returns_list`
都過，不再是既有環境限制）。

**Task 1（`13b4eee`）大戶張數 `lv12_15_shares`**
- 【重點】**by-name INSERT 修正經實測確認必要**：建「舊 7 欄表→ALTER 加 `lv12_15_shares` 到最後（第 8 欄）」
  的 DB，餵 `shares=5,000,000 / total=25,000,000`：
  - by-name INSERT → `lv12_15_shares=5,000,000`、`total_shares=25,000,000` ✅ 正確
  - 位置式 INSERT（計畫原寫法）→ `lv12_15_shares=2`（拿到 streak 值）、`total_shares=5,000,000`（拿到張數）
    🔴 **整排錯位**。證明 Developer 偏離計畫改成 by-name 是對的，否則正式 DB 會被靜默寫壞（不報錯給錯資料）。
- `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 對已有該欄的表重複跑兩遍，無報錯（冪等）✅
- `save_to_db()` 的 df 選欄與 INSERT 欄位一致（`stock_id,date,lv12_15_pct,lv12_15_cnt,lv12_15_shares,
  total_shares,week_chg,streak`）✅

**`_push_html` 修復（`3e416cf`）**
- **限定範圍 commit**：臨時 repo 實測——docs 檔更新的同時「手動 `git add` 了不相關的 `unrelated.py`」，
  `git commit -- <docs 檔>` 後該 commit **只含 docs 檔**，`unrelated.py` 仍 staged、HEAD 內容未變 ✅
  （正是先前 `_push_html` 誤掃 staged 變更那個地雷的修復）。
- **pull --rebase 撞衝突**：模擬兩機分岔＋同行衝突，`pull --rebase --autostash` 回傳非 0 →
  `rebase --abort` → 工作區乾淨、**無半完成 rebase**、**本機 commit 完整保留**、**不會 push**，
  留 ahead/behind 給人工處理 ✅。

**工作流 checklist（`cc3f1c0`）**：純文件，`CLAUDE-debugger.md:118`／`CLAUDE-developer.md:130`
確認都有「## 工作流自檢」章節 ✅。

### 🟡 建議改善（不阻擋）
- `_push_html` 的 `pull --rebase --autostash` 若因**非衝突原因**失敗（無 upstream／網路斷），
  接著的 `git rebase --abort` 會因「沒有進行中的 rebase」而報無害錯誤（無 `check=True` 不會 crash），
  本機 commit 一樣保留、一樣不 push，行為安全，只是 log 可能出現一句 rebase 的雜訊，可忽略。

### 留給 Cody 決定
- `_push_html` 現在「push 前自動 `git pull --rebase`」是**行為改變**（以前直接 push）。行為正確、
  分岔時安全中止，但是否保留這個自動 pull 由 Cody 決定（若不想自動 pull，可改回手動同步）。

### 結論
- [x] 可以繼續下一個任務——3 個 commit 全部 ✅，身分檔移行乾淨（下次 `git merge master` 應乾淨不再撞）。
  Developer 那邊確認後即可 push 到 origin。

---

## [2026-07-05] 驗證 - 籌碼面 code review 三項修復（XSS 跳脫、chips.html 靜默失敗、week_chg NaN）

### 驗證方式
- 跑全專案測試；直接呼叫 `_esc()`／`json.dumps(...).replace("</", "<\/")` 實測正常字串跟惡意
  payload 的行為；讀 `main.py::_push_html()` 前後的分支邏輯

### ✅ 驗證通過
- **測試套件**：85 個，84 過、1 個既有環境限制（`test_scan_patterns_returns_list` 需要本機真的
  有 `data/screener.db`，debug 資料夾沒有，跟這次修復無關，前幾則任務已多次碰到同一個）。
- **XSS 跳脫（`_esc()`）**：正常字串（`台積電`、`2330`、`半導體設備`）原樣輸出不變，`None`/`""`
  正確轉空字串，`<script>alert(1)</script>` 正確跳脫成 `&lt;script&gt;...`，視覺輸出對一般資料
  完全沒有影響，只有含特殊字元的輸入才會不同。
- **`</script>` 提前結束攻擊修法**：`json.dumps(...).replace("</", "<\/")` 實測過，正常資料 JSON
  結構不變，惡意 `</script>` 序列正確變成 `<\/script>`，不會提前結束 script 區塊、不會讓後續內容
  被當成新 HTML 解析。
- **`chips_html_written` 分支邏輯**：`main.py:528-532` `if chips_html_written: log 成功 else:
  log 警告`，方向正確；`chips_generator.py::generate()` 兩者皆空提前 `return False`、正常寫檔
  `return True`，跟 docstring 描述一致，沒有反過來。
- **`week_chg` NaN 修法**：`main.py:517` 已改成 `None if pd.isna(row["week_chg"]) else
  float(row["week_chg"])`，跟專案已建立的 `pd.isna()` 慣例一致。

### 🟡 建議改善（不阻擋）
- `_esc()` 用 `if value else ""` 判斷是否要跳脫，如果哪天被拿去處理整數 `0`／`False` 這種合法但
  falsy 的值會被誤轉成空字串。目前所有呼叫端（`chips_generator.py`、`html_generator.py`）都只餵
  字串型別的 `stock_id`／`stock_name`／族群名稱，不會踩到這個問題，純粹提醒以後如果擴充 `_esc()`
  的使用範圍（例如拿去處理數值欄位）要注意。

### 結論
- [x] 可以繼續下一個任務——三項自動化可驗證的項目都通過，`verify=False` TLS 風險那項 Developer
  已明確標註留給 Cody 自己決定，不在 Debugger 驗證範圍內。

---

## [2026-07-05] 驗證 - `--realtime` crash 修復（pd.NA 布林值判斷，commit `e8dd27d`）

### 驗證方式
- 查 git log 確認目前 code 狀態；跑全專案測試；追 `get_chips_today()` 唯一消費端的實際程式碼

### ✅ 驗證通過（三項checklist）
- **全專案測試**：75 個測試（不是原本認知的 79 個——少的 4 個是 `tests/test_data_generator.py`，隨整支檔案一起被 revert 掉了），**74 過、1 個既有環境問題**（`test_scan_patterns_returns_list` 需要本機真的有 `data/screener.db`，debug 資料夾沒有這檔案，跟本次修復無關，籌碼頁 review 時就發現過同一個環境限制）。
- **`--realtime` 不會再 crash**：不需要真的重跑一次去賭，因為原本會炸的程式碼路徑已經不存在——中途發生 commit `71aa41e`「首頁 index.html 改回 html_generator.py 產生，React 前端移到 react-frontend-redesign 分支」，`export/data_generator.py`（這次 crash 修復的檔案）整支被刪除。`--realtime` 跟平常模式共用同一個 `run()` 函式，都是呼叫 `generate_html()`（`export/html_generator.py`），`main.py` 現在完全沒有任何地方 import 或呼叫 `data_generator`，原本的 crash 現場已經從程式碼裡消失，邏輯上不可能再重現同一個 bug。
- **檢查其他呼叫端有沒有同樣的 `... or 0` 危險寫法**：追了 `get_chips_today()`（FULL OUTER JOIN 那個函式）唯一的消費端 `main.py:430 chips_df = get_chips_today(...) → generate_html()`。`html_generator.py` 本來就用安全的 `_na(v): return 0 if (v is None or pd.isna(v)) else v`（第 196、330、513 行各自重複定義一次，小小的重複但邏輯是對的），沒有沿用 `data_generator.py` 那種危險的 `x.get(...) or 0`。另外也查了 `chips_generator.py:638`、`screener/institutional.py:247` 類似的 `or 0` 寫法，但那邊資料源是單一表查詢（不是 FULL OUTER JOIN），欄位由 `_parse_num()` 保證一定是實際 int、經過 `int(t_net) if t_net is not None else None` 轉換成 plain Python 型別，不會出現 `pd.NA`，風險跟 `get_chips_today()` 的 join 情境不同。

### 🟡 建議改善（不阻擋）
- `html_generator.py` 的 `_na()` helper 在同一支檔案裡重複定義 3 次（196/330/513 行），完全一樣的一行邏輯，可以抽成 module-level 函式，避免以後改邏輯漏改其中一處。

### 結論
- [x] 可以繼續下一個任務——三項驗證都通過，這則任務可以標記完成。不是因為原本的 fix 被實際驗證跑過，而是上層決定（revert 前端）連帶把會炸的程式碼整支清掉了，原始 crash 場景已經不可能重現。

---

## [2026-07-04] 報告＋修復 - Section 8「大戶持倉」永遠空白（Cody 授權 Debugger 直接修）

### 🔴 找到的問題
`docs/chips.html` Section 8（大戶持倉連增/連減排行）一直顯示「無大戶持倉資料（尚未執行
--update-shareholder）」，但這句話是誤導的——`shareholder` 表其實已經有 7 週資料
（2026-05-08 ~ 2026-06-26，`--backfill-shareholder 8` 確實成功跑完了）。

**根因**：`--update-shareholder`（抓最新週）跟 `--backfill-shareholder`（補歷史週）是兩條
分開呼叫的路徑，`_add_week_change_streak()` 只在「寫入當下」處理那一批資料，不會回頭重算
已經寫入的舊批次。實際發生順序：
1. `--update-shareholder` 先跑，寫入最新週 `2026-06-26`——當時 DB 是空的，找不到更舊的週可
   比，`week_chg=NULL, streak=0`（這在當下是正確答案，沒有前一週可比）
2. `--backfill-shareholder 8` 後來才跑，依序補進 `2026-05-08 ~ 06-12`，這 6 週彼此之間算
   得都對
3. 但沒有任何呼叫再回頭重算 `06-26`——即使現在已經有 `06-12` 可以當基準了，它的
   `week_chg`/`streak` 還是凍結在步驟 1 寫入當下的錯誤初始值
4. `get_shareholder_top()`（`screener/database.py:258`）只抓「每支股票最新一筆」= 全部都
   是 `06-26` = 全部 `streak=0`
5. `chips_generator.py:660-661` 篩選 `streak>0`/`streak<0` 建 Top 30/20 榜單，全部落空

實測驗證：修復前直接查 DB，`2026-06-26` 這天 1037 筆 **100% `streak=0`、100%
`week_chg=NULL`**，沒有例外，不是少數個股的問題，是整批凍結。

這是**結構性問題**，只要「backfill 補歷史」跟「update 抓最新」分開跑、且沒有「回頭重算最新
一週」這一步，每次都會重現一樣的空白。

### ✅ 已修（Cody 授權直接改）
- `scrapers/shareholder.py` 新增 `recompute_latest_streak()`：用 `ROW_NUMBER() OVER
  (PARTITION BY stock_id ORDER BY date DESC)` 抓每支股票目前資料庫裡最新一筆（rn=1）跟
  次新一筆（rn=2）比較，重算 `week_chg`/`streak` 並 `UPDATE` 回 DB。不用重打 TDCC，
  `lv12_15_pct` 已經在 DB 裡，只是重算兩個衍生欄位。用 rn=1/rn=2 逐股比較（而非假設整批
  同一個 `write_date`），可以正確處理個別股票資料缺一週的情況。
- 同時把 `_add_week_change_streak()` 裡重複的 streak 方向邏輯抽成 `_streak_step()` 共用
  helper，兩處呼叫同一份邏輯，避免以後改其中一處漏改另一處。
- `main.py::_backfill_shareholder()` 收尾時自動呼叫 `recompute_latest_streak()`，往後每次
  backfill 完成都會自動修正最新週，不用手動介入。
- 新增 2 個測試（`tests/test_shareholder.py`）：`test_recompute_latest_streak_fixes_week_
  frozen_before_backfill` 直接重現「先寫最新週、後補歷史週」的真實情境，驗證重算後
  `week_chg`/`streak` 正確；`test_recompute_latest_streak_skips_stock_with_only_one_week`
  驗證無前值可比時不會出錯。5 個 shareholder 測試、全專案 78 個測試全過。
- **已對正式 `data/screener.db` 實跑修復**：修復前 `2026-06-26` 全數 `streak=0`；修復後
  分佈為 `streak=-1` 485 檔、`streak=0` 93 檔、`streak=1` 459 檔，`week_chg` 全部非空。
  直接呼叫 `get_shareholder_top()` + `_shareholder_table()` 驗證：連增 462 檔、連減 485
  檔，渲染結果不再是「無資料」。

### 結論
- [x] 已修並加測試、已對正式 DB 實跑修復——下次 `python main.py` 重新產生
  `docs/chips.html` 時 Section 8 就會正常顯示；往後每次 `--backfill-shareholder` 收尾都
  會自動重算，不會再需要手動修

---

## [2026-07-03] 報告 - TPEx 三大法人／融資融券資料源驗證（commit `3daaee5`）

### 🔴 數據問題（需立刻修）
- 問題：`processors/performance.py::calc_meta_chips_signals()` 第 626 行 `meta_stock_count = universe.groupby("meta_sector")["stock_id"].count().to_dict()` 把分母改回算「整個族群成分股數（TWSE+TPEx）」，但 `main.py` 第 79-102 行 `fetch_institutional_tpex()` 是包在自己的 `try/except`，抓取失敗時只 `logger.warning(...)` 然後整段跳過，不會 fallback、不會標記、不會阻擋後續流程。
  重現方式（推論，非本機重現，因為今天 TPEx API 剛好正常）：任何一天 TPEx OpenAPI 逾時／改版／服務中斷時，`institutional` 表當天只會有 TWSE 資料，但 Section 5「外資買超比例」分母仍然照樣算 TWSE+TPEx 全族群成分股數。對 TPEx 佔比高的族群（例如「半導體設備」86 檔裡 57 檔是 TPEx、「軟體/雲端」83 檔裡 57 檔是 TPEx）比例會被系統性低估，且完全沒有警示——這正是 2026-07-02 那次報告修過的同一類 bug（當時用「分母排除上櫃」當安全網），這次把安全網拿掉、改成「賭 TPEx 每天都會成功」，沒有補等效的防呆。
  相關 log／程式位置：`main.py:101-102`（`logger.warning("TPEx 三大法人寫入失敗: %s", exc)`，只 log 不做其他處理）、`processors/performance.py:626`。
  影響：`export/chips_generator.py` 同一次改動把原本「⚠️ 三大法人資料目前只有上市來源」的警語整段拿掉（diff 見下方），代表往後真的遇到 TPEx 抓取失敗時，使用者在頁面上完全看不到任何提示，會把偏低的比例誤讀成準確數字。
  建議修法（擇一）：(a) `calc_meta_chips_signals()` 分母改成用「當天 institutional 表裡實際有資料的股票所屬交易所」動態判斷，而不是固定用 universe 全表；(b) `main.py` 在 TPEx 抓取失敗時寫一個旗標（例如當天 log 或一個 state 檔），`chips_generator.py` 讀到旗標時把警語文字帶回來。

### 🟡 建議改善
- `scrapers/chips.py::fetch_institutional_tpex()` docstring（第 113 行）寫「TWSE T86 是併在自營商（dealer）類別下」，這句話跟我實際打 TWSE T86 API 驗證到的結構不符：TWSE 的『外資自營商』（row[7]，`外資自營商買賣超股數`）根本沒有被併進 `dealer_net`（row[11] 只對應『自營商買賣超股數』，定義上就是不含外資自營商的自營商自身部位，跟 TPEx 的 `Dealers-Difference` 概念一致），`fetch_institutional()`（scrapers/chips.py 第 75-78 行）現在的寫法是把 row[7] 直接丟掉，三個欄位都沒有它。
  也就是說 TWSE 的 `foreign_net + trust_net + dealer_net` 理論上不保證等於 `total_net`（差額就是被丟掉的 row[7]），跟 TPEx 那邊刻意做到『恆等式必成立』的設計不是同一個口徑。
  目前完全沒有實際影響：我直接打了 TWSE（2025-07-01、2026-01-01、2026-05-01、2026-06-01、2026-06-30、2026-07-02，涵蓋近一年抽樣）跟 TPEx（2026-07-02 全量 930 筆）的即時 API，兩邊的『外資自營商』欄位全部是 0，沒有一筆例外，所以現在恆等式剛好都成立，只是巧合，不是程式保證的。
  建議：把 docstring 改成如實描述現況（TWSE 目前直接捨棄外資自營商欄位、TPEx 折入 dealer_net），並在 `fetch_institutional()` 加一行註解說明『外資自營商』欄位長期觀察下來恆為 0，如果哪天不是 0，`foreign_net`/`dealer_net` 兩邊交易所的口徑就會不一致，屆時要重新評估要不要也把它折進 TWSE 的 dealer_net。

### ✅ 驗證通過
- Section 5「外資買超比例」實際產出數字合理：直接查今天（2026-07-02 資料）產出的 `docs/chips.html`，「半導體設備」53/86＝62%、「軟體/雲端」49/83＝59%。分子（53、49）明顯超過各自純 TWSE 檔數（半導體設備 TWSE 只有 29 檔、軟體/雲端 TWSE 只有 26 檔），證實 TPEx 股票確實有被正確併入分子與分母，不是只有分母變大、分子沒跟上的半吊子狀態。
- TPEx OpenAPI 欄位口徑對照：直接打 `tpex_3insti_daily_trading`（930 筆全量）跟 `tpex_mainboard_margin_balance` 即時驗證，複現 Developer 的數學恆等式驗證結果（`foreign_net+trust_net+dealer_net==total_net`，0 筆誤差），且欄位語意（`ForeignDealers-Difference`＝外資自營商、`Dealers-Difference`＝自營商自身、`SecuritiesInvestmentTrustCompanies-Difference`＝投信）跟程式碼裡對應的 key 命名一致，沒有抓錯欄位。
- TWSE T86 欄位順序對照：直接打即時 API 驗證 19 欄位語意，`row[4]`＝外陸資買賣超(不含外資自營商)、`row[10]`＝投信買賣超、`row[11]`＝自營商買賣超（不含外資自營商）、`row[18]`＝三大法人合計，程式碼裡引用的 index 語意正確（唯一落差是上面 🟡 提到的『外資自營商』被丟棄問題，不影響目前已驗證的欄位）。
- TPEx／TWSE 回應日期不對齊時的處理邏輯（`main.py:90-91`、`133-134`）沒有 crash 或誤刪風險：`DELETE FROM institutional WHERE date = ? AND stock_id IN (SELECT stock_id FROM inst_tpex_df)` 有限定 `stock_id` 範圍，不會刪到同一天 TWSE 剛寫入的資料；但今天實際兩邊剛好同一天，沒有測到真正錯開的情境，這點跟 debug-tasks.md 原本寫的一樣，維持「邏輯上安全、但未實測過」的結論。

### 結論
- [x] 需要修改後再確認 —— 🔴 那項（TPEx 抓取失敗時分母不會跟著調整，且警語已被拿掉）建議在下一輪處理，其餘（🟡 docstring 用詞、Section 5 數字、欄位口徑）都可以先繼續其他任務，不阻擋。

---

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
- [x] 需要修改後再確認 — 已於下方驗證通過（見 commit `8e61d71` 驗證報告）

---

## [2026-07-02] 驗證 - commit 8e61d71「html_generator UnboundLocalError(pd) + moneydj 股票代號解析誤判」

### 驗證方式
- `grep -n "import pandas as pd" export/html_generator.py` 確認區域 import 是否清乾淨
- 靜態 review `scrapers/moneydj.py::_parse_stock_table()` 正則式改動
- 執行測試：`pytest tests/test_moneydj.py -v`、全專案 `pytest`（70 個測試，69 過 / 1 失敗，失敗為已知環境問題，見下方說明）
- 手動直接呼叫 `_meta_stock_cards()`／`_stock_table()`／`_stock_card_html()` 三個函式並傳入空 `chips_df`，重現原始 crash 情境

### ✅ 驗證通過（對照 debug-tasks.md 的「請 Debugger 驗證」清單）
- **`UnboundLocalError` 修復確認生效**：手動用空 `chips_df`（`pd.DataFrame()`）直接呼叫三個函式，全部正常回傳 HTML 字串，沒有再拋出 `UnboundLocalError`（修復前這個情境會 100% 觸發崩潰）。
- **區域 import 清除完整**：`grep -n "import pandas as pd" export/html_generator.py` 只剩模組頂部第 2 行，`_stock_card_html`／`_stock_table`／`_meta_stock_cards` 三處區域 import 都已移除，沒有遺漏。
- **`scrapers/moneydj.py` 正則式修正邏輯正確**：`r'^(91\d{4}|\d{4})(.*)$'` 明確區分「91 開頭 6 碼 TDR」跟「一般 4 碼股票」兩種合法格式，不會再貪婪多吃。對應測試 `test_scrape_industry_sectors_stops_at_4_digit_code`、`test_scrape_industry_sectors_keeps_6_digit_tdr_code` 皆通過。
- **`stock_universe.csv` 674191 → 6741 修正確認**：檔案裡已無 `674191`，`6741`（APP*-KY）只出現一次，跟既有代號沒有重複。

### 🟡 建議改善（非阻擋項）
- `export/html_generator.py` 目前沒有任何專屬的自動化測試（`tests/` 底下沒有 `test_html_generator.py`）。這類「函式內區域 import 導致 `UnboundLocalError`」的錯誤特性是：只有在特定分支（`chips_df` 為空）才會觸發，靜態 review 很容易漏看（這次稍早 review commit `6993d36` 時我自己就漏掉了）。建議至少補一個「`chips_df` 為空時 `generate_html()`／這三個子函式不會 crash」的回歸測試，避免以後有人在 `pd.DataFrame()` fallback 前面加類似的區域 import 又重演一次。

### 結論
- [x] 可以繼續下一個任務 — commit `8e61d71` 的 CRITICAL 修復經直接函式呼叫驗證確實解決了 `UnboundLocalError`，moneydj 正則式修正跟 stock_universe.csv 代號修正也都正確，沒有發現新問題

---

## [2026-07-02] 驗證 - commit f4f3795「scan_volume_turnover 歷史資料不足時算出誤導性量倍數」（Cody 要求再次確認）

### 驗證方式
- 靜態 review `screener/signals.py::scan_volume_turnover()` 完整邏輯
- 執行測試：`pytest tests/test_signals.py -v`（2 個測試全過）

### ✅ 驗證通過
- **`_MIN_WINDOW_DAYS = 20` 門檻套用位置正確**：`window = grp.iloc[window_start: today_idx + 1]`（涵蓋今天這筆），`if len(window) < _MIN_WINDOW_DAYS: continue` 在計算 `vol_max`／`vol_avg` 之前執行，資料不足時確實會在算出誤導性量倍數之前就跳過，不會有「先算完才丟棄」的競態問題。
- `test_detects_signal_with_sufficient_history`：25+ 筆歷史、符合三條件時正常產生訊號，且 `vol_window_days >= 20` 的斷言正確驗證了門檻確實用的是實際窗口天數。

### 🟡 建議改善（測試精準度，非程式邏輯問題）
- `test_skips_stock_with_insufficient_history` 這個測試雖然 `assert results == []` 成立，但逐行手算後發現：它實際上是被**更早的「② 收跌」條件**擋下（測試資料裡 `today.close=110 > prev.close=100`，不滿足「收跌」），根本沒有走到 `_MIN_WINDOW_DAYS` 那道檢查。換句話說，**這個測試目前沒有真正隔離驗證『歷史資料不足時跳過』這件事**——就算把 `_MIN_WINDOW_DAYS` 改回舊版的 `< 2`，這個測試依然會通過（因為前面的條件②已經先擋掉了），無法在未來真的保護到這個修復。
  建議補一個測試案例：`today` 收跌、`prev` 漲停（滿足②③兩個硬性條件），但歷史資料只有 2~19 筆，確認確實是被 window 長度門檻擋下，而不是巧合被其他條件擋下。

### 結論
- [x] 可以繼續下一個任務 — production 邏輯本身經讀碼確認正確，`_MIN_WINDOW_DAYS` 門檻確實會在資料不足時跳過該股票，不影響這次驗證的正確性判斷；唯一發現是既有測試沒有精準隔離要驗證的路徑（🟡 非阻擋，建議之後補測試避免未來迴歸時測試失去保護力）

---

## [2026-07-02] 驗證 - commit e4a3536「TWSE 擋頁誤判成合法 CSV 導致日期被誤切回前一天」

### 驗證方式
- 執行測試：`pytest tests/test_twse.py -v`（7 個測試全過，含 3 個新增測試）與全專案 `pytest`（70 個測試，69 過 / 1 失敗，詳見下方說明）
- 靜態 review 完整呼叫鏈：`scrapers/twse.py::fetch_daily_prices()` → `scrapers/finmind.py::fetch_twse`（別名匯入）→ `fetch_prices_for_stocks()` → `main.py::run()` 探測股防呆邏輯
- 手動模擬三種情境驗證 `main.py` 第 328-352 行的探測股邏輯（`prices_df` 不含 2330 / 正常情境價格相同 / 正常情境價格不同）

### ✅ 驗證通過（對照 debug-tasks.md 的「請 Debugger 驗證」清單）
- **`tests/test_twse.py` 三個新測試邏輯正確**：html 擋頁（content-type 含 html）正確拋 `TWSEBlockedError`；content-type 沒標 html 但內容無法解析成 CSV（`ParserError`）也正確拋 `TWSEBlockedError`；合法的非 JSON CSV 回應（瀏覽器 UA 觸發）仍能正常解析，沒有把合法情況也誤判成擋頁（沒改過頭）。
- **判斷順序正確**：`fetch_daily_prices()` 先檢查 content-type 是否為 html，不是的話才嘗試 `pd.read_csv()`，解析失敗才 fallback 視為擋頁，跟合法「JSON 回應但 `stat != OK`」（走 `_parse_json` 的 `ValueError` 分支）完全分開，不會誤吞。
- **`TWSEBlockedError` 正確被上游吞掉、不會讓整個流程崩潰**：`TWSEBlockedError` 繼承 `RuntimeError`，`fetch_prices_for_stocks()` 用 broad `except Exception` 包住 TWSE 抓取，被封鎖時只會丟掉 TWSE 那個 frame（`logger.error` 記錄），`prices_df` 會正常退化成只剩 TPEx 資料，不會拋到上層。
- **`main.py` 探測股邏輯手動模擬三種情境，全部正確**：
  1. `prices_df` 不含 2330（模擬 TWSE 整批被擋）→ 正確進入 `elif prev_csv.exists():` 的 warning 分支，不切 `trade_date`
  2. 正常情境、2330 價格跟前一天相同 → 正確觸發切日期（跟修復前行為一致，沒有破壞原本「市場尚未更新」防呆邏輯）
  3. 正常情境、2330 價格跟前一天不同 → 正確不切日期
- 沒有發現上市/上櫃資料來源混用的問題，這次修復完全侷限在 TWSE 抓取路徑跟探測股防呆邏輯。

### 已知非本次改動造成的問題
- 全專案 `pytest` 1 個失敗：`tests/test_patterns.py::test_scan_patterns_returns_list`，原因是這個 debug 工作目錄底下沒有 `data/screener.db`（`_duckdb.IOException: database does not exist`），是重複出現過好幾次的既有環境問題，與本次改動無關。

### 結論
- [x] 可以繼續下一個任務 — commit `e4a3536` 的兩個疊加 bug（TWSE 擋頁誤判成合法 CSV、探測股邏輯退而求其次誤判市場未更新）修復邏輯正確、測試齊全，手動模擬三種情境皆符合預期，沒有發現新問題

---

## [2026-07-02] 報告 - `data/` 資料正確性全面 review（DuckDB + stock_universe.csv）

### 審查方式
- 直接查詢 `tw-sector-tracker/data/screener.db`（Developer 資料夾的正式資料，372,539 筆、1040 檔、2025-01-02~2026-07-02）
- `daily_prices`：null/負值/漲跌停範圍 sanity check、跟前一筆比價格暴增暴跌 5 倍以上的離群點全表掃描
- `stock_universe.csv`：重複 `stock_id`、缺值、`exchange` 合法值、族群規模分佈
- `institutional`／`margin` 表：資料涵蓋範圍、null 值
- 補充說明：這個 debug 分支本地的 `data/`（gitignored）目前只有今天 `--realtime` 跑出來的單日快照（1038 檔、每檔 1 筆），不是完整歷史，這次 review 的是 Developer 資料夾裡真正在用的正式資料

### 🔴 數據問題（需立刻修）
- 問題：`daily_prices` 裡股票 `3114`（好德，TPEx，連接器族群）在 `2025-04-25` 這天的 `close` 是 `2118.96`，前後幾天正常價格都在 NT$20 上下（4/24 收 20.90、4/28 收 21.57），比值分別是 ×101.4 跟 ×0.0102——幾乎精確是 100 倍的落差，典型的小數點/單位換算錯誤（不是股票分割，分割不會在 3 天內完全復原）。
  位置：`data/screener.db` 的 `daily_prices` 表，`stock_id='3114'`, `date='2025-04-25'`。
  影響：
  - 這一筆壞資料同時污染了兩天的 `change_pct`：`2025-04-25` 顯示漲幅 `+10036.37%`、`2025-04-28` 顯示跌幅 `-98.98%`，兩者都是不可能發生在台股（漲跌停 ±10%）的數字，但目前程式沒有任何欄位範圍檢查，會被當成正常資料吃進所有依賴 `change_pct`／`close` 的計算（`scan_volume_turnover`、累積漲跌 badge、拐點偵測等），如果剛好落在某支股票的 lookback 窗口內，會嚴重扭曲該股票當時的訊號判斷。
  - 全表掃描（`close / prev_close` 比值 >5 倍或 <1/5）只抓到這一組離群點，說明**不是系統性問題**，是單一資料源在單一日期寫入時的一次性錯誤，但既然抓到了就要修。
  - `3114` 是 TPEx 股票，寫入路徑會經過 FinMind（Phase 2）或 yfinance（`--backfill-yf`）其中一條，建議 Developer 先查 FinMind API 對 `3114` 在 `2025-04-25` 的原始回應，若正常則改查 `yfinance.Ticker('3114.TWO').history()` 同一天的數字，找出是哪個資料源、哪個轉換步驟出的錯（例如漏除 100、或誤把某個單位當成分當成元）。
  重現方式：`SELECT * FROM daily_prices WHERE stock_id='3114' AND date BETWEEN '2025-04-24' AND '2025-04-28'`。

### 🟡 建議改善
- `stock_id='2321'`（東訊，TWSE，網通設備）在今天（`2026-07-02`）的即時行情快照裡 `close=0.0`、`volume=1`，前三天都正常收在 `13.9`。這支股票平常成交量就極低（近日 volume 常是 0），研判是即時行情源對零成交/極冷門股回傳了 `0` 而不是「延用前一筆」或「標記缺值」，是 `--realtime` 路徑上的一個資料填補瑕疵。目前只有這一筆，還沒造成下游計算錯誤，但如果隔天這支股票又正常成交，`prev_close=0` 會讓當天 `change_pct` 計算除以 0 或算出離譜倍數（重演跟 3114 類似的情況）。建議即時行情抓取對 `close<=0` 或缺值的股票，改成跳過寫入該筆（沿用前一交易日收盤）而不是寫入 0。
  位置：`scrapers/realtime.py`（`fetch_realtime_prices`，實際路徑未逐行 review，僅從結果反推）。
  [x] Developer 已補強 — 見 debug-tasks.md `[2026-07-02] 即時行情零成交股 close=0 防呆補強`。`fetch_realtime_prices()` call site 補上明確的 `price <= 0` 擋，但無法在目前的 `data/screener.db` 重現這筆（本機查到 `2321` 今天實際收 `13.7`，非 0），研判是 Debugger 當時另一份快照資料夾的單次快照，麻煩之後若再遇到附上當時 CSV 原始內容協助對照。
- `stock_universe.csv` 的 `meta_sector='生物辨識'` 只有 2 檔股票（`5203` 訊連、`6910` 德鴻），是全部 41 個 meta_sector 裡最小的（其餘最小也有第二小門檻以上）。
  [x] Cody 確認：維持現狀即可，不是分類遺漏。
- `institutional`（1424 檔）／`margin`（1280 檔）涵蓋的 `stock_id` 數量都比 `stock_universe.csv`（1040 檔）多，研判是 T86／MI_MARGN 原始資料涵蓋全市場（含 ETF、權證等不在掃盤名單內的標的），目前看起來沒有造成問題（`inst_map.get(sid)` 用字典查找，多出來的 key 不會被存取到），純粹記錄一下，非阻擋項。

### ✅ 驗證通過
- `stock_universe.csv`：1040 筆、`stock_id` 無重複、`exchange` 欄位只有合法值（`TWSE`=515／`TPEx`=525，無缺漏無異常值）、`stock_id`/`stock_name`/`exchange`/`meta_sector`/`sub_sector` 五個核心欄位皆無缺值。
- 「⚠️ 也在 XXX」的重複族群註記（345 檔有此標記，例如鴻海同時也在機器人/自動化、消費電子等 11 個相關族群）確認只是 `note` 欄位的描述性註記，**不是**真正的資料列重複——每支股票在 `stock_universe.csv` 裡仍然只有一個 `(meta_sector, sub_sector)` 主分類，實際計算不會有同一族群內雙重計入的問題。
- `daily_prices` 歷史深度健康：TWSE（515 檔）與 TPEx（525 檔）中位數皆為 360 筆，最小值 93～98 筆（新上市/上櫃股票資料自然較短，合理），沒有發現任何交易所被系統性漏抓的跡象。
- 沒有負成交量；全表 close/prev_close 比值離群掃描只抓到上述 2 筆真正的異常，其餘 372,537 筆價格序列在檢測範圍內看起來合理（含少數興櫃類無漲跌停限制個股的 >10% 波動，屬正常）。
- 族群規模（meta_sector 層級）中位數 18 檔、最小 2 檔，沒有出現「0 檔」或明顯遺漏整個族群的情況。

### 結論
- [x] 已修復 — 🔴 `3114` 離群資料已由 Developer 修正（見 debug-tasks.md `[2026-07-02] 修正 3114 離群資料`），🟡 兩項建議改善仍待之後找時間處理，不阻擋其他任務
  - ⚠️ **更正（2026-07-03 複驗）**：這台筆電（`codyliu`）上的 `data/daily_prices/2025-04-25.csv` 與 DuckDB **仍是髒值 2118.96**，此修正在本機不存在，詳見下方 `[2026-07-03] 驗證 - debug-tasks 5 則任務` 的 🔴 項。

---

## [2026-07-03] 驗證 - debug-tasks.md 五則任務逐項複驗（TPEx 資料源 / 籌碼頁 / close=0 防呆 / Pages 部署 / 3114）

### 驗證方式
- 靜態 review：`scrapers/chips.py`（TPEx 兩支新函式 + TWSE 對照）、`main.py::_update_chips_db`／`_backfill_shareholder`、`processors/performance.py::calc_meta_chips_signals`、`scrapers/realtime.py`、`screener/institutional.py`、`.github/workflows/pages.yml`
- 實測 API：直接打 TWSE T86（1325 檔）與 TPEx `tpex_3insti_daily_trading`（930 檔），核對欄位語意與恆等式
- 實跑：`_best_price` 假造 item 測試、`calc_meta_chips_signals` 對 Developer 正式 DB 實跑、DuckDB 全表離群掃描
- 資料源：Developer 資料夾 `C:\Users\codyliu\Desktop\tw-sector-tracker\data\screener.db`（本機這份，`data/` 為 gitignored、不隨 git 同步）

### 🔴 數據問題（需立刻修）
- 問題：**任務⑤「修正 3114 離群資料」在這台機器上根本沒有生效**。debug-tasks.md 記載「用 2118.96/100=21.19 校正…已執行 `python main.py --reimport` 重建 DuckDB」，但實測本機：
  - `data/daily_prices/2025-04-25.csv` 第一欄仍是 `3114,2118.96,2098.06,10036.37,25`（未校正）
  - `data/daily_prices/2025-04-28.csv` 仍是 `3114,21.57,-2097.39,-98.98,12`（仍拿髒值 2118.96 當前一天算出 -98.98%）
  - DuckDB `daily_prices` 查 `3114`：2025-04-25 `close=2118.96, change_pct=10036.37`、2025-04-28 `change_pct=-98.98`，**跟修復前一模一樣**
  位置：`data/daily_prices/2025-04-25.csv`、`2025-04-28.csv`、`data/screener.db`（本機 `codyliu` 筆電）
  研判：`data/` 是 gitignored，不隨 git 同步。修正很可能是在**桌電（`cody`）**做的，這台筆電的 `data/` 從沒拿到校正後的檔案；`--reimport` 若在本機跑，也只會忠實匯入這份仍是髒值的 CSV。
  影響：只要在這台機器執行 `python main.py`，`3114`（好德，TPEx）在 2025-04-25 附近的 126 日窗口內所有依賴歷史行情的訊號（巨量換手、累積漲跌、拐點偵測）都仍被 100 倍髒值污染——這正是 CLAUDE.md 最怕的「不報錯、但給錯結果」。
  重現方式：`grep "^3114," data/daily_prices/2025-04-25.csv`（本機）→ 仍是 2118.96。
  建議：確認到底哪台機器是「主力執行 main.py」的機器。若是桌電，本機這份髒 CSV 影響有限（但仍建議同步）；若這台筆電也會實際產出上線頁面，必須把校正後的 `2025-04-25.csv`／`2025-04-28.csv` 複製過來、重跑 `--reimport`。根本解：`data/` 既然 gitignored，跨機器的資料修正沒有同步管道，這類「純資料修正」在多機器環境下很容易只在一台生效。

### 🟡 建議改善
- **任務①：TPEx 與 TWSE 的 `dealer_net` 口徑不一致（同名不同義）**。實測欄位語意：
  - TWSE T86 `dealer_net = row[11]`（自營商買賣超 = 自行+避險），**不含外資自營商**（row[7] 獨立、未存進任何欄位；row[18] 三大法人合計才含它——已用 1325 檔驗證 `row4+row7+row10+row11==row18`）
  - TPEx code `dealer_net = ForeignDealers-Difference + Dealers-Difference`，**併入外資自營商**（`scrapers/chips.py:135`）
  兩邊 `dealer_net` 定義不同，差額 = 外資自營商。測試日（2026-07-02）TWSE 與 TPEx 的外資自營商**剛好都是 0**（所以兩邊恆等式都成立、Developer 也因此驗證 0 誤差），但外資自營商非零時就會發作。目前 `dealer_net` 只在 `screener/institutional.py` 的顯示欄位被消費、不進任何跨所彙總，所以實務影響小。若要口徑嚴格一致，建議 TPEx `dealer_net` 改成只用 `Dealers-Difference`（不加 `ForeignDealers`）—— 代價是 TPEx 的「foreign+trust+dealer==total」恆等式會差一個外資自營商，但這剛好跟 TWSE 的行為一致（TWSE 存的三欄和本來就 ≠ total）。附註：`foreign_net`／`trust_net`／`total_net` 三欄口徑**都一致**（Section 5 用的 `foreign_net` 沒問題）。
- **任務①：Section 5 買超比例在「TWSE/TPEx 日期不同步」時會被低估**（Developer 明說沒測到的情境）。`calc_meta_chips_signals` 的 `today = all_dates[-1]`（`performance.py:656`）取 institutional 表最大日期；TPEx OpenAPI 只能抓「當下」、TWSE T86 抓 trade_date，兩者發布時間若差一個週期，會落在不同 `date` 分區。此時 `today_inst` 只含「日期等於 today 的那個交易所」的股票（分子），但分母 `meta_stock_count` 永遠是全族群（TWSE+TPEx）→ `foreign_buy_ratio = buy_count/total_stocks` 被系統性低估。這跟任務②原本要修的「分子/分母交易所範圍不一致」是同一類 bug，只是換成由日期不同步觸發。matched 日（如 2026-07-02）正常。建議：計算 today 快照類指標時，分子分母的交易所範圍要一致（例如 today 只取「TWSE 與 TPEx 都有資料的最新日期」，或分母也跟著 today 實際涵蓋的交易所收斂）。
- **任務③：`2321` 在 DB 的 2026-07-02 `close=0.0` 舊資料仍殘留**。`realtime.py` 的 `price<=0` 防呆只防「未來寫入」、不清舊資料。此筆為防呆上線前寫入的髒點。**確認沒有 cascade**：2321 在 2026-07-03 的 `change_pct=-7.91%` 是對前一交易日 13.9 正確算出（即時 API 自帶參考價，不吃 DB 的 0），非我先前預警的除以 0。影響僅限「任何直接讀 2321 這天 close 的消費者」，範圍小。可考慮把這筆補成前一日 13.9 或標記缺值。
- **任務②：`foreign_buy_ratio` docstring 標示錯誤**。`performance.py:615` docstring 寫「外資買超股數 / META 總股數」，但實際計算（`:727`）是 `buy_count / total_stocks` = 「外資買超**檔數** / META 總**檔數**」，分子是股票數不是股數。純文件不符，改正即可。

### ✅ 驗證通過
- **任務①恆等式**：TPEx `tpex_3insti_daily_trading` 930/930 檔 `foreign_ex+foreign_dealer+trust+dealer==total` 成立；5 個對應欄位 key 全部存在、無打錯字。TWSE T86 1325/1325 檔 `row4+row7+row10+row11==row18` 成立。
- **任務①口徑（一致的部分）**：`foreign_net`（兩所都排除外資自營商）、`trust_net`、`total_net`（兩所都含外資自營商）三欄定義一致，不會同名不同義。
- **任務①串接**：`_update_chips_db` TWSE/TPEx 各寫各自日期分區；TPEx 的 DELETE 加 `AND stock_id IN (SELECT stock_id FROM <tpex_df>)`，加上 TWSE(上市)／TPEx(上櫃)代號本就不重疊，不會互相覆蓋刪除；日期對不上只 `logger.info` 提示、兩段互相獨立不阻擋，行為符合預期。
- **任務①Section 5 實跑**：對正式 DB 跑 `calc_meta_chips_signals`，41 個 META 全部正常回傳（無 crash → 任務②的 `universe` 多帶 `exchange` 欄沒弄壞下游）。高上櫃佔比族群買超檔數合理且明顯反映 TPEx：軟體/雲端 49/83、MCU/嵌入式 22/27、遊戲/電競 5/17（TPEx 82%）——分子確實計入上櫃股票，不再被當缺資料跳過。
- **任務② `_backfill_shareholder` 日期順序**：`target_dates = list(reversed(available[:weeks]))`（`main.py:260`）由舊到新依序寫入，配合 `save_to_db` 「跟 DB 最新一筆比」的假設正確。（`week_chg`/`streak` 方向的實跑驗證需 Cody 跑 `--backfill-shareholder 8`，本機 DB 無多週資料，無法在此重現。）
- **任務② institutional.py docstring 單位**：已由「元」改為「股」（`:10` 明確標「institutional 表單位是股，非元」）。
- **任務③ close=0 防呆**：呼叫端 `if price is None or price <= 0: continue`（`realtime.py:127`）+ `_best_price` 各層 fallback 都 `return v if v>0 else None`。假造 4 種零值 item（`z="0"`／五檔全 `-`／`0_0_0`／今高今開 `0`）全部回 `None` → 跳過；正常盤（900.0）、漲停鎖死只有買方五檔（50.5）都正確取值。
- **任務④ Pages 部署設定**：`.github/workflows/pages.yml` 觸發條件 `push` to `master` + `paths: docs/**` 正確、用標準 `actions/upload-pages-artifact@v3` + `deploy-pages@v4`、`permissions`（pages: write, id-token: write）正確；`docs/.nojekyll`（0 bytes）存在。

### 未能在本機完成的驗證項（需 Cody 協助）
- **任務④ workflow 執行紀錄**：本機沒裝 `gh` CLI（bash 與 PowerShell 皆 `command not found`），無法跑 `gh run list --workflow=pages.yml` 確認實際觸發成功。debug-tasks.md 記載 Developer 已用 curl 確認網站更新到 2026-07-03，屬旁證。建議 Cody 有裝 gh 的機器上跑一次確認，或下次 `python main.py` push 後看 repo 的 Actions 頁。
- **任務② shareholder streak 方向**：需 `python main.py --backfill-shareholder 8` 實跑後查 `shareholder` 表 `week_chg`/`streak`（本機 DB 只有單週）。

### 結論
- [ ] 需要修改後再確認 — 🔴 `3114` 髒值在本機（`codyliu` 筆電）仍未修，先釐清「主力執行機器是哪台 + `data/` 跨機器同步策略」再決定要不要在本機重補；🟡 `dealer_net` 口徑不一致、Section 5 日期不同步低估、2321 殘留 0 值、docstring 標示錯誤四項為非阻擋改善項。任務①③④主體邏輯與②全部四項修正經 review／實測驗證正確。

---

## [2026-07-03] 報告 - `daily_prices` 全表資料品質稽核（Cody 要求確認「是否只有 3114 錯」）

### 稽核方式
- 對象：Developer 正式 DB `data/screener.db` 全表 `daily_prices` **373,874 筆**（1040 檔，2017-12-01 ~ 2026-07-03）
- 三種獨立錯誤偵測法交叉比對，避免單一門檻漏抓

### 🔴 硬錯誤 — 全表僅 2 筆（跟先前回報一致，無新增）
- `3114`（好德，TPEx）2025-04-25 `close=2118.96`（應為原始序列 ~22.3 / 還原序列 ~21.2）；連帶污染 2025-04-28 `change_pct=-98.98`。**源頭是 yfinance 本身**：實測 `yf.Ticker('3114.TWO').history()` 該日 raw close = 2230、還原 close = 2118.96（除息回溯 ×0.95），鄰近日 raw 22.00→22.70，真值 ~22.3 與 Yahoo 官網、FinMind 一致。**代表 `--backfill-yf` 會再抓回同一髒值，不能靠重抓修**。
- `2321`（東訊，TWSE）2026-07-02 `close=0.0`（應為 ~13.9）；未 cascade（07-03 change_pct 正確）。

### 交叉驗證（三法一致指向同 2 筆，無其他隱藏錯誤）
- **單日暴衝彈回掃描**（close 同時 > 前一日與後一日 R 倍）：R=5/3/2 三個門檻都只抓到 `3114`、`2321`——**沒有 2~4 倍的中等錯誤漏網**。
- **change_pct 內部自洽**（`change_pct` vs `change/(close-change)*100`）：37 萬筆只有 **1 筆**不一致，就是 `3114`——沒有系統性的漲跌幅計算 bug。
- **close≤0 / null**：只有 `2321` 那 1 筆；負成交量 **0**；重複 `(stock_id,date)` **0**。

### 🟡 灰色地帶 — 334 筆 |change_pct|>10.5%（非首日），判定絕大多數為真實事件
- 分佈：TPEx 216 + TWSE 118。台股有 ±10% 漲跌停，超過者理論上僅發生在減資／除權息／IPO 蜜月期／停牌復牌等無漲跌停日。
- 抽查最極端的幾檔（`4585` +51%、`4582` +45%、`7772` +84%、`6831` 2025-04 連續雙向 >10%）：全部是「**跳到新價位後維持住**」+ `change_pct` 內部自洽（例：4585 209.9/410.3=51.15% ✓），符合真實公司事件／2025-04 關稅股災的形態，**不是 3114 型的單值髒（單值髒會隔天彈回，已被上面掃描排除）**。
- 限制：無法用程式 100% 清完全部 334 筆（需比對公司減資／除權息事件表），但**未發現任何 100 倍或彈回型錯誤混入**。屬「已盡力查、殘餘不確定性低」。

### 🟡 停牌/冷門股未排除 — 2 檔（對應 CLAUDE.md「停牌股要正確排除或標注」）
- `6236`（中湛，TPEx）、`8291`（尚茂，TPEx）：收盤價連續 30~123 天完全不變、期間總成交量僅個位數（8291 連 123 天 17.1、總量 10）→ 幾乎無交易，疑似停牌／瀕臨下市。目前掃盤名單未排除，其凍結價與每日 0% 漲跌會混進量價/換手類掃描，建議標注或排除。

### 結論
- [x] 可以繼續下一個任務（就資料品質而言）— 全表交叉稽核確認硬錯誤僅 `3114`、`2321` 兩筆，無其他隱藏的離群髒值；334 筆超限多為真實事件、2 檔停牌股為完整性提醒。惟 `3114`／`2321` 的實際修正仍受「`data/` gitignored、雙機不同步」限制，需搭配上一則報告的同步策略處理

### 追記（2026-07-03，Cody 授權 Debugger 直接修）
- **`3114` 已在 `codyliu` 筆電修正**（Cody 明確授權「直接幫我改」）：手動改 `data/daily_prices/2025-04-25.csv`（close `2118.96`→`21.19`、change `0.29`、change_pct `1.39`）與 `2025-04-28.csv`（change/pct 對 21.19 重算為 `0.38`/`1.79`，close 21.57 不動），已跑 `python main.py --reimport` 重建 DuckDB（373,874 筆）。改後 DB 驗證 3114 序列 20.90→21.19→21.57→21.71 正常；重掃單日暴衝彈回只剩 2321、change_pct 內部不一致歸零。**值用 21.19（還原序列口徑，跟桌電一致）而非官網 raw 22.3，以維持與相鄰日 20.90/21.57 的口徑一致**。
- 兩台現況：桌電先前已修 21.19、筆電此次也修 21.19 → 一致。
- **`2321` 尚未修**：2026-07-02 close=0.0（該日 volume=1、幾乎未交易）。正確值不明確（建議 carry-forward 前一日 13.9 或移除該列），未擅自修，待 Cody 指示。task③ 的即時防呆已防未來復發。
  - ⚙️ **更新**：`2321` 已由 Cody 授權修成 `13.9` 並 reimport（FinMind 對 2321 這幾天普遍回 `close=0`、不可用，改用穩定真實價）。全表現已零硬錯誤。

---

## [2026-07-03] 報告＋修復 - 集保 streak going-forward 隱患（Cody 授權 Debugger 直接修）

### 背景
驗證 Task ②「`_backfill_shareholder` 日期順序」時，Cody 提出「希望以後同一個資料來源都 OK」。順序修正只保證**一次性歷史回補**正確；決定「以後」的是**每週例行更新**那條路（`_update_shareholder` → `save_to_db` → `_add_week_change_streak`），故額外 review going-forward 路徑。

### 🔴 找到的隱患（會讓 streak 靜默失真）
- `scrapers/shareholder.py::_add_week_change_streak()` 原本取「該股 DB 最新一筆」當 streak 比較基準：
  ```sql
  ... QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) = 1
  ```
  但 `save_to_db` 的順序是「先算 streak → 再 DELETE 同 date → INSERT」，且**沒有排除跟本次要寫的同一週**。
- 觸發情境（都很常見）：`_update_shareholder` 每次抓 TDCC「當前最新週」（`available_dates[0]`）。若①設**每日 cron** 跑 `--update-shareholder`、②同一週手動重跑、③TDCC 尚未出新週仍抓到同一週——本次 date 就跟 DB 既有那週相同，於是拿「上次寫的自己」當基準：`chg = 本週pct - 同週pct ≈ 0` → **streak 被洗成 0**，連增/連減週數失真（跟 Section 8 一開始空白同類的 streak 污染，觸發點在「重跑」）。
- 根因：streak 基準應是「**嚴格更舊**的週」，不是「最新一筆」（最新一筆可能就是自己）。

### ✅ 已修（Cody 授權直接改）
- `_add_week_change_streak` 的 prev 查詢加上 `AND date < ?`（本次寫入週），只跟真正更早的週比。對正常「舊→新」寫入行為不變（仍取前一週）；對「重跑同週」則正確排除自己、改抓更舊那週，streak 不再被洗掉。也順帶對「某股某週抓取失敗造成的週缺口」更 robust（會自動跟最近的更舊週比，方向仍正確）。
- 新增 `tests/test_shareholder.py`（3 個測試，全過）：連續上升 streak 累加、**重跑同週 streak 不被弄壞**（沒 guard 會失敗）、轉向時 streak 翻負。
- 這次修改只動 `_add_week_change_streak` 內部查詢條件，不影響 `_backfill_shareholder`／`_update_shareholder` 呼叫方式。

### 結論
- [x] 已修並加測試 — 回答 Cody「以後同一個資料來源 OK 嗎」：歷史（backfill 順序）+ 以後（每週更新重跑）兩條路現在都正確。建議之後例行更新可安心設每日 cron，不會再洗壞 streak。
