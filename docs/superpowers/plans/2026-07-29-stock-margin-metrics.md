# 個股列表新增欄位：融資／融券佔比與維持率(估) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 `docs/index.html` 的個股列表新增四個可排序欄位——融資佔比、融資維持率(估)、融券餘額佔比、融券維持率(估)——分別呈現多方／空方槓桿部位的曝險規模與斷頭/軋空風險，維持率低於130%時有警示色與徽章。

**Architecture:** 新增兩支純函式：`screener/database.py::get_latest_total_shares()`（per-stock fallback 撈集保已發行股數）跟 `processors/performance.py::calc_avg20_close()`（近20日均收盤價，當融資/放空成本基準）。兩者的輸出餵進既有的 `export/index_generator.py::build_stock_detail_data()`，在那裡算出四個新欄位並掛進每支股票的資料字典；再把新欄位接進既有的個股列表 JS 渲染/排序邏輯（`renderStockListItem`/`_sortValue`/`sortStockList`）跟表頭。最後在 `main.py::run()` 呼叫兩支新函式並傳進 `generate_index_html()`。

**Tech Stack:** Python (pandas, duckdb), pytest, 純字串樣板產生的 HTML/CSS/JS（沒有前端框架）。

---

### Task 1: `get_latest_total_shares()` — 集保已發行股數 per-stock fallback 查詢

**Files:**
- Modify: `screener/database.py`
- Test: `tests/test_database.py`

比照既有 `get_chips_today()` 的 per-stock fallback 模式（`screener/database.py:266`附近）：每支股票各自取 `<= trade_date` 的最新一筆，不是整表取單一最新日期——`shareholder` 表是每週更新，同一批股票裡不同股票的「最新一筆」日期可能不同（例如某股某週資料抓取失敗、跳過一週）。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_database.py`，找到現有 import 那一行：

```python
from screener.database import get_chips_today, get_shareholder_top, import_csv_prices, init_db
```

改成：

```python
from screener.database import get_chips_today, get_shareholder_top, import_csv_prices, init_db, get_latest_total_shares
```

然後在檔案最後面加入：

```python
def test_get_latest_total_shares_per_stock_fallback(tmp_path, monkeypatch):
    """跟get_chips_today()一樣的per-stock fallback：每支股票各自取<=trade_date的
    最新一筆，不是整表取單一最新日期——某股集保資料比整表最新日期舊，仍要抓到
    自己的最新一筆，不是回空。"""
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    con = duckdb.connect(db_path)
    con.execute("CREATE TABLE shareholder (stock_id VARCHAR, date DATE, total_shares BIGINT)")
    con.execute("INSERT INTO shareholder VALUES ('2330', '2026-07-09', 100000000)")
    con.execute("INSERT INTO shareholder VALUES ('2330', '2026-07-16', 100000000)")
    con.execute("INSERT INTO shareholder VALUES ('2317', '2026-07-02', 50000000)")  # 更舊一週，沒跟上
    con.close()

    df = get_latest_total_shares("2026-07-16")

    row_2330 = df[df["stock_id"] == "2330"].iloc[0]
    assert row_2330["total_shares"] == 100000000
    assert str(row_2330["date"]) == "2026-07-16"

    row_2317 = df[df["stock_id"] == "2317"].iloc[0]
    assert row_2317["total_shares"] == 50000000
    assert str(row_2317["date"]) == "2026-07-02"


