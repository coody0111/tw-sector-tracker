# 動能派個股健檢訊號 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `screener/signals.py::scan_momentum_health()`，掃描全市場個股的均線排列狀態、出場三原則、族群內相對強弱評分，並產出五級強弱分類，供後續「持股健檢」頁面使用。

**Architecture:** 沿用 `scan_volume_turnover()` 的既有慣例（DuckDB read-only 查詢、逐股 groupby、graceful skip 歷史不足的股票、回傳 list of dict）。相對強弱評分重用 `processors/performance.py::calc_cumulative_meta()` 算好的族群層級 5 日累積漲跌，不重複實作族群聚合邏輯。

**Tech Stack:** Python, pandas, DuckDB（既有依賴，無新套件）

## Global Constraints

- 均線最少歷史門檻：65 個交易日（來自 spec `_MIN_MA_HISTORY_DAYS`）
- 出場三原則「重挫長黑」門檻：`change_pct <= -4.0`（來自 spec `_EXIT_BIG_BLACK_PCT`，主觀預設值，可調）
- 相對強弱窗口：5 個交易日（來自 spec `_RS_WINDOW_DAYS`，對齊現有累積漲跌 badge）
- 本次範圍**不含** `export/html_generator.py`／`docs/health.html`／`main.py` CLI 接線——資料層 spec 明確排除頁面 UI 實作，留到下一階段 UI 設計（需用 `ui-ux-pro-max` skill）再開新的 brainstorming/spec/plan
- 本次範圍**不含**大盤指數層級健檢（無資料源）
- 對照 spec：`docs/superpowers/specs/2026-07-02-momentum-health-signal-design.md`

---

### Task 1: 均線排列 + 出場三原則 + 進場確認（核心健檢邏輯）

**Files:**
- Modify: `screener/signals.py`（新增常數、`_load_universe_map()` 加 `universe_path` 參數、新增 `scan_momentum_health()`）
- Test: `tests/test_signals.py`

**Interfaces:**
- Consumes：DuckDB `daily_prices` 表（`stock_id, date, close, change_pct`）；`data/stock_universe.csv`（`stock_id, stock_name, meta_sector`）
- Produces：`scan_momentum_health(trade_date: str, db_path: str = _DB_PATH, universe_path: str = _UNIVERSE_PATH) -> List[Dict[str, Any]]`，每筆 dict 含 `stock_id, stock_name, meta_sector, close, change_pct, ma5, ma10, ma20, ma60, ma_alignment, ma5_slope_down, exit_3_rule_triggered, entry_confirmed, rs_score(None), rs_rank_pct(None), strength_tier(None)`。後續 Task 2/3 會就地補上 `rs_score`／`rs_rank_pct`／`strength_tier`。

- [ ] **Step 1: 寫失敗測試 — 多頭排列 + 不觸發出場三原則**

在 `tests/test_signals.py` 檔案開頭加入 import（跟既有 import 放一起）：

```python
import pandas as pd
from screener.signals import scan_volume_turnover, scan_momentum_health
```

在檔案最後面新增：

