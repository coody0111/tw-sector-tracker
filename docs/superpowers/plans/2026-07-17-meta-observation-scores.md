# `calc_meta_observation_scores()` 觀察分 Implementation Plan（v2 Plan 2/3）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `processors/observation_scores.py::calc_meta_observation_scores()`，依 5 因子公式（相對強度/族群廣度/延續性/成分股量能參與/籌碼確認）算出每個族群的「觀察分」，供首頁與逆轟策略頁共用決定族群優先展開順序。

**Architecture:** 全新獨立檔案 `processors/observation_scores.py`（不是加進既有的 `processors/performance.py`——該檔已871行超過專案800行上限，且這支函式設計上完全不呼叫該檔任何既有函式，是自然的新檔邊界）。內部拆成2支私有計算函式（`_calc_price_based_factors()` 吃 daily_prices 算4個因子、`_calc_chips_factor()` 吃 institutional+margin 算籌碼因子）+ 1支公開組裝函式（`calc_meta_observation_scores()` 負責開DB連線查資料、呼叫前兩支、做百分位排名、reweight、算最終分數）。3個Task依此切分，每個Task完成後都是可獨立commit、可通過測試的完整狀態。

**Tech Stack:** Python、DuckDB、pandas（既有依賴，無新套件）。

## Global Constraints

- 對照 spec：`docs/superpowers/specs/2026-07-17-meta-observation-scores-design.md`（下稱「spec」）。
- **完全獨立實作**：`_calc_price_based_factors()`/`_calc_chips_factor()`/`calc_meta_observation_scores()` 都不呼叫 `processors/performance.py` 裡任何既有函式（`calc_cumulative_meta`/`calc_universe_performance`/`calc_meta_signals`/`calc_meta_chips_signals`）。這是 Cody 明確拍板的刻意取捨（spec §2），換效能（單一連線）跟隔離性，代價是 `_calc_chips_factor()` 裡的跨交易所涵蓋度判斷邏輯（`partial_coverage`）跟 `calc_meta_chips_signals()` 重複一份，之後不會自動同步——**寫Task時不用重新論證這個決定，照做就好**。
- **可以**重用 `streak_utils.calc_streak()`——這是通用數學工具（不是 spec §2 講的4支「姊妹函式」之一），本來就是為了避免重複實作而抽出來的共用小工具，重複實作它才是真正的問題。
- **nullable 欄位防呆**：`daily_prices.volume`（BIGINT）、`daily_prices.change_pct`（DOUBLE）、`institutional.foreign_net`（BIGINT）都沒有 `NOT NULL` 約束，DuckDB→pandas 讀出來 NULL 可能是 `pd.NA`（nullable整數欄位）也可能是 `float('nan')`（浮點欄位），視底層dtype而定。這是這次 v2 資料層 Plan 1（`screener/signals.py` 三個Task）連續踩到4次的同一類bug——**每個Task的NA防呆都已經在下方程式碼裡寫好**（一律用 `pd.notna()`/`.dropna()` 等 pandas 原生NA感知方法，不要對個別scalar直接 `float()`/`int()`/`bool()`），照抄即可，但寫測試時要確實驗證這些防呆有生效（每個Task都有對應的NaN regression test）。
- 每個Task完成後跑對應測試檔確認沒有破壞既有測試（照專案慣例，這步留給 Debugger 驗證，實作階段用 hand-trace 或 subagent review 階段的實際執行代替）。

---

### Task 1: `_calc_price_based_factors()`——相對強度/族群廣度/延續性/量能參與 4 因子原始值

**Files:**
- Create: `processors/observation_scores.py`
- Test: Create `tests/test_observation_scores.py`

**Interfaces:**
- Consumes：`universe_df`（欄位至少含 `stock_id`/`meta_sector`）、`price_df`（欄位 `stock_id`/`date`/`change_pct`/`volume`，呼叫端負責只傳入最近N個交易日，這支函式不做日期範圍過濾，用 `price_df` 裡實際出現的所有日期）。
- Produces：`Dict[str, Dict[str, Any]]`，key是`meta_name`，value含 `rs_raw`(float|None)、`breadth_raw`(float|None)、`continuation_raw`(int|None)、`volume_raw`(float|None)。

**「不可用」條件（見 spec §3）**：
- `rs_raw`：universe 或該族群在「最近3個實際出現的日期」裡任一天缺 valid `change_pct` 資料 → `None`（嚴格版本，不用0填補缺口）
- `breadth_raw`：該族群「今日」（`price_df`裡最新一天）完全沒有股票有 valid `change_pct` → `None`
- `continuation_raw`：該族群在整個 `price_df` 時間窗完全沒有 valid `change_pct` 資料 → `None`（只要有任何資料就能算，跳過缺值日、用剩餘有效日照時間順序算streak）
- `volume_raw`：該族群「今日」沒有 valid `volume` 資料，或今日之前不足5個 valid `volume` 交易日 → `None`

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_observation_scores.py`：

```python
import pandas as pd
from processors.observation_scores import _calc_price_based_factors


def _make_universe(rows):
    """rows: list of (stock_id, meta_sector)"""
    return pd.DataFrame(rows, columns=["stock_id", "meta_sector"])


