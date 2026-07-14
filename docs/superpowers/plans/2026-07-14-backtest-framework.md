# 回測地基一般化 + 超額報酬 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `screener/backtest.py` 從「只驗巨量換手、只報絕對報酬」升級成「評估任一選股訊號預測力」的地基：任一 scanner → D+1 開盤進場 → 多天期**超額報酬**（減大盤、扣成本、漲停剔除）→ 依大盤 regime 分段的勝率/期望值。

**Architecture:** 重寫 `run_backtest()` 成吃 `scanner` callable；抽出價格索引、大盤指數、regime 判定、單筆前瞻報酬四個純 helper，`run_backtest` 只負責串接；`print_summary()` 升級成報超額報酬 + 分 regime。全部用合成 DuckDB 單元測試，不依賴真實 `data/`。

**Tech Stack:** Python、DuckDB、pandas（既有依賴，無新套件）。

## Global Constraints

- 對照 spec：`docs/superpowers/specs/2026-07-14-backtest-framework-design.md`
- **無 lookahead**：訊號用 ≤ D 的資料；進場最早 D+1。
- **大盤基準用「等權 universe 平均報酬」**（`daily_prices.change_pct` 逐日平均累積成指數）——因為此 DB 無 `taiex` 表，等權指數永遠可從 daily_prices 算出、且對「超額報酬」目的足夠。
- **進場價 = D+1 開盤**，`open` 為 NULL/NaN（目前 import 丟掉 open，見 spec 資料相依）時**退回 D+1 收盤**。
- 成本：來回 `cost_pct=0.6`（%），從 ret 與 excess 各扣一次。
- 漲停剔除門檻：D+1 開盤 ≥ D 收盤 × 1.095。
- 缺資料（H 天後無報價/新股）→ 該天期回 None，匯總時 `dropna`，不 crash。
- 天期預設 `horizons=(5, 10, 14)`。

---

### Task 1: 抽價格索引 helper + `run_backtest` 改吃任意 scanner（D+1 開盤進場、多天期報酬）

**Files:**
- Modify: `screener/backtest.py`（重寫 `run_backtest`，新增 `_build_price_index`、`_forward_return`）
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: 無（起點）。
- Produces:
  - `_build_price_index(db_path: str) -> tuple[dict, dict, dict]` 回 `(close_map, open_map, stock_dates)`；`close_map/open_map` key=`(stock_id, pd.Timestamp)`，`stock_dates` key=stock_id → 已排序 `list[pd.Timestamp]`。
  - `_forward_return(close_map, open_map, stock_dates, sid, d_ts, horizon) -> tuple[float|None, float|None]` 回 `(entry_price, ret_pct)`；進場 D+1 開盤（缺→D+1 收盤），出場 D+1+horizon 收盤；資料不足回 `(None, None)`。
  - `run_backtest(scanner, db_path=_DB_PATH, horizons=(5,10,14)) -> pd.DataFrame`；`scanner: Callable[[str, str], list[dict]]`（`(date_str, db_path) -> [{"stock_id":..., "close":...}, ...]`）。每列：`signal_date, stock_id, entry_price, ret_5, ret_10, ret_14`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_backtest.py` 加入合成 DB helper 與測試：

```python
import duckdb
import pandas as pd
from screener.backtest import run_backtest, _build_price_index, _forward_return


def _make_prices(tmp_path, rows):
    """rows: list of (stock_id, 'YYYY-MM-DD', open, close)"""
    db = str(tmp_path / "bt.db")
    con = duckdb.connect(db)
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, open DOUBLE, close DOUBLE, change_pct DOUBLE)")
    con.executemany(
        "INSERT INTO daily_prices VALUES (?, ?, ?, ?, NULL)",
        [(s, pd.to_datetime(d).date(), o, c) for (s, d, o, c) in rows],
    )
    con.close()
    return db