def test_get_latest_total_shares_returns_empty_dataframe_when_no_data(tmp_path, monkeypatch):
    import screener.database as db_mod
    db_path = str(tmp_path / "empty.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    con = duckdb.connect(db_path)
    con.execute("CREATE TABLE shareholder (stock_id VARCHAR, date DATE, total_shares BIGINT)")
    con.close()

    df = get_latest_total_shares("2026-07-16")
    assert df.empty
```

- [ ] **Step 2: 執行測試確認會失敗**

Run: `pytest tests/test_database.py -k get_latest_total_shares -v`
Expected: FAIL，`ImportError: cannot import name 'get_latest_total_shares' from 'screener.database'`

- [ ] **Step 3: 實作 `get_latest_total_shares()`**

在 `screener/database.py`，找到 `get_chips_today()` 函式結束的地方（`return df` 後面、`def get_shareholder_top(...)` 開始之前），插入：

```python
def get_latest_total_shares(trade_date: str) -> pd.DataFrame:
    """
    取每支股票最新一筆(<= trade_date)集保已發行股數(total_shares)，供融資/融券佔比計算。
    trade_date: 'YYYY-MM-DD'

    跟 get_chips_today() 一樣做 per-stock fallback：每支股票各自取 <= trade_date 的
    最新一筆，不是整張表取單一最新日期——shareholder 表是每週更新，同一批股票裡
    不同股票的「最新一筆」日期可能不同（例如某股某週資料抓取失敗、跳過一週）。
    """
    con = get_conn()
    df = con.execute("""
        SELECT stock_id, total_shares, date
        FROM shareholder
        WHERE date <= ?
        QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) = 1
    """, [trade_date]).df()
    con.close()
    return df
```

- [ ] **Step 4: 執行測試確認全部通過**

Run: `pytest tests/test_database.py -v`
Expected: 全部 PASS（既有測試 + 這次新增的2個）

- [ ] **Step 5: Commit**

```bash
git add screener/database.py tests/test_database.py
git commit -m "feat(database): 新增get_latest_total_shares()集保已發行股數per-stock查詢"
```

---

### Task 2: `calc_avg20_close()` — 20日均收盤價

**Files:**
- Modify: `processors/performance.py`
- Test: `tests/test_processors.py`

比照既有 `calc_stock_sparklines()`（`processors/performance.py:287`附近）的 pivot 模式，每支股票近20個交易日的平均收盤價，供融資/融券維持率(估)當成本基準。不足20天的股票用實際天數的平均值，不強求剛好20筆。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_processors.py` 檔案最後面加入：

```python
def test_calc_avg20_close_returns_average_of_available_days(tmp_path):
    import duckdb
    from processors.performance import calc_avg20_close

    db_path = str(tmp_path / "avg20.db")
    con = duckdb.connect(db_path)
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, close DOUBLE)")
    con.executemany(
        "INSERT INTO daily_prices VALUES (?, ?, ?)",
        [
            ("2330", "2026-07-13", 900.0),
            ("2330", "2026-07-14", 910.0),
            ("2330", "2026-07-15", 920.0),
        ],
    )
    con.close()

    result = calc_avg20_close(pd.DataFrame([{"stock_id": "2330"}]), db_path=db_path, lookback=20)

    assert result["2330"] == 910.0  # (900+910+920)/3


def test_calc_avg20_close_uses_actual_days_when_insufficient_history(tmp_path):
    """股票只有8天歷史(不滿20天lookback窗口)：用實際8天平均，不強湊、不回None。"""
    import duckdb
    from processors.performance import calc_avg20_close

    db_path = str(tmp_path / "avg20-partial.db")
    con = duckdb.connect(db_path)
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, close DOUBLE)")
    con.executemany(
        "INSERT INTO daily_prices VALUES (?, ?, ?)",
        [("2330", f"2026-07-{d:02d}", 100.0 + d) for d in range(1, 9)],  # 8天
    )
    con.close()

    result = calc_avg20_close(pd.DataFrame([{"stock_id": "2330"}]), db_path=db_path, lookback=20)

    expected = round(sum(100.0 + d for d in range(1, 9)) / 8, 2)
    assert result["2330"] == expected


def test_calc_avg20_close_returns_empty_dict_when_no_price_data(tmp_path):
    import duckdb
    from processors.performance import calc_avg20_close

    db_path = str(tmp_path / "avg20-empty.db")
    con = duckdb.connect(db_path)
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, close DOUBLE)")
    con.close()

    result = calc_avg20_close(pd.DataFrame([{"stock_id": "2330"}]), db_path=db_path, lookback=20)
    assert result == {}
```

- [ ] **Step 2: 執行測試確認會失敗**

Run: `pytest tests/test_processors.py -k calc_avg20_close -v`
Expected: FAIL，`ImportError: cannot import name 'calc_avg20_close'`

- [ ] **Step 3: 實作 `calc_avg20_close()`**

在 `processors/performance.py`，找到 `calc_meta_rank_history()` 函式結束的地方（檔案最後面），加入：

```python
def calc_avg20_close(
    universe_df: pd.DataFrame,
    db_path: str = "data/screener.db",
    lookback: int = 20,
) -> Dict[str, float]:
    """
    每支股票近N個交易日(預設20日)的平均收盤價，供融資/融券維持率(估)當成本基準
    (docs/adr/0002-margin-maintenance-ratio-is-an-estimate.md)。比照
    calc_stock_sparklines() 的pivot模式；不足20天的股票用實際天數的平均值，
    不強求剛好20筆、不硬湊假資料。

    Returns
    -------
    {stock_id: avg_close}，只包含有資料的股票；完全沒有價格資料時回空dict。
    """
    try:
        con = duckdb.connect(db_path, read_only=True)
        dates_df = con.execute(
            f"SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT {lookback}"
        ).fetchdf()
        prices_df = con.execute(
            "SELECT stock_id, date, close FROM daily_prices"
        ).fetchdf()
        con.close()
    except Exception:
        return {}

    if prices_df.empty or dates_df.empty:
        return {}

    all_dates = set(dates_df["date"].tolist())
    stock_ids = set(universe_df["stock_id"].astype(str))
    prices_df["stock_id"] = prices_df["stock_id"].astype(str)
    prices_df = prices_df[
        prices_df["stock_id"].isin(stock_ids) & prices_df["date"].isin(all_dates)
    ]
    prices_df = prices_df.dropna(subset=["close"])

    if prices_df.empty:
        return {}

    avg_by_stock = prices_df.groupby("stock_id")["close"].mean()
    return {sid: round(float(v), 2) for sid, v in avg_by_stock.items()}
```

- [ ] **Step 4: 執行測試確認全部通過**

Run: `pytest tests/test_processors.py -k calc_avg20_close -v`
Expected: 全部 PASS（3個測試）

- [ ] **Step 5: Commit**

```bash
git add processors/performance.py tests/test_processors.py
git commit -m "feat(performance): 新增calc_avg20_close()20日均收盤價"
```

---

### Task 3: `build_stock_detail_data()` 新增四個融資/融券欄位

**Files:**
- Modify: `export/index_generator.py`
- Test: `tests/test_index_generator.py`

`build_stock_detail_data()` 新增兩個可選參數 `total_shares_df`、`avg20_map`，每支股票算出 `financed_pct`／`maintenance_est`／`shorted_pct`／`short_maintenance_est`／`total_shares_asof` 五個新欄位。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_index_generator.py`，找到 `test_build_stock_detail_data_defaults_rolling_and_chips_to_none_without_data` 測試，在它後面（`test_build_stock_detail_data_attaches_volume_and_vol_ratio` 之前）插入：

```python
def test_build_stock_detail_data_calculates_financing_and_short_metrics():
    """複刻真實案例：凌華 close=159.5、20日均價=139.35、TWSE(financing_ratio=0.6)、
    融資餘額3385張、融券餘額196張、已發行股數217779257股：
    融資佔比=3385*1000/217779257*100=1.55%、融資維持率=159.5/139.35/0.6*100=190.8%、
    融券餘額佔比=196*1000/217779257*100=0.09%、融券維持率=139.35/159.5/0.6*100=145.6%
    （融券維持率公式分子分母跟融資對調，方向相反）。"""
    universe_df = pd.DataFrame([
        {"stock_id": "6166", "stock_name": "凌華", "meta_sector": "工業電腦", "exchange": "TWSE"},
    ])
    prices_df = pd.DataFrame([{"stock_id": "6166", "close": 159.5, "change_pct": 10.0}])
    chips_df = pd.DataFrame([
        {"stock_id": "6166", "foreign_net": 0, "trust_net": 0,
         "margin_balance": 3385, "margin_change": 0,
         "short_balance": 196, "short_change": 0},
    ])
    total_shares_df = pd.DataFrame([{"stock_id": "6166", "total_shares": 217779257, "date": "2026-07-09"}])
    avg20_map = {"6166": 139.35}

    stock = build_stock_detail_data(
        universe_df, prices_df, chips_df=chips_df,
        total_shares_df=total_shares_df, avg20_map=avg20_map,
    )["工業電腦"][0]

    assert stock["financed_pct"] == 1.55
    assert stock["maintenance_est"] == 190.8
    assert stock["shorted_pct"] == 0.09
    assert stock["short_maintenance_est"] == 145.6
    assert stock["total_shares_asof"] == "2026-07-09"


def test_build_stock_detail_data_short_maintenance_drops_when_price_rallies_hard():
    """放空情境：股價相對20日均價大漲，代表放空者正在虧損，融券維持率(估)應該
    明顯低於100%，驗證公式方向跟融資維持率相反(分子分母對調)——這裡刻意只給
    short_balance不給margin_balance，驗證融資側正確回None、不受融券側資料影響。"""
    universe_df = pd.DataFrame([
        {"stock_id": "9999", "stock_name": "暴衝股", "meta_sector": "測試族群", "exchange": "TWSE"},
    ])
    prices_df = pd.DataFrame([{"stock_id": "9999", "close": 200.0, "change_pct": 50.0}])
    chips_df = pd.DataFrame([
        {"stock_id": "9999", "foreign_net": 0, "trust_net": 0,
         "margin_balance": 0, "margin_change": 0,
         "short_balance": 500, "short_change": 0},
    ])
    total_shares_df = pd.DataFrame([{"stock_id": "9999", "total_shares": 100000000, "date": "2026-07-09"}])
    avg20_map = {"9999": 100.0}

    stock = build_stock_detail_data(
        universe_df, prices_df, chips_df=chips_df,
        total_shares_df=total_shares_df, avg20_map=avg20_map,
    )["測試族群"][0]

    assert stock["short_maintenance_est"] == 83.3  # 100/200/0.6*100
    assert stock["financed_pct"] is None
    assert stock["maintenance_est"] is None


def test_build_stock_detail_data_financing_and_short_fields_null_independently():
    """融資餘額=0時融資兩欄回None；融券餘額=0時融券兩欄回None——兩組各自獨立判斷，
    不會因為其中一組有值就連帶影響另一組。"""
    universe_df = pd.DataFrame([
        {"stock_id": "1111", "stock_name": "只有融資", "meta_sector": "測試族群", "exchange": "TWSE"},
        {"stock_id": "2222", "stock_name": "只有融券", "meta_sector": "測試族群", "exchange": "TWSE"},
    ])
    prices_df = pd.DataFrame([
        {"stock_id": "1111", "close": 100.0, "change_pct": 1.0},
        {"stock_id": "2222", "close": 100.0, "change_pct": 1.0},
    ])
    chips_df = pd.DataFrame([
        {"stock_id": "1111", "foreign_net": 0, "trust_net": 0,
         "margin_balance": 1000, "margin_change": 0, "short_balance": 0, "short_change": 0},
        {"stock_id": "2222", "foreign_net": 0, "trust_net": 0,
         "margin_balance": 0, "margin_change": 0, "short_balance": 500, "short_change": 0},
    ])
    total_shares_df = pd.DataFrame([
        {"stock_id": "1111", "total_shares": 100000000, "date": "2026-07-09"},
        {"stock_id": "2222", "total_shares": 100000000, "date": "2026-07-09"},
    ])
    avg20_map = {"1111": 90.0, "2222": 90.0}

    result = build_stock_detail_data(
        universe_df, prices_df, chips_df=chips_df,
        total_shares_df=total_shares_df, avg20_map=avg20_map,
    )["測試族群"]
    only_financed = next(s for s in result if s["stock_id"] == "1111")
    only_shorted = next(s for s in result if s["stock_id"] == "2222")

    assert only_financed["financed_pct"] is not None
    assert only_financed["maintenance_est"] is not None
    assert only_financed["shorted_pct"] is None
    assert only_financed["short_maintenance_est"] is None

    assert only_shorted["financed_pct"] is None
    assert only_shorted["maintenance_est"] is None
    assert only_shorted["shorted_pct"] is not None
    assert only_shorted["short_maintenance_est"] is not None


def test_build_stock_detail_data_defaults_financing_fields_to_none_without_data():
    """total_shares_df/avg20_map都沒傳時，四個新欄位+total_shares_asof都要是None，
    不能crash——跟其他enrichment參數(stock_sparklines/rolling_returns/chips_df)的
    fail-soft慣例一致。"""
    universe_df = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "股票甲", "meta_sector": "族群A", "exchange": "TWSE"},
    ])
    prices_df = pd.DataFrame([{"stock_id": "1000", "close": 100.0, "change_pct": 2.0}])

    stock = build_stock_detail_data(universe_df, prices_df)["族群A"][0]

    assert stock["financed_pct"] is None
    assert stock["maintenance_est"] is None
    assert stock["shorted_pct"] is None
    assert stock["short_maintenance_est"] is None
    assert stock["total_shares_asof"] is None