def _make_price_rows(rows):
    """rows: list of (stock_id, date, change_pct, volume)"""
    return pd.DataFrame(rows, columns=["stock_id", "date", "change_pct", "volume"])


def test_calc_price_based_factors_rs_breadth_continuation():
    """3天資料，2個族群：sectorA（2檔，漲跌互抵，族群均值平盤）、sectorB（1檔，穩定上漲）。
    驗證相對強度（vs universe cum3）、族群廣度（今日上漲比例）、延續性（連漲天數）三個因子。"""
    universe = _make_universe([
        ("A1", "sectorA"), ("A2", "sectorA"), ("B1", "sectorB"),
    ])
    prices = _make_price_rows([
        ("A1", "2026-07-01", 1.0, 1000), ("A1", "2026-07-02", 1.0, 1000), ("A1", "2026-07-03", 1.0, 1000),
        ("A2", "2026-07-01", -1.0, 1000), ("A2", "2026-07-02", -1.0, 1000), ("A2", "2026-07-03", -1.0, 1000),
        ("B1", "2026-07-01", 2.0, 1000), ("B1", "2026-07-02", 2.0, 1000), ("B1", "2026-07-03", 2.0, 1000),
    ])

    result = _calc_price_based_factors(universe, prices)

    # universe cum3 = 每日等權均值(1.0-1.0+2.0)/3=0.667%，複利3天 ≈ +2.01%
    # sectorA cum3 = 每日均值(1.0-1.0)/2=0%，複利3天 = 0%；rs_raw = 0 - 2.01 = -2.01
    # sectorB cum3 = 每日均值2.0%，複利3天 ≈ +6.12%；rs_raw = 6.12 - 2.01 = 4.11
    assert result["sectorA"]["rs_raw"] == -2.01
    assert result["sectorB"]["rs_raw"] == 4.11

    # 今日(07-03)：sectorA上漲1檔(A1)/共2檔=0.5；sectorB上漲1檔(B1)/共1檔=1.0
    assert result["sectorA"]["breadth_raw"] == 0.5
    assert result["sectorB"]["breadth_raw"] == 1.0

    # sectorA今日均值0%（不漲不跌）→ streak=0；sectorB連漲3天（均值每天都是+2.0%）→ streak=3
    assert result["sectorA"]["continuation_raw"] == 0
    assert result["sectorB"]["continuation_raw"] == 3


def test_calc_price_based_factors_volume_raw_needs_six_days():
    """量能參與需要「今日」+「今日之前5個valid交易日」共6天；不足時回None，足夠時算出集合量比。"""
    universe = _make_universe([("C1", "sectorC")])
    # 5天量都是1000（今日之前），第6天(今日)量衝到2500
    rows = [("C1", f"2026-06-{d:02d}", 0.5, 1000) for d in range(25, 30)]
    rows.append(("C1", "2026-06-30", 0.5, 2500))
    prices = _make_price_rows(rows)

    result = _calc_price_based_factors(universe, prices)

    assert result["sectorC"]["volume_raw"] == 2.5  # 2500 / (5*1000/5) = 2500/1000

    # 只給5天（不足6天）驗證回None
    universe2 = _make_universe([("D1", "sectorD")])
    prices2 = _make_price_rows([("D1", f"2026-06-{d:02d}", 0.5, 1000) for d in range(26, 31)])
    result2 = _calc_price_based_factors(universe2, prices2)
    assert result2["sectorD"]["volume_raw"] is None


def test_calc_price_based_factors_handles_nan_without_crash():
    """個股當日change_pct/volume是NULL（例如停牌）時，該股當天被排除在計算之外，不crash、
    不悄悄產生錯誤數字（呼應v2資料層Plan1連續抓到4次的NaN/pd.NA洩漏問題）。"""
    universe = _make_universe([("E1", "sectorE"), ("E2", "sectorE")])
    prices = _make_price_rows([
        ("E1", "2026-07-01", 1.0, 1000), ("E1", "2026-07-02", 1.0, 1000), ("E1", "2026-07-03", None, 1000),
        ("E2", "2026-07-01", 1.0, 1000), ("E2", "2026-07-02", 1.0, 1000), ("E2", "2026-07-03", 1.0, None),
    ])

    result = _calc_price_based_factors(universe, prices)

    # 今日(07-03)：E1的change_pct是NULL被排除，只剩E2(1.0>0)有效 → up=1, total=1 → breadth_raw=1.0
    assert result["sectorE"]["breadth_raw"] == 1.0
    # 沒有crash（測試能跑到這裡就是最基本的驗證）；只有這個族群、universe跟族群均值完全相同，
    # 兩者cum3相同 → rs_raw應該是0.0（今日均值只採計E2一檔，跟universe同一份資料算出來一致）
    assert result["sectorE"]["rs_raw"] == 0.0
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_observation_scores.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'processors.observation_scores'`）

- [ ] **Step 3: 實作**

Create `processors/observation_scores.py`：

```python
"""
族群「觀察分」計算——決定族群優先展開順序，供首頁與逆轟策略頁共用。

設計 spec：docs/superpowers/specs/2026-07-17-meta-observation-scores-design.md

刻意的設計決定：這個模組完全獨立，不呼叫 processors/performance.py 裡任何既有函式
（calc_cumulative_meta/calc_universe_performance/calc_meta_signals/calc_meta_chips_signals），
單一 DuckDB 連線查完 daily_prices/institutional/margin，記憶體裡算完5因子。換取效能（不用開4次
連線）與跟既有4支函式的完全隔離；代價是 partial_coverage 等邏輯與 calc_meta_chips_signals()
重複一份，兩邊之後各自修正不會自動同步（見設計 spec §2）。
"""
from typing import Any, Dict, Optional

