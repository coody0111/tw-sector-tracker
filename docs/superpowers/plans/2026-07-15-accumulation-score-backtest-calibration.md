# 進貨分回測校準 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `screener/patterns.py::calc_accumulation_score()`（進貨分）接進 `screener/backtest.py::run_backtest()`（通用回測框架），用真實歷史資料驗證進貨分切點（封頂40/30/20、閘門0.5、label門檻40、weakening定義）。

**Architecture:** 新增一個 scanner 工廠函式 `scan_accumulation_score()`，內部預先建好大戶/近5日報酬的「任意歷史日期」查詢索引（一次查詢建 dict，跟 `backtest.py::_build_price_index` 同手法），每天呼叫既有 `scan_institutional()` 拿外資/投信 streak，餵進既有 `calc_accumulation_score()`；額外用一個 side-effect 快取字典把分數細節帶出 `run_backtest()`（因為 `run_backtest()` 本身只認 `sig["stock_id"]`，不改動它）。`print_accumulation_calibration()` 消費快取印出分數分桶報告。`main.py` 補上 CLI 入口，順便修好目前已壞掉的 `--backtest`。全部新增，不修改 `screener/backtest.py`。

**Tech Stack:** Python、DuckDB、pandas（既有依賴，無新套件）。

## Global Constraints

- 對照 spec：`docs/superpowers/specs/2026-07-15-accumulation-score-backtest-calibration-design.md`
- **不修改 `screener/backtest.py`**：Task 1-6 剛做完、等 Debugger 驗證中。
- 大戶資料週頻、「as of 某日」查詢一律 forward-fill（找 ≤ 目標日期的最新一筆），不做人工插值。
- 缺資料（大戶/報酬查無資料）→ 回 `None`，交給既有 `calc_accumulation_score()` 的防呆處理，不 crash。

---

### Task 1: 大戶/近5日報酬「任意歷史日期」查詢 helper

**Files:**
- Modify: `screener/patterns.py`（新增 `_shareholder_history_index`、`_shareholder_as_of`、`_recent_return_index`、`_recent_return_as_of`，加在 `_accumulation_label()` 之後）
- Test: `tests/test_patterns.py`

**Interfaces:**
- Consumes: 無（起點，純讀 DB）。
- Produces：
  - `_shareholder_history_index(db_path: str) -> dict`：key=stock_id → 依日期排序的 `[{"date": pd.Timestamp, "streak": int|None, "lv12_chg": int|None, "lv15_chg": int|None}, ...]`。
  - `_shareholder_as_of(index: dict, stock_id: str, d_ts: pd.Timestamp) -> tuple[int|None, int|None]`：回 `(streak, holder_net_lots)`，`holder_net_lots = lv12_chg + lv15_chg`；查無資料回 `(None, None)`。
  - `_recent_return_index(db_path: str) -> dict`：key=stock_id → 依日期排序的 `[(pd.Timestamp, close), ...]`。
  - `_recent_return_as_of(index: dict, stock_id: str, d_ts: pd.Timestamp, days: int = 5) -> float|None`：`(最新收盤/N日前收盤 − 1) × 100`，只用 `<= d_ts` 的資料；資料不足回 `None`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_patterns.py` 檔尾加入（先加一行 import，這四個函式是這個 Task 新增的）：

```python
from screener.patterns import (
    _shareholder_history_index, _shareholder_as_of,
    _recent_return_index, _recent_return_as_of,
)


def _make_shareholder_db(tmp_path, rows):
    """rows: list of (stock_id, 'YYYY-MM-DD', streak, lv12_shares, lv15_shares)"""
    db = str(tmp_path / "sh.db")
    con = duckdb.connect(db)
    con.execute("""
        CREATE TABLE shareholder (
            stock_id VARCHAR, date DATE, lv12_15_pct DOUBLE, lv12_15_cnt INTEGER,
            lv12_15_shares BIGINT, total_shares BIGINT, week_chg DOUBLE, streak INTEGER,
            lv12_shares BIGINT, lv12_pct DOUBLE, lv15_shares BIGINT, lv15_pct DOUBLE
        )
    """)
    con.executemany(
        "INSERT INTO shareholder (stock_id, date, streak, lv12_shares, lv15_shares) VALUES (?, ?, ?, ?, ?)",
        [(s, pd.to_datetime(d).date(), streak, lv12, lv15) for (s, d, streak, lv12, lv15) in rows],
    )
    con.close()
    return db