def test_forward_return_enters_next_day_open(tmp_path):
    # 訊號日 05-01；D+1(05-02) 開盤 100 進，D+1+5(05-07) 收 110 → +10%
    rows = [("2330", f"2026-05-{d:02d}", 100.0, 100.0) for d in range(1, 8)]
    rows[-1] = ("2330", "2026-05-07", 108.0, 110.0)  # 出場日收盤 110
    rows[1] = ("2330", "2026-05-02", 100.0, 101.0)   # 進場日開盤 100
    db = _make_prices(tmp_path, rows)
    close_map, open_map, stock_dates = _build_price_index(db)
    entry, ret = _forward_return(close_map, open_map, stock_dates, "2330",
                                 pd.Timestamp("2026-05-01"), 5)
    assert entry == 100.0            # 用 D+1 開盤，不是 D 收盤
    assert ret == 10.0              # (110-100)/100


def test_run_backtest_accepts_any_scanner(tmp_path):
    rows = [("2330", f"2026-05-{d:02d}", 100.0, 100.0 + d) for d in range(1, 10)]
    db = _make_prices(tmp_path, rows)

    def fake_scanner(date_str, db_path):
        return [{"stock_id": "2330", "close": 100.0}] if date_str == "2026-05-01" else []

    df = run_backtest(fake_scanner, db_path=db, horizons=(5,))
    assert len(df) == 1
    assert df.iloc[0]["signal_date"] == "2026-05-01"
    assert df.iloc[0]["stock_id"] == "2330"
    assert "ret_5" in df.columns
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_backtest.py::test_forward_return_enters_next_day_open tests/test_backtest.py::test_run_backtest_accepts_any_scanner -q`
Expected: FAIL（`ImportError: cannot import name '_build_price_index'` / `run_backtest` 舊簽章不吃 scanner）

- [ ] **Step 3: 重寫實作**

把 `screener/backtest.py` 的 `run_backtest` 及 helper 改成：

```python
def _build_price_index(db_path: str):
    con = duckdb.connect(db_path, read_only=True)
    df = con.execute("SELECT stock_id, date, open, close FROM daily_prices ORDER BY stock_id, date").df()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    close_map = {(r.stock_id, r.date): r.close for r in df.itertuples()}
    open_map = {(r.stock_id, r.date): r.open for r in df.itertuples()}
    stock_dates = {sid: sorted(g["date"].tolist()) for sid, g in df.groupby("stock_id")}
    return close_map, open_map, stock_dates


def _forward_return(close_map, open_map, stock_dates, sid, d_ts, horizon):
    future = [t for t in stock_dates.get(sid, []) if t > d_ts]
    if len(future) < horizon + 1:          # 需要 D+1(進場) 與 D+1+horizon(出場)
        return None, None
    entry_date, exit_date = future[0], future[horizon]
    entry = open_map.get((sid, entry_date))
    if entry is None or pd.isna(entry):    # open 缺(import 丟掉)→退回 D+1 收盤
        entry = close_map.get((sid, entry_date))
    exit_close = close_map.get((sid, exit_date))
    if entry is None or pd.isna(entry) or entry == 0 or exit_close is None or pd.isna(exit_close):
        return entry, None
    return entry, round((exit_close - entry) / entry * 100, 2)


def run_backtest(scanner, db_path: str = _DB_PATH, horizons=(5, 10, 14)) -> pd.DataFrame:
    close_map, open_map, stock_dates = _build_price_index(db_path)
    con = duckdb.connect(db_path, read_only=True)
    dates = [str(r[0])[:10] for r in con.execute(
        "SELECT DISTINCT date FROM daily_prices ORDER BY date").fetchall()]
    con.close()

    rows = []
    for d_str in dates:
        picks = scanner(d_str, db_path)
        if not picks:
            continue
        d_ts = pd.Timestamp(d_str)
        for sig in picks:
            sid = sig["stock_id"]
            row = {"signal_date": d_str, "stock_id": sid, "entry_price": None}
            for h in horizons:
                entry, ret = _forward_return(close_map, open_map, stock_dates, sid, d_ts, h)
                row["entry_price"] = entry
                row[f"ret_{h}"] = ret
            rows.append(row)
    return pd.DataFrame(rows)
```

（保留檔頭 `import duckdb`、`import pandas as pd`、`_DB_PATH`；舊的 `scan_volume_turnover` import 可留著給 Task 6 實跑用。）

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_backtest.py::test_forward_return_enters_next_day_open tests/test_backtest.py::test_run_backtest_accepts_any_scanner -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add screener/backtest.py tests/test_backtest.py
git commit -m "refactor(backtest): run_backtest 吃任意 scanner + D+1 開盤進場多天期報酬"
```

