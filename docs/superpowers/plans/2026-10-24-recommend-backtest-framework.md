# 個股推薦：階段 2 回測框架 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **本專案規矩**（CLAUDE.md）：Developer 不自己跑測試、不跑資料；每個 Task 的「Run」步驟由 Debugger 在交接時執行。Developer 寫完一個 Task 就 commit（只加該 Task 的檔），整批完成後 append `debug-tasks.md` 交接。

**Goal:** 把 session scratchpad 的回測原型改寫成 repo 內有測試的 `recommend/` 套件，能一鍵重跑「突破策略」的完整回測報告與案例庫指標。

**Architecture:** `recommend/data.py` 從 DuckDB 載入「股票×日期」面板；`features.py` 依規格第 3 節算特徵（純函式，DataFrame 進出）；`strategies/` 每條策略一個檔、共用 `Strategy` 介面；`exits.py` 模擬出場；`backtest.py` 組裝訊號→交易→報告（第 11、12 節）與案例庫指標（第 6 節）。`main.py --backtest-recommend` 印出報告。

**Tech Stack:** Python 3.11、pandas、numpy、DuckDB、pytest。

**規格：** `docs/superpowers/specs/2026-10-22-stock-recommendation-design.md`（以下「§」指該文件章節）。

---

## File Structure

| 檔案 | 職責 |
|---|---|
| `recommend/__init__.py` | 空檔（套件） |
| `recommend/ticks.py` | 跳動單位、精確漲停價（§3 漲停價） |
| `recommend/data.py` | 從 DuckDB 載入面板（行情＋籌碼＋集保＋股票池） |
| `recommend/features.py` | §3 特徵：漲停、一字、量比、創 N 日高、區間、前 20 日漲幅、流動性、籌碼視窗與百分位 |
| `recommend/strategies/__init__.py` | `ALL_STRATEGIES` 清單 |
| `recommend/strategies/base.py` | `Strategy` 介面、`Signal` 欄位約定 |
| `recommend/strategies/breakout.py` | §7.5 突破策略（整理型／續攻型） |
| `recommend/exits.py` | §11 出場：停損 6%、回落 20%、60 日；成本 |
| `recommend/backtest.py` | 訊號→交易、報告指標、基準、案例命中、案例庫指標 |
| `main.py` | 新增 `--backtest-recommend` |
| `tests/test_recommend_ticks.py` … `tests/test_recommend_backtest.py` | 各模組測試 |

共用常數（全部放 `recommend/features.py` 或各自模組頂端，數字來源寫在註解）：
- 成本 `FEE = 0.001425 * 0.28`、`TAX = 0.003`（§11）。
- 流動性 `MIN_VMA20 = 300`（張，§3 排除）。

**不在這份計畫內**（之後的計畫處理）：
- 「隨便哪天買」基準與及格標準自動評分（§11 基準、§12）：本計畫先輸出原始數字，及格門檻 Cody 尚未定案。
- 處置股、全額交割股排除：DB 目前沒有這兩種名單；股票池本來就不含 ETF。
- 大盤反轉日排除：`run_trades(exclude_dates=...)` 已留參數，反轉日定義待 0-7 長期資料驗證。
- 推薦頁、Telegram、成績單（階段 4～5）。

---

### Task 1: 跳動單位與精確漲停價

**Files:**
- Create: `recommend/__init__.py`（空）
- Create: `recommend/ticks.py`
- Test: `tests/test_recommend_ticks.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recommend_ticks.py
import pytest

from recommend.ticks import limit_up_price, tick_size


@pytest.mark.parametrize("price,tick", [
    (9.99, 0.01), (10, 0.05), (49.95, 0.05), (50, 0.1), (99.9, 0.1),
    (100, 0.5), (499.5, 0.5), (500, 1), (999, 1), (1000, 5), (2400, 5),
])
def test_tick_size_boundaries(price, tick):
    assert tick_size(price) == tick


@pytest.mark.parametrize("ref,limit", [
    (306.5, 337.0),    # 306.5×1.1=337.15 → 100～500 跳 0.5 → 337.0（6672 2026-09-24 類型）
    (541.0, 595.0),    # 595.1 → 500～1000 跳 1 → 595
    (9.5, 10.45),      # 10.45 → 10～50 跳 0.05 → 10.45
    (45.6, 50.1),      # 50.16 → 50～100 跳 0.1 → 50.1
    (2200.0, 2420.0),  # ≥1000 跳 5
])
def test_limit_up_price_rounds_down_to_tick_of_result(ref, limit):
    assert limit_up_price(ref) == pytest.approx(limit)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recommend_ticks.py -v`
Expected: FAIL（`ModuleNotFoundError: recommend`）

- [ ] **Step 3: Write minimal implementation**

```python
# recommend/ticks.py
"""台股普通股跳動單位與漲停價（規格 §3）。ETF 規則不同，不適用。"""
import math

_TICKS = [(10, 0.01), (50, 0.05), (100, 0.1), (500, 0.5), (1000, 1.0)]


def tick_size(price: float) -> float:
    for upper, tick in _TICKS:
        if price < upper:
            return tick
    return 5.0


def limit_up_price(ref: float) -> float:
    """參考價 × 1.10，無條件捨去到「該價位」的跳動單位。"""
    raw = ref * 1.10
    tick = tick_size(raw)
    return round(math.floor(raw / tick + 1e-9) * tick, 2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recommend_ticks.py -v`
Expected: PASS（16 passed）

- [ ] **Step 5: Commit**

```bash
git add recommend/__init__.py recommend/ticks.py tests/test_recommend_ticks.py
git commit -m "feat(recommend): 跳動單位與精確漲停價"
```

---

### Task 2: 面板資料載入

**Files:**
- Create: `recommend/data.py`
- Test: `tests/test_recommend_data.py`

面板欄位：`stock_id, date, open, high, low, close, volume, change, foreign_net, trust_net, foreign_pct, total_shares, big_pct, big_date, meta_sector, stock_name`（`big_date`＝對到的那份集保資料日，Task 4 用它判斷「同一週」），依 `stock_id, date` 排序。
集保 `lv12_15_pct`（400 張以上持股 %）以 `merge_asof(direction="backward", allow_exact_matches=True)` 對到交易日（§3：用「含資料日當天」版本）；`total_shares` 同樣 asof，2025-12 之前沒有集保資料時以該股最早一筆往回補（§3 法人買超占股本）。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recommend_data.py
import duckdb
import pandas as pd