import duckdb
import pandas as pd

from streak_utils import calc_streak as _streak


def _calc_price_based_factors(
    universe_df: pd.DataFrame,
    price_df: pd.DataFrame,
) -> Dict[str, Dict[str, Any]]:
    """
    計算「觀察分」5因子中，來自 daily_prices 的4個因子原始值：
    rs_raw（相對強度，族群cum3 - universe cum3）、breadth_raw（今日上漲比例）、
    continuation_raw（連漲天數，原始未封頂）、volume_raw（集合量比）。

    price_df 需含欄位 stock_id/date/change_pct/volume，呼叫端負責只傳入
    最近N個交易日（這支函式不做日期過濾，用 price_df 裡實際出現的所有日期）。
    universe_df 需含 stock_id/meta_sector。

    Returns
    -------
    {meta_name: {
        "rs_raw": float | None,
        "breadth_raw": float | None,
        "continuation_raw": int | None,
        "volume_raw": float | None,
    }}
    """
    if price_df.empty:
        return {}

    universe = universe_df[["stock_id", "meta_sector"]].copy()
    universe["stock_id"] = universe["stock_id"].astype(str)
    prices = price_df.copy()
    prices["stock_id"] = prices["stock_id"].astype(str)

    merged = prices.merge(universe, on="stock_id", how="inner")
    if merged.empty:
        return {}
    all_dates = sorted(merged["date"].unique())
    today = all_dates[-1]
    all_metas = set(merged["meta_sector"].dropna().unique())

    valid_pct = merged.dropna(subset=["change_pct"])
    meta_daily_avg = valid_pct.groupby(["meta_sector", "date"])["change_pct"].mean()
    meta_pivot = meta_daily_avg.unstack(level="date").reindex(columns=all_dates)
    universe_daily_avg = valid_pct.groupby("date")["change_pct"].mean().reindex(all_dates)

    def _cum3(series: pd.Series) -> Optional[float]:
        window_dates = all_dates[-3:]
        if len(window_dates) < 3:
            return None
        values = [series.get(d) for d in window_dates]
        if any(v is None or pd.isna(v) for v in values):
            return None
        factor = 1.0
        for v in values:
            factor *= (1 + float(v) / 100)
        return round((factor - 1) * 100, 2)

    universe_cum3 = _cum3(universe_daily_avg)

    today_valid = valid_pct[valid_pct["date"] == today]
    up_counts = today_valid[today_valid["change_pct"] > 0].groupby("meta_sector").size()
    total_counts = today_valid.groupby("meta_sector").size()

    valid_vol = merged.dropna(subset=["volume"])
    meta_vol_sum = valid_vol.groupby(["meta_sector", "date"])["volume"].sum()
    vol_pivot = meta_vol_sum.unstack(level="date").reindex(columns=all_dates)

    results: Dict[str, Dict[str, Any]] = {}
    for meta_name in all_metas:
        # 相對強度
        meta_cum3 = _cum3(meta_pivot.loc[meta_name]) if meta_name in meta_pivot.index else None
        rs_raw = (
            round(meta_cum3 - universe_cum3, 2)
            if meta_cum3 is not None and universe_cum3 is not None
            else None
        )

        # 族群廣度
        if meta_name in total_counts.index:
            total = int(total_counts.loc[meta_name])
            up = int(up_counts.get(meta_name, 0))
            breadth_raw = round(up / total, 4) if total > 0 else None
        else:
            breadth_raw = None

        # 延續性（原始streak，未封頂；跳過缺值日，用剩餘有效日照時間順序算，
        # 不強求streak一定要以「今日」為終點——資料不足時流失的只是可能低估天數，不會是None）
        if meta_name in meta_pivot.index:
            meta_series = meta_pivot.loc[meta_name].dropna()
            pct_values = [float(meta_series[d]) for d in all_dates if d in meta_series.index]
            continuation_raw = _streak(pct_values) if pct_values else None
        else:
            continuation_raw = None

        # 成分股量能參與：明確要求「今日」本身有valid volume，避免今日缺值時
        # 誤把「最近一個有量的日子」當成今日、悄悄算出跟今天無關的比值
        if meta_name in vol_pivot.index and pd.notna(vol_pivot.loc[meta_name].get(today)):
            vol_row = vol_pivot.loc[meta_name]
            today_vol = float(vol_row[today])
            prior_dates = [d for d in all_dates[:-1] if d in vol_row.index and pd.notna(vol_row[d])]
            if len(prior_dates) >= 5:
                past_vols = [float(vol_row[d]) for d in prior_dates[-5:]]
                avg_vol = sum(past_vols) / len(past_vols)
                volume_raw = round(today_vol / avg_vol, 2) if avg_vol > 0 else None
            else:
                volume_raw = None
        else:
            volume_raw = None

        results[meta_name] = {
            "rs_raw": rs_raw,
            "breadth_raw": breadth_raw,
            "continuation_raw": continuation_raw,
            "volume_raw": volume_raw,
        }

    return results
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_observation_scores.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add processors/observation_scores.py tests/test_observation_scores.py
git commit -m "feat(observation-scores): 新增_calc_price_based_factors算相對強度/廣度/延續性/量能參與4因子原始值"
```

---

### Task 2: `_calc_chips_factor()`——籌碼確認因子原始值（獨立重寫 partial_coverage）

**Files:**
- Modify: `processors/observation_scores.py`
- Test: `tests/test_observation_scores.py`

**Interfaces:**
- Consumes：`universe_df`（欄位至少含 `stock_id`/`meta_sector`/`exchange`）、`inst_df`（欄位 `stock_id`/`date`/`foreign_net`，呼叫端負責只傳入 institutional 表最新一個交易日的資料）、`margin_df`（欄位 `stock_id`/`date`，呼叫端負責只傳入 margin 表**自己**最新一個交易日的資料，不能綁 institutional 的日期，兩表發布日可能不同步）。
- Produces：`Dict[str, Dict[str, Any]]`，key是`meta_name`（涵蓋 `universe_df` 裡所有族群），value含 `chips_raw`(float|None)、`partial_coverage`(bool)。

- [ ] **Step 1: 寫失敗測試**

Append to `tests/test_observation_scores.py`：

```python
from processors.observation_scores import _calc_chips_factor