def test_shareholder_as_of_uses_historical_week_not_latest(tmp_path):
    """驗證「as of 某日」查的是那天當下最新的一週資料，不是資料庫裡整體最新一筆
    （最容易犯的 bug：forward-fill 方向抓錯，見設計 spec 測試策略#2）。"""
    rows = [
        ("2330", "2026-05-01", 1, 100000, 50000),   # 第1週
        ("2330", "2026-05-08", 2, 120000, 55000),   # 第2週：lv12_chg=+20000, lv15_chg=+5000
        ("2330", "2026-05-15", 3, 150000, 40000),   # 第3週：lv12_chg=+30000, lv15_chg=-15000
    ]
    db = _make_shareholder_db(tmp_path, rows)
    index = _shareholder_history_index(db)

    streak, holder_net_lots = _shareholder_as_of(index, "2330", pd.Timestamp("2026-05-10"))
    assert streak == 2
    assert holder_net_lots == 25000  # 用第2週的變化，不是第3週的 15000

    streak1, holder1 = _shareholder_as_of(index, "2330", pd.Timestamp("2026-05-03"))
    assert streak1 == 1
    assert holder1 is None  # 第1週沒有前一週可比

    streak0, holder0 = _shareholder_as_of(index, "2330", pd.Timestamp("2026-04-01"))
    assert streak0 is None
    assert holder0 is None  # 所有資料之前，查無資料


def test_recent_return_as_of_uses_only_past_data(tmp_path):
    """近5日報酬「as of d_ts」只能用 <= d_ts 的收盤價，不能偷看未來
    （回測最基本的 no-lookahead 要求，見設計 spec 資料索引細節段落）。"""
    db = str(tmp_path / "px.db")
    con = duckdb.connect(db)
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, close DOUBLE)")
    rows = [("2330", f"2026-05-{d:02d}", 100.0 + d) for d in range(1, 11)]
    con.executemany("INSERT INTO daily_prices VALUES (?, ?, ?)",
                     [(s, pd.to_datetime(d).date(), c) for (s, d, c) in rows])
    con.close()

    index = _recent_return_index(db)
    ret = _recent_return_as_of(index, "2330", pd.Timestamp("2026-05-06"), days=5)
    assert ret == round((106.0 - 101.0) / 101.0 * 100, 2)

    ret_insufficient = _recent_return_as_of(index, "2330", pd.Timestamp("2026-05-03"), days=5)
    assert ret_insufficient is None
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_patterns.py::test_shareholder_as_of_uses_historical_week_not_latest tests/test_patterns.py::test_recent_return_as_of_uses_only_past_data -q`
Expected: FAIL（`ImportError` / `NameError: name '_shareholder_history_index' is not defined`）

- [ ] **Step 3: 實作**

在 `screener/patterns.py` 的 `_accumulation_label()` 函式之後加入：

```python
def _shareholder_history_index(db_path: str) -> dict:
    """
    讀一次 shareholder 全表，依 stock_id 分組、按 date 排序，計算每筆的
    lv12_chg/lv15_chg（跟同股前一筆比較，用 pandas diff，不逐股查 DB），
    回傳 {stock_id: [{"date":..., "streak":..., "lv12_chg":..., "lv15_chg":...}, ...]}。
    """
    con = duckdb.connect(db_path, read_only=True)
    df = con.execute(
        "SELECT stock_id, date, streak, lv12_shares, lv15_shares FROM shareholder ORDER BY stock_id, date"
    ).df()
    con.close()

    df["date"] = pd.to_datetime(df["date"])
    index = {}
    for sid, grp in df.groupby("stock_id"):
        grp = grp.sort_values("date").reset_index(drop=True)
        grp["lv12_chg"] = grp["lv12_shares"].diff()
        grp["lv15_chg"] = grp["lv15_shares"].diff()
        rows = []
        for r in grp.itertuples():
            rows.append({
                "date": r.date,
                "streak": None if pd.isna(r.streak) else int(r.streak),
                "lv12_chg": None if pd.isna(r.lv12_chg) else int(r.lv12_chg),
                "lv15_chg": None if pd.isna(r.lv15_chg) else int(r.lv15_chg),
            })
        index[str(sid)] = rows
    return index