from recommend.data import load_panel


def _db(tmp_path):
    path = str(tmp_path / "t.db")
    con = duckdb.connect(path)
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE,"
                " close DOUBLE, volume BIGINT, change DOUBLE, change_pct DOUBLE)")
    con.execute("CREATE TABLE institutional (stock_id VARCHAR, date DATE, foreign_net BIGINT, trust_net BIGINT,"
                " dealer_net BIGINT, total_net BIGINT)")
    con.execute("CREATE TABLE foreign_holdings (stock_id VARCHAR, date DATE, foreign_pct DOUBLE)")
    con.execute("CREATE TABLE shareholder (stock_id VARCHAR, date DATE, lv12_15_pct DOUBLE, total_shares BIGINT)")
    for d, c in (("2026-01-05", 100), ("2026-01-06", 110), ("2026-01-07", 111)):
        con.execute("INSERT INTO daily_prices VALUES ('2330', ?, ?, ?, ?, ?, 1000, 1, 1)", [d, c, c, c, c])
    con.execute("INSERT INTO institutional VALUES ('2330', '2026-01-06', 5000, 100, 0, 5100)")
    con.execute("INSERT INTO foreign_holdings VALUES ('2330', '2026-01-06', 70.5)")
    con.execute("INSERT INTO shareholder VALUES ('2330', '2026-01-06', 80.0, 1000000)")
    con.close()
    uni = tmp_path / "u.csv"
    pd.DataFrame([{"stock_id": "2330", "stock_name": "台積電", "exchange": "TWSE", "meta_sector": "半導體",
                   "sub_sector": "", "note": ""}]).to_csv(uni, index=False, encoding="utf-8-sig")
    return path, str(uni)


def test_load_panel_merges_tables_and_asof_holders(tmp_path):
    db, uni = _db(tmp_path)
    p = load_panel(db_path=db, universe_path=uni)
    assert list(p["date"].dt.strftime("%m-%d")) == ["01-05", "01-06", "01-07"]
    r6 = p[p["date"] == "2026-01-06"].iloc[0]
    assert r6["foreign_net"] == 5000 and r6["foreign_pct"] == 70.5
    assert r6["big_pct"] == 80.0                       # 資料日當天可用
    r7 = p[p["date"] == "2026-01-07"].iloc[0]
    assert r7["big_pct"] == 80.0 and pd.isna(r7["foreign_net"])  # 集保 asof 往後帶；當天沒籌碼為 NaN
    assert r7["big_date"] == pd.Timestamp("2026-01-06")
    assert p["total_shares"].iloc[0] == 1_000_000      # 集保之前的日子用最早一筆往回補
    assert p["meta_sector"].iloc[0] == "半導體"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recommend_data.py -v`
Expected: FAIL（`ModuleNotFoundError: recommend.data`）

- [ ] **Step 3: Write minimal implementation**

```python
# recommend/data.py
"""從 DuckDB 載入「股票×日期」面板（唯讀）。"""
import duckdb
import pandas as pd

DB_PATH = "data/screener.db"
UNIVERSE_PATH = "data/stock_universe.csv"


