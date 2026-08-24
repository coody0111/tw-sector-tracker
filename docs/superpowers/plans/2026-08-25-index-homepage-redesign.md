# 首頁（index.html）版面／視覺重設 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorder `docs/index.html`'s sections so the heatgrid is the top-priority hero element, sort the anomaly cards by severity, reposition the stock-detail panel so it no longer interrupts the heatgrid, lay its three summary boxes out side-by-side, add glass/glow depth to the dark theme, and wire four already-computed-but-unused data points (dealer net, weekly returns, holder %, weekly institutional totals) into the UI.

**Architecture:** All HTML/CSS/JS lives as an f-string template inside `export/index_generator.py` (`docs/index.html` is a generated artifact — never edit it directly, it will be overwritten by the next `main.py` run). Backend calculations live in `processors/performance.py`. `main.py` wires DB queries into `generate_index_html()`. No new files; every task touches these three existing files (plus their test files).

**Tech Stack:** Python (pandas, duckdb), vanilla JS/CSS embedded in Python f-strings, pytest.

**Baseline:** `pytest -q` → 482 passed, 1 warning (unrelated `FutureWarning`) before this plan starts. Every task must keep the suite green with only new tests added (no regressions).

---

### Task 1: Sort anomaly cards by severity

**Files:**
- Modify: `export/index_generator.py:191-244` (`find_anomaly_cards`)
- Test: `tests/test_index_generator.py:207-299` (append after existing `find_anomaly_cards` tests, before line 302's `from export.index_generator import build_heatgrid_cards`)

- [ ] **Step 1: Write the failing tests**

Insert these two tests right after `test_find_anomaly_cards_silently_excludes_sector_missing_from_signals_and_windows` (currently ends at line 299) and before the `from export.index_generator import build_heatgrid_cards` import line:

```python
def test_find_anomaly_cards_sorts_burst_before_trend():
    """burst(爆量暴衝)排在trend(連續噴出)前面，不管兩者在meta_perf裡的原始順序。"""
    meta_perf = [
        {"meta_name": "連續噴出族群", "avg_change_pct": 2.0, "up_count": 1, "down_count": 0, "flat_count": 0},
        {"meta_name": "爆量族群", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    meta_signals = {
        "連續噴出族群": {"vol_ratio": 1.0, "yesterday_rank": 2},
        "爆量族群": {"vol_ratio": 1.8, "yesterday_rank": 15},  # 排名跳動13 >= 10
    }
    heatgrid_windows = {
        "連續噴出族群": {"streak_today": 6, "last_week_pct_today": 1.0, "this_week_pct_today": 9.0,
                        "streak_5d_ago": None, "last_week_pct_5d_ago": None},
        "爆量族群": {"streak_today": 1, "last_week_pct_today": 1.0, "this_week_pct_today": 1.5,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},
    }
    result = find_anomaly_cards(meta_perf, meta_signals, heatgrid_windows)
    assert [r["meta_name"] for r in result] == ["爆量族群", "連續噴出族群"]
    assert result[0]["kind"] == "burst"
    assert result[1]["kind"] == "trend"


def test_find_anomaly_cards_sorts_by_abs_pct_within_same_kind():
    """同kind(都是burst)內依abs(pct)降冪排列，幅度大的排前面。"""
    meta_perf = [
        {"meta_name": "小漲爆量", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
        {"meta_name": "大跌爆量", "avg_change_pct": -8.0, "up_count": 0, "down_count": 1, "flat_count": 0},
        {"meta_name": "中漲爆量", "avg_change_pct": 3.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    meta_signals = {
        "小漲爆量": {"vol_ratio": 1.8, "yesterday_rank": 13},
        "大跌爆量": {"vol_ratio": 1.8, "yesterday_rank": 13},
        "中漲爆量": {"vol_ratio": 1.8, "yesterday_rank": 13},
    }
    heatgrid_windows = {
        name: {"streak_today": 1, "last_week_pct_today": 1.0, "this_week_pct_today": 1.5,
               "streak_5d_ago": None, "last_week_pct_5d_ago": None}
        for name in ["小漲爆量", "大跌爆量", "中漲爆量"]
    }
    result = find_anomaly_cards(meta_perf, meta_signals, heatgrid_windows)
    # abs(pct)：大跌爆量=8.0 > 中漲爆量=3.0 > 小漲爆量=1.0
    assert [r["meta_name"] for r in result] == ["大跌爆量", "中漲爆量", "小漲爆量"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_index_generator.py -k "sorts_burst_before_trend or sorts_by_abs_pct" -v`
Expected: FAIL — both tests fail because the current insertion order is by `meta_perf`/dict iteration order, not by kind/magnitude (e.g. first test gets `["連續噴出族群", "爆量族群"]` instead of the expected order).

- [ ] **Step 3: Add the sort**

In `export/index_generator.py`, find the end of `find_anomaly_cards` (currently):

```python
        if is_trend:
            last_week_pct = window_data.get("last_week_pct_today")
            this_week_pct = window_data.get("this_week_pct_today")
            results.append({
                "kind": "trend", "meta_name": meta_name, "pct": pct_map[meta_name],
                "reason": f"上週 {last_week_pct:+.1f}% → 本週 {this_week_pct:+.1f}%　加速 {accel:+.1f}pt",
            })

    return results
```

Change to:

```python
        if is_trend:
            last_week_pct = window_data.get("last_week_pct_today")
            this_week_pct = window_data.get("this_week_pct_today")
            results.append({
                "kind": "trend", "meta_name": meta_name, "pct": pct_map[meta_name],
                "reason": f"上週 {last_week_pct:+.1f}% → 本週 {this_week_pct:+.1f}%　加速 {accel:+.1f}pt",
            })

    # 排序：burst(爆量暴衝)優先於trend(連續噴出)——量能異常是更即時的訊號；同kind內依
    # abs(pct)降冪(幅度大的優先)。用pct(卡片上本來就顯示給人看的數字)當排序依據，而不是
    # vol_ratio/accel，使用者比較看得懂「為什麼這張排前面」。卡片視覺大小不變，只調整順序。
    results.sort(key=lambda r: (r["kind"] != "burst", -abs(r["pct"])))
    return results
```

Also update the function's docstring (currently ends with `"同一族群兩者都成立時，burst 優先（量能異常是更即時的訊號）。"`) to add one line noting the output is sorted:

```python
    同一族群兩者都成立時，burst 優先（量能異常是更即時的訊號）。
    回傳結果依嚴重程度排序：burst 排在 trend 前面，同 kind 內依 abs(pct) 降冪。
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_index_generator.py -k "find_anomaly_cards" -v`
Expected: PASS — all 8 `find_anomaly_cards` tests pass (6 existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index): 異動族群卡片依嚴重程度排序(burst優先,同kind比幅度)"
```

---

### Task 2: `calc_meta_chips_signals()` — add dealer_net + weekly cumulative totals

**Files:**
- Modify: `processors/performance.py:618-775` (`calc_meta_chips_signals`)
- Modify: `tests/test_processors.py:104-127` (`_seed_chips_db` helper — must stay backward-compatible with existing 4-tuple callers)
- Test: `tests/test_processors.py` (append new tests after the existing `calc_meta_chips_signals` test block)

- [ ] **Step 1: Make `_seed_chips_db` backward-compatible with a 5th column**

The real `institutional` table (`screener/database.py:52`) already has `dealer_net`, but the test helper's mock schema only has 4 columns. Adding `dealer_net` to production's SELECT will break every existing test that uses `_seed_chips_db` unless the helper is updated first — and it must stay backward-compatible (existing tests pass 4-element tuples).

In `tests/test_processors.py`, replace:

```python
def _seed_chips_db(db_path, inst_rows, margin_rows=None):
    """inst_rows: list of (stock_id, date, foreign_net, trust_net)
    margin_rows: list of (stock_id, date, margin_balance, margin_change)"""
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE institutional (
            stock_id VARCHAR, date DATE, foreign_net BIGINT, trust_net BIGINT
        )
    """)
    con.executemany("INSERT INTO institutional VALUES (?, ?, ?, ?)", inst_rows)
```

With:

```python
def _seed_chips_db(db_path, inst_rows, margin_rows=None):
    """inst_rows: list of (stock_id, date, foreign_net, trust_net) or
    (stock_id, date, foreign_net, trust_net, dealer_net) — 5th element optional,
    defaults to 0 for existing callers that don't test dealer_net.
    margin_rows: list of (stock_id, date, margin_balance, margin_change)"""
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE institutional (
            stock_id VARCHAR, date DATE, foreign_net BIGINT, trust_net BIGINT, dealer_net BIGINT
        )
    """)
    normalized_inst_rows = [
        (r[0], r[1], r[2], r[3], r[4] if len(r) > 4 else 0) for r in inst_rows
    ]
    con.executemany("INSERT INTO institutional VALUES (?, ?, ?, ?, ?)", normalized_inst_rows)
```

- [ ] **Step 2: Run existing tests to confirm the helper change alone doesn't break anything**

Run: `python -m pytest tests/test_processors.py -k "calc_meta_chips_signals" -v`
Expected: PASS — all 5 existing tests still pass (helper is backward-compatible; production code hasn't changed yet).

- [ ] **Step 3: Write the failing tests for dealer_net + weekly totals**

Append after the last existing `calc_meta_chips_signals` test (`test_calc_meta_chips_signals_margin_not_zeroed_when_margin_lags_inst`):

```python
def test_calc_meta_chips_signals_includes_dealer_net_today(tmp_path):
    """dealer_net(自營商買賣超)要跟foreign_net/trust_net一樣，加總進signals，
    即使screener/database.py::get_chips_today()早就抓了這個欄位，這裡先前沒有用到。"""
    db_path = tmp_path / "test.db"
    universe = _make_universe([
        ("1101", "測試族群", "TWSE"),
    ])
    _seed_chips_db(db_path, [
        ("1101", "2026-07-03", 1000, 100, -300),  # dealer_net=-300
    ])

    result = calc_meta_chips_signals(universe, db_path=str(db_path), lookback=1)

    assert result["測試族群"]["dealer_net_today"] == -300