def _shareholder_as_of(index: dict, stock_id: str, d_ts) -> tuple:
    """回傳 <= d_ts 的最新一筆大戶資料 (streak, holder_net_lots)；查無資料回 (None, None)。"""
    rows = index.get(stock_id, [])
    candidates = [r for r in rows if r["date"] <= d_ts]
    if not candidates:
        return None, None
    latest = candidates[-1]
    streak = latest["streak"]
    if latest["lv12_chg"] is None or latest["lv15_chg"] is None:
        holder_net_lots = None
    else:
        holder_net_lots = latest["lv12_chg"] + latest["lv15_chg"]
    return streak, holder_net_lots


def _recent_return_index(db_path: str) -> dict:
    """
    讀一次 daily_prices 全表，依 stock_id 分組、按 date 排序，回傳
    {stock_id: [(date, close), ...]}，供 _recent_return_as_of() 查詢。
    """
    con = duckdb.connect(db_path, read_only=True)
    df = con.execute(
        "SELECT stock_id, date, close FROM daily_prices ORDER BY stock_id, date"
    ).df()
    con.close()

    df["date"] = pd.to_datetime(df["date"])
    index = {}
    for sid, grp in df.groupby("stock_id"):
        grp = grp.sort_values("date")
        index[str(sid)] = list(zip(grp["date"], grp["close"]))
    return index


def _recent_return_as_of(index: dict, stock_id: str, d_ts, days: int = 5):
    """
    回傳 <= d_ts 的最近 days 個交易日累積報酬%（收盤價比值法，跟
    screener/database.py::get_rolling_returns() 同公式，但支援任意歷史日期）。
    資料不足或除零回 None。
    """
    rows = [(d, c) for d, c in index.get(stock_id, []) if d <= d_ts]
    if len(rows) < days + 1:
        return None
    c0 = rows[-1][1]
    cn = rows[-1 - days][1]
    if c0 is None or cn is None or pd.isna(c0) or pd.isna(cn) or cn == 0:
        return None
    return round((c0 - cn) / cn * 100, 2)
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_patterns.py::test_shareholder_as_of_uses_historical_week_not_latest tests/test_patterns.py::test_recent_return_as_of_uses_only_past_data -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add screener/patterns.py tests/test_patterns.py
git commit -m "feat(patterns): 大戶/近5日報酬「任意歷史日期」查詢 helper，供回測用"
```

---

### Task 2: `scan_accumulation_score()` scanner 工廠

**Files:**
- Modify: `screener/patterns.py`（新增 `scan_accumulation_score`，加在 Task 1 新函式之後）
- Test: `tests/test_patterns.py`

**Interfaces:**
- Consumes: Task 1 的 `_shareholder_history_index`/`_shareholder_as_of`/`_recent_return_index`/`_recent_return_as_of`；既有 `screener.institutional.scan_institutional`；既有 `calc_accumulation_score`。
- Produces: `scan_accumulation_score(db_path: str = _DB_PATH) -> tuple[Callable, dict]`，回傳 `(scanner, cache)`；`scanner` 符合 `run_backtest()` 介面 `Callable[[str, str], list[dict]]`；`cache` key=`(date_str, stock_id)` → `calc_accumulation_score()` 完整回傳值。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_patterns.py` 加入（先加一行 import）：

