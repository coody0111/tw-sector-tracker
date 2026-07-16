# 逆轟策略 v2 — 資料層 Implementation Plan（Plan 1/3）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依 v2 spec §6「資料與接口變更清單」，幫 `screener/signals.py` 三支既有函式新增證據欄位（全部向下相容、只加欄位不改既有判斷邏輯），供後續 Plan 2（觀察分）、Plan 3（generator+UI）消費。

**Architecture:** 四個獨立 Task，每個只動一支函式（或新增一個常數），互相不依賴、可任意順序執行、各自獨立 commit。全部沿用既有函式簽章與呼叫慣例，不新增參數、不改變回傳的股票集合（`scan_bullish_alignment_new_high`/`scan_consecutive_limit_up` 過濾邏輯不變，只是每筆多幾個欄位）。

**Tech Stack:** Python、DuckDB、pandas（既有依賴，無新套件）。

## Global Constraints

- 對照 spec：`docs/superpowers/specs/2026-07-16-momentum-strategy-page-v2-design.md`（下稱「v2 spec」）§3、§6。
- **只加欄位，不改變既有回傳的股票集合／既有欄位語意**——`scan_bullish_alignment_new_high()`/
  `scan_consecutive_limit_up()` 現有的價格命中判斷完全不動；`scan_momentum_health()` 的
  `exit_3_rule_triggered`/`entry_confirmed` 兩個既有欄位的計算邏輯完全不動，只是額外把它們的
  子條件個別欄位也回傳出去。
- **不做**族群觀察分（`calc_meta_observation_scores()`，另一個獨立 Plan 2）、不做 generator/UI
  （Plan 3）、不做 freshness 檢查（v2 spec 明講「在修正前由 generator 做降級顯示」，屬於 Plan 3）、
  不做 `scan_limit_up_unlocked()`（v2 spec §3.5b 已標記為「不阻擋 v2 其餘部分先落地，可以晚一點
  再做」，本次不排進來）。
- 每個 Task 完成後跑 `python -m pytest tests/test_signals.py -q` 確認沒有破壞既有測試（照專案
  慣例，這步留給 Debugger 驗證，實作階段用 hand-trace 或 subagent review 階段的實際執行代替）。

---

### Task 1: `scan_momentum_health()` 新增出場子條件、動能子條件、單日抗跌差、RS樣本數

**Files:**
- Modify: `screener/signals.py`（`scan_momentum_health()`，第189-403行）
- Test: `tests/test_signals.py`

**Interfaces:**
- Consumes: 無新依賴，沿用函式現有的 `price_df`/`universe_df`/`target`/`results` 中間變數。
- Produces: `scan_momentum_health()` 每筆回傳 dict 新增 6 個欄位：
  - `below_ma5`（bool）：`close < ma5`（出場三原則子條件1）
  - `big_black_proxy`（bool）：`change_pct <= _EXIT_BIG_BLACK_PCT`（出場三原則子條件3，v2 spec §3.3
    要求正名為「proxy」，不宣稱是完整K棒長黑判斷）
  - `ma5_rising`（bool）：今日 MA5 > 昨日 MA5（動能子條件，`entry_confirmed` 的組成之一）
  - `ma10_rising`（bool）：今日 MA10 > 昨日 MA10（動能子條件，`entry_confirmed` 的組成之一）
  - `daily_excess_pct`（float|None）：個股今日 `change_pct` − universe 今日等權平均 `change_pct`
    （v2 spec §3.1 新增欄位，修正原本誤用 5 日 `rs_market_score` 代替單日抗跌差的問題；universe
    今日無資料或個股今日缺值時回 `None`）
  - `rs_sample_count`（int）：該股所屬 `meta_sector` 當日有效算出 `rs_score` 的股票數（v2 spec §3.2
    RS 樣本信心分級的分母，`scan_momentum_health()` 直接算好，消費端不用重算）

`ma5_slope_down`（既有欄位，語意不變，等同新欄位命名習慣裡的「五日線下彎」，這裡不重複新增）。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_signals.py` 加入（放在既有 `test_scan_momentum_health_tier_bullish_but_weak_rs_is_weak`
之後、`test_scan_consecutive_limit_up_counts_streak` 之前）：

```python
def test_scan_momentum_health_exposes_exit_and_entry_sub_conditions(tmp_path):
    """出場三原則的三個子條件（below_ma5/ma5_slope_down/big_black_proxy）跟動能子條件
    （ma5_rising/ma10_rising）都要個別回傳，不只有合併後的 exit_3_rule_triggered/entry_confirmed。"""
    db_path = tmp_path / "test.db"
    dates = pd.date_range("2026-01-01", periods=66, freq="D")
    # 65 天穩定上升，最後一天重挫長黑跌破均線（觸發完整出場三原則）
    closes = [100.0 + i * 0.5 for i in range(65)] + [90.0]
    change_pcts = [0.3] * 65 + [-8.0]
    rows = [
        ("1101", d.strftime("%Y-%m-%d"), c, pct, 1000)
        for d, c, pct in zip(dates, closes, change_pcts)
    ]
    _seed_db(db_path, rows)

    results = scan_momentum_health(dates[-1].strftime("%Y-%m-%d"), db_path=str(db_path))

    assert len(results) == 1
    r = results[0]
    assert r["below_ma5"] is True
    assert r["big_black_proxy"] is True
    assert r["exit_3_rule_triggered"] is True  # 既有欄位不變
    assert r["ma5_rising"] is False
    assert r["ma10_rising"] is False