def _make_chips_universe(rows):
    """rows: list of (stock_id, meta_sector, exchange)"""
    return pd.DataFrame(rows, columns=["stock_id", "meta_sector", "exchange"])


def _make_inst_rows(rows):
    """rows: list of (stock_id, date, foreign_net)"""
    return pd.DataFrame(rows, columns=["stock_id", "date", "foreign_net"])


def _make_margin_rows(rows):
    """rows: list of (stock_id, date)"""
    return pd.DataFrame(rows, columns=["stock_id", "date"])


def test_calc_chips_factor_no_partial_coverage_when_all_exchanges_present():
    """族群橫跨TWSE+TPEx，今天institutional跟margin兩邊都有兩個交易所的資料 → 不標記partial_coverage。"""
    universe = _make_chips_universe([
        ("1101", "測試族群", "TWSE"),
        ("6488", "測試族群", "TPEx"),
    ])
    inst_df = _make_inst_rows([
        ("1101", "2026-07-03", 1000),
        ("6488", "2026-07-03", 500),
    ])
    margin_df = _make_margin_rows([
        ("1101", "2026-07-03"),
        ("6488", "2026-07-03"),
    ])

    result = _calc_chips_factor(universe, inst_df, margin_df)

    assert result["測試族群"]["partial_coverage"] is False
    assert result["測試族群"]["chips_raw"] == 1.0  # 1101、6488都foreign_net>0 → 2/2買超檔數比例


def test_calc_chips_factor_flags_partial_coverage_when_exchange_missing():
    """族群橫跨TWSE+TPEx，但今天institutional只有TWSE資料（模擬TPEx抓取失敗）→ 標記partial_coverage。"""
    universe = _make_chips_universe([
        ("1101", "測試族群", "TWSE"),
        ("6488", "測試族群", "TPEx"),
    ])
    inst_df = _make_inst_rows([
        ("1101", "2026-07-03", 1000),
        # 6488(TPEx) 今日沒有institutional資料
    ])
    margin_df = _make_margin_rows([
        ("1101", "2026-07-03"),
        ("6488", "2026-07-03"),
    ])

    result = _calc_chips_factor(universe, inst_df, margin_df)

    assert result["測試族群"]["partial_coverage"] is True
    # chips_raw仍算得出來（只是涵蓋不全）：total_stocks只算「今日institutional實際有資料的交易所」
    # 涵蓋的檔數（只有TWSE=1檔），buy_count=1（1101） → 1/1=1.0
    assert result["測試族群"]["chips_raw"] == 1.0


