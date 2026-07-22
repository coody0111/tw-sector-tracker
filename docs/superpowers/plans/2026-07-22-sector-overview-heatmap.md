# 族群總覽頁（index.html）熱區格改版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新建 `export/index_generator.py` 取代 `export/html_generator.py`，把 `docs/index.html`
從現有卡片式版面改成熱區格（heatmap grid）版面：41 個族群卡片 + 異動族群快報 + 族群近況
（升溫/退燒排行 + 轉折點）+ 個股點開面板。

**Architecture:** 視覺/互動設計已在
`docs/superpowers/specs/2026-07-15-sector-overview-heatmap-redesign.md`（下稱「視覺 spec」）定案，
參考 mockup `docs/superpowers/mockups/2026-07-15-index-v18-inline-expand.html`。技術落地決策在
`docs/superpowers/specs/2026-07-22-sector-overview-heatmap-implementation-design.md`（下稱
「實作 spec」）：新檔案取代舊檔案（`html_generator.py` 保留不刪）、資料層大部分重用
`main.py::run()` 現有已算好的資料、轉折點用「回推同一套算法」而非開新歷史快照表。全部三個功能
區塊一次做完，不分批上線。

**分層原則（這份 plan 執行時務必遵守）**：這個專案的 `export/*_generator.py` 全部檔案**沒有任何
一個直接呼叫 `duckdb.connect()`**——DB 查詢一律留在 `processors/`，`export/` 只吃已經算好的資料
做渲染/分類。跟 v2 逆轟策略同款分工（`processors/observation_scores.py` 算原始 5 因子數值，
`export/momentum_generator.py::classify_sector_state()` 才做五級標籤分類）：這次「回推窗口原始
數值」的查詢放 `processors/performance.py`（新函式，緊鄰既有 `calc_meta_signals()` 等姊妹函式），
「拿原始數值分類成五級動能狀態」的 `classify_tier()` 留在 `export/index_generator.py`。

**Tech Stack:** Python、DuckDB、pandas（既有依賴，無新套件）。額外重用專案既有共用工具
`streak_utils.calc_streak()`（不要重新實作 streak 計算邏輯，這支就是為了避免重複實作抽出來的）。

---

## Global Constraints

- 對照文件：視覺 spec（`2026-07-15-sector-overview-heatmap-redesign.md`）定 CSS/HTML 結構/互動邏輯；
  實作 spec（`2026-07-22-sector-overview-heatmap-implementation-design.md`）定資料層/檔案結構/
  測試方式。兩份都要看，這份 plan 是把兩者轉成可執行的 Task。
- **`export/html_generator.py` 不動、不刪**：`main.py` 改呼叫新函式後，舊檔變成沒人呼叫但保留
  當 rollback 用，之後另開獨立任務刪除。
- **DB 查詢在 `processors/`，分類/渲染在 `export/`**：見上方「分層原則」，這是這份 plan 執行時
  的硬規則，不是建議。
- **`classify_tier()` 是第三套獨立的五級分類邏輯**（跟 `scan_momentum_health()` 的 `strength_tier`、
  `momentum_generator.py::classify_sector_state()` 都不同、不共用計算依據，見實作 spec §3.1）——
  這是刻意的設計決定，不要在寫 Task 時重新論證，也不要嘗試「順便重構統一」三套邏輯。
- **重用 `streak_utils.calc_streak()`**：這支是通用共用工具（`processors/performance.py` 開頭已
  `import`），這次的 streak 回推計算直接呼叫它，不要重新寫一份迴圈邏輯。
- **草案門檻，不回測**：`classify_tier`/`classify_temp` 的門檻（accel>3/-2、streak<=-5、±5pt）、
  異動族群門檻（量比≥1.5x、排名跳動≥10、streak≥5）全部是視覺 spec 定的經驗法則草案，程式碼跟
  頁面文案都要清楚標注「草案，待回測」，不能包裝成精確驗證過的數字。
- **資料不足時回 `None`，不硬湊**：窗口/streak 資料不足時回 `None`；`classify_tier(None, ...)`
  等任一輸入為 `None` 時回傳 `None`；轉折點列表遇到 `None` 直接跳過該族群，不能顯示成「沒有
  翻轉」（那是誤導）。見實作 spec §2.2「資料不足時的行為」。
- **41 個族群全部要有卡片**：不能只 render 部分族群（2026-07-09 曾經因為這個問題讓連結全部
  靜默失敗，`test_html_generator.py` 已有同類回歸測試
  `test_generate_renders_card_for_every_meta_sector_not_just_top_bottom_10`，這次新檔案要有
  對應的測試）。
- **onclick 安全寫法**：熱區格/異動族群卡片的 `onclick` 一律用 `onclick="selectGroup(this.dataset.metaName)"`
  這種「讀 DOM 屬性」寫法，不要把族群名稱直接字串內插進 `onclick="selectGroup('...')"`（族群名稱
  可能含 `/` 等字元，且這是既有 `chips_generator.py`/`html_generator.py` 已經在用的安全慣例，見
  Task 8 詳細說明）。
- 每個 Task 完成後跑對應測試檔確認沒有破壞既有測試（照專案慣例，最終驗證留給 Debugger）。

---

### Task 1：`processors/performance.py::_streak_and_windows_as_of()` —— 回推任意時間點的窗口

**Files:**
- Modify: `processors/performance.py`（新函式，加在 `calc_meta_chips_signals()` 之後，檔案最後）
- Test: `tests/test_processors.py`

**Interfaces:**
- `_streak_and_windows_as_of(daily_pcts: list, cutoff_index: int) -> dict | None`：純函式。
  `daily_pcts` 是某族群「每日平均漲跌%」序列（舊→新，完整序列）。`cutoff_index` 是 0-based
  index，代表「假裝這個 index 是今天」。回傳
  `{"streak": int, "last_week_pct": float, "this_week_pct": float}`；`cutoff_index < 9`
  （不足 10 天可用歷史）時回傳 `None`。

- [ ] **Step 1: 寫失敗測試**

Append to `tests/test_processors.py`：

```python
from processors.performance import _streak_and_windows_as_of


def test_streak_and_windows_as_of_computes_this_and_last_week():
    """thisWeek=最近5天(index 5~9)複利報酬，lastWeek=再往前5天(index 0~4)。
    全部+1.0%：thisWeek=(1.01^5-1)*100≈5.10，lastWeek同理也≈5.10。"""
    daily_pcts = [1.0] * 10  # index 0~9，10天歷史，cutoff_index=9剛好卡在邊界
    result = _streak_and_windows_as_of(daily_pcts, cutoff_index=9)
    assert result is not None
    assert result["this_week_pct"] == 5.1
    assert result["last_week_pct"] == 5.1
    assert result["streak"] == 10  # 連漲10天(index 0~9全部+1.0%)


def test_streak_and_windows_as_of_returns_none_when_insufficient_history():
    """cutoff_index=8時只有9天資料(index 0~8)，不足10天(thisWeek5+lastWeek5)，回None。"""
    daily_pcts = [1.0] * 9
    result = _streak_and_windows_as_of(daily_pcts, cutoff_index=8)
    assert result is None


def test_streak_and_windows_as_of_streak_resets_on_direction_change():
    """連漲3天後轉跌，streak應該是-1(今天跌，只算今天這1天)，不是累加正負號混合。"""
    daily_pcts = [1.0, -0.5, -0.5, -0.5, 1.0, 1.0, 1.0, 1.0, 1.0, -0.3]
    # index 9(今天)是-0.3，往前看index 8是+1.0方向不同 → streak=-1
    result = _streak_and_windows_as_of(daily_pcts, cutoff_index=9)
    assert result["streak"] == -1


def test_streak_and_windows_as_of_zero_pct_breaks_streak_to_zero():
    """今天漲跌%剛好是0(持平)時，streak視為0（跟streak_utils.calc_streak()既有慣例一致）。"""
    daily_pcts = [1.0] * 9 + [0.0]
    result = _streak_and_windows_as_of(daily_pcts, cutoff_index=9)
    assert result["streak"] == 0


def test_streak_and_windows_as_of_five_days_ago_reuses_todays_last_week_as_this_week():
    """驗證窗口重疊關係：cutoff_index往前推5(等於算「5天前的今天」)時，它的this_week_pct
    應該等於原本cutoff_index算出來的last_week_pct（同一個窗口，只是換了個稱呼）——
    這是轉折點回推算法能省一次計算的關鍵前提，必須驗證是真的邏輯保證，不是巧合。"""
    daily_pcts = [0.5, 0.5, -0.3, -0.3, -0.3, 1.2, 1.2, 1.2, 1.2, 1.2, 0.8, 0.8, 0.8, 0.8, 0.8]
    today = _streak_and_windows_as_of(daily_pcts, cutoff_index=14)
    five_days_ago = _streak_and_windows_as_of(daily_pcts, cutoff_index=9)
    assert five_days_ago is not None
    assert five_days_ago["this_week_pct"] == today["last_week_pct"]
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_processors.py -k streak_and_windows_as_of -q`
Expected: FAIL（`ImportError: cannot import name '_streak_and_windows_as_of'`）

- [ ] **Step 3: 實作**

Append to `processors/performance.py`（檔案最後）：

```python
def _streak_and_windows_as_of(daily_pcts: List[float], cutoff_index: int) -> Optional[Dict[str, Any]]:
    """
    回推「假裝 cutoff_index 是今天」時的 streak/上週/本週窗口，供族群總覽頁熱區格改版的轉折點
    回推算法使用（不用開新的歷史快照表，見
    docs/superpowers/specs/2026-07-22-sector-overview-heatmap-implementation-design.md §2.3）。

    daily_pcts：某族群「每日平均漲跌%」序列，舊→新排列，長度需涵蓋到 cutoff_index。
    cutoff_index：0-based index，這個位置視為「今天」。

    窗口定義（以 cutoff_index=T0 為基準）：
        thisWeek = daily_pcts[T0-4 : T0+1]   （最近5天，含當天）
        lastWeek = daily_pcts[T0-9 : T0-4]   （再往前5天）
    streak：重用共用工具 streak_utils.calc_streak()，餵入截到 cutoff_index 為止的子序列。

    Returns
    -------
    {"streak": int, "last_week_pct": float, "this_week_pct": float} 或
    None（cutoff_index < 9，可用歷史不足10天，無法同時算出兩個5日窗口）
    """
    if cutoff_index < 9:
        return None

    this_week_window = daily_pcts[cutoff_index - 4: cutoff_index + 1]
    last_week_window = daily_pcts[cutoff_index - 9: cutoff_index - 4]

    def _compound(window: List[float]) -> float:
        factor = 1.0
        for pct in window:
            factor *= (1 + pct / 100)
        return round((factor - 1) * 100, 2)

    this_week_pct = _compound(this_week_window)
    last_week_pct = _compound(last_week_window)
    streak = _streak(daily_pcts[:cutoff_index + 1])

    return {"streak": streak, "last_week_pct": last_week_pct, "this_week_pct": this_week_pct}
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_processors.py -k streak_and_windows_as_of -q`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add processors/performance.py tests/test_processors.py
git commit -m "feat(performance): 新增_streak_and_windows_as_of()回推任意時間點streak/上週/本週窗口"
```

---

### Task 2：`processors/performance.py::calc_meta_heatgrid_windows()` —— 查詢組裝今天+5天前的原始窗口值

**Files:**
- Modify: `processors/performance.py`
- Test: `tests/test_processors.py`

**Interfaces:**
- `calc_meta_heatgrid_windows(universe_df: pd.DataFrame, db_path: str = "data/screener.db") -> Dict[str, Dict[str, Any]]`：
  回傳 `{meta_name: {streak_today, last_week_pct_today, this_week_pct_today, streak_5d_ago, last_week_pct_5d_ago}}`。
  **只回傳原始數值，不做五級分類**（分類邏輯在 `export/index_generator.py`，見分層原則）。
  `this_week_pct_5d_ago` 不需要回傳，因為它就等於 `last_week_pct_today`（Task 1 已驗證這個窗口
  重疊關係），呼叫端直接重用即可。

- [ ] **Step 1: 寫失敗測試**

Append to `tests/test_processors.py`：

```python
import duckdb
from processors.performance import calc_meta_heatgrid_windows


def _seed_heatgrid_db(db_path, price_rows):
    """price_rows: list of (stock_id, date, change_pct)"""
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, change_pct DOUBLE)")
    con.executemany("INSERT INTO daily_prices VALUES (?, ?, ?)", price_rows)
    con.close()


def test_calc_meta_heatgrid_windows_computes_today_and_five_days_ago(tmp_path):
    """15天歷史，單一族群單一股票，全部+1.0%（連漲）：today跟5天前都應該算得出來(不是None)。"""
    db_path = tmp_path / "test.db"
    rows = [("1000", f"2026-06-{d:02d}", 1.0) for d in range(1, 16)]  # 06-01~06-15，15天
    _seed_heatgrid_db(db_path, rows)
    universe = pd.DataFrame([{"stock_id": "1000", "meta_sector": "測試族群"}])

    result = calc_meta_heatgrid_windows(universe, db_path=str(db_path))

    assert "測試族群" in result
    row = result["測試族群"]
    assert row["streak_today"] == 15
    assert row["streak_5d_ago"] == 10
    assert row["this_week_pct_today"] is not None
    assert row["last_week_pct_5d_ago"] is not None


def test_calc_meta_heatgrid_windows_five_days_ago_none_when_insufficient_history(tmp_path):
    """只有10天歷史：today算得出來(剛好卡在邊界)，5天前不足9天(_streak_and_windows_as_of的
    cutoff_index=4<9)，5天前的欄位應該是None，但不影響today的值。"""
    db_path = tmp_path / "test.db"
    rows = [("2000", f"2026-06-{d:02d}", 1.0) for d in range(1, 11)]  # 10天
    _seed_heatgrid_db(db_path, rows)
    universe = pd.DataFrame([{"stock_id": "2000", "meta_sector": "資料不足族群"}])

    result = calc_meta_heatgrid_windows(universe, db_path=str(db_path))

    row = result["資料不足族群"]
    assert row["streak_today"] == 10
    assert row["this_week_pct_today"] is not None
    assert row["streak_5d_ago"] is None
    assert row["last_week_pct_5d_ago"] is None


