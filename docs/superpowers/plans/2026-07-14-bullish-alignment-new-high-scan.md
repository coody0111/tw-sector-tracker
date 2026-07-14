# 通用多頭排列＋創新高掃描 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `screener/signals.py::scan_bullish_alignment_new_high()`，掃描全市場個股，只回傳「多頭排列（close>MA5>MA10>MA60）且創新高（收盤價突破過去 N 個交易日的最高收盤）」同時成立的股票，供進場雷達使用。

**Architecture:** 沿用 `scan_volume_turnover()` 的既有慣例（DuckDB read-only 查詢、逐股 groupby、graceful skip 歷史不足的股票、回傳「已過濾」的 list of dict，不是像 `scan_momentum_health`——尚未實作——那樣的全市場健檢字典）。跟既有 `patterns.py::detect_breakout_confirm`（「多頭拐點」）並存，不修改、不呼叫它：那支限定 MA60 走平才轉折（抓長期盤整後啟動），這支不要求 MA60 走平（抓已在乾淨多頭排列中的續強訊號），兩者用途不同。

**Tech Stack:** Python, pandas, DuckDB（既有依賴，無新套件）

## Global Constraints

- 均線最少歷史門檻：`max(60, lookback_days)` 個交易日（MA60 本身需要 60 筆）
- 創新高比較窗口預設 **60 個交易日**（`_DEFAULT_LOOKBACK_DAYS`，約一季，「波段新高」而非「歷史新高」——理由見 spec「創新高」節：全市場個股歷史回補深度不穩定，全歷史比較會系統性偏誤，回補淺的股票更容易被誤判創新高）
- 均線口徑用 **MA5/MA10/MA60**（不是 `detect_breakout_confirm` 的 MA5/MA20/MA60——動能派策略用 MA10，見 mapping spec B1/B3）
- ⚠️ **已知限制、本次不修**：「創新高」用原始收盤價，不是還原股價（本專案目前沒有任何還原股價資料源，TWSE/TPEx 官方每日資料是原始價，yfinance 回補是否為還原價依版本 `auto_adjust` 預設值而定、本專案未鎖定）。除權息當天原始價跳空下修，可能讓除權息後短期內的個股被誤判「沒創新高」——這是**假陰性**（漏抓，不是誤報），相對安全但不精確。真正修法（`daily_prices` 加還原價欄位）是獨立資料層任務，不在這次範圍。
- 本次範圍**不含**頁面 UI 呈現、**不含**併入 `calc_composite_score()` 的 pattern 加分清單（權重討論獨立於「訊號存不存在」，留給 Developer/Cody 之後決定）
- 對照 spec：`docs/superpowers/specs/2026-07-14-bullish-alignment-new-high-scan-design.md`

---

### Task 1: 多頭排列＋創新高核心偵測

**Files:**
- Modify: `screener/signals.py`（新增常數、`_load_universe_map()` 加 `universe_path` 參數、新增 `scan_bullish_alignment_new_high()`）
- Test: `tests/test_signals.py`

**Interfaces:**
- Consumes：DuckDB `daily_prices` 表（`stock_id, date, close, change_pct`）；`data/stock_universe.csv`（`stock_id, stock_name, meta_sector`）
- Produces：`scan_bullish_alignment_new_high(trade_date: str, lookback_days: int = 60, db_path: str = _DB_PATH, universe_path: str = _UNIVERSE_PATH) -> List[Dict[str, Any]]`，只回傳「多頭排列 且 創新高」都成立的股票，依 `change_pct` 降序，每筆 dict 含 `stock_id, stock_name, meta_sector, close, change_pct, ma5, ma10, ma60, lookback_days`

- [ ] **Step 1: 寫失敗測試 — 三種情境（命中/多頭但非新高/新高但非多頭）+ 歷史不足跳過**

在 `tests/test_signals.py` 檔案開頭加入 import（跟既有 import 放一起）：

```python
import pandas as pd
from screener.signals import scan_volume_turnover, scan_bullish_alignment_new_high
```

在檔案最後面新增：

