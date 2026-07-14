# 進貨分回測校準設計

**日期**：2026-07-15
**作者**：Developer（與 Cody brainstorming 後）
**狀態**：已核准（2026-07-15 Cody review 通過）

---

## 背景與目標

`screener/patterns.py::calc_accumulation_score()`（進貨分，spec: `docs/superpowers/specs/2026-07-14-accumulation-score-design.md`）已經實作完成、單元測試涵蓋所有分支，但公式裡的切點（外資/投信/大戶封頂 40/30/20、價格閘門 0.5、label 門檻 40、weakening 定義）全部是「草案」，從未用真實歷史資料驗證過準不準。

`screener/backtest.py::run_backtest()`（通用回測框架，plan: `docs/superpowers/plans/2026-07-14-backtest-framework.md`）Task 1-6 已全部完成，支援任意 scanner callable、大盤超額報酬（`bench_H`/`excess_H`）、交易成本、漲停剔除（`no_fill`）、大盤 regime 分段。

Cody 的原則是「做任何事都要回測」——本 spec 的目標是把進貨分接進回測框架，讓 Cody 能實際跑出「進貨分高的股票，後續超額報酬是否真的比較好」的真實數字，用來決定切點要不要調整。

## 非目標（本次不做）

- **不修改 `screener/backtest.py`**：Task 1-6 剛做完、還在等 Debugger 驗證，本次新增的東西完全獨立，不碰這個檔案。
- **不依照本次結果自動調整 `calc_accumulation_score()` 的切點**：這次只負責「產出真實數據」，切點要不要改是 Cody 看數字之後的另一個決定，不在本 spec 範圍內。
- **不做「持股健檢」「Telegram 推播」**：spec `2026-07-14-accumulation-score-design.md` 已列的其他 follow-up，另開。
- **不優化 `scan_institutional()` 的效能**：即使逐日呼叫在 8 年歷史上可能偏慢，這次先跑出結果，效能問題等真的太慢再處理，不要一開始就過度優化。

---

## 架構

### 核心組件：`scan_accumulation_score()` scanner 工廠

**位置**：`screener/patterns.py`（跟 `calc_accumulation_score()` 同檔）。

```python
def scan_accumulation_score(db_path: str = _DB_PATH):
    """
    回傳 (scanner, cache) tuple：
    - scanner: 符合 run_backtest() 介面的 Callable[[str, str], list[dict]]，
      每天對全市場（scan_institutional 撈到的所有股票）算一次進貨分。
    - cache: dict，key=(date_str, stock_id) → calc_accumulation_score() 完整回傳值，
      run_backtest() 跑完後用這個字典把 score/weakening/label 等欄位 merge 回結果 DataFrame。
      （run_backtest() 本身只認 sig["stock_id"]，不會把額外欄位帶進輸出，這是刻意用
      side-effect 快取繞過，不改 backtest.py。）
    """
```

**內部運作**：
1. 呼叫時（非每天，是建立 scanner 當下）先讀一次 `shareholder` 全表、一次 `daily_prices` 全表，建立「任意歷史日期」的查表索引（跟 `backtest.py::_build_price_index`/`_market_index` 同樣手法：一次查詢建 dict，之後純記憶體查找）。
2. 回傳的 `scanner(date_str, db_path)` 內部：呼叫 `scan_institutional(date_str, db_path=db_path)` 拿當天全市場的 `foreign_streak`/`trust_streak`（這個函式本身已經是一次查完全市場，不用逐股查）；對每支股票用步驟1建好的索引查「as of date_str」的大戶連增週數/當週張數變化/近5日報酬；餵進 `calc_accumulation_score()`；結果同時寫進 `cache[(date_str, stock_id)]` 並回傳 `{"stock_id": sid, "close": ...}` 給 `run_backtest()`。

### 資料索引細節

- **大戶「as of 某日」查表**：`shareholder` 表的 `streak`/`lv12_shares`/`lv15_shares` 欄位本身就是逐週累積存好的歷史值（不是只存最新一筆——已確認 `scrapers/shareholder.py::_add_week_change_streak`/`recompute_latest_streak` 是逐週遞增計算並存進 DB）。讀一次全表，依 stock_id 分組、依 date 排序，查詢時找「≤ 目標日期的最新一筆」（forward-fill 語意：同一週內每天查到的都是同一組數字，這是週資料的本質限制，已跟 Cody 確認過、決定照樣接受，不做人工插值）。`holder_net_lots` = 該筆的 `lv12_shares - 前一筆lv12_shares` + `lv15_shares - 前一筆lv15_shares`（用 pandas `.diff()` 算，不用逐股查 DB）。
- **近5日報酬「as of 某日」查表**：複用 `daily_prices` 的 close 序列，「as of d_ts」= 用 ≤ d_ts 的收盤價序列取最近5個交易日算報酬（跟 `screener/database.py::get_rolling_returns()` 的公式一致：`(最新收盤/N日前收盤 − 1) × 100`，但這裡要支援任意歷史日期，不能直接沿用 `get_rolling_returns()`——那個函式寫死抓「表裡最新」，沒有日期參數）。

