# 逆轟動能策略頁面 — 統整 Design Spec

> [!WARNING]
> **Superseded（2026-07-16）**：頁面資訊架構、五級狀態文案與後續實作要求已由
> `2026-07-16-momentum-strategy-page-v2-design.md` 取代。本文件只保留作為 B1~B6 原始資料層
> 稽核與決策歷史；若內容衝突，以 v2 為準。

> 來源：`notes/動能派學習筆記.md`（CMoney「逆轟高灰」系列，110 篇）、`notes/每日心得日誌.md`
> 本文取代並整併以下三份先前各自獨立的 design spec（內容已完整吸收，避免多份文件各自漂移）：
> - ~~`2026-07-02-momentum-health-signal-design.md`~~
> - ~~`2026-07-14-consecutive-limit-up-scan-design.md`~~
> - ~~`2026-07-14-bullish-alignment-new-high-scan-design.md`~~
>
> **保留、不取代**：`2026-07-09-momentum-notes-scan-mapping.md`——那是「110 篇筆記 vs 現有程式碼」
> 的原始逐條稽核紀錄（B1~B6 六個缺口的證據、程式碼行號引用），性質是稽核研究，不是「要蓋什麼」的
> 設計文件，繼續保留作為本文各項決策的證據來源，本文多處會引用它。
>
> 作者：Debugger（2026-07-14，整併三份舊 spec + 補一次落差稽核）。

---

## 背景與目標

動能派每天的決策順序（`2026-07-09` mapping spec 附錄 A，已驗證仍然成立）：

| # | 每天問的問題 | 筆記出處 | 資料層來源 |
|---|---|---|---|
| ① | 今天資金在哪個**主流族群**？ | 十九、族群選股 | 既有 `calc_meta_performance`/`calc_cumulative_meta`（已實作，不用新建） |
| ② | 那族群裡**誰最強**？（選龍頭，不買二三軍）| 十二、三十、相對強弱 | B4 相對強弱（本文 §3.4） |
| ③ | 這檔**現在能不能進**？（進場三原則）| 十一、四十五、五十六 | B3 通用多頭排列+創新高（本文 §3.3）+ 既有 `detect_breakout_confirm` |
| ④ | **手上的該不該出**？（出場三原則）| 三、二十二、五十二 | B2 出場三原則（本文 §3.2） |
| ⑤ | 有沒有**最強型態**？（連續漲停鎖死）| 三十六、四十五 | B5 連續漲停鎖死（本文 §3.5） |

**Cody 已拍板的頁面結構決定**（2026-07-14）：新頁面照這 5 個問題分區塊組織，不是照現有五級強弱分類
（超強/強/整理/弱/超弱）分頁——五級分類仍會算出來，但用途是「①~⑤ 算完後的綜合標籤」，不是頁面
本身的一級分區。詳見 §4。

**動工順序（Cody 已拍板）**：資料層（B1+B2+B3+B4+B5 全部函式）先全部做完、驗證過，才開頁面
brainstorming/spec/plan。本文只涵蓋資料層規格 + 頁面資訊架構草案，**不含頁面視覺設計**（那是
下一階段，照 `CLAUDE.md` 規則要用 `ui-ux-pro-max` skill，且要等資料層落地才開工）。

---

## 1. 落差稽核結論（整併時新發現，這次一併收斂）

整併三份舊 spec 時，逐項對照 `2026-07-09` mapping spec 的原始建議，抓到 **2 個既有落差**，記錄
收斂決定如下，不悄悄略過：

### 1.1 🔴 均線排列口徑不一致：07-02 design 誤把 MA20 也放進「多頭排列」門檻

- **問題**：`2026-07-09` mapping spec B1 明確建議「`ma_bull_stack`（多頭排列 close>MA5>MA10>MA60）」
  ——三線判斷，不含 MA20。`2026-07-14` 的 B3 spec 也正確遵守這個口徑（`close>MA5>MA10>MA60`）。
  但**已經寫好、尚未實作的 `2026-07-02` 那份 `scan_momentum_health()` plan，`ma_alignment` 判斷式
  卻是 `ma5>ma10>ma20>ma60`**（四線，多要求 MA20 也要卡在中間）——這比策略本身的定義更嚴格，
  會讓「MA5>MA10>MA60 已成立，但 MA20 暫時卡在奇怪位置」的股票被誤判成「糾結」而非「多頭排列」，
  產生假陰性（漏抓真正符合策略定義的股票）。