def test_scan_momentum_health_ma5_ma10_rising_true_when_uptrend(tmp_path):
    """穩定上升趨勢中，MA5/MA10 都該是 rising=True。"""
    db_path = tmp_path / "test.db"
    dates = pd.date_range("2026-01-01", periods=65, freq="D")
    rows = [("1101", d.strftime("%Y-%m-%d"), 100.0 + i * 0.5, 0.3, 1000)
            for i, d in enumerate(dates)]
    _seed_db(db_path, rows)

    results = scan_momentum_health(dates[-1].strftime("%Y-%m-%d"), db_path=str(db_path))

    assert results[0]["ma5_rising"] is True
    assert results[0]["ma10_rising"] is True
    assert results[0]["below_ma5"] is False
    assert results[0]["big_black_proxy"] is False


def test_scan_momentum_health_daily_excess_pct_uses_single_day_not_5day(tmp_path):
    """daily_excess_pct 必須用「今日」個股 change_pct 減「今日」universe 等權平均，
    不能誤用 5 日累積報酬（v2 spec §3.1 要修正的那個問題）。"""
    db_path = tmp_path / "test.db"
    dates = pd.date_range("2026-01-01", periods=65, freq="D")
    rows = []
    # 1101：前64天平淡(0.1%)，今日+3.0%（明顯跑贏大盤）
    for i, d in enumerate(dates[:-1]):
        rows.append(("1101", d.strftime("%Y-%m-%d"), 100.0 + i * 0.1, 0.1, 1000))
    rows.append(("1101", dates[-1].strftime("%Y-%m-%d"), 106.5, 3.0, 1000))
    # 1102：universe 對照組，今日 -1.0%（跟1101同族群，讓 universe 今日均值被拉低）
    for i, d in enumerate(dates[:-1]):
        rows.append(("1102", d.strftime("%Y-%m-%d"), 50.0 + i * 0.05, 0.1, 1000))
    rows.append(("1102", dates[-1].strftime("%Y-%m-%d"), 49.5, -1.0, 1000))
    _seed_db(db_path, rows)

    results = scan_momentum_health(dates[-1].strftime("%Y-%m-%d"), db_path=str(db_path))
    r1101 = next(r for r in results if r["stock_id"] == "1101")

    # universe 今日等權平均 = (3.0 + (-1.0)) / 2 = 1.0；daily_excess_pct = 3.0 - 1.0 = 2.0
    assert r1101["daily_excess_pct"] == 2.0


def test_scan_momentum_health_rs_sample_count_reflects_sector_size(tmp_path):
    """rs_sample_count 應該是同族群當日有效算出 rs_score 的股票數，不是全市場股票數。"""
    db_path = tmp_path / "test.db"
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "stock_id,stock_name,meta_sector\n"
        "1101,測試A,sectorA\n1102,測試B,sectorA\n1103,測試C,sectorB\n",
        encoding="utf-8",
    )
    dates = pd.date_range("2026-01-01", periods=65, freq="D")
    rows = []
    for sid in ["1101", "1102", "1103"]:
        for i, d in enumerate(dates):
            rows.append((sid, d.strftime("%Y-%m-%d"), 100.0 + i * 0.2, 0.2, 1000))
    _seed_db(db_path, rows)

    results = scan_momentum_health(
        dates[-1].strftime("%Y-%m-%d"), db_path=str(db_path), universe_path=str(universe_path)
    )

    r1101 = next(r for r in results if r["stock_id"] == "1101")
    r1103 = next(r for r in results if r["stock_id"] == "1103")
    assert r1101["rs_sample_count"] == 2  # sectorA 有 1101+1102 兩檔
    assert r1103["rs_sample_count"] == 1  # sectorB 只有 1103 一檔
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_signals.py::test_scan_momentum_health_exposes_exit_and_entry_sub_conditions tests/test_signals.py::test_scan_momentum_health_ma5_ma10_rising_true_when_uptrend tests/test_signals.py::test_scan_momentum_health_daily_excess_pct_uses_single_day_not_5day tests/test_signals.py::test_scan_momentum_health_rs_sample_count_reflects_sector_size -q`
Expected: FAIL（`KeyError: 'below_ma5'` 等，欄位不存在）

- [ ] **Step 3: 實作**

在 `screener/signals.py` 的 `scan_momentum_health()` 內，找到（第276-309行）：

```python
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
            "rs_market_score":       None,
            "strength_tier":         None,
        })
