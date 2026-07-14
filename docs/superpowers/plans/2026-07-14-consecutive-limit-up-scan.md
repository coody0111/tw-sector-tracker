# 連續漲停鎖死偵測 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `screener/signals.py::scan_consecutive_limit_up()`，逐股計算連續鎖漲停天數（動能派筆記最強型態：三十六、四十五），輸出連板數與量縮鎖死輔助判斷，供後續排序/標記「最強型態」使用。

**Architecture:** 沿用 `scan_volume_turnover()` 的既有慣例（DuckDB read-only 查詢、逐股 groupby、`_load_universe_map()` 補股名/族群、回傳依關鍵欄位降冪排列的 list of dict）。跟 `scan_volume_turnover()` 是獨立函式——後者抓「漲停打開反轉」訊號，這個函式抓「還在連續鎖死」訊號，語意相反，刻意不合併。

**Tech Stack:** Python, pandas, DuckDB（既有依賴，無新套件）

## Global Constraints

- 漲停判定門檻：`change_pct >= 9.5`（來自 spec `_LIMIT_UP_PCT`，沿用 `scan_volume_turnover` 既有慣例，維持專案內一致）
- 本次範圍**不含**頁面 UI 串接——資料層 spec 明確排除，UI 留到 Cody 提出的「逆轟策略」獨立頁面 spec/plan（會整合這個函式 + `scan_momentum_health` + 後續 B3）
- 本次範圍**不含**興櫃股過濾（結構上 `daily_prices` 資料源不含興櫃股，見 spec「資料正確性風險」第 2 點）與處置股偵測（無資料源，已知限制，見 spec 第 3 點）
- 對照 spec：`docs/superpowers/specs/2026-07-14-consecutive-limit-up-scan-design.md`

---

### Task 1: 連續鎖漲停天數核心偵測

**Files:**
- Modify: `screener/signals.py`（新增常數 `_LIMIT_UP_PCT`、新增 `scan_consecutive_limit_up()`）
- Test: `tests/test_signals.py`

**Interfaces:**
- Consumes：DuckDB `daily_prices` 表（`stock_id, date, close, change_pct, volume`）；`data/stock_universe.csv`（透過既有 `_load_universe_map()`）
- Produces：`scan_consecutive_limit_up(trade_date: str, db_path: str = _DB_PATH) -> List[Dict[str, Any]]`，每筆 dict 含 `stock_id, stock_name, meta_sector, close, change_pct, volume, limit_up_streak, volume_declining_streak(None)`。Task 2 會就地補上 `volume_declining_streak`。

- [ ] **Step 1: 寫失敗測試 — 連板天數計算 + 未漲停股票不出現 + 排序**

在 `tests/test_signals.py` 檔案開頭 import 區塊加入：

```python
from screener.signals import scan_volume_turnover, scan_consecutive_limit_up
```

在檔案最後面新增：

```python
def test_scan_consecutive_limit_up_counts_streak(tmp_path):
    """連續 3 天漲停（含今天）應算出 limit_up_streak == 3。"""
    db_path = tmp_path / "test.db"
    rows = [
        ("2330", "2026-07-10", 100.0, 1.0, 5000),
        ("2330", "2026-07-11", 101.0, 1.0, 5000),
        ("2330", "2026-07-12", 111.1, 9.8, 4000),
        ("2330", "2026-07-13", 122.2, 10.0, 3000),
        ("2330", "2026-07-14", 134.4, 9.9, 2000),
    ]
    _seed_db(db_path, rows)

    results = scan_consecutive_limit_up("2026-07-14", db_path=str(db_path))

    assert len(results) == 1
    assert results[0]["stock_id"] == "2330"
    assert results[0]["limit_up_streak"] == 3


def test_scan_consecutive_limit_up_excludes_stock_without_todays_limit(tmp_path):
    """今天沒漲停的股票不該出現在結果裡（不是 limit_up_streak==0 混在結果裡）。"""
    db_path = tmp_path / "test.db"
    rows = [
        ("2330", "2026-07-13", 100.0, 9.8, 3000),
        ("2330", "2026-07-14", 110.0, 10.0, 2000),   # 今天漲停 → 應出現
        ("2317", "2026-07-13", 50.0, 1.0, 3000),
        ("2317", "2026-07-14", 50.5, 1.0, 3000),      # 今天沒漲停 → 不該出現
    ]
    _seed_db(db_path, rows)

    results = scan_consecutive_limit_up("2026-07-14", db_path=str(db_path))

    ids = [r["stock_id"] for r in results]
    assert "2330" in ids
    assert "2317" not in ids


def test_scan_consecutive_limit_up_sorts_by_streak_descending(tmp_path):
    """連板數高的排前面。"""
    db_path = tmp_path / "test.db"
    rows = [
        ("AAAA", "2026-07-12", 100.0, 9.8, 3000),
        ("AAAA", "2026-07-13", 110.0, 10.0, 2000),
        ("AAAA", "2026-07-14", 121.0, 10.0, 1000),   # streak=3
        ("BBBB", "2026-07-14", 50.0, 10.0, 3000),     # streak=1
    ]
    _seed_db(db_path, rows)

    results = scan_consecutive_limit_up("2026-07-14", db_path=str(db_path))

    assert [r["stock_id"] for r in results] == ["AAAA", "BBBB"]
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_signals.py -k consecutive_limit_up -v`
Expected: FAIL，錯誤訊息類似 `ImportError: cannot import name 'scan_consecutive_limit_up'`

