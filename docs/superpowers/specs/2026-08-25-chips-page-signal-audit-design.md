# 籌碼頁（chips.html）重構前置：訊號有效性稽核 設計 (2026-08-25)

狀態：草案，待 Cody review（四級分類需逐項確認）

## 背景與問題

Cody 想重構籌碼頁，但一開始就卡在「不知道該怎麼下手、該做到怎樣的程度」，brainstorming 過程中
挖出更根本的問題：Cody 自己也不確定籌碼資料（外資/投信連買、大戶籌碼、融資警示…）到底有沒有
實際用得上的價值，一度想找外部 paper/文獻佐證。

討論後改變方向——這個專案已經有現成的回測框架（`screener/backtest.py`，
見 `docs/superpowers/specs/2026-07-14-backtest-framework-design.md`），能直接用**這個 app 自己
資料庫的真實歷史**驗證每個訊號有沒有 edge，比外部 paper（別的市場、別的資料源）更貼近實際使用
情境。查了才發現：`chips.html` 現況 9 個 tab（`export/chips_generator.py` 1535 行、輸出
`docs/chips.html` 1941 行，有機成長多次疊加功能），只有 5 個 tab 對應到 `CHIPS_RULES` 已定義的
回測規則，另外 4 個（越跌越買/外資偷偷買/董監持股，另加消融對照變體）從未被系統性驗證過。

「重構要做到怎樣的程度」這個問題，答案應該由「訊號有沒有用」決定優先順序，而不是純美感重排——
沒有證據支持的訊號不該繼續佔據頁面最顯眼的位置。

## 目標

1. 盤點 chips.html 9 個 tab 對應的回測規則覆蓋率
2. 補齊「越跌越買」「外資偷偷買」缺少的回測規則（`dip_buy`/`stealth_buy`），讓 9 個 tab 裡
   7 個有回測結果可查
3. 對回測框架核心機制做正確性 review（進出場時序、成本/漲停處理、基準/regime 分段），排除
   「數字本身算錯」的可能性，讓後續決策建立在可信的證據上
4. 依證據強度把 7 個已驗證 tab + 董監持股（樣本不足獨立列一類）分成四級，作為下一步資訊架構/
   視覺優先順序的依據

## 非目標 (YAGNI)

- **不調整任何規則的篩選門檻/權重去追求「跑出正的 edge」**——法人資料樣本僅約 4 個月（57-63
  個訊號日），硬調參數找 edge 容易 overfit、產出不可信的假陽性結果，比誠實承認「目前沒有」更
  危險。要改門檻是之後累積更多資料、有明確假設才做的獨立任務。
- **不在本次幫董監持股（`insider_holdings` 表）補回測**——集保資料查證後只有 3 個月頻快照
  （2026-05-01/06-01/07-01），樣本不足以支撐任何統計結論，做了也只是產出不可信的假結果。
- **不在本次進行實際視覺/資訊架構改版**——那是下一步，照 CLAUDE.md 規矩要先過
  `ui-ux-pro-max` skill 才動手，不在這份 spec 範圍內。
- **不改變 chips.html 上線頁面任何顯示邏輯**——這次新增的 `dip_buy`/`stealth_buy` 規則只存在
  於回測路徑（`python main.py --backtest-chips`），沒有動 `chips_generator.py` 任何
  `_build_section*()` 函式，頁面實際顯示的「越跌越買」「外資偷偷買」表格維持原本的族群層級
  計算方式不變。

## 方法論 review

讀過 `screener/backtest.py`（`run_backtest`/`_forward_return`/`_bench_return`/`_market_index`/
`_regime_at`）、`screener/institutional.py`（`scan_institutional`/`_calc_streak`/`_calc_cum_pct`/
`rank_joint_buy_candidates`/`rank_continuation_candidates`）、
`processors/performance.py::get_margin_divergence()`，確認：

- **進出場時序正確**：訊號日 D 收盤產生訊號 → **D+1 開盤進場**（開盤缺值退回 D+1 收盤）→
  D+1+N 收盤出場，沒有用到訊號當下還不存在的資料
- **連買天數/累計漲幅/融資背離全部嚴格回看**：一致用 `date <= trade_date` 或
  `window.tail(lookback)`，無前瞻偏誤（look-ahead bias）
- **成本/漲停處理正確**：交易成本從報酬扣一次，`excess = 已扣成本的報酬 - 基準`；`no_fill`
  （D+1 開盤 ≥ D 收盤 ×1.095）正確標記並在主結果剔除