```python
def test_scan_momentum_health_classifies_ma_alignment(tmp_path):
    """65 筆穩定上升的收盤價，應判斷為多頭排列，且不觸發出場三原則、有進場確認。"""
    db_path = tmp_path / "test.db"
    dates = pd.date_range("2026-01-01", periods=65, freq="D")
    rows = []
    close = 100.0
    for d in dates:
        close += 0.5
        rows.append(("2330", d.strftime("%Y-%m-%d"), close, 0.5, 1000))
    _seed_db(db_path, rows)

    results = scan_momentum_health(dates[-1].strftime("%Y-%m-%d"), db_path=str(db_path))

    assert len(results) == 1
    assert results[0]["stock_id"] == "2330"
    assert results[0]["ma_alignment"] == "多頭排列"
    assert results[0]["exit_3_rule_triggered"] is False
    assert results[0]["entry_confirmed"] is True


def test_scan_momentum_health_triggers_exit_3_rule(tmp_path):
    """站穩均線一段時間後，最後一天跌破5MA+5MA下彎+重挫長黑，三條件同時成立才觸發。"""
    db_path = tmp_path / "test.db"
    dates = pd.date_range("2026-01-01", periods=65, freq="D")
    rows = []
    close = 100.0
    for i, d in enumerate(dates):
        if i < 64:
            close += 0.5
            pct = 0.5
        else:
            close = close * (1 - 0.05)
            pct = -5.0
        rows.append(("2330", d.strftime("%Y-%m-%d"), close, pct, 1000))
    _seed_db(db_path, rows)

    results = scan_momentum_health(dates[-1].strftime("%Y-%m-%d"), db_path=str(db_path))

    assert len(results) == 1
    assert results[0]["exit_3_rule_triggered"] is True


def test_scan_momentum_health_skips_insufficient_history(tmp_path):
    """歷史資料 < 65 筆時，直接跳過不產生結果。"""
    db_path = tmp_path / "test.db"
    rows = [("2330", f"2026-01-{d:02d}", 100.0 + d, 0.1, 1000) for d in range(1, 30)]
    _seed_db(db_path, rows)

    results = scan_momentum_health("2026-01-29", db_path=str(db_path))

    assert results == []


def test_scan_momentum_health_exit_3_rule_needs_all_three_conditions(tmp_path):
    """跌破MA5 + MA5下彎兩個條件都滿足，但跌幅沒到 -4% 門檻時，不該觸發出場三原則。
    這個測試專門隔離驗證「重挫長黑」這個條件本身，避免像之前 scan_volume_turnover
    的測試一樣，被其他條件先擋下、沒有真正測到目標條件（Debugger review 時抓到的問題）。
    """
    db_path = tmp_path / "test.db"
    dates = pd.date_range("2026-01-01", periods=65, freq="D")
    rows = []
    close = 100.0
    for i, d in enumerate(dates):
        if i < 64:
            close += 0.5
            pct = 0.5
        else:
            close = close * (1 - 0.015)  # 只跌 -1.5%，跌破MA5+MA5下彎都成立，但沒到 -4% 門檻
            pct = -1.5
        rows.append(("2330", d.strftime("%Y-%m-%d"), close, pct, 1000))
    _seed_db(db_path, rows)

    results = scan_momentum_health(dates[-1].strftime("%Y-%m-%d"), db_path=str(db_path))

    assert len(results) == 1
    # 跌破MA5、MA5下彎這兩個條件確實成立，用來確認不是因為前兩個條件沒觸發才導致 False
    assert results[0]["close"] < results[0]["ma5"]
    assert results[0]["ma5_slope_down"] is True
    # 但第三條件（重挫長黑 <= -4%）沒有滿足，所以整體不該觸發
    assert results[0]["exit_3_rule_triggered"] is False
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_signals.py -k momentum_health -v`
Expected: FAIL，錯誤訊息類似 `ImportError: cannot import name 'scan_momentum_health'`

- [ ] **Step 3: 實作 `scan_momentum_health()`**

在 `screener/signals.py` 的 `_MIN_WINDOW_DAYS = 20` 那行下方新增常數：

```python
# 動能派均線健檢常數
_MIN_MA_HISTORY_DAYS = 65   # MA60 + 斜率比較所需最少交易日（60 + 緩衝）
_EXIT_BIG_BLACK_PCT = -4.0  # 「重挫長黑」門檻，主觀預設值，可依實測調整
_RS_WINDOW_DAYS = 5         # 相對強弱計算窗口，對齊現有累積漲跌 badge
```

把既有的 `_load_universe_map()` 改成接受可選路徑參數（向下相容，`scan_volume_turnover` 既有呼叫端不用改）：

```python
def _load_universe_map(universe_path: str = _UNIVERSE_PATH) -> dict:
    try:
        df = pd.read_csv(universe_path, usecols=["stock_id", "stock_name", "meta_sector"], dtype=str)
        return df.set_index("stock_id")[["stock_name", "meta_sector"]].to_dict("index")
    except Exception:
        return {}
```