- [ ] **Step 3: 實作 `scan_consecutive_limit_up()`**

在 `screener/signals.py` 的 `_MIN_WINDOW_DAYS = 20` 那行下方新增常數：

```python
_LIMIT_UP_PCT = 9.5   # 漲停判定門檻，沿用 scan_volume_turnover 既有慣例（見設計文件資料正確性風險）
```

在檔案最後面（`scan_volume_turnover()` 之後）新增：

```python
def scan_consecutive_limit_up(
    trade_date: str,
    db_path: str = _DB_PATH,
) -> List[Dict[str, Any]]:
    """
    連續漲停鎖死偵測：逐股計算連續鎖漲停天數，供「最強型態」排序/標記使用。

    跟 scan_volume_turnover() 是獨立函式：那個抓「漲停打開反轉」，這個抓「還在
    連續鎖死」，語意相反，資料來源相同但用途不同，刻意不合併。

    Parameters
    ----------
    trade_date : str   e.g. "2026-07-14"

    Returns
    -------
    list of dict，依 limit_up_streak 降冪排列，每筆含：
        stock_id, stock_name, meta_sector, close, change_pct, volume,
        limit_up_streak (連續鎖漲停天數，今天算第1天),
        volume_declining_streak (bool|None，連板期間量是否逐日遞減/持平；
                                  streak<2 時為 None，Task 2 補上)
    """
    con = duckdb.connect(db_path, read_only=True)
    price_df = con.execute(f"""
        SELECT stock_id, date, close, change_pct, volume
        FROM daily_prices
        WHERE date <= '{trade_date}'
        ORDER BY stock_id, date
    """).df()
    con.close()

    if price_df.empty:
        logger.warning("scan_consecutive_limit_up: DuckDB 無行情資料")
        return []

    universe_map = _load_universe_map()
    price_df["date"] = pd.to_datetime(price_df["date"])
    target = pd.to_datetime(trade_date)

    results = []

    for sid, grp in price_df.groupby("stock_id"):
        grp = grp.sort_values("date").reset_index(drop=True)

        today_rows = grp[grp["date"] == target]
        if today_rows.empty:
            continue
        today_idx = today_rows.index[0]
        today = grp.iloc[today_idx]

        if today["change_pct"] < _LIMIT_UP_PCT:
            continue

        # 從今天往前數連續漲停天數
        streak = 0
        i = today_idx
        while i >= 0 and grp.iloc[i]["change_pct"] >= _LIMIT_UP_PCT:
            streak += 1
            i -= 1

        uinfo = universe_map.get(str(sid), {})
        results.append({
            "stock_id":                sid,
            "stock_name":              uinfo.get("stock_name", ""),
            "meta_sector":             uinfo.get("meta_sector", ""),
            "close":                   float(today["close"]),
            "change_pct":              float(today["change_pct"]),
            "volume":                  int(today["volume"]),
            "limit_up_streak":         streak,
            "volume_declining_streak": None,
        })

    results.sort(key=lambda x: -x["limit_up_streak"])

    logger.info("連續漲停鎖死掃描 %s：命中 %d 檔", trade_date, len(results))
    return results
```

- [ ] **Step 4: 執行測試確認通過**

Run: `pytest tests/test_signals.py -k consecutive_limit_up -v`
Expected: 3 個測試全 PASS

- [ ] **Step 5: 確認既有測試沒有被影響**

Run: `pytest tests/test_signals.py -v`
Expected: 全部測試（含既有 `scan_volume_turnover` 測試）PASS

- [ ] **Step 6: Commit**

```bash
git add screener/signals.py tests/test_signals.py
git commit -m "feat: 新增 scan_consecutive_limit_up 連續漲停鎖死偵測"
```

---

### Task 2: 量縮鎖死輔助判斷（volume_declining_streak）

**Files:**
- Modify: `screener/signals.py`
- Test: `tests/test_signals.py`