---

### Task 2: 大盤等權指數 + 超額報酬

**Files:**
- Modify: `screener/backtest.py`（新增 `_market_index`；`run_backtest` 每列加 `bench_H`/`excess_H`）
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: Task 1 的 `run_backtest`、`_forward_return`。
- Produces:
  - `_market_index(db_path: str) -> dict`：key=`pd.Timestamp` → 等權指數 level（`daily_prices.change_pct` 逐日平均、`(1+avg/100)` 連乘）。
  - `run_backtest` 每列新增 `bench_{h}`（大盤同進出區間報酬%）、`excess_{h}`（`ret_{h} - bench_{h}`）。

- [ ] **Step 1: 寫失敗測試**

```python
def test_run_backtest_excess_return_vs_market(tmp_path):
    # 2330 D+1→D+1+5 漲 10%；同期大盤(這裡只有 2330 一檔→大盤=它自己)→ excess≈0
    # 再加一檔 9999 全程不動，把大盤拉低，讓 2330 有正 excess
    rows = []
    for d in range(1, 10):
        rows.append(("2330", f"2026-05-{d:02d}", 100.0, 100.0))
        rows.append(("9999", f"2026-05-{d:02d}", 50.0, 50.0))
    # 2330 進場日(05-02)開盤100、出場日(05-07)收110
    rows = [r for r in rows if not (r[0]=="2330" and r[1] in ("2026-05-02","2026-05-07"))]
    rows += [("2330","2026-05-02",100.0,100.0), ("2330","2026-05-07",100.0,110.0)]
    # change_pct：給 2330 出場日 +10、其餘 0，讓大盤等權指數只被 2330 的 +10 稍微拉抬
    db = _make_prices_with_change(tmp_path, rows)

    def scanner(ds, dbp):
        return [{"stock_id":"2330","close":100.0}] if ds=="2026-05-01" else []

    df = run_backtest(scanner, db_path=db, horizons=(5,))
    r = df.iloc[0]
    assert r["bench_5"] > 0                 # 大盤同期>0(2330 自己的漲幅也拉抬等權指數)
    assert r["excess_5"] < r["ret_5"]      # 扣掉大盤後 < 原始報酬
    assert abs(r["excess_5"] - (r["ret_5"] - r["bench_5"])) < 1e-6  # cost 之後仍成立
```

同時在測試檔加 `_make_prices_with_change`（跟 `_make_prices` 一樣但 change_pct 由參數帶）：

```python
def _make_prices_with_change(tmp_path, rows):
    db = str(tmp_path / "bt2.db")
    con = duckdb.connect(db)
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, open DOUBLE, close DOUBLE, change_pct DOUBLE)")
    prev = {}
    ins = []
    for (s, d, o, c) in rows:
        chg = 0.0 if s not in prev else round((c/prev[s]-1)*100, 4)
        prev[s] = c
        ins.append((s, pd.to_datetime(d).date(), o, c, chg))
    con.executemany("INSERT INTO daily_prices VALUES (?,?,?,?,?)", ins)
    con.close()
    return db
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_backtest.py::test_run_backtest_excess_return_vs_market -q`
Expected: FAIL（`KeyError: 'excess_5'`）

- [ ] **Step 3: 實作**

`screener/backtest.py` 加 `_market_index`，並在 `run_backtest` 串接：

```python
def _market_index(db_path: str) -> dict:
    con = duckdb.connect(db_path, read_only=True)
    df = con.execute(
        "SELECT date, AVG(change_pct) AS c FROM daily_prices GROUP BY date ORDER BY date"
    ).df()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    df["idx"] = (1 + df["c"].fillna(0) / 100).cumprod()
    return dict(zip(df["date"], df["idx"]))


def _bench_return(idx_map, stock_dates_any, sid, d_ts, horizon):
    """大盤等權指數在該股 D+1→D+1+horizon 同一進出日的報酬%。"""
    future = [t for t in stock_dates_any.get(sid, []) if t > d_ts]
    if len(future) < horizon + 1:
        return None
    e, x = future[0], future[horizon]
    ie, ix = idx_map.get(e), idx_map.get(x)
    if ie is None or ix is None or ie == 0:
        return None
    return round((ix / ie - 1) * 100, 2)
```