def test_calc_meta_heatgrid_windows_averages_multiple_stocks_in_same_meta(tmp_path):
    """族群內兩檔股票，每日取平均漲跌%再算streak/window，不是逐股各自算。"""
    db_path = tmp_path / "test.db"
    rows = []
    for d in range(1, 16):
        rows.append(("3000", f"2026-06-{d:02d}", 2.0))
        rows.append(("3001", f"2026-06-{d:02d}", 0.0))
    _seed_heatgrid_db(db_path, rows)
    universe = pd.DataFrame([
        {"stock_id": "3000", "meta_sector": "混合族群"},
        {"stock_id": "3001", "meta_sector": "混合族群"},
    ])

    result = calc_meta_heatgrid_windows(universe, db_path=str(db_path))

    # 每日平均 = (2.0+0.0)/2 = 1.0，15天複利 this_week_today ≈ (1.01^5-1)*100 = 5.10
    assert result["混合族群"]["this_week_pct_today"] == 5.1


def test_calc_meta_heatgrid_windows_returns_empty_dict_when_no_price_data(tmp_path):
    db_path = tmp_path / "empty.db"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, change_pct DOUBLE)")
    con.close()
    universe = pd.DataFrame([{"stock_id": "1000", "meta_sector": "測試族群"}])

    result = calc_meta_heatgrid_windows(universe, db_path=str(db_path))
    assert result == {}
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_processors.py -k calc_meta_heatgrid_windows -q`
Expected: FAIL（`ImportError: cannot import name 'calc_meta_heatgrid_windows'`）

- [ ] **Step 3: 實作**

Append to `processors/performance.py`（檔案最後，`_streak_and_windows_as_of()` 之後）：

```python
_HEATGRID_LOOKBACK_DAYS = 20  # 涵蓋今天(cutoff=最新)+5天前(cutoff=最新-5)都需要的15天history，留5天餘裕


def calc_meta_heatgrid_windows(
    universe_df: pd.DataFrame,
    db_path: str = "data/screener.db",
) -> Dict[str, Dict[str, Any]]:
    """
    對每個 meta_sector 算「今天」跟「5個交易日前」的 streak/上週/本週窗口原始數值，供族群總覽頁
    熱區格改版使用。**只回傳原始數值，不做五級分類**——分類邏輯（classify_tier）在
    export/index_generator.py，這支函式只負責查資料庫、算數字（跟 observation_scores.py 算原始
    rs_raw/breadth_raw 等因子、分類邏輯留給消費端的分工一致）。

    Returns
    -------
    {meta_name: {
        "streak_today": int, "last_week_pct_today": float, "this_week_pct_today": float,
        "streak_5d_ago": int | None, "last_week_pct_5d_ago": float | None,
    }}
    `this_week_pct_5d_ago` 不回傳：它等於 last_week_pct_today（見 Task 1 驗證過的窗口重疊
    關係），消費端直接重用 last_week_pct_today 即可，不用多存一份重複資料。
    """
    con = duckdb.connect(db_path, read_only=True)
    try:
        dates_df = con.execute(
            f"SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT {_HEATGRID_LOOKBACK_DAYS}"
        ).fetchdf()
        if dates_df.empty:
            return {}
        min_date = dates_df["date"].min()
        price_df = con.execute(
            "SELECT stock_id, date, change_pct FROM daily_prices WHERE date >= ?",
            [min_date],
        ).fetchdf()
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
    pct_pivot = (
        merged.groupby(["meta_sector", "date"])["change_pct"].mean()
        .unstack(level="date")
        .reindex(columns=all_dates)
    )

    today_index = len(all_dates) - 1
    five_days_ago_index = today_index - 5

    results: Dict[str, Dict[str, Any]] = {}
    for meta_name in pct_pivot.index:
        daily_pcts = [
            float(v) if pd.notna(v) else 0.0
            for v in pct_pivot.loc[meta_name].tolist()
        ]

        today_calc = _streak_and_windows_as_of(daily_pcts, today_index)
        if today_calc is None:
            results[meta_name] = {
                "streak_today": None, "last_week_pct_today": None, "this_week_pct_today": None,
                "streak_5d_ago": None, "last_week_pct_5d_ago": None,
            }
            continue

        five_days_ago_calc = (
            _streak_and_windows_as_of(daily_pcts, five_days_ago_index)
            if five_days_ago_index >= 0 else None
        )

        results[meta_name] = {
            "streak_today": today_calc["streak"],
            "last_week_pct_today": today_calc["last_week_pct"],
            "this_week_pct_today": today_calc["this_week_pct"],
            "streak_5d_ago": five_days_ago_calc["streak"] if five_days_ago_calc else None,
            "last_week_pct_5d_ago": five_days_ago_calc["last_week_pct"] if five_days_ago_calc else None,
        }

    return results
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_processors.py -k heatgrid -q`
Expected: PASS（9 passed，含 Task 1 的 5 個）

- [ ] **Step 5: Commit**

```bash
git add processors/performance.py tests/test_processors.py
git commit -m "feat(performance): 新增calc_meta_heatgrid_windows()查詢組裝今天+5天前的原始窗口值"
```

---

### Task 3：`export/index_generator.py`（新檔案）—— `classify_tier()`/`classify_temp()`/`heat_bg()`

**Files:**
- Create: `export/index_generator.py`
- Test: Create `tests/test_index_generator.py`

**Interfaces:**
- `classify_tier(streak: Optional[int], last_week_pct: Optional[float], this_week_pct: Optional[float]) -> dict | None`：
  回傳 `{"key": str, "label": str}`，`key ∈ {super,strong,mid,weak,superweak}`。任一輸入為
  `None` 時回傳 `None`。
- `classify_temp(accel: Optional[float]) -> dict | None`：回傳 `{"key": str, "label": str, "icon": str}`
  或 `None`（`|accel| < 5` 時不顯示徽章，`accel` 為 `None` 時同樣回 `None`）。
- `heat_bg(pct: float, max_abs_pct: float) -> str`：回傳 CSS `color-mix()` 字串。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_index_generator.py`：

```python
from export.index_generator import classify_tier, classify_temp, heat_bg


def test_classify_tier_superweak_when_streak_very_negative():
    assert classify_tier(-5, 1.0, -3.0) == {"key": "superweak", "label": "超弱"}
    assert classify_tier(-8, 1.0, -3.0) == {"key": "superweak", "label": "超弱"}


def test_classify_tier_super_when_streak_positive_and_accel_strong():
    # accel = this_week(6.0) - last_week(1.0) = 5.0 > 3
    assert classify_tier(3, 1.0, 6.0) == {"key": "super", "label": "超強"}


def test_classify_tier_strong_when_streak_positive_and_accel_stable():
    # accel = 2.0 - 1.0 = 1.0，介於-2~3之間
    assert classify_tier(3, 1.0, 2.0) == {"key": "strong", "label": "強"}


def test_classify_tier_weak_when_streak_negative_and_accel_declining():
    # accel = -5.0 - (-1.0) = -4.0 < -2
    assert classify_tier(-2, -1.0, -5.0) == {"key": "weak", "label": "弱"}


def test_classify_tier_mid_as_fallback():
    # streak=0（持平），不符合任何超強/強/弱/超弱條件
    assert classify_tier(0, 1.0, 1.5) == {"key": "mid", "label": "整理"}


def test_classify_tier_returns_none_when_any_input_is_none():
    assert classify_tier(None, 1.0, 2.0) is None
    assert classify_tier(3, None, 2.0) is None
    assert classify_tier(3, 1.0, None) is None


def test_classify_temp_hot_and_cold_thresholds():
    assert classify_temp(5.0) == {"key": "hot", "label": "增溫 +5.0pt", "icon": "🔥"}
    assert classify_temp(7.3) == {"key": "hot", "label": "增溫 +7.3pt", "icon": "🔥"}
    assert classify_temp(-5.0) == {"key": "cold", "label": "退燒 -5.0pt", "icon": "❄️"}
    assert classify_temp(4.9) is None  # 未達門檻
    assert classify_temp(-4.9) is None
    assert classify_temp(None) is None


def test_heat_bg_scales_alpha_by_relative_magnitude():
    up_full = heat_bg(10.0, max_abs_pct=10.0)  # t=1.0, alpha=0.66
    up_half = heat_bg(5.0, max_abs_pct=10.0)   # t=0.5, alpha=0.41
    down = heat_bg(-10.0, max_abs_pct=10.0)
    assert "var(--up)" in up_full and "66%" in up_full
    assert "var(--up)" in up_half and "41%" in up_half
    assert "var(--down)" in down


def test_heat_bg_handles_zero_max_abs_without_crash():
    """全市場今日漲跌全部剛好0%的極端情況（理論上不會發生，但不能讓除以0直接crash）。"""
    result = heat_bg(0.0, max_abs_pct=0.0)
    assert "var(--up)" in result  # pct=0視為非負，走up分支，alpha取t=0的最低值
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_index_generator.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'export.index_generator'`）

- [ ] **Step 3: 實作**

Create `export/index_generator.py`：

```python
"""
產生 docs/index.html — 族群總覽頁（熱區格版面）
資料來源：processors/performance.py 的 calc_meta_performance()/calc_meta_signals()/
         calc_meta_chips_signals()/calc_cumulative_meta()/calc_meta_heatgrid_windows()
視覺/互動設計：docs/superpowers/specs/2026-07-15-sector-overview-heatmap-redesign.md
技術落地設計：docs/superpowers/specs/2026-07-22-sector-overview-heatmap-implementation-design.md

刻意的設計決定：這個模組取代 export/html_generator.py 在 main.py::run() 裡的角色，但不刪除
舊檔案（沒有其他模組依賴它，保留當 rollback 用）。這個檔案完全不呼叫 duckdb.connect()——跟
專案其他 export/*_generator.py 檔案一致的分層慣例，DB 查詢一律在 processors/ 完成，這裡只吃
已經算好的原始數值做分類/渲染。

classify_tier() 是這個模組獨有的第三套「五級動能狀態」分類邏輯，跟
screener/signals.py::scan_momentum_health() 的 strength_tier、
export/momentum_generator.py::classify_sector_state() 都不共用計算依據——這裡故意只吃
streak + 5日窗口加速度，不查法人資料，換取 41 個族群卡片能快速全部算完。
"""
from typing import Any, Dict, List, Optional

_TIER_LABEL = {"super": "超強", "strong": "強", "mid": "整理", "weak": "弱", "superweak": "超弱"}

# 動能五級/溫度變化門檻：視覺spec定的經驗法則草案，沒有回測驗證（見 Global Constraints）。
_TIER_SUPERWEAK_STREAK = -5
_TIER_SUPER_ACCEL = 3
_TIER_STRONG_ACCEL_FLOOR = -2
_TIER_WEAK_ACCEL_CEIL = -2
_TEMP_THRESHOLD_PT = 5.0


def classify_tier(
    streak: Optional[int],
    last_week_pct: Optional[float],
    this_week_pct: Optional[float],
) -> Optional[Dict[str, str]]:
    """
    族群層級動能五級分類（草案，待回測，見 Global Constraints）。跟 scan_momentum_health()/
    classify_sector_state() 是獨立的第三套邏輯，只吃 streak + 本週比上週加速度，不查法人資料。

    任一輸入為 None 時回傳 None（資料不足，不硬湊等級）。
    """
    if streak is None or last_week_pct is None or this_week_pct is None:
        return None

    accel = this_week_pct - last_week_pct

    if streak <= _TIER_SUPERWEAK_STREAK:
        key = "superweak"
    elif streak > 0 and accel > _TIER_SUPER_ACCEL:
        key = "super"
    elif streak > 0 and accel >= _TIER_STRONG_ACCEL_FLOOR:
        key = "strong"
    elif streak < 0 and accel < _TIER_WEAK_ACCEL_CEIL:
        key = "weak"
    else:
        key = "mid"

    return {"key": key, "label": _TIER_LABEL[key]}


def classify_temp(accel: Optional[float]) -> Optional[Dict[str, str]]:
    """
    溫度變化徽章（草案門檻 ±5pt，見 Global Constraints）。刻意跟今日漲跌紅綠色系分開
    （橙=增溫/藍=退燒），因為這兩件事回答不同問題：一個族群今天可能還是紅的，但已經在退燒。
    |accel| < 5pt 或 accel 為 None 時回傳 None（不顯示徽章）。
    """
    if accel is None:
        return None
    if accel >= _TEMP_THRESHOLD_PT:
        return {"key": "hot", "label": f"增溫 +{accel:.1f}pt", "icon": "🔥"}
    if accel <= -_TEMP_THRESHOLD_PT:
        return {"key": "cold", "label": f"退燒 {accel:.1f}pt", "icon": "❄️"}
    return None


def heat_bg(pct: float, max_abs_pct: float) -> str:
    """
    熱區格卡片底色（紅漲綠跌，飽和度依當日漲跌幅相對全市場最大值算），直接對應視覺 spec 的
    heatBg() JS 函式。max_abs_pct=0（全市場今日漲跌全部剛好0%的極端情況）時 t 視為 0，
    不除以0。
    """
    t = min(abs(pct) / max_abs_pct, 1.0) if max_abs_pct > 0 else 0.0
    alpha = 0.16 + t * 0.5
    alpha_pct = round(alpha * 100)
    color_var = "var(--up)" if pct >= 0 else "var(--down)"
    return f"color-mix(in srgb, {color_var} {alpha_pct}%, var(--panel))"
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_index_generator.py -q`
Expected: PASS（10 passed）