```

- [ ] **Step 2: 執行測試確認會失敗**

Run: `pytest tests/test_index_generator.py -k "financing or short_maintenance or financing_and_short" -v`
Expected: FAIL（`build_stock_detail_data() got an unexpected keyword argument 'total_shares_df'` 或 `KeyError: 'financed_pct'`）

- [ ] **Step 3: 修改 `build_stock_detail_data()`**

在 `export/index_generator.py`，找到函式簽章（`export/index_generator.py:518`附近）：

```python
def build_stock_detail_data(
    universe_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    stock_sparklines: Optional[Dict[str, dict]] = None,
    rolling_returns: Optional[Dict[str, dict]] = None,
    chips_df: Optional[pd.DataFrame] = None,
) -> Dict[str, List[Dict[str, Any]]]:
```

改成：

```python
def build_stock_detail_data(
    universe_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    stock_sparklines: Optional[Dict[str, dict]] = None,
    rolling_returns: Optional[Dict[str, dict]] = None,
    chips_df: Optional[pd.DataFrame] = None,
    total_shares_df: Optional[pd.DataFrame] = None,
    avg20_map: Optional[Dict[str, float]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
```

在函式 docstring 裡（找到 `不補假資料、不crash。` 這句），在它後面加一段：

```python
    total_shares_df：screener/database.py::get_latest_total_shares() 的輸出（含
    stock_id/total_shares/date欄位），供financed_pct/shorted_pct的分母(已發行股數)
    +集保資料實際日期(total_shares_asof)。
    avg20_map：processors/performance.py::calc_avg20_close() 的輸出，供
    maintenance_est/short_maintenance_est的成本基準。兩者任一沒傳、或這支股票
    沒有對應資料，四個新欄位都回傳None（不補假資料）。
```

找到：

```python
    universe = universe_df[["stock_id", "stock_name", "meta_sector"]].copy()
    universe["stock_id"] = universe["stock_id"].astype(str)
    prices = prices_df.copy()
    if not prices.empty:
        prices["stock_id"] = prices["stock_id"].astype(str)
    prices_map = prices.set_index("stock_id") if not prices.empty else pd.DataFrame()
    sparklines = stock_sparklines or {}
    rolling = rolling_returns or {}
    chips = chips_df.copy() if chips_df is not None and not chips_df.empty else pd.DataFrame()
    if not chips.empty:
        chips["stock_id"] = chips["stock_id"].astype(str)
    chips_map = chips.set_index("stock_id") if not chips.empty else pd.DataFrame()
```

改成（`universe` 多選 `exchange` 欄，新增 `total_shares_map`／`avg20`）：

```python
    universe_cols = ["stock_id", "stock_name", "meta_sector"]
    if "exchange" in universe_df.columns:
        universe_cols.append("exchange")
    universe = universe_df[universe_cols].copy()
    universe["stock_id"] = universe["stock_id"].astype(str)
    prices = prices_df.copy()
    if not prices.empty:
        prices["stock_id"] = prices["stock_id"].astype(str)
    prices_map = prices.set_index("stock_id") if not prices.empty else pd.DataFrame()
    sparklines = stock_sparklines or {}
    rolling = rolling_returns or {}
    chips = chips_df.copy() if chips_df is not None and not chips_df.empty else pd.DataFrame()
    if not chips.empty:
        chips["stock_id"] = chips["stock_id"].astype(str)
    chips_map = chips.set_index("stock_id") if not chips.empty else pd.DataFrame()
    total_shares = total_shares_df.copy() if total_shares_df is not None and not total_shares_df.empty else pd.DataFrame()
    if not total_shares.empty:
        total_shares["stock_id"] = total_shares["stock_id"].astype(str)
    total_shares_map = total_shares.set_index("stock_id") if not total_shares.empty else pd.DataFrame()
    avg20 = avg20_map or {}
```

找到主迴圈：

```python
    for _, row in universe.iterrows():
        sid = row["stock_id"]
        meta_name = row["meta_sector"]
        if pd.isna(meta_name):
            continue
        has_price = sid in prices_map.index
        spark = sparklines.get(sid, {})
        roll = rolling.get(sid, {})
        c = chips_map.loc[sid] if sid in chips_map.index else None
        entry: Dict[str, Any] = {
            "stock_id": sid,
            "stock_name": row["stock_name"],
            "no_data": not has_price,
            "close": float(prices_map.loc[sid]["close"]) if has_price else None,
            "change_pct": float(prices_map.loc[sid]["change_pct"]) if has_price else None,
            "pcts": spark.get("pcts", []),
            "dates": spark.get("dates", []),
            "volumes": spark.get("volumes", []),
            "volume": spark.get("volumes", [None])[-1] if spark.get("volumes") else None,
            "vol_ratio": spark.get("vol_ratio"),
            "opens": spark.get("opens", []),
            "highs": spark.get("highs", []),
            "lows": spark.get("lows", []),
            "closes": spark.get("closes", []),
            "roll5": roll.get(5), "roll7": roll.get(7), "roll10": roll.get(10), "roll14": roll.get(14),
            "foreign_net": _chips_num(c["foreign_net"]) if c is not None else None,
            "trust_net": _chips_num(c["trust_net"]) if c is not None else None,
            "margin_balance": _chips_num(c["margin_balance"]) if c is not None else None,
            "margin_change": _chips_num(c["margin_change"]) if c is not None else None,
        }
        result[meta_name].append(entry)
```

改成（新增 financing_ratio 計算 + 四個新欄位 + total_shares_asof）：

```python
    for _, row in universe.iterrows():
        sid = row["stock_id"]
        meta_name = row["meta_sector"]
        if pd.isna(meta_name):
            continue
        has_price = sid in prices_map.index
        spark = sparklines.get(sid, {})
        roll = rolling.get(sid, {})
        c = chips_map.loc[sid] if sid in chips_map.index else None
        close_price = float(prices_map.loc[sid]["close"]) if has_price else None

        # 融資成數：上市6成/上櫃5成，注意股/處置股例外不處理（見spec Out of Scope）
        exchange = row.get("exchange")
        financing_ratio = 0.6 if exchange == "TWSE" else 0.5

        margin_balance_lots = _chips_num(c["margin_balance"]) if c is not None else None
        short_balance_lots = _chips_num(c.get("short_balance")) if c is not None else None
        total_shares_val = (
            int(total_shares_map.loc[sid, "total_shares"]) if sid in total_shares_map.index else None
        )
        total_shares_asof_raw = (
            total_shares_map.loc[sid, "date"] if sid in total_shares_map.index else None
        )
        total_shares_asof = (
            pd.Timestamp(total_shares_asof_raw).strftime("%Y-%m-%d")
            if total_shares_asof_raw is not None and pd.notna(total_shares_asof_raw) else None
        )
        avg20_close = avg20.get(sid)

        financed_pct = (
            round(margin_balance_lots * 1000 / total_shares_val * 100, 2)
            if margin_balance_lots and total_shares_val else None
        )
        maintenance_est = (
            round(close_price / avg20_close / financing_ratio * 100, 1)
            if margin_balance_lots and avg20_close and close_price is not None else None
        )
        shorted_pct = (
            round(short_balance_lots * 1000 / total_shares_val * 100, 2)
            if short_balance_lots and total_shares_val else None
        )
        short_maintenance_est = (
            round(avg20_close / close_price / financing_ratio * 100, 1)
            if short_balance_lots and avg20_close and close_price is not None else None
        )

        entry: Dict[str, Any] = {
            "stock_id": sid,
            "stock_name": row["stock_name"],
            "no_data": not has_price,
            "close": close_price,
            "change_pct": float(prices_map.loc[sid]["change_pct"]) if has_price else None,
            "pcts": spark.get("pcts", []),
            "dates": spark.get("dates", []),
            "volumes": spark.get("volumes", []),
            "volume": spark.get("volumes", [None])[-1] if spark.get("volumes") else None,
            "vol_ratio": spark.get("vol_ratio"),
            "opens": spark.get("opens", []),
            "highs": spark.get("highs", []),
            "lows": spark.get("lows", []),
            "closes": spark.get("closes", []),
            "roll5": roll.get(5), "roll7": roll.get(7), "roll10": roll.get(10), "roll14": roll.get(14),
            "foreign_net": _chips_num(c["foreign_net"]) if c is not None else None,
            "trust_net": _chips_num(c["trust_net"]) if c is not None else None,
            "margin_balance": _chips_num(c["margin_balance"]) if c is not None else None,
            "margin_change": _chips_num(c["margin_change"]) if c is not None else None,
            "financed_pct": financed_pct,
            "maintenance_est": maintenance_est,
            "shorted_pct": shorted_pct,
            "short_maintenance_est": short_maintenance_est,
            "total_shares_asof": total_shares_asof,
        }
        result[meta_name].append(entry)
```

- [ ] **Step 4: 執行測試確認全部通過**

Run: `pytest tests/test_index_generator.py -v`
Expected: 全部 PASS（含既有全部 `build_stock_detail_data` 測試——注意既有測試的 `chips_df` fixture
沒有 `short_balance` 欄位，`c.get("short_balance")` 對缺欄位的 Series 安全回 None，不會 crash）

- [ ] **Step 5: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index_generator): build_stock_detail_data()新增融資/融券佔比+維持率(估)"
```

---

### Task 4: 個股列表 CSS/JS 新增四欄（含警示徽章＋集保日期提示）

**Files:**
- Modify: `export/index_generator.py`
- Test: `tests/test_index_generator.py`

新增 CSS class（`.maint-badge`、`.asof-note`），JS 新增 `_plainPctTd()`／`_maintTd()` 兩個渲染 helper，`renderStockListItem()`／`_sortValue()` 掛上四個新欄位，表頭跟排序 key 對應更新，個股列表上方顯示集保資料實際日期。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_index_generator.py` 檔案最後面加入：

```python
def test_generate_renders_financing_and_short_columns_with_warning_badges(tmp_path):
    """個股列表新增融資佔比/融資維持率(估)/融券餘額佔比/融券維持率(估)四欄，
    低於130%時要有警示徽章，欄位都可點排序，且集保資料日期有顯示提示。"""
    output_path = tmp_path / "index.html"
    meta_perf = [{"meta_name": "族群A", "avg_change_pct": 2.0, "up_count": 1, "down_count": 0, "flat_count": 0}]
    universe_df = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "測試股", "meta_sector": "族群A", "exchange": "TWSE"},
    ])
    prices_df = pd.DataFrame([{"stock_id": "1000", "close": 200.0, "change_pct": 2.0}])
    chips_df = pd.DataFrame([
        {"stock_id": "1000", "foreign_net": 0, "trust_net": 0,
         "margin_balance": 1000, "margin_change": 0, "short_balance": 500, "short_change": 0},
    ])
    total_shares_df = pd.DataFrame([{"stock_id": "1000", "total_shares": 100000000, "date": "2026-07-09"}])
    avg20_map = {"1000": 100.0}  # close(200)遠高於avg20(100) → short_maintenance_est<130，觸發警示

    generate(
        date(2026, 7, 29), meta_perf, universe_df, {}, {}, prices_df, {},
        chips_df=chips_df, total_shares_df=total_shares_df, avg20_map=avg20_map,
        output_path=str(output_path),
    )

    html = output_path.read_text(encoding="utf-8")
    assert ">融資佔比</button>" in html
    assert ">融資維持率(估)</button>" in html
    assert ">融券餘額佔比</button>" in html
    assert ">融券維持率(估)</button>" in html
    assert "onclick=\"sortStockList(this.parentElement,'financed')\"" in html
    assert "onclick=\"sortStockList(this.parentElement,'maint')\"" in html
    assert "onclick=\"sortStockList(this.parentElement,'shorted')\"" in html
    assert "onclick=\"sortStockList(this.parentElement,'shortmaint')\"" in html
    assert "function _plainPctTd" in html
    assert "function _maintTd" in html
    assert "maint-badge" in html
    assert "集保資料：" in html