def test_calc_chips_factor_excludes_nan_foreign_net_from_buy_count():
    """個股foreign_net是NULL時（缺值），該股被排除在買超檔數分子之外，不crash。
    分母(total_stocks)是「該族群在有資料的交易所裡的全部檔數」，不是逐股完整度檢查，
    這跟既有calc_meta_chips_signals()的既有行為一致，不是這次新增的bug。"""
    universe = _make_chips_universe([
        ("1101", "測試族群", "TWSE"),
        ("2330", "測試族群", "TWSE"),
    ])
    inst_df = _make_inst_rows([
        ("1101", "2026-07-03", 1000),
        ("2330", "2026-07-03", None),  # NULL，模擬缺值
    ])
    margin_df = _make_margin_rows([
        ("1101", "2026-07-03"),
        ("2330", "2026-07-03"),
    ])

    result = _calc_chips_factor(universe, inst_df, margin_df)

    assert result["測試族群"]["chips_raw"] == 0.5  # buy_count=1(僅1101) / total_stocks=2(TWSE全部檔數)
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_observation_scores.py -q -k chips_factor`
Expected: FAIL（`ImportError: cannot import name '_calc_chips_factor'`）

- [ ] **Step 3: 實作**

Append to `processors/observation_scores.py`：

```python
def _calc_chips_factor(
    universe_df: pd.DataFrame,
    inst_df: pd.DataFrame,
    margin_df: pd.DataFrame,
) -> Dict[str, Dict[str, Any]]:
    """
    計算「觀察分」5因子中的籌碼確認因子原始值：chips_raw（外資買超檔數比例）、
    partial_coverage（跨交易所資料涵蓋是否不全）。

    獨立重寫版本的跨交易所涵蓋度判斷邏輯，刻意不呼叫 calc_meta_chips_signals()
    （見設計 spec §2 的取捨說明——效能與隔離性換維護成本）。

    inst_df 需含 stock_id/date/foreign_net，呼叫端只傳 institutional 表最新一天的資料。
    margin_df 需含 stock_id/date，呼叫端只傳 margin 表**自己**最新一天的資料（margin
    跟 institutional 發布日可能不同步，不能共用同一個 today）。
    universe_df 需含 stock_id/meta_sector/exchange。

    Returns
    -------
    {meta_name: {
        "chips_raw": float | None,
        "partial_coverage": bool,
    }}
    """
    universe = universe_df[["stock_id", "meta_sector", "exchange"]].copy()
    universe["stock_id"] = universe["stock_id"].astype(str)

    meta_all_exchanges: Dict[str, set] = {
        name: set(grp.dropna().unique())
        for name, grp in universe.groupby("meta_sector")["exchange"]
    }
    meta_stock_count_by_exchange = universe.groupby(["meta_sector", "exchange"])["stock_id"].count()
    all_metas = set(universe["meta_sector"].dropna().unique())

    inst = inst_df.copy()
    inst["stock_id"] = inst["stock_id"].astype(str)
    inst_merged = inst.merge(universe, on="stock_id", how="inner")
    inst_merged = inst_merged.dropna(subset=["foreign_net", "meta_sector"])

    margin = margin_df.copy()
    margin["stock_id"] = margin["stock_id"].astype(str)
    margin_merged = margin.merge(universe, on="stock_id", how="inner")
    margin_covered_by_meta: Dict[str, set] = {
        name: set(grp["exchange"].dropna().unique())
        for name, grp in margin_merged.groupby("meta_sector")
    }

    results: Dict[str, Dict[str, Any]] = {}
    for meta_name in all_metas:
        meta_inst = inst_merged[inst_merged["meta_sector"] == meta_name]
        covered_exchanges = meta_inst["exchange"].dropna().unique().tolist()

        if covered_exchanges and meta_name in meta_stock_count_by_exchange.index.get_level_values(0):
            total_stocks = int(
                meta_stock_count_by_exchange.loc[meta_name]
                .reindex(covered_exchanges).fillna(0).sum()
            )
        else:
            total_stocks = 0

        buy_count = int((meta_inst["foreign_net"] > 0).sum())
        chips_raw = round(buy_count / total_stocks, 4) if total_stocks > 0 else None

        expected_exchanges = meta_all_exchanges.get(meta_name, set())
        inst_partial = bool(expected_exchanges - set(covered_exchanges))
        margin_partial = bool(expected_exchanges - margin_covered_by_meta.get(meta_name, set()))
        partial_coverage = inst_partial or margin_partial

        results[meta_name] = {"chips_raw": chips_raw, "partial_coverage": partial_coverage}

    return results
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_observation_scores.py -q`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add processors/observation_scores.py tests/test_observation_scores.py
git commit -m "feat(observation-scores): 新增_calc_chips_factor算籌碼確認因子，獨立重寫partial_coverage判斷"
```

---

### Task 3: `calc_meta_observation_scores()`——查詢組裝、百分位排名、reweight、最終分數

**Files:**
- Modify: `processors/observation_scores.py`
- Test: `tests/test_observation_scores.py`

**Interfaces:**
- Consumes：`universe_df`（欄位含 `stock_id`/`meta_sector`/`exchange`）、`db_path`（預設 `"data/screener.db"`）。
- Produces：`Dict[str, Dict[str, Any]]`，完整欄位見下方 docstring。這是本次要交付給消費端（首頁+逆轟頁未來的 Plan 3）使用的公開函式。

- [ ] **Step 1: 寫失敗測試**

Append to `tests/test_observation_scores.py`：