```

改成：

```python
        ma5_slope_down = ma5_today < ma5_yday
        ma5_rising = ma5_today > ma5_yday
        ma10_rising = ma10_today > ma10_yday

        today = window.iloc[-1]
        below_ma5 = bool(today["close"] < ma5_today)
        big_black_proxy = bool(today["change_pct"] <= _EXIT_BIG_BLACK_PCT)
        exit_3_rule_triggered = bool(below_ma5 and ma5_slope_down and big_black_proxy)
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
            "below_ma5":             below_ma5,
            "big_black_proxy":       big_black_proxy,
            "ma5_rising":            ma5_rising,
            "ma10_rising":           ma10_rising,
            "exit_3_rule_triggered": exit_3_rule_triggered,
            "entry_confirmed":       entry_confirmed,
            "rs_score":              None,
            "rs_rank_pct":           None,
            "rs_market_score":       None,
            "rs_sample_count":       0,
            "daily_excess_pct":      None,
            "strength_tier":         None,
        })
```

再來，找到（第340-374行，「大盤」基準區塊，緊接在 `market_cum5` 計算之後）：

```python
    # 「大盤」基準 = universe 等權平均近5日累積報酬（不用 TAIEX 加權指數——universe 只有
    # 追蹤的電子科技股，跟涵蓋全市場的 TAIEX 不是同一個母體，混用會有 apples-to-oranges 問題）。
    # 只用有在 universe 裡的股票，跟族群基準同一套母體。
    universe_ids = set(universe_df["stock_id"].astype(str))
    market_df = price_df[price_df["stock_id"].astype(str).isin(universe_ids) & (price_df["date"] <= target)]
    market_cum5 = None
    market_dates = sorted(market_df["date"].unique())
    if len(market_dates) >= _RS_WINDOW_DAYS:
        last_n = market_dates[-_RS_WINDOW_DAYS:]
        daily_avg = market_df[market_df["date"].isin(last_n)].groupby("date")["change_pct"].mean()
        factor = 1.0
        for d in last_n:
            pct = daily_avg.get(d)
            if pct is not None and pd.notna(pct):
                factor *= (1 + float(pct) / 100)
        market_cum5 = round((factor - 1) * 100, 2)
```

在這段之後（緊接著，`for row in results:` 迴圈之前）新增單日大盤基準計算：

```python
    # 「今日」大盤基準（v2 spec §3.1 daily_excess_pct，跟上面的5日 market_cum5 是不同週期，
    # 不能混用——這裡只取 target 當天 universe 等權平均，不做5日累積）。
    today_market_df = market_df[market_df["date"] == target]
    market_today_avg_pct = None
    if not today_market_df.empty:
        avg_val = today_market_df["change_pct"].mean()
        if pd.notna(avg_val):
            market_today_avg_pct = float(avg_val)
```

找到（第358-374行，個股 5日 RS 計算迴圈）：

```python
    for row in results:
        sid = row["stock_id"]
        grp = price_df[(price_df["stock_id"] == sid) & (price_df["date"] <= target)]
        cum5_window = grp.sort_values("date").tail(_RS_WINDOW_DAYS)
        if len(cum5_window) < _RS_WINDOW_DAYS:
            continue  # rs_score/rs_market_score 保持 None

        factor = 1.0
        for pct in cum5_window["change_pct"]:
            factor *= (1 + float(pct) / 100)
        stock_cum5 = round((factor - 1) * 100, 2)

        sector_cum5 = sector_cum5_map.get(row["meta_sector"])
        if sector_cum5 is not None:
            row["rs_score"] = round(stock_cum5 - sector_cum5, 2)
        if market_cum5 is not None:
            row["rs_market_score"] = round(stock_cum5 - market_cum5, 2)
```

改成（新增 `daily_excess_pct` 計算，注意這段要放在迴圈最上面、`continue` 之前，因為
`daily_excess_pct` 是單日資料，不受 5日視窗不足的限制而跳過）：

```python
    for row in results:
        sid = row["stock_id"]
        if market_today_avg_pct is not None:
            row["daily_excess_pct"] = round(row["change_pct"] - market_today_avg_pct, 2)

        grp = price_df[(price_df["stock_id"] == sid) & (price_df["date"] <= target)]
        cum5_window = grp.sort_values("date").tail(_RS_WINDOW_DAYS)
        if len(cum5_window) < _RS_WINDOW_DAYS:
            continue  # rs_score/rs_market_score 保持 None

        factor = 1.0
        for pct in cum5_window["change_pct"]:
            factor *= (1 + float(pct) / 100)
        stock_cum5 = round((factor - 1) * 100, 2)

        sector_cum5 = sector_cum5_map.get(row["meta_sector"])
        if sector_cum5 is not None:
            row["rs_score"] = round(stock_cum5 - sector_cum5, 2)
        if market_cum5 is not None:
            row["rs_market_score"] = round(stock_cum5 - market_cum5, 2)