def test_calc_meta_chips_signals_computes_foreign_and_trust_weekly_totals(tmp_path):
    """foreign_net_week/trust_net_week = 近5個交易日foreign_net/trust_net加總，
    口徑對齊現有「近5日」滾動視窗慣例(不是自然日曆週)。"""
    db_path = tmp_path / "test.db"
    universe = _make_universe([
        ("1101", "測試族群", "TWSE"),
    ])
    _seed_chips_db(db_path, [
        ("1101", "2026-06-29", 100, 10),
        ("1101", "2026-06-30", 200, 20),
        ("1101", "2026-07-01", 300, 30),
        ("1101", "2026-07-02", 400, 40),
        ("1101", "2026-07-03", 500, 50),
    ])

    result = calc_meta_chips_signals(universe, db_path=str(db_path), lookback=10)

    assert result["測試族群"]["foreign_net_week"] == 100 + 200 + 300 + 400 + 500
    assert result["測試族群"]["trust_net_week"] == 10 + 20 + 30 + 40 + 50


def test_calc_meta_chips_signals_weekly_totals_use_available_days_when_fewer_than_5(tmp_path):
    """資料不足5個交易日時，加總有多少天算多少天，不強制補齊——比照
    get_shareholder_trend()的既有慣例，不是回傳None或0。"""
    db_path = tmp_path / "test.db"
    universe = _make_universe([
        ("1101", "測試族群", "TWSE"),
    ])
    _seed_chips_db(db_path, [
        ("1101", "2026-07-02", 100, 10),
        ("1101", "2026-07-03", 200, 20),
    ])

    result = calc_meta_chips_signals(universe, db_path=str(db_path), lookback=10)

    assert result["測試族群"]["foreign_net_week"] == 100 + 200
    assert result["測試族群"]["trust_net_week"] == 10 + 20
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python -m pytest tests/test_processors.py -k "dealer_net_today or weekly_totals" -v`
Expected: FAIL with `KeyError: 'dealer_net_today'` / `KeyError: 'foreign_net_week'` (keys don't exist yet in the returned dict).

- [ ] **Step 5: Implement dealer_net + weekly totals**

In `processors/performance.py`, find the institutional SELECT (currently):

```python
        inst_df = con.execute(
            "SELECT stock_id, date, foreign_net, trust_net FROM institutional WHERE date >= ?",
            [min_date],
        ).fetchdf()
```

Change to:

```python
        inst_df = con.execute(
            "SELECT stock_id, date, foreign_net, trust_net, dealer_net FROM institutional WHERE date >= ?",
            [min_date],
        ).fetchdf()
```

Find the pivot construction (currently):

```python
    foreign_pivot = (
        inst_merged.groupby(["meta_sector", "date"])["foreign_net"].sum()
        .unstack(level="date").reindex(columns=all_dates).fillna(0)
    )
    trust_pivot = (
        inst_merged.groupby(["meta_sector", "date"])["trust_net"].sum()
        .unstack(level="date").reindex(columns=all_dates).fillna(0)
    )
```

Add a `dealer_pivot` right after it:

```python
    foreign_pivot = (
        inst_merged.groupby(["meta_sector", "date"])["foreign_net"].sum()
        .unstack(level="date").reindex(columns=all_dates).fillna(0)
    )
    trust_pivot = (
        inst_merged.groupby(["meta_sector", "date"])["trust_net"].sum()
        .unstack(level="date").reindex(columns=all_dates).fillna(0)
    )
    dealer_pivot = (
        inst_merged.groupby(["meta_sector", "date"])["dealer_net"].sum()
        .unstack(level="date").reindex(columns=all_dates).fillna(0)
    )
```

In the per-meta loop, find:

```python
    for meta_name in foreign_pivot.index:
        f_row = foreign_pivot.loc[meta_name]
        t_row = trust_pivot.loc[meta_name]

        foreign_net_today = int(f_row.get(today, 0))
        trust_net_today = int(t_row.get(today, 0))
```

Change to:

```python
    for meta_name in foreign_pivot.index:
        f_row = foreign_pivot.loc[meta_name]
        t_row = trust_pivot.loc[meta_name]
        d_row = dealer_pivot.loc[meta_name]

        foreign_net_today = int(f_row.get(today, 0))
        trust_net_today = int(t_row.get(today, 0))
        dealer_net_today = int(d_row.get(today, 0))

        # 本週累計：近5個交易日foreign_net/trust_net加總(不是自然日曆週)，口徑對齊現有
        # 「近5日」滾動視窗慣例(get_rolling_returns等)。all_dates不足5天時，有多少天就加
        # 多少天，不強制補齊——比照get_shareholder_trend()的既有慣例。
        last5_dates = all_dates[-5:]
        foreign_net_week = int(f_row[last5_dates].sum())
        trust_net_week = int(t_row[last5_dates].sum())
```

Find the final dict construction:

```python
        m = margin_by_meta.get(meta_name, {})
        signals[meta_name] = {
            "foreign_net_today": foreign_net_today,
            "trust_net_today": trust_net_today,
            "foreign_buy_count": buy_count,
            "total_stocks": total_stocks,
            "foreign_buy_ratio": round(buy_count / total_stocks, 2) if total_stocks > 0 else 0,
            "foreign_streak": foreign_streak,
            "trust_streak": trust_streak,
            "partial_coverage": partial_coverage,
            "margin_change_today": m.get("margin_change_today", 0),
            "margin_balance_today": m.get("margin_balance_today", 0),
            "margin_alert": m.get("margin_alert", False),
        }
```

Change to:

```python
        m = margin_by_meta.get(meta_name, {})
        signals[meta_name] = {
            "foreign_net_today": foreign_net_today,
            "trust_net_today": trust_net_today,
            "dealer_net_today": dealer_net_today,
            "foreign_net_week": foreign_net_week,
            "trust_net_week": trust_net_week,
            "foreign_buy_count": buy_count,
            "total_stocks": total_stocks,
            "foreign_buy_ratio": round(buy_count / total_stocks, 2) if total_stocks > 0 else 0,
            "foreign_streak": foreign_streak,
            "trust_streak": trust_streak,
            "partial_coverage": partial_coverage,
            "margin_change_today": m.get("margin_change_today", 0),
            "margin_balance_today": m.get("margin_balance_today", 0),
            "margin_alert": m.get("margin_alert", False),
        }
```

Also update the function's docstring return-shape comment (currently lists `margin_alert, # bool` as the last line) to add:

```python
        dealer_net_today,                     # 自營商今日買賣超（原始股數）
        foreign_net_week, trust_net_week,      # 近5個交易日累計買賣超（原始股數）
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_processors.py -k "calc_meta_chips_signals" -v`
Expected: PASS — all 8 tests (5 existing + 3 new).

- [ ] **Step 7: Run full test file to confirm no regressions from the schema change**

Run: `python -m pytest tests/test_processors.py -v 2>&1 | tail -30`
Expected: no FAILs. All pre-existing tests using `_seed_chips_db` with 4-tuples still pass (dealer_net defaults to 0 for them).

- [ ] **Step 8: Commit**

```bash
git add processors/performance.py tests/test_processors.py
git commit -m "feat(chips): calc_meta_chips_signals新增dealer_net_today+本週累計買賣超"
```

---

### Task 3: Wire dealer_net/weekly totals/weekly_returns into `card_meta`

**Files:**
- Modify: `export/index_generator.py:1199-1224` (`generate()`, `card_meta` construction)
- Test: `tests/test_index_generator.py` (append after `test_generate_embeds_rank_history_into_card_meta_for_history_record`)

- [ ] **Step 1: Write the failing tests**

```python
def test_generate_embeds_dealer_net_and_weekly_totals_into_card_meta(tmp_path):
    """自營商今日買賣超+外資/投信本週累計買賣超要塞進CARD_META，
    供buildChipsSummary()渲染籌碼摘要用。"""
    meta_perf = [
        {"meta_name": "測試族群", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    universe_df = pd.DataFrame([{"stock_id": "1", "stock_name": "股票一", "meta_sector": "測試族群"}])
    prices_df = pd.DataFrame([{"stock_id": "1", "change_pct": 1.0, "close": 100.0}])
    meta_chips = {
        "測試族群": {
            "dealer_net_today": -300000, "foreign_net_week": 9100000, "trust_net_week": 2050000,
        },
    }

    output_path = tmp_path / "index.html"
    generate(
        date(2026, 8, 25), meta_perf, universe_df,
        meta_signals={}, meta_chips=meta_chips, prices_df=prices_df,
        heatgrid_windows={}, output_path=str(output_path),
    )

    html = output_path.read_text(encoding="utf-8")
    compact = html.replace(" ", "")
    assert '"dealer_net_today":-300000' in compact
    assert '"foreign_net_week":9100000' in compact
    assert '"trust_net_week":2050000' in compact


def test_generate_embeds_weekly_returns_into_card_meta(tmp_path):
    """weekly_returns(跟weekly_ranks平行對齊的每週複利報酬%)要塞進CARD_META，
    供buildHistoryRecord()渲染每週小字報酬%用。"""
    meta_perf = [
        {"meta_name": "工業電腦", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    universe_df = pd.DataFrame([{"stock_id": "1", "stock_name": "股票一", "meta_sector": "工業電腦"}])
    prices_df = pd.DataFrame([{"stock_id": "1", "change_pct": 1.0, "close": 100.0}])
    rank_history = {
        "工業電腦": {
            "weekly_ranks": [18, 9, 7, 4, 1], "weekly_returns": [-2.0, 1.2, 2.8, 3.5, 5.7],
            "in_top10_this_week": True, "consecutive_weeks_in_top10": 3,
            "last_top10_week_index": None, "last_top10_rank": None,
        },
    }

    output_path = tmp_path / "index.html"
    generate(
        date(2026, 8, 25), meta_perf, universe_df,
        meta_signals={}, meta_chips={}, prices_df=prices_df,
        heatgrid_windows={}, rank_history=rank_history, output_path=str(output_path),
    )

    html = output_path.read_text(encoding="utf-8")
    compact = html.replace(" ", "")
    assert '"weekly_returns":[-2.0,1.2,2.8,3.5,5.7]' in compact
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_index_generator.py -k "dealer_net_and_weekly_totals or embeds_weekly_returns" -v`
Expected: FAIL — the assertions don't find the keys because `card_meta` doesn't include them yet.

- [ ] **Step 3: Add the fields to `card_meta`**

In `export/index_generator.py`, find:

```python
        card_meta[meta_name] = {
            "pct": c["pct"], "up_count": c["up_count"], "down_count": c["down_count"],
            "daily_pct": sig.get("daily_pct", []), "dates": sig.get("dates", []),
            "foreign_net_today": chips.get("foreign_net_today", 0),
            "trust_net_today": chips.get("trust_net_today", 0),
            "foreign_buy_count": chips.get("foreign_buy_count", 0),
            "total_stocks": chips.get("total_stocks", 0),
            "foreign_streak": chips.get("foreign_streak", 0),
            "trust_streak": chips.get("trust_streak", 0),
            "margin_change_today": chips.get("margin_change_today", 0),
            "margin_balance_today": chips.get("margin_balance_today", 0),
            "margin_alert": bool(chips.get("margin_alert", False)),
            "weekly_ranks": rank_row.get("weekly_ranks", []),
            "in_top10_this_week": rank_row.get("in_top10_this_week", False),
            "consecutive_weeks_in_top10": rank_row.get("consecutive_weeks_in_top10", 0),
            "last_top10_week_index": rank_row.get("last_top10_week_index"),
            "last_top10_rank": rank_row.get("last_top10_rank"),
        }
```

Change to:

```python
        card_meta[meta_name] = {
            "pct": c["pct"], "up_count": c["up_count"], "down_count": c["down_count"],
            "daily_pct": sig.get("daily_pct", []), "dates": sig.get("dates", []),
            "foreign_net_today": chips.get("foreign_net_today", 0),
            "trust_net_today": chips.get("trust_net_today", 0),
            "dealer_net_today": chips.get("dealer_net_today", 0),
            "foreign_net_week": chips.get("foreign_net_week", 0),
            "trust_net_week": chips.get("trust_net_week", 0),
            "foreign_buy_count": chips.get("foreign_buy_count", 0),
            "total_stocks": chips.get("total_stocks", 0),
            "foreign_streak": chips.get("foreign_streak", 0),
            "trust_streak": chips.get("trust_streak", 0),
            "margin_change_today": chips.get("margin_change_today", 0),
            "margin_balance_today": chips.get("margin_balance_today", 0),
            "margin_alert": bool(chips.get("margin_alert", False)),
            "weekly_ranks": rank_row.get("weekly_ranks", []),
            "weekly_returns": rank_row.get("weekly_returns", []),
            "in_top10_this_week": rank_row.get("in_top10_this_week", False),
            "consecutive_weeks_in_top10": rank_row.get("consecutive_weeks_in_top10", 0),
            "last_top10_week_index": rank_row.get("last_top10_week_index"),
            "last_top10_rank": rank_row.get("last_top10_rank"),
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_index_generator.py -k "dealer_net_and_weekly_totals or embeds_weekly_returns or embeds_rank_history" -v`
Expected: PASS — 3 tests (2 new + the pre-existing `embeds_rank_history` test, confirming it still passes with the new keys present).

- [ ] **Step 5: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index): card_meta接上dealer_net/本週累計買賣超/weekly_returns"
```

---

### Task 4: `build_stock_detail_data()` — add holder_pct / holder_week_chg

**Files:**
- Modify: `export/index_generator.py:527-666` (`build_stock_detail_data`)
- Test: `tests/test_index_generator.py` (append after `test_build_stock_detail_data_defaults_to_empty_sparkline_when_missing`)

- [ ] **Step 1: Write the failing tests**

```python
def test_build_stock_detail_data_attaches_holder_pct_and_week_chg():
    """大戶佔比(lv12_15_pct)+週變化(week_chg)要從shareholder_df接進個股資料，
    跟chips.html的get_shareholder_top()同一份資料、同一套離群值防護(該函式內已過濾)。"""
    universe_df = pd.DataFrame([
        {"stock_id": "2330", "stock_name": "台積電", "meta_sector": "半導體"},
    ])
    prices_df = pd.DataFrame([{"stock_id": "2330", "close": 1080.0, "change_pct": 3.2}])
    shareholder_df = pd.DataFrame([
        {"stock_id": "2330", "lv12_15_pct": 68.4, "week_chg": 0.6},
    ])

    stock = build_stock_detail_data(
        universe_df, prices_df, shareholder_df=shareholder_df,
    )["半導體"][0]

    assert stock["holder_pct"] == 68.4
    assert stock["holder_week_chg"] == 0.6