在檔案最後面（`scan_volume_turnover()` 之後）新增：

```python
def scan_momentum_health(
    trade_date: str,
    db_path: str = _DB_PATH,
    universe_path: str = _UNIVERSE_PATH,
) -> List[Dict[str, Any]]:
    """
    動能派個股健檢：均線排列、出場三原則、相對強弱評分、五級強弱分類。

    Parameters
    ----------
    trade_date : str   e.g. "2026-07-02"

    Returns
    -------
    list of dict，每筆含：
        stock_id, stock_name, meta_sector, close, change_pct,
        ma5, ma10, ma20, ma60,
        ma_alignment ("多頭排列"/"空頭排列"/"糾結"),
        ma5_slope_down (bool),
        exit_3_rule_triggered (bool)，   ← (1)跌破MA5 (2)MA5下彎 (3)重挫長黑 三者同時成立
        entry_confirmed (bool)，         ← 多頭排列 + MA5/MA10 皆上揚
        rs_score (float|None)，          ← 個股5日報酬 - 族群5日平均報酬
        rs_rank_pct (float|None)，       ← 族群內百分位排名，1.0=最強
        strength_tier                    ← 超強/強/整理/弱/超弱
    """
    con = duckdb.connect(db_path, read_only=True)
    price_df = con.execute(f"""
        SELECT stock_id, date, close, change_pct
        FROM daily_prices
        WHERE date <= '{trade_date}'
        ORDER BY stock_id, date
    """).df()
    con.close()

    if price_df.empty:
        logger.warning("scan_momentum_health: DuckDB 無行情資料")
        return []

    universe_map = _load_universe_map(universe_path)
    price_df["date"] = pd.to_datetime(price_df["date"])
    target = pd.to_datetime(trade_date)

    results = []

    for sid, grp in price_df.groupby("stock_id"):
        grp = grp.sort_values("date").reset_index(drop=True)

        today_rows = grp[grp["date"] == target]
        if today_rows.empty:
            continue
        today_idx = today_rows.index[0]

        if today_idx + 1 < _MIN_MA_HISTORY_DAYS:
            # 歷史資料不足以穩定算出 MA60 + 斜率比較，跳過避免雜訊訊號
            continue

        window = grp.iloc[: today_idx + 1]
        close = window["close"]

        ma5 = close.rolling(5).mean()
        ma10 = close.rolling(10).mean()
        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()

        if pd.isna(ma60.iloc[-1]) or pd.isna(ma5.iloc[-2]) or pd.isna(ma10.iloc[-2]):
            continue

        ma5_today, ma5_yday = float(ma5.iloc[-1]), float(ma5.iloc[-2])
        ma10_today, ma10_yday = float(ma10.iloc[-1]), float(ma10.iloc[-2])
        ma20_today = float(ma20.iloc[-1])
        ma60_today = float(ma60.iloc[-1])

        if ma5_today > ma10_today > ma20_today > ma60_today:
            ma_alignment = "多頭排列"
        elif ma5_today < ma10_today < ma20_today < ma60_today:
            ma_alignment = "空頭排列"
        else:
            ma_alignment = "糾結"

        ma5_slope_down = ma5_today < ma5_yday
        ma5_rising = ma5_today > ma5_yday
        ma10_rising = ma10_today > ma10_yday

        today = window.iloc[-1]
        exit_3_rule_triggered = bool(
            today["close"] < ma5_today
            and ma5_slope_down
            and today["change_pct"] <= _EXIT_BIG_BLACK_PCT
        )
        entry_confirmed = bool(
            ma_alignment == "多頭排列" and ma5_rising and ma10_rising
        )

        uinfo = universe_map.get(str(sid), {})
        results.append({
            "stock_id":              sid,
            "stock_name":            uinfo.get("stock_name", ""),
            "meta_sector":           uinfo.get("meta_sector", ""),
            "close":                 float(today["close"]),
            "change_pct":            float(today["change_pct"]),
            "ma5":                   round(ma5_today, 2),
            "ma10":                  round(ma10_today, 2),
            "ma20":                  round(ma20_today, 2),
            "ma60":                  round(ma60_today, 2),
            "ma_alignment":          ma_alignment,
            "ma5_slope_down":        ma5_slope_down,
            "exit_3_rule_triggered": exit_3_rule_triggered,
            "entry_confirmed":       entry_confirmed,
            "rs_score":              None,
            "rs_rank_pct":           None,
            "strength_tier":         None,
        })

    logger.info("動能健檢掃描 %s：共 %d 檔（歷史資料足夠）", trade_date, len(results))
    return results
```

