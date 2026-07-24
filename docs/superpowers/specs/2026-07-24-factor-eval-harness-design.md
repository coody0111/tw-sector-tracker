# 因子評估檢（Factor Evaluation Harness）設計 (2026-07-24)

## 目標

用現有價量資料，對一批**價量因子**算樣本外 RankIC，個股與族群雙層對照，
誠實排出「哪個因子真的能預測未來相對強弱、哪個是雜訊」。
兼具兩個目的：**學會建立因子的完整流程** + **改善族群掃盤**（用驗證過的因子當排序分數）。

概念背景見 `factor.md`。

## 資料範圍與限制（重要，決定結論可信度）

盤點 `data/screener.db`（DuckDB）：

| 資料表 | 期間 | 可否研究 |
|---|---|---|
| `daily_prices`（OHLCV + change_pct） | **實際連續覆蓋約「一年多」**（DB 的 MIN/MAX 2017–2026 為零星稀疏值造成的假象，非連續） | ✅ 唯一有足夠連續歷史者 |
| `institutional`（三大法人） | 約 3 個月 | ❌ 太短 |
| `margin`（融資融券） | 約 3 個月 | ❌ 太短 |
| `foreign_holdings`（外資持股%） | 約 10 天 | ❌ 幾乎沒有 |
| `shareholder`（大戶持股） | 約 2 個月 | ❌ 太短 |
| `broker_branch` / `insider_holdings` / `signals` | 0 筆 | 空 |

**結論**：第一版只做**價量因子**。籌碼類資料太短，現在算 RankIC 無統計意義（未來會累積）。

**誠實前提**：一年多的日線偏短 → 第一版產出是**初步、指示性**的訊號，不是鐵證；
RankIC 會偏吵、樣本外切分很緊。**檯子本身才是可長期複用的資產**——資料每天在長，
之後（含籌碼）重跑一次結果會越來越可信。這個限制要在報告輸出的表頭明白標注。

## 非目標 (YAGNI)

- 不做因子搜尋/進化引擎（等這台檯子穩了、資料變多再說）。
- 不碰籌碼因子（資料太短）。
- 不接實盤 / 下單 / 部位管理。
- 不動 production 掃盤每日流程（`main.py`）。

## 架構

新開 `research/` 套件，與 production 掃盤流程隔離；資料存取沿用 DuckDB（`data/screener.db`）。

| 檔案 | 單一職責 | 對外介面（重點） |
|---|---|---|
| `research/factor_data.py` | 載入價量、組 date×stock 面板、算未來報酬、掛族群對應 | `load_price_panel()`, `forward_returns(panel, horizons)`, `sector_map()` |
| `research/factors.py` | 因子庫：每個因子 = 函式(面板) → 每檔每日一個值 | `FACTORS: dict[str, Callable]`，每個回傳 date×stock 的 DataFrame |
| `research/evaluate.py` | RankIC、IC 衰減、分位多空、樣本外切分、族群聚合 | `rank_ic(factor, fwd_ret)`, `evaluate_factor(...)`, `to_sector(...)` |
| `research/run_factor_eval.py` | CLI 串接 → 輸出報告 | `main()` |
| `tests/test_factors.py`, `tests/test_evaluate.py` | 單元測試（重點防前視） | — |

### 資料流

```
daily_prices(DuckDB) ──load_price_panel──▶ 價格面板(date×stock: close/high/low/volume)
                                              │
                    ┌─────────────────────────┼──────────────────────────┐
                    ▼                          ▼                          ▼
           factors[f](panel)          forward_returns(panel,          sector_map()
           = 因子值(date×stock)         [1,5,10,20])                   (stock→meta_sector)
                    │                          │                          │
                    └──────────┬───────────────┘                          │
                               ▼                                          │
                    evaluate_factor:                                      │
                      個股層: rank_ic(因子, 未來報酬) ──┐                  │
                      族群層: to_sector(因子/報酬, ─────┼── 族群聚合 ◀─────┘
                              sector_map) → rank_ic     │
                               ▼                        ▼
                        樣本內/外切分 → 總表(CSV + 終端摘要)
```

## 因子候選清單（第一批，全價量、point-in-time）

每個因子在第 t 天只用 ≤t 的資料，輸出每檔每日一個值：