def test_build_stock_detail_data_defaults_holder_fields_to_none_without_data():
    """shareholder_df沒傳、或這支股票不在裡面(可能被離群值防護排除、或還沒有集保資料)，
    holder_pct/holder_week_chg回None，不補假資料，前端顯示「—」。"""
    universe_df = pd.DataFrame([
        {"stock_id": "9999", "stock_name": "無資料股", "meta_sector": "測試族群"},
    ])
    prices_df = pd.DataFrame([{"stock_id": "9999", "close": 10.0, "change_pct": 1.0}])

    stock = build_stock_detail_data(universe_df, prices_df)["測試族群"][0]

    assert stock["holder_pct"] is None
    assert stock["holder_week_chg"] is None

    # 也確認shareholder_df有傳、但這支股票不在裡面的情況
    shareholder_df = pd.DataFrame([{"stock_id": "2330", "lv12_15_pct": 68.4, "week_chg": 0.6}])
    stock2 = build_stock_detail_data(
        universe_df, prices_df, shareholder_df=shareholder_df,
    )["測試族群"][0]
    assert stock2["holder_pct"] is None
    assert stock2["holder_week_chg"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_index_generator.py -k "holder_pct or holder_fields" -v`
Expected: FAIL with `KeyError: 'holder_pct'` (the entry dict doesn't have this key yet), and `TypeError: build_stock_detail_data() got an unexpected keyword argument 'shareholder_df'`.

- [ ] **Step 3: Add the parameter and wiring**

In `export/index_generator.py`, find the function signature:

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

Change to:

```python
def build_stock_detail_data(
    universe_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    stock_sparklines: Optional[Dict[str, dict]] = None,
    rolling_returns: Optional[Dict[str, dict]] = None,
    chips_df: Optional[pd.DataFrame] = None,
    total_shares_df: Optional[pd.DataFrame] = None,
    avg20_map: Optional[Dict[str, float]] = None,
    shareholder_df: Optional[pd.DataFrame] = None,
) -> Dict[str, List[Dict[str, Any]]]:
```

Add a docstring line after the `avg20_map` paragraph (before the "無行情的個股不再跳過" paragraph):

```python
    shareholder_df：screener/database.py::get_shareholder_top() 的輸出（含stock_id/
    lv12_15_pct/week_chg欄位），供個股表格「大戶佔比」「大戶週變化」兩欄。這支函式已經
    內建離群值防護(_MAX_VALID_HOLDER_PCT)並過濾掉異常值，這裡不用再重覆過濾——沒傳、或
    這支股票不在裡面(被防護排除、或還沒有集保資料)，兩欄都回None，前端顯示「—」。
```

Find the resource-preparation block:

```python
    total_shares = total_shares_df.copy() if total_shares_df is not None and not total_shares_df.empty else pd.DataFrame()
    if not total_shares.empty:
        total_shares["stock_id"] = total_shares["stock_id"].astype(str)
    total_shares_map = total_shares.set_index("stock_id") if not total_shares.empty else pd.DataFrame()
    avg20 = avg20_map or {}
```

Change to:

```python
    total_shares = total_shares_df.copy() if total_shares_df is not None and not total_shares_df.empty else pd.DataFrame()
    if not total_shares.empty:
        total_shares["stock_id"] = total_shares["stock_id"].astype(str)
    total_shares_map = total_shares.set_index("stock_id") if not total_shares.empty else pd.DataFrame()
    avg20 = avg20_map or {}
    shareholder = shareholder_df.copy() if shareholder_df is not None and not shareholder_df.empty else pd.DataFrame()
    if not shareholder.empty:
        shareholder["stock_id"] = shareholder["stock_id"].astype(str)
    shareholder_map = shareholder.set_index("stock_id") if not shareholder.empty else pd.DataFrame()
```

Find the per-stock calculation block (right after `avg20_close = avg20.get(sid)`):

```python
        avg20_close = avg20.get(sid)

        financed_pct = (
```

Change to:

```python
        avg20_close = avg20.get(sid)
        holder_pct = (
            float(shareholder_map.loc[sid, "lv12_15_pct"])
            if sid in shareholder_map.index and pd.notna(shareholder_map.loc[sid, "lv12_15_pct"]) else None
        )
        holder_week_chg = (
            float(shareholder_map.loc[sid, "week_chg"])
            if sid in shareholder_map.index and pd.notna(shareholder_map.loc[sid, "week_chg"]) else None
        )

        financed_pct = (
```

Find the `entry` dict construction:

```python
            "shorted_pct": shorted_pct,
            "short_maintenance_est": short_maintenance_est,
            "total_shares_asof": total_shares_asof,
        }
```

Change to:

```python
            "shorted_pct": shorted_pct,
            "short_maintenance_est": short_maintenance_est,
            "total_shares_asof": total_shares_asof,
            "holder_pct": holder_pct,
            "holder_week_chg": holder_week_chg,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_index_generator.py -k "holder_pct or holder_fields" -v`
Expected: PASS — both new tests pass.

- [ ] **Step 5: Run the full `build_stock_detail_data` test group to confirm no regressions**

Run: `python -m pytest tests/test_index_generator.py -k "build_stock_detail_data" -v`
Expected: all pass (existing 13 + 2 new = 15).

- [ ] **Step 6: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index): build_stock_detail_data新增shareholder_df→大戶佔比/週變化"
```

---

### Task 5: Wire `shareholder_df` through `generate()` and `main.py`

**Files:**
- Modify: `export/index_generator.py:1148-1197` (`generate()` signature and its call to `build_stock_detail_data`)
- Modify: `main.py:754-787` (fetch `shareholder_df`, pass it to `generate_index_html`)
- Test: `tests/test_index_generator.py` (append a `generate()`-level integration test)

- [ ] **Step 1: Write the failing test**

```python
def test_generate_passes_shareholder_df_through_to_stock_detail(tmp_path):
    """generate()要把shareholder_df透傳給build_stock_detail_data()，
    確認大戶佔比/週變化真的接到STOCKS的個股資料裡（不只是Task4測過的底層函式本身）。"""
    meta_perf = [{"meta_name": "半導體", "avg_change_pct": 3.2, "up_count": 1, "down_count": 0, "flat_count": 0}]
    universe_df = pd.DataFrame([{"stock_id": "2330", "stock_name": "台積電", "meta_sector": "半導體"}])
    prices_df = pd.DataFrame([{"stock_id": "2330", "close": 1080.0, "change_pct": 3.2}])
    shareholder_df = pd.DataFrame([{"stock_id": "2330", "lv12_15_pct": 68.4, "week_chg": 0.6}])

    output_path = tmp_path / "index.html"
    generate(
        date(2026, 8, 25), meta_perf, universe_df, {}, {}, prices_df, {},
        shareholder_df=shareholder_df, output_path=str(output_path),
    )

    html = output_path.read_text(encoding="utf-8")
    compact = html.replace(" ", "")
    assert '"holder_pct":68.4' in compact
    assert '"holder_week_chg":0.6' in compact
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_index_generator.py -k "passes_shareholder_df_through" -v`
Expected: FAIL with `TypeError: generate() got an unexpected keyword argument 'shareholder_df'`.

- [ ] **Step 3: Add `shareholder_df` to `generate()`**

In `export/index_generator.py`, find the `generate()` signature:

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

Change to:

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
    shareholder_df: Optional[pd.DataFrame] = None,
    output_path: str = "docs/index.html",
) -> None:
```

Add a docstring line in the "有就顯示、沒有就不顯示" list (after the `avg20_map` line):

```python
    - shareholder_df：get_shareholder_top() 輸出，個股表格「大戶佔比」「大戶週變化」兩欄。
```

Find the `build_stock_detail_data` call:

```python
    stock_detail = build_stock_detail_data(
        universe_df, prices_df, stock_sparklines, rolling_returns, chips_df,
        total_shares_df, avg20_map,
    )
```

Change to:

```python
    stock_detail = build_stock_detail_data(
        universe_df, prices_df, stock_sparklines, rolling_returns, chips_df,
        total_shares_df, avg20_map, shareholder_df,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_index_generator.py -k "passes_shareholder_df_through" -v`
Expected: PASS.

- [ ] **Step 5: Wire `main.py` to fetch and pass `shareholder_df`**

In `main.py`, find the `avg20_map` fetch block (currently at line ~761-765):

```python
        try:
            avg20_map = calc_avg20_close(universe_df) if universe_df is not None else {}
        except Exception as exc:
            logger.warning("20日均價計算失敗，index.html融資/融券維持率(估)本次不顯示: %s", exc)
            avg20_map = {}
```

Add a new block right after it, before the `vol_turnover_signals` block:

```python
        try:
            avg20_map = calc_avg20_close(universe_df) if universe_df is not None else {}
        except Exception as exc:
            logger.warning("20日均價計算失敗，index.html融資/融券維持率(估)本次不顯示: %s", exc)
            avg20_map = {}

        try:
            from screener.database import get_shareholder_top
            index_shareholder_df = get_shareholder_top()
        except Exception as exc:
            logger.warning("大戶持倉資料計算失敗，index.html個股表格本次不顯示大戶佔比/週變化: %s", exc)
            index_shareholder_df = pd.DataFrame()
```

Note: this duplicates a `get_shareholder_top()` call that already exists later in `main.py` (around line 818) for `chips.html`'s `sh_rows` construction — kept as a separate, independently-`try/except`-wrapped fetch to match this file's existing convention where each generator's block owns its own data fetching (e.g. `total_shares_df`/`avg20_map` are each fetched once, right before the block that uses them, with their own try/except). Not sharing the DataFrame between the two call sites avoids coupling the chips.html block to the index.html block.

Find the `generate_index_html(...)` call:

```python
        if universe_df is not None:
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

Change to:

```python
        if universe_df is not None:
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
                                 avg20_map=avg20_map,
                                 shareholder_df=index_shareholder_df)
```

- [ ] **Step 6: Sanity-check `main.py` still imports cleanly**

Run: `python -c "import main"`
Expected: no `ImportError`/`SyntaxError` (this only checks the module parses and top-level imports resolve; it does not execute `run()`).

- [ ] **Step 7: Commit**

```bash
git add export/index_generator.py main.py tests/test_index_generator.py
git commit -m "feat(index): generate()/main.py接上shareholder_df"
```

---

### Task 6: Individual stock table — add 大戶佔比 / 大戶週變化 columns (11→13)

**Files:**
- Modify: `export/index_generator.py:1677-1694` (server-rendered `<thead>` inside `selectGroup()`'s panel template)
- Modify: `export/index_generator.py` JS section: `_sortValue()`, `renderStockListItem()` (around lines 1499-1594)
- Test: `tests/test_index_generator.py` (append after `test_generate_renders_financing_and_short_columns_with_warning_badges`)

- [ ] **Step 1: Write the failing test**

```python
def test_generate_renders_holder_pct_and_week_chg_columns(tmp_path):
    """個股列表新增「大戶佔比」「大戶週變化」兩欄(11→13欄)，插在量比跟融資佔比之間，
    可點排序，無資料時顯示「─」不是空白或crash。"""
    output_path = tmp_path / "index.html"
    meta_perf = [{"meta_name": "族群A", "avg_change_pct": 2.0, "up_count": 1, "down_count": 0, "flat_count": 0}]
    universe_df = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "測試股", "meta_sector": "族群A"},
    ])
    prices_df = pd.DataFrame([{"stock_id": "1000", "close": 100.0, "change_pct": 2.0}])
    shareholder_df = pd.DataFrame([{"stock_id": "1000", "lv12_15_pct": 41.2, "week_chg": -1.1}])

    generate(
        date(2026, 8, 25), meta_perf, universe_df, {}, {}, prices_df, {},
        shareholder_df=shareholder_df, output_path=str(output_path),
    )

    html = output_path.read_text(encoding="utf-8")
    assert ">大戶佔比</button>" in html
    assert ">大戶週變化</button>" in html
    assert "onclick=\"sortStockList(this.parentElement,'holder')\"" in html
    assert "onclick=\"sortStockList(this.parentElement,'holderchg')\"" in html
    assert "function _holderPctTd" in html
    assert "function _holderChgTd" in html
    assert "colspan=\"13\"" in html  # 無行情佔位列的colspan要跟著新欄位數更新(原本11)
    assert "colspan=\"11\"" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_index_generator.py -k "holder_pct_and_week_chg_columns" -v`
Expected: FAIL — none of the new headers/functions/colspan exist yet.

- [ ] **Step 3: Update the server-rendered `<thead>` in `selectGroup()`'s panel template**

In `export/index_generator.py`, find (inside the JS template string, `selectGroup()`):

```javascript
      <div class="overflow-wrap"><table class="stock-list-table">
        <thead><tr>
          <th aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'id')">股票</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'close')">收盤</button></th>
          <th class="num" aria-sort="descending"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'pct')">漲跌%</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'vol')">量比</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'financed')">融資佔比</button></th>
```

Change to:

```javascript
      <div class="overflow-wrap"><table class="stock-list-table">
        <thead><tr>
          <th aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'id')">股票</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'close')">收盤</button></th>
          <th class="num" aria-sort="descending"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'pct')">漲跌%</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'vol')">量比</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'holder')">大戶佔比</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'holderchg')">大戶週變化</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'financed')">融資佔比</button></th>
```

(The rest of the `<thead>` row — 融資維持率(估) through 14日 — is unchanged.)

- [ ] **Step 4: Add `_holderPctTd`/`_holderChgTd` helpers and update `_sortValue`/`renderStockListItem`**

Find (in the same JS template, near `_plainPctTd`):

```javascript
// 融資佔比/融券餘額佔比：純數字顯示，不設警示門檻(沒有客觀依據硬設門檻)。
function _plainPctTd(v) {{
  if (v === null || v === undefined) return '<td class="num tabular">─</td>';
  return `<td class="num tabular">${{v.toFixed(2)}}%</td>`;
}}
```

Add right after it:

```javascript
// 大戶佔比：純數字顯示，跟融資/融券佔比一樣不設門檻。
function _holderPctTd(v) {{
  if (v === null || v === undefined) return '<td class="num tabular">─</td>';
  return `<td class="num tabular">${{v.toFixed(2)}}%</td>`;
}}

// 大戶週變化：有正負號，紅漲綠跌配色(比照_rollTd的漲跌色慣例)。
function _holderChgTd(v) {{
  if (v === null || v === undefined) return '<td class="num tabular">─</td>';
  const c = v >= 0 ? 'var(--up)' : 'var(--down)';
  return `<td class="num tabular" style="color:${{c}}">${{v>=0?'+':''}}${{v.toFixed(2)}}%</td>`;
}}
```

Find `renderStockListItem`:

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

Change to:

```javascript
function renderStockListItem(s) {{
  const sid = escHtml(s.stock_id);
  if (s.no_data) {{
    return `<tr class="stock-item no-data"><td><span class="si-id">${{sid}}</span><span class="si-name">${{escHtml(s.stock_name)}}</span></td><td colspan="13">無行情</td></tr>`;
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
    + `${{_holderPctTd(s.holder_pct)}}`
    + `${{_holderChgTd(s.holder_week_chg)}}`
    + `${{_plainPctTd(s.financed_pct)}}`
    + `${{_maintTd(s.maintenance_est)}}`
    + `${{_plainPctTd(s.shorted_pct)}}`
    + `${{_maintTd(s.short_maintenance_est)}}`
    + `${{_rollTd(s.roll5)}}${{_rollTd(s.roll7)}}${{_rollTd(s.roll10)}}${{_rollTd(s.roll14)}}</tr>`;
}}
```

Find `_sortValue`:

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

Change to:

```javascript
function _sortValue(s, key) {{
  if (key === 'pct') return s.change_pct;
  if (key === 'id') return s.stock_id;
  if (key === 'close') return s.close;
  if (key === 'vol') return s.vol_ratio;
  if (key === 'holder') return s.holder_pct;
  if (key === 'holderchg') return s.holder_week_chg;
  if (key === 'financed') return s.financed_pct;
  if (key === 'maint') return s.maintenance_est;
  if (key === 'shorted') return s.shorted_pct;
  if (key === 'shortmaint') return s.short_maintenance_est;
  if (key === '5' || key === '7' || key === '10' || key === '14') return s['roll' + key];
  return null;
}}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_index_generator.py -k "holder_pct_and_week_chg_columns" -v`
Expected: PASS.

- [ ] **Step 6: Run the full financing/columns test group to confirm no regressions**

Run: `python -m pytest tests/test_index_generator.py -k "financing_and_short_columns or rolling_return_columns or volume_ratio_column" -v`
Expected: all pass (colspan/column changes didn't break the pre-existing column tests, since none of them assert an exact colspan value or column count).

- [ ] **Step 7: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index): 個股表格新增大戶佔比/大戶週變化兩欄(11→13欄)"
```

---

### Task 7: `buildChipsSummary()` — add dealer row + weekly cumulative row

**Files:**
- Modify: `export/index_generator.py:1387-1424` (`buildChipsSummary` JS function)
- Test: `tests/test_index_generator.py` (append after Task 3's tests, or anywhere after `build_heatgrid_cards` import — this is a `generate()`-level test since `buildChipsSummary` is JS, not directly unit-testable)

- [ ] **Step 1: Write the failing test**

```python
def test_generate_includes_dealer_and_weekly_rows_in_chips_summary_function(tmp_path):
    """buildChipsSummary()的JS原始碼要包含自營商那一行的邏輯+本週累計那一行的邏輯
    (這是JS函式定義本身的原始碼檢查，不是渲染後的HTML——buildChipsSummary()只在使用者
    點開族群時才在瀏覽器裡執行，見測試策略「無法自動化測試JS」的既有限制)。"""
    output_path = tmp_path / "index.html"
    generate(date(2026, 8, 25), _sample_meta_perf(), _sample_universe_df(), {}, {}, _sample_prices_df(), {},
             output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    build_chips_start = html.index("function buildChipsSummary(meta)")
    build_chips_end = html.index("function buildHistoryRecord(meta)")
    build_chips_body = html[build_chips_start:build_chips_end]

    assert "自營商" in build_chips_body
    assert "meta.dealer_net_today" in build_chips_body
    assert "本週累計" in build_chips_body
    assert "meta.foreign_net_week" in build_chips_body
    assert "meta.trust_net_week" in build_chips_body
```

(`_sample_meta_perf()`/`_sample_universe_df()`/`_sample_prices_df()` are existing helpers defined at `tests/test_index_generator.py:919-934` — each returns a minimal one-sector/one-stock fixture, already used by `test_generate_includes_nav_links_to_other_three_pages` and others.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_index_generator.py -k "dealer_and_weekly_rows_in_chips_summary" -v`
Expected: FAIL — `"自營商" in build_chips_body` is False (the function body doesn't have it yet).

- [ ] **Step 3: Add the dealer row and weekly cumulative row**

In `export/index_generator.py`, find `buildChipsSummary`'s margin block and return statement:

```javascript
  if (meta.margin_change_today && meta.margin_balance_today > 0) {{
    const pct = meta.margin_change_today / meta.margin_balance_today * 100;
    const arrow = meta.margin_change_today > 0 ? '↑' : '↓';
    const color = meta.margin_change_today > 0 ? 'var(--accent)' : 'var(--ink-3)';
    const alert = meta.margin_alert ? '<span class="cs-alert">融資擴張</span>' : '';
    rows.push(`<div class="cs-row"><span class="cs-label">融資</span><span style="color:${{color}};font-weight:700">${{arrow}}${{Math.abs(pct).toFixed(1)}}%</span>${{alert}}</div>`);
  }}
  return rows.length ? `<div class="chips-summary">${{rows.join('')}}</div>` : '';
}}
```

Change to (dealer row inserted right after the trust_net_today block, before margin; weekly cumulative row appended after margin, before return):

```javascript
  if (meta.dealer_net_today) {{
    const dn = meta.dealer_net_today, k = Math.trunc(dn / 1000);
    const color = dn > 0 ? 'var(--up)' : 'var(--down)';
    const sign = dn > 0 ? '+' : '';
    rows.push(`<div class="cs-row"><span class="cs-label">自營商</span><span style="color:${{color}};font-weight:700">${{sign}}${{k.toLocaleString()}}張</span></div>`);
  }}
  if (meta.margin_change_today && meta.margin_balance_today > 0) {{
    const pct = meta.margin_change_today / meta.margin_balance_today * 100;
    const arrow = meta.margin_change_today > 0 ? '↑' : '↓';
    const color = meta.margin_change_today > 0 ? 'var(--accent)' : 'var(--ink-3)';
    const alert = meta.margin_alert ? '<span class="cs-alert">融資擴張</span>' : '';
    rows.push(`<div class="cs-row"><span class="cs-label">融資</span><span style="color:${{color}};font-weight:700">${{arrow}}${{Math.abs(pct).toFixed(1)}}%</span>${{alert}}</div>`);
  }}
  if (meta.foreign_net_week || meta.trust_net_week) {{
    const fw = meta.foreign_net_week || 0, tw = meta.trust_net_week || 0;
    const fwK = Math.trunc(fw / 1000), twK = Math.trunc(tw / 1000);
    const fColor = fw >= 0 ? 'var(--up)' : 'var(--down)';
    const tColor = tw >= 0 ? 'var(--up)' : 'var(--down)';
    rows.push(
      `<div class="cs-row cs-week"><span class="cs-label">本週累計</span>`
      + `<span>外資 <span style="color:${{fColor}};font-weight:700">${{fw>=0?'+':''}}${{fwK.toLocaleString()}}張</span></span>`
      + `<span>投信 <span style="color:${{tColor}};font-weight:700">${{tw>=0?'+':''}}${{twK.toLocaleString()}}張</span></span></div>`
    );
  }}
  return rows.length ? `<div class="chips-summary">${{rows.join('')}}</div>` : '';
}}
```

- [ ] **Step 4: Add CSS for `.cs-week`**

In `export/index_generator.py`'s `_CSS` block, find:

```css
.cs-row .cs-alert{color:var(--accent);font-weight:700}
```

Add right after it:

```css
.cs-row.cs-week{width:100%;border-top:1px solid var(--border);padding-top:8px;margin-top:2px;gap:14px}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_index_generator.py -k "dealer_and_weekly_rows_in_chips_summary" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index): buildChipsSummary新增自營商行+本週累計買賣超行"
```

---

### Task 8: `buildHistoryRecord()` — per-week return % in each week cell

**Files:**
- Modify: `export/index_generator.py:1429-1456` (`buildHistoryRecord` JS function)
- Modify: `export/index_generator.py` `_CSS` block (`.history-week` rules)
- Test: `tests/test_index_generator.py`

- [ ] **Step 1: Write the failing test**

```python
def test_generate_includes_weekly_return_pct_in_history_record_function(tmp_path):
    """buildHistoryRecord()的JS原始碼要讀取meta.weekly_returns、每個週格子多渲染一行
    小字報酬%(hw-pct)。原始碼層級檢查，理由同上個Task的JS檢查慣例。"""
    output_path = tmp_path / "index.html"
    generate(date(2026, 8, 25), _sample_meta_perf(), _sample_universe_df(), {}, {}, _sample_prices_df(), {},
             output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    history_start = html.index("function buildHistoryRecord(meta)")
    history_end = html.index("// 收盤價格式")
    history_body = html[history_start:history_end]

    assert "meta.weekly_returns" in history_body
    assert "hw-pct" in history_body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_index_generator.py -k "weekly_return_pct_in_history_record" -v`
Expected: FAIL.

- [ ] **Step 3: Add per-week pct rendering**

In `export/index_generator.py`, find `buildHistoryRecord`:

```javascript
function buildHistoryRecord(meta) {{
  const ranks = meta.weekly_ranks || [];
  if (!ranks.length) return '';

  let summary;
  if (meta.in_top10_this_week) {{
    summary = `連續 <b>${{meta.consecutive_weeks_in_top10}}</b> 週進榜（前10名）`;
  }} else if (meta.last_top10_week_index !== null && meta.last_top10_week_index !== undefined) {{
    const weeksAgo = ranks.length - 1 - meta.last_top10_week_index;
    summary = `上次進榜是 <b>W-${{weeksAgo}}</b>，當時排第 <b>#${{meta.last_top10_rank}}</b> 名`;
  }} else {{
    summary = `近${{ranks.length}}週都沒有進前10`;
  }}

  const weekCells = ranks.map((rank, i) => {{
    const isCurrent = i === ranks.length - 1;
    const label = isCurrent ? '本週' : `W-${{ranks.length - 1 - i}}`;
    const inTop10 = rank <= 10;
    const cls = 'history-week' + (inTop10 ? ' in-top10' : '');
    return `<div class="${{cls}}"><span class="hw-label">${{label}}</span><span class="hw-rank tabular">#${{rank}}</span></div>`;
  }}).join('');

  return `<div class="history-wrap">
    <div class="history-summary">${{summary}}</div>
    <div class="history-weekline-label">近${{ranks.length}}週排行軌跡</div>
    <div class="history-weekline">${{weekCells}}</div>
  </div>`;
}}
```

Change to:

```javascript
function buildHistoryRecord(meta) {{
  const ranks = meta.weekly_ranks || [];
  if (!ranks.length) return '';
  const returns = meta.weekly_returns || [];

  let summary;
  if (meta.in_top10_this_week) {{
    summary = `連續 <b>${{meta.consecutive_weeks_in_top10}}</b> 週進榜（前10名）`;
  }} else if (meta.last_top10_week_index !== null && meta.last_top10_week_index !== undefined) {{
    const weeksAgo = ranks.length - 1 - meta.last_top10_week_index;
    summary = `上次進榜是 <b>W-${{weeksAgo}}</b>，當時排第 <b>#${{meta.last_top10_rank}}</b> 名`;
  }} else {{
    summary = `近${{ranks.length}}週都沒有進前10`;
  }}

  const weekCells = ranks.map((rank, i) => {{
    const isCurrent = i === ranks.length - 1;
    const label = isCurrent ? '本週' : `W-${{ranks.length - 1 - i}}`;
    const inTop10 = rank <= 10;
    const cls = 'history-week' + (inTop10 ? ' in-top10' : '');
    const ret = returns[i];
    const retHtml = (ret !== null && ret !== undefined)
      ? `<span class="hw-pct tabular" style="color:${{ret >= 0 ? 'var(--up)' : 'var(--down)'}}">${{ret>=0?'+':''}}${{ret.toFixed(1)}}%</span>`
      : '';
    return `<div class="${{cls}}"><span class="hw-label">${{label}}</span><span class="hw-rank tabular">#${{rank}}</span>${{retHtml}}</div>`;
  }}).join('');

  return `<div class="history-wrap">
    <div class="history-summary">${{summary}}</div>
    <div class="history-weekline-label">近${{ranks.length}}週排行軌跡</div>
    <div class="history-weekline">${{weekCells}}</div>
  </div>`;
}}
```

- [ ] **Step 4: Add CSS for `.hw-pct`**

In `_CSS`, find:

```css
.history-week .hw-rank{display:block;margin-top:3px;font-size:.86rem;font-weight:700;color:var(--ink)}
```

Add right after it:

```css
.history-week .hw-pct{display:block;margin-top:2px;font-size:.62rem;font-weight:600}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_index_generator.py -k "weekly_return_pct_in_history_record" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index): buildHistoryRecord每週格子加報酬%小字"
```

---

### Task 9: Page layout reorder — heatgrid hero + two-column secondary row

**Files:**
- Modify: `export/index_generator.py:1260-1281` (`generate()`'s HTML body — section order)
- Modify: `export/index_generator.py` `_CSS` block (new `.secondary-row`/`.secondary-col` rules)
- Test: `tests/test_index_generator.py`

- [ ] **Step 1: Write the failing test**

```python
def test_generate_renders_heatgrid_before_secondary_row_with_anomaly_and_recap_side_by_side(tmp_path):
    """熱區格(族群排行)要在HTML裡出現在異動族群前面(滿版置頂當主角)；異動族群跟族群近況
    要被包在同一個.secondary-row容器裡並排兩欄，不是各自獨立佔滿版寬的區塊。"""
    output_path = tmp_path / "index.html"
    generate(date(2026, 8, 25), _sample_meta_perf(), _sample_universe_df(), {}, {}, _sample_prices_df(), {},
             output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    heatgrid_pos = html.index('id="heatgrid"')
    anomaly_pos = html.index('<h2>異動族群</h2>')
    recap_pos = html.index('<h2>族群近況</h2>')
    secondary_row_pos = html.index('class="secondary-row"')

    assert heatgrid_pos < anomaly_pos, "熱區格要在異動族群前面(滿版置頂當主角)"
    assert secondary_row_pos < anomaly_pos < recap_pos, "異動族群跟族群近況要包在secondary-row容器裡，異動族群在前(左欄)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_index_generator.py -k "heatgrid_before_secondary_row" -v`
Expected: FAIL — currently 異動族群's `<h2>` appears before `id="heatgrid"`, and there's no `.secondary-row` class at all.

- [ ] **Step 3: Reorder the HTML body**

In `export/index_generator.py`, find the `<main>` body (currently):

```python
<main id="main-content">
{_market_regime_html(market_regime)}
{_vol_turnover_html(vol_turnover_signals)}
<div class="section-head"><h2>異動族群</h2><span class="count">{len(anomaly_cards)} 檔符合</span></div>
<div class="section-sub">「現在正在發生」的瞬間訊號——爆量排名跳動、或連續多週噴出。跟下面「族群近況」不同：這裡是單日事件，族群近況是週度趨勢。</div>
<div class="anomaly-wrap"><div class="anomaly-strip">{_anomaly_cards_html(anomaly_cards)}</div></div>

<div class="section-head"><h2>族群排行</h2><span class="count">今日漲跌% ・{len(cards)} 個族群</span></div>
<div class="section-rule"></div>
<div class="section-sub">動能狀態標籤是這版的重點：不是只看今日漲跌，而是綜合「連漲天數＋本週比上週是否加速」判斷這個族群現在的動能還在不在。</div>
<div class="tier-legend">
  <span><span class="dot" style="background:var(--tier-super)"></span>超強＝多頭排列+持續加速</span>
  <span><span class="dot" style="background:var(--tier-strong)"></span>強＝多頭排列，動能穩定</span>
  <span><span class="dot" style="background:var(--tier-mid)"></span>整理＝方向不明</span>
  <span><span class="dot" style="background:var(--tier-weak)"></span>弱＝動能減弱中</span>
  <span><span class="dot" style="background:var(--tier-superweak)"></span>超弱＝轉弱+連跌</span>
</div>
<div class="heatgrid" id="heatgrid">{_heatgrid_html(cards)}</div>
<div class="legend-note">動能狀態標籤（超強/強/整理/弱/超弱）是族群層級獨立算的草案規則（連漲天數+本週比上週加速度），跟個股層級或觀察分頁面的五級分類不共用計算依據，門檻未經回測驗證。「近5日→前5日」是滾動5個交易日的複利累積漲跌幅，不是自然日曆週。</div>

{_sector_recap_html(recap)}
</main>
```

Change to:

```python
<main id="main-content">
{_market_regime_html(market_regime)}
{_vol_turnover_html(vol_turnover_signals)}
<div class="section-head"><h2>族群排行</h2><span class="count">今日漲跌% ・{len(cards)} 個族群</span></div>
<div class="section-rule"></div>
<div class="section-sub">動能狀態標籤是這版的重點：不是只看今日漲跌，而是綜合「連漲天數＋本週比上週是否加速」判斷這個族群現在的動能還在不在。</div>
<div class="tier-legend">
  <span><span class="dot" style="background:var(--tier-super)"></span>超強＝多頭排列+持續加速</span>
  <span><span class="dot" style="background:var(--tier-strong)"></span>強＝多頭排列，動能穩定</span>
  <span><span class="dot" style="background:var(--tier-mid)"></span>整理＝方向不明</span>
  <span><span class="dot" style="background:var(--tier-weak)"></span>弱＝動能減弱中</span>
  <span><span class="dot" style="background:var(--tier-superweak)"></span>超弱＝轉弱+連跌</span>
</div>
<div class="heatgrid" id="heatgrid">{_heatgrid_html(cards)}</div>
<div class="legend-note">動能狀態標籤（超強/強/整理/弱/超弱）是族群層級獨立算的草案規則（連漲天數+本週比上週加速度），跟個股層級或觀察分頁面的五級分類不共用計算依據，門檻未經回測驗證。「近5日→前5日」是滾動5個交易日的複利累積漲跌幅，不是自然日曆週。</div>

<div class="secondary-row">
  <div class="secondary-col">
    <div class="section-head"><h2>異動族群</h2><span class="count">{len(anomaly_cards)} 檔符合</span></div>
    <div class="section-sub">「現在正在發生」的瞬間訊號——爆量排名跳動、或連續多週噴出。跟旁邊「族群近況」不同：這裡是單日事件，族群近況是週度趨勢。</div>
    <div class="anomaly-wrap"><div class="anomaly-strip">{_anomaly_cards_html(anomaly_cards)}</div></div>
  </div>
  <div class="secondary-col">
    {_sector_recap_html(recap)}
  </div>
</div>
</main>
```

(Note: only the section order and the new `.secondary-row`/`.secondary-col` wrapper divs changed; every inner call — `_anomaly_cards_html(anomaly_cards)`, `_sector_recap_html(recap)`, `_heatgrid_html(cards)` — is unchanged. The 異動族群 section's copy changed "下面" → "旁邊" since it's no longer below the recap, it's now beside it.)

- [ ] **Step 4: Add `.secondary-row` CSS**

In `_CSS`, find the `.rankmove-item:last-child{border-bottom:none}` line (last line of the recap-related CSS block) and add right after it:

```css
.secondary-row{display:grid;grid-template-columns:1fr 1fr;gap:24px;padding:0 26px;align-items:start}
@media (max-width:900px){.secondary-row{grid-template-columns:1fr}}
.secondary-row .section-head{padding:20px 0 8px}
.secondary-row .section-rule{margin:0 0 4px}
.secondary-row .section-sub{padding:0 0 14px}
.secondary-row .anomaly-wrap{margin:0}
.secondary-row .role-note{margin:0 0 20px}
.secondary-row .status-cols{padding:0}
.secondary-row .turning-wrap{margin:20px 0 0}
.secondary-row .rankmove-wrap{margin:20px 0 0}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_index_generator.py -k "heatgrid_before_secondary_row" -v`
Expected: PASS.

- [ ] **Step 6: Run the full test file to catch any order-dependent regressions**

Run: `python -m pytest tests/test_index_generator.py -v 2>&1 | tail -20`
Expected: all pass — no test in this file asserts absolute byte-offset ordering between 族群排行/異動族群/族群近況 other than the one just added.

- [ ] **Step 7: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index): 熱區格滿版置頂當主角,異動族群+族群近況併成二欄次要區"
```

---

### Task 10: Visual — glass/glow for super-tier tiles + accent border on detail panel

**Files:**
- Modify: `export/index_generator.py:966-1056` (`_heatgrid_html` — add `tier-super` class to the tile)
- Modify: `export/index_generator.py` `_CSS` block (`.heat-tile.tier-super`, `.detail-panel` border color)
- Test: `tests/test_index_generator.py`

- [ ] **Step 1: Write the failing test**

```python
def test_build_heatgrid_cards_super_tier_tile_gets_tier_super_css_class(tmp_path):
    """超強(super)tier的熱區格tile要多帶一個tier-super class，供CSS加玻璃質感+光暈；
    其餘tier(strong/mid/weak/superweak/None)不受影響，維持原本只有heat-tile一個class。"""
    output_path = tmp_path / "index.html"
    meta_perf = [
        {"meta_name": "超強族群", "avg_change_pct": 6.0, "up_count": 1, "down_count": 0, "flat_count": 0},
        {"meta_name": "整理族群", "avg_change_pct": 0.1, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    # streak=3且accel=(this_week 6.0 - last_week 1.0)=5.0 > 3 → super
    meta_signals = {}
    heatgrid_windows = {
        "超強族群": {"streak_today": 3, "last_week_pct_today": 1.0, "this_week_pct_today": 6.0,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},
        "整理族群": {"streak_today": 0, "last_week_pct_today": 1.0, "this_week_pct_today": 1.5,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},
    }

    universe_df = pd.DataFrame([
        {"stock_id": "1", "stock_name": "股票一", "meta_sector": "超強族群"},
        {"stock_id": "2", "stock_name": "股票二", "meta_sector": "整理族群"},
    ])
    prices_df = pd.DataFrame([
        {"stock_id": "1", "close": 100.0, "change_pct": 6.0},
        {"stock_id": "2", "close": 50.0, "change_pct": 0.1},
    ])

    generate(date(2026, 8, 25), meta_perf, universe_df, meta_signals, {}, prices_df, heatgrid_windows,
             output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert 'class="heat-tile tier-super"' in html
    assert 'class="heat-tile"' in html  # 整理族群仍是純heat-tile，沒被誤加class
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_index_generator.py -k "tier_super_css_class" -v`
Expected: FAIL — `'class="heat-tile tier-super"'` not found (every tile currently only has `class="heat-tile"`).

- [ ] **Step 3: Add the conditional class**

In `export/index_generator.py`, in `_heatgrid_html`, find:

```python
        pct_color = "var(--up)" if c["pct"] >= 0 else "var(--down)"
        meta_name_safe = _esc(c["meta_name"])
        tiles.append(
            f'<div class="heat-tile" data-meta-name="{meta_name_safe}" '
```

Change to:

```python
        pct_color = "var(--up)" if c["pct"] >= 0 else "var(--down)"
        meta_name_safe = _esc(c["meta_name"])
        tile_class = "heat-tile tier-super" if tier is not None and tier["key"] == "super" else "heat-tile"
        tiles.append(
            f'<div class="{tile_class}" data-meta-name="{meta_name_safe}" '
```

- [ ] **Step 4: Add glass/glow CSS (theme-aware via `color-mix`, no separate light-theme block needed)**

In `_CSS`, find:

```css
.heat-tile:hover{transform:translateY(-2px);box-shadow:var(--shadow-2);z-index:2}
.heat-tile.active{outline:2px solid var(--accent);outline-offset:-2px}
```

Add right after it:

```css
/* 超強tier玻璃質感+光暈：故意不覆寫background(每個tile已有inline style來自heat_bg()，
   CSS class的background會被inline覆蓋蓋掉，寫了也不會顯示)，只加border-color+box-shadow。
   用color-mix(in srgb, var(--accent) N%, transparent)而非寫死rgba(240,187,85,...)，
   因為--accent深色(#F0BB55)/淺色(#93701E)主題色相不同，color-mix自動跟著--accent變色，
   兩個主題都合理，不用另外在:root[data-theme="light"]開一組rgba數值。*/
.heat-tile.tier-super{
  border-color:color-mix(in srgb, var(--accent) 50%, transparent);
  box-shadow:0 0 22px color-mix(in srgb, var(--accent) 18%, transparent), var(--shadow-2);
}
.heat-tile.tier-super:hover{box-shadow:0 0 26px color-mix(in srgb, var(--accent) 24%, transparent), var(--shadow-2)}
```

- [ ] **Step 5: Update `.detail-panel` border color + remove now-unused `grid-column`**

This CSS edit belongs conceptually to Task 11 (panel repositioning) since `grid-column:1/-1` only made sense while the panel was a grid item inside `#heatgrid`. Do it here since it's a one-line visual tweak that's easy to verify now; Task 11 will not need to touch this CSS again.

In `_CSS`, find:

```css
.detail-panel{
  grid-column:1/-1;background:var(--panel);border:1px solid var(--border-2);border-radius:5px;
  padding:22px 26px;box-shadow:var(--shadow-2);scroll-margin-top:20px;
  animation:expandIn .22s ease-out;
}
```

Change to:

```css
.detail-panel{
  margin:20px 26px 0;background:var(--panel);border:1px solid var(--accent);border-radius:5px;
  padding:22px 26px;box-shadow:var(--shadow-2);scroll-margin-top:20px;
  animation:expandIn .22s ease-out;
}
```

(`grid-column:1/-1` is replaced with `margin:20px 26px 0` — Task 11 moves the panel to be a sibling of `#heatgrid` rather than a grid item inside it, so `grid-column` would be dead CSS; the margin gives it the same 26px page-gutter alignment as other top-level sections like `.turning-wrap`/`.rankmove-wrap`. Border color changed from `var(--border-2)` to `var(--accent)` per spec's "浮起" emphasis.)

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_index_generator.py -k "tier_super_css_class" -v`
Expected: PASS.

- [ ] **Step 7: Run the full heatgrid-related test group to confirm no regressions**

Run: `python -m pytest tests/test_index_generator.py -k "build_heatgrid_cards or heatgrid_html or classify_tier" -v`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "style(index): 超強tier熱區格加玻璃光暈,個股明細面板邊框改用accent色"
```

---

### Task 11: Reposition the stock-detail panel — anchor after `#heatgrid`, not inside a row

**Files:**
- Modify: `export/index_generator.py:1624-1708` (`selectGroup()` JS function)
- Test: `tests/test_index_generator.py`

- [ ] **Step 1: Write the failing test**

```python
def test_generate_selectgroup_inserts_panel_after_heatgrid_container_not_inside_a_row(tmp_path):
    """個股明細面板要插在#heatgrid容器「之後」(整個熱區格結束後)，不是插進被點tile
    所在列的最後一格後面——避免面板打斷41格熱區格的排列。用原始碼字串檢查selectGroup()
    的insertAdjacentElement()呼叫對象是heatgrid變數，不是tiles/rowTiles相關的東西。"""
    output_path = tmp_path / "index.html"
    generate(date(2026, 8, 25), _sample_meta_perf(), _sample_universe_df(), {}, {}, _sample_prices_df(), {},
             output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    select_group_start = html.index("function selectGroup(")
    select_group_end = html.index("/* ── 個股/族群搜尋 ── */")
    select_group_body = html[select_group_start:select_group_end]

    assert "heatgrid.insertAdjacentElement('afterend', panel)" in select_group_body
    assert "rowTiles" not in select_group_body
    assert "document.getElementById('heatgrid')" in select_group_body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_index_generator.py -k "inserts_panel_after_heatgrid_container" -v`
Expected: FAIL — current code uses `rowTiles`/`lastInRow.insertAdjacentElement(...)`, not `heatgrid.insertAdjacentElement(...)`.

- [ ] **Step 3: Change the insertion anchor**

In `export/index_generator.py`, find (inside `selectGroup()`):

```javascript
  const tiles = [...document.querySelectorAll('.heat-tile')];
  const tile = tiles.find(t => t.dataset.metaName === name);
  if (!tile) return;
  tile.classList.add('active');
```

This part is unchanged. Find further down:

```javascript
  const rowTop = tile.offsetTop;
  const rowTiles = tiles.filter(t => t.offsetTop === rowTop);
  const lastInRow = rowTiles[rowTiles.length - 1];
  lastInRow.insertAdjacentElement('afterend', panel);
  // renderPanelStocks()一定要在panel插入document「之後」呼叫——它內部用
  // document.getElementById('panelStocksWrap')找tbody，插入前panel還是離線節點，
  // document.getElementById找不到，會被wrap===null的guard擋掉，表格永遠是空的
  // （Cody回報「列表要點欄位才會出現」就是這個bug：點欄位排序時panel已經在document
  // 裡了，才第一次真的render出東西）。
  if (stocks.length) renderPanelStocks();
  panel.scrollIntoView({{behavior:'smooth', block:'nearest'}});
}}
```

Change to:

```javascript
  // 面板錨定在#heatgrid容器「之後」(不是被點tile所在列的最後一格後面)——這樣熱區格
  // 41格的排列永遠完整不被打斷，換族群時直接點旁邊的tile就換，不用先收合再點。
  const heatgrid = document.getElementById('heatgrid');
  heatgrid.insertAdjacentElement('afterend', panel);
  // renderPanelStocks()一定要在panel插入document「之後」呼叫——它內部用
  // document.getElementById('panelStocksWrap')找tbody，插入前panel還是離線節點，
  // document.getElementById找不到，會被wrap===null的guard擋掉，表格永遠是空的
  // （Cody回報「列表要點欄位才會出現」就是這個bug：點欄位排序時panel已經在document
  // 裡了，才第一次真的render出東西）。
  if (stocks.length) renderPanelStocks();
  panel.scrollIntoView({{behavior:'smooth', block:'nearest'}});
}}
```

Note: the `tiles` array (`[...document.querySelectorAll('.heat-tile')]`) is still used earlier in the function (for `tiles.find(t => t.dataset.metaName === name)`), so it stays — only the `rowTop`/`rowTiles`/`lastInRow` lines are removed.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_index_generator.py -k "inserts_panel_after_heatgrid_container" -v`
Expected: PASS.

- [ ] **Step 5: Run the toggle/render-order tests to confirm no regressions**

Run: `python -m pytest tests/test_index_generator.py -k "selectgroup or render_panel_stocks_after" -v`
Expected: all pass — `test_generate_selectgroup_toggles_closed_on_repeat_click` and `test_generate_calls_render_panel_stocks_after_panel_is_attached_to_dom` both do substring/ordering checks unrelated to the insertion target variable name, so they're unaffected.

- [ ] **Step 6: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index): 個股明細面板改錨定#heatgrid容器之後,不再插入tile網格中間"
```

---

### Task 12: Three-column layout for 走勢／籌碼動向／歷史進榜 inside the detail panel

**Files:**
- Modify: `export/index_generator.py:1672-1694` (`selectGroup()`'s panel `innerHTML` template)
- Modify: `export/index_generator.py` `_CSS` block (new `.detail-three-col` rule)
- Test: `tests/test_index_generator.py`

- [ ] **Step 1: Write the failing test**

```python
def test_generate_wraps_spark_chips_history_in_three_column_grid(tmp_path):
    """走勢/籌碼動向/歷史進榜三個摘要區塊要包在.detail-three-col容器裡並排三欄，
    不是原本的垂直堆疊(各自獨立一整行)。"""
    output_path = tmp_path / "index.html"
    generate(date(2026, 8, 25), _sample_meta_perf(), _sample_universe_df(), {}, {}, _sample_prices_df(), {},
             output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    select_group_start = html.index("function selectGroup(")
    select_group_end = html.index("/* ── 個股/族群搜尋 ── */")
    select_group_body = html[select_group_start:select_group_end]

    assert '"detail-three-col"' in select_group_body or "detail-three-col" in select_group_body
    assert "metaSpark" in select_group_body
    assert "chipsSum" in select_group_body
    assert "historyRecord" in select_group_body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_index_generator.py -k "three_column_grid" -v`
Expected: FAIL — `detail-three-col` doesn't exist yet.

- [ ] **Step 3: Wrap the three summary blocks**

In `export/index_generator.py`, find (inside `selectGroup()`, both branches use `${{metaSpark}}${{chipsSum}}${{historyRecord}}`):

```javascript
  if (!stocks.length) {{
    panel.innerHTML = `
      <div class="detail-head"><h3>${{safeName}}</h3><span class="dpct" style="color:${{pctColor}}">${{pctStr}}</span></div>
      <div class="detail-sub">▲${{meta.up_count}}檔 ▼${{meta.down_count}}檔</div>
      ${{metaSpark}}${{chipsSum}}${{historyRecord}}
      <div class="detail-empty">這個族群目前沒有個股行情資料。</div>`;
  }} else {{
    panel.innerHTML = `
      <div class="detail-head"><h3>${{safeName}}</h3><span class="dpct" style="color:${{pctColor}}">${{pctStr}}</span></div>
      <div class="detail-sub">▲${{meta.up_count}}檔 ▼${{meta.down_count}}檔　・　共 ${{stocks.length}} 檔</div>
      ${{metaSpark}}${{chipsSum}}${{historyRecord}}${{asofNote}}
      <div class="overflow-wrap"><table class="stock-list-table">
```

Change to:

```javascript
  if (!stocks.length) {{
    panel.innerHTML = `
      <div class="detail-head"><h3>${{safeName}}</h3><span class="dpct" style="color:${{pctColor}}">${{pctStr}}</span></div>
      <div class="detail-sub">▲${{meta.up_count}}檔 ▼${{meta.down_count}}檔</div>
      <div class="detail-three-col">
        <div class="tc-box">${{metaSpark}}</div>
        <div class="tc-box">${{chipsSum}}</div>
        <div class="tc-box">${{historyRecord}}</div>
      </div>
      <div class="detail-empty">這個族群目前沒有個股行情資料。</div>`;
  }} else {{
    panel.innerHTML = `
      <div class="detail-head"><h3>${{safeName}}</h3><span class="dpct" style="color:${{pctColor}}">${{pctStr}}</span></div>
      <div class="detail-sub">▲${{meta.up_count}}檔 ▼${{meta.down_count}}檔　・　共 ${{stocks.length}} 檔</div>
      <div class="detail-three-col">
        <div class="tc-box">${{metaSpark}}</div>
        <div class="tc-box">${{chipsSum}}</div>
        <div class="tc-box">${{historyRecord}}</div>
      </div>
      ${{asofNote}}
      <div class="overflow-wrap"><table class="stock-list-table">
```

(Only the two `panel.innerHTML` template literals change; the rest of the table markup below is untouched.)

- [ ] **Step 4: Add `.detail-three-col`/`.tc-box` CSS**

In `_CSS`, find:

```css
.meta-sparkline{margin:4px 0 10px;line-height:0}
.meta-sparkline svg{width:100%;height:auto;display:block;max-width:420px}
.chips-summary{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:14px;padding:8px 12px;background:var(--panel-2);border-radius:5px;font-size:.76rem}
```

Change to:

```css
.detail-three-col{display:grid;grid-template-columns:1fr 1fr 1.3fr;gap:12px;margin:10px 0 14px}
@media (max-width:768px){.detail-three-col{grid-template-columns:1fr}}
.tc-box{background:var(--panel-2);border-radius:5px;padding:10px 12px}
.meta-sparkline{margin:0;line-height:0}
.meta-sparkline svg{width:100%;height:auto;display:block}
.chips-summary{display:flex;flex-direction:column;gap:6px;flex-wrap:wrap;margin:0;padding:0;background:none;font-size:.76rem}
```

(`.meta-sparkline`'s `max-width:420px` is removed since it now fills its `.tc-box` column instead of the full panel width; `.chips-summary` drops its own background/padding since `.tc-box` now provides that container styling, and switches `flex-direction` to `column` so the chip rows stack vertically inside the narrower column instead of wrapping horizontally.)

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_index_generator.py -k "three_column_grid" -v`
Expected: PASS.

- [ ] **Step 6: Run the sparkline/chips-summary/history related tests to confirm no regressions**

Run: `python -m pytest tests/test_index_generator.py -k "sparkline or chips_summary or history_record or embeds_rank_history" -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index): 個股明細面板走勢/籌碼/歷史三區改並排三欄"
```

---

### Task 13: Full regression run + hand off browser verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -q`
Expected: `482 + <number of new tests added across Tasks 1-12> passed` — count them: Task1(+2) Task2(+3) Task3(+2) Task4(+2) Task5(+1) Task6(+1) Task7(+1) Task8(+1) Task9(+1) Task10(+1) Task11(+1) Task12(+1) = +17, so expect **499 passed**, 1 (pre-existing, unrelated) warning. If the actual new-test count differs (e.g. a step above needed an extra assertion split into two tests), that's fine — the key bar is: no FAILs, and the count only went up from 482.

- [ ] **Step 2: Spot-check the generated HTML by hand with a throwaway script**

Run a quick manual smoke check (not a pytest test — just confirms the whole `generate()` pipeline still produces valid output end-to-end with a slightly richer fixture than any single unit test):

```bash
python -c "
from datetime import date
import pandas as pd
from export.index_generator import generate

meta_perf = [{'meta_name': 'AI晶片', 'avg_change_pct': 5.66, 'up_count': 18, 'down_count': 3, 'flat_count': 0}]
universe_df = pd.DataFrame([{'stock_id': '2330', 'stock_name': '台積電', 'meta_sector': 'AI晶片'}])
prices_df = pd.DataFrame([{'stock_id': '2330', 'close': 1080.0, 'change_pct': 3.2}])
generate(date(2026, 8, 25), meta_perf, universe_df, {}, {}, prices_df, {}, output_path='/tmp/smoke_index.html')
print('OK — wrote /tmp/smoke_index.html, size:', __import__('os').path.getsize('/tmp/smoke_index.html'), 'bytes')
"
```

Expected: prints `OK — wrote /tmp/smoke_index.html, size: <N> bytes` with no traceback.

- [ ] **Step 3: Update `debug-tasks.md` per project workflow**

Per `CLAUDE.md`'s required workflow, append a new entry to `debug-tasks.md` (repo root) summarizing this plan's changes for the Debugger to verify. Use the template from `CLAUDE.md`:

```markdown
## [2026-08-25] 首頁（index.html）版面/視覺重設 — 13個Task全部完成

### 改了什麼
- 異動檔案：export/index_generator.py, processors/performance.py, main.py,
  tests/test_index_generator.py, tests/test_processors.py
- 邏輯說明：
  1. 版面重排：熱區格滿版置頂當主角；異動族群(已排序)+族群近況併成二欄次要區
  2. 異動族群加排序(burst優先,同kind比abs(pct))
  3. 視覺：超強tier熱區格加玻璃光暈(color-mix跟著--accent走,雙主題自動適配)，
     個股明細面板邊框改accent色
  4. 個股明細面板改錨定#heatgrid容器之後，不再插進tile網格中間打斷排列
  5. 面板內走勢/籌碼動向/歷史進榜三區改並排三欄(detail-three-col)
  6. 補齊4項已算好但沒接進面板的資料：自營商(dealer_net_today)、
     每週報酬%(weekly_returns)、大戶佔比+週變化(個股表格11→13欄)、
     外資/投信本週累計買賣超(近5交易日加總)

### 資料來源相關（如有異動）
- 上市資料（TWSE）：無異動，institutional/margin/shareholder表既有資料，未新增爬蟲
- 上櫃資料（TPEx）：同上，calc_meta_chips_signals()的per-stock/per-meta fallback邏輯未變動

### 請 Debugger 驗證
- [ ] 主要功能邏輯正確（尤其：dealer_net的SELECT修改是否影響production的institutional表查詢；
      shareholder_df在main.py是否正確接線，實際跑一次main.py確認docs/index.html有大戶佔比/週變化欄）
- [ ] 上市/上櫃資料來源沒有混用
- [ ] 沒有影響其他模組（chips.html/momentum.html/patterns.html的nav互連、既有功能）
- [ ] 瀏覽器實測（這台debug worktree可能沒有瀏覽器工具，若無工具請如實回報跳過）：
  - 熱區格41格排列完整、點擊展開的個股明細面板出現在熱區格下方(不再插進tile中間)
  - 三欄並排(走勢/籌碼動向/歷史進榜)版面正確、窄螢幕會改回垂直堆疊
  - 異動族群卡片排序正確(爆量暴衝排前面)
  - 深色/淺色主題切換，超強tier熱區格光暈兩個主題都合理(不是只深色能看)
  - **順便補測 2026-07-23 遺留的兩項舊欠款**：Tab focus + Enter/Space 鍵盤展開熱區格tile；
    手機版窄螢幕的secondary-row/三欄排版responsive行為

### 特別注意
- `docs/index.html` 是 generated artifact，不要手動編輯——下次 `python main.py` 跑過會被
  `export/index_generator.py` 重新產生的版本覆蓋。這次的所有改動都在 `export/index_generator.py`。
- `tests/test_processors.py::_seed_chips_db()` 的 institutional mock schema多加了 dealer_net
  欄位(預設0)，是backward-compatible的改動，所有既有呼叫端不用改。
- main.py 新增了第二次 `get_shareholder_top()` 呼叫(index.html用)，跟chips.html既有那次呼叫
  各自獨立(見Task5 Step5的說明)，這是刻意的取捨，不是遺漏。
```

- [ ] **Step 4: Commit the debug-tasks.md update**

```bash
git add debug-tasks.md
git commit -m "docs(debug-tasks): 交接首頁版面/視覺重設13個Task"
```

- [ ] **Step 5: Sync to debug worktree per CLAUDE.md workflow**

Per `CLAUDE.md`, check `../tw-sector-tracker-debug` is clean (no uncommitted changes) and merge master in:

```bash
cd ../tw-sector-tracker-debug
git status --short
```

If clean, run `git merge master`. If not clean, stop and confirm with Cody how to proceed before merging (per `CLAUDE.md`'s explicit instruction — do not overwrite uncommitted Debugger work).

---

## Plan Self-Review Notes

- **Spec coverage:** All 6 architecture items (①-⑥ including ⑥'s four sub-items a/b/c/d) map to Tasks 1-12. Task 13 covers the plan's own regression/hand-off requirements plus the two 2026-07-23 legacy verification items the spec explicitly folded in.
- **Discovered deviations from the spec's literal CSS, called out inline in their tasks:**
  - Task 10: the spec's starting-point CSS (`background:linear-gradient(...)`) would be silently overridden by the per-tile inline `style="background:{c['heat_bg']}"` already present on every `.heat-tile` — this plan drops the `background` line and keeps only `border-color`/`box-shadow`, using `color-mix(in srgb, var(--accent) N%, transparent)` instead of hardcoded `rgba(240,187,85,...)`. This is strictly better than the spec's own literal snippet at satisfying the spec's own dual-theme requirement (§③ "雙主題相容"), and the spec explicitly authorizes implementer discretion here ("作為起點...implementer可微調到位").
- **Type/name consistency check:** `dealer_net_today`, `foreign_net_week`, `trust_net_week`, `weekly_returns`, `holder_pct`, `holder_week_chg` are spelled identically across every task that touches them (Task 2's `calc_meta_chips_signals()` return dict → Task 3's `card_meta` → Task 7/8's JS reads them as `meta.dealer_net_today` etc.; Task 4's `build_stock_detail_data()` entry dict → Task 6's JS reads them as `s.holder_pct`/`s.holder_week_chg`).
- **No placeholders:** every step has literal code, not descriptions of code.
