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