- [ ] **Step 4: 執行測試確認通過**

Run: `pytest tests/test_signals.py -k momentum_health -v`
Expected: 4 個測試全 PASS

- [ ] **Step 5: 確認既有測試沒有被 `_load_universe_map` 簽名變動影響**

Run: `pytest tests/test_signals.py -v`
Expected: 全部測試（含既有 `scan_volume_turnover` 兩個測試）PASS

- [ ] **Step 6: Commit**

```bash
git add screener/signals.py tests/test_signals.py
git commit -m "feat: 新增 scan_momentum_health 均線排列與出場三原則健檢"
```

---

### Task 2: 相對強弱評分（RS score）

**Files:**
- Modify: `screener/signals.py`
- Test: `tests/test_signals.py`

**Interfaces:**
- Consumes：Task 1 的 `scan_momentum_health()` 產出（就地補上 `rs_score`／`rs_rank_pct` 欄位）；`processors/performance.py::calc_cumulative_meta(universe_df: pd.DataFrame, db_path: str) -> List[Dict]`（既有函式，回傳含 `meta_name`／`cum5` 欄位的 list，`cum5` 可能為 `None`）
- Produces：`scan_momentum_health()` 回傳值裡的 `rs_score`（float 或 None）、`rs_rank_pct`（float 0~1 或 None，1.0 代表該族群內最強）欄位改為有值

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_signals.py` 新增：

```python
def test_scan_momentum_health_computes_relative_strength(tmp_path):
    """個股 5 日漲 8%、族群平均漲 3%（族群另一檔跌 2%）時，rs_score 應為 5.0。"""
    db_path = tmp_path / "test.db"
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "stock_id,stock_name,meta_sector\n"
        "1101,測試強股,sectorA\n"
        "1102,測試弱股,sectorA\n",
        encoding="utf-8",
    )

    dates = pd.date_range("2026-01-01", periods=65, freq="D")
    rows = []
    for sid, last_day_pct in [("1101", 8.0), ("1102", -2.0)]:
        close = 100.0
        for i, d in enumerate(dates):
            pct = 0.0 if i < 64 else last_day_pct
            close = close * (1 + pct / 100)
            rows.append((sid, d.strftime("%Y-%m-%d"), close, pct, 1000))
    _seed_db(db_path, rows)

    results = scan_momentum_health(
        dates[-1].strftime("%Y-%m-%d"),
        db_path=str(db_path),
        universe_path=str(universe_path),
    )

    strong = next(r for r in results if r["stock_id"] == "1101")
    weak = next(r for r in results if r["stock_id"] == "1102")
    assert strong["rs_score"] == 5.0
    assert strong["rs_rank_pct"] == 1.0
    assert weak["rs_rank_pct"] < strong["rs_rank_pct"]
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_signals.py -k relative_strength -v`
Expected: FAIL（`rs_score` 仍是 `None`，斷言 `None == 5.0` 失敗）

- [ ] **Step 3: 實作相對強弱計算**

在 `screener/signals.py` 檔案頂部 import 區塊新增：

```python
from processors.performance import calc_cumulative_meta
```

新增一個小 helper（放在 `_load_universe_map` 附近）：

```python
def _load_universe_df(universe_path: str = _UNIVERSE_PATH) -> pd.DataFrame:
    return pd.read_csv(universe_path, dtype=str)