```

- [ ] **Step 2: 執行測試確認會失敗**

Run: `pytest tests/test_index_generator.py -k financing_and_short_columns -v`
Expected: FAIL（`generate() got an unexpected keyword argument 'total_shares_df'`）

- [ ] **Step 3: 新增 CSS**

在 `export/index_generator.py`，找到（`export/index_generator.py:773`附近）：

```
.vol-burst-badge{display:inline-block;padding:1px 5px;border-radius:3px;font-size:.68rem;font-weight:700;
  background:color-mix(in srgb, var(--accent) 20%, transparent);color:var(--accent);vertical-align:middle}
```

在它後面加：

```
.maint-badge{display:inline-block;padding:1px 5px;border-radius:3px;font-size:.68rem;font-weight:700;
  background:color-mix(in srgb, var(--down) 20%, transparent);color:var(--down);vertical-align:middle;margin-left:3px}
.asof-note{font-size:.68rem;color:var(--ink-3);margin:6px 0 0;font-family:var(--mono)}
```

- [ ] **Step 4: 新增 JS helper 函式**

在 `export/index_generator.py`，找到 `_volTd()` 函式（`export/index_generator.py:1397`附近）結束的地方（`}}`），在它後面、`renderStockListItem` 之前插入：

```javascript
// 融資佔比/融券餘額佔比：純數字顯示，不設警示門檻(沒有客觀依據硬設門檻)。
function _plainPctTd(v) {{
  if (v === null || v === undefined) return '<td class="num tabular">─</td>';
  return `<td class="num tabular">${{v.toFixed(2)}}%</td>`;
}}