在 `run_backtest` 開頭加 `idx_map = _market_index(db_path)`；迴圈內每個 horizon 算完 `ret` 後：

```python
                row[f"ret_{h}"] = ret
                bench = _bench_return(idx_map, stock_dates, sid, d_ts, h)
                row[f"bench_{h}"] = bench
                row[f"excess_{h}"] = (round(ret - bench, 2)
                                      if ret is not None and bench is not None else None)
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_backtest.py::test_run_backtest_excess_return_vs_market -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add screener/backtest.py tests/test_backtest.py
git commit -m "feat(backtest): 大盤等權指數 + 超額報酬(excess = ret - 大盤同期)"
```

---

### Task 3: 漲停買不到剔除（no_fill）

**Files:**
- Modify: `screener/backtest.py`（`run_backtest` 每列加 `no_fill`）
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: Task 1/2 的 `run_backtest`、`close_map`/`open_map`。
- Produces: `run_backtest(..., limit_up_skip=True)`；每列新增 `no_fill: bool`（D+1 開盤 ≥ D 收盤 ×1.095）。

- [ ] **Step 1: 寫失敗測試**

```python
def test_run_backtest_flags_limit_up_no_fill(tmp_path):
    # D(05-01)收100，D+1(05-02)開110(+10%>9.5%漲停)→ 買不到
    rows = [("2330", f"2026-05-{d:02d}", 100.0, 100.0) for d in range(1, 10)]
    rows = [r for r in rows if not (r[0]=="2330" and r[1] in ("2026-05-01","2026-05-02"))]
    rows += [("2330","2026-05-01",100.0,100.0), ("2330","2026-05-02",110.0,111.0)]
    db = _make_prices(tmp_path, rows)

    def scanner(ds, dbp):
        return [{"stock_id":"2330","close":100.0}] if ds=="2026-05-01" else []

    df = run_backtest(scanner, db_path=db, horizons=(5,))
    assert bool(df.iloc[0]["no_fill"]) is True
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_backtest.py::test_run_backtest_flags_limit_up_no_fill -q`
Expected: FAIL（`KeyError: 'no_fill'`）

- [ ] **Step 3: 實作**

`run_backtest` 迴圈內，取得 `d_close`（D 當日收盤）與 `entry`（D+1 開盤），加 `no_fill`：

```python
        for sig in picks:
            sid = sig["stock_id"]
            d_close = close_map.get((sid, d_ts))
            future = [t for t in stock_dates.get(sid, []) if t > d_ts]
            d1_open = open_map.get((sid, future[0])) if future else None
            if d1_open is None or pd.isna(d1_open):
                d1_open = close_map.get((sid, future[0])) if future else None
            no_fill = bool(limit_up_skip and d_close and d1_open
                           and d1_open >= d_close * 1.095)
            row = {"signal_date": d_str, "stock_id": sid,
                   "entry_price": None, "no_fill": no_fill}
```

並把 `run_backtest` 簽章加 `limit_up_skip: bool = True`。

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_backtest.py::test_run_backtest_flags_limit_up_no_fill -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add screener/backtest.py tests/test_backtest.py
git commit -m "feat(backtest): 標記漲停買不到(no_fill),主結果可剔除"
```

---

### Task 4: 扣交易成本

**Files:**
- Modify: `screener/backtest.py`（`ret_{h}`/`excess_{h}` 扣 `cost_pct`）
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: Task 2 的 `ret`/`excess`。
- Produces: `run_backtest(..., cost_pct: float = 0.6)`；`ret_{h}`、`excess_{h}` 皆已扣一次來回成本。

- [ ] **Step 1: 寫失敗測試**

```python
def test_run_backtest_deducts_cost(tmp_path):
    rows = [("2330", f"2026-05-{d:02d}", 100.0, 100.0) for d in range(1, 10)]
    rows = [r for r in rows if not (r[0]=="2330" and r[1] in ("2026-05-02","2026-05-07"))]
    rows += [("2330","2026-05-02",100.0,100.0), ("2330","2026-05-07",100.0,110.0)]
    db = _make_prices(tmp_path, rows)
    def scanner(ds, dbp):
        return [{"stock_id":"2330","close":100.0}] if ds=="2026-05-01" else []
    df = run_backtest(scanner, db_path=db, horizons=(5,), cost_pct=0.6)
    assert df.iloc[0]["ret_5"] == round(10.0 - 0.6, 2)   # 9.4
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_backtest.py::test_run_backtest_deducts_cost -q`
Expected: FAIL（`ret_5 == 10.0`，未扣成本）

- [ ] **Step 3: 實作**

`run_backtest` 簽章加 `cost_pct: float = 0.6`；算完 `ret`/`excess` 後扣成本：

```python
                if ret is not None:
                    ret = round(ret - cost_pct, 2)
                row[f"ret_{h}"] = ret
                bench = _bench_return(idx_map, stock_dates, sid, d_ts, h)
                row[f"bench_{h}"] = bench
                row[f"excess_{h}"] = (round(ret - bench, 2)
                                      if ret is not None and bench is not None else None)