- **收斂決定**：**`ma_alignment` 判斷改回策略原始口徑，只看 `close>MA5>MA10>MA60`（三線）**。
  `ma20` 繼續算、繼續回傳（純資訊性欄位，供頁面顯示或未來其他用途），但**不參與 `ma_alignment`
  的判斷邏輯**。§3.1 已用修正後口徑重寫。
- **影響範圍**：`docs/superpowers/plans/2026-07-02-momentum-health-signal.md` 的 Task 1 實作程式碼
  跟對應測試需要跟著修正（尚未實作，**建議在真的動工 Task 1 之前直接照 §3.1 的口徑寫**，不要照
  舊 plan 檔案裡的原始程式碼碼照抄）。

### 1.2 🟡 相對強弱只做了族群內，沒做「vs 大盤」；族群基準用平均不是中位數

- **問題**：mapping spec B4 原文：「個股層：`個股近N日報酬 − 所屬族群中位數` = 族群內相對強弱；
  `個股 − 大盤(加權指數或 universe 等權)` = 大盤相對強弱」——**要求兩種 RS**。但 `2026-07-02`
  design 只做了族群內這一種（`rs_score = 個股5日報酬 − 族群5日平均報酬`），且用的是**平均**
  （重用 `calc_cumulative_meta` 的 `groupby().mean()`），不是 mapping spec 建議的**中位數**。
  「大盤相對強弱」完全沒做。
- **收斂決定**：
  1. **族群基準維持用平均，不改中位數**——`calc_cumulative_meta` 是全專案唯一、已測試過的族群
     聚合函式，改成中位數要新開一條計算路徑，且「族群內選龍頭」用平均或中位數對排名結果的影響
     很小（樣本數通常不大，離群值機率低），不值得為此增加一套新邏輯。**這是刻意的務實選擇，不是
     沒注意到 mapping spec 寫的是中位數**。
  2. **補上「vs 大盤」這個缺項**：新增 `rs_market_score = 個股5日報酬 − universe 等權平均5日報酬`。
     用 **universe 等權平均**（不用 TAIEX 加權指數）——理由：universe 只有 1040 檔電子科技股，
     跟 TAIEX（涵蓋全市場、金融傳產都在內）本來就不是同一個母體，混用會有 apples-to-oranges 問題
     （呼應 `2026-07-09` market-regime-dashboard 附錄 3 已經記錄過的同類母體不一致提醒）；用
     universe 自己的等權平均當「大盤」基準，語意上更接近「這檔在我們追蹤的池子裡是不是真的強」。
  3. §3.4 已用這個收斂後的口徑重寫欄位定義。

---

## 2. 已知資料缺口（現況記錄，非本次修復範圍）

| 缺口 | 現況 | 影響 | 修法 | 優先度 |
|---|---|---|---|---|
| **open 開盤價被 import 丟掉** | CSV 有 open/high/low，但 `screener/database.py:171` 寫死 `NULL::DOUBLE AS open`，近期資料救得回（`CAST(open AS DOUBLE)` 一行）；深歷史（`backfill.py` TWSE月別/yfinance）record 本身沒存 open，要重跑回補才有 | B2「重挫長黑」目前只能用 `change_pct<=-4%` 近似，沒辦法真的算 K 棒實體（`\|close-open\|`） | 近期一行救回＋reimport；深歷史等 Developer/Cody 排優先度重跑回補 | 中（不擋 B2 先上線，先用近似值） |
| **還原股價完全沒有資料源** | TWSE/TPEx 官方每日資料確定是原始價；yfinance 回補是否為還原價**取決於安裝版本的 `auto_adjust` 預設值，本專案未鎖定，屬未知狀態**；`daily_prices` 沒有欄位區分原始價/還原價 | B3「創新高」除權息當天後短期可能誤判「沒創新高」（假陰性，不會製造假訊號） | 幫 `daily_prices` 加還原價欄位，或明確鎖定 yfinance `auto_adjust=True` 並跟官方原始價分欄 | 低（假陰性方向安全，且是獨立的資料層任務） |
| **興櫃股沒有漲跌幅限制** | 已查證 `stock_universe.csv` 的 `exchange` 欄目前只有 TWSE/TPEx，沒有興櫃股 | B5「連續漲停」現階段非問題 | universe 若擴充收錄興櫃要重新檢查 | 低（現況非問題，僅記錄前提） |
| **處置股搓合日 change_pct** | 整個 repo grep 無任何處置股偵測邏輯 | B5 連板數可能被處置股的特殊搓合價污染，產生不合理離群值 | 無現成修法，需人工對照 TWSE 公告 | 低（真的出現離群值再處理） |