```

最後，找到（第376-384行，`rs_rank_pct` 計算）：

```python
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

改成（新增 `rs_sample_count`，用同一個 `rs_df`／`valid` 遮罩算每個族群的有效樣本數）：

```python
    rs_df = pd.DataFrame(results)
    valid = rs_df["rs_score"].notna()
    if valid.any():
        rs_df.loc[valid, "rs_rank_pct"] = (
            rs_df.loc[valid].groupby("meta_sector")["rs_score"].rank(pct=True, ascending=True)
        )
        sample_counts = rs_df.loc[valid].groupby("meta_sector")["rs_score"].transform("count")
        rs_df.loc[valid, "rs_sample_count"] = sample_counts
    for i, row in enumerate(results):
        val = rs_df.loc[i, "rs_rank_pct"]
        row["rs_rank_pct"] = None if pd.isna(val) else round(float(val), 3)
        count_val = rs_df.loc[i, "rs_sample_count"]
        row["rs_sample_count"] = int(count_val) if pd.notna(count_val) else 0
```

同時更新函式 docstring（第206-219行）的 Returns 段落，把 6 個新欄位加進去：

```python
    Returns
    -------
    list of dict，每筆含：
        stock_id, stock_name, meta_sector, close, change_pct,
        ma5, ma10, ma20, ma60,
        ma_alignment ("多頭排列"/"空頭排列"/"糾結"),
        ma5_slope_down (bool)，          ← 出場子條件：五日線下彎
        below_ma5 (bool)，               ← 出場子條件：跌破五日線（v2新增）
        big_black_proxy (bool)，         ← 出場子條件：重挫proxy，非完整K棒長黑判斷（v2新增）
        ma5_rising (bool)，              ← 動能子條件：MA5上揚（v2新增）
        ma10_rising (bool)，             ← 動能子條件：MA10上揚（v2新增）
        exit_3_rule_triggered (bool)，   ← (1)below_ma5 (2)ma5_slope_down (3)big_black_proxy 三者同時成立
        entry_confirmed (bool)，         ← 多頭排列 + ma5_rising + ma10_rising
        rs_score (float|None)，          ← 個股5日報酬 - 族群5日平均報酬
        rs_rank_pct (float|None)，       ← 族群內百分位排名，1.0=最強
        rs_market_score (float|None)，   ← 個股5日報酬 - universe 等權平均5日報酬（vs 大盤，5日週期）
        daily_excess_pct (float|None)，  ← 個股今日漲跌% - universe 今日等權平均漲跌%（單日週期，v2新增，
                                            不可與 rs_market_score 混用，見設計 spec §3.1）
        rs_sample_count (int)，          ← 同族群當日有效算出 rs_score 的股票數（v2新增，RS樣本信心分母）
        strength_tier                    ← 超強/強/整理/弱/超弱
    """
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_signals.py::test_scan_momentum_health_exposes_exit_and_entry_sub_conditions tests/test_signals.py::test_scan_momentum_health_ma5_ma10_rising_true_when_uptrend tests/test_signals.py::test_scan_momentum_health_daily_excess_pct_uses_single_day_not_5day tests/test_signals.py::test_scan_momentum_health_rs_sample_count_reflects_sector_size -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add screener/signals.py tests/test_signals.py
git commit -m "feat(signals): scan_momentum_health 新增出場/動能子條件+daily_excess_pct+rs_sample_count（v2 spec §3.1/§3.2/§3.3）"
```

---

### Task 2: `scan_bullish_alignment_new_high()`（B3）新增量能確認標記

**Files:**
- Modify: `screener/signals.py`（`scan_bullish_alignment_new_high()`，第494-601行）
- Test: `tests/test_signals.py`

**Interfaces:**
- Consumes: 無新依賴。**現有的價格命中判斷完全不動**（v2 spec §3.4：「只加標記，不改既有價格
  命中集合」）。
- Produces: 每筆回傳 dict 新增 2 個欄位：
  - `volume_ratio_20d`（float|None）：今日成交量 / 今日之前20個交易日均量；不足20天回 `None`
  - `volume_confirmed`（bool|None）：`volume_ratio_20d >= 1.5`；`volume_ratio_20d` 為 `None` 時
    這欄也是 `None`（無法判斷，不猜）