```python
def test_scan_bullish_alignment_new_high_filters_correctly(tmp_path):
    """三種情境同時測試，避免像 detect_breakout_confirm 早期版本那樣只驗證單一條件：
    (1) 多頭排列 + 創新高 → 命中
    (2) 多頭排列，但今日收盤不是窗口內最高（前面有更高的收盤）→ 排除
    (3) 創新高（單日急拉），但不是多頭排列（下跌趨勢中 MA10 < MA60）→ 排除
    """
    db_path = tmp_path / "test.db"
    dates = pd.date_range("2026-01-01", periods=60, freq="D")

    rows = []

    # 1101：60 天穩定上升（close = 100+i），今日收盤是窗口內最高，且多頭排列
    close_1101 = [100 + i for i in range(60)]
    for d, c in zip(dates, close_1101):
        rows.append(("1101", d.strftime("%Y-%m-%d"), float(c), 0.5, 1000))

    # 1102：前 58 天同樣上升到 157（i=57），最後兩天回檔到 155/156——
    # 今日(156)仍然是多頭排列（MA5/MA10/MA60 都還在下方），但不是窗口最高（157 更高）
    close_1102 = [100 + i for i in range(58)] + [155, 156]
    for d, c in zip(dates, close_1102):
        rows.append(("1102", d.strftime("%Y-%m-%d"), float(c), 0.1, 1000))

    # 1103：59 天緩跌（200 → 約101），今日單日急拉到 250——
    # 250 是窗口內最高（創新高成立），但 MA10 仍低於 MA60（下跌趨勢均線還沒排列成多頭）
    close_1103 = [round(200 - i * 1.7, 2) for i in range(59)] + [250.0]
    for d, c in zip(dates, close_1103):
        rows.append(("1103", d.strftime("%Y-%m-%d"), float(c), 5.0, 1000))

    _seed_db(db_path, rows)

    results = scan_bullish_alignment_new_high(dates[-1].strftime("%Y-%m-%d"), db_path=str(db_path))
    ids = [r["stock_id"] for r in results]

    assert "1101" in ids, "多頭排列 + 創新高都成立，應命中"
    assert "1102" not in ids, "多頭排列成立，但今日非窗口內最高收盤，不該命中"
    assert "1103" not in ids, "今日創新高，但均線不是多頭排列（下跌趨勢中的單日急拉），不該命中"

    hit = next(r for r in results if r["stock_id"] == "1101")
    assert hit["ma5"] == 157.0
    assert hit["ma10"] == 154.5
    assert hit["ma60"] == 129.5
    assert hit["lookback_days"] == 60


def test_scan_bullish_alignment_new_high_skips_insufficient_history(tmp_path):
    """歷史資料 < max(60, lookback_days) 筆時，直接跳過不產生結果，不 crash。"""
    db_path = tmp_path / "test.db"
    rows = [("1101", f"2026-01-{d:02d}", 100.0 + d, 0.1, 1000) for d in range(1, 30)]
    _seed_db(db_path, rows)

    results = scan_bullish_alignment_new_high("2026-01-29", db_path=str(db_path))

    assert results == []


def test_scan_bullish_alignment_new_high_lookback_days_changes_boundary(tmp_path):
    """lookback_days 決定「創新高」的比較窗口：120 天前有過一次高點(300)，
    60 天窗口看不到那次高點 → 判定創新高；120 天窗口看得到 → 判定非創新高。
    同一組資料、同一天，只改 lookback_days，結果應該不同。"""
    db_path = tmp_path / "test.db"
    dates = pd.date_range("2026-01-01", periods=120, freq="D")

    ancient = [110.0] * 60
    ancient[30] = 300.0  # 120 天前的舊高點，只有 lookback=120 才看得到
    recent = [round(150 + i * (205 - 150) / 59, 2) for i in range(60)]  # 近60天穩定上升到205
    closes = ancient + recent
    rows = [("1101", d.strftime("%Y-%m-%d"), c, 0.1, 1000) for d, c in zip(dates, closes)]
    _seed_db(db_path, rows)

    today_str = dates[-1].strftime("%Y-%m-%d")
    results_60 = scan_bullish_alignment_new_high(today_str, lookback_days=60, db_path=str(db_path))
    results_120 = scan_bullish_alignment_new_high(today_str, lookback_days=120, db_path=str(db_path))

    assert "1101" in [r["stock_id"] for r in results_60], "60天窗口看不到120天前的300高點，應判定創新高"
    assert "1101" not in [r["stock_id"] for r in results_120], "120天窗口看得到那次300高點，不該判定創新高"
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_signals.py -k bullish_alignment_new_high -v`
Expected: FAIL，錯誤訊息類似 `ImportError: cannot import name 'scan_bullish_alignment_new_high'`

- [ ] **Step 3: 實作 `scan_bullish_alignment_new_high()`**

把既有的 `_load_universe_map()` 改成接受可選路徑參數（向下相容，`scan_volume_turnover` 既有呼叫端不用改；若 `docs/superpowers/plans/2026-07-02-momentum-health-signal.md` 已經先落地過這個改動，這一步是 no-op，確認簽名一致即可）：

```python
def _load_universe_map(universe_path: str = _UNIVERSE_PATH) -> dict:
    try:
        df = pd.read_csv(universe_path, usecols=["stock_id", "stock_name", "meta_sector"], dtype=str)
        return df.set_index("stock_id")[["stock_name", "meta_sector"]].to_dict("index")
    except Exception:
        return {}
```

在 `_MIN_WINDOW_DAYS = 20` 那行下方新增常數：

```python
# 通用多頭排列＋創新高掃描常數（動能派筆記十一/四十五；mapping spec B3）
_DEFAULT_LOOKBACK_DAYS = 60  # 「創新高」比較窗口，約一季（波段新高，非歷史新高，理由見 design spec）
```

在檔案最後面（`scan_volume_turnover()` 之後）新增：