---

## 3. 資料層規格（B1~B6 統整）

### 3.0 統一新增位置

所有新掃描函式集中在 `screener/signals.py`，比照既有 `scan_volume_turnover()` 慣例：
`trade_date`/`db_path`/`universe_path` 參數、DuckDB read-only 查詢、逐股 groupby、graceful skip
歷史不足的股票、回傳 list of dict。**不修改、不呼叫** `patterns.py::detect_breakout_confirm`
（多頭拐點）——那支邏輯獨立，跟本文新增的訊號並存互補，不整合成同一支函式。

### 3.1 B1：均線排列（收斂後口徑，§1.1 已說明修正原因）

```
ma5 / ma10 / ma20 / ma60   今日均線值（ma20 純資訊性欄位，不參與判斷）
ma_alignment                "多頭排列"（close>MA5>MA10>MA60）／
                             "空頭排列"（close<MA5<MA10<MA60）／
                             "糾結"（其他）
ma5_slope_down               bool，今日 MA5 < 昨日 MA5
```

均線最少歷史門檻：65 個交易日（MA60 + 斜率比較需要）。

### 3.2 B2：出場三原則

```
exit_3_rule_triggered   bool，三條件同時成立才 True：
                         (1) close < MA5
                         (2) ma5_slope_down
                         (3) change_pct <= -4.0（重挫長黑，近似值，見 §2 open 缺口）
entry_confirmed          bool，多頭排列 且 MA5/MA10 皆上揚（附加在既有型態訊號上的確認 badge）
```

`_EXIT_BIG_BLACK_PCT = -4.0`：主觀預設值，可依回測調整。

### 3.3 B3：通用多頭排列＋創新高

獨立函式 `scan_bullish_alignment_new_high()`（已有完整 plan：
`docs/superpowers/plans/2026-07-14-bullish-alignment-new-high-scan.md`，**內容不需要因本次整併
變動**，口徑本來就是正確的 5/10/60）。跟 `detect_breakout_confirm` 差異：不要求 MA60 走平，抓
「已在乾淨多頭排列中的續強」而非「長期盤整後啟動」。「創新高」預設看 60 個交易日（波段新高，非
歷史新高，理由見該 plan）。**還原股價缺口見 §2，該 plan 已完整記錄，不重複貼一次全文**。

### 3.4 B4：相對強弱（含 §1.2 收斂後的新增欄位）

```
rs_score          個股近5日報酬 − 所屬 meta_sector 近5日平均報酬（沿用 calc_cumulative_meta）
rs_rank_pct        rs_score 在所屬 meta_sector 內的百分位排名（1.0 = 族群內最強）
rs_market_score    個股近5日報酬 − universe 等權平均近5日報酬（新增，見 §1.2 決定 2）
```

`_RS_WINDOW_DAYS = 5`：對齊既有累積漲跌 badge 的窗口，不另開新週期。

### 3.5 B5：連續漲停鎖死

獨立函式 `scan_consecutive_limit_up()`（已有完整 plan：
`docs/superpowers/plans/2026-07-14-consecutive-limit-up-scan.md`，**內容不需要變動**）。輸出
`limit_up_streak`（連板數）+ `volume_declining_streak`（量縮鎖死，streak<2 時為 `None`）。
`9.5%` 門檻沿用 `scan_volume_turnover` 既有慣例。興櫃/處置股缺口見 §2。

### 3.6 B6：已對上、不用新建（純參考，避免重工）