// 融資/融券維持率(估)：低於130%(法規追繳門檻)視為警示，用警示色+粗體+文字徽章明確標示。
// 融資/融券兩欄共用同一套門檻邏輯(見docs/adr/0002-margin-maintenance-ratio-is-an-estimate.md)。
function _maintTd(v) {{
  if (v === null || v === undefined) return '<td class="num tabular">─</td>';
  const isDanger = v < 130;
  const style = isDanger ? 'color:var(--down);font-weight:700' : 'color:var(--ink-2)';
  const badge = isDanger ? ' <span class="maint-badge">追繳risk</span>' : '';
  return `<td class="num tabular" style="${{style}}">${{v.toFixed(1)}}%${{badge}}</td>`;
}}
```

- [ ] **Step 5: 更新 `renderStockListItem()`**

找到（`export/index_generator.py:1405`附近）：

```javascript
function renderStockListItem(s) {{
  const sid = escHtml(s.stock_id);
  if (s.no_data) {{
    return `<tr class="stock-item no-data"><td><span class="si-id">${{sid}}</span><span class="si-name">${{escHtml(s.stock_name)}}</span></td><td colspan="7">無行情</td></tr>`;
  }}
  const color = s.change_pct >= 0 ? 'var(--up)' : 'var(--down)';
  const sign = s.change_pct >= 0 ? '+' : '';
  const arrow = s.change_pct > 0 ? '▲' : (s.change_pct < 0 ? '▼' : '─');
  return `<tr class="stock-item" tabindex="0" onclick="openStockCard('${{sid}}')" `
    + `onkeydown="if(event.key==='Enter'||event.key===' '){{event.preventDefault();openStockCard('${{sid}}')}}">`
    + `<td><span class="si-id">${{sid}}</span><span class="si-name">${{escHtml(s.stock_name)}}</span></td>`
    + `<td class="num tabular">${{fmtPrice(s.close)}}</td>`
    + `<td class="num tabular" style="color:${{color}}">${{arrow}} ${{sign}}${{s.change_pct.toFixed(2)}}%</td>`
    + `${{_volTd(s.vol_ratio)}}`
    + `${{_rollTd(s.roll5)}}${{_rollTd(s.roll7)}}${{_rollTd(s.roll10)}}${{_rollTd(s.roll14)}}</tr>`;
}}
```

改成（新增4欄、colspan 7→11）：

```javascript
function renderStockListItem(s) {{
  const sid = escHtml(s.stock_id);
  if (s.no_data) {{
    return `<tr class="stock-item no-data"><td><span class="si-id">${{sid}}</span><span class="si-name">${{escHtml(s.stock_name)}}</span></td><td colspan="11">無行情</td></tr>`;
  }}
  const color = s.change_pct >= 0 ? 'var(--up)' : 'var(--down)';
  const sign = s.change_pct >= 0 ? '+' : '';
  const arrow = s.change_pct > 0 ? '▲' : (s.change_pct < 0 ? '▼' : '─');
  return `<tr class="stock-item" tabindex="0" onclick="openStockCard('${{sid}}')" `
    + `onkeydown="if(event.key==='Enter'||event.key===' '){{event.preventDefault();openStockCard('${{sid}}')}}">`
    + `<td><span class="si-id">${{sid}}</span><span class="si-name">${{escHtml(s.stock_name)}}</span></td>`
    + `<td class="num tabular">${{fmtPrice(s.close)}}</td>`
    + `<td class="num tabular" style="color:${{color}}">${{arrow}} ${{sign}}${{s.change_pct.toFixed(2)}}%</td>`
    + `${{_volTd(s.vol_ratio)}}`
    + `${{_plainPctTd(s.financed_pct)}}`
    + `${{_maintTd(s.maintenance_est)}}`
    + `${{_plainPctTd(s.shorted_pct)}}`
    + `${{_maintTd(s.short_maintenance_est)}}`
    + `${{_rollTd(s.roll5)}}${{_rollTd(s.roll7)}}${{_rollTd(s.roll10)}}${{_rollTd(s.roll14)}}</tr>`;
}}
```

- [ ] **Step 6: 更新 `_sortValue()`**

找到（`export/index_generator.py:1485`附近）：

```javascript
function _sortValue(s, key) {{
  if (key === 'pct') return s.change_pct;
  if (key === 'id') return s.stock_id;
  if (key === 'close') return s.close;
  if (key === 'vol') return s.vol_ratio;
  if (key === '5' || key === '7' || key === '10' || key === '14') return s['roll' + key];
  return null;
}}
```

改成：

```javascript
function _sortValue(s, key) {{
  if (key === 'pct') return s.change_pct;
  if (key === 'id') return s.stock_id;
  if (key === 'close') return s.close;
  if (key === 'vol') return s.vol_ratio;
  if (key === 'financed') return s.financed_pct;
  if (key === 'maint') return s.maintenance_est;
  if (key === 'shorted') return s.shorted_pct;
  if (key === 'shortmaint') return s.short_maintenance_est;
  if (key === '5' || key === '7' || key === '10' || key === '14') return s['roll' + key];
  return null;
}}
```

- [ ] **Step 7: 更新 `selectGroup()` 的表頭與集保日期提示**

找到（`export/index_generator.py:1553`附近）：

```javascript
  const metaSpark = buildSparkline(meta.daily_pct, meta.dates, 'meta-sparkline');
  const chipsSum = buildChipsSummary(meta);
  const historyRecord = buildHistoryRecord(meta);