```python
def scan_bullish_alignment_new_high(
    trade_date: str,
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    db_path: str = _DB_PATH,
    universe_path: str = _UNIVERSE_PATH,
) -> List[Dict[str, Any]]:
    """
    通用多頭排列＋創新高掃描（動能派筆記十一、四十五；mapping spec B3）。

    跟 patterns.py::detect_breakout_confirm（「多頭拐點」）不同：那支限定 MA60
    要先走平才轉折，抓的是「長期盤整後啟動」；這支不要求 MA60 走平，抓「已經在
    乾淨多頭排列、還在創新高」的續強訊號，兩者並存、互補（一個抓啟動、一個抓續強），
    這支不修改也不呼叫 detect_breakout_confirm。

    均線用 5/10/60（不是既有 detect_breakout_confirm 的 5/20/60——動能派策略用
    MA10 不是 MA20，見 mapping spec B1/B3）。

    ⚠️ 已知限制（未修復，記錄於此避免誤用）：「創新高」用的是原始收盤價
    （daily_prices.close，TWSE/TPEx 官方每日資料本來就是原始價；yfinance 回補
    是否為還原價則依安裝版本的 auto_adjust 預設值而定，本專案未明確鎖定，見
    scrapers/backfill.py::_fetch_yfinance_one_stock）。除權息當天原始價會跳空
    下修，可能讓除權息後短期內的個股被誤判「沒創新高」（假陰性，不是假陽性——
    不會多顯示錯誤訊號，只會少顯示，相對安全但仍不精確）。專案目前沒有任何還原
    股價資料源可用，這是資料面的既有缺口，不在這次範圍內修。

    lookback_days 預設 60（約一季，「波段新高」，不是「歷史新高」）：全市場個股
    的歷史回補深度不穩定，用全歷史「歷史新高」在資料不齊時會產生系統性偏誤
    （回補淺的股票更容易被誤判創新高）；60 個交易日是務實的預設值，呼叫端可調整。

    Parameters
    ----------
    trade_date : str   e.g. "2026-07-14"
    lookback_days : int   「創新高」比較窗口（交易日，含今日，預設 60）

    Returns
    -------
    list of dict，只回傳「多頭排列 且 創新高」都成立的股票，依 change_pct 降序：
        stock_id, stock_name, meta_sector, close, change_pct,
        ma5, ma10, ma60, lookback_days
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
        logger.warning("scan_bullish_alignment_new_high: DuckDB 無行情資料")
        return []

    universe_map = _load_universe_map(universe_path)
    price_df["date"] = pd.to_datetime(price_df["date"])
    target = pd.to_datetime(trade_date)

    min_history = max(60, lookback_days)
    results = []

    for sid, grp in price_df.groupby("stock_id"):
        grp = grp.sort_values("date").reset_index(drop=True)

        today_rows = grp[grp["date"] == target]
        if today_rows.empty:
            continue
        today_idx = today_rows.index[0]

        if today_idx + 1 < min_history:
            # 歷史資料不足以穩定算出 MA60 或跑滿 lookback_days 窗口，跳過避免雜訊訊號
            continue

        window = grp.iloc[: today_idx + 1]
        close = window["close"]

        ma5  = close.rolling(5).mean().iloc[-1]
        ma10 = close.rolling(10).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1]
        if pd.isna(ma60):
            continue

        today_close = float(close.iloc[-1])
        if not (today_close > ma5 > ma10 > ma60):
            continue

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

    results.sort(key=lambda x: -(x["change_pct"] or 0))
    logger.info("多頭排列+創新高掃描 %s：命中 %d 檔（lookback=%d）", trade_date, len(results), lookback_days)
    return results
```

- [ ] **Step 4: 執行測試確認通過**

Run: `pytest tests/test_signals.py -k bullish_alignment_new_high -v`
Expected: 3 個測試全 PASS

- [ ] **Step 5: 確認既有測試沒有被 `_load_universe_map` 簽名變動影響**

Run: `pytest tests/test_signals.py -v`
Expected: 全部測試（含既有 `scan_volume_turnover` 兩個測試）PASS

- [ ] **Step 6: 全專案回歸測試**

Run: `pytest -v`
Expected: 全部通過（已知例外：`tests/test_patterns.py::test_scan_patterns_returns_list` 若當下工作目錄缺 `data/screener.db` 會失敗，這是既有環境限制，跟本次改動無關，不算失敗）

- [ ] **Step 7: Commit**

```bash
git add screener/signals.py tests/test_signals.py
git commit -m "feat: 新增 scan_bullish_alignment_new_high 通用多頭排列+創新高掃描"
```

---

## 完成後的狀態

`screener/signals.py::scan_bullish_alignment_new_high()` 可獨立呼叫，回傳全市場符合「多頭排列 + 創新高」的股票候選名單，跟既有 `detect_breakout_confirm`（多頭拐點）並存，互補不衝突。**這次 plan 不包含**：頁面 UI 呈現、併入 `calc_composite_score()` 權重、還原股價資料源（見 design spec 已知限制）。下一步是 Cody/Developer 決定要不要把這個訊號接進既有的 `chips.html`/`patterns.html` 呈現，或等「逆轟策略」獨立頁面（見同批討論的頁面規劃）一起設計。