```python
from screener.patterns import scan_accumulation_score


def _make_full_accumulation_db(tmp_path):
    """建 institutional + shareholder + daily_prices 三張最小表，模擬 2330 在
    訊號日 2026-05-08 當下：外資連買5日(全正)、投信連買3日(前2天賣、後3天買)、
    大戶第2週資料(streak=2, holder_net_lots=20000+5000=25000)、近5日報酬>0。"""
    db = str(tmp_path / "acc.db")
    con = duckdb.connect(db)
    con.execute("CREATE TABLE institutional (stock_id VARCHAR, date DATE, foreign_net BIGINT, trust_net BIGINT, dealer_net BIGINT, total_net BIGINT)")
    con.execute("""
        CREATE TABLE shareholder (
            stock_id VARCHAR, date DATE, lv12_15_pct DOUBLE, lv12_15_cnt INTEGER,
            lv12_15_shares BIGINT, total_shares BIGINT, week_chg DOUBLE, streak INTEGER,
            lv12_shares BIGINT, lv12_pct DOUBLE, lv15_shares BIGINT, lv15_pct DOUBLE
        )
    """)
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT, change DOUBLE, change_pct DOUBLE)")

    inst_rows = [
        ("2330", "2026-05-04", 1000, -500),
        ("2330", "2026-05-05", 1000, -500),
        ("2330", "2026-05-06", 1000, 800),
        ("2330", "2026-05-07", 1000, 800),
        ("2330", "2026-05-08", 1000, 800),
    ]
    con.executemany(
        "INSERT INTO institutional VALUES (?, ?, ?, ?, 0, ?)",
        [(s, pd.to_datetime(d).date(), f, t, f + t) for (s, d, f, t) in inst_rows],
    )

    sh_rows = [
        ("2330", "2026-05-01", 1, 100000, 50000),
        ("2330", "2026-05-08", 2, 120000, 55000),
    ]
    con.executemany(
        "INSERT INTO shareholder (stock_id, date, streak, lv12_shares, lv15_shares) VALUES (?, ?, ?, ?, ?)",
        [(s, pd.to_datetime(d).date(), streak, lv12, lv15) for (s, d, streak, lv12, lv15) in sh_rows],
    )

    px_rows = [("2330", f"2026-05-{d:02d}", 100.0 + d) for d in range(1, 9)]
    con.executemany(
        "INSERT INTO daily_prices (stock_id, date, close, change_pct) VALUES (?, ?, ?, 0.0)",
        [(s, pd.to_datetime(d).date(), c) for (s, d, c) in px_rows],
    )
    con.close()
    return db


def test_scan_accumulation_score_computes_score_for_signal_date(tmp_path):
    """驗證 scan_accumulation_score() 在某一天的訊號清單裡，每檔股票的分數是用
    calc_accumulation_score() 對「as of 那天」的五個輸入算出來的，cache 存了完整明細。
    手動推演：foreign_streak=5(40分) + trust_streak=3(18分) + sh_streak=2(14分)
    = 72分；weakening=False(holder_net_lots=25000>0)；近5日報酬(108-103)/103*100=4.85%>0
    → confirmed → gate=1.0 → score=72 → label='進貨'。"""
    db = _make_full_accumulation_db(tmp_path)
    scanner, cache = scan_accumulation_score(db_path=db)

    picks = scanner("2026-05-08", db)
    assert len(picks) == 1
    assert picks[0]["stock_id"] == "2330"

    result = cache[("2026-05-08", "2330")]
    assert result["score"] == 72
    assert result["weakening"] is False
    assert result["label"] == "進貨"
    assert result["holder_net_lots"] == 25000
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_patterns.py::test_scan_accumulation_score_computes_score_for_signal_date -q`
Expected: FAIL（`NameError: name 'scan_accumulation_score' is not defined`）

- [ ] **Step 3: 實作**

在 `screener/patterns.py` 加入（`_recent_return_as_of` 之後）：

```python
def scan_accumulation_score(db_path: str = _DB_PATH):
    """
    回傳 (scanner, cache) tuple（見設計 spec
    docs/superpowers/specs/2026-07-15-accumulation-score-backtest-calibration-design.md）：
    - scanner: 符合 run_backtest() 介面的 Callable[[str, str], list[dict]]，每天對
      scan_institutional() 撈到的全市場股票算一次進貨分。
    - cache: dict，key=(date_str, stock_id) → calc_accumulation_score() 完整回傳值。
      run_backtest() 本身只認 sig["stock_id"]，不會把 score 等欄位帶進輸出，這裡用
      side-effect 快取事後 merge 回結果 DataFrame，刻意不修改 screener/backtest.py。
    """
    from screener.institutional import scan_institutional

    sh_index = _shareholder_history_index(db_path)
    ret_index = _recent_return_index(db_path)
    cache: dict = {}

    def _scan(date_str: str, scan_db_path: str) -> list:
        d_ts = pd.Timestamp(date_str)
        picks = []
        for stock in scan_institutional(date_str, db_path=scan_db_path):
            sid = stock["stock_id"]
            sh_streak, holder_net_lots = _shareholder_as_of(sh_index, sid, d_ts)
            recent_return = _recent_return_as_of(ret_index, sid, d_ts, days=5)
            result = calc_accumulation_score(
                foreign_streak=stock["foreign_streak"],
                trust_streak=stock["trust_streak"],
                sh_streak=sh_streak,
                holder_net_lots=holder_net_lots,
                recent_return=recent_return,
            )
            cache[(date_str, sid)] = result
            picks.append({"stock_id": sid, "close": stock.get("close")})
        return picks

    return _scan, cache
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_patterns.py::test_scan_accumulation_score_computes_score_for_signal_date -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add screener/patterns.py tests/test_patterns.py
git commit -m "feat(patterns): scan_accumulation_score() 把進貨分包成 run_backtest scanner"
```