```

在 `scan_momentum_health()` 裡，把 `logger.info(...)` 那行**之前**、`return results` **之前**插入以下區塊（也就是在原本的 for 迴圈結束之後）：

```python
    if not results:
        logger.info("動能健檢掃描 %s：共 0 檔（歷史資料足夠）", trade_date)
        return results

    universe_df = _load_universe_df(universe_path)
    sector_cum = calc_cumulative_meta(universe_df, db_path)
    sector_cum5_map = {r["meta_name"]: r["cum5"] for r in sector_cum if r["cum5"] is not None}

    for row in results:
        sid = row["stock_id"]
        grp = price_df[(price_df["stock_id"] == sid) & (price_df["date"] <= target)]
        cum5_window = grp.sort_values("date").tail(_RS_WINDOW_DAYS)
        if len(cum5_window) < _RS_WINDOW_DAYS:
            continue  # rs_score 保持 None

        factor = 1.0
        for pct in cum5_window["change_pct"]:
            factor *= (1 + float(pct) / 100)
        stock_cum5 = round((factor - 1) * 100, 2)

        sector_cum5 = sector_cum5_map.get(row["meta_sector"])
        if sector_cum5 is not None:
            row["rs_score"] = round(stock_cum5 - sector_cum5, 2)

    rs_df = pd.DataFrame(results)
    valid = rs_df["rs_score"].notna()
    if valid.any():
        rs_df.loc[valid, "rs_rank_pct"] = (
            rs_df.loc[valid].groupby("meta_sector")["rs_score"].rank(pct=True, ascending=True)
        )
    for i, row in enumerate(results):
        val = rs_df.loc[i, "rs_rank_pct"]
        row["rs_rank_pct"] = None if pd.isna(val) else round(float(val), 3)
```

刪掉原本函式最後那一行單獨的 `logger.info(...)`（已經搬到上面 `if not results:` 分支裡），改成在 `return results` 前保留一次：

```python
    logger.info("動能健檢掃描 %s：共 %d 檔（歷史資料足夠）", trade_date, len(results))
    return results
```

- [ ] **Step 4: 執行測試確認通過**

Run: `pytest tests/test_signals.py -k "momentum_health or relative_strength" -v`
Expected: 全部 PASS（含 Task 1 的 3 個 + 這次新增的 1 個）

- [ ] **Step 5: Commit**

```bash
git add screener/signals.py tests/test_signals.py
git commit -m "feat: scan_momentum_health 加上相對強弱評分（rs_score/rs_rank_pct）"
```

---

### Task 3: 五級強弱分類 + 完整回歸測試

**Files:**
- Modify: `screener/signals.py`
- Test: `tests/test_signals.py`

**Interfaces:**
- Consumes：Task 1 的 `ma_alignment`／`exit_3_rule_triggered`、Task 2 的 `rs_rank_pct`
- Produces：`scan_momentum_health()` 回傳值裡的 `strength_tier` 欄位（`"超強"|"強"|"整理"|"弱"|"超弱"`）改為有值

**判斷優先順序（由上往下，第一個符合的規則生效）：**
```
1. 空頭排列 且 exit_3_rule_triggered            → 超弱
2. 多頭排列 且 rs_rank_pct >= 0.8                → 超強
3. 多頭排列 且 (rs_rank_pct is None 或 >= 0.5)   → 強
4. 空頭排列（未觸發出場三原則）                    → 弱
5. 糾結                                          → 整理
6. 其餘（多頭排列但 rs_rank_pct < 0.5）           → 弱
```

- [ ] **Step 1: 寫失敗測試**

```python
def test_scan_momentum_health_tier_exit_signal_overrides_alignment(tmp_path):
    """空頭排列 + 出場三原則觸發 → 超弱，即使沒有額外 rs_score 資料也一樣判定。"""
    db_path = tmp_path / "test.db"
    dates = pd.date_range("2026-01-01", periods=65, freq="D")
    rows = []
    close = 200.0
    for i, d in enumerate(dates):
        if i < 64:
            close -= 0.5
            pct = -0.25
        else:
            close = close * (1 - 0.06)
            pct = -6.0
        rows.append(("2330", d.strftime("%Y-%m-%d"), close, pct, 1000))
    _seed_db(db_path, rows)

    results = scan_momentum_health(dates[-1].strftime("%Y-%m-%d"), db_path=str(db_path))

    assert results[0]["ma_alignment"] == "空頭排列"
    assert results[0]["exit_3_rule_triggered"] is True
    assert results[0]["strength_tier"] == "超弱"