### 消費端：`print_accumulation_calibration()`

**位置**：`screener/patterns.py`。

```python
def print_accumulation_calibration(df: pd.DataFrame, cache: dict, horizons=(5, 10, 14)) -> None:
    """
    印出兩塊報告：
    1. 依 score 分桶（0-20/20-40/40-60/60-100）的平均超額報酬/勝率，回答「分數越高表現是否越好」。
    2. weakening 但 holder_net_lots>0 的「富鼎型邊界案例」子集，跟其餘樣本的平均超額報酬對照，
       回答「純大戶進貨、法人沒動被判轉弱，是否真的該轉弱」這個已知懸而未決的問題。
    """
```

### CLI 整合

- **修好 `main.py --backtest`**：目前呼叫 `run_backtest()` 零參數會直接 `TypeError`（Task 1 重構後 `scanner` 變必填，這是既有回歸，非本次造成）。修法：補預設用 `scan_volume_turnover` 當 scanner（跟 plan 文件「實跑驗收」段落給的範例一致）。
- **新增 `main.py --backtest-accumulation`**：跑 `scan_accumulation_score()` + `run_backtest()` + `print_accumulation_calibration()`，一個指令印出完整進貨分校準報告。

---

## 錯誤處理／邊界情況

- 股票完全沒有大戶資料（太新掛牌、或下市，`shareholder` 表查無資料）→ `sh_streak=None`、`holder_net_lots=None`，直接餵給 `calc_accumulation_score()`，函式本身已有 `None`/`NaN` 防呆（見 `2026-07-14-accumulation-score-design.md` 資料完整性段落），不會 crash。
- `recent_return` 資料不足（新股不到5個交易日）→ 回 `None`，`calc_accumulation_score()` 視為未 confirm（既有行為，不用額外處理）。
- `scan_institutional()` 對某天回傳空清單（例如非交易日、資料缺漏）→ `run_backtest()` 既有邏輯本來就會 `continue` 跳過，沿用即可。
- 漲停鎖死（`no_fill`）：`run_backtest()` 本來就會標記，`print_accumulation_calibration()` 的分桶統計要記得比照 `print_summary()` 預設剔除 `no_fill=True` 的訊號，避免「看得到分數但買不到」的雜訊混進校準結果。

---

## 測試策略

`tests/test_patterns.py` 新增測試，用合成 DuckDB（造 `institutional`/`shareholder`/`daily_prices` 三張最小表，比照 `tests/test_backtest.py` 現有合成資料手法）：

1. **`scan_accumulation_score` 算對「某天」的分數**：造兩週大戶資料、幾天法人資料，驗證某個信號日算出的 `score`/`weakening` 跟手動算的一致。
2. **大戶資料是「as of」不是「最新」**：造一支股票有兩筆大戶週資料（一新一舊），驗證查詢「舊那週對應的交易日」時，用的是舊的大戶數字，不是最新一筆（這是最容易犯的 bug——forward-fill 邏輯抓錯方向）。
3. **cache 正確 merge 回 `run_backtest()` 輸出**：跑一個小規模合成場景，驗證 `df` 加上 `score` 欄位後，數值跟 `cache[(date, stock_id)]["score"]` 一致。
4. **`print_accumulation_calibration` 不 crash**：合成一組涵蓋多個分數區間、含至少一筆 weakening+holder 正值的資料，驗證印出的文字含分桶區間字樣跟富鼎案例比較字樣，空 DataFrame 不 crash。

不自己跑 pytest（照專案規則留給 Debugger）。

---

## 已知限制（如實記錄，不隱藏）

- **大戶資料只有 7 週歷史**：回測樣本量必然很小，而且同一週內每天訊號的大戶數字完全相同（週資料本質限制）。Cody 已確認接受這個限制，先跑出結果看看，不做人工插值或延伸假設。
- **`scan_institutional()` 效能未知**：目前設計是逐日呼叫、每次都對 `institutional` 全表做 `QUALIFY ROW_NUMBER()` 查詢，8年歷史逐日跑可能偏慢。這次先跑、不預先優化；如果跑起來真的太慢，是下一輪的問題。
- **本次結果不能直接當「統計證明」**：跟 `2026-07-14-accumulation-score-design.md` 的「實證校準」段落一樣的 caveat——樣本小、regime 單一，這次跑出來的數字是「校準參考」，不是最終答案。

---

## 後續 follow-up（本 spec 範圍外）

1. 若校準結果顯示現有切點（40/30/20、閘門0.5、label門檻40）明顯不合理，另開 spec 調整 `calc_accumulation_score()` 公式。
2. 若富鼎型邊界案例的比較結果支持修改 weakening 定義，另開 spec。
3. `scan_institutional()` 效能優化（如果需要）。
