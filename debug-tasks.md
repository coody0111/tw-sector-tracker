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