def test_scan_momentum_health_tier_bullish_but_weak_rs_is_weak(tmp_path):
    """多頭排列，但族群內相對強弱排名落後（<50%），應歸類為弱，不是強。"""
    db_path = tmp_path / "test.db"
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "stock_id,stock_name,meta_sector\n"
        "1101,測試強股,sectorA\n"
        "1102,測試弱股,sectorA\n",
        encoding="utf-8",
    )
    dates = pd.date_range("2026-01-01", periods=65, freq="D")
    rows = []
    # 兩檔都緩步上漲維持多頭排列，但最後一天漲幅差很多，1102 明顯較弱
    for sid, last_day_pct in [("1101", 8.0), ("1102", 0.1)]:
        close = 100.0
        for i, d in enumerate(dates):
            pct = 0.3 if i < 64 else last_day_pct
            close = close * (1 + pct / 100)
            rows.append((sid, d.strftime("%Y-%m-%d"), close, pct, 1000))
    _seed_db(db_path, rows)

    results = scan_momentum_health(
        dates[-1].strftime("%Y-%m-%d"),
        db_path=str(db_path),
        universe_path=str(universe_path),
    )

    weak = next(r for r in results if r["stock_id"] == "1102")
    assert weak["ma_alignment"] == "多頭排列"
    assert weak["rs_rank_pct"] < 0.5
    assert weak["strength_tier"] == "弱"
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_signals.py -k tier -v`
Expected: FAIL（`strength_tier` 仍是 `None`）

- [ ] **Step 3: 實作五級分類**

在 `screener/signals.py` 的 `scan_momentum_health()` 裡，緊接在 Task 2 新增的 `rs_rank_pct` 賦值迴圈之後（仍在 `logger.info(...)` 之前）插入：

```python
    for row in results:
        rank = row["rs_rank_pct"]
        if row["ma_alignment"] == "空頭排列" and row["exit_3_rule_triggered"]:
            row["strength_tier"] = "超弱"
        elif row["ma_alignment"] == "多頭排列" and rank is not None and rank >= 0.8:
            row["strength_tier"] = "超強"
        elif row["ma_alignment"] == "多頭排列" and (rank is None or rank >= 0.5):
            row["strength_tier"] = "強"
        elif row["ma_alignment"] == "空頭排列":
            row["strength_tier"] = "弱"
        elif row["ma_alignment"] == "糾結":
            row["strength_tier"] = "整理"
        else:
            row["strength_tier"] = "弱"
```

- [ ] **Step 4: 執行測試確認通過**

Run: `pytest tests/test_signals.py -k tier -v`
Expected: 2 個測試 PASS

- [ ] **Step 5: 全專案回歸測試**

Run: `pytest -v`
Expected: 全部通過（已知例外：`tests/test_patterns.py::test_scan_patterns_returns_list` 若當下工作目錄缺 `data/screener.db` 會失敗，這是既有環境問題，跟本次改動無關，不算失敗）

- [ ] **Step 6: Commit**

```bash
git add screener/signals.py tests/test_signals.py
git commit -m "feat: scan_momentum_health 加上五級強弱分類（strength_tier）"
```

---

## 完成後的狀態

`screener/signals.py::scan_momentum_health()` 可獨立呼叫，回傳全市場個股的均線健檢結果，供下一階段（獨立 spec/plan）串接 `docs/health.html` 頁面使用。**這次 plan 不包含頁面串接**——下一步是另開 brainstorming，針對 `docs/health.html` 的視覺呈現用 `ui-ux-pro-max` skill 設計。