- [ ] **Step 5: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index-generator): 新建export/index_generator.py，新增classify_tier/classify_temp/heat_bg"
```

---

### Task 4：`find_turning_points()`／`find_anomaly_cards()` —— 轉折點偵測、異動族群動態清單

**Files:**
- Modify: `export/index_generator.py`
- Test: `tests/test_index_generator.py`

**Interfaces:**
- `find_turning_points(heatgrid_windows: dict) -> list`：對每個族群用 `classify_tier()` 從原始
  窗口值算出 `tier_today`/`tier_last_week`（`tier_last_week` 用 `last_week_pct_today` 當
  `this_week_pct`，見 Task 1 驗證過的窗口重疊關係），兩者不同才列入。回傳
  `[{meta_name, prev_key, prev_label, cur_key, cur_label, direction}]`，
  `direction ∈ {"轉強訊號", "轉弱訊號，留意"}`。
- `find_anomaly_cards(meta_perf: list, meta_signals: dict, heatgrid_windows: dict) -> list`：
  動態產生異動族群卡片（不是固定 5 張）。回傳
  `[{kind, meta_name, pct, reason}]`，`kind ∈ {"burst", "trend"}`。
  - `爆量暴衝(burst)`：`meta_signals[meta]["vol_ratio"] >= 1.5` 且排名跳動
    `yesterday_rank - today_rank >= 10`（今日排名依 `avg_change_pct` 降冪算，第1名最高）。
  - `連續噴出(trend)`：`accel = this_week_pct_today - last_week_pct_today`，
    `classify_temp(accel)` 是 `"hot"` 且 `streak_today >= 5`（草案門檻，見 Global Constraints）。
  - 同一族群若同時符合兩種條件，`burst` 優先（跟現有 `momentum_generator.py` 的優先序寫法
    一致，量能異常訊號比週度加速度更即時）。

- [ ] **Step 1: 寫失敗測試**

Append to `tests/test_index_generator.py`：

```python
from export.index_generator import find_turning_points, find_anomaly_cards


def test_find_turning_points_detects_flip_and_labels_direction():
    heatgrid_windows = {
        "族群A": {  # 5天前弱(streak<0,accel<-2)，今天超強(streak>0,accel>3)
            "streak_today": 3, "last_week_pct_today": 1.0, "this_week_pct_today": 6.0,
            "streak_5d_ago": -2, "last_week_pct_5d_ago": 3.0,
        },
        "族群B": {  # 5天前強，今天弱
            "streak_today": -2, "last_week_pct_today": -1.0, "this_week_pct_today": -5.0,
            "streak_5d_ago": 3, "last_week_pct_5d_ago": -0.5,
        },
        "族群C": {  # 前後都整理(mid)，沒變化
            "streak_today": 0, "last_week_pct_today": 1.0, "this_week_pct_today": 1.5,
            "streak_5d_ago": 0, "last_week_pct_5d_ago": 1.0,
        },
    }
    result = find_turning_points(heatgrid_windows)

    names = {r["meta_name"] for r in result}
    assert names == {"族群A", "族群B"}
    a = next(r for r in result if r["meta_name"] == "族群A")
    assert a["direction"] == "轉強訊號"
    assert a["cur_key"] == "super" and a["prev_key"] == "weak"
    b = next(r for r in result if r["meta_name"] == "族群B")
    assert b["direction"] == "轉弱訊號，留意"


def test_find_turning_points_skips_when_five_days_ago_data_is_none():
    heatgrid_windows = {
        "資料不足族群": {
            "streak_today": 3, "last_week_pct_today": 1.0, "this_week_pct_today": 6.0,
            "streak_5d_ago": None, "last_week_pct_5d_ago": None,
        },
    }
    result = find_turning_points(heatgrid_windows)
    assert result == []


