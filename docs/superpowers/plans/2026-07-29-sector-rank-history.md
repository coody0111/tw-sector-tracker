# 族群排名歷史：排名進出榜＋歷史出現紀錄 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 `docs/index.html`（族群總覽頁）新增兩個功能：頁面層級「排名進出榜」（族群近況新子類別，列出這週剛跨過前10名門檻進榜/掉出榜的族群）跟單一族群「歷史出現紀錄」（點進族群詳細面板看到近5週精確排名軌跡＋文字摘要）。

**Architecture:** 新增一個純函式 `calc_meta_rank_history()`（`processors/performance.py`）即時從 `daily_prices` 全歷史用目前的族群分類算出每個 meta_sector 近N週（5交易日滾動視窗為一週）的排名，不存快照表。`export/index_generator.py` 新增 `find_rank_crossings()` 比較本週/上週排名產生進出榜清單，掛進 `build_sector_recap()` 的回傳字典；同時把每個族群的排名歷史塞進既有的 `card_meta`（JS 端 `CARD_META` 物件），供 `selectGroup()` 點開族群時渲染「歷史出現紀錄」區塊。

**Tech Stack:** Python (pandas, duckdb), pytest, 純字串樣板產生的 HTML/CSS/JS（沒有前端框架）。

---

### Task 1: `calc_meta_rank_history()` 純函式

**Files:**
- Modify: `processors/performance.py`
- Test: `tests/test_processors.py`

這支函式即時從 `daily_prices` 全歷史算出每個 meta_sector 近N週（預設5週，每週=5個交易日滾動視窗）的排名歷史。跟 `calc_meta_heatgrid_windows()` 同一個檔案、同樣的 pivot 模式（見該函式在 `processors/performance.py` 第934行附近），但這裡不是算 streak/加速度，是算「每一週跟其他全部 meta_sector 比較後的名次」。

- [ ] **Step 1: 寫失敗測試 — 基本排名正確性**

在 `tests/test_processors.py` 檔案最後面加：

```python
import duckdb
from processors.performance import calc_meta_rank_history


def _seed_rank_history_db(db_path, price_rows):
    """price_rows: list of (stock_id, date, change_pct)"""
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, change_pct DOUBLE)")
    con.executemany("INSERT INTO daily_prices VALUES (?, ?, ?)", price_rows)
    con.close()


def test_calc_meta_rank_history_ranks_metas_by_weekly_compound_return(tmp_path):
    """3個族群、剛好1週(5個交易日)資料：每天固定漲跌%，驗證複利報酬排序正確，
    本週排名=1的族群in_top10_this_week應為True。"""
    db_path = tmp_path / "test.db"
    rows = []
    for d in range(1, 6):  # 5天
        rows.append(("A1", f"2026-06-{d:02d}", 3.0))   # 族群A：每天+3%
        rows.append(("B1", f"2026-06-{d:02d}", 1.0))   # 族群B：每天+1%
        rows.append(("C1", f"2026-06-{d:02d}", -2.0))  # 族群C：每天-2%
    _seed_rank_history_db(db_path, rows)
    universe = pd.DataFrame([
        {"stock_id": "A1", "meta_sector": "族群A"},
        {"stock_id": "B1", "meta_sector": "族群B"},
        {"stock_id": "C1", "meta_sector": "族群C"},
    ])

    result = calc_meta_rank_history(universe, db_path=str(db_path), weeks_back=5)

    assert result["族群A"]["weekly_ranks"] == [1]
    assert result["族群B"]["weekly_ranks"] == [2]
    assert result["族群C"]["weekly_ranks"] == [3]
    assert result["族群A"]["in_top10_this_week"] is True
    assert result["族群C"]["in_top10_this_week"] is True  # 只有3個族群，前10名門檻涵蓋全部


def test_calc_meta_rank_history_uses_current_classification_not_historical(tmp_path):
    """驗證ADR-0001的核心承諾：排名一律用『現在傳進來的』universe_df分類回推，不管
    歷史上這支股票曾經屬於哪個族群——同一批價格資料，換一個universe_df(股票改分類)，
    排名歷史應該跟著變。"""
    db_path = tmp_path / "test.db"
    rows = [("X1", f"2026-06-{d:02d}", 5.0) for d in range(1, 6)]
    _seed_rank_history_db(db_path, rows)

    universe_old = pd.DataFrame([{"stock_id": "X1", "meta_sector": "舊分類族群"}])
    universe_new = pd.DataFrame([{"stock_id": "X1", "meta_sector": "新分類族群"}])

    result_old = calc_meta_rank_history(universe_old, db_path=str(db_path), weeks_back=5)
    result_new = calc_meta_rank_history(universe_new, db_path=str(db_path), weeks_back=5)

    assert "舊分類族群" in result_old and "新分類族群" not in result_old
    assert "新分類族群" in result_new and "舊分類族群" not in result_new
    assert result_new["新分類族群"]["weekly_ranks"] == result_old["舊分類族群"]["weekly_ranks"]


def test_calc_meta_rank_history_counts_consecutive_top10_streak(tmp_path):
    """3週資料，某族群連續3週都是排名第1(前10)：consecutive_weeks_in_top10應為3。"""
    db_path = tmp_path / "test.db"
    rows = []
    for d in range(1, 16):  # 15天 = 3週
        rows.append(("A1", f"2026-06-{d:02d}", 3.0))   # 永遠第一
        rows.append(("B1", f"2026-06-{d:02d}", 1.0))
    _seed_rank_history_db(db_path, rows)
    universe = pd.DataFrame([
        {"stock_id": "A1", "meta_sector": "常勝族群"},
        {"stock_id": "B1", "meta_sector": "普通族群"},
    ])

    result = calc_meta_rank_history(universe, db_path=str(db_path), weeks_back=5)

    assert result["常勝族群"]["weekly_ranks"] == [1, 1, 1]
    assert result["常勝族群"]["in_top10_this_week"] is True
    assert result["常勝族群"]["consecutive_weeks_in_top10"] == 3


def test_calc_meta_rank_history_last_top10_week_when_not_currently_ranked(tmp_path):
    """12個族群(1個主角+11個陪榜)、4週資料：族群總數>10，前10名門檻才有意義。
    主角族群前2週表現最強(排名1)，後2週表現墊底(排名12，掉出前10)。驗證not
    in_top10_this_week時，能回頭找出「最近一次進前10是第幾週、當時排第幾名」。"""
    db_path = tmp_path / "test.db"
    rows = []
    for d in range(1, 21):  # 20天 = 4週
        rows.append(("A1", f"2026-06-{d:02d}", 5.0))
    for d in range(1, 21):
        # 11個陪榜族群，確保族群總數是12個(>10)，這樣排名不是全部都算前10
        for i in range(11):
            rows.append((f"P{i}", f"2026-06-{d:02d}", 0.5))
    # 讓A1只在前2週表現最好(第1名)，後2週表現變最差(單獨改後兩週的change_pct)
    rows = [r for r in rows if not (r[0] == "A1" and int(r[1][-2:]) > 10)]
    rows += [("A1", f"2026-06-{d:02d}", -5.0) for d in range(11, 21)]  # 後兩週變最差
    _seed_rank_history_db(db_path, rows)

    universe_rows = [{"stock_id": "A1", "meta_sector": "起伏族群"}]
    universe_rows += [{"stock_id": f"P{i}", "meta_sector": f"陪榜{i}"} for i in range(11)]
    universe = pd.DataFrame(universe_rows)

    result = calc_meta_rank_history(universe, db_path=str(db_path), weeks_back=5)

    row = result["起伏族群"]
    assert row["weekly_ranks"][0] == 1   # 第1週最強
    assert row["weekly_ranks"][1] == 1   # 第2週最強
    assert row["weekly_ranks"][-1] > 10  # 本週(最後一週)跌到10名外
    assert row["in_top10_this_week"] is False
    assert row["last_top10_week_index"] == 1  # 最近一次進前10是index1(第2週)
    assert row["last_top10_rank"] == 1


def test_calc_meta_rank_history_never_in_top10_returns_none_lookback(tmp_path):
    """族群近5週都沒進過前10：last_top10_week_index/last_top10_rank都要是None，
    不是隨便回0或其他假值。"""
    db_path = tmp_path / "test.db"
    rows = []
    for d in range(1, 6):
        rows.append(("A1", f"2026-06-{d:02d}", -5.0))  # 永遠墊底
        for i in range(11):
            rows.append((f"P{i}", f"2026-06-{d:02d}", 1.0))
    _seed_rank_history_db(db_path, rows)
    universe_rows = [{"stock_id": "A1", "meta_sector": "常年墊底"}]
    universe_rows += [{"stock_id": f"P{i}", "meta_sector": f"陪榜{i}"} for i in range(11)]
    universe = pd.DataFrame(universe_rows)

    result = calc_meta_rank_history(universe, db_path=str(db_path), weeks_back=5)

    row = result["常年墊底"]
    assert row["in_top10_this_week"] is False
    assert row["last_top10_week_index"] is None
    assert row["last_top10_rank"] is None
    assert row["consecutive_weeks_in_top10"] == 0


def test_calc_meta_rank_history_partial_weeks_when_insufficient_history(tmp_path):
    """只有8天歷史(不滿2週=10天)：只能算出1個完整週，weekly_ranks長度應該是1，
    不強湊成weeks_back(5)長度、不用假資料補足。"""
    db_path = tmp_path / "test.db"
    rows = [("A1", f"2026-06-{d:02d}", 1.0) for d in range(1, 9)]  # 8天
    _seed_rank_history_db(db_path, rows)
    universe = pd.DataFrame([{"stock_id": "A1", "meta_sector": "新資料族群"}])

    result = calc_meta_rank_history(universe, db_path=str(db_path), weeks_back=5)

    assert len(result["新資料族群"]["weekly_ranks"]) == 1


def test_calc_meta_rank_history_returns_empty_dict_when_no_price_data(tmp_path):
    db_path = tmp_path / "empty.db"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, change_pct DOUBLE)")
    con.close()
    universe = pd.DataFrame([{"stock_id": "1000", "meta_sector": "測試族群"}])

    result = calc_meta_rank_history(universe, db_path=str(db_path))
    assert result == {}
```