def load_panel(db_path: str = DB_PATH, universe_path: str = UNIVERSE_PATH, start: str | None = None) -> pd.DataFrame:
    where = "WHERE date >= ?" if start else ""
    args = [start] if start else []
    con = duckdb.connect(db_path, read_only=True)
    try:
        px = con.execute(f"SELECT stock_id, date, open, high, low, close, volume, change FROM daily_prices {where}", args).df()
        inst = con.execute(f"SELECT stock_id, date, foreign_net, trust_net FROM institutional {where}", args).df()
        fh = con.execute(f"SELECT stock_id, date, foreign_pct FROM foreign_holdings {where}", args).df()
        sh = con.execute("SELECT stock_id, date, lv12_15_pct AS big_pct, total_shares FROM shareholder "
                         "WHERE total_shares > 0").df()
    finally:
        con.close()
    for t in (px, inst, fh, sh):
        t["date"] = pd.to_datetime(t["date"])
    sh["big_date"] = sh["date"]
    df = px.merge(inst, on=["stock_id", "date"], how="left").merge(fh, on=["stock_id", "date"], how="left")
    df = pd.merge_asof(df.sort_values("date"), sh.sort_values("date"), on="date", by="stock_id",
                       direction="backward", allow_exact_matches=True)
    first = sh.sort_values("date").groupby("stock_id")["total_shares"].first()
    df["total_shares"] = df["total_shares"].fillna(df["stock_id"].map(first))
    uni = pd.read_csv(universe_path, dtype=str, encoding="utf-8-sig")[["stock_id", "stock_name", "meta_sector"]]
    df = df.merge(uni, on="stock_id", how="inner")
    return df.sort_values(["stock_id", "date"]).reset_index(drop=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recommend_data.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add recommend/data.py tests/test_recommend_data.py
git commit -m "feat(recommend): 從 DuckDB 載入回測面板"
```

---

### Task 3: 價量特徵

**Files:**
- Create: `recommend/features.py`
- Test: `tests/test_recommend_features.py`

定義（§3）：
- 參考價 `ref = close − change`（官方漲跌以參考價為基準，除權息日也成立）；`limit_up = close ≥ limit_up_price(ref) − 1e-6`。新上市前 5 個交易日不判定（該股第 1～5 筆）。
- `one_word = limit_up & open == high == low == close`。
- 量比 `vr = volume ÷ 前 20 個「有成交（volume>0）」交易日平均`，不含當日；不足 20 天為 NaN。
- `hi90 = 前 90 日收盤最高（不含當日）`；`rng20 = 前 20 日收盤 最高÷最低 − 1`；`ret20_prev = 前一日收盤 ÷ 21 日前收盤 − 1`。
- `liq = 前 20 日平均量 ≥ 300 張`。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recommend_features.py
import numpy as np
import pandas as pd

from recommend.features import add_price_features


def _panel(closes, volumes=None, opens=None, changes=None, sid="2330"):
    n = len(closes)
    volumes = volumes or [1000] * n
    opens = opens or closes
    if changes is None:
        changes = [0.0] + [round(closes[i] - closes[i - 1], 2) for i in range(1, n)]
    return pd.DataFrame({
        "stock_id": sid, "date": pd.bdate_range("2026-01-01", periods=n),
        "open": opens, "high": [max(o, c) for o, c in zip(opens, closes)],
        "low": [min(o, c) for o, c in zip(opens, closes)], "close": closes,
        "volume": volumes, "change": changes,
    })


def test_limit_up_uses_reference_price_and_tick():
    closes = [100.0] * 25 + [110.0]
    f = add_price_features(_panel(closes))
    assert f["limit_up"].iloc[-1]
    assert not f["limit_up"].iloc[-2]


def test_limit_up_not_judged_in_first_five_rows():
    f = add_price_features(_panel([100.0, 110.0, 121.0, 133.0, 146.0, 160.5, 176.5]))
    assert not f["limit_up"].iloc[:5].any()
    assert f["limit_up"].iloc[5]


def test_one_word_requires_flat_ohlc():
    closes = [100.0] * 25 + [110.0]
    p = _panel(closes)
    f = add_price_features(p)
    assert f["one_word"].iloc[-1]                         # 開高低收都 110
    p.loc[p.index[-1], "low"] = 105.0
    assert not add_price_features(p)["one_word"].iloc[-1]


def test_volume_ratio_excludes_zero_volume_days_and_today():
    vols = [1000] * 10 + [0] * 5 + [1000] * 10 + [3000]
    f = add_price_features(_panel([100.0] * 26, volumes=vols))
    assert f["vr"].iloc[-1] == 3.0


def test_high_range_and_prior_return_exclude_today():
    closes = list(np.linspace(100, 120, 95)) + [130.0]
    f = add_price_features(_panel(closes))
    last = f.iloc[-1]
    assert last["hi90"] == closes[-2]
    assert last["rng20"] == closes[-2] / closes[-21] - 1
    assert last["ret20_prev"] == closes[-2] / closes[-22] - 1


def test_liquidity_threshold_300_lots():
    f = add_price_features(_panel([100.0] * 21, volumes=[299] * 20 + [5000]))
    assert not f["liq"].iloc[-1]
    f = add_price_features(_panel([100.0] * 21, volumes=[300] * 20 + [5000]))
    assert f["liq"].iloc[-1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recommend_features.py -v`
Expected: FAIL（`ModuleNotFoundError: recommend.features`）

- [ ] **Step 3: Write minimal implementation**

```python
# recommend/features.py
"""規格 §3 的特徵定義。回測、頁面、推薦共用；輸入面板（recommend.data.load_panel）回傳新 DataFrame。"""
import numpy as np
import pandas as pd

from recommend.ticks import limit_up_price

MIN_VMA20 = 300        # 張；§3 排除低流動性
NEW_LISTING_DAYS = 5   # 新上市前 5 個交易日無漲跌幅限制，不判定漲停


def add_price_features(panel: pd.DataFrame) -> pd.DataFrame:
    df = panel.sort_values(["stock_id", "date"]).reset_index(drop=True).copy()
    g = df.groupby("stock_id", sort=False)
    ref = df["close"] - df["change"].fillna(0)
    limit = ref.map(lambda r: limit_up_price(r) if r > 0 else np.inf)
    seq = g.cumcount()
    df["limit_up"] = (df["close"] >= limit - 1e-6) & (seq >= NEW_LISTING_DAYS)
    flat = (df["open"] == df["high"]) & (df["high"] == df["low"]) & (df["low"] == df["close"])
    df["one_word"] = df["limit_up"] & flat

    # 量比分母：前 20 個「有成交」日的平均（停牌日不算），不含當日。
    # 先在有成交的列上算 20 日均（含該列），再對每一列取「前一列為止最後一個有成交日」的值。
    traded = df["volume"].where(df["volume"] > 0)
    r20 = traded.groupby(df["stock_id"]).transform(lambda s: s.dropna().rolling(20).mean().reindex(s.index))
    base = r20.groupby(df["stock_id"]).transform(lambda s: s.ffill().shift(1))
    df["vr"] = df["volume"] / base
    prev_close = g["close"].shift(1)
    df["hi90"] = g["close"].transform(lambda s: s.shift(1).rolling(90).max())
    hi20 = g["close"].transform(lambda s: s.shift(1).rolling(20).max())
    lo20 = g["close"].transform(lambda s: s.shift(1).rolling(20).min())
    df["rng20"] = hi20 / lo20 - 1
    df["ret20_prev"] = prev_close / g["close"].shift(21) - 1
    df["liq"] = g["volume"].transform(lambda s: s.shift(1).rolling(20).mean()) >= MIN_VMA20
    return df
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recommend_features.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add recommend/features.py tests/test_recommend_features.py
git commit -m "feat(recommend): 價量特徵（漲停、一字、量比、新高、區間、流動性）"
```

---

### Task 4: 籌碼特徵與百分位

**Files:**
- Modify: `recommend/features.py`（新增 `add_chip_features`）
- Test: `tests/test_recommend_features.py`（追加）

定義（§3）：
- `inst5 = 近 5 日（外資＋投信）淨買超股數合計 ÷ 總發行股數 × 100`，`inst5_pr` = 當日股票池百分位。
- `fpct5 = 外資持股% 今日 − 5 個交易日前`，`fpct5_pr` 同上。
- `trust_days10 = 近 10 日投信淨買超 > 0 的天數`。
- `big1w = 集保 400 張以上 % 本週 − 上週`：以面板的 `big_date`（集保資料日）分週，每週取一個值做差，再對回每個交易日；`big1w_pr` 同上。
- 百分位：當天、有該欄位值的股票中 `rank(pct=True)`（§3 百分位）。

- [ ] **Step 1: Write the failing test**

```python
# 追加到 tests/test_recommend_features.py
from recommend.features import add_chip_features


def _chip_panel():
    dates = pd.bdate_range("2026-01-01", periods=12)
    rows = []
    for sid, f_net, t_net, fpct0 in (("A", 1000, 100, 10.0), ("B", 0, -50, 20.0)):
        for k, d in enumerate(dates):
            rows.append({"stock_id": sid, "date": d, "foreign_net": f_net, "trust_net": t_net if k % 2 == 0 else 0,
                         "foreign_pct": fpct0 + k * (0.5 if sid == "A" else 0.0), "total_shares": 1_000_000,
                         "big_pct": 50.0 if k < 6 else (51.0 if sid == "A" else 49.0),
                         "big_date": dates[0] if k < 6 else dates[6]})
    return pd.DataFrame(rows)


def test_chip_windows_and_percentiles():
    f = add_chip_features(_chip_panel())
    a = f[f["stock_id"] == "A"].iloc[-1]
    b = f[f["stock_id"] == "B"].iloc[-1]
    assert a["inst5"] == (1000 * 5 + 100 * 2) / 1_000_000 * 100   # 最後 5 天投信有 2 天買（k=8,10）
    assert a["fpct5"] == 2.5
    assert a["trust_days10"] == 5
    assert a["inst5_pr"] == 1.0 and b["inst5_pr"] == 0.5
    assert a["big1w"] == 1.0 and b["big1w"] == -1.0
    assert a["big1w_pr"] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recommend_features.py::test_chip_windows_and_percentiles -v`
Expected: FAIL（`ImportError: cannot import name 'add_chip_features'`）

- [ ] **Step 3: Write minimal implementation**

```python
# 追加到 recommend/features.py

def add_chip_features(panel: pd.DataFrame) -> pd.DataFrame:
    df = panel.sort_values(["stock_id", "date"]).reset_index(drop=True).copy()
    g = df.groupby("stock_id", sort=False)
    both = df["foreign_net"].fillna(0) + df["trust_net"].fillna(0)
    df["inst5"] = both.groupby(df["stock_id"]).transform(lambda s: s.rolling(5).sum()) / df["total_shares"] * 100
    df["fpct5"] = g["foreign_pct"].transform(lambda s: s - s.shift(5))
    df["trust_days10"] = g["trust_net"].transform(lambda s: (s > 0).astype(float).rolling(10).sum())
    # 集保週變化：以集保資料日分週，每週一個值，跟前一週相減後對回每個交易日（第一週為 NaN）
    weekly = (df.dropna(subset=["big_date"]).groupby(["stock_id", "big_date"])["big_pct"].first()
              .groupby(level="stock_id").diff().rename("big1w").reset_index())
    df = df.merge(weekly, on=["stock_id", "big_date"], how="left")
    for col in ("inst5", "fpct5", "big1w"):
        df[f"{col}_pr"] = df.groupby("date")[col].rank(pct=True)
    return df
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recommend_features.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: Commit**

```bash
git add recommend/features.py tests/test_recommend_features.py
git commit -m "feat(recommend): 籌碼特徵（法人占股本、外資持股增幅、投信天數、大戶週增）與百分位"
```

---

### Task 5: 策略介面與突破策略

**Files:**
- Create: `recommend/strategies/__init__.py`
- Create: `recommend/strategies/base.py`
- Create: `recommend/strategies/breakout.py`
- Test: `tests/test_recommend_breakout.py`

訊號 DataFrame 欄位約定：`stock_id, date, strategy, type, routes`（`routes` 為「法人,外資,投信,大戶」中命中者以「,」連接）、`n_routes`。

突破策略（§7.5）：`limit_up & close > hi90 & liq & n_routes ≥ 1`；型態 `整理`＝`rng20 < 0.30`，`續攻`＝`0.30 ≤ rng20 < 0.70 且 ret20_prev ≥ 0.20`，其他不出訊號。路線：法人 `inst5_pr ≥ 0.9`、外資 `fpct5_pr ≥ 0.9`、投信 `trust_days10 ≥ 6`、大戶 `big1w_pr ≥ 0.9`。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recommend_breakout.py
import pandas as pd

from recommend.strategies import ALL_STRATEGIES
from recommend.strategies.breakout import BreakoutStrategy


def _feat(**over):
    base = {"stock_id": "6672", "date": pd.Timestamp("2026-09-24"), "close": 337.5, "hi90": 310.0,
            "limit_up": True, "liq": True, "rng20": 0.179, "ret20_prev": 0.05,
            "inst5_pr": 1.0, "fpct5_pr": 1.0, "trust_days10": 4, "big1w_pr": 0.94}
    base.update(over)
    return pd.DataFrame([base])


def test_6672_0924_is_consolidation_with_three_routes():
    sig = BreakoutStrategy().scan(_feat())
    r = sig.iloc[0]
    assert (r["strategy"], r["type"], r["routes"], r["n_routes"]) == ("突破策略", "整理", "法人,外資,大戶", 3)


def test_continuation_type_and_rejections():
    s = BreakoutStrategy()
    assert s.scan(_feat(rng20=0.45, ret20_prev=0.25)).iloc[0]["type"] == "續攻"
    assert s.scan(_feat(rng20=0.45, ret20_prev=0.10)).empty        # 大起大落沒漲
    assert s.scan(_feat(rng20=0.75, ret20_prev=0.40)).empty        # 區間 ≥ 70%
    assert s.scan(_feat(close=300.0)).empty                        # 沒創 90 日高
    assert s.scan(_feat(limit_up=False)).empty
    assert s.scan(_feat(liq=False)).empty
    assert s.scan(_feat(inst5_pr=0.5, fpct5_pr=0.5, trust_days10=2, big1w_pr=0.5)).empty  # 沒有籌碼路線


def test_registry_contains_breakout():
    assert [s.name for s in ALL_STRATEGIES] == ["突破策略"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recommend_breakout.py -v`
Expected: FAIL（`ModuleNotFoundError: recommend.strategies`）

- [ ] **Step 3: Write minimal implementation**

```python
# recommend/strategies/base.py
"""策略介面（規格 §7.0）：每條策略各自的進場條件與型態；出場規則見 recommend.exits。"""
from typing import Protocol

import pandas as pd

SIGNAL_COLUMNS = ["stock_id", "date", "strategy", "type", "routes", "n_routes"]


class Strategy(Protocol):
    name: str

    def scan(self, features: pd.DataFrame) -> pd.DataFrame:
        """輸入特徵面板，回傳符合的訊號（欄位見 SIGNAL_COLUMNS）。"""
        ...
```

```python
# recommend/strategies/breakout.py
"""突破策略（規格 §7.5）：漲停＋創 90 日高＋籌碼任一路線，分整理型／續攻型。"""
import numpy as np
import pandas as pd

from recommend.strategies.base import SIGNAL_COLUMNS

NEW_HIGH_DAYS = 90       # §3：60～150 日 PF 差距屬雜訊，定 90（13.9）
BOX_MAX = 0.30           # 整理型：前 20 日區間 < 30%
CONT_MAX = 0.70          # 續攻型：區間 30%～70%
CONT_MIN_RUN = 0.20      # 續攻型：前 20 日漲 ≥ 20%
PR_TOP = 0.90
TRUST_DAYS = 6
ROUTES = {
    "法人": lambda f: f["inst5_pr"] >= PR_TOP,
    "外資": lambda f: f["fpct5_pr"] >= PR_TOP,
    "投信": lambda f: f["trust_days10"] >= TRUST_DAYS,
    "大戶": lambda f: f["big1w_pr"] >= PR_TOP,
}


class BreakoutStrategy:
    name = "突破策略"

    def scan(self, features: pd.DataFrame) -> pd.DataFrame:
        f = features
        hits = {k: rule(f).fillna(False).astype(bool) for k, rule in ROUTES.items()}
        n_routes = sum(h.astype(int) for h in hits.values())
        box = f["rng20"] < BOX_MAX
        cont = (f["rng20"] >= BOX_MAX) & (f["rng20"] < CONT_MAX) & (f["ret20_prev"] >= CONT_MIN_RUN)
        ok = f["limit_up"] & (f["close"] > f["hi90"]) & f["liq"] & (n_routes >= 1) & (box | cont)
        out = f.loc[ok, ["stock_id", "date"]].copy()
        out["strategy"] = self.name
        out["type"] = np.where(box[ok], "整理", "續攻")
        out["routes"] = [",".join(k for k in ROUTES if hits[k].loc[i]) for i in out.index]
        out["n_routes"] = n_routes[ok].astype(int)
        return out[SIGNAL_COLUMNS].reset_index(drop=True)
```

```python
# recommend/strategies/__init__.py
"""已上線的策略清單；新增策略＝新增一個檔案並加進這裡（規格 §7.0）。"""
from recommend.strategies.breakout import BreakoutStrategy

ALL_STRATEGIES = [BreakoutStrategy()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recommend_breakout.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add recommend/strategies tests/test_recommend_breakout.py
git commit -m "feat(recommend): 策略介面與突破策略（整理型／續攻型）"
```

---

### Task 6: 出場模擬

**Files:**
- Create: `recommend/exits.py`
- Test: `tests/test_recommend_exits.py`

規則（§11）：訊號日隔天開盤進場；隔天一字漲停 → 買不到（回傳 None）；之後每天看收盤：收盤 ≤ 進場 × 0.94 停損；收盤 ≤ 持有期最高收盤 × 0.80 回落出場；第 60 個交易日收盤到期。報酬扣成本：`exit × (1 − FEE − TAX) ÷ (entry × (1 + FEE)) − 1`；R ＝ 報酬 ÷ 0.06；`mfe` ＝ 持有期最高收盤 ÷ 進場 − 1。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recommend_exits.py
import pandas as pd
import pytest

from recommend.exits import FEE, TAX, simulate_trade


def _path(opens, closes, one_word=None):
    n = len(closes)
    return pd.DataFrame({"date": pd.bdate_range("2026-01-01", periods=n), "open": opens, "close": closes,
                         "one_word": one_word or [False] * n})


def _net(entry, exit_):
    return exit_ * (1 - FEE - TAX) / (entry * (1 + FEE)) - 1


def test_stop_loss_on_close_six_percent():
    t = simulate_trade(_path([0, 100, 100, 100], [100, 98, 93.9, 120]), signal_pos=0)
    assert (t["exit_reason"], t["exit_price"]) == ("停損", 93.9)
    assert t["ret"] == pytest.approx(_net(100, 93.9))
    assert t["r_multiple"] == pytest.approx(t["ret"] / 0.06)


def test_trailing_twenty_percent_from_peak_close():
    t = simulate_trade(_path([0, 100] + [0] * 3, [100, 110, 150, 125, 119.9]), signal_pos=0)
    assert t["exit_reason"] == "回落" and t["exit_price"] == 119.9
    assert t["mfe"] == pytest.approx(0.5)


def test_max_hold_sixty_days_and_unfillable_one_word():
    closes = [100] + [101] * 70
    t = simulate_trade(_path([0] + [100] * 70, closes), signal_pos=0)
    assert t["exit_reason"] == "到期" and t["hold_days"] == 60
    assert simulate_trade(_path([0, 110], [100, 110], one_word=[False, True]), signal_pos=0) is None


def test_open_position_when_path_ends():
    t = simulate_trade(_path([0, 100, 0], [100, 105, 108]), signal_pos=0)
    assert t["exit_reason"] == "持有中" and t["exit_price"] == 108
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recommend_exits.py -v`
Expected: FAIL（`ModuleNotFoundError: recommend.exits`）

- [ ] **Step 3: Write minimal implementation**

```python
# recommend/exits.py
"""出場規則（規格 §11）：停損 6%、自最高收盤回落 20%、最長 60 個交易日；收盤判斷、隔天開盤進場。"""
import pandas as pd

FEE = 0.001425 * 0.28   # 手續費 2.8 折，買賣各一次
TAX = 0.003             # 賣出證交稅
STOP = 0.06
TRAIL = 0.20
MAX_HOLD = 60


def simulate_trade(path: pd.DataFrame, signal_pos: int) -> dict | None:
    """path：單一股票依日期排序的 open/close/one_word；signal_pos：訊號日在 path 的位置。
    隔天一字漲停買不到 → None。"""
    e = signal_pos + 1
    if e >= len(path) or bool(path["one_word"].iloc[e]):
        return None
    entry = float(path["open"].iloc[e])
    if not entry > 0:
        return None
    peak, reason, k = entry, "持有中", e
    last = min(len(path), e + MAX_HOLD) - 1
    for k in range(e, last + 1):
        c = float(path["close"].iloc[k])
        peak = max(peak, c)
        if c <= entry * (1 - STOP):
            reason = "停損"
            break
        if c <= peak * (1 - TRAIL):
            reason = "回落"
            break
    else:
        if last - e + 1 == MAX_HOLD:
            reason = "到期"
    exit_price = float(path["close"].iloc[k])
    ret = exit_price * (1 - FEE - TAX) / (entry * (1 + FEE)) - 1
    return {
        "entry_date": path["date"].iloc[e], "entry_price": entry,
        "exit_date": path["date"].iloc[k], "exit_price": exit_price, "exit_reason": reason,
        "hold_days": k - e + 1, "ret": ret, "r_multiple": ret / STOP, "mfe": peak / entry - 1,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recommend_exits.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add recommend/exits.py tests/test_recommend_exits.py
git commit -m "feat(recommend): 出場模擬（停損 6%、回落 20%、60 日）"
```

---

### Task 7: 回測組裝與報告指標

**Files:**
- Create: `recommend/backtest.py`
- Test: `tests/test_recommend_backtest.py`

- `run_trades(features, signals, exclude_dates=())`：每個訊號跑 `simulate_trade`，回傳交易表（訊號欄位＋出場欄位）；`exclude_dates` 是要排除的訊號日（假交易日、大盤反轉日）。
- `report(trades, split_date)`：§11 報告欄位——`n, days, mean_ret, win_rate, payoff, pf, mean_r, top5_share, max_day_share, mean_ex_top3_days, in_sample/out_sample（mean_r, pf）, worst10_mean, max_consec_losses`；`by_month`、`by_type`（DataFrame）。持有中的交易不計入報告。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recommend_backtest.py
import pandas as pd
import pytest

from recommend.backtest import report, run_trades


def _feat():
    d = pd.bdate_range("2026-01-01", periods=8)
    rows = []
    for sid, closes in (("A", [100, 110, 112, 120, 130, 140, 150, 160]), ("B", [50, 55, 54, 51, 50, 49, 48, 47])):
        for k, (dt, c) in enumerate(zip(d, closes)):
            rows.append({"stock_id": sid, "date": dt, "open": c, "close": c, "one_word": False})
    return pd.DataFrame(rows)


def test_run_trades_links_signals_to_exits_and_excludes_dates():
    f = _feat()
    sig = pd.DataFrame({"stock_id": ["A", "B"], "date": [f["date"][1], f["date"][1]],
                        "strategy": "突破策略", "type": ["整理", "續攻"], "routes": "法人", "n_routes": 1})
    t = run_trades(f, sig)
    assert list(t["stock_id"]) == ["A", "B"]
    assert t.loc[t["stock_id"] == "B", "exit_reason"].iloc[0] == "停損"
    assert run_trades(f, sig, exclude_dates=[f["date"][1]]).empty


def _trades(rets, days=None, types=None):
    n = len(rets)
    return pd.DataFrame({"date": days or list(pd.bdate_range("2026-01-01", periods=n)), "ret": rets,
                         "r_multiple": [r / 0.06 for r in rets], "exit_reason": "停損",
                         "type": types or ["整理"] * n})


def test_report_core_metrics():
    r = report(_trades([0.30, -0.06, -0.06, 0.12]), split_date="2026-01-03")
    assert r["n"] == 4
    assert r["win_rate"] == 0.5
    assert r["pf"] == pytest.approx(0.42 / 0.12)
    assert r["payoff"] == pytest.approx(0.21 / 0.06)
    assert r["max_consec_losses"] == 2
    assert r["in_sample"]["n"] == 2 and r["out_sample"]["n"] == 2
    assert r["top5_share"] == pytest.approx(0.30 / 0.42)


def test_report_skips_open_positions():
    t = _trades([0.1, 0.2])
    t.loc[1, "exit_reason"] = "持有中"
    assert report(t, split_date="2026-01-02")["n"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recommend_backtest.py -v`
Expected: FAIL（`ModuleNotFoundError: recommend.backtest`）

- [ ] **Step 3: Write minimal implementation**

```python
# recommend/backtest.py
"""回測框架（規格 §11 報告欄位、§12 及格所需數字）。"""
import numpy as np
import pandas as pd

from recommend.exits import FEE, TAX, simulate_trade


def run_trades(features: pd.DataFrame, signals: pd.DataFrame, exclude_dates=()) -> pd.DataFrame:
    excl = set(pd.to_datetime(list(exclude_dates)))
    sig = signals[~signals["date"].isin(excl)]
    paths = {sid: g.reset_index(drop=True) for sid, g in
             features[["stock_id", "date", "open", "close", "one_word"]].groupby("stock_id", sort=False)}
    rows = []
    for s in sig.itertuples(index=False):
        path = paths.get(s.stock_id)
        if path is None:
            continue
        pos = path.index[path["date"] == s.date]
        if len(pos) == 0:
            continue
        t = simulate_trade(path, int(pos[0]))
        if t is not None:
            rows.append({**s._asdict(), **t})
    return pd.DataFrame(rows)


def _core(t: pd.DataFrame) -> dict:
    s = t["ret"]
    w, l = s[s > 0], s[s <= 0]
    return {
        "n": len(s),
        "mean_ret": s.mean() if len(s) else np.nan,
        "mean_r": t["r_multiple"].mean() if len(s) else np.nan,
        "win_rate": (s > 0).mean() if len(s) else np.nan,
        "payoff": w.mean() / -l.mean() if len(w) and len(l) else np.nan,
        "pf": w.sum() / -l.sum() if len(l) and l.sum() else np.nan,
    }


def report(trades: pd.DataFrame, split_date: str) -> dict:
    t = trades[trades["exit_reason"] != "持有中"].sort_values("date").reset_index(drop=True)
    out = _core(t)
    s = t["ret"]
    gains = s[s > 0].sort_values(ascending=False)
    k = max(1, int(np.ceil(len(s) * 0.05)))
    out["top5_share"] = gains.head(k).sum() / gains.sum() if gains.sum() else np.nan
    per_day = t.groupby("date")["ret"].sum()
    out["days"] = len(per_day)
    out["max_day_share"] = per_day.abs().max() / per_day.abs().sum() if len(per_day) else np.nan
    top3 = per_day.sort_values(ascending=False).head(3).index
    out["mean_ex_top3_days"] = t.loc[~t["date"].isin(top3), "ret"].mean()
    out["worst10_mean"] = s.sort_values().head(max(1, int(np.ceil(len(s) * 0.10)))).mean()
    streak = best = 0
    for v in (s <= 0):
        streak = streak + 1 if v else 0
        best = max(best, streak)
    out["max_consec_losses"] = best
    split = pd.Timestamp(split_date)
    out["in_sample"] = _core(t[t["date"] < split])
    out["out_sample"] = _core(t[t["date"] >= split])
    out["by_month"] = pd.DataFrame([{"month": m, **_core(g)} for m, g in t.groupby(t["date"].dt.to_period("M"))])
    out["by_type"] = pd.DataFrame([{"type": k_, **_core(g)} for k_, g in t.groupby("type")])
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recommend_backtest.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add recommend/backtest.py tests/test_recommend_backtest.py
git commit -m "feat(recommend): 回測組裝與報告指標"
```

---

### Task 8: 案例庫指標與案例命中

**Files:**
- Modify: `recommend/backtest.py`（新增 `winner_episodes`、`catch_rate`、`blowup_rate`、`case_hits`）
- Test: `tests/test_recommend_backtest.py`（追加）

定義（§6 自動指標）：
- 飆股段：起漲日後 30 個交易日內最高收盤 ≥ 起漲收盤 × 2；同一檔 40 個交易日內只留漲幅最大的起漲日。
- 抓到：起漲日 −5～+15 個交易日內有訊號。
- 踩雷：訊號後第 20 個交易日收盤（隔天開盤進、扣成本）≤ −15%。
- 必考題：`CASES = [("6672", "2026-09-24"), ("6213", "2026-09-24")]`（§6 C2、C5）。

- [ ] **Step 1: Write the failing test**

```python
# 追加到 tests/test_recommend_backtest.py
from recommend.backtest import CASES, blowup_rate, case_hits, catch_rate, winner_episodes


def _price(sid, closes):
    d = pd.bdate_range("2026-01-01", periods=len(closes))
    return pd.DataFrame({"stock_id": sid, "date": d, "open": closes, "close": closes, "one_word": False})


def test_winner_episodes_and_catch_rate():
    closes = [10.0] * 10 + [10 + k for k in range(1, 15)] + [24.0] * 50   # 第 10 天起漲，之後到 24（+140%）
    f = pd.concat([_price("A", closes), _price("B", [10.0] * 74)])
    eps = winner_episodes(f, start="2026-01-01", end="2026-12-31")
    assert list(eps["stock_id"]) == ["A"]
    start = eps["start_date"].iloc[0]
    sig_hit = pd.DataFrame({"stock_id": ["A"], "date": [start + pd.offsets.BDay(3)]})
    sig_miss = pd.DataFrame({"stock_id": ["A"], "date": [start + pd.offsets.BDay(20)]})
    assert catch_rate(eps, sig_hit, f) == 1.0
    assert catch_rate(eps, sig_miss, f) == 0.0


def test_blowup_rate_twenty_day_minus_fifteen():
    f = pd.concat([_price("A", [100.0] * 2 + [80.0] * 25), _price("B", [100.0] * 27)])
    d1 = f["date"].iloc[0]
    sig = pd.DataFrame({"stock_id": ["A", "B"], "date": [d1, d1]})
    assert blowup_rate(sig, f) == 0.5


def test_case_hits():
    sig = pd.DataFrame({"stock_id": ["6672"], "date": [pd.Timestamp("2026-09-24")]})
    assert case_hits(sig) == {("6672", "2026-09-24"): True, ("6213", "2026-09-24"): False}
    assert CASES == [("6672", "2026-09-24"), ("6213", "2026-09-24")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recommend_backtest.py -v`
Expected: FAIL（`ImportError: cannot import name 'CASES'`）

- [ ] **Step 3: Write minimal implementation**

```python
# 追加到 recommend/backtest.py（FEE、TAX 已在 Task 7 的 import）

CASES = [("6672", "2026-09-24"), ("6213", "2026-09-24")]   # §6 C2、C5 必考題
WIN_GAIN, WIN_HORIZON, WIN_DEDUP = 1.0, 30, 40
CATCH_BEFORE, CATCH_AFTER = 5, 15
BLOWUP_DAYS, BLOWUP_RET = 20, -0.15


def winner_episodes(features: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    rows = []
    for sid, g in features.groupby("stock_id", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        fwd = g["close"][::-1].rolling(WIN_HORIZON, min_periods=1).max()[::-1].shift(-1) / g["close"] - 1
        cand = g.index[(fwd >= WIN_GAIN) & g["date"].between(pd.Timestamp(start), pd.Timestamp(end))]
        taken = []
        for i in sorted(cand, key=lambda i: -fwd[i]):
            if all(abs(i - t) >= WIN_DEDUP for t in taken):
                taken.append(i)
                rows.append({"stock_id": sid, "start_date": g.at[i, "date"], "gain": fwd[i]})
    return pd.DataFrame(rows, columns=["stock_id", "start_date", "gain"])


def catch_rate(episodes: pd.DataFrame, signals: pd.DataFrame, features: pd.DataFrame) -> float:
    if episodes.empty:
        return np.nan
    dates = {sid: g["date"].sort_values().reset_index(drop=True) for sid, g in features.groupby("stock_id")}
    sig = signals.groupby("stock_id")["date"].apply(set).to_dict()
    hits = 0
    for e in episodes.itertuples(index=False):
        d = dates[e.stock_id]
        i = int(d.searchsorted(e.start_date))
        window = set(d.iloc[max(0, i - CATCH_BEFORE): i + CATCH_AFTER + 1])
        hits += bool(window & sig.get(e.stock_id, set()))
    return hits / len(episodes)


def blowup_rate(signals: pd.DataFrame, features: pd.DataFrame) -> float:
    f = features.sort_values(["stock_id", "date"]).reset_index(drop=True)
    g = f.groupby("stock_id", sort=False)
    entry = g["open"].shift(-1)
    exit_ = g["close"].shift(-BLOWUP_DAYS)
    f["a20"] = exit_ * (1 - FEE - TAX) / (entry * (1 + FEE)) - 1
    m = signals.merge(f[["stock_id", "date", "a20"]], on=["stock_id", "date"], how="left").dropna(subset=["a20"])
    return (m["a20"] <= BLOWUP_RET).mean() if len(m) else np.nan


def case_hits(signals: pd.DataFrame) -> dict:
    keys = set(zip(signals["stock_id"], pd.to_datetime(signals["date"]).dt.strftime("%Y-%m-%d")))
    return {c: c in keys for c in CASES}
```

> 註：`blowup_rate` 測試裡 A 第 2 天起 80，訊號第 1 天收盤後隔天開盤 100、第 21 天收盤 80 → −20% 踩雷；B 不變。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recommend_backtest.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add recommend/backtest.py tests/test_recommend_backtest.py
git commit -m "feat(recommend): 案例庫指標（飆股抓到率、踩雷率、必考題命中）"
```

---

### Task 9: CLI `--backtest-recommend`

**Files:**
- Modify: `main.py`（argparse 與 dispatch；新增 `backtest_recommend_cli()`）
- Test: `tests/test_main.py`（追加，source 檢查同既有慣例）

輸出：每條策略的總表（§11 欄位）、樣本內外、分型態、按月、案例庫三指標與必考題命中。排除日：`config.is_trading_day` 為 False 的日子（防假交易日殘留）。樣本切分日 `2026-01-01`（§11：2025 找規則、2026 驗證）。

- [ ] **Step 1: Write the failing test**

```python
# 追加到 tests/test_main.py
def test_backtest_recommend_cli_wires_all_strategies():
    from main import backtest_recommend_cli
    src = inspect.getsource(backtest_recommend_cli)
    for name in ("load_panel", "add_price_features", "add_chip_features", "ALL_STRATEGIES",
                 "run_trades", "report", "winner_episodes", "catch_rate", "blowup_rate", "case_hits"):
        assert name in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py::test_backtest_recommend_cli_wires_all_strategies -v`
Expected: FAIL（`ImportError: cannot import name 'backtest_recommend_cli'`）

- [ ] **Step 3: Write minimal implementation**

在 `main.py` 的 `backfill_official_cli` 之後加：

```python
def backtest_recommend_cli(start: str = "2025-01-01", split: str = "2026-01-01") -> None:
    """個股推薦回測（規格 §11、§12、§6 案例庫指標），結果印到 log。"""
    from config import is_trading_day
    from recommend.backtest import blowup_rate, case_hits, catch_rate, report, run_trades, winner_episodes
    from recommend.data import load_panel
    from recommend.features import add_chip_features, add_price_features
    from recommend.strategies import ALL_STRATEGIES

    feats = add_chip_features(add_price_features(load_panel(start=start)))
    bad_days = [d for d in feats["date"].drop_duplicates() if not is_trading_day(d.date().isoformat())]
    end = feats["date"].max() - pd.offsets.BDay(30)
    eps = winner_episodes(feats, start=start, end=str(end.date()))
    for strat in ALL_STRATEGIES:
        sig = strat.scan(feats)
        r = report(run_trades(feats, sig, exclude_dates=bad_days), split_date=split)
        logger.info("=== %s：訊號 %d、已出場 %d、交易日 %d ===", strat.name, len(sig), r["n"], r["days"])
        logger.info("每筆 %.2fR｜勝率 %.0f%%｜賺賠比 %.2f｜PF %.2f｜前5%%占 %.0f%%｜單日最大占 %.0f%%｜最差10%% %.1f%%｜最多連虧 %d",
                    r["mean_r"], r["win_rate"] * 100, r["payoff"], r["pf"], r["top5_share"] * 100,
                    r["max_day_share"] * 100, r["worst10_mean"] * 100, r["max_consec_losses"])
        logger.info("樣本內 %s｜樣本外 %s", r["in_sample"], r["out_sample"])
        logger.info("分型態\n%s", r["by_type"].round(3).to_string(index=False))
        logger.info("按月\n%s", r["by_month"].round(3).to_string(index=False))
        logger.info("飆股抓到率 %.0f%%（%d 段）｜踩雷率 %.1f%%｜必考題 %s",
                    catch_rate(eps, sig, feats) * 100, len(eps), blowup_rate(sig, feats) * 100, case_hits(sig))
```

argparse（`--backfill-official` 那段之前）：

```python
    parser.add_argument("--backtest-recommend", action="store_true",
                        help="個股推薦策略回測：報告、樣本內外、分型態、按月、飆股抓到率、踩雷率、必考題（唯讀 DB）")
```

dispatch（`elif args.backfill_official:` 之前）：

```python
    elif args.backtest_recommend:
        backtest_recommend_cli()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat(recommend): --backtest-recommend 一鍵回測報告"
```

---

### Task 10: 交接與對照驗證

**Files:**
- Modify: `debug-tasks.md`（append）

- [ ] **Step 1: Append 交接**

```markdown
## [YYYY-MM-DD] 個股推薦階段 2：recommend/ 回測框架

### 改了什麼
- 新增 recommend/（ticks、data、features、strategies、exits、backtest）、main.py --backtest-recommend、對應 7 個測試檔
- 邏輯依規格 §3、§7.5、§11、§12、§6；scratchpad 原型改寫進 repo

### 請 Debugger 驗證
- [ ] tests/test_recommend_*.py 與全套
- [ ] 官方行情重建後跑 `python main.py --backtest-recommend`：
      6672、6213 2026-09-24 必考題皆命中；兩型合計 PF、每筆 R 與 §13.10／13.11 同方向（數字會因資料由還原價改官方價而變，列出差異）
- [ ] 精確漲停判斷 vs 舊近似（change_pct ≥ 9.5 且收＝高）：列出不一致的天數與例子
```

- [ ] **Step 2: Commit 並交給 Debugger**

```bash
git add debug-tasks.md
git commit -m "docs: 交接個股推薦階段 2 回測框架"
git -C ../tw-sector-tracker-debug merge --ff-only master
```

然後 SendMessage 給 `tw-sector-tracker-debug-*` session。