- 量能確認：`patterns.py::_calc_vol_price_score`、`signals.py` 爆量倍數
- 籌碼進貨：`_calc_chips_score`、`calc_meta_chips_signals`、大戶持倉（筆記說籌碼只給 50 分，
  複合評分權重外資25+投信20=45 偏高，是否下修留給 Cody 之後決定，不在本文範圍內處理）
- 形態偵測：雙底/頭肩底/三角/楔型/VCP/多頭拐點

### 3.7 五級強弱分類（整合 B1~B4，附加標籤，不是頁面分區依據——見 §4）

| 等級 | 條件 |
|------|------|
| 超強 | 多頭排列 且 `rs_rank_pct` >= 0.8 |
| 強 | 多頭排列 且 `rs_rank_pct` is None 或 >= 0.5 |
| 整理 | 糾結 |
| 弱 | 空頭排列（未觸發出場三原則）或多頭排列但 `rs_rank_pct` < 0.5 |
| 超弱 | 空頭排列 且 `exit_3_rule_triggered` |

---

## 4. 頁面資訊架構草案（依 Cody 拍板的 5 問題結構，視覺設計留待下一階段）

```
逆轟策略.html
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
① 今天資金在哪？   主流族群強度排名
                    來源：既有 calc_meta_performance/calc_cumulative_meta（免新建）

② 族群裡誰最強？   族群內 RS 排名（rs_rank_pct 由高到低）
                    來源：B4 §3.4

③ 能不能進？       多頭排列+創新高（B3）並列既有「多頭拐點」（detect_breakout_confirm）
                    entry_confirmed 當輔助 badge
                    來源：B3 §3.3 + 既有 patterns.py

④ 該不該出？       持股健檢：exit_3_rule_triggered 命中清單
                    來源：B2 §3.2

⑤ 最強型態？       連續漲停鎖死榜（limit_up_streak 由高到低）
                    來源：B5 §3.5
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

五級強弱分類（§3.7）作為**個股卡片/列上的綜合標籤**（例如在②③⑤任何列出個股的地方標一個
超強/強/整理/弱/超弱 badge），不是獨立的第 6 個分區——避免跟 5 問題架構打架、資訊重複。

**本文不含**：實際視覺呈現（卡片/表格/顏色系統）、`html_generator.py`/`chips_generator.py`
是否共用既有元件或開全新 generator、導覽列串接方式。這些留給下一階段 UI brainstorming
（`ui-ux-pro-max` skill）。

---

## 5. 對應的實作 Plan 檔案（本文是統整 spec，執行仍照三份獨立 plan）

| 資料層項目 | Plan 檔案 | 狀態 |
|---|---|---|
| B1+B2+B4（+ 本文 §1 收斂修正） | `docs/superpowers/plans/2026-07-02-momentum-health-signal.md` | **需要照 §1.1/§1.2 修正後才能照抄實作**，尚未動工 |
| B3 | `docs/superpowers/plans/2026-07-14-bullish-alignment-new-high-scan.md` | 口徑已正確，可直接照抄實作，尚未動工 |
| B5 | `docs/superpowers/plans/2026-07-14-consecutive-limit-up-scan.md` | 可直接照抄實作，尚未動工 |

---

## 6. 建置優先序（沿用 `2026-07-09` mapping spec C 節，仍然成立）

```
B1 均線口徑 → B2 出場三原則 → B4 相對強弱 → B5 連續漲停鎖死 → B3 通用多頭排列+創新高
→ 整合五級分類
```

每一條實作後都可以用 `screener/backtest.py` 回測驗證「到底賺不賺」，把筆記從「相信作者」變成
「自己歷史驗證過」。

---

## Out of scope（本文範圍外）

- 頁面實際視覺設計（下一階段，`ui-ux-pro-max` skill，等資料層全部落地才開工）
- 大盤指數層級健檢（需另接 TAIEX，`2026-07-02` design 已排除，本文維持排除）
- 還原股價資料源、open 欄深歷史回補（§2 已記錄，獨立資料層任務）
- 隔日沖券商辨識（併入既有「券商分點」`broker_branch.py` 規劃，不在本文範圍）
- 複合評分權重調整（外資/投信/籌碼權重是否下修，留給 Cody 之後決定）