- [ ] **Step 2: 執行測試確認會失敗**

Run: `pytest tests/test_processors.py -k rank_history -v`
Expected: FAIL，錯誤訊息是 `ImportError: cannot import name 'calc_meta_rank_history'`

- [ ] **Step 3: 實作 `calc_meta_rank_history()`**

在 `processors/performance.py` 裡，緊接在 `calc_meta_heatgrid_windows()` 函式結束之後（檔案最後面）加入：

```python
def calc_meta_rank_history(
    universe_df: pd.DataFrame,
    db_path: str = "data/screener.db",
    weeks_back: int = 5,
) -> Dict[str, Dict[str, Any]]:
    """
    近N週(預設5週，每週=5個交易日滾動視窗，沿用cum5/roll5慣例)每個meta_sector的排名歷史，
    供族群近況「排名進出榜」跟單一族群「歷史出現紀錄」使用。即時從daily_prices全歷史用
    universe_df目前的meta_sector分類重算，不存快照表——族群分類本身會變動(例如工業電腦從
    電腦周邊拆出)，存快照會讓歷史資料卡在過期分類上，見
    docs/adr/0001-sector-rank-history-recomputed-not-snapshotted.md。

    「上榜」門檻＝前10名（依該週平均change_pct的複利報酬，全部meta_sector一起排序）。

    Returns
    -------
    {meta_name: {
        "weekly_ranks": List[int]，舊→新排列，長度<=weeks_back(資料不足5週時回較短list，
            不強湊)，最後一筆是本週。
        "in_top10_this_week": bool，本週排名是否<=10(資料完全不足、weekly_ranks為空時False)
        "consecutive_weeks_in_top10": int，連續進榜週數(含本週)，本週未進榜則為0
        "last_top10_week_index": int | None，本週未進榜時，weekly_ranks裡最近一次進榜的
            index(從新到舊找)；weekly_ranks範圍內都沒進榜(或本週已進榜)則為None
        "last_top10_rank": int | None，對應last_top10_week_index當時的排名
    }}
    """
    con = duckdb.connect(db_path, read_only=True)
    try:
        price_df = con.execute(
            "SELECT stock_id, date, change_pct FROM daily_prices"
        ).fetchdf()
    except Exception:
        return {}
    finally:
        con.close()

    if price_df.empty:
        return {}

    universe = universe_df[["stock_id", "meta_sector"]].copy()
    universe["stock_id"] = universe["stock_id"].astype(str)
    price_df["stock_id"] = price_df["stock_id"].astype(str)

    merged = price_df.merge(universe, on="stock_id", how="inner")
    merged = merged.dropna(subset=["change_pct", "meta_sector"])
    if merged.empty:
        return {}

    all_dates = sorted(merged["date"].unique())
    total_days = len(all_dates)
    num_complete_weeks = total_days // 5
    weeks_available = min(weeks_back, num_complete_weeks)
    if weeks_available == 0:
        return {}

    pct_pivot = (
        merged.groupby(["meta_sector", "date"])["change_pct"].mean()
        .unstack(level="date")
        .reindex(columns=all_dates)
    )
    meta_names = list(pct_pivot.index)

    def _compound(values: List[float]) -> float:
        factor = 1.0
        for v in values:
            factor *= (1 + v / 100)
        return round((factor - 1) * 100, 2)

    # week_ranks_by_week[i] = {meta_name: rank}，i=0是weeks_available裡最舊那週，
    # i=weeks_available-1是本週
    week_ranks_by_week: List[Dict[str, int]] = []
    for i in range(weeks_available):
        start = total_days - 5 * (weeks_available - i)
        end = total_days - 5 * (weeks_available - i - 1)
        window_dates = all_dates[start:end]

        week_pcts: Dict[str, float] = {}
        for meta_name in meta_names:
            series = pct_pivot.loc[meta_name, window_dates]
            if series.isna().any():
                continue  # 這個meta這週資料不完整，不參與這週的排名
            week_pcts[meta_name] = _compound(series.tolist())

        ranked = sorted(week_pcts.items(), key=lambda x: -x[1])
        week_ranks_by_week.append({name: idx + 1 for idx, (name, _) in enumerate(ranked)})

    results: Dict[str, Dict[str, Any]] = {}
    for meta_name in meta_names:
        weekly_ranks_raw = [week_ranks_by_week[i].get(meta_name) for i in range(weeks_available)]
        weekly_ranks = [r for r in weekly_ranks_raw if r is not None]
        if not weekly_ranks:
            results[meta_name] = {
                "weekly_ranks": [], "in_top10_this_week": False,
                "consecutive_weeks_in_top10": 0,
                "last_top10_week_index": None, "last_top10_rank": None,
            }
            continue

        this_week_rank = weekly_ranks_raw[-1]
        in_top10_this_week = this_week_rank is not None and this_week_rank <= 10

        consecutive = 0
        if in_top10_this_week:
            for rank in reversed(weekly_ranks_raw):
                if rank is not None and rank <= 10:
                    consecutive += 1
                else:
                    break

        last_top10_week_index = None
        last_top10_rank = None
        if not in_top10_this_week:
            for idx in range(len(weekly_ranks_raw) - 1, -1, -1):
                rank = weekly_ranks_raw[idx]
                if rank is not None and rank <= 10:
                    last_top10_week_index = idx
                    last_top10_rank = rank
                    break

        results[meta_name] = {
            "weekly_ranks": weekly_ranks_raw,
            "in_top10_this_week": in_top10_this_week,
            "consecutive_weeks_in_top10": consecutive,
            "last_top10_week_index": last_top10_week_index,
            "last_top10_rank": last_top10_rank,
        }

    return results
```