- **regime 分段正確**：20 日回看報酬分多頭/盤整/空頭，只用訊號日以前的資料

**方法論 caveat（非 bug，但影響解讀）**：「大盤基準」不是加權指數 TAIEX，是 `daily_prices`
全部股票 `change_pct` 逐日簡單平均算出的「等權指數」——`docs/superpowers/plans/
2026-07-14-backtest-framework.md` 記錄這是刻意決定（當時這個 DB 沒有可用的 taiex 表接進這套
框架）。代表「超額報酬」的實際意思是「贏過所有股票的平均表現」，不是「贏過真正的大盤指數」。
11 條規則都用同一套基準比較，相對排序仍然站得住腳，只是數字不能直接等同新聞常見的「打敗大盤」。

## 回測結果總表

| Tab | 規則 | 樣本（訊號日/筆數） | 勝率 D+5/D+10/D+14 | 平均超額（全部，D+14） | 判讀 |
|---|---|---|---|---|---|
| 法人同步觀察 | `joint_buy` | 61日/377筆 | 44/44/43% | +1.55%（中位數 **-2.58%**） | 均值被少數大贏家拉正，非穩定 edge |
| 外資籌碼（連買） | `foreign_continuation` 系列（含 streak_only/price_only） | 61日/732-754筆 | 39/34-36/37-39% | **-0.42~-1.11%** | 全負，盤整/空頭更慘，3 種加權算法結果雷同→問題在訊號本身 |
| 投信籌碼（連買） | `trust_continuation` 系列（含 streak_only/price_only） | 57日/437-439筆 | 37-38/38-39/40% | ~0~+0.26% | 略優於外資版，仍不到 50% |
| 越跌越買 | `dip_buy`（本次新增） | 63日/1722筆 | 38/38/40% | **-0.53%** | 樣本最大、表現也偏差，原假設沒得到支持 |
| 外資偷偷買 | `stealth_buy`（本次新增） | 63日/1615筆 | 42/43/43% | +0.57% | 11 條裡表現相對最好，盤整 regime 到 +3%（n=8-9日，樣本小需存疑） |
| 大戶籌碼 | `tdcc_accumulation` | 29日/834筆（最小樣本） | 37/40/39% | +0.10%（多頭反而 **-0.51%**） | 無 edge |
| 融資警示 | `margin_bearish` | 63日/1154筆 | 避險命中 54/51/47% | 逐期遞減 | 短期（5日）尚可，長期退化——符合「示警」而非「預測」的定位 |
| 董監持股 | *（無法回測）* | 集保僅 3 個月頻快照 | — | — | 樣本量不足，暫緩 |

**結論**：11 條規則裡沒有一條展現出穩定、大樣本的正向 edge。表現最不糟的是 `stealth_buy`，也
只是接近打平；唯一在做自己該做的事的是 `margin_bearish`（它本來就是風險提示，不是選股訊號）。

## 分類結論（四級，待 Cody 逐項確認）

**🔴 證據最弱，建議砍掉或大幅降級**
- 越跌越買 — `dip_buy` 樣本最大（1722筆）、表現也最差，「跌時法人還連買」的假設被證偽

**🟡 有資訊價值，但要拿掉「訊號/建議」的語氣，改成觀察性描述**
- 外資籌碼／投信籌碼（連買）、大戶籌碼 — 知道「外資投信這陣子在買什麼」本身有資訊價值，但
  不該再用醒目色塊/徽章暗示「這是機會、跟著買會漲」
- 法人同步觀察 — 現況是全頁最顯眼的 hero 區塊（chips.html 開頁「候選觀察」），數據支持強度
  撐不起這個地位，該降到跟其他觀察性區塊同一層級

**🟢 保留現有定位，微調文案精確度**
- 融資警示 — 唯一「做到自己該做的事」的規則，文案更精確：強調「5日內參考價值較高，拉長就
  不準」

**⚪ 樣本不足，誠實標示「還不知道」（跟已驗證無效要用不同視覺語言）**
- 董監持股 — 不是驗證後沒用，是資料才 3 個月不夠驗證，不該跟「已驗證無效」的東西混為一談

## 本次新增程式碼

- `screener/backtest.py`：`scan_chips_rule()` 新增 `dip_buy`/`stealth_buy` 分支，
  `CHIPS_RULES`/`CHIPS_RULE_CONFIG` 對應加入（commit `92389fb`）
- `tests/test_backtest.py`：對應單元測試（`test_dip_buy_rule_requires_streak_and_five_day_drop`/
  `test_stealth_buy_rule_requires_foreign_streak_and_flat_price`）