```

（注意：`ret` 先扣成本，`excess = 已扣成本的 ret − bench`。）

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_backtest.py::test_run_backtest_deducts_cost -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add screener/backtest.py tests/test_backtest.py
git commit -m "feat(backtest): ret/excess 扣來回交易成本(預設0.6%)"
```

---

### Task 5: 大盤 regime 分段標記

**Files:**
- Modify: `screener/backtest.py`（新增 `_regime_at`；`run_backtest` 每列加 `regime`）
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: Task 2 的 `_market_index`。
- Produces:
  - `_regime_at(idx_map, sorted_market_dates, d_ts, lookback=20, up=3.0, down=-3.0) -> str`：用大盤等權指數「訊號日 D 回看 lookback 日報酬」分 `"多頭"`/`"盤整"`/`"空頭"`；資料不足回 `"?"`。
  - `run_backtest` 每列新增 `regime`（該訊號日的大盤氛圍），供 `print_summary` 分段。

- [ ] **Step 1: 寫失敗測試**

```python
def test_regime_at_classifies_market_trend(tmp_path):
    from screener.backtest import _market_index, _regime_at
    # 造一段大盤：前 22 天每天 +0.5%(累積約 +11%)→ D 應判「多頭」
    rows = []
    price = 100.0
    for d in range(1, 26):
        price *= 1.005
        rows.append(("MKT", f"2026-05-{d:02d}", price, price))
    db = _make_prices_with_change(tmp_path, rows)
    idx = _market_index(db)
    sdates = sorted(idx.keys())
    reg = _regime_at(idx, sdates, pd.Timestamp("2026-05-25"), lookback=20, up=3.0, down=-3.0)
    assert reg == "多頭"
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_backtest.py::test_regime_at_classifies_market_trend -q`
Expected: FAIL（`cannot import name '_regime_at'`）

- [ ] **Step 3: 實作**

```python
def _regime_at(idx_map, sorted_dates, d_ts, lookback=20, up=3.0, down=-3.0) -> str:
    past = [t for t in sorted_dates if t <= d_ts]
    if len(past) < lookback + 1:
        return "?"
    now, ref = idx_map[past[-1]], idx_map[past[-1 - lookback]]
    if ref == 0:
        return "?"
    r = (now / ref - 1) * 100
    return "多頭" if r >= up else ("空頭" if r <= down else "盤整")
```