```python
import duckdb
from processors.observation_scores import calc_meta_observation_scores


def _seed_observation_db(db_path, price_rows, inst_rows=None, margin_rows=None):
    """price_rows: list of (stock_id, date, change_pct, volume)
    inst_rows: list of (stock_id, date, foreign_net)
    margin_rows: list of (stock_id, date)"""
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE daily_prices (
            stock_id VARCHAR, date DATE, change_pct DOUBLE, volume BIGINT
        )
    """)
    con.executemany("INSERT INTO daily_prices VALUES (?, ?, ?, ?)", price_rows)
    con.execute("""
        CREATE TABLE institutional (
            stock_id VARCHAR, date DATE, foreign_net BIGINT
        )
    """)
    if inst_rows:
        con.executemany("INSERT INTO institutional VALUES (?, ?, ?)", inst_rows)
    con.execute("""
        CREATE TABLE margin (
            stock_id VARCHAR, date DATE
        )
    """)
    if margin_rows:
        con.executemany("INSERT INTO margin VALUES (?, ?)", margin_rows)
    con.close()


def _make_full_universe(rows):
    """rows: list of (stock_id, meta_sector, exchange)"""
    return pd.DataFrame(rows, columns=["stock_id", "meta_sector", "exchange"])


def test_calc_meta_observation_scores_end_to_end_all_factors_available():
    """完整6天資料（滿足量能參與需要的天數）+ 齊全籌碼資料，2個族群，5因子全部可算，
    驗證score_coverage=1.0（無缺項）、observation_score落在合理範圍、原始值都有填。"""
    import tempfile, pathlib
    db_path = pathlib.Path(tempfile.mkdtemp()) / "test.db"

    universe = _make_full_universe([
        ("A1", "sectorA", "TWSE"), ("A2", "sectorA", "TWSE"),
        ("B1", "sectorB", "TWSE"),
    ])

    price_rows = []
    for d in range(25, 30):  # 5天暖身資料
        price_rows.append(("A1", f"2026-06-{d:02d}", 1.0, 1000))
        price_rows.append(("A2", f"2026-06-{d:02d}", -1.0, 1000))
        price_rows.append(("B1", f"2026-06-{d:02d}", 2.0, 1000))
    # 今日(06-30)
    price_rows.append(("A1", "2026-06-30", 1.0, 1000))
    price_rows.append(("A2", "2026-06-30", -1.0, 1000))
    price_rows.append(("B1", "2026-06-30", 2.0, 2500))  # B1今日爆量

    inst_rows = [
        ("A1", "2026-06-30", 1000), ("A2", "2026-06-30", -500), ("B1", "2026-06-30", 800),
    ]
    margin_rows = [("A1", "2026-06-30"), ("A2", "2026-06-30"), ("B1", "2026-06-30")]

    _seed_observation_db(db_path, price_rows, inst_rows, margin_rows)

    result = calc_meta_observation_scores(universe, db_path=str(db_path))

    assert result["sectorA"]["score_coverage"] == 1.0
    assert result["sectorB"]["score_coverage"] == 1.0
    assert result["sectorA"]["observation_score"] is not None
    assert result["sectorB"]["observation_score"] is not None
    # sectorB全面優於sectorA（漲幅更高、量能爆量、外資買超檔數比例更高），分數應該更高
    assert result["sectorB"]["observation_score"] > result["sectorA"]["observation_score"]
    # 原始值都要有填，供UI顯示
    for meta in ("sectorA", "sectorB"):
        assert result[meta]["rs_raw"] is not None
        assert result[meta]["breadth_raw"] is not None
        assert result[meta]["continuation_raw"] is not None


def test_calc_meta_observation_scores_reweights_when_chips_partial_coverage():
    """族群橫跨TWSE+TPEx但今日籌碼資料只有TWSE到齊 → chips因子視為不可用，
    score_coverage應該是1.0-0.10=0.90（不是1.0，也不是誤把chips_raw當0分計入）。"""
    import tempfile, pathlib
    db_path = pathlib.Path(tempfile.mkdtemp()) / "test.db"

    universe = _make_full_universe([
        ("C1", "sectorC", "TWSE"), ("C2", "sectorC", "TPEx"),
    ])
    price_rows = []
    for d in range(25, 31):
        price_rows.append(("C1", f"2026-06-{d:02d}", 0.5, 1000))
        price_rows.append(("C2", f"2026-06-{d:02d}", 0.5, 1000))
    inst_rows = [("C1", "2026-06-30", 500)]  # C2(TPEx)今日缺institutional資料
    margin_rows = [("C1", "2026-06-30"), ("C2", "2026-06-30")]

    _seed_observation_db(db_path, price_rows, inst_rows, margin_rows)

    result = calc_meta_observation_scores(universe, db_path=str(db_path))

    assert result["sectorC"]["score_coverage"] == 0.90
    assert result["sectorC"]["observation_score"] is not None  # 其餘4因子仍可算


def test_calc_meta_observation_scores_all_factors_unavailable_returns_none_score():
    """族群完全沒有任何天期資料（例如全新上市族群），5因子全不可用時仍要回傳這個族群
    （不能從結果消失），observation_score=None、score_coverage=0。"""
    import tempfile, pathlib
    db_path = pathlib.Path(tempfile.mkdtemp()) / "test.db"

    # universe裡登記了sectorD，但daily_prices/institutional/margin完全沒有D1的任何資料
    universe = _make_full_universe([
        ("D1", "sectorD", "TWSE"),
        ("E1", "sectorE", "TWSE"),  # sectorE有正常資料，用來讓價格類查詢不會整批提早return {}
    ])
    price_rows = [("E1", f"2026-06-{d:02d}", 0.5, 1000) for d in range(25, 31)]
    _seed_observation_db(db_path, price_rows, inst_rows=[("E1", "2026-06-30", 500)],
                          margin_rows=[("E1", "2026-06-30")])

    result = calc_meta_observation_scores(universe, db_path=str(db_path))

    assert "sectorD" in result
    assert result["sectorD"]["observation_score"] is None
    assert result["sectorD"]["score_coverage"] == 0
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_observation_scores.py -q -k end_to_end or reweights or all_factors_unavailable`
Expected: FAIL（`ImportError: cannot import name 'calc_meta_observation_scores'`）