```

改成（新增 `asofNote` 計算）：

```javascript
  const metaSpark = buildSparkline(meta.daily_pct, meta.dates, 'meta-sparkline');
  const chipsSum = buildChipsSummary(meta);
  const historyRecord = buildHistoryRecord(meta);
  const asofStock = stocks.find(s => s.total_shares_asof);
  const asofNote = asofStock ? `<div class="asof-note">集保資料：${{escHtml(asofStock.total_shares_asof)}}</div>` : '';
```

找到（`export/index_generator.py:1563`附近）的 `else` 分支：

```javascript
  }} else {{
    panel.innerHTML = `
      <div class="detail-head"><h3>${{safeName}}</h3><span class="dpct" style="color:${{pctColor}}">${{pctStr}}</span></div>
      <div class="detail-sub">▲${{meta.up_count}}檔 ▼${{meta.down_count}}檔　・　共 ${{stocks.length}} 檔</div>
      ${{metaSpark}}${{chipsSum}}${{historyRecord}}
      <div class="overflow-wrap"><table class="stock-list-table">
        <thead><tr>
          <th aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'id')">股票</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'close')">收盤</button></th>
          <th class="num" aria-sort="descending"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'pct')">漲跌%</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'vol')">量比</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'5')">5日</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'7')">7日</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'10')">10日</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'14')">14日</button></th>
        </tr></thead>
        <tbody id="panelStocksWrap"></tbody>
      </table></div>`;
  }}
```

改成（新增4個表頭、插入 `asofNote`）：

```javascript
  }} else {{
    panel.innerHTML = `
      <div class="detail-head"><h3>${{safeName}}</h3><span class="dpct" style="color:${{pctColor}}">${{pctStr}}</span></div>
      <div class="detail-sub">▲${{meta.up_count}}檔 ▼${{meta.down_count}}檔　・　共 ${{stocks.length}} 檔</div>
      ${{metaSpark}}${{chipsSum}}${{historyRecord}}${{asofNote}}
      <div class="overflow-wrap"><table class="stock-list-table">
        <thead><tr>
          <th aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'id')">股票</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'close')">收盤</button></th>
          <th class="num" aria-sort="descending"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'pct')">漲跌%</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'vol')">量比</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'financed')">融資佔比</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'maint')">融資維持率(估)</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'shorted')">融券餘額佔比</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'shortmaint')">融券維持率(估)</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'5')">5日</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'7')">7日</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'10')">10日</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'14')">14日</button></th>
        </tr></thead>
        <tbody id="panelStocksWrap"></tbody>
      </table></div>`;
  }}