`run_backtest`：算 `idx_map` 後 `sorted_mkt = sorted(idx_map.keys())`；每列加 `row["regime"] = _regime_at(idx_map, sorted_mkt, d_ts)`。

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_backtest.py::test_regime_at_classifies_market_trend -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add screener/backtest.py tests/test_backtest.py
git commit -m "feat(backtest): 每筆訊號標記大盤 regime(多頭/盤整/空頭),供分段驗"
```

---

### Task 6: `print_summary` 升級（超額報酬 + 漲停剔除 + 分 regime）

**Files:**
- Modify: `screener/backtest.py`（重寫 `print_summary`）
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: Task 1-5 的 DataFrame 欄位（`ret_{h}`、`excess_{h}`、`no_fill`、`regime`）。
- Produces: `print_summary(df, horizons=(5,10,14), skip_no_fill=True) -> None`（純列印，可安全對空 df）。

- [ ] **Step 1: 寫失敗測試**（驗不 crash + 有分段區塊字樣）

```python
def test_print_summary_runs_with_new_columns(capsys, tmp_path):
    from screener.backtest import print_summary
    df = pd.DataFrame([
        {"signal_date":"2026-05-01","stock_id":"2330","entry_price":100.0,"no_fill":False,
         "regime":"多頭","ret_5":9.4,"bench_5":3.0,"excess_5":6.4},
        {"signal_date":"2026-05-02","stock_id":"2454","entry_price":50.0,"no_fill":True,
         "regime":"盤整","ret_5":-2.0,"bench_5":0.0,"excess_5":-2.0},
    ])
    print_summary(df, horizons=(5,))
    out = capsys.readouterr().out
    assert "超額" in out
    assert "多頭" in out or "regime" in out.lower()
    # 空 df 不 crash
    print_summary(pd.DataFrame(), horizons=(5,))
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_backtest.py::test_print_summary_runs_with_new_columns -q`
Expected: FAIL（舊 `print_summary` 找不到 `excess`/`regime`、或對空 df/新欄位報錯）

- [ ] **Step 3: 實作**（重寫 `print_summary`）

```python
def print_summary(df: pd.DataFrame, horizons=(5, 10, 14), skip_no_fill=True) -> None:
    if df.empty:
        print("無訊號資料")
        return
    used = df[~df["no_fill"]] if (skip_no_fill and "no_fill" in df.columns) else df
    n_skip = len(df) - len(used)
    print("=" * 60)
    print(f"  回測結果  訊號 {len(df)} 筆（漲停剔除 {n_skip}）  "
          f"日期 {df['signal_date'].min()} ~ {df['signal_date'].max()}")
    print("=" * 60)

    def _block(sub, tag):
        for h in horizons:
            col, exc = f"ret_{h}", f"excess_{h}"
            if exc not in sub.columns:
                continue
            s = sub[sub[exc].notna()]
            if s.empty:
                continue
            win = (s[exc] > 0).mean() * 100
            avg_ex = s[exc].mean()
            avg_ret = s[col].mean()
            wins = s[s[exc] > 0][exc]
            loss = s[s[exc] <= 0][exc]
            ev = win/100 * (wins.mean() if len(wins) else 0) + (1-win/100) * (loss.mean() if len(loss) else 0)
            print(f"  [{tag}] D+{h:<2}  n={len(s):<4} 勝率(超額>0) {win:4.0f}%  "
                  f"平均超額 {avg_ex:+.2f}%  平均報酬 {avg_ret:+.2f}%  期望值 {ev:+.2f}%")

    _block(used, "全部")
    if "regime" in used.columns:
        print("-" * 60)
        for reg in ["多頭", "盤整", "空頭"]:
            sub = used[used["regime"] == reg]
            if not sub.empty:
                _block(sub, reg)
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_backtest.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add screener/backtest.py tests/test_backtest.py
git commit -m "feat(backtest): print_summary 報超額報酬+漲停剔除+分 regime 段"
```

---

## Out of scope（本 plan 不做，spec 已列）

- 補 `open` import（`CAST(open AS DOUBLE)` + reimport）：另做；未補前 D+1 進場自動退回 D+1 收盤。
- 還原股價（除權息跳空）：v1 用原始價，除權息日的離群報酬先靠 excess 對照稀釋。
- 規則出場（抱到跌破5MA下彎長黑）：需先有出場邏輯（筆記 B2）。
- 進貨分/籌碼訊號回測：等籌碼資料累積夠。

## 實跑驗收（plan 做完後、非 Task）

拿現有 `scan_volume_turnover` 包成 scanner 對真實 `data/screener.db`（8 年）跑一發：
```python
from screener.backtest import run_backtest, print_summary
from screener.signals import scan_volume_turnover
df = run_backtest(lambda d, p: scan_volume_turnover(d, db_path=p), db_path="data/screener.db")
print_summary(df)
```
看「巨量換手」在多頭/盤整/空頭各段的超額報酬有沒有 edge。