- **近似方法**：chips.html 原版「越跌越買」「外資偷偷買」門檻是族群層級（族群 5 日累計報酬 +
  族群層級外資/投信連買），回測需要買到具體個股才有價格可查後續報酬，沒有可交易的「族群」
  標的，改用個股自己的 `price_cum_pct`（`scan_institutional(..., price_window=5)`）+ 個股自己的
  `foreign_streak`/`trust_streak` 做近似——語意略窄於原版，但方向一致，足以驗證假設本身有沒有
  edge
- 這批 commit 尚未 push 到 origin，等 Debugger 跑完 `pytest` 回報 ✅ 後再 push（見
  `debug-tasks.md` 2026-08-25 條目）

## 視覺／資訊架構設計（`ui-ux-pro-max` skill 產出，2026-08-25）

Mockup：`docs/superpowers/mockups/2026-08-25-chips-page-evidence-tiers-mockup.html`（瀏覽器直接
開啟即可看外觀，只示範新元件/新排序，不是完整頁面重繪）。

**設計原則**：不換色票字型系統（沿用 `docs/chips.html` 既有 CSS 變數），四個等級全部用現有
token 組出，不新增色相：

| 等級 | Token | 說明 |
|---|---|---|
| 🟢 已驗證 | `--accent`（金）+ `--accent-soft` | 現況已用於 active tab/排序箭頭，語意本來就是「值得注意」 |
| 🟡 觀察用 | `--muted` + `--surface-3` | 中性、不強調，跟既有 `.market-badge` 同一套語言 |
| ⚪ 待驗證 | `--caution`（藍灰）+ `--caution-soft` | 這個變數現況只用在 1 處 disclosure 文字，語意本來就契合「需要留意但不是壞消息」 |
| 🔴 證據偏弱 | `--subtle` + 虛線框 | 不用警示色（`--up`/`--down` 已被漲跌語意佔用，混用會撞色），用「視覺重量減到最低」表達降級 |

徽章一律「文字+顏色」雙重編碼（已驗證/觀察用/待驗證/證據偏弱四種不同文字），不單靠顏色分辨，
呼應 `ui-ux-pro-max` 的 accessibility「Color Only」規則（Don't convey information by color alone）。

**四項具體改動**：

1. **側邊 tab nav 組內重排**：沿用現有 3 個功能分組（法人動向／特殊型態／持股結構）不重新
   發明分類，但**組內順序改成證據強度排序**（原順序是功能上線時間先後）。例如「特殊型態」組
   內原本是 越跌越買→外資偷偷買→融資警示，改成 融資警示→外資偷偷買→越跌越買。
2. **每個 tab 加證據徽章**：直接掛在 tab 按鈕文字旁，四級對應四色四文字（見上表）。
3. **拿掉「候選觀察」開頁 hero**：現況 `joint_buy`（法人同步觀察）是全頁最顯眼的開頁區塊，
   但證據強度只是「觀察用」，改成跟其他觀察用項目同一層級的一般 tab，不再享有 hero 版位。
4. **每個有回測結果的 tab 面板頂部固定顯示「證據卡」**：訊號日數/筆數/勝率/平均超額，數字
   直接對應 spec 總表，讓 Cody 在頁面上就能自己判斷可信度，不用回頭翻 spec 或問我。「待驗證」
   跟「證據偏弱」兩型不用證據卡，改用對應語氣的說明 banner（見 mockup ③④）。

## Open Questions / 下一步

1. Cody 逐項確認/調整四級分類 + 上面的視覺/資訊架構設計（mockup 四個示範區塊）
2. 確認後才拆成實作任務清單真的動 `export/chips_generator.py`（照 CLAUDE.md 規矩，較大規模
   改動建議先 `writing-plans` 拆 task，不要一次全部重寫）
3. 董監持股：等 `insider_holdings` 資料再累積幾個月（多幾個月頻快照）後補回測，屆時可比照這次
   的方法論加進 `CHIPS_RULES`

## 相關文件

- `docs/superpowers/specs/2026-07-14-backtest-framework-design.md` — 回測框架方法論原始設計
- `docs/superpowers/specs/2026-07-15-accumulation-score-backtest-calibration-design.md` —
  進貨分回測校準（同樣手法，先例）
- `docs/superpowers/specs/2026-07-14-chips-metric-definitions-design.md` — 籌碼頁既有指標定義
- `debug-tasks.md`（2026-08-25 條目）— Debugger 驗證清單