門檻 1.5 沿用專案既有慣例（`scan_volume_turnover()`/`detect_breakout_confirm()` 皆用同一數字），
不另外發明新門檻。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_signals.py` 加入（放在既有 `test_scan_bullish_alignment_new_high_skips_insufficient_history`
之後）：

```python
def test_scan_bullish_alignment_new_high_flags_volume_confirmed(tmp_path):
    """今日量 >= 前20日均量*1.5 時 volume_confirmed=True；量沒跟上時 False；
    現有的多頭排列+創新高判斷完全不受影響（不從清單剔除量沒確認的股票）。"""
    db_path = tmp_path / "test.db"
    dates = pd.date_range("2026-01-01", periods=60, freq="D")

    rows = []
    # 1101：60天穩定上升，前20天(index 39-58)量都1000，今日(index59)量衝到2000（>=1500門檻）
    close_1101 = [100 + i for i in range(60)]
    for i, (d, c) in enumerate(zip(dates, close_1101)):
        vol = 2000 if i == 59 else 1000
        rows.append(("1101", d.strftime("%Y-%m-%d"), float(c), 0.5, vol))

    # 1104：60天穩定上升(跟1101同型態，確保會被判多頭排列+創新高)，但今日量只有1100（<1500門檻）
    close_1104 = [200 + i * 0.5 for i in range(60)]
    for i, (d, c) in enumerate(zip(dates, close_1104)):
        vol = 1100 if i == 59 else 1000
        rows.append(("1104", d.strftime("%Y-%m-%d"), float(c), 0.3, vol))

    _seed_db(db_path, rows)

    results = scan_bullish_alignment_new_high(dates[-1].strftime("%Y-%m-%d"), db_path=str(db_path))
    ids = [r["stock_id"] for r in results]

    assert "1101" in ids and "1104" in ids, "量能標記不該影響既有的價格命中集合"
    r1101 = next(r for r in results if r["stock_id"] == "1101")
    r1104 = next(r for r in results if r["stock_id"] == "1104")
    assert r1101["volume_ratio_20d"] == 2.0
    assert r1101["volume_confirmed"] is True
    assert r1104["volume_confirmed"] is False


def test_scan_bullish_alignment_new_high_volume_confirmed_none_when_insufficient_history(tmp_path):
    """理論上不會發生（min_history 已保證>=60天，遠超20天量能窗口），但仍驗證邊界防呆行為，
    確認函式不會對『資料不足』的情況猜一個 True/False。"""
    db_path = tmp_path / "test.db"
    rows = [("1101", f"2026-01-{d:02d}", 100.0 + d, 0.1, 1000) for d in range(1, 30)]
    _seed_db(db_path, rows)

    results = scan_bullish_alignment_new_high("2026-01-29", db_path=str(db_path))

    assert results == []  # 歷史不足60天，既有邏輯本來就會跳過，這裡確認沒有因為新增邏輯而 crash
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_signals.py::test_scan_bullish_alignment_new_high_flags_volume_confirmed tests/test_signals.py::test_scan_bullish_alignment_new_high_volume_confirmed_none_when_insufficient_history -q`
Expected: FAIL（`KeyError: 'volume_ratio_20d'`）

- [ ] **Step 3: 實作**

在 `screener/signals.py` 找到（第37-38行，B3常數區塊），新增量能門檻常數：

```python
# 通用多頭排列＋創新高掃描常數（動能派筆記十一/四十五；mapping spec B3）
_DEFAULT_LOOKBACK_DAYS = 60  # 「創新高」比較窗口，約一季（波段新高，非歷史新高，理由見統整 spec）
_B3_VOLUME_MULTIPLE = 1.5     # 量能確認門檻（v2 spec §3.4），沿用 scan_volume_turnover 既有慣例
_B3_VOLUME_LOOKBACK_DAYS = 20  # 量能確認的均量比較窗口
```

找到（第534-541行）：

```python
    con = duckdb.connect(db_path, read_only=True)
    price_df = con.execute(f"""
        SELECT stock_id, date, close, change_pct
        FROM daily_prices
        WHERE date <= '{trade_date}'
        ORDER BY stock_id, date
    """).df()
    con.close()
```

改成（SELECT 加入 `volume`）：

```python
    con = duckdb.connect(db_path, read_only=True)
    price_df = con.execute(f"""
        SELECT stock_id, date, close, change_pct, volume
        FROM daily_prices
        WHERE date <= '{trade_date}'
        ORDER BY stock_id, date
    """).df()
    con.close()
```

找到（第579-596行）：

```python
        prior_window = close.iloc[-lookback_days:-1]
        if prior_window.empty or today_close <= prior_window.max():
            continue

        today_row = window.iloc[-1]
        change_pct = today_row.get("change_pct")
        uinfo = universe_map.get(str(sid), {})
        results.append({
            "stock_id":      sid,
            "stock_name":    uinfo.get("stock_name", ""),
            "meta_sector":   uinfo.get("meta_sector", ""),
            "close":         today_close,
            "change_pct":    float(change_pct) if pd.notna(change_pct) else None,
            "ma5":           round(float(ma5), 2),
            "ma10":          round(float(ma10), 2),
            "ma60":          round(float(ma60), 2),
            "lookback_days": lookback_days,
        })