```

- [ ] **Step 8: 更新 `generate()` 簽章跟呼叫 `build_stock_detail_data()`**

找到（`export/index_generator.py:1078`附近）：

```python
def generate(
    trade_date: date,
    meta_perf: List[Dict[str, Any]],
    universe_df: pd.DataFrame,
    meta_signals: Dict[str, Dict[str, Any]],
    meta_chips: Dict[str, Dict[str, Any]],
    prices_df: pd.DataFrame,
    heatgrid_windows: Dict[str, Dict[str, Any]],
    stock_sparklines: Optional[Dict[str, dict]] = None,
    rolling_returns: Optional[Dict[str, dict]] = None,
    chips_df: Optional[pd.DataFrame] = None,
    cum_data: Optional[List[Dict[str, Any]]] = None,
    market_regime: Optional[Dict[str, Any]] = None,
    vol_turnover_signals: Optional[List[Dict[str, Any]]] = None,
    rank_history: Optional[Dict[str, Dict[str, Any]]] = None,
    output_path: str = "docs/index.html",
) -> None:
```

改成：

```python
def generate(
    trade_date: date,
    meta_perf: List[Dict[str, Any]],
    universe_df: pd.DataFrame,
    meta_signals: Dict[str, Dict[str, Any]],
    meta_chips: Dict[str, Dict[str, Any]],
    prices_df: pd.DataFrame,
    heatgrid_windows: Dict[str, Dict[str, Any]],
    stock_sparklines: Optional[Dict[str, dict]] = None,
    rolling_returns: Optional[Dict[str, dict]] = None,
    chips_df: Optional[pd.DataFrame] = None,
    cum_data: Optional[List[Dict[str, Any]]] = None,
    market_regime: Optional[Dict[str, Any]] = None,
    vol_turnover_signals: Optional[List[Dict[str, Any]]] = None,
    rank_history: Optional[Dict[str, Dict[str, Any]]] = None,
    total_shares_df: Optional[pd.DataFrame] = None,
    avg20_map: Optional[Dict[str, float]] = None,
    output_path: str = "docs/index.html",
) -> None:
```

在 docstring 裡找到 `- rank_history：calc_meta_rank_history() 輸出...` 那句，在它後面加：

```python
    - total_shares_df：get_latest_total_shares() 輸出，個股融資/融券佔比的分母
      (已發行股數)+集保資料實際日期。
    - avg20_map：calc_avg20_close() 輸出，個股融資/融券維持率(估)的成本基準。
```

找到：

```python
    stock_detail = build_stock_detail_data(universe_df, prices_df, stock_sparklines, rolling_returns, chips_df)
```

改成：

```python
    stock_detail = build_stock_detail_data(
        universe_df, prices_df, stock_sparklines, rolling_returns, chips_df,
        total_shares_df, avg20_map,
    )
```

- [ ] **Step 9: 執行測試確認全部通過**

Run: `pytest tests/test_index_generator.py -v`
Expected: 全部 PASS

- [ ] **Step 10: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index_generator): 個股列表新增融資/融券佔比+維持率(估)四欄UI"
```

---

### Task 5: 接進 `main.py`

**Files:**
- Modify: `main.py`

呼叫 `get_latest_total_shares()`／`calc_avg20_close()` 並傳進 `generate_index_html()`，比照現有 `heatgrid_windows`／`rank_history` 的 try/except fail-soft 慣例。

- [ ] **Step 1: 新增 import**

在 `main.py` 第19行附近，找到：

```python
from processors.performance import calc_sector_performance, calc_meta_performance, calc_universe_performance, calc_cumulative_meta, calc_meta_signals, calc_meta_chips_signals, get_stock_chips_ranking, get_margin_divergence, calc_market_breadth, calc_capital_concentration, classify_market_regime, calc_meta_heatgrid_windows, calc_stock_sparklines, calc_meta_rank_history
```

改成（最後面加 `calc_avg20_close`）：

```python
from processors.performance import calc_sector_performance, calc_meta_performance, calc_universe_performance, calc_cumulative_meta, calc_meta_signals, calc_meta_chips_signals, get_stock_chips_ranking, get_margin_divergence, calc_market_breadth, calc_capital_concentration, classify_market_regime, calc_meta_heatgrid_windows, calc_stock_sparklines, calc_meta_rank_history, calc_avg20_close
```

- [ ] **Step 2: 呼叫兩支新函式**

在 `main.py`，找到（`main.py:749`附近）：

```python
        try:
            index_chips_df = get_chips_today(trade_date.isoformat())
        except Exception as exc:
            logger.warning("個股籌碼資料計算失敗，index.html個股卡片本次不顯示外資/投信/融資: %s", exc)
            index_chips_df = pd.DataFrame()
```

在這段後面（`index_chips_df = pd.DataFrame()` 之後）加入：

```python

        try:
            from screener.database import get_latest_total_shares
            total_shares_df = get_latest_total_shares(trade_date.isoformat())
        except Exception as exc:
            logger.warning("集保已發行股數計算失敗，index.html融資/融券佔比本次不顯示: %s", exc)
            total_shares_df = pd.DataFrame()

        try:
            avg20_map = calc_avg20_close(universe_df) if universe_df is not None else {}
        except Exception as exc:
            logger.warning("20日均價計算失敗，index.html融資/融券維持率(估)本次不顯示: %s", exc)
            avg20_map = {}
```

- [ ] **Step 3: 傳進 `generate_index_html()`**

找到（`main.py:761`附近）：

```python
            generate_index_html(trade_date, meta_perf, universe_df,
                                 meta_signals=meta_signals,
                                 meta_chips=meta_chips,
                                 prices_df=prices_df if prices_df is not None else pd.DataFrame(),
                                 heatgrid_windows=heatgrid_windows,
                                 stock_sparklines=stock_sparklines,
                                 rolling_returns=rolling_returns,
                                 chips_df=index_chips_df,
                                 cum_data=cum_data,
                                 market_regime=market_regime,
                                 vol_turnover_signals=vol_turnover_signals,
                                 rank_history=rank_history)
```

改成：