**Interfaces:**
- Consumes：Task 1 的逐股迴圈內已算出的 `streak`、`today_idx`、`grp`（連板期間的成交量序列）
- Produces：`scan_consecutive_limit_up()` 回傳值裡的 `volume_declining_streak` 欄位（`bool` 或 `None`）改為有值——`streak >= 2` 時才判斷，`< 2` 時無法判斷趨勢，維持 `None`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_signals.py` 新增：

```python
def test_scan_consecutive_limit_up_flags_volume_declining_streak(tmp_path):
    """連板期間成交量逐日遞減（惜售、鎖更死）→ volume_declining_streak True；
    中間有一天量增 → False。"""
    db_path = tmp_path / "test.db"
    rows = [
        # AAAA: 量逐日遞減（3000 → 2000 → 1000）
        ("AAAA", "2026-07-12", 100.0, 9.8, 3000),
        ("AAAA", "2026-07-13", 110.0, 10.0, 2000),
        ("AAAA", "2026-07-14", 121.0, 10.0, 1000),
        # BBBB: 第三天量反增（1000 → 1000 → 5000）
        ("BBBB", "2026-07-12", 50.0, 9.8, 1000),
        ("BBBB", "2026-07-13", 55.0, 10.0, 1000),
        ("BBBB", "2026-07-14", 60.5, 10.0, 5000),
    ]
    _seed_db(db_path, rows)

    results = scan_consecutive_limit_up("2026-07-14", db_path=str(db_path))

    a = next(r for r in results if r["stock_id"] == "AAAA")
    b = next(r for r in results if r["stock_id"] == "BBBB")
    assert a["volume_declining_streak"] is True
    assert b["volume_declining_streak"] is False


def test_scan_consecutive_limit_up_single_day_streak_has_none_volume_trend(tmp_path):
    """只有 1 天漲停，無法判斷「逐日遞減」趨勢，應為 None（不是 False）。"""
    db_path = tmp_path / "test.db"
    rows = [
        ("CCCC", "2026-07-13", 50.0, 1.0, 3000),
        ("CCCC", "2026-07-14", 55.0, 10.0, 2000),
    ]
    _seed_db(db_path, rows)

    results = scan_consecutive_limit_up("2026-07-14", db_path=str(db_path))

    assert results[0]["limit_up_streak"] == 1
    assert results[0]["volume_declining_streak"] is None
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_signals.py -k volume_declining -v`
Expected: FAIL（`volume_declining_streak` 仍是 `None`，`assert True is True` 那個會過，但 BBBB 那個 `is False` 的斷言會抓到 `None is False` 失敗）

- [ ] **Step 3: 實作量縮判斷**

在 `screener/signals.py` 的 `scan_consecutive_limit_up()` 裡，把這一段：

```python
        # 從今天往前數連續漲停天數
        streak = 0
        i = today_idx
        while i >= 0 and grp.iloc[i]["change_pct"] >= _LIMIT_UP_PCT:
            streak += 1
            i -= 1

        uinfo = universe_map.get(str(sid), {})
        results.append({
            "stock_id":                sid,
            "stock_name":              uinfo.get("stock_name", ""),
            "meta_sector":             uinfo.get("meta_sector", ""),
            "close":                   float(today["close"]),
            "change_pct":              float(today["change_pct"]),
            "volume":                  int(today["volume"]),
            "limit_up_streak":         streak,
            "volume_declining_streak": None,
        })
```

改成：

```python
        # 從今天往前數連續漲停天數
        streak = 0
        i = today_idx
        while i >= 0 and grp.iloc[i]["change_pct"] >= _LIMIT_UP_PCT:
            streak += 1
            i -= 1

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

- [ ] **Step 4: 執行測試確認通過**

Run: `pytest tests/test_signals.py -k "consecutive_limit_up or volume_declining" -v`
Expected: 全部 PASS（含 Task 1 的 3 個 + 這次新增的 2 個）

- [ ] **Step 5: 全專案回歸測試**

Run: `pytest -v`
Expected: 全部通過（已知例外：`tests/test_patterns.py::test_scan_patterns_returns_list` 若當下工作目錄缺 `data/screener.db` 會失敗，這是既有環境問題，跟本次改動無關，不算失敗）

- [ ] **Step 6: Commit**

```bash
git add screener/signals.py tests/test_signals.py
git commit -m "feat: scan_consecutive_limit_up 加上量縮鎖死輔助判斷（volume_declining_streak）"
```

---

## 完成後的狀態

`screener/signals.py::scan_consecutive_limit_up()` 可獨立呼叫，回傳全市場連續鎖漲停個股清單（含連板數、量縮輔助判斷），供下一階段（獨立 spec/plan）串接「逆轟策略」頁面使用。**這次 plan 不包含頁面串接**。

**已知限制，未在本次 plan 處理，留待 Cody 確認優先度：**
- 處置股（分盤集合競價）目前無偵測機制，連板名單若出現異常個案建議人工核對 TWSE 處置股公告（見 design 文件風險 3）。
- 興櫃股過濾目前靠資料源結構性排除（`stock_universe.csv` 不含興櫃），若未來追蹤範圍擴大需重新檢視。