```

改成：

```python
        prior_window = close.iloc[-lookback_days:-1]
        if prior_window.empty or today_close <= prior_window.max():
            continue

        volume = window["volume"]
        today_volume = float(volume.iloc[-1])
        prior_vol_window = volume.iloc[-(_B3_VOLUME_LOOKBACK_DAYS + 1):-1]
        if len(prior_vol_window) < _B3_VOLUME_LOOKBACK_DAYS:
            volume_ratio_20d = None
            volume_confirmed = None
        else:
            avg_vol = prior_vol_window.mean()
            if avg_vol > 0:
                volume_ratio_20d = round(today_volume / avg_vol, 2)
                volume_confirmed = bool(volume_ratio_20d >= _B3_VOLUME_MULTIPLE)
            else:
                volume_ratio_20d = None
                volume_confirmed = None

        today_row = window.iloc[-1]
        change_pct = today_row.get("change_pct")
        uinfo = universe_map.get(str(sid), {})
        results.append({
            "stock_id":         sid,
            "stock_name":       uinfo.get("stock_name", ""),
            "meta_sector":      uinfo.get("meta_sector", ""),
            "close":            today_close,
            "change_pct":       float(change_pct) if pd.notna(change_pct) else None,
            "ma5":              round(float(ma5), 2),
            "ma10":             round(float(ma10), 2),
            "ma60":             round(float(ma60), 2),
            "lookback_days":    lookback_days,
            "volume_ratio_20d": volume_ratio_20d,
            "volume_confirmed": volume_confirmed,
        })