1. **動量 momentum_N**：過去 N 日報酬（N = 5 / 20 / 60）。
2. **短期反轉 reversal_5**：過去 5 日報酬取負（隔日/短期反轉效應）。
3. **波動 volatility_20**：過去 20 日日報酬標準差（低波動異象，通常取負向看）。
4. **量比 volume_ratio**：近 5 日均量 / 過去 20 日均量。
5. **日內區間位置 range_pos**：(close − low) / (high − low)，當日收盤強弱。
6. **Vol Regime Adaptive Momentum**：以過去 20 日波動判 regime（高/低，用中位數切）→
   高波動用 5 日動量、低波動用 20 日動量；再疊 `range_pos` 與 `volume_ratio` 排名做過濾/加權。

## 評估方法（核心概念）

- **point-in-time（鐵律）**：因子第 t 天不碰未來；未來報酬只用 t 之後。所有計算以此為準。
- **未來報酬**：對每個 horizon ∈ {1,5,10,20}，`fwd_ret[t] = close[t+h]/close[t] − 1`。
- **RankIC**：每個交易日算「因子橫截面排名 vs 未來報酬排名」的 Spearman 相關，對全期取平均；
  另報 **IC IR**（平均 / 標準差）與命中率（IC>0 的比例）。
- **IC 衰減**：同一因子在 1/5/10/20 日的 RankIC 一起看，判斷有效期限。
- **分位多空價差**：把因子分 5 等分，最高分組 vs 最低分組的未來平均報酬差（直觀的「賺賠」）。
- **樣本外切分**：時間切（非隨機），依實際連續資料範圍，研究期:樣本外 ≈ **2:1**。兩段分開算、比對是否失效。
- **雙層對照**：
  - 個股層：直接對 ~1000 檔算 RankIC（橫截面大、較穩）。
  - 族群層：`to_sector` 把個股因子聚合成族群因子（成員中位數）、族群未來報酬 = 成員等權平均；
    再對 ~40 族群算 RankIC。橫截面薄、較吵，需長期才準——與個股層對照觀察差異。

### universe / 資料衛生（防前視、防倖存者偏誤）

- 每個交易日的橫截面，只納入「該日有價量、且回看窗足夠」的股票；資料不足者當日剔除（非全期剔除）。
- 下市股在其存活期間照常納入，之後自然無資料——不回頭剔除（避免倖存者偏誤）。
- 低流動性過濾：可選，近 20 日均量低於門檻者剔除（第一版用寬鬆門檻或不設，於 spec 註記為可調參數）。

## 產出

一張總表，每列 = `因子 × 層級(個股/族群) × 天期(1/5/10/20) × 期間(樣本內/外)`，欄位：
平均 RankIC、IC IR、IC 命中率、分位多空價差、樣本天數。
輸出 `research/output/factor_eval_<date>.csv` + 終端摘要表；表頭標注資料範圍與「一年多、初步」警語。
（未來可接掃盤：把驗證有效的因子合成族群排序分數。）

## 測試策略（第一風險 = 前視偏誤）

- **合成資料驗算對**：造一組「因子值與未來報酬完全同序」的假資料 → RankIC 應 ≈ +1；
  完全反序 → ≈ −1；隨機 → ≈ 0。確認 `rank_ic` 正確。
- **前視驗證**：斷言 `factors[f]` 在第 t 天的輸出不依賴 >t 的任何資料
  （用「把 t 之後的資料改成 NaN，t 當日因子值不變」的測試）。
- **未來報酬驗證**：`fwd_ret[t]` 對得上 `close[t+h]/close[t]−1`（用小面板手算比對）。
- **族群聚合驗證**：小面板手算 `to_sector` 的中位數/等權平均。
- **樣本外切分驗證**：切分點正確、兩段不重疊、無洩漏。

## 分工

- **開發者（我）**：research/ 四個模組 + 測試，TDD。
- **Cody**：跑 `python research/run_factor_eval.py` 看報告（依 CLAUDE.md，資料/程式由 Cody 跑）。
- **Debugger**：驗前視鐵律、RankIC 正確、雙層聚合、樣本外無洩漏。

## 資料來源相關（CLAUDE.md 要求）

- 只讀 `daily_prices`（歷史價量），純研究、唯讀；不觸每日 TWSE/TPEx 流程、不涉回補。
- 上市/上櫃無混用（族群對應沿用 `stock_universe.csv` 的 meta_sector）。