- [ ] **Step 4: 執行測試確認全部通過**

Run: `pytest tests/test_processors.py -k rank_history -v`
Expected: 全部 PASS（7個測試）

- [ ] **Step 5: Commit**

```bash
git add processors/performance.py tests/test_processors.py
git commit -m "feat(performance): 新增calc_meta_rank_history()即時算族群週排名歷史"
```

---

### Task 2: `find_rank_crossings()` — 頁面層級排名進出榜邏輯

**Files:**
- Modify: `export/index_generator.py`
- Test: `tests/test_index_generator.py`

比照 `find_turning_points()` 的模式（在 `export/index_generator.py` 第125行附近），比較每個族群「本週排名」vs「上週排名」，找出剛跨過前10門檻進榜/掉出榜的族群。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_index_generator.py`，找到 `from export.index_generator import find_turning_points, find_anomaly_cards` 這行，改成：

```python
from export.index_generator import find_turning_points, find_anomaly_cards, find_rank_crossings
```

然後在 `test_find_turning_points_skips_when_five_days_ago_data_is_none` 測試後面加入：

```python
def test_find_rank_crossings_detects_just_in_and_just_out():
    """複刻討論用的真實案例：散熱上週#14(不在前10)、本週#3(前10)=剛進榜；
    半導體設備上週#7(前10)、本週#28(不在前10)=剛掉出榜。"""
    rank_history = {
        "散熱": {"weekly_ranks": [20, 18, 16, 14, 3], "in_top10_this_week": True,
                 "consecutive_weeks_in_top10": 1, "last_top10_week_index": None, "last_top10_rank": None},
        "半導體設備": {"weekly_ranks": [10, 9, 8, 7, 28], "in_top10_this_week": False,
                      "consecutive_weeks_in_top10": 0, "last_top10_week_index": 3, "last_top10_rank": 7},
        "穩定族群": {"weekly_ranks": [5, 5, 5, 5, 5], "in_top10_this_week": True,
                    "consecutive_weeks_in_top10": 5, "last_top10_week_index": None, "last_top10_rank": None},
    }

    result = find_rank_crossings(rank_history)

    just_in_names = {r["meta_name"] for r in result["just_in"]}
    just_out_names = {r["meta_name"] for r in result["just_out"]}
    assert just_in_names == {"散熱"}
    assert just_out_names == {"半導體設備"}
    assert "穩定族群" not in just_in_names and "穩定族群" not in just_out_names

    sereater = next(r for r in result["just_in"] if r["meta_name"] == "散熱")
    assert sereater["prev_rank"] == 14 and sereater["cur_rank"] == 3

    semi = next(r for r in result["just_out"] if r["meta_name"] == "半導體設備")
    assert semi["prev_rank"] == 7 and semi["cur_rank"] == 28