---

### Task 3: `print_accumulation_calibration()` 校準報告

**Files:**
- Modify: `screener/patterns.py`（新增 `print_accumulation_calibration`，加在 `scan_accumulation_score` 之後）
- Test: `tests/test_patterns.py`

**Interfaces:**
- Consumes: `run_backtest()` 的輸出 DataFrame（含 `signal_date`/`stock_id`/`no_fill`/`excess_H`）、Task 2 的 `cache`。
- Produces: `print_accumulation_calibration(df: pd.DataFrame, cache: dict, horizons=(5, 10, 14)) -> None`（純列印，空 df 安全）。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_patterns.py` 加入（先加一行 import）：

```python
from screener.patterns import print_accumulation_calibration


def test_print_accumulation_calibration_runs_with_buckets_and_boundary_case(capsys):
    df = pd.DataFrame([
        {"signal_date": "2026-05-01", "stock_id": "2330", "no_fill": False, "excess_5": 6.0},
        {"signal_date": "2026-05-02", "stock_id": "2454", "no_fill": False, "excess_5": -1.0},
        {"signal_date": "2026-05-03", "stock_id": "8261", "no_fill": False, "excess_5": 3.0},
    ])
    cache = {
        ("2026-05-01", "2330"): {"score": 72, "weakening": False, "holder_net_lots": 25000},
        ("2026-05-02", "2454"): {"score": 10, "weakening": False, "holder_net_lots": None},
        ("2026-05-03", "8261"): {"score": 20, "weakening": True, "holder_net_lots": 920},
    }
    print_accumulation_calibration(df, cache, horizons=(5,))
    out = capsys.readouterr().out
    assert "60-100分" in out
    assert "富鼎型邊界" in out

    # 空 df 不 crash
    print_accumulation_calibration(pd.DataFrame(), {}, horizons=(5,))
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_patterns.py::test_print_accumulation_calibration_runs_with_buckets_and_boundary_case -q`
Expected: FAIL（`NameError: name 'print_accumulation_calibration' is not defined`）

- [ ] **Step 3: 實作**

```python
def print_accumulation_calibration(df: pd.DataFrame, cache: dict, horizons=(5, 10, 14)) -> None:
    """
    印出進貨分校準報告：
    1. 依 score 分桶（0-19/20-39/40-59/60-100）看各桶平均超額報酬/勝率，回答
       「分數越高，後續表現是否真的越好」。
    2. weakening=True 但 holder_net_lots>0 的「富鼎型邊界案例」子集，跟其餘樣本對照，
       回答「純大戶進貨、法人沒動被判轉弱，是否真的該轉弱」。
    預設剔除 no_fill=True（漲停買不到）的訊號，比照 backtest.py::print_summary()。
    """
    if df.empty:
        print("無訊號資料")
        return

    df = df.copy()
    df["score"] = df.apply(
        lambda r: cache.get((r["signal_date"], r["stock_id"]), {}).get("score"), axis=1)
    df["weakening"] = df.apply(
        lambda r: cache.get((r["signal_date"], r["stock_id"]), {}).get("weakening"), axis=1)
    df["holder_net_lots"] = df.apply(
        lambda r: cache.get((r["signal_date"], r["stock_id"]), {}).get("holder_net_lots"), axis=1)

    used = df[~df["no_fill"]] if "no_fill" in df.columns else df

    def _block(sub, tag, h):
        exc = f"excess_{h}"
        if exc not in sub.columns:
            return
        s = sub[sub[exc].notna()]
        if s.empty:
            print(f"  [{tag}] D+{h:<2}  n=0")
            return
        win = (s[exc] > 0).mean() * 100
        avg_ex = s[exc].mean()
        print(f"  [{tag}] D+{h:<2}  n={len(s):<4} 勝率(超額>0) {win:4.0f}%  平均超額 {avg_ex:+.2f}%")

    print("=" * 60)
    print("  進貨分分數分桶（score 越高，後續超額報酬是否越好？）")
    print("=" * 60)
    buckets = [(0, 20, "0-19分"), (20, 40, "20-39分"), (40, 60, "40-59分"), (60, 101, "60-100分")]
    for lo, hi, tag in buckets:
        sub = used[(used["score"] >= lo) & (used["score"] < hi)]
        if sub.empty:
            continue
        for h in horizons:
            _block(sub, tag, h)

    print("-" * 60)
    print("  富鼎型邊界案例（weakening=True 但大戶當週淨增 >0）vs 其餘樣本")
    print("-" * 60)
    is_boundary = (used["weakening"] == True) & (used["holder_net_lots"] > 0)
    boundary = used[is_boundary]
    rest = used[~is_boundary]
    for h in horizons:
        _block(boundary, "富鼎型邊界", h)
        _block(rest, "其餘樣本", h)
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_patterns.py::test_print_accumulation_calibration_runs_with_buckets_and_boundary_case -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add screener/patterns.py tests/test_patterns.py
git commit -m "feat(patterns): print_accumulation_calibration() 分數分桶+富鼎邊界案例報告"
```

---

### Task 4: `main.py` CLI 整合（修好 `--backtest` + 新增 `--backtest-accumulation`）

**Files:**
- Modify: `main.py:821-822`（`--backtest` 之後加新旗標）、`main.py:859-861`（修 `--backtest` dispatch、加新 dispatch）

**Interfaces:**
- Consumes: Task 2 的 `scan_accumulation_score`、Task 3 的 `print_accumulation_calibration`；既有 `screener.signals.scan_volume_turnover`（已在 `main.py:25` import）、既有 `screener.backtest.run_backtest`（已在 `main.py:26` import）。
- Produces: `python main.py --backtest`（修好，不再 TypeError）、`python main.py --backtest-accumulation`（新指令）。

這個 Task 是純 CLI 佈線，沒有對應的自動化測試（跟現有 `--backtest-patterns`/`--backtest-patterns-rr` 等旗標一致，`tests/test_main.py` 本來就不覆蓋這層 argparse dispatch）。用語法檢查代替「執行確認通過」。

- [ ] **Step 1: 修改 `--backtest` dispatch，並新增 `--backtest-accumulation` 旗標與 dispatch**

在 `main.py:821-822` 之後（`--backtest` 的 `add_argument` 之後）插入新旗標：

```python
    parser.add_argument("--backtest", action="store_true",
                        help="跑巨量換手回測，輸出勝率與期望值統計")
    parser.add_argument("--backtest-accumulation", action="store_true",
                        help="跑進貨分回測校準，輸出分數分桶超額報酬 + weakening 邊界案例比較")
```

在 `main.py:859-861`，把：

```python
    elif args.backtest:
        df = run_backtest()
        print_backtest_summary(df)
```

改成：

```python
    elif args.backtest:
        df = run_backtest(lambda d, p: scan_volume_turnover(d, db_path=p))
        print_backtest_summary(df)
    elif args.backtest_accumulation:
        from screener.patterns import scan_accumulation_score, print_accumulation_calibration
        scanner, cache = scan_accumulation_score()
        df = run_backtest(scanner)
        print_accumulation_calibration(df, cache)
```

- [ ] **Step 2: 語法檢查**

Run: `python -m py_compile main.py`
Expected: 無輸出、exit code 0（純語法檢查，不執行任何邏輯、不碰資料庫）

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "fix(main): 修好壞掉的 --backtest + 新增 --backtest-accumulation 進貨分回測入口"
```

---

## 實跑驗收（plan 做完後、非 Task，Cody 自行執行）

```bash
python main.py --backtest-accumulation
```

看進貨分分數分桶的超額報酬有沒有隨分數遞增、富鼎型邊界案例的超額報酬是否明顯優於/劣於其餘樣本——用這兩組真實數字決定要不要調整 `calc_accumulation_score()` 的切點或 weakening 定義。