- [ ] **Step 3: 實作**

Append to `processors/observation_scores.py`（模組層級常數放在檔案最上方 import 區塊之後，函式放在檔案最後）：

在檔案最上方 `from streak_utils import calc_streak as _streak` 之後新增：

```python
_PRICE_LOOKBACK_DAYS = 11  # 涵蓋cum3(3天)、streak(視資料而定)、量能參與(今日+5天)所需的查詢窗口
_RS_WEIGHT = 0.30
_BREADTH_WEIGHT = 0.25
_CONTINUATION_WEIGHT = 0.20
_VOLUME_WEIGHT = 0.15
_CHIPS_WEIGHT = 0.10
_CONTINUATION_CAP_DAYS = 5  # 延續性因子封頂天數：連漲5天(以上)=滿分
```

在檔案最後新增：

```python
def calc_meta_observation_scores(
    universe_df: pd.DataFrame,
    db_path: str = "data/screener.db",
) -> Dict[str, Dict[str, Any]]:
    """
    首頁與逆轟頁共用的「觀察分」，決定族群優先展開順序（非最終買賣動作）。

    完全獨立實作：不呼叫 processors/performance.py 的 calc_cumulative_meta()/
    calc_universe_performance()/calc_meta_signals()/calc_meta_chips_signals()，
    單一 DuckDB 連線查完 daily_prices/institutional/margin 後在記憶體算完。刻意的
    設計決定，換取效能（不用開4次連線）與跟既有4支函式的完全隔離；代價是
    partial_coverage 等邏輯與 calc_meta_chips_signals() 重複一份，兩邊之後各自
    修正不會自動同步，見設計 spec §2。

    Returns
    -------
    {meta_name: {
        "observation_score": float | None,  # 0~100，5因子全不可用時 None
        "score_coverage": float,            # 0~1，實際可用權重比例
        "rs_raw": float | None,             # cum3差值（%），供UI顯示原始值，非0~1
        "breadth_raw": float | None,        # 今日上漲比例（0~1，本身就是最終用於加權的值）
        "continuation_raw": int | None,     # streak天數（原始整數，未封頂，供UI顯示）
        "volume_raw": float | None,         # 集合量比（原始值，非0~1）
        "chips_raw": float | None,          # foreign_buy_ratio（0~1，本身就是最終用於加權的值）
        "partial_coverage": bool,           # 籌碼資料是否涵蓋不全（chips_raw為None時的可能原因）
    }}
    """
    con = duckdb.connect(db_path, read_only=True)
    try:
        price_dates_df = con.execute(
            f"SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT {_PRICE_LOOKBACK_DAYS}"
        ).fetchdf()
        if price_dates_df.empty:
            return {}
        min_price_date = price_dates_df["date"].min()
        price_df = con.execute(
            "SELECT stock_id, date, change_pct, volume FROM daily_prices WHERE date >= ?",
            [min_price_date],
        ).fetchdf()

        inst_latest = con.execute("SELECT MAX(date) FROM institutional").fetchone()[0]
        if inst_latest is not None:
            inst_df = con.execute(
                "SELECT stock_id, date, foreign_net FROM institutional WHERE date = ?",
                [inst_latest],
            ).fetchdf()
        else:
            inst_df = pd.DataFrame(columns=["stock_id", "date", "foreign_net"])

        margin_latest = con.execute("SELECT MAX(date) FROM margin").fetchone()[0]
        if margin_latest is not None:
            margin_df = con.execute(
                "SELECT stock_id, date FROM margin WHERE date = ?",
                [margin_latest],
            ).fetchdf()
        else:
            margin_df = pd.DataFrame(columns=["stock_id", "date"])
    finally:
        con.close()

    price_factors = _calc_price_based_factors(universe_df, price_df)
    chips_factors = _calc_chips_factor(universe_df, inst_df, margin_df)

    all_metas = set(universe_df["meta_sector"].dropna().unique()) | set(price_factors.keys())
    if not all_metas:
        return {}

    rs_series = pd.Series(
        {m: price_factors.get(m, {}).get("rs_raw") for m in all_metas}, dtype="float64"
    )
    volume_series = pd.Series(
        {m: price_factors.get(m, {}).get("volume_raw") for m in all_metas}, dtype="float64"
    )
    rs_rank = rs_series.rank(pct=True, ascending=True)
    volume_rank = volume_series.rank(pct=True, ascending=True)

    results: Dict[str, Dict[str, Any]] = {}
    for meta_name in all_metas:
        pf = price_factors.get(meta_name, {})
        cf = chips_factors.get(meta_name, {"chips_raw": None, "partial_coverage": False})

        rs_raw = pf.get("rs_raw")
        breadth_raw = pf.get("breadth_raw")
        continuation_raw = pf.get("continuation_raw")
        volume_raw = pf.get("volume_raw")
        chips_raw = cf.get("chips_raw")
        partial_coverage = bool(cf.get("partial_coverage", False))

        weighted_sum = 0.0
        coverage = 0.0

        if rs_raw is not None and pd.notna(rs_rank.get(meta_name)):
            weighted_sum += _RS_WEIGHT * float(rs_rank[meta_name])
            coverage += _RS_WEIGHT
        if breadth_raw is not None:
            weighted_sum += _BREADTH_WEIGHT * breadth_raw
            coverage += _BREADTH_WEIGHT
        if continuation_raw is not None:
            continuation_score = (
                min(max(continuation_raw, 0), _CONTINUATION_CAP_DAYS) / _CONTINUATION_CAP_DAYS
            )
            weighted_sum += _CONTINUATION_WEIGHT * continuation_score
            coverage += _CONTINUATION_WEIGHT
        if volume_raw is not None and pd.notna(volume_rank.get(meta_name)):
            weighted_sum += _VOLUME_WEIGHT * float(volume_rank[meta_name])
            coverage += _VOLUME_WEIGHT
        if chips_raw is not None and not partial_coverage:
            weighted_sum += _CHIPS_WEIGHT * chips_raw
            coverage += _CHIPS_WEIGHT

        observation_score = round(100 * weighted_sum / coverage, 1) if coverage > 0 else None

        results[meta_name] = {
            "observation_score": observation_score,
            "score_coverage": round(coverage, 2),
            "rs_raw": rs_raw,
            "breadth_raw": breadth_raw,
            "continuation_raw": continuation_raw,
            "volume_raw": volume_raw,
            "chips_raw": chips_raw,
            "partial_coverage": partial_coverage,
        }

    return results
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_observation_scores.py -q`
Expected: PASS（9 passed）