def test_find_rank_crossings_skips_when_fewer_than_two_weeks_of_data():
    """weekly_ranks長度<2(例如剛上線第一天只算得出1週)時，沒有『上週』可以比較，
    不能誤判成剛進榜/剛掉出榜。"""
    rank_history = {
        "新族群": {"weekly_ranks": [3], "in_top10_this_week": True,
                  "consecutive_weeks_in_top10": 1, "last_top10_week_index": None, "last_top10_rank": None},
    }

    result = find_rank_crossings(rank_history)

    assert result["just_in"] == []
    assert result["just_out"] == []


def test_find_rank_crossings_sorts_by_magnitude_of_change():
    """剛進榜/剛掉出榜清單依變動幅度排序，變動最大的排最前面。"""
    rank_history = {
        "小幅進榜": {"weekly_ranks": [12, 9], "in_top10_this_week": True,
                    "consecutive_weeks_in_top10": 1, "last_top10_week_index": None, "last_top10_rank": None},
        "大幅進榜": {"weekly_ranks": [30, 2], "in_top10_this_week": True,
                    "consecutive_weeks_in_top10": 1, "last_top10_week_index": None, "last_top10_rank": None},
    }

    result = find_rank_crossings(rank_history)

    assert [r["meta_name"] for r in result["just_in"]] == ["大幅進榜", "小幅進榜"]