```python
            generate_index_html(trade_date, meta_perf, universe_df,
                                 meta_signals=meta_signals,
                                 meta_chips=meta_chips,
                                 prices_df=prices_df if prices_df is not None else pd.DataFrame(),
                                 heatgrid_windows=heatgrid_windows,
                                 stock_sparklines=stock_sparklines,
                                 rolling_returns=rolling_returns,
                                 chips_df=index_chips_df,
                                 cum_data=cum_data,
                                 market_regime=market_regime,
                                 vol_turnover_signals=vol_turnover_signals,
                                 rank_history=rank_history,
                                 total_shares_df=total_shares_df,
                                 avg20_map=avg20_map)
```

- [ ] **Step 4: 確認語法正確**

Run: `python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read())"`
Expected: 無輸出（沒有語法錯誤）

- [ ] **Step 5: 執行全部測試確認沒有回歸**

Run: `pytest -q`
Expected: 全部通過

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "feat(main): 接上get_latest_total_shares()+calc_avg20_close()，傳進index.html產生流程"
```

---

### Task 6: 全套測試確認 + debug-tasks.md 交接

**Files:** （無新檔案，純驗證＋交接文件）

- [ ] **Step 1: 跑全部測試**

Run: `pytest -q`
Expected: 全部通過（0 failed）

- [ ] **Step 2: 若有測試失敗，回頭檢查對應 Task 的實作，修正後重跑，直到全綠**

- [ ] **Step 3: 更新 `debug-tasks.md`**

在 `debug-tasks.md` 最後面加入交接區塊（依 `CLAUDE.md` 既有模板）：

```markdown
## [YYYY-MM-DD] 個股列表新增融資/融券佔比與維持率(估)

### 改了什麼
- 異動檔案：screener/database.py, processors/performance.py, export/index_generator.py,
  main.py, tests/test_database.py, tests/test_processors.py, tests/test_index_generator.py
- 邏輯說明：新增get_latest_total_shares()(集保已發行股數，per-stock fallback)+
  calc_avg20_close()(20日均收盤價)兩支資料函式，接進build_stock_detail_data()算出
  四個新欄位：融資佔比、融資維持率(估)(現價/20日均價/融資成數*100%，<130%警示)、
  融券餘額佔比、融券維持率(估)(20日均價/現價/融資成數*100%，方向跟融資相反，
  同樣<130%警示)。個股列表新增這四欄可排序，緊接在量比後面，多空方各自分組相鄰。
  設計討論見CONTEXT.md、docs/adr/0002-margin-maintenance-ratio-is-an-estimate.md，
  spec見docs/superpowers/specs/2026-07-29-stock-margin-metrics-design.md，實作計畫見
  docs/superpowers/plans/2026-07-29-stock-margin-metrics.md。
- 8個task逐一TDD完成，全程先寫失敗測試、確認失敗、再實作、確認通過、才commit。

### 資料來源相關（如有異動）
- 融資佔比/融券餘額佔比：來源是集保股權分散表(shareholder表total_shares)，每週更新，
  比其他每日欄位新鮮度較低，個股列表上方會顯示「集保資料：YYYY-MM-DD」實際日期。
- 融資維持率(估)/融券維持率(估)：兩者都是估算值，不是真實維持率(真實維持率是帳戶
  層級資料，交易所不公布)，用20日均價當成本基準是業界慣例做法。
- 上市/上櫃資料：無異動，都是既有daily_prices/margin/shareholder表的新用法。

### 請 Debugger 驗證
- [ ] 全部測試通過(pytest -q全綠，本機已跑過)
- [ ] 點進任一族群的個股列表，新增4欄：融資佔比/融資維持率(估)/融券餘額佔比/
      融券維持率(估)，位置在量比後面
- [ ] 四欄都可以點欄名排序
- [ ] 融資維持率(估)/融券維持率(估)低於130%時要有警示色+「追繳risk」徽章
- [ ] 個股列表上方要有「集保資料：YYYY-MM-DD」的日期提示
- [ ] 融資餘額=0的股票，融資佔比/融資維持率(估)兩欄顯示「─」；融券餘額=0時，
      融券餘額佔比/融券維持率(估)兩欄顯示「─」——兩組各自獨立判斷

### 特別注意
- 這兩個維持率都是**估算值**，不是真實維持率——UI上「(估)」是刻意標註，不能被誤會
  成精確數字
- 融資成數固定用交易所預設值(上市6成/上櫃5成)，沒有處理注意股/處置股等可能有不同
  融資成數的例外情況(見spec Out of Scope)
```

- [ ] **Step 4: Commit**

```bash
git add debug-tasks.md
git commit -m "docs(debug-tasks): 交接個股列表融資/融券佔比與維持率(估)"
```

---

## Self-Review

**Spec 覆蓋檢查**：
- User Story 1/2（融資佔比、融資維持率估）→ Task 1(資料)+3(計算)+4(UI)
- User Story 3/4（融券餘額佔比、融券維持率估）→ 同上，Task 3 的公式方向對調
- User Story 5（130%共用警示門檻）→ Task 4 `_maintTd()` 兩欄共用同一套邏輯
- User Story 6（四欄都可排序）→ Task 4 `_sortValue()` 新增4個key
- User Story 7（餘額=0時顯示「─」，兩組各自獨立）→ Task 3
  `test_build_stock_detail_data_financing_and_short_fields_null_independently`
- User Story 8（集保資料日期提示）→ Task 4 `asofNote`
- User Story 9（(估)標註+不是真實維持率）→ Task 4 表頭文字「融資維持率(估)」/
  「融券維持率(估)」本身即標註，設計討論記錄在ADR-0002
- User Story 10（多空方各自分組相鄰）→ Task 4 表頭順序：融資佔比/融資維持率(估)/
  融券餘額佔比/融券維持率(估)
- Out of Scope（不處理注意股/處置股例外、不做融資使用率、不為佔比設門檻）→
  全程沒有新增這些邏輯，Task 3/4 的 financing_ratio 只用簡單二元 TWSE/TPEx 判斷

**型別/命名一致性檢查**：`financed_pct`/`maintenance_est`/`shorted_pct`/
`short_maintenance_est`/`total_shares_asof` 五個欄位名稱，從 Task 3 定義開始，
一路到 Task 4（JS `renderStockListItem`/`_sortValue`/`asofNote` 讀取）都用同一組
名稱，沒有改名。`_maintTd`/`_plainPctTd` 函式名稱在 Task 4 的 Step 4（定義）跟
Step 5（`renderStockListItem` 呼叫）之間一致。