```

同時更新函式 docstring（第528-532行）：

```python
    Returns
    -------
    list of dict，只回傳「多頭排列 且 創新高」都成立的股票，依 change_pct 降序：
        stock_id, stock_name, meta_sector, close, change_pct,
        ma5, ma10, ma60, lookback_days,
        volume_ratio_20d (float|None)，  ← 今日量/前20日均量，v2新增（不足20日回None）
        volume_confirmed (bool|None)     ← volume_ratio_20d >= 1.5，v2新增，純標記不過濾清單
    """
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_signals.py::test_scan_bullish_alignment_new_high_flags_volume_confirmed tests/test_signals.py::test_scan_bullish_alignment_new_high_volume_confirmed_none_when_insufficient_history tests/test_signals.py::test_scan_bullish_alignment_new_high_filters_correctly tests/test_signals.py::test_scan_bullish_alignment_new_high_lookback_days_changes_boundary -q`
Expected: PASS（含既有兩個測試，確認沒有破壞既有的價格命中判斷）

- [ ] **Step 5: Commit**

```bash
git add screener/signals.py tests/test_signals.py
git commit -m "feat(signals): scan_bullish_alignment_new_high(B3) 新增量能確認標記，不改既有價格命中集合（v2 spec §3.4）"
```

---

### Task 3: `scan_consecutive_limit_up()`（B5）新增起漲日量能確認 + 新增跌停常數

**Files:**
- Modify: `screener/signals.py`（`scan_consecutive_limit_up()`，第406-491行；常數區塊第35行）
- Test: `tests/test_signals.py`

**Interfaces:**
- Consumes: 無新依賴，沿用函式現有的 `price_df`/`streak`/`i`（迴圈變數，連板起點索引為 `i+1`）。
- Produces：
  - 新增模組常數 `_LIMIT_DOWN_PCT = -9.5`（v2 spec §3.6，跌停判斷，只供風險標記使用）
  - `scan_consecutive_limit_up()` 回傳每筆新增 `breakout_volume_confirmed`（`bool | None`）：
    連板起點當天量 ≥ 起點前20個交易日均量×1.5 → `True`；量沒跟上 → `False`；起點前歷史不足
    20個交易日 → `None`

這個 Task 的算法設計跟 v1 舊 plan（已作廢的 `2026-07-16-momentum-strategy-page.md` Task 1）完全
相同——v1→v2 的轉變只影響「怎麼呈現」（命令式文案→證據標籤），不影響「這個資料本身該怎麼算」，
所以這裡直接沿用同一套已經設計過的算法，不重新發明。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_signals.py` 加入（放在既有 `test_scan_consecutive_limit_up_single_day_streak_has_none_volume_trend`
之後）：

```python
def test_scan_consecutive_limit_up_flags_breakout_volume_confirmed(tmp_path):
    """連板起點那天（第一根漲停）若量 >= 前20日均量*1.5，breakout_volume_confirmed=True；
    量不夠則 False。用兩檔股票對照：AAAA 起漲日爆量、BBBB 起漲日量平淡。"""
    db_path = tmp_path / "test.db"
    rows = []
    for d in range(1, 21):
        rows.append(("AAAA", f"2026-06-{d:02d}", 100.0, 0.5, 1000))
    rows += [
        ("AAAA", "2026-07-12", 110.0, 9.8, 3000),
        ("AAAA", "2026-07-13", 121.0, 10.0, 2500),
        ("AAAA", "2026-07-14", 133.1, 10.0, 2000),
    ]
    for d in range(1, 21):
        rows.append(("BBBB", f"2026-06-{d:02d}", 50.0, 0.5, 1000))
    rows += [
        ("BBBB", "2026-07-12", 55.0, 9.8, 1100),
        ("BBBB", "2026-07-13", 60.5, 10.0, 900),
        ("BBBB", "2026-07-14", 66.5, 10.0, 800),
    ]
    _seed_db(db_path, rows)

    results = scan_consecutive_limit_up("2026-07-14", db_path=str(db_path))

    a = next(r for r in results if r["stock_id"] == "AAAA")
    b = next(r for r in results if r["stock_id"] == "BBBB")
    assert a["breakout_volume_confirmed"] is True
    assert b["breakout_volume_confirmed"] is False


def test_scan_consecutive_limit_up_breakout_volume_none_when_insufficient_history(tmp_path):
    """連板起點前歷史不足20個交易日（新股）時，breakout_volume_confirmed 應為 None。"""
    db_path = tmp_path / "test.db"
    rows = [
        ("CCCC", "2026-07-08", 50.0, 0.5, 1000),
        ("CCCC", "2026-07-09", 50.2, 0.5, 1000),
        ("CCCC", "2026-07-10", 50.5, 0.5, 1000),
        ("CCCC", "2026-07-11", 50.8, 0.5, 1000),
        ("CCCC", "2026-07-12", 55.0, 9.8, 3000),
        ("CCCC", "2026-07-13", 60.5, 10.0, 2500),
        ("CCCC", "2026-07-14", 66.5, 10.0, 2000),
    ]
    _seed_db(db_path, rows)

    results = scan_consecutive_limit_up("2026-07-14", db_path=str(db_path))

    assert results[0]["breakout_volume_confirmed"] is None
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_signals.py::test_scan_consecutive_limit_up_flags_breakout_volume_confirmed tests/test_signals.py::test_scan_consecutive_limit_up_breakout_volume_none_when_insufficient_history -q`
Expected: FAIL（`KeyError: 'breakout_volume_confirmed'`）

- [ ] **Step 3: 實作**

在 `screener/signals.py` 找到（第35行）：

```python
_LIMIT_UP_PCT = 9.5   # 漲停判定門檻，沿用 scan_volume_turnover 既有慣例（見設計文件資料正確性風險）
```

改成（新增跌停常數 + B5起漲量能常數）：

```python
_LIMIT_UP_PCT = 9.5   # 漲停判定門檻，沿用 scan_volume_turnover 既有慣例（見設計文件資料正確性風險）
_LIMIT_DOWN_PCT = -9.5  # 跌停判定門檻（v2 spec §3.6），只供「跌停風險」標記用，不產生放空/立刻砍指令
_B5_BREAKOUT_VOL_MULTIPLE = 1.5    # 連板起漲日量能確認門檻，沿用專案既有 1.5 倍慣例
_B5_BREAKOUT_VOL_LOOKBACK_DAYS = 20  # 起漲日均量比較窗口
```

在 `scan_consecutive_limit_up()` 內，找到（`volume_declining_streak` 計算區塊之後、`uinfo = ...`
之前）：

```python
        # 量縮鎖死判斷（筆記：惜售最強）：連板期間成交量逐日遞減或持平（舊→新）。
        # streak 天數對應的列是 [i+1, today_idx]（含頭尾，已按日期升冪排序）。
        volume_declining_streak = None
        if streak >= 2:
            streak_vols = grp.iloc[i + 1: today_idx + 1]["volume"].tolist()
            volume_declining_streak = all(
                streak_vols[k] <= streak_vols[k - 1] for k in range(1, len(streak_vols))
            )

        uinfo = universe_map.get(str(sid), {})
        results.append({
            "stock_id":                sid,
            "stock_name":              uinfo.get("stock_name", ""),
            "meta_sector":             uinfo.get("meta_sector", ""),
            "close":                   float(today["close"]),
            "change_pct":              float(today["change_pct"]),
            "volume":                  int(today["volume"]),
            "limit_up_streak":         streak,
            "volume_declining_streak": volume_declining_streak,
        })
```

改成：

```python
        # 量縮鎖死判斷（筆記：惜售最強）：連板期間成交量逐日遞減或持平（舊→新）。
        # streak 天數對應的列是 [i+1, today_idx]（含頭尾，已按日期升冪排序）。
        volume_declining_streak = None
        if streak >= 2:
            streak_vols = grp.iloc[i + 1: today_idx + 1]["volume"].tolist()
            volume_declining_streak = all(
                streak_vols[k] <= streak_vols[k - 1] for k in range(1, len(streak_vols))
            )

        # 連板起漲日量能確認（筆記四十五：起漲沒出量=假突破機率高，不追）。
        # 跟 volume_declining_streak 是不同階段的量能訊號：這個看「起點那天」相對它自己
        # 20日均量是否放量，不是看連板期間日與日之間的相對變化。
        breakout_start_idx = i + 1
        pre_breakout = grp.iloc[max(0, breakout_start_idx - _B5_BREAKOUT_VOL_LOOKBACK_DAYS): breakout_start_idx]
        if len(pre_breakout) < _B5_BREAKOUT_VOL_LOOKBACK_DAYS:
            breakout_volume_confirmed = None
        else:
            pre_avg_vol = pre_breakout["volume"].mean()
            breakout_day_vol = grp.iloc[breakout_start_idx]["volume"]
            breakout_volume_confirmed = bool(
                pre_avg_vol > 0 and breakout_day_vol >= pre_avg_vol * _B5_BREAKOUT_VOL_MULTIPLE
            )

        uinfo = universe_map.get(str(sid), {})
        results.append({
            "stock_id":                  sid,
            "stock_name":                uinfo.get("stock_name", ""),
            "meta_sector":               uinfo.get("meta_sector", ""),
            "close":                     float(today["close"]),
            "change_pct":                float(today["change_pct"]),
            "volume":                    int(today["volume"]),
            "limit_up_streak":           streak,
            "volume_declining_streak":   volume_declining_streak,
            "breakout_volume_confirmed": breakout_volume_confirmed,
        })
```

同時更新函式 docstring（第417-424行）的 Returns 段落：

```python
    Returns
    -------
    list of dict，依 limit_up_streak 降冪排列，每筆含：
        stock_id, stock_name, meta_sector, close, change_pct, volume,
        limit_up_streak (連續鎖漲停天數，今天算第1天),
        volume_declining_streak (bool|None，連板期間量是否逐日遞減/持平；
                                  streak<2 時為 None),
        breakout_volume_confirmed (bool|None，連板起點當天量是否 >= 起點前20個交易日
                                    均量*1.5；起點前歷史不足20日時為 None，v2新增)
    """
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_signals.py::test_scan_consecutive_limit_up_flags_breakout_volume_confirmed tests/test_signals.py::test_scan_consecutive_limit_up_breakout_volume_none_when_insufficient_history -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add screener/signals.py tests/test_signals.py
git commit -m "feat(signals): scan_consecutive_limit_up(B5) 新增起漲量能確認 + 新增_LIMIT_DOWN_PCT常數（v2 spec §3.5/§3.6）"
```

---

## Self-Review（對照 v2 spec §6 逐項檢查）

- **`scan_momentum_health()`**：spec 列的「新增出場三條件子欄位、ma5_rising、ma10_rising、
  daily_excess_pct、RS 樣本數」六項，Task 1 全部覆蓋（`below_ma5`/`big_black_proxy` 對應「出場
  三條件子欄位」的另兩條，`ma5_slope_down` 本來就已經是既有欄位，一併在 docstring 註記清楚）。
- **`scan_bullish_alignment_new_high()`**：spec 要求「讀取volume，新增volume_ratio_20d、
  volume_confirmed，不改變既有價格命中集合」，Task 2 完整覆蓋，且新增測試明確驗證「既有價格
  命中集合不受影響」（`test_scan_bullish_alignment_new_high_flags_volume_confirmed` 斷言
  `"1101" in ids and "1104" in ids`）。
- **`scan_consecutive_limit_up()`**：spec 要求「新增breakout_volume_confirmed」，Task 3 覆蓋，
  算法沿用已經設計過、未實作的舊 v1 plan 內容，不是重新發明。
- **`_LIMIT_DOWN_PCT`**：spec §3.6 要求新增，Task 3 一併完成，放在跟 `_LIMIT_UP_PCT` 同一個
  常數區塊，對稱命名。
- **明確排除的項目**（`calc_meta_observation_scores()`、freshness 檢查、generator/UI、
  `scan_limit_up_unlocked()`）：都沒有出現在這 3 個 Task 裡，確認沒有範圍外溢。

## No Placeholder 掃描

三個 Task 的程式碼區塊都是可以直接貼上執行的完整程式碼，測試斷言皆為具體數值比對（例如
`assert r1101["daily_excess_pct"] == 2.0`，不是「add assertion here」這種空泛寫法）。

## Type Consistency 掃描

- Task 1 新增的 6 個欄位名稱（`below_ma5`/`big_black_proxy`/`ma5_rising`/`ma10_rising`/
  `daily_excess_pct`/`rs_sample_count`）跟 v2 spec §3.3/§3.1/§3.2 用的欄位名稱逐字核對一致。
- Task 2 的 `volume_ratio_20d`/`volume_confirmed` 跟 v2 spec §3.4 用的欄位名稱一致。
- Task 3 的 `breakout_volume_confirmed` 跟 v2 spec §3.5 用的欄位名稱一致，跟已作廢的 v1 plan
  用的名稱也一致（同一個資料概念，不因為 v1→v2 改名）。
- `_LIMIT_DOWN_PCT` 常數名稱跟 v2 spec §3.6 給的名稱完全一致。