```

- [ ] **Step 2: 執行測試確認會失敗**

Run: `pytest tests/test_index_generator.py -k rank_crossings -v`
Expected: FAIL，`ImportError: cannot import name 'find_rank_crossings'`

- [ ] **Step 3: 實作 `find_rank_crossings()`**

在 `export/index_generator.py`，找到 `find_turning_points()` 函式（第125行附近，`def find_turning_points(heatgrid_windows...` 一路到 `return results`，接著空一行是 `def find_anomaly_cards(`），在 `find_turning_points()` 函式結束、`find_anomaly_cards()` 開始之前插入：

```python
def find_rank_crossings(rank_history: Dict[str, Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    排名進出榜（視覺spec用語：族群近況新子類別）。比較每個meta的「本週排名」vs「上週排名」，
    找出剛跨過前10名門檻進榜/掉出榜的族群。跟轉折點列表(tier換級，見find_turning_points())
    是刻意並存的不同訊號——tier只看自身動能，這裡純粹比較相對排名，見
    docs/adr/0003-rank-crossing-signal-kept-separate-from-tier-signal.md。

    rank_history: calc_meta_rank_history()的輸出。weekly_ranks長度<2(沒有『上週』可比較)
    的族群不參與判定。

    Returns
    -------
    {"just_in": [{"meta_name":.., "prev_rank":.., "cur_rank":..}, ...],
     "just_out": [{"meta_name":.., "prev_rank":.., "cur_rank":..}, ...]}
    各自依變動幅度(排名進步/退步的名次差)由大到小排序。
    """
    just_in = []
    just_out = []
    for meta_name, data in rank_history.items():
        ranks = data.get("weekly_ranks") or []
        if len(ranks) < 2:
            continue
        prev_rank, cur_rank = ranks[-2], ranks[-1]
        prev_in = prev_rank <= 10
        cur_in = cur_rank <= 10
        if not prev_in and cur_in:
            just_in.append({"meta_name": meta_name, "prev_rank": prev_rank, "cur_rank": cur_rank})
        elif prev_in and not cur_in:
            just_out.append({"meta_name": meta_name, "prev_rank": prev_rank, "cur_rank": cur_rank})

    just_in.sort(key=lambda r: r["prev_rank"] - r["cur_rank"], reverse=True)
    just_out.sort(key=lambda r: r["cur_rank"] - r["prev_rank"], reverse=True)
    return {"just_in": just_in, "just_out": just_out}
```

- [ ] **Step 4: 執行測試確認全部通過**

Run: `pytest tests/test_index_generator.py -k rank_crossings -v`
Expected: 全部 PASS（3個測試）

- [ ] **Step 5: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index_generator): 新增find_rank_crossings()排名進出榜判定邏輯"
```

---

### Task 3: 掛進 `build_sector_recap()`

**Files:**
- Modify: `export/index_generator.py`
- Test: `tests/test_index_generator.py`

`build_sector_recap()` 新增可選參數 `rank_history`，回傳字典新增 `rank_crossings` 鍵。沿用既有 `active_names` 過濾模式（跟 `turning_points` 一致，避免顯示不在目前 `meta_perf` 名單裡的族群）。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_index_generator.py`，找到 `test_build_sector_recap_includes_turning_points` 測試，在它後面加入：

```python
def test_build_sector_recap_includes_rank_crossings():
    meta_perf = [
        {"meta_name": "散熱", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    heatgrid_windows = {}
    rank_history = {
        "散熱": {"weekly_ranks": [14, 3], "in_top10_this_week": True,
                 "consecutive_weeks_in_top10": 1, "last_top10_week_index": None, "last_top10_rank": None},
    }
    cards = build_heatgrid_cards(meta_perf, {}, {}, heatgrid_windows)
    recap = build_sector_recap(cards, heatgrid_windows, rank_history)

    assert recap["rank_crossings"]["just_in"][0]["meta_name"] == "散熱"


def test_build_sector_recap_rank_crossings_defaults_empty_without_rank_history():
    """rank_history沒傳(None)時rank_crossings要是空list，不能crash——跟其他
    enrichment參數(cum_data等)的fail-soft慣例一致。"""
    meta_perf = [
        {"meta_name": "族群A", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    cards = build_heatgrid_cards(meta_perf, {}, {}, {})
    recap = build_sector_recap(cards, {})

    assert recap["rank_crossings"] == {"just_in": [], "just_out": []}


def test_build_sector_recap_excludes_stale_sector_from_rank_crossings():
    """rank_history有某族群的進榜資料，但meta_perf已經不包含它——跟turning_points的
    過濾邏輯一致，不能顯示已下架族群。"""
    meta_perf = [
        {"meta_name": "有效族群", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    rank_history = {
        "有效族群": {"weekly_ranks": [14, 3], "in_top10_this_week": True,
                    "consecutive_weeks_in_top10": 1, "last_top10_week_index": None, "last_top10_rank": None},
        "已下架族群": {"weekly_ranks": [14, 3], "in_top10_this_week": True,
                     "consecutive_weeks_in_top10": 1, "last_top10_week_index": None, "last_top10_rank": None},
    }
    cards = build_heatgrid_cards(meta_perf, {}, {}, {})
    recap = build_sector_recap(cards, {}, rank_history)

    just_in_names = {r["meta_name"] for r in recap["rank_crossings"]["just_in"]}
    assert "已下架族群" not in just_in_names
    assert "有效族群" in just_in_names
```

- [ ] **Step 2: 執行測試確認會失敗**

Run: `pytest tests/test_index_generator.py -k rank_crossings -v`
Expected: 新增的3個測試 FAIL（`build_sector_recap() got an unexpected keyword argument` 或 `KeyError: 'rank_crossings'`）

- [ ] **Step 3: 修改 `build_sector_recap()`**

在 `export/index_generator.py` 第408行附近，把：

```python
def build_sector_recap(
    cards: List[Dict[str, Any]],
    heatgrid_windows: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
```

改成：

```python
def build_sector_recap(
    cards: List[Dict[str, Any]],
    heatgrid_windows: Dict[str, Dict[str, Any]],
    rank_history: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
```

然後找到函式最後的：

```python
    active_names = {c["meta_name"] for c in cards}
    active_windows = {name: data for name, data in heatgrid_windows.items() if name in active_names}

    return {
        "hot_top5": hot_top5,
        "cold_top5": cold_top5,
        "today_breakout": today_breakout,
        "foreign_stealth": foreign_stealth,
        "trust_stealth": trust_stealth,
        "volume_anomaly": volume_anomaly,
        "turning_points": find_turning_points(active_windows),
    }
```

改成：

```python
    active_names = {c["meta_name"] for c in cards}
    active_windows = {name: data for name, data in heatgrid_windows.items() if name in active_names}
    active_rank_history = {
        name: data for name, data in (rank_history or {}).items() if name in active_names
    }

    return {
        "hot_top5": hot_top5,
        "cold_top5": cold_top5,
        "today_breakout": today_breakout,
        "foreign_stealth": foreign_stealth,
        "trust_stealth": trust_stealth,
        "volume_anomaly": volume_anomaly,
        "turning_points": find_turning_points(active_windows),
        "rank_crossings": find_rank_crossings(active_rank_history),
    }
```

（`Optional` 已經在檔案頂端 `from typing import ... Optional` 匯入過，不用新增 import。）

- [ ] **Step 4: 執行測試確認全部通過**

Run: `pytest tests/test_index_generator.py -v`
Expected: 全部 PASS（含既有全部 `build_sector_recap` 測試，簽章向後相容不會壞掉既有測試）

- [ ] **Step 5: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index_generator): build_sector_recap()掛上rank_crossings"
```

---

### Task 4: 頁面層級「排名進出榜」HTML/CSS

**Files:**
- Modify: `export/index_generator.py`
- Test: `tests/test_index_generator.py`

在 `_sector_recap_html()` 新增一個獨立區塊，接在既有 `.turning-wrap` 後面（不塞進6欄Top5網格，理由見spec）。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_index_generator.py` 找一個現有測試 `generate()` 完整流程的測試（搜尋 `def test_generate` 開頭的測試找一個做為插入點參考），在檔案裡任何一個既有 `def test_generate_` 測試後面加入：

```python
def test_generate_renders_rank_crossings_section_in_sector_recap(tmp_path):
    """排名進出榜區塊要出現在族群近況裡，緊接在轉折點列表(.turning-wrap)後面，
    左右兩欄分別列剛進榜/剛掉出榜的族群名稱跟排名變化。"""
    meta_perf = [
        {"meta_name": "散熱", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
        {"meta_name": "半導體設備", "avg_change_pct": -1.0, "up_count": 0, "down_count": 1, "flat_count": 0},
    ]
    universe_df = pd.DataFrame([
        {"stock_id": "1", "stock_name": "股票一", "meta_sector": "散熱"},
        {"stock_id": "2", "stock_name": "股票二", "meta_sector": "半導體設備"},
    ])
    prices_df = pd.DataFrame([
        {"stock_id": "1", "change_pct": 1.0, "close": 100.0},
        {"stock_id": "2", "change_pct": -1.0, "close": 50.0},
    ])
    rank_history = {
        "散熱": {"weekly_ranks": [14, 3], "in_top10_this_week": True,
                 "consecutive_weeks_in_top10": 1, "last_top10_week_index": None, "last_top10_rank": None},
        "半導體設備": {"weekly_ranks": [7, 28], "in_top10_this_week": False,
                     "consecutive_weeks_in_top10": 0, "last_top10_week_index": 0, "last_top10_rank": 7},
    }

    output_path = tmp_path / "index.html"
    generate(
        date(2026, 7, 29), meta_perf, universe_df,
        meta_signals={}, meta_chips={}, prices_df=prices_df,
        heatgrid_windows={}, rank_history=rank_history,
        output_path=str(output_path),
    )

    html = output_path.read_text(encoding="utf-8")
    assert "排名進出榜" in html
    assert "散熱" in html and "半導體設備" in html
    assert html.index(".turning-wrap") < html.index("rankmove-wrap") if ".turning-wrap" in html else True
```

（最後一行的 `if` 是防呆——`.turning-wrap` 是 CSS class 定義字串本身在 `<style>` 裡出現一次，跟 HTML 內容裡的 class 屬性都算「出現在 html 裡」，這個斷言只是確保兩者都存在且沒有明顯順序錯誤，不是嚴格的 DOM 結構檢查。）

- [ ] **Step 2: 執行測試確認會失敗**

Run: `pytest tests/test_index_generator.py -k rank_crossings_section -v`
Expected: FAIL，`generate() got an unexpected keyword argument 'rank_history'`

- [ ] **Step 3: 新增 CSS**

在 `export/index_generator.py`，找到（第790-799行附近）：

```
.turning-desc{margin-left:auto;font-size:.72rem;color:var(--ink-2);font-style:italic;font-family:var(--serif)}
"""
```

在 `.turning-desc{...}` 那一行後面、`"""` 之前插入：

```
.rankmove-wrap{margin:26px 26px 0;background:var(--panel);border:1px solid var(--border-2);border-radius:5px;padding:18px 22px}
.rankmove-head{font-family:var(--serif);font-weight:700;font-size:1rem;color:var(--ink);margin-bottom:4px}
.rankmove-sub{font-size:.72rem;color:var(--ink-3);margin-bottom:14px}
.rankmove-cols{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.rankmove-col h4{margin:0 0 8px;font-family:var(--mono);font-size:.66rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
.rankmove-col.in h4{color:var(--up)}
.rankmove-col.out h4{color:var(--down)}
.rankmove-item{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border);font-size:.85rem}
.rankmove-item:last-child{border-bottom:none}
.rankmove-item .rm-name{font-family:var(--serif);font-weight:600;color:var(--ink)}
.rankmove-item .rm-shift{font-family:var(--mono);font-size:.74rem;color:var(--ink-2)}
.rankmove-empty{color:var(--ink-3);font-size:.78rem;font-family:var(--serif)}
```

- [ ] **Step 4: 修改 `_sector_recap_html()` 加入排名進出榜區塊**

在 `export/index_generator.py`，找到 `_sector_recap_html()` 函式（第924行附近），把函式簽章：

```python
def _sector_recap_html(recap: Dict[str, Any]) -> str:
```

保持不變（`recap` 字典裡已經有 `rank_crossings` 鍵，不用改簽章）。在函式內部，找到：

```python
    turning = recap["turning_points"]
```

這一行前面加入排名進出榜的 HTML 組裝邏輯：

```python
    def _rankmove_col(items: List[Dict[str, Any]], direction: str) -> str:
        if not items:
            return '<div class="rankmove-empty">目前沒有族群{}</div>'.format(
                "剛進榜" if direction == "in" else "剛掉出榜"
            )
        return "".join(
            f'<div class="rankmove-item"><span class="rm-name">{_esc(r["meta_name"])}</span>'
            f'<span class="rm-shift tabular">#{r["prev_rank"]}→#{r["cur_rank"]}</span></div>'
            for r in items
        )

    rank_crossings = recap.get("rank_crossings", {"just_in": [], "just_out": []})
    rankmove_html = f"""
<div class="rankmove-wrap">
  <div class="rankmove-head">排名進出榜</div>
  <div class="rankmove-sub">這週剛擠進/掉出前10名的族群（跟上週排名比較，不是自身動能——跟上面「轉折點」是不同角度的訊號）</div>
  <div class="rankmove-cols">
    <div class="rankmove-col in"><h4>剛進榜</h4>{_rankmove_col(rank_crossings["just_in"], "in")}</div>
    <div class="rankmove-col out"><h4>剛掉出榜</h4>{_rankmove_col(rank_crossings["just_out"], "out")}</div>
  </div>
</div>"""
```

然後找到函式最後的 return（原本是）：

```python
<div class="turning-wrap">
  <div class="turning-head">轉折點：等級真的翻轉的族群</div>
  <div class="turning-sub">不是看誰漲最多，是看「上週的等級」跟「這週的等級」是否真的換了一級。</div>
  <div>{turning_html}</div>
</div>"""
```

改成：

```python
<div class="turning-wrap">
  <div class="turning-head">轉折點：等級真的翻轉的族群</div>
  <div class="turning-sub">不是看誰漲最多，是看「上週的等級」跟「這週的等級」是否真的換了一級。</div>
  <div>{turning_html}</div>
</div>
{rankmove_html}"""
```

- [ ] **Step 5: 修改 `generate()` 簽章跟呼叫 `build_sector_recap()`**

在 `export/index_generator.py` 第990行附近，把 `generate()` 的簽章：

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
    output_path: str = "docs/index.html",
) -> None:
```

改成（新增 `rank_history` 參數，放在 `vol_turnover_signals` 後面）：

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

在同一函式的 docstring 補一行說明（找到 `- vol_turnover_signals：scan_volume_turnover() 輸出(list)，巨量換手訊號區塊。` 這行，在它後面加）：

```python
    - rank_history：calc_meta_rank_history() 輸出，族群近況「排名進出榜」跟單一族群
      「歷史出現紀錄」用。
```

然後找到：

```python
    recap = build_sector_recap(cards, heatgrid_windows)
```

改成：

```python
    recap = build_sector_recap(cards, heatgrid_windows, rank_history)
```

- [ ] **Step 6: 執行測試確認全部通過**

Run: `pytest tests/test_index_generator.py -v`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index_generator): 族群近況新增排名進出榜HTML區塊"
```

---

### Task 5: 單一族群「歷史出現紀錄」— CSS + JS

**Files:**
- Modify: `export/index_generator.py`

單一族群點開詳細面板時顯示「歷史出現紀錄」：5格橫向排列的精確名次軌跡 + 文字摘要。資料透過既有 `CARD_META`（JS端）傳遞，先在 Task 6 把 `weekly_ranks` 等欄位塞進 `card_meta` dict，這個 Task 先做純前端渲染邏輯（`buildHistoryRecord()`），下個 Task 再接資料源。這個 Task 沒有 Python 單元測試（純 JS 字串樣板函式，跟 `buildChipsSummary()`/`buildSparkline()` 一樣的性質，靠 Task 6 的整合測試驗證最終渲染結果），但仍要跑一次既有全部測試確保沒有語法破壞既有輸出。

- [ ] **Step 1: 新增 CSS**

在 `export/index_generator.py`，找到 `.rankmove-empty{...}`（Task 4 剛加的最後一行 CSS），在它後面追加：

```
.history-wrap{margin-top:16px}
.history-summary{font-family:var(--serif);font-size:.92rem;color:var(--ink);margin-bottom:10px;
  padding:9px 13px;background:var(--panel-2);border-left:3px solid var(--accent);border-radius:0 4px 4px 0}
.history-summary b{color:var(--accent)}
.history-weekline-label{font-family:var(--mono);font-size:.6rem;font-weight:700;color:var(--ink-3);
  letter-spacing:.06em;text-transform:uppercase;margin-bottom:6px}
.history-weekline{display:grid;grid-template-columns:repeat(5,1fr);gap:6px}
.history-week{border:1px solid var(--border);border-radius:5px;padding:7px 8px;background:var(--panel-3);
  font-family:var(--mono);font-size:.64rem;color:var(--ink-2);text-align:center}
.history-week .hw-label{display:block;color:var(--ink-3)}
.history-week .hw-rank{display:block;margin-top:3px;font-size:.86rem;font-weight:700;color:var(--ink)}
.history-week.in-top10{border-color:color-mix(in srgb, var(--accent) 45%, var(--border))}
.history-week.in-top10 .hw-rank{color:var(--accent)}
```

- [ ] **Step 2: 新增 `buildHistoryRecord()` JS 函式**

在 `export/index_generator.py`，找到 JS 函式 `buildChipsSummary()`（第1211行附近，`// meta是CARD_META[name]...` 開頭的函式），在這支函式結束（`return rows.length ? ... : '';` 那行跟接下來的 `}}` 之後）加入新函式：

```javascript
// 單一族群「歷史出現紀錄」：近幾週精確排名軌跡+文字摘要。meta是CARD_META[name]，
// weekly_ranks/in_top10_this_week/consecutive_weeks_in_top10/last_top10_week_index/
// last_top10_rank都是Python端calc_meta_rank_history()算好的數值，不是使用者輸入，不用escHtml。
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

- [ ] **Step 3: 跑全部測試確認沒有語法破壞既有輸出**

Run: `pytest tests/test_index_generator.py -v`
Expected: 全部 PASS（這步只新增了未被呼叫的函式跟未被引用的CSS，不影響既有輸出）

- [ ] **Step 4: Commit**

```bash
git add export/index_generator.py
git commit -m "feat(index_generator): 新增buildHistoryRecord() JS函式(尚未接資料源)"
```

---

### Task 6: 把排名歷史資料接進 `card_meta` + `selectGroup()`

**Files:**
- Modify: `export/index_generator.py`
- Test: `tests/test_index_generator.py`

把 Task 1 算出的 `rank_history` 塞進既有 `card_meta` dict（`CARD_META` JS 物件的 Python 端來源），並在 `selectGroup()` 呼叫 Task 5 的 `buildHistoryRecord()`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_index_generator.py` 檔案裡，緊接在 Task 4 加的 `test_generate_renders_rank_crossings_section_in_sector_recap` 後面加入：

```python
def test_generate_embeds_rank_history_into_card_meta_for_history_record(tmp_path):
    """單一族群的排名歷史資料要塞進CARD_META，供點開族群詳細面板時
    buildHistoryRecord()渲染「歷史出現紀錄」使用。"""
    meta_perf = [
        {"meta_name": "工業電腦", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    universe_df = pd.DataFrame([
        {"stock_id": "1", "stock_name": "股票一", "meta_sector": "工業電腦"},
    ])
    prices_df = pd.DataFrame([{"stock_id": "1", "change_pct": 1.0, "close": 100.0}])
    rank_history = {
        "工業電腦": {"weekly_ranks": [18, 9, 7, 4, 1], "in_top10_this_week": True,
                    "consecutive_weeks_in_top10": 3, "last_top10_week_index": None, "last_top10_rank": None},
    }

    output_path = tmp_path / "index.html"
    generate(
        date(2026, 7, 29), meta_perf, universe_df,
        meta_signals={}, meta_chips={}, prices_df=prices_df,
        heatgrid_windows={}, rank_history=rank_history,
        output_path=str(output_path),
    )

    html = output_path.read_text(encoding="utf-8")
    assert '"weekly_ranks":[18,9,7,4,1]' in html.replace(" ", "")
    assert '"in_top10_this_week":true' in html.replace(" ", "")
    assert '"consecutive_weeks_in_top10":3' in html.replace(" ", "")
    assert "buildHistoryRecord(meta)" in html  # selectGroup()有呼叫這支函式
```

- [ ] **Step 2: 執行測試確認會失敗**

Run: `pytest tests/test_index_generator.py -k embeds_rank_history -v`
Expected: FAIL（`weekly_ranks` 不在輸出的 JSON 裡，因為 `card_meta` 還沒塞這個欄位）

- [ ] **Step 3: 修改 `card_meta` dict 組裝邏輯**

在 `export/index_generator.py` 第1031行附近，找到：

```python
    card_meta = {}
    for c in cards:
        meta_name = c["meta_name"]
        sig = meta_signals.get(meta_name, {})
        chips = meta_chips.get(meta_name, {})
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
        }
    card_meta_js = json.dumps(card_meta, ensure_ascii=False).replace("</", "<\\/")
```

改成（新增 `rank_row` 查表跟5個新欄位）：

```python
    card_meta = {}
    for c in cards:
        meta_name = c["meta_name"]
        sig = meta_signals.get(meta_name, {})
        chips = meta_chips.get(meta_name, {})
        rank_row = (rank_history or {}).get(meta_name, {})
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
    card_meta_js = json.dumps(card_meta, ensure_ascii=False).replace("</", "<\\/")
```

- [ ] **Step 4: 在 `selectGroup()` 呼叫 `buildHistoryRecord()`**

在 `export/index_generator.py` 的 `selectGroup()` 函式（第1393行附近），找到：

```javascript
  const metaSpark = buildSparkline(meta.daily_pct, meta.dates, 'meta-sparkline');
  const chipsSum = buildChipsSummary(meta);
```

改成：

```javascript
  const metaSpark = buildSparkline(meta.daily_pct, meta.dates, 'meta-sparkline');
  const chipsSum = buildChipsSummary(meta);
  const historyRecord = buildHistoryRecord(meta);
```

然後找到 `if (!stocks.length) {{` 分支裡的：

```javascript
      ${{metaSpark}}${{chipsSum}}
      <div class="detail-empty">這個族群目前沒有個股行情資料。</div>`;
```

改成：

```javascript
      ${{metaSpark}}${{chipsSum}}${{historyRecord}}
      <div class="detail-empty">這個族群目前沒有個股行情資料。</div>`;
```

以及 `else {{` 分支裡的：

```javascript
      ${{metaSpark}}${{chipsSum}}
      <div class="overflow-wrap"><table class="stock-list-table">
```

改成：

```javascript
      ${{metaSpark}}${{chipsSum}}${{historyRecord}}
      <div class="overflow-wrap"><table class="stock-list-table">
```

- [ ] **Step 5: 執行測試確認全部通過**

Run: `pytest tests/test_index_generator.py -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index_generator): card_meta掛上排名歷史，selectGroup()渲染歷史出現紀錄"
```

---

### Task 7: 接進 `main.py`

**Files:**
- Modify: `main.py`

呼叫 `calc_meta_rank_history()` 並傳進 `generate_index_html()`，比照現有 `heatgrid_windows` 的 try/except fail-soft 慣例。

- [ ] **Step 1: 新增 import**

在 `main.py` 第19行附近，找到：

```python
from processors.performance import calc_sector_performance, calc_meta_performance, calc_universe_performance, calc_cumulative_meta, calc_meta_signals, calc_meta_chips_signals, get_stock_chips_ranking, get_margin_divergence, calc_market_breadth, calc_capital_concentration, classify_market_regime, calc_meta_heatgrid_windows, calc_stock_sparklines
```

改成（在最後面加 `calc_meta_rank_history`）：

```python
from processors.performance import calc_sector_performance, calc_meta_performance, calc_universe_performance, calc_cumulative_meta, calc_meta_signals, calc_meta_chips_signals, get_stock_chips_ranking, get_margin_divergence, calc_market_breadth, calc_capital_concentration, classify_market_regime, calc_meta_heatgrid_windows, calc_stock_sparklines, calc_meta_rank_history
```

- [ ] **Step 2: 呼叫新函式並傳進 `generate_index_html()`**

在 `main.py` 第724行附近，找到：

```python
        try:
            heatgrid_windows = calc_meta_heatgrid_windows(universe_df) if universe_df is not None else {}
        except Exception as exc:
            logger.warning("熱區格動能窗口計算失敗，index.html 動能標籤本次不顯示: %s", exc)
            heatgrid_windows = {}
```

在這段後面（`heatgrid_windows = {}` 之後）加入：

```python

        try:
            rank_history = calc_meta_rank_history(universe_df) if universe_df is not None else {}
        except Exception as exc:
            logger.warning("族群排名歷史計算失敗，index.html排名進出榜/歷史出現紀錄本次不顯示: %s", exc)
            rank_history = {}
```

然後找到（第755行附近）：

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
                                 vol_turnover_signals=vol_turnover_signals)
```

改成：

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
                                 rank_history=rank_history)
```

- [ ] **Step 3: 確認語法正確（不需要跑main.py本身，main.py不應由開發者自己執行——見CLAUDE.md「你不該做的事」）**

Run: `python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read())"`
Expected: 無輸出（沒有語法錯誤）

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat(main): 接上calc_meta_rank_history()，傳進index.html產生流程"
```

---

### Task 8: 全套測試確認

**Files:** （無新檔案，純驗證）

- [ ] **Step 1: 跑全部測試**

Run: `pytest -q`
Expected: 全部通過（原本415個測試 + 這個 plan 新增的約16個測試 ≈ 431個，全綠，0 failed）

- [ ] **Step 2: 若有測試失敗，回頭檢查對應 Task 的實作，修正後重跑，直到全綠**

- [ ] **Step 3: 更新 `debug-tasks.md`**

在 `debug-tasks.md` 最後面加入交接區塊（依 `CLAUDE.md` 既有模板）：

```markdown
## [2026-07-29] 族群排名歷史：排名進出榜＋歷史出現紀錄

### 改了什麼
- 異動檔案：processors/performance.py, export/index_generator.py, main.py,
  tests/test_processors.py, tests/test_index_generator.py
- 邏輯說明：新增calc_meta_rank_history()即時從daily_prices全歷史算族群週排名
  (5交易日滾動視窗一週，不存快照表，用目前族群分類回推)。族群近況新增「排名
  進出榜」子類別(這週vs上週跨過前10門檻的族群)，跟既有轉折點列表並存不合併。
  單一族群詳細面板新增「歷史出現紀錄」(近5週精確排名軌跡+文字摘要)。
  設計討論見CONTEXT.md、docs/adr/0001-*.md、docs/adr/0003-*.md，spec見
  docs/superpowers/specs/2026-07-29-sector-rank-history-design.md。

### 資料來源相關（如有異動）
- 上市/上櫃資料：無異動，純粹是daily_prices既有change_pct欄位的新用法(即時算
  週排名)，沒有新增資料源或改變抓取邏輯。

### 請 Debugger 驗證
- [ ] 全部測試通過(pytest -q全綠)
- [ ] 族群近況區塊新增「排名進出榜」，位置在轉折點列表下面，左右兩欄剛進榜/
      剛掉出榜
- [ ] 點進任一族群詳細面板，最上面(走勢圖/籌碼摘要之後)有「歷史出現紀錄」，
      顯示5格排名軌跡+一句文字摘要
- [ ] 沒有進前10的族群面板要顯示「上次進榜是W-x第Y名」或「近N週都沒有進前10」
- [ ] 族群分類異動(例如工業電腦)的歷史排名要能正確反映目前分類，不是卡在舊分類

### 特別注意
- 這個功能完全是即時計算，不需要等待資料庫累積新資料——上線當天就有完整5週
  歷史可看(資料庫回溯到2025-01-02，遠超過5週所需天數)
```

- [ ] **Step 4: Commit**

```bash
git add debug-tasks.md
git commit -m "docs(debug-tasks): 交接族群排名歷史(排名進出榜+歷史出現紀錄)"
```

---

## Self-Review

**Spec 覆蓋檢查**：
- User Story 1/2（頁面層級剛進榜/剛掉出榜）→ Task 2/3/4
- User Story 3/4/5（單一族群精確排名軌跡+文字摘要邊界情況）→ Task 1（純函式邏輯）+ Task 5/6（渲染）
- User Story 6（跟轉折點列表並存不合併）→ Task 4（獨立區塊，不塞進Top5網格）
- User Story 7（用目前分類回推，不受歷史分類影響）→ Task 1 `test_calc_meta_rank_history_uses_current_classification_not_historical`
- Implementation Decisions 的「資料不足時的行為」→ Task 1 `test_calc_meta_rank_history_partial_weeks_when_insufficient_history`
- Out of Scope（不存快照表、不影響既有轉折點列表）→ 全程沒有新增資料庫表，`build_sector_recap()` 的 `turning_points` 邏輯完全沒動

**型別/命名一致性檢查**：`calc_meta_rank_history()` 回傳的 `weekly_ranks`/`in_top10_this_week`/`consecutive_weeks_in_top10`/`last_top10_week_index`/`last_top10_rank` 五個鍵名，從 Task 1 定義開始，一路到 Task 2（`find_rank_crossings` 讀 `weekly_ranks`）、Task 3（`build_sector_recap` 傳遞）、Task 6（`card_meta` 塞值、JS `buildHistoryRecord()` 讀取）都用同一組名稱，沒有改名。