- [ ] **Step 5: Commit**

```bash
git add processors/observation_scores.py tests/test_observation_scores.py
git commit -m "feat(observation-scores): 新增calc_meta_observation_scores()組裝5因子、百分位排名、reweight（v2 spec §2.2）"
```

---

## Self-Review（對照 spec 逐項檢查）

- **5因子精確公式**（spec §3）：Task 1 覆蓋相對強度/族群廣度/延續性/成分股量能參與4項，Task 2 覆蓋籌碼確認1項，全部覆蓋。
- **歸一化**（spec §3.1）：Task 3 對 `rs_raw`/`volume_raw` 做跨族群百分位排名，`breadth_raw`/`chips_raw`（已是0~1）與 `continuation_raw`（已封頂）直接使用，完全對應。
- **reweight機制+score_coverage**（spec §4）：Task 3 完整實作，含「5因子全不可用時仍回傳、observation_score=None」的邊界情況（`test_calc_meta_observation_scores_all_factors_unavailable_returns_none_score`覆蓋）。
- **完全獨立實作**（spec §2）：三個函式都不呼叫 `processors/performance.py` 既有函式，只重用通用工具 `streak_utils.calc_streak()`，符合 Global Constraints 的明確授權。
- **margin用自己的最新日期**（spec §3.2）：Task 3 的 `margin_latest = con.execute("SELECT MAX(date) FROM margin")` 獨立查詢，不綁 institutional 的 `inst_latest`，對應。
- **函式簽章/docstring**（spec §5）：Task 3 的 `calc_meta_observation_scores()` docstring 逐欄位對應 spec，一致。
- **NA/NaN防呆**（spec §6驗收條件最後一項）：Task 1 的 `.dropna(subset=["change_pct"])`/`.dropna(subset=["volume"])`/`pd.notna()`守衛、Task 2 的 `.dropna(subset=["foreign_net", "meta_sector"])`，全部沿用 pandas 原生NA感知方法，且各自有對應的NaN regression test（`test_calc_price_based_factors_handles_nan_without_crash`、`test_calc_chips_factor_excludes_nan_foreign_net_from_buy_count`）。
- **檔案位置**：新建 `processors/observation_scores.py`（Cody已拍板，因 `processors/performance.py` 已871行超過800行上限，且這次完全獨立不共用既有函式，是自然新檔邊界）。

## No Placeholder 掃描

三個Task的程式碼區塊都是可以直接貼上執行的完整程式碼，測試斷言皆為具體數值比對（例如 `assert result["sectorB"]["rs_raw"] == 4.11`），沒有「add assertion here」這類空泛寫法。

## Type Consistency 掃描

- Task 1 定義的4個欄位名稱（`rs_raw`/`breadth_raw`/`continuation_raw`/`volume_raw`）在 Task 3 組裝時逐字對應使用（`pf.get("rs_raw")` 等），一致。
- Task 2 定義的 `chips_raw`/`partial_coverage` 在 Task 3 組裝時逐字對應使用（`cf.get("chips_raw")`/`cf.get("partial_coverage")`），一致。
- Task 3 最終回傳的8個欄位名稱與 spec §5 docstring 逐字核對一致。
- 模組層級常數命名（`_RS_WEIGHT` 等）三個Task間沒有互相衝突或改名。

## Out of scope（本次不做，spec §7 已列）

- 把 `index.html` 排序邏輯換成消費這支函式（Plan 3整合工作）。
- `export/momentum_generator.py` 本身（Plan 3）。
- 回測驗證5因子權重/門檻是否有效（獨立任務，不跟這次資料層/計算邏輯開發綁一起）。