def test_find_anomaly_cards_burst_requires_volume_and_rank_jump():
    meta_perf = [
        {"meta_name": "爆量族群", "avg_change_pct": 5.0, "up_count": 1, "down_count": 0, "flat_count": 0},
        {"meta_name": "普通族群", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    meta_signals = {
        "爆量族群": {"vol_ratio": 1.8, "yesterday_rank": 15},  # 今日依avg_change_pct排序是#1，跳動14
        "普通族群": {"vol_ratio": 1.2, "yesterday_rank": 2},
    }
    heatgrid_windows = {
        "爆量族群": {"streak_today": 3, "last_week_pct_today": 1.0, "this_week_pct_today": 2.0,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},
        "普通族群": {"streak_today": 3, "last_week_pct_today": 1.0, "this_week_pct_today": 2.0,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},
    }
    result = find_anomaly_cards(meta_perf, meta_signals, heatgrid_windows)

    assert [r["meta_name"] for r in result] == ["爆量族群"]
    assert result[0]["kind"] == "burst"


def test_find_anomaly_cards_trend_requires_hot_temp_and_sustained_streak():
    meta_perf = [
        {"meta_name": "噴出族群", "avg_change_pct": 2.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    meta_signals = {"噴出族群": {"vol_ratio": 1.0, "yesterday_rank": 1}}
    heatgrid_windows = {
        # accel = 9.0 - 1.0 = 8.0 (>=5, hot)，streak_today=6 (>=5)
        "噴出族群": {"streak_today": 6, "last_week_pct_today": 1.0, "this_week_pct_today": 9.0,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},
    }

    result = find_anomaly_cards(meta_perf, meta_signals, heatgrid_windows)

    assert [r["meta_name"] for r in result] == ["噴出族群"]
    assert result[0]["kind"] == "trend"


def test_find_anomaly_cards_trend_not_triggered_when_streak_below_threshold():
    """accel達到hot門檻但streak<5(不夠持續)，不算連續噴出。"""
    meta_perf = [
        {"meta_name": "曇花一現", "avg_change_pct": 2.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    meta_signals = {"曇花一現": {"vol_ratio": 1.0, "yesterday_rank": 1}}
    heatgrid_windows = {
        "曇花一現": {"streak_today": 2, "last_week_pct_today": 1.0, "this_week_pct_today": 9.0,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},
    }

    result = find_anomaly_cards(meta_perf, meta_signals, heatgrid_windows)
    assert result == []


def test_find_anomaly_cards_burst_takes_precedence_over_trend_for_same_sector():
    meta_perf = [
        {"meta_name": "雙重訊號", "avg_change_pct": 5.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    meta_signals = {"雙重訊號": {"vol_ratio": 2.0, "yesterday_rank": 20}}  # burst條件成立
    heatgrid_windows = {
        # accel=8.0(hot), streak_today=6(>=5) → trend條件也成立
        "雙重訊號": {"streak_today": 6, "last_week_pct_today": 1.0, "this_week_pct_today": 9.0,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},
    }

    result = find_anomaly_cards(meta_perf, meta_signals, heatgrid_windows)
    assert len(result) == 1
    assert result[0]["kind"] == "burst"


def test_find_anomaly_cards_returns_empty_list_when_nothing_qualifies():
    meta_perf = [
        {"meta_name": "平淡族群", "avg_change_pct": 0.1, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    meta_signals = {"平淡族群": {"vol_ratio": 1.0, "yesterday_rank": 1}}
    heatgrid_windows = {
        "平淡族群": {"streak_today": 1, "last_week_pct_today": 1.0, "this_week_pct_today": 1.5,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},
    }

    result = find_anomaly_cards(meta_perf, meta_signals, heatgrid_windows)
    assert result == []
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_index_generator.py -k "turning_points or anomaly_cards" -q`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 實作**

Append to `export/index_generator.py`：

```python
_TIER_RANK = {"superweak": 0, "weak": 1, "mid": 2, "strong": 3, "super": 4}
_ANOMALY_VOL_RATIO_MIN = 1.5
_ANOMALY_RANK_JUMP_MIN = 10
_ANOMALY_TREND_STREAK_MIN = 5


def _accel_from_windows(window_data: Dict[str, Any]) -> Optional[float]:
    """this_week_pct_today - last_week_pct_today，任一為None時回None。"""
    this_week = window_data.get("this_week_pct_today")
    last_week = window_data.get("last_week_pct_today")
    if this_week is None or last_week is None:
        return None
    return round(this_week - last_week, 2)


def _tiers_from_windows(window_data: Dict[str, Any]) -> Dict[str, Optional[Dict[str, str]]]:
    """從calc_meta_heatgrid_windows()的原始數值算出tier_today/tier_last_week。
    tier_last_week重用last_week_pct_today當this_week(見Task1驗證過的窗口重疊關係)。"""
    tier_today = classify_tier(
        window_data.get("streak_today"),
        window_data.get("last_week_pct_today"),
        window_data.get("this_week_pct_today"),
    )
    tier_last_week = classify_tier(
        window_data.get("streak_5d_ago"),
        window_data.get("last_week_pct_5d_ago"),
        window_data.get("last_week_pct_today"),
    )
    return {"tier_today": tier_today, "tier_last_week": tier_last_week}


def find_turning_points(heatgrid_windows: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    轉折點列表（視覺spec用語：族群近況②）。比對 tier_today vs tier_last_week，真的換了一級
    才列入（不是幅度排序）。任一為 None（資料不足）或兩者相同時跳過。
    """
    results = []
    for meta_name, window_data in heatgrid_windows.items():
        tiers = _tiers_from_windows(window_data)
        cur = tiers["tier_today"]
        prev = tiers["tier_last_week"]
        if cur is None or prev is None or cur["key"] == prev["key"]:
            continue
        direction = "轉強訊號" if _TIER_RANK[cur["key"]] > _TIER_RANK[prev["key"]] else "轉弱訊號，留意"
        results.append({
            "meta_name": meta_name,
            "prev_key": prev["key"], "prev_label": prev["label"],
            "cur_key": cur["key"], "cur_label": cur["label"],
            "direction": direction,
        })
    return results


def find_anomaly_cards(
    meta_perf: List[Dict[str, Any]],
    meta_signals: Dict[str, Dict[str, Any]],
    heatgrid_windows: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    異動族群動態清單（視覺spec用語：頁面最上方快報，今日vs昨日的瞬間訊號）。不是固定5張卡，
    符合條件有幾檔就回傳幾檔（見實作 spec §3）。門檻是視覺 spec 定的經驗法則草案，待回測
    （見 Global Constraints）。

    爆量暴衝(burst)：vol_ratio >= 1.5 且今日排名比昨日跳動 >= 10（今日排名依 avg_change_pct
    降冪計算，第1名跳動幅度最大）。
    連續噴出(trend)：classify_temp(accel)=="hot" 且 streak_today >= 5（草案，要求持續而非
    曇花一現）。
    同一族群兩者都成立時，burst 優先（量能異常是更即時的訊號）。
    """
    ranked = sorted(meta_perf, key=lambda r: r["avg_change_pct"], reverse=True)
    today_rank = {row["meta_name"]: i + 1 for i, row in enumerate(ranked)}
    pct_map = {row["meta_name"]: row["avg_change_pct"] for row in meta_perf}

    results = []
    for meta_name in pct_map:
        sig = meta_signals.get(meta_name, {})
        window_data = heatgrid_windows.get(meta_name, {})
        vol_ratio = sig.get("vol_ratio")
        yesterday_rank = sig.get("yesterday_rank")
        accel = _accel_from_windows(window_data)
        streak_today = window_data.get("streak_today")

        is_burst = (
            vol_ratio is not None and vol_ratio >= _ANOMALY_VOL_RATIO_MIN
            and yesterday_rank is not None
            and (yesterday_rank - today_rank[meta_name]) >= _ANOMALY_RANK_JUMP_MIN
        )
        if is_burst:
            results.append({
                "kind": "burst", "meta_name": meta_name, "pct": pct_map[meta_name],
                "reason": f"今日量能 {vol_ratio}x 於5日均量，昨日#{yesterday_rank}→今日#{today_rank[meta_name]}",
            })
            continue

        temp = classify_temp(accel) if accel is not None else None
        is_trend = (
            temp is not None and temp["key"] == "hot"
            and streak_today is not None and streak_today >= _ANOMALY_TREND_STREAK_MIN
        )
        if is_trend:
            last_week_pct = window_data.get("last_week_pct_today")
            this_week_pct = window_data.get("this_week_pct_today")
            results.append({
                "kind": "trend", "meta_name": meta_name, "pct": pct_map[meta_name],
                "reason": f"上週 {last_week_pct:+.1f}% → 本週 {this_week_pct:+.1f}%　加速 {accel:+.1f}pt",
            })

    return results
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_index_generator.py -q`
Expected: PASS（19 passed）

- [ ] **Step 5: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index-generator): 新增find_turning_points/find_anomaly_cards(轉折點/異動族群動態清單)"
```

---

### Task 5：`build_heatgrid_cards()` —— 熱區格 41 張卡片資料組裝

**Files:**
- Modify: `export/index_generator.py`
- Test: `tests/test_index_generator.py`

**Interfaces:**
- `build_heatgrid_cards(meta_perf: list, meta_signals: dict, meta_chips: dict, heatgrid_windows: dict) -> list`：
  依 `avg_change_pct` 降冪排列（rank 1~N），每筆組裝成卡片渲染需要的完整欄位（含
  `classify_tier`/`classify_temp`/`heat_bg` 的分類結果）。`heat_bg()` 用的 `max_abs_pct` 在
  這支函式內部算一次（across 全部族群），不需要呼叫端傳。

- [ ] **Step 1: 寫失敗測試**

Append to `tests/test_index_generator.py`：

```python
from export.index_generator import build_heatgrid_cards


def test_build_heatgrid_cards_ranks_by_avg_change_pct_and_includes_all_fields():
    meta_perf = [
        {"meta_name": "族群A", "avg_change_pct": 5.0, "up_count": 10, "down_count": 2, "flat_count": 1},
        {"meta_name": "族群B", "avg_change_pct": -3.0, "up_count": 2, "down_count": 10, "flat_count": 0},
    ]
    meta_signals = {
        "族群A": {"streak": 5, "vol_ratio": 1.8, "yesterday_rank": 3},
        "族群B": {"streak": -2, "vol_ratio": 1.1, "yesterday_rank": 1},
    }
    meta_chips = {
        "族群A": {"foreign_streak": 3, "trust_streak": 0},
        "族群B": {"foreign_streak": -1, "trust_streak": 2},
    }
    heatgrid_windows = {
        "族群A": {"streak_today": 3, "last_week_pct_today": 1.0, "this_week_pct_today": 6.0,
                  "streak_5d_ago": None, "last_week_pct_5d_ago": None},
        "族群B": {"streak_today": -2, "last_week_pct_today": -1.0, "this_week_pct_today": -3.5,
                  "streak_5d_ago": None, "last_week_pct_5d_ago": None},
    }

    cards = build_heatgrid_cards(meta_perf, meta_signals, meta_chips, heatgrid_windows)

    assert [c["meta_name"] for c in cards] == ["族群A", "族群B"]
    assert cards[0]["rank"] == 1
    assert cards[1]["rank"] == 2
    a = cards[0]
    assert a["pct"] == 5.0
    assert a["up_count"] == 10 and a["down_count"] == 2
    assert a["tier"] == {"key": "super", "label": "超強"}  # streak=3>0, accel=6.0-1.0=5.0>3
    assert a["foreign_streak"] == 3 and a["trust_streak"] == 0
    assert a["last_week_pct"] == 1.0 and a["this_week_pct"] == 6.0
    assert "color-mix" in a["heat_bg"]


def test_build_heatgrid_cards_handles_missing_signals_gracefully():
    """meta_signals/meta_chips/heatgrid_windows某族群缺資料時(例如新族群還沒被算過)不crash，
    相關欄位回None/預設值，不是KeyError。"""
    meta_perf = [
        {"meta_name": "新族群", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    cards = build_heatgrid_cards(meta_perf, {}, {}, {})

    assert cards[0]["meta_name"] == "新族群"
    assert cards[0]["tier"] is None
    assert cards[0]["foreign_streak"] is None
    assert cards[0]["streak"] is None
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_index_generator.py -k build_heatgrid_cards -q`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 實作**

Append to `export/index_generator.py`：

```python
def build_heatgrid_cards(
    meta_perf: List[Dict[str, Any]],
    meta_signals: Dict[str, Dict[str, Any]],
    meta_chips: Dict[str, Dict[str, Any]],
    heatgrid_windows: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    熱區格 41 張卡片資料（視覺 spec §3「族群排行」），依 avg_change_pct 降冪排列。組合
    meta_perf（今日漲跌/家數）+ meta_signals（量比，既有函式）+ meta_chips（外資/投信連買
    天數，既有函式）+ heatgrid_windows（processors/performance.py::calc_meta_heatgrid_windows()
    算的原始窗口值，這裡才做 classify_tier/classify_temp 分類）。
    """
    ranked = sorted(meta_perf, key=lambda r: r["avg_change_pct"], reverse=True)
    max_abs_pct = max((abs(r["avg_change_pct"]) for r in ranked), default=0.0)

    cards = []
    for i, row in enumerate(ranked):
        meta_name = row["meta_name"]
        sig = meta_signals.get(meta_name, {})
        chips = meta_chips.get(meta_name, {})
        window_data = heatgrid_windows.get(meta_name, {})
        pct = row["avg_change_pct"]
        accel = _accel_from_windows(window_data)

        cards.append({
            "rank": i + 1,
            "meta_name": meta_name,
            "pct": pct,
            "up_count": row["up_count"],
            "down_count": row["down_count"],
            "streak": window_data.get("streak_today"),
            "vol_ratio": sig.get("vol_ratio"),
            "foreign_streak": chips.get("foreign_streak"),
            "trust_streak": chips.get("trust_streak"),
            "last_week_pct": window_data.get("last_week_pct_today"),
            "this_week_pct": window_data.get("this_week_pct_today"),
            "accel": accel,
            "tier": classify_tier(
                window_data.get("streak_today"),
                window_data.get("last_week_pct_today"),
                window_data.get("this_week_pct_today"),
            ),
            "temp": classify_temp(accel),
            "heat_bg": heat_bg(pct, max_abs_pct),
        })
    return cards
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_index_generator.py -q`
Expected: PASS（21 passed）

- [ ] **Step 5: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index-generator): 新增build_heatgrid_cards()組裝41張熱區格卡片資料"
```

---

### Task 6：`build_sector_recap()` —— 升溫/退燒 Top5 + 轉折點列表格式化

**Files:**
- Modify: `export/index_generator.py`
- Test: `tests/test_index_generator.py`

**Interfaces:**
- `build_sector_recap(meta_perf: list, heatgrid_windows: dict) -> dict`：回傳
  `{"hot_top5": [...], "cold_top5": [...], "turning_points": [...]}`。`hot_top5`/`cold_top5`
  依 `accel`（`_accel_from_windows()` 算出）排序，`accel` 為 `None` 的族群排除，不參與排序
  （資料不足代表無法判斷升溫/退燒）。`turning_points` 呼叫 Task 4 的 `find_turning_points()`，
  但傳入前**必須先用 `meta_perf` 過濾 `heatgrid_windows`**（只保留當下還在 `meta_perf` 裡的
  族群）——`main.py` 呼叫 `calc_meta_performance()` 跟 `calc_meta_heatgrid_windows()` 是兩個
  獨立呼叫，各自有獨立的失敗模式，理論上兩邊回傳的族群集合可能不完全一致；`hot_top5`/
  `cold_top5` 已經用 `pct_map`（衍生自 `meta_perf`）排除了不在 `meta_perf` 裡的族群，
  `turning_points` 若直接吃未過濾的 `heatgrid_windows` 會產生「同一個回傳值裡，`hot_top5`/
  `cold_top5` 排除了某族群、但 `turning_points` 卻還顯示它」的不一致（Task 4 code review
  提前讀到這支函式的規格後發現的落地前風險，這裡在寫 Task 6 之前直接修正，不留到之後才補）。

- [ ] **Step 1: 寫失敗測試**

Append to `tests/test_index_generator.py`：

```python
from export.index_generator import build_sector_recap


def test_build_sector_recap_sorts_hot_and_cold_by_accel():
    meta_perf = [
        {"meta_name": "升溫族群", "avg_change_pct": 3.0, "up_count": 1, "down_count": 0, "flat_count": 0},
        {"meta_name": "退燒族群", "avg_change_pct": -1.0, "up_count": 0, "down_count": 1, "flat_count": 0},
        {"meta_name": "普通族群", "avg_change_pct": 0.5, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    heatgrid_windows = {
        "升溫族群": {"streak_today": 3, "last_week_pct_today": 1.0, "this_week_pct_today": 9.0,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},  # accel=8.0
        "退燒族群": {"streak_today": -2, "last_week_pct_today": 1.0, "this_week_pct_today": -5.0,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},  # accel=-6.0
        "普通族群": {"streak_today": 1, "last_week_pct_today": 1.0, "this_week_pct_today": 1.5,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},  # accel=0.5
    }

    recap = build_sector_recap(meta_perf, heatgrid_windows)

    assert recap["hot_top5"][0]["meta_name"] == "升溫族群"
    assert recap["cold_top5"][0]["meta_name"] == "退燒族群"


def test_build_sector_recap_excludes_none_accel_from_hot_cold_ranking():
    meta_perf = [
        {"meta_name": "資料不足", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
        {"meta_name": "正常族群", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    heatgrid_windows = {
        "資料不足": {"streak_today": None, "last_week_pct_today": None, "this_week_pct_today": None,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},
        "正常族群": {"streak_today": 1, "last_week_pct_today": 1.0, "this_week_pct_today": 3.0,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},
    }

    recap = build_sector_recap(meta_perf, heatgrid_windows)

    hot_names = [r["meta_name"] for r in recap["hot_top5"]]
    assert "資料不足" not in hot_names
    assert "正常族群" in hot_names


def test_build_sector_recap_includes_turning_points():
    meta_perf = [
        {"meta_name": "翻轉族群", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    heatgrid_windows = {
        "翻轉族群": {"streak_today": 3, "last_week_pct_today": 1.0, "this_week_pct_today": 6.0,
                    "streak_5d_ago": -2, "last_week_pct_5d_ago": 3.5},
    }
    recap = build_sector_recap(meta_perf, heatgrid_windows)
    assert recap["turning_points"][0]["meta_name"] == "翻轉族群"
    assert recap["turning_points"][0]["direction"] == "轉強訊號"


def test_build_sector_recap_excludes_stale_sector_from_turning_points():
    """heatgrid_windows有某族群的翻轉資料，但meta_perf(當下有效族群清單)已經不包含它
    (例如calc_meta_performance()跟calc_meta_heatgrid_windows()兩個獨立呼叫，某次族群集合
    不一致)——turning_points不能顯示這個已經不在meta_perf裡的族群，要跟hot_top5/cold_top5
    的過濾邏輯一致(這是Task 4 code review提前發現的落地前風險，Task 6一開始就要防)。"""
    meta_perf = [
        {"meta_name": "有效族群", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    heatgrid_windows = {
        "有效族群": {"streak_today": 1, "last_week_pct_today": 1.0, "this_week_pct_today": 1.5,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},
        "已下架族群": {  # 有真實翻轉(弱→超強)，但不在meta_perf裡
            "streak_today": 3, "last_week_pct_today": 1.0, "this_week_pct_today": 6.0,
            "streak_5d_ago": -2, "last_week_pct_5d_ago": 3.5,
        },
    }
    recap = build_sector_recap(meta_perf, heatgrid_windows)
    turning_names = [r["meta_name"] for r in recap["turning_points"]]
    assert "已下架族群" not in turning_names
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_index_generator.py -k build_sector_recap -q`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 實作**

Append to `export/index_generator.py`：

```python
_SECTOR_RECAP_TOP_N = 5


def build_sector_recap(
    meta_perf: List[Dict[str, Any]],
    heatgrid_windows: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    族群近況（視覺 spec §4）：升溫/退燒雙欄 Top5 + 轉折點列表。accel 為 None（資料不足）的
    族群不參與升溫/退燒排序（沒有依據判斷是升溫還是退燒，不能硬排進去）。
    """
    pct_map = {row["meta_name"]: row["avg_change_pct"] for row in meta_perf}
    with_accel = []
    for meta_name, window_data in heatgrid_windows.items():
        if meta_name not in pct_map:
            continue
        accel = _accel_from_windows(window_data)
        if accel is None:
            continue
        with_accel.append({"meta_name": meta_name, "pct": pct_map[meta_name], "accel": accel})

    hot_top5 = sorted(with_accel, key=lambda r: r["accel"], reverse=True)[:_SECTOR_RECAP_TOP_N]
    cold_top5 = sorted(with_accel, key=lambda r: r["accel"])[:_SECTOR_RECAP_TOP_N]

    # turning_points 傳入前先用 pct_map（衍生自 meta_perf）過濾 heatgrid_windows，跟上面
    # hot_top5/cold_top5 的排除邏輯保持一致——calc_meta_performance()/calc_meta_heatgrid_windows()
    # 是main.py裡兩個獨立呼叫，理論上族群集合可能不完全一致，不過濾會讓同一個回傳值裡
    # hot_top5/cold_top5排除了某族群、但turning_points卻還顯示它，是自相矛盾的輸出。
    active_windows = {name: data for name, data in heatgrid_windows.items() if name in pct_map}

    return {
        "hot_top5": hot_top5,
        "cold_top5": cold_top5,
        "turning_points": find_turning_points(active_windows),
    }
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_index_generator.py -q`
Expected: PASS（25 passed）

- [ ] **Step 5: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index-generator): 新增build_sector_recap()組裝升溫/退燒Top5+轉折點列表"
```

---

### Task 7：`build_stock_detail_data()` —— 個股點開面板資料（每族群成分股清單）

**Files:**
- Modify: `export/index_generator.py`
- Test: `tests/test_index_generator.py`

**Interfaces:**
- `build_stock_detail_data(universe_df: pd.DataFrame, prices_df: pd.DataFrame) -> Dict[str, list]`：
  回傳 `{meta_name: [{"stock_id","stock_name","close","change_pct"}, ...]}`，族群內依
  `change_pct` 降冪排列。沒有行情資料的股票直接跳過（不補假資料），全部 41 個族群都要有 key
  （即使該族群成分股清單是空 list），不能只回傳有資料的族群。

- [ ] **Step 1: 寫失敗測試**

Append to `tests/test_index_generator.py`（先加一行 import）：

```python
import pandas as pd
from export.index_generator import build_stock_detail_data


def test_build_stock_detail_data_groups_by_meta_and_sorts_by_change_pct():
    universe_df = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "股票甲", "meta_sector": "族群A"},
        {"stock_id": "1001", "stock_name": "股票乙", "meta_sector": "族群A"},
        {"stock_id": "2000", "stock_name": "股票丙", "meta_sector": "族群B"},
    ])
    prices_df = pd.DataFrame([
        {"stock_id": "1000", "close": 100.0, "change_pct": 2.0},
        {"stock_id": "1001", "close": 50.0, "change_pct": 5.0},
        {"stock_id": "2000", "close": 30.0, "change_pct": -1.0},
    ])

    result = build_stock_detail_data(universe_df, prices_df)

    assert [s["stock_id"] for s in result["族群A"]] == ["1001", "1000"]  # 5.0 > 2.0
    assert result["族群B"][0]["stock_id"] == "2000"


def test_build_stock_detail_data_includes_all_meta_sectors_even_with_no_price_data():
    """族群存在universe裡但完全沒有對應行情資料時，仍要有這個key(空list)，不能整個族群消失。"""
    universe_df = pd.DataFrame([
        {"stock_id": "9999", "stock_name": "無行情股", "meta_sector": "空資料族群"},
    ])
    prices_df = pd.DataFrame(columns=["stock_id", "close", "change_pct"])

    result = build_stock_detail_data(universe_df, prices_df)

    assert result["空資料族群"] == []


def test_build_stock_detail_data_skips_individual_stock_missing_price():
    """族群內部分股票有行情、部分沒有：有行情的股票正常列出，沒行情的那檔跳過(不補假資料)。"""
    universe_df = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "有行情", "meta_sector": "族群C"},
        {"stock_id": "1001", "stock_name": "無行情", "meta_sector": "族群C"},
    ])
    prices_df = pd.DataFrame([{"stock_id": "1000", "close": 10.0, "change_pct": 1.0}])

    result = build_stock_detail_data(universe_df, prices_df)

    assert len(result["族群C"]) == 1
    assert result["族群C"][0]["stock_id"] == "1000"
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_index_generator.py -k build_stock_detail_data -q`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 實作**

Append to `export/index_generator.py`（檔案開頭 import 區塊補上 `pandas`）：

```python
import pandas as pd
```

（放在檔案最上方 `from typing import ...` 之後）

在檔案最後新增：

```python
def build_stock_detail_data(
    universe_df: pd.DataFrame,
    prices_df: pd.DataFrame,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    個股點開面板資料（視覺 spec §「點開個股清單」）。全部 meta_sector 都要有 key（即使該族群
    沒有任何股票有行情資料，回空 list），族群內依 change_pct 降冪排列。沒行情的個股跳過，不補
    假資料（跟 processors/performance.py 現有 join 慣例一致）。
    """
    universe = universe_df[["stock_id", "stock_name", "meta_sector"]].copy()
    universe["stock_id"] = universe["stock_id"].astype(str)
    prices = prices_df.copy()
    if not prices.empty:
        prices["stock_id"] = prices["stock_id"].astype(str)
    prices_map = prices.set_index("stock_id") if not prices.empty else pd.DataFrame()

    result: Dict[str, List[Dict[str, Any]]] = {
        meta_name: [] for meta_name in universe["meta_sector"].dropna().unique()
    }

    for _, row in universe.iterrows():
        sid = row["stock_id"]
        meta_name = row["meta_sector"]
        if pd.isna(meta_name) or sid not in prices_map.index:
            continue
        p = prices_map.loc[sid]
        result[meta_name].append({
            "stock_id": sid,
            "stock_name": row["stock_name"],
            "close": float(p["close"]),
            "change_pct": float(p["change_pct"]),
        })

    for meta_name in result:
        result[meta_name].sort(key=lambda s: s["change_pct"], reverse=True)

    return result
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_index_generator.py -q`
Expected: PASS（27 passed）

- [ ] **Step 5: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index-generator): 新增build_stock_detail_data()組裝個股點開面板資料"
```

---

### Task 8：`generate()` —— HTML/CSS/JS 頁面組裝

**Files:**
- Modify: `export/index_generator.py`（新增 `generate()`、CSS 常數、render helper 函式，加在檔案
  最後）
- Test: `tests/test_index_generator.py`

**Interfaces:**
- `generate(trade_date: date, meta_perf: list, universe_df: pd.DataFrame, meta_signals: dict, meta_chips: dict, prices_df: pd.DataFrame, heatgrid_windows: dict, output_path: str = "docs/index.html") -> None`：
  `meta_perf` 為空時直接 `return`（不寫檔，比照舊 `html_generator.py::generate()` 既有慣例）。

**安全寫法**：熱區格/異動族群卡片一律 `onclick="selectGroup(this.dataset.metaName)"`（讀 DOM
屬性），不要把族群名稱字串內插進 `onclick="selectGroup('...')"`——族群名稱可能含 `/`（例如
「機器人/自動化」），直接內插進單引號字串會破壞 HTML/JS。`selectGroup(name)` 內部用
`tiles.find(t => t.dataset.metaName === name)`（JS 相等比較）找卡片，不是拼字串組 CSS selector。

- [ ] **Step 1: 寫失敗測試**

Append to `tests/test_index_generator.py`（先加一行 import）：

```python
from datetime import date
from export.index_generator import generate


def _sample_meta_perf():
    return [
        {"meta_name": "測試族群", "avg_change_pct": 3.5, "up_count": 5, "down_count": 1, "flat_count": 0},
    ]


def _sample_universe_df():
    return pd.DataFrame([
        {"stock_id": "1000", "stock_name": "測試股", "meta_sector": "測試族群"},
    ])


def _sample_prices_df():
    return pd.DataFrame([
        {"stock_id": "1000", "close": 100.0, "change_pct": 3.5},
    ])


def test_generate_returns_early_and_skips_write_when_meta_perf_empty(tmp_path):
    output_path = tmp_path / "index.html"

    generate(date(2026, 7, 22), [], pd.DataFrame(), {}, {}, pd.DataFrame(), {}, output_path=str(output_path))

    assert not output_path.exists()


def test_generate_writes_page_with_all_41_style_sectors_present(tmp_path):
    """41個族群全部要有卡片，這裡用3個族群模擬同樣的「全部要出現」要求
    （呼應2026-07-09 index.html只render部分族群導致連結靜默失敗的回歸測試精神）。"""
    output_path = tmp_path / "index.html"
    meta_perf = [
        {"meta_name": f"族群{i}", "avg_change_pct": float(i) - 1, "up_count": 1, "down_count": 0, "flat_count": 0}
        for i in range(3)
    ]
    universe_df = pd.DataFrame([
        {"stock_id": f"100{i}", "stock_name": f"股票{i}", "meta_sector": f"族群{i}"} for i in range(3)
    ])
    prices_df = pd.DataFrame([
        {"stock_id": f"100{i}", "close": 10.0 + i, "change_pct": float(i) - 1} for i in range(3)
    ])

    generate(date(2026, 7, 22), meta_perf, universe_df, {}, {}, prices_df, {}, output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    import re
    names_present = set(re.findall(r'data-meta-name="(族群\d)"', html))
    assert names_present == {"族群0", "族群1", "族群2"}


def test_generate_escapes_malicious_meta_and_stock_name(tmp_path):
    """族群名稱/股票名稱來自stock_universe.csv，頁面發布到GitHub Pages，比照既有generator防護。"""
    output_path = tmp_path / "index.html"
    meta_perf = [
        {"meta_name": "<script>alert(1)</script>", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    universe_df = pd.DataFrame([
        {"stock_id": "9999", "stock_name": "<img onerror=alert(2)>", "meta_sector": "<script>alert(1)</script>"},
    ])
    prices_df = pd.DataFrame([{"stock_id": "9999", "close": 1.0, "change_pct": 1.0}])

    generate(date(2026, 7, 22), meta_perf, universe_df, {}, {}, prices_df, {}, output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "<img onerror=alert(2)>" not in html


def test_generate_uses_this_dataset_metaname_not_raw_string_interpolation(tmp_path):
    """族群名稱含斜線(例如「機器人/自動化」)時，onclick不能直接內插原始名稱字串，
    必須用this.dataset.metaName讀DOM屬性——這是最容易在改版時不小心退化回不安全寫法的地方。"""
    output_path = tmp_path / "index.html"
    meta_perf = [
        {"meta_name": "機器人/自動化", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    universe_df = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "測試股", "meta_sector": "機器人/自動化"},
    ])
    prices_df = pd.DataFrame([{"stock_id": "1000", "close": 10.0, "change_pct": 1.0}])

    generate(date(2026, 7, 22), meta_perf, universe_df, {}, {}, prices_df, {}, output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert "onclick=\"selectGroup('機器人/自動化')\"" not in html
    assert "onclick=\"selectGroup(this.dataset.metaName)\"" in html


def test_generate_includes_nav_links_to_other_three_pages(tmp_path):
    output_path = tmp_path / "index.html"
    generate(date(2026, 7, 22), _sample_meta_perf(), _sample_universe_df(), {}, {}, _sample_prices_df(), {}, output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert 'href="chips.html"' in html
    assert 'href="patterns.html"' in html
    assert 'href="momentum.html"' in html


def test_generate_renders_anomaly_section_empty_state_when_no_cards_qualify(tmp_path):
    output_path = tmp_path / "index.html"
    generate(date(2026, 7, 22), _sample_meta_perf(), _sample_universe_df(), {}, {}, _sample_prices_df(), {}, output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert "目前沒有族群符合" in html  # 0張異動族群卡片時的誠實空狀態文案
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_index_generator.py -k generate -q`
Expected: FAIL（`ImportError: cannot import name 'generate'`）

- [ ] **Step 3: 實作**

在 `export/index_generator.py` 檔案開頭 import 區塊補上：

```python
from datetime import date
from html import escape as _html_escape
from pathlib import Path
```

（`pandas`/`typing` 既有 import 保留，這三行加在它們之後）

在檔案最後加入：

```python
def _esc(value) -> str:
    """HTML-escape 外部資料（族群/股票名稱等），比照 chips_generator.py::_esc() 同一防護。"""
    return _html_escape(str(value)) if value else ""


_CSS = """
:root{
  --bg:#080B12; --panel:#0F1420; --panel-2:#161D2C; --panel-3:#1E2738;
  --border:#293346; --border-2:#37435C;
  --ink:#DADFE8; --ink-2:#98A0B4; --ink-3:#636B80;
  --up:#E6432F; --down:#37B25C;
  --accent:#F0BB55; --accent-dim:#B98A3A;
  --burst:#F0BB55; --trend:#C77FBD;
  --tier-super:#F0BB55; --tier-strong:#4FC46A; --tier-mid:#8B94AC; --tier-weak:#E08A3E; --tier-superweak:#E6432F;
  --heat-hot:#FF7A3D; --heat-cold:#4FA8E8;
  --serif: Georgia,"Iowan Old Style","Source Serif 4","Noto Serif TC",serif;
  --sans: "Public Sans",-apple-system,"PingFang TC","Microsoft JhengHei","Segoe UI",sans-serif;
  --mono: ui-monospace,"IBM Plex Mono","Cascadia Code","Roboto Mono",monospace;
  --shadow-1: 0 1px 2px rgba(0,0,0,.35);
  --shadow-2: 0 10px 28px rgba(0,0,0,.5), 0 2px 6px rgba(0,0,0,.35);
}
:root[data-theme="light"]{
  --bg:#EFE8D8; --panel:#F8F3E6; --panel-2:#EAE1CB; --panel-3:#E0D5B8;
  --border:#D6C9A3; --border-2:#C3B387;
  --ink:#241C10; --ink-2:#6B5B3D; --ink-3:#93825E;
  --up:#A8432C; --down:#3D7048;
  --accent:#93701E; --accent-dim:#C4A24E;
  --burst:#93701E; --trend:#7A4E6E;
  --tier-super:#93701E; --tier-strong:#3D7048; --tier-mid:#7A7260; --tier-weak:#9A5A24; --tier-superweak:#A8432C;
  --heat-hot:#C05A20; --heat-cold:#2E6FA3;
  --shadow-1: 0 1px 2px rgba(60,45,10,.1);
  --shadow-2: 0 10px 28px rgba(60,45,10,.16), 0 2px 6px rgba(60,45,10,.1);
}
*{box-sizing:border-box}
body{
  margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:14px;line-height:1.55;padding:0 0 80px;
  background-image:radial-gradient(ellipse at top left, rgba(255,255,255,.04), transparent 55%);
}
.tabular{font-family:var(--mono);font-variant-numeric:tabular-nums}
a{color:inherit}
.skip-link{position:absolute;left:-999px;top:0;background:var(--panel);color:var(--ink);padding:8px 14px;z-index:100}
.skip-link:focus{left:8px;top:8px}

.topbar{display:flex;align-items:baseline;gap:16px;padding:20px 26px;border-bottom:1px solid var(--border);flex-wrap:wrap}
.topbar h1{font-family:var(--serif);font-size:1.28rem;font-weight:600;color:var(--ink);letter-spacing:.01em;margin:0}
.topbar .kicker{font-size:.62rem;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--accent)}
.topbar .updated{font-size:.72rem;color:var(--ink-3);margin-left:auto;font-family:var(--mono)}
.topbar button{font-family:var(--mono);font-size:.68rem;background:var(--panel-2);border:1px solid var(--border);color:var(--ink-2);padding:5px 12px;border-radius:4px;cursor:pointer}
.nav-links{display:flex;gap:8px}
.nav-link{font-size:.78rem;padding:5px 14px;border-radius:6px;border:1px solid var(--border);color:var(--ink-2);text-decoration:none}
.nav-link:hover{border-color:var(--ink-2);color:var(--ink)}
.nav-link.active{border-color:var(--accent);color:var(--ink);background:var(--panel-2)}
.nav-link:focus-visible,button:focus-visible,.heat-tile:focus-visible,.anomaly-card:focus-visible{outline:3px solid var(--accent);outline-offset:2px}

.section-head{display:flex;align-items:baseline;gap:12px;padding:26px 26px 8px}
.section-head h2{font-family:var(--serif);font-size:1.05rem;font-weight:600;color:var(--ink);margin:0}
.section-head .count{font-family:var(--mono);font-size:.7rem;color:var(--ink-3)}
.section-rule{height:1px;background:linear-gradient(to right,var(--ink) 0%,var(--border) 45%,transparent 100%);margin:0 26px 4px}
.section-sub{padding:0 26px 14px;font-size:.76rem;color:var(--ink-2);max-width:720px}

.anomaly-wrap{position:relative;margin:0 26px}
.anomaly-strip{display:flex;gap:14px;overflow-x:auto;padding:2px 2px 6px}
.anomaly-wrap::after{content:"";position:absolute;top:0;right:0;bottom:6px;width:44px;pointer-events:none;background:linear-gradient(to right, transparent, var(--bg) 88%)}
.anomaly-card{flex:0 0 240px;background:var(--panel);border:1px solid var(--border);border-radius:4px;padding:15px 17px;position:relative;cursor:pointer;transition:box-shadow .2s,transform .2s,border-color .2s}
.anomaly-card:hover{border-color:var(--border-2);transform:translateY(-2px)}
.anomaly-card::before{content:"";position:absolute;left:0;top:15px;bottom:15px;width:2px;border-radius:2px}
.anomaly-card.burst::before{background:var(--burst)} .anomaly-card.trend::before{background:var(--trend)}
.anomaly-kind{font-size:.6rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;margin-bottom:8px}
.anomaly-kind.burst{color:var(--burst)} .anomaly-kind.trend{color:var(--trend)}
.anomaly-name{font-family:var(--serif);font-weight:600;font-size:1.0rem;color:var(--ink)}
.anomaly-pct{font-family:var(--mono);font-weight:600;font-size:1.02rem;color:var(--up);float:right}
.anomaly-reason{margin-top:10px;font-size:.72rem;color:var(--ink-2);line-height:1.6;padding-top:9px;border-top:1px solid var(--border)}
.anomaly-empty{color:var(--ink-3);font-size:.82rem;font-style:italic;padding:8px 2px}

.tier-legend{display:flex;gap:16px;padding:0 26px 16px;font-size:.68rem;color:var(--ink-2);flex-wrap:wrap;font-family:var(--mono)}
.tier-legend span{display:inline-flex;align-items:center;gap:5px}
.tier-legend .dot{width:8px;height:8px;border-radius:2px}

.heatgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(224px,1fr));gap:8px;padding:0 26px}
.heat-tile{
  border-radius:5px;padding:13px 14px;cursor:pointer;transition:transform .15s,box-shadow .15s;
  position:relative;border:1px solid rgba(255,255,255,.06);background:var(--panel);
  border-top:3px solid transparent;
}
.heat-tile:hover{transform:translateY(-2px);box-shadow:var(--shadow-2);z-index:2}
.heat-tile.active{outline:2px solid var(--accent);outline-offset:-2px}

.detail-panel{
  grid-column:1/-1;background:var(--panel);border:1px solid var(--border-2);border-radius:5px;
  padding:22px 26px;box-shadow:var(--shadow-2);scroll-margin-top:20px;
  animation:expandIn .22s ease-out;
}
@keyframes expandIn{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:translateY(0)}}
.detail-head{display:flex;align-items:baseline;gap:12px;margin-bottom:2px}
.detail-head h3{font-family:var(--serif);font-size:1.22rem;font-weight:600;margin:0;color:var(--ink)}
.detail-head .dpct{font-family:var(--mono);font-size:.98rem;font-weight:700}
.detail-close{margin-left:auto;font-family:var(--mono);font-size:.68rem;background:none;border:1px solid var(--border);color:var(--ink-3);padding:4px 10px;border-radius:4px;cursor:pointer}
.detail-sub{font-size:.75rem;color:var(--ink-3);margin-bottom:18px;font-family:var(--mono)}
.stocktable{width:100%;border-collapse:collapse}
.stocktable thead th{text-align:left;font-family:var(--mono);font-size:.6rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);padding:0 10px 8px;border-bottom:1px solid var(--ink)}
.stocktable thead th.num{text-align:right}
.stocktable tbody td{padding:10px 10px;border-bottom:1px solid var(--border);font-size:.84rem}
.stocktable tbody tr:hover{background:var(--panel-2)}
.stocktable .sid{font-family:var(--mono);color:var(--ink-3);font-size:.72rem;margin-right:8px}
.stocktable .sname{font-family:var(--serif);font-weight:600;color:var(--ink)}
.stocktable td.num{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums}
.stocktable .bar-cell{width:120px}
.mini-bar{height:6px;border-radius:3px;background:var(--panel-3);position:relative;overflow:hidden}
.mini-bar span{position:absolute;top:0;bottom:0;left:0;border-radius:3px}
.detail-empty{color:var(--ink-3);font-size:.86rem;padding:20px 0;font-family:var(--serif)}

.ht-top{display:flex;align-items:baseline;gap:8px}
.ht-rank{font-family:var(--mono);font-size:.6rem;color:var(--ink-3);flex-shrink:0}
.ht-name{font-family:var(--serif);font-weight:700;font-size:.96rem;color:var(--ink);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;letter-spacing:.01em}
.ht-pct{font-family:var(--mono);font-weight:700;font-size:1.0rem;flex-shrink:0}
.ht-status-row{display:flex;align-items:center;gap:6px;margin-top:8px;flex-wrap:wrap}
.ht-tier{display:inline-flex;align-items:center;gap:5px;padding:3px 8px;border-radius:20px;font-size:.62rem;font-weight:700;letter-spacing:.02em}
.ht-tier .dot{width:6px;height:6px;border-radius:50%}
.ht-temp{display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:20px;font-family:var(--mono);font-size:.62rem;font-weight:700}
.ht-temp.hot{background:color-mix(in srgb, var(--heat-hot) 20%, transparent);color:var(--heat-hot)}
.ht-temp.cold{background:color-mix(in srgb, var(--heat-cold) 20%, transparent);color:var(--heat-cold)}
.ht-temp.flat{background:rgba(255,255,255,.06);color:var(--ink-3)}
.ht-streak{font-family:var(--mono);font-size:.68rem;color:var(--ink-2);margin-top:7px;font-weight:600}
.ht-streak .n{font-weight:800}
.ht-streak .cnt{color:var(--ink-3);font-weight:400}
.ht-badges{display:flex;gap:5px;margin-top:7px;flex-wrap:wrap}
.badge{font-family:var(--mono);font-size:.58rem;font-weight:700;padding:2px 6px;border-radius:3px;display:inline-flex;align-items:center;gap:3px}
.badge.foreign{background:rgba(212,162,78,.16);color:var(--accent);border:1px solid rgba(212,162,78,.3)}
.badge.trust{background:rgba(169,120,154,.16);color:var(--trend);border:1px solid rgba(169,120,154,.3)}
.badge.vol{background:rgba(255,255,255,.06);color:var(--ink-2);border:1px solid var(--border)}
.ht-week{display:flex;align-items:center;justify-content:space-between;margin-top:9px;padding-top:8px;border-top:1px solid rgba(255,255,255,.08);font-family:var(--mono);font-size:.62rem}
.ht-week .lbl{color:var(--ink-3)}
.ht-week .vals{font-weight:700}
.legend-note{padding:14px 26px 0;font-size:.7rem;color:var(--ink-3);max-width:760px}

.role-note{margin:0 26px 20px;padding:11px 15px;background:var(--panel);border:1px solid var(--border);border-radius:4px;font-size:.74rem;color:var(--ink-2);display:flex;gap:18px;flex-wrap:wrap}
.role-note b{color:var(--ink)}
.status-cols{display:grid;grid-template-columns:1fr 1fr;gap:20px;padding:0 26px}
@media (max-width:760px){.status-cols{grid-template-columns:1fr}}
.status-col-head{display:flex;align-items:center;gap:8px;font-family:var(--serif);font-weight:700;font-size:1rem;margin-bottom:12px;padding-bottom:10px;border-bottom:2px solid}
.status-col-head.hot{color:var(--heat-hot);border-color:var(--heat-hot)}
.status-col-head.cold{color:var(--heat-cold);border-color:var(--heat-cold)}
.status-row{display:flex;align-items:center;gap:10px;padding:9px 4px;border-bottom:1px solid var(--border)}
.status-row .sr-name{font-family:var(--serif);font-weight:600;font-size:.88rem;color:var(--ink);flex:1}
.status-row .sr-today{font-family:var(--mono);font-size:.74rem;width:56px;text-align:right}
.status-row .sr-pt{font-family:var(--mono);font-weight:800;font-size:.86rem;width:66px;text-align:right}

.turning-wrap{margin:26px 26px 0;background:var(--panel);border:1px solid var(--border-2);border-radius:5px;padding:18px 22px}
.turning-head{font-family:var(--serif);font-weight:700;font-size:1rem;color:var(--ink);margin-bottom:4px}
.turning-sub{font-size:.72rem;color:var(--ink-3);margin-bottom:14px}
.turning-row{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border)}
.turning-row:last-child{border-bottom:none}
.turning-name{font-family:var(--serif);font-weight:700;font-size:.9rem;color:var(--ink);width:110px;flex-shrink:0}
.turning-transition{display:flex;align-items:center;gap:8px;font-family:var(--mono);font-size:.72rem}
.turning-pill{padding:3px 9px;border-radius:20px;font-weight:700}
.turning-arrow{color:var(--ink-3)}
.turning-desc{margin-left:auto;font-size:.72rem;color:var(--ink-2);font-style:italic;font-family:var(--serif)}
"""

_TIER_COLOR_VAR = {
    "super": "var(--tier-super)", "strong": "var(--tier-strong)", "mid": "var(--tier-mid)",
    "weak": "var(--tier-weak)", "superweak": "var(--tier-superweak)",
}


def _pct_str(pct: float) -> str:
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"


def _anomaly_cards_html(anomaly_cards: List[Dict[str, Any]]) -> str:
    if not anomaly_cards:
        return '<div class="anomaly-empty">目前沒有族群符合爆量暴衝或連續噴出的條件</div>'
    cards = []
    for c in anomaly_cards:
        kind_label = "爆量暴衝" if c["kind"] == "burst" else "連續噴出"
        cards.append(
            f'<div class="anomaly-card {c["kind"]}" data-meta-name="{_esc(c["meta_name"])}" '
            f'onclick="selectGroup(this.dataset.metaName)" tabindex="0">'
            f'<div class="anomaly-kind {c["kind"]}">{kind_label}</div>'
            f'<span class="anomaly-pct tabular">{_pct_str(c["pct"])}</span>'
            f'<div class="anomaly-name">{_esc(c["meta_name"])}</div>'
            f'<div class="anomaly-reason">{_esc(c["reason"])}</div>'
            f'</div>'
        )
    return "".join(cards)


def _heatgrid_html(cards: List[Dict[str, Any]]) -> str:
    tiles = []
    for c in cards:
        tier = c["tier"]
        temp = c["temp"]
        tier_html = ""
        if tier is not None:
            color = _TIER_COLOR_VAR[tier["key"]]
            tier_html = (
                f'<div class="ht-tier" style="background:{color}22;color:{color}">'
                f'<span class="dot" style="background:{color}"></span>{tier["label"]}</div>'
            )
        else:
            tier_html = '<div class="ht-tier" style="color:var(--ink-3)">資料不足</div>'

        if temp is not None:
            temp_html = f'<div class="ht-temp {temp["key"]}">{temp["icon"]} {temp["label"]}</div>'
        elif c["accel"] is not None:
            temp_html = f'<div class="ht-temp flat tabular">→ {c["accel"]:+.1f}pt</div>'
        else:
            temp_html = ""

        streak = c["streak"]
        if streak is None:
            streak_html = "資料不足"
        elif streak > 0:
            streak_html = f'連漲 <span class="n" style="color:var(--up)">{streak}</span> 日'
        elif streak < 0:
            streak_html = f'連跌 <span class="n" style="color:var(--down)">{abs(streak)}</span> 日'
        else:
            streak_html = "持平"

        badges = []
        if c["foreign_streak"] is not None and c["foreign_streak"] >= 2:
            badges.append(f'<span class="badge foreign">外資連買{c["foreign_streak"]}日</span>')
        if c["trust_streak"] is not None and c["trust_streak"] >= 2:
            badges.append(f'<span class="badge trust">投信連買{c["trust_streak"]}日</span>')
        if c["vol_ratio"] is not None and c["vol_ratio"] >= 1.5:
            badges.append(f'<span class="badge vol">量能{c["vol_ratio"]}x</span>')
        badges_html = f'<div class="ht-badges">{"".join(badges)}</div>' if badges else ""

        week_html = ""
        if c["last_week_pct"] is not None and c["this_week_pct"] is not None:
            lw, tw = c["last_week_pct"], c["this_week_pct"]
            lw_color = "var(--up)" if lw >= 0 else "var(--down)"
            tw_color = "var(--up)" if tw >= 0 else "var(--down)"
            week_html = (
                f'<div class="ht-week"><span class="lbl">近5日→前5日</span>'
                f'<span class="vals tabular"><span style="color:{lw_color}">{_pct_str(lw)}</span>'
                f'<span class="lbl">→</span><span style="color:{tw_color}">{_pct_str(tw)}</span></span></div>'
            )

        pct_color = "var(--up)" if c["pct"] >= 0 else "var(--down)"
        meta_name_safe = _esc(c["meta_name"])
        tiles.append(
            f'<div class="heat-tile" data-meta-name="{meta_name_safe}" '
            f'onclick="selectGroup(this.dataset.metaName)" tabindex="0" '
            f'style="background:{c["heat_bg"]};border-top-color:{_TIER_COLOR_VAR[tier["key"]] if tier else "transparent"}">'
            f'<div class="ht-top"><span class="ht-rank tabular">#{c["rank"]}</span>'
            f'<span class="ht-name" title="{meta_name_safe}">{meta_name_safe}</span>'
            f'<span class="ht-pct tabular" style="color:{pct_color}">{_pct_str(c["pct"])}</span></div>'
            f'<div class="ht-status-row">{tier_html}{temp_html}</div>'
            f'<div class="ht-streak">{streak_html}<span class="cnt">　'
            f'<span style="color:var(--up)">▲{c["up_count"]}檔</span> '
            f'<span style="color:var(--down)">▼{c["down_count"]}檔</span></span></div>'
            f'{badges_html}{week_html}</div>'
        )
    return "".join(tiles)


def _sector_recap_html(recap: Dict[str, Any]) -> str:
    def _status_row(r: Dict[str, Any], is_hot: bool) -> str:
        color = "var(--heat-hot)" if is_hot else "var(--heat-cold)"
        sign = "+" if r["accel"] >= 0 else ""
        pct_color = "var(--up)" if r["pct"] >= 0 else "var(--down)"
        return (
            f'<div class="status-row"><span class="sr-name">{_esc(r["meta_name"])}</span>'
            f'<span class="sr-today tabular" style="color:{pct_color}">{_pct_str(r["pct"])}</span>'
            f'<span class="sr-pt tabular" style="color:{color}">{sign}{r["accel"]:.1f}pt</span></div>'
        )

    hot_html = "".join(_status_row(r, True) for r in recap["hot_top5"]) or '<div class="detail-empty">資料不足</div>'
    cold_html = "".join(_status_row(r, False) for r in recap["cold_top5"]) or '<div class="detail-empty">資料不足</div>'

    turning = recap["turning_points"]
    if turning:
        turning_html = "".join(
            f'<div class="turning-row"><span class="turning-name">{_esc(tp["meta_name"])}</span>'
            f'<span class="turning-transition">'
            f'<span class="turning-pill" style="background:{_TIER_COLOR_VAR[tp["prev_key"]]}22;color:{_TIER_COLOR_VAR[tp["prev_key"]]}">{tp["prev_label"]}</span>'
            f'<span class="turning-arrow">→</span>'
            f'<span class="turning-pill" style="background:{_TIER_COLOR_VAR[tp["cur_key"]]}22;color:{_TIER_COLOR_VAR[tp["cur_key"]]}">{tp["cur_label"]}</span>'
            f'</span><span class="turning-desc">{tp["direction"]}</span></div>'
            for tp in turning
        )
    else:
        turning_html = '<div class="detail-empty">本週沒有族群發生等級翻轉</div>'

    return f"""
<div class="section-head"><h2>族群近況</h2><span class="count">升溫/退燒排行・轉折點</span></div>
<div class="section-rule"></div>
<div class="role-note">
  <span>🔥❄️ <b>族群近況</b>＝週度趨勢訊號（加速度、等級翻轉），時間尺度是「這週 vs 上週」</span>
  <span>⚡ <b>異動族群</b>（頁面最上方）＝瞬間訊號（爆量+排名跳動），時間尺度是「今天 vs 昨天」</span>
  <span>兩者角色不同，故意分開兩個區塊，不是重複資訊</span>
</div>
<div class="status-cols">
  <div><div class="status-col-head hot">🔥 近期增溫 Top 5</div><div>{hot_html}</div></div>
  <div><div class="status-col-head cold">❄️ 近期退燒 Top 5</div><div>{cold_html}</div></div>
</div>
<div class="turning-wrap">
  <div class="turning-head">⚠ 轉折點：等級真的翻轉的族群</div>
  <div class="turning-sub">不是看誰漲最多，是看「上週的等級」跟「這週的等級」是否真的換了一級。</div>
  <div>{turning_html}</div>
</div>"""


def generate(
    trade_date: date,
    meta_perf: List[Dict[str, Any]],
    universe_df: pd.DataFrame,
    meta_signals: Dict[str, Dict[str, Any]],
    meta_chips: Dict[str, Dict[str, Any]],
    prices_df: pd.DataFrame,
    heatgrid_windows: Dict[str, Dict[str, Any]],
    output_path: str = "docs/index.html",
) -> None:
    """
    產生 docs/index.html（族群總覽頁熱區格版面）。meta_perf 為空時不寫檔（比照舊
    export/html_generator.py::generate() 既有慣例）。
    """
    if not meta_perf:
        return

    date_str = trade_date.strftime("%Y-%m-%d")
    weekday = ["一", "二", "三", "四", "五", "六", "日"][trade_date.weekday()]

    cards = build_heatgrid_cards(meta_perf, meta_signals, meta_chips, heatgrid_windows)
    anomaly_cards = find_anomaly_cards(meta_perf, meta_signals, heatgrid_windows)
    recap = build_sector_recap(meta_perf, heatgrid_windows)
    stock_detail = build_stock_detail_data(universe_df, prices_df)

    stock_detail_js = json.dumps(stock_detail, ensure_ascii=False).replace("</", "<\\/")
    card_meta_js = json.dumps(
        {c["meta_name"]: {"pct": c["pct"], "up_count": c["up_count"], "down_count": c["down_count"]} for c in cards},
        ensure_ascii=False,
    ).replace("</", "<\\/")

    html = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<title>族群總覽 {date_str}</title>
<style>{_CSS}</style>
</head>
<body>
<a class="skip-link" href="#main-content">跳到主要內容</a>
<header class="topbar">
  <div><div class="kicker">台股電子半導體族群追蹤</div><h1>族群總覽</h1></div>
  <button onclick="toggleTheme()" id="themeToggle">切換亮色預覽</button>
  <div class="updated">{date_str}（週{weekday}）更新</div>
  <nav class="nav-links" aria-label="主要功能">
    <a class="nav-link active" href="index.html" aria-current="page">族群績效</a>
    <a class="nav-link" href="chips.html">籌碼分析</a>
    <a class="nav-link" href="patterns.html">形態掃描</a>
    <a class="nav-link" href="momentum.html">逆轟策略</a>
  </nav>
</header>
<main id="main-content">
<div class="section-head"><h2>⚡ 異動族群</h2><span class="count">{len(anomaly_cards)} 檔符合</span></div>
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
<div class="legend-note">⚠️ 動能狀態標籤（超強/強/整理/弱/超弱）是族群層級獨立算的草案規則（連漲天數+本週比上週加速度），跟個股層級或觀察分頁面的五級分類不共用計算依據，門檻未經回測驗證。「近5日→前5日」是滾動5個交易日的複利累積漲跌幅，不是自然日曆週。</div>

{_sector_recap_html(recap)}
</main>
<script>
const STOCKS = {stock_detail_js};
const CARD_META = {card_meta_js};

// escHtml：innerHTML拼字串前一律過這支，把字串當純文字塞進暫時的div再讀回escape過的innerHTML。
// 這裡一定要用，不能省——name(族群名)是從data-meta-name屬性讀回來的(瀏覽器解析HTML屬性時
// 已經把&lt;還原成<，所以.dataset.metaName拿到的是「解過碼的原始字串」)，s.stock_name是從
// 內嵌JSON讀的(json.dumps只做JSON字串轉義，從來沒被HTML-escape過)——這兩個字串如果直接
// 內插進innerHTML模板字串，等於繞過Python端generate()裡_esc()做過的escaping，是真的可以
// 執行的DOM XSS路徑(尤其<img onerror=...>/<svg onload=...>這類非<script>標籤，瀏覽器插入
// innerHTML後event handler真的會觸發，不是<script>標籤那種inert的假象全)。
function escHtml(s) {{
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}}

function selectGroup(name) {{
  const existing = document.getElementById('detailPanel');
  if (existing) existing.remove();
  document.querySelectorAll('.heat-tile').forEach(t => t.classList.remove('active'));

  const tiles = [...document.querySelectorAll('.heat-tile')];
  const tile = tiles.find(t => t.dataset.metaName === name);
  if (!tile) return;
  tile.classList.add('active');

  const meta = CARD_META[name];
  if (!meta) return;
  const stocks = STOCKS[name] || [];
  const safeName = escHtml(name);

  const panel = document.createElement('div');
  panel.id = 'detailPanel';
  panel.className = 'detail-panel';
  const pctColor = meta.pct >= 0 ? 'var(--up)' : 'var(--down)';
  const pctStr = (meta.pct >= 0 ? '+' : '') + meta.pct.toFixed(2) + '%';
  // 收合按鈕故意不再靠interpolate name進onclick字串或事後從DOM文字反查——直接閉包捕捉
  // selectGroup自己的name參數，同一個安全等級的做法比「從text內容讀回名字再傳一次」更直接。
  const closeBtn = document.createElement('button');
  closeBtn.className = 'detail-close';
  closeBtn.textContent = '收合';
  closeBtn.onclick = () => selectGroup(name);

  if (!stocks.length) {{
    panel.innerHTML = `
      <div class="detail-head"><h3>${{safeName}}</h3><span class="dpct" style="color:${{pctColor}}">${{pctStr}}</span></div>
      <div class="detail-sub">▲${{meta.up_count}}檔 ▼${{meta.down_count}}檔</div>
      <div class="detail-empty">這個族群目前沒有個股行情資料。</div>`;
  }} else {{
    const maxChg = Math.max(...stocks.map(s => Math.abs(s.change_pct)));
    const rows = stocks.map(s => {{
      const w = maxChg > 0 ? (Math.abs(s.change_pct) / maxChg * 100).toFixed(0) : 0;
      const color = s.change_pct >= 0 ? 'var(--up)' : 'var(--down)';
      const sign = s.change_pct >= 0 ? '+' : '';
      return `<tr><td><span class="sid">${{escHtml(s.stock_id)}}</span><span class="sname">${{escHtml(s.stock_name)}}</span></td>
        <td class="num">${{s.close.toFixed(1)}}</td>
        <td class="num" style="color:${{color}}">${{sign}}${{s.change_pct.toFixed(2)}}%</td>
        <td class="bar-cell"><div class="mini-bar"><span style="width:${{w}}%;background:${{color}}"></span></div></td></tr>`;
    }}).join('');
    panel.innerHTML = `
      <div class="detail-head"><h3>${{safeName}}</h3><span class="dpct" style="color:${{pctColor}}">${{pctStr}}</span></div>
      <div class="detail-sub">▲${{meta.up_count}}檔 ▼${{meta.down_count}}檔　・　共 ${{stocks.length}} 檔</div>
      <table class="stocktable">
        <thead><tr><th>個股</th><th class="num">收盤</th><th class="num">漲跌%</th><th>幅度</th></tr></thead>
        <tbody>${{rows}}</tbody>
      </table>`;
  }}
  panel.querySelector('.detail-head').appendChild(closeBtn);

  const rowTop = tile.offsetTop;
  const rowTiles = tiles.filter(t => t.offsetTop === rowTop);
  const lastInRow = rowTiles[rowTiles.length - 1];
  lastInRow.insertAdjacentElement('afterend', panel);
  panel.scrollIntoView({{behavior:'smooth', block:'nearest'}});
}}

function toggleTheme() {{
  const root = document.documentElement;
  const isLight = root.getAttribute('data-theme') === 'light';
  root.setAttribute('data-theme', isLight ? 'dark' : 'light');
  document.getElementById('themeToggle').textContent = isLight ? '切換亮色預覽' : '切換深色預覽';
}}
</script>
</body></html>"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
```

**注意事項（實作時務必處理）**：

1. 上面 `generate()` 的內部程式碼用到 `json.dumps`，檔案開頭 import 區塊還需要補一行
   `import json`（放在 `from datetime import date` 之前或之後皆可，跟其他既有 import 放一起）。
2. **`escHtml()` 是這個 Task 最重要的安全細節，不能省略**：`selectGroup(name)` 收到的 `name`
   是從 `data-meta-name` 屬性讀回來的——瀏覽器解析 HTML 屬性時已經把 `&lt;` 還原成 `<`，
   所以 `.dataset.metaName` 拿到的是「解過碼的原始字串」，不是 Python 端 `_esc()` 過的版本。
   `STOCKS` 裡的 `s.stock_name` 更直接：`json.dumps()` 只做 JSON 字串轉義，從來沒被 HTML-escape
   過。這兩個字串如果直接內插進 `innerHTML` 模板字串（`` `<h3>${name}</h3>` ``這種寫法），
   等於繞過 Python 端做過的所有 escaping，是真的可以執行的 DOM XSS 路徑——尤其
   `<img onerror=...>`/`<svg onload=...>` 這類非 `<script>` 標籤，瀏覽器把它們插入
   `innerHTML` 後 event handler 真的會觸發（不是 `<script>` 標籤那種瀏覽器預設不執行的假象
   全）。`escHtml()`（`div.textContent=s` 再讀回 `div.innerHTML`）是標準且正確的 JS 端
   HTML-escape 寫法，`name`/`s.stock_id`/`s.stock_name` 內插進任何 `innerHTML` 模板字串前
   都要先過這支函式。**這是純前端互動邏輯，Python pytest 測試套件測不到（需要真的執行 JS
   才會顯現），屬於這次 code review 需要人工特別複查的地方，不是自動化測試能完全覆蓋的**。
3. 收合按鈕改用 `closeBtn.onclick = () => selectGroup(name)`（JS 閉包直接捕捉 `name` 變數）
   取代原本「從 DOM 文字內容反查名稱再重新呼叫」的寫法——更直接，也不需要额外讀 DOM 文字。

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_index_generator.py -q`
Expected: PASS（33 passed）

- [ ] **Step 5: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index-generator): 新增generate()產生docs/index.html(CSS/HTML/JS組裝，安全onclick寫法)"
```

---

### Task 9：`main.py` 掛接新 generator（取代 `html_generator.py`）

**Files:**
- Modify: `main.py`

**Interfaces:** 無新函式，純接線：把 `main.py::run()` 呼叫 `export/html_generator.py::generate()`
的地方換成呼叫 `export/index_generator.py::generate()`，新增
`calc_meta_heatgrid_windows()` 呼叫一次。

- [ ] **Step 1: 修改 import**

`main.py` 第 19 行，原本：

```python
from processors.performance import calc_sector_performance, calc_meta_performance, calc_universe_performance, calc_cumulative_meta, calc_meta_signals, calc_meta_chips_signals, calc_stock_sparklines, get_stock_chips_ranking, get_margin_divergence, calc_market_breadth, calc_capital_concentration, classify_market_regime
```

改成（加上 `calc_meta_heatgrid_windows`）：

```python
from processors.performance import calc_sector_performance, calc_meta_performance, calc_universe_performance, calc_cumulative_meta, calc_meta_signals, calc_meta_chips_signals, calc_stock_sparklines, get_stock_chips_ranking, get_margin_divergence, calc_market_breadth, calc_capital_concentration, classify_market_regime, calc_meta_heatgrid_windows
```

`main.py` 第 21 行，原本：

```python
from export.html_generator import generate as generate_html
```

改成：

```python
from export.index_generator import generate as generate_index_html
```

（`export/html_generator.py` 本身檔案不動、不刪，只是這裡不再 import 它——沒有其他地方
`import` 這個名稱，`grep -n "generate_html" main.py` 確認過改完後這個名稱不會再出現在
`main.py` 任何地方。）

- [ ] **Step 2: 修改呼叫點**

`main.py` 第 728-754 行，原本：

```python
        try:
            # universe_df 必須含 exchange 欄位，否則 calc_meta_observation_scores() 內部
            # _calc_chips_factor() 會 KeyError（見 debug-tasks.md 2026-07-18 條目提醒）。
            obs_universe_df = pd.read_csv(
                UNIVERSE_PATH, dtype=str,
                usecols=["stock_id", "stock_name", "meta_sector", "exchange"],
            )
            observation_scores = calc_meta_observation_scores(obs_universe_df)
        except Exception as exc:
            logger.warning("觀察分計算失敗，index.html 排序退回avg_change_pct、momentum頁本次不產生: %s", exc)
            observation_scores = {}

        generate_html(trade_date, pd.DataFrame(perf) if perf else pd.DataFrame(),
                      sectors_df=sectors_df,
                      prices_df=prices_df if prices_df is not None else pd.DataFrame(),
                      chips_df=chips_df,
                      meta_perf=meta_perf,
                      universe_df=universe_df,
                      cum_data=cum_data,
                      meta_signals=meta_signals,
                      meta_chips=meta_chips,
                      stock_sparklines=stock_sparklines,
                      vol_turnover=vol_signals,
                      rolling_returns=rolling_returns,
                      market_regime=market_regime,
                      observation_scores=observation_scores)
        logger.info("HTML generated → docs/index.html")
```

改成（`observation_scores` 計算區塊保留不動——它現在只服務 momentum.html，不再服務
index.html 排序，所以警告訊息文字要跟著修正；`generate_html(...)` 換成
`generate_index_html(...)`，新增 `heatgrid_windows` 計算）：

```python
        try:
            # universe_df 必須含 exchange 欄位，否則 calc_meta_observation_scores() 內部
            # _calc_chips_factor() 會 KeyError（見 debug-tasks.md 2026-07-18 條目提醒）。
            obs_universe_df = pd.read_csv(
                UNIVERSE_PATH, dtype=str,
                usecols=["stock_id", "stock_name", "meta_sector", "exchange"],
            )
            observation_scores = calc_meta_observation_scores(obs_universe_df)
        except Exception as exc:
            # 注意：observation_scores 現在只服務 momentum.html（index.html 改用熱區格版面
            # 自己的 classify_tier()，不再依賴 observation_scores 排序，見
            # docs/superpowers/specs/2026-07-22-sector-overview-heatmap-implementation-design.md）。
            logger.warning("觀察分計算失敗，momentum頁本次不產生: %s", exc)
            observation_scores = {}

        try:
            heatgrid_windows = calc_meta_heatgrid_windows(universe_df) if universe_df is not None else {}
        except Exception as exc:
            logger.warning("熱區格動能窗口計算失敗，index.html 動能標籤本次不顯示: %s", exc)
            heatgrid_windows = {}

        generate_index_html(trade_date, meta_perf, universe_df,
                             meta_signals=meta_signals,
                             meta_chips=meta_chips,
                             prices_df=prices_df if prices_df is not None else pd.DataFrame(),
                             heatgrid_windows=heatgrid_windows)
        logger.info("HTML generated → docs/index.html")
```

⚠️ **實作時注意參數順序**：`generate_index_html()`（即 `export/index_generator.py::generate()`）
的簽章是
`generate(trade_date, meta_perf, universe_df, meta_signals, meta_chips, prices_df, heatgrid_windows, output_path=...)`——
上面呼叫用關鍵字參數傳 `meta_signals`/`meta_chips`/`prices_df`/`heatgrid_windows`，只有前三個
（`trade_date`/`meta_perf`/`universe_df`）用位置參數，跟 Task 8 定義的函式簽章逐一核對一致。

- [ ] **Step 3: 驗證**

Run: `python -c "import main"`
Expected: 無錯誤（確認 import 路徑正確、沒有語法錯誤）

Run: `python -m pytest tests/ -q`
Expected: 全部既有測試維持通過（這一步只改 wiring，不改任何函式邏輯，`tests/test_html_generator.py`
的既有測試不受影響——那個檔案測的是 `export/html_generator.py`，這次沒有修改那個檔案本身）。

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat(main): index.html改掛export/index_generator.py(熱區格版面取代卡片版面)"
```

---

### Task 10：`DESIGN.md` 更新 —— 反映新熱區格設計

**Files:**
- Modify: `DESIGN.md`（只改「改版原則」「已完成的設計決策」「版面結構（目前）」三個跟
  `index.html` 相關的段落，第 100-172 行「型態掃描設計」「選股訊號」段落跟這次無關，不要動）

**Interfaces:** 純文件更新，無程式碼。

- [ ] **Step 1: 更新「視覺規範」表格**

`DESIGN.md` 第 9-20 行，原本的視覺規範表格（`#0b0f18` 背景等舊卡片版配色）改成反映新熱區格
設計的配色，並加一句指向兩份 spec 的說明：

```markdown
### 視覺規範（2026-07-22 熱區格改版，取代舊卡片版配色）

> 完整 CSS token 定義見
> `docs/superpowers/specs/2026-07-15-sector-overview-heatmap-redesign.md` §「視覺設計」，
> 這裡只列摘要，避免兩處維護同一份數字漂移。

| 項目 | 規定 |
|------|------|
| 背景色 | `#080B12`（body）、`#0F1420`（卡片 panel）、`#161D2C`（panel-2） |
| 邊框 | `#293346`，hover 時 `#37B25C`(border-2) |
| 上漲色 | `#E6432F`（紅，飽和度刻意調高） |
| 下跌色 | `#37B25C`（綠） |
| 強調色 | `#F0BB55`（銅金 accent） |
| 中性/次要文字 | `#98A0B4`（ink-2）、`#636B80`（ink-3） |
| 版面 | 熱區格 `grid-template-columns:repeat(auto-fill,minmax(224px,1fr))`，不加 max-width |
| 圓角 | 卡片 `5px`，大區塊 `5px` |
| 亮色主題 | 支援 `:root[data-theme="light"]` 手動切換（不用 `prefers-color-scheme`） |
```

- [ ] **Step 2: 更新「禁止事項」**

第 22-28 行，維持既有條目，新增一條：

```markdown
- ❌ **不用固定張數的示範清單**：異動族群等「符合條件才出現」的區塊要動態產生，不能為了
  版面好看固定顯示幾張卡（2026-07-22 熱區格改版的教訓：舊 mockup 曾經固定顯示 5 張異動
  族群示範卡，正式資料需要動態）
```

- [ ] **Step 3: 更新「設計語言」**

第 30-35 行，原本「卡片為主要容器，10 欄 grid」改成：

```markdown
### 設計語言（2026-07-22 更新）

- **熱區格（heatgrid）為主要容器**：`auto-fill` grid，底色依當日漲跌幅飽和度編碼（紅漲綠跌），
  頂部邊框色依動能五級編碼（雙重視覺編碼：底色=今日方向，頂色=本週動能）
- 個股點開面板：原地展開到被點卡片所在那一整排正下方（不是側邊滑出、不是固定接在最後面）
- Badge/chip 模式：用小標籤嵌在卡片內，不單獨開區塊（沿用既有慣例）
- 色彩語意分層：今日漲跌（紅/綠）、動能五級（金/綠/灰/橘/紅）、溫度變化（橙/藍）三組顏色
  故意互相區分，之後加新指標要遵守這個原則，不要混用
```

- [ ] **Step 4: 新增「已完成的設計決策」條目**

第 39-50 行的表格新增一列：

```markdown
| 2026-07-22 | 族群總覽頁改熱區格版面（取代卡片版面） | 卡片版面排名/訊號資訊分散、族群→個股要三層點擊；熱區格一次呈現41個族群全貌，個股點開面板原地展開省一層點擊 |
```

- [ ] **Step 5: 更新「版面結構（目前）」**

第 175-183 行，原本：

```
[Header：日期 + 市場均漲跌幅 + 上漲/下跌家數]
[▲ 漲幅 Top10 卡片 × 10]   ← 含 3d/5d/7d 排名 badge + signal badge
[▼ 跌幅 Top10 卡片 × 10]   ← 同上
  └─ 展開面板：sparkline → 籌碼摘要行 → 個股卡片（含外資/投信 badge）
[各產業分組：mini-card grid（5欄），點擊展開個股卡片]
```

改成：

```
[Topbar：標題 + 更新時間 + 亮暗主題切換 + nav連到chips/patterns/momentum]
[⚡ 異動族群：橫向捲動快報，動態張數，爆量暴衝/連續噴出]
[族群排行：41個族群熱區格，動能五級+溫度變化+連漲跌天數+法人badge+上週→本週]
  └─ 點卡片：個股清單原地展開到該排正下方（收盤/漲跌%/幅度長條）
[族群近況：升溫/退燒Top5雙欄 + 轉折點列表（等級真的翻轉的族群）]
```

- [ ] **Step 6: Commit**

```bash
git add DESIGN.md
git commit -m "docs(design): 更新DESIGN.md反映熱區格改版(視覺規範/設計語言/版面結構)"
```

---

## Self-Review（對照兩份 spec 逐項檢查）

- **檔案結構**（實作 spec §1）：Task 3 新建 `export/index_generator.py`，`export/html_generator.py`
  全程不動不刪，Task 9 只改 `main.py` 的 import/呼叫點。
- **分層原則**（實作 spec，DB 查詢在 processors/，分類/渲染在 export/）：Task 1/2 把
  `_streak_and_windows_as_of()`/`calc_meta_heatgrid_windows()` 放在 `processors/performance.py`
  （會呼叫 `duckdb.connect()`），Task 3 之後的 `classify_tier()`/`heat_bg()`/`find_turning_points()`
  等全部放 `export/index_generator.py` 且不含任何 `duckdb.connect()` 呼叫——這是本次 review
  過程中發現並修正的一個真實架構違規（原始草稿把 DB 查詢寫進 export/ 檔案，跟專案裡所有
  `export/*_generator.py` 檔案零 `duckdb.connect()` 的既有慣例不符，已重新設計修正）。
- **轉折點回推算法，不開新表**（實作 spec §2.3）：Task 1 的窗口重疊關係測試
  （`test_streak_and_windows_as_of_five_days_ago_reuses_todays_last_week_as_this_week`）+
  Task 4 的 `_tiers_from_windows()` 正確重用 `last_week_pct_today` 當 5 天前的 `this_week`，
  完整對應。
- **資料不足回 None，不硬湊**（實作 spec §2.2）：Task 1（`cutoff_index<9`）、Task 2（`streak_today`
  為 None 時整組回 None）、Task 3 `classify_tier`（任一輸入 None 即回 None）、Task 4
  `find_turning_points`（任一 tier None 就跳過）全部有對應測試。
- **41 個族群全部要有卡片**：Task 8 的
  `test_generate_writes_page_with_all_41_style_sectors_present` 直接呼應
  2026-07-09 那次教訓的回歸測試精神。
- **異動族群動態張數，不是固定5張**（視覺 spec §「已知限制」）：Task 4 `find_anomaly_cards()`
  回傳「符合條件有幾檔就幾檔」的 list，Task 8 有 0 檔時的空狀態測試。
- **onclick 安全寫法**：Task 8 專門測試
  `test_generate_uses_this_dataset_metaname_not_raw_string_interpolation`，且 self-review 過程中
  額外發現並修正了 `selectGroup()` 內部重建 detail-panel HTML 時的 DOM-based XSS 路徑（見 Task 8
  「注意事項」第2點），這是視覺 spec/實作 spec 都沒有明確提到、寫 Task 8 時才發現的真實安全考量。
- **DESIGN.md 更新**（實作 spec §6）：Task 10 完整覆蓋，且明確限定只改 index.html 相關段落，
  不動型態掃描/巨量換手段落。
- **草案門檻標注**（Global Constraints）：`classify_tier`/`classify_temp`/`find_anomaly_cards`
  的門檻常數全部有註解標明「草案，待回測」，`generate()` 的 `legend-note` 也有對應頁面文案。
- **第三套獨立分類邏輯的技術債聲明**（實作 spec §3.1）：`export/index_generator.py` 模組
  docstring 跟 Global Constraints 都有寫，避免以後被誤以為要跟 `scan_momentum_health`/
  `classify_sector_state` 共用邏輯。

## No Placeholder 掃描

十個 Task 的程式碼區塊都是可以直接貼上執行的完整程式碼，測試斷言皆為具體數值/字串比對
（例如 `assert result["混合族群"]["this_week_pct"] == 5.1`），沒有「add assertion here」這類
空泛寫法。Task 9（main.py wiring）用「找到第N行原本XX，改成YY」的精確 diff 描述法，附帶
`grep` 驗證步驟確認改動範圍正確。

## Type Consistency 掃描

- Task 1 定義的 `_streak_and_windows_as_of()` 回傳鍵名（`streak`/`last_week_pct`/`this_week_pct`）
  在 Task 2 讀取時逐字對應（`today_calc["streak"]` 等）。
- Task 2 定義的 `calc_meta_heatgrid_windows()` 回傳鍵名（`streak_today`/`last_week_pct_today`/
  `this_week_pct_today`/`streak_5d_ago`/`last_week_pct_5d_ago`）在 Task 4 的
  `_accel_from_windows()`/`_tiers_from_windows()`、Task 5 的 `build_heatgrid_cards()`、Task 6 的
  `build_sector_recap()` 全部逐字對應使用，沒有改名或型別不一致。
- Task 3 定義的 `classify_tier()`/`classify_temp()` 回傳鍵名（`key`/`label`/`icon`）在 Task 4
  `find_turning_points()`、Task 5 `build_heatgrid_cards()`、Task 8 `_heatgrid_html()`/
  `_sector_recap_html()` 全部逐字對應使用。
- Task 4 定義的 `_accel_from_windows()`/`_tiers_from_windows()` 私有 helper 在 Task 5/6 直接
  呼叫重用，沒有各自重新實作一份（避免兩處算 accel/tier 邏輯以後改一邊忘了改另一邊）。
- Task 8 `generate()` 呼叫 Task 5/6/7 的函式（`build_heatgrid_cards`/`find_anomaly_cards`/
  `build_sector_recap`/`build_stock_detail_data`）參數順序與名稱跟各自 Task 定義的簽章逐一
  核對一致。
- Task 9 `main.py` 呼叫 `generate_index_html()`/`calc_meta_heatgrid_windows()` 的參數，跟
  Task 8/Task 2 定義的函式簽章逐一核對一致。

## Out of scope（本次不做，兩份 spec 已列，或 brainstorming 階段已決定不做）

- 手機窄螢幕版面（視覺 spec 全系列 9 輪 mockup 都只做桌機寬螢幕，沒有可以照抄的設計）。
- 動能五級門檻、溫度變化門檻、異動族群門檻的回測驗證（全部標記「草案，待回測」）。
- `export/html_generator.py` 整檔刪除（含其測試）——保留當 rollback 用，之後獨立任務再刪。
- `scan_limit_up_unlocked()`、紫圈/橘圈徽章（跟這次無關，屬於逆轟策略 v2 的 out of scope 項目，
  這裡重申不要誤植進來）。
- 讓族群層級 `classify_tier()` 重用 `scan_momentum_health()` 的規則常數（實作 spec §3.1 明確
  決定不做，是刻意的技術債）。
