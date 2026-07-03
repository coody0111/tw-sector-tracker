# 動能派個股健檢訊號 — 設計文件

> 來源：`動能派學習筆記.md`（CMoney「逆轟高灰」系列）+ `每日心得日誌.md`
> 範圍：僅個股層級健檢，不含大盤指數層級（大盤層級需另接 TAIEX 資料源，列為後續獨立任務）

---

## 背景與目標

現有 `screener/patterns.py` 負責偵測具體圖形型態（雙底、VCP、三角突破等），`screener/signals.py` 的 `scan_volume_turnover` 負責量能異常訊號。這兩者都缺少動能派交易法的核心判斷依據：**均線排列狀態**與**族群內相對強弱**。

動能派筆記的「出場三原則」「進場三原則」本質上是**均線為核心的持股健檢機制**，跟現有的型態偵測是互補關係，不是替代關係：
- 型態偵測回答「有沒有出現特定圖形」
- 均線健檢回答「目前整體趨勢結構健不健康」

本次設計新增一個獨立訊號模組，產出個股層級的均線健檢結果，供既有訊號/型態附加「確認層」，並開一個獨立的「持股健檢」頁面呈現完整清單。

---

## 架構決策

**新增位置**：`screener/signals.py::scan_momentum_health()`，比照既有 `scan_volume_turnover()` 的介面慣例（`trade_date`, `db_path` 參數；回傳 list of dict；DuckDB read-only 查詢）。

**不做的事**：
- 不重新實作突破偵測邏輯（`patterns.py` 已有 VCP/60日突破/雙底等，均線排列只是附加在這些訊號上的「確認層」欄位，不是新的獨立進場訊號來源）
- 不含大盤指數層級的健檢（`大盤整體滿足三原則時也全出` 這條筆記提到的延伸應用，需要先有 TAIEX 大盤指數資料源，目前專案完全沒有這個資料，列為後續任務）

---

## 均線計算

`screener/technical.py` 目前只有 SMA20/SMA50，動能派用的是 5/10/60MA，需新增（沿用既有 `sma()` function，不用重寫）。

需要至少 **65 個交易日**歷史資料才能穩定算出 MA60 並比較「今日 MA5 vs 昨日 MA5」的斜率。不足門檻的股票直接跳過（沿用 `scan_volume_turnover` 裡 `_MIN_WINDOW_DAYS` 的 graceful-skip 慣例，避免用不足的歷史資料算出雜訊）。

---

## 核心欄位

| 欄位 | 定義 |
|------|------|
| `ma5` / `ma10` / `ma20` / `ma60` | 今日均線值 |
| `ma_alignment` | `多頭排列`（MA5>MA10>MA20>MA60）／`空頭排列`（反序）／`糾結`（其他） |
| `ma5_slope_down` | bool，今日 MA5 < 昨日 MA5 |
| `exit_3_rule_triggered` | bool，**三條件同時成立**才 True：`(1)` 收盤 < MA5 `(2)` MA5 下彎 `(3)` `change_pct ≤ -4.0`（重挫長黑，門檻可調） |
| `entry_confirmed` | bool，`多頭排列` 且 MA5/MA10 皆上揚——附加在既有型態訊號上的確認 badge，非獨立訊號 |
| `rs_score` | 個股 5 日報酬率 − 族群 5 日平均報酬率（重用 `processors/performance.py::calc_cumulative_meta` 的 groupby 邏輯，跟現有累積漲跌 badge 用同一個 5 日窗口，避免多一套時間週期） |
| `rs_rank_pct` | 該股 `rs_score` 在所屬 `meta_sector` 內的百分位排名 |
| `strength_tier` | `超強`／`強`／`整理`／`弱`／`超弱`，由 `ma_alignment` + `rs_rank_pct` 綜合判斷（見下表） |

### 五級分類判斷邏輯

| 等級 | 條件 |
|------|------|
| 超強 | 多頭排列 且 `rs_rank_pct` 前 20% |
| 強 | 多頭排列 且 `rs_rank_pct` 前 50%（未達超強） |
| 整理 | 糾結排列 |
| 弱 | 空頭排列 或 `rs_rank_pct` 後 50% |
| 超弱 | 空頭排列 且 `exit_3_rule_triggered` |

---

## 可調參數（比照既有 `_YFINANCE_MIN_SUCCESS_RATE` 的慣例，寫成模組常數並註明理由）

```python
_MIN_MA_HISTORY_DAYS = 65   # MA60 + 斜率比較所需最少交易日
_EXIT_BIG_BLACK_PCT = -4.0  # 「重挫長黑」門檻，主觀預設值，可依實測調整
_RS_WINDOW_DAYS = 5         # 相對強弱計算窗口，對齊現有累積漲跌 badge
```

---

## 呈現方式

**新增獨立頁面 `docs/health.html`**（跟 `chips.html`／`patterns.html` 同等級，不是塞進 `index.html`）。理由：`DESIGN.md` 已定過「不重複資訊」「不塞爆卡片」的規則，均線健檢資訊量（4條均線+排列狀態+RS+五級分類）不適合再塞進已經很滿的首頁卡片；首頁字數也會因此變長，違反「上方不留過長的資訊區塊」的規則。

**導覽列**：`html_generator.py` 現有的 `.nav-links`（第 1167-1171 行附近）在 `index.html`／`chips.html`／`patterns.html` 三個頁面共用同一段導覽列 markup，新增 `<a class="nav-link" href="health.html">持股健檢</a>` 需要同步加進三個頁面既有的導覽列產生邏輯。

具體頁面內部的區塊順序、視覺呈現（例如是否用卡片/表格呈現五級分類）留到下一階段 UI 設計時再細化，且照 `CLAUDE.md` 規則要用 `ui-ux-pro-max` skill，不在本次資料層 spec 範圍內。

---

## 測試（`tests/test_signals.py` 新增案例）

1. `ma_alignment` 三種狀態分類正確性（多頭/空頭/糾結各一組資料）
2. `exit_3_rule_triggered`：只滿足 1～2 個條件時應為 `False`，三個同時成立才 `True`（比照 Debugger 之前對 `scan_volume_turnover` 測試的意見，確保測試真的隔離驗證到這個條件，不是被其他條件先擋下）
3. 歷史資料 < 65 筆時 graceful skip，不產生訊號
4. `rs_score` 計算正確性（手算範例：個股 5 日漲 8%，族群平均漲 3% → `rs_score = 5.0`）

---

## Out of scope（本次不做，列為後續任務）

- 大盤指數層級健檢（需先有 TAIEX scraper）
- 「持股健檢」頁面的實際 UI/視覺設計（下一階段另外 brainstorm，且照 `CLAUDE.md` 規則要用 `ui-ux-pro-max` skill）
- 隔日沖券商辨識（已有共識，併入既有「券商分點」`broker_branch.py` 規劃，不在這次個股均線健檢範圍內）
