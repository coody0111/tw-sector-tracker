# 大戶持倉 400張/1000張分層追蹤 + 修正歷史週變化損毀 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把現有 TDCC 大戶持倉（level 12-15 合計）拆出 400張(level 12)、1000張(level 15) 兩個獨立追蹤分層（各自現況張數/佔比 + 查詢時現算的週張數變化），並修正這次調查發現的歷史 `week_chg`/`streak` 損毀資料。

**Architecture:** 沿用 `scrapers/shareholder.py` 既有的 fetch → save_to_db 模式做欄位擴充（不新增模組）；400/1000張的週變化比照既有 `share_chg` 模式在 `screener/database.py::get_shareholder_top()` 查詢時用 self-join 現算，不落地存表；新增 `recompute_all_history()` 一次性修復合計欄位的歷史 `week_chg`/`streak`。

**Tech Stack:** Python, DuckDB, pandas（既有依賴，無新套件）

## Global Constraints

- 對照 spec：`docs/superpowers/specs/2026-07-10-shareholder-tier-breakdown-design.md`
- 400/1000張分層本次不做 streak（連增/連減週數）追蹤
- 不修 TDCC 抓取本身為何在 2380 那週解析出 100.0% 離群值（建議 Cody 事後人工核對，不在本次範圍）
- 不會實際執行 `--update-shareholder`/`--backfill-shareholder`——這需要 Cody 自己跑，本 plan 只確保 code 正確

---

### Task 1: `_fetch_one_stock()` 多留 level 12、15 個別數字

**Files:**
- Modify: `scrapers/shareholder.py:44-105`（`_fetch_one_stock()`）
- Test: `tests/test_shareholder.py`

**Interfaces:**
- Consumes：TDCC 回應（`_ROW_RE`/`_CELL_RE` 解析出的逐 level 資料列，格式不變）
- Produces：`_fetch_one_stock()` 回傳 dict 新增 4 個 key：`lv12_shares`, `lv12_pct`, `lv15_shares`, `lv15_pct`

- [ ] **Step 1: 寫失敗測試 — 確認個別 level 12/15 數字有被留下來**

在 `tests/test_shareholder.py` 檔案開頭的 import 加入 `_fetch_one_stock`：

```python
from scrapers.shareholder import (
    _add_week_change_streak,
    _fetch_one_stock,
    fetch_shareholder_weekly,
    recompute_latest_streak,
    save_to_db,
)
```

在檔案結尾加入：

```python
def test_fetch_one_stock_keeps_level_12_and_15_individually(monkeypatch):
    """_fetch_one_stock 除了 lv12_15 合計，還要各自留下 level 12（400張門檻）跟
    level 15（1000張以上）的股數/占比，不能只回傳加總後的數字。"""
    html = (
        "<table></table>"
        "<table>"
        "<tr><td>11</td><td>200,001-400,000</td><td>5</td><td>1,000,000</td><td>4.0</td></tr>"
        "<tr><td>12</td><td>400,001-600,000</td><td>3</td><td>1,500,000</td><td>6.0</td></tr>"
        "<tr><td>13</td><td>600,001-800,000</td><td>2</td><td>1,400,000</td><td>5.6</td></tr>"
        "<tr><td>14</td><td>800,001-1,000,000</td><td>1</td><td>900,000</td><td>3.6</td></tr>"
        "<tr><td>15</td><td>1,000,001以上</td><td>2</td><td>3,000,000</td><td>12.0</td></tr>"
        "<tr><td>16</td><td>合計</td><td>13</td><td>25,000,000</td><td>100.0</td></tr>"
        "</table>"
    )

    class FakeResp:
        text = html

        def raise_for_status(self):
            pass

    class FakeSession:
        def post(self, *args, **kwargs):
            return FakeResp()

    rec = _fetch_one_stock(FakeSession(), "tok", "uri", "2330", "20260703")

    assert rec is not None
    # 合計（既有欄位）：level 12+13+14+15 股數加總
    assert rec["lv12_15_shares"] == 1_500_000 + 1_400_000 + 900_000 + 3_000_000
    # 新欄位：level 12、15 各自的數字（不是加總）
    assert rec["lv12_shares"] == 1_500_000
    assert rec["lv15_shares"] == 3_000_000
    assert round(rec["lv12_pct"], 4) == round(1_500_000 / 25_000_000 * 100, 4)
    assert round(rec["lv15_pct"], 4) == round(3_000_000 / 25_000_000 * 100, 4)
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `.venv/bin/pytest tests/test_shareholder.py::test_fetch_one_stock_keeps_level_12_and_15_individually -v`
Expected: FAIL（`KeyError: 'lv12_shares'`，目前回傳 dict 沒有這個 key）

- [ ] **Step 3: 修改 `_fetch_one_stock()`**

找到現有實作（`scrapers/shareholder.py:76-105`）：

```python
    lv_shares = 0
    lv_cnt = 0
    total_shares = 0
    total_cnt = 0

    for row in rows:
        level, _range, cnt_str, shares_str, _pct = row
        try:
            cnt = int(cnt_str) if cnt_str else 0
            shares = int(shares_str) if shares_str else 0
        except ValueError:
            continue

        if "合" in _range:  # 合計行（有些股票有差異數調整使合計變第17行）
            total_shares = shares
            total_cnt = cnt
        elif level in _LARGE_HOLDER_LEVELS:
            lv_shares += shares
            lv_cnt += cnt

    if total_shares == 0:
        return None

    return {
        "lv12_15_shares": lv_shares,
        "lv12_15_cnt": lv_cnt,
        "total_shares": total_shares,
        "total_cnt": total_cnt,
        "lv12_15_pct": round(lv_shares / total_shares * 100, 4),
    }
```

改成：

```python
    lv_shares = 0
    lv_cnt = 0
    lv12_shares = 0
    lv15_shares = 0
    total_shares = 0
    total_cnt = 0

    for row in rows:
        level, _range, cnt_str, shares_str, _pct = row
        try:
            cnt = int(cnt_str) if cnt_str else 0
            shares = int(shares_str) if shares_str else 0
        except ValueError:
            continue

        if "合" in _range:  # 合計行（有些股票有差異數調整使合計變第17行）
            total_shares = shares
            total_cnt = cnt
        elif level in _LARGE_HOLDER_LEVELS:
            lv_shares += shares
            lv_cnt += cnt
            if level == "12":
                lv12_shares = shares
            elif level == "15":
                lv15_shares = shares

    if total_shares == 0:
        return None

    return {
        "lv12_15_shares": lv_shares,
        "lv12_15_cnt": lv_cnt,
        "total_shares": total_shares,
        "total_cnt": total_cnt,
        "lv12_15_pct": round(lv_shares / total_shares * 100, 4),
        "lv12_shares": lv12_shares,
        "lv15_shares": lv15_shares,
        "lv12_pct": round(lv12_shares / total_shares * 100, 4),
        "lv15_pct": round(lv15_shares / total_shares * 100, 4),
    }
```

- [ ] **Step 4: 執行測試確認通過**

Run: `.venv/bin/pytest tests/test_shareholder.py::test_fetch_one_stock_keeps_level_12_and_15_individually -v`
Expected: PASS

- [ ] **Step 5: 執行既有測試確認沒壞掉**

Run: `.venv/bin/pytest tests/test_shareholder.py -v`
Expected: 全部 PASS（`test_transient_post_failure_is_retried` 用的假 HTML 只有 level 1 跟合計，沒有 level 12/15，`lv12_shares`/`lv15_shares` 應該正確回傳 0，不影響既有斷言）

- [ ] **Step 6: Commit**

```bash
git add scrapers/shareholder.py tests/test_shareholder.py
git commit -m "feat: shareholder scraper 額外保留 level 12/15 個別張數與占比"
```

---

### Task 2: Schema 新增欄位 + `save_to_db()` 寫入

**Files:**
- Modify: `screener/database.py:69-81`（`init_db()` 的 `shareholder` 表）
- Modify: `scrapers/shareholder.py:178-199`（`save_to_db()`）
- Test: `tests/test_shareholder.py`

**Interfaces:**
- Consumes：Task 1 新增的 `lv12_shares`/`lv12_pct`/`lv15_shares`/`lv15_pct`
- Produces：`shareholder` 表新增這 4 欄；`save_to_db(rows)` 會把它們寫入 DB

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_shareholder.py` 結尾加入：

```python
def test_save_to_db_persists_lv12_and_lv15_tiers(tmp_path, monkeypatch):
    """save_to_db 應該把 lv12_shares/lv12_pct/lv15_shares/lv15_pct 這 4 個新欄位
    寫進 shareholder 表，不能像 lv12_15_shares 加欄位後只改 schema 卻沒改寫入邏輯。"""
    import scrapers.shareholder as shareholder_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(shareholder_mod, "_DB_PATH", db_path)

    con = duckdb.connect(db_path)
    con.execute("""
        CREATE TABLE shareholder (
            stock_id VARCHAR NOT NULL, date DATE NOT NULL,
            lv12_15_pct DOUBLE, lv12_15_cnt INTEGER, lv12_15_shares BIGINT,
            total_shares BIGINT, week_chg DOUBLE, streak INTEGER,
            lv12_shares BIGINT, lv12_pct DOUBLE, lv15_shares BIGINT, lv15_pct DOUBLE,
            PRIMARY KEY (stock_id, date)
        )
    """)
    con.close()

    rows = [{
        "stock_id": "2330", "date": "2026-07-03",
        "lv12_15_pct": 20.0, "lv12_15_cnt": 100,
        "lv12_15_shares": 5_000_000, "total_shares": 25_000_000,
        "lv12_shares": 1_500_000, "lv12_pct": 6.0,
        "lv15_shares": 3_000_000, "lv15_pct": 12.0,
    }]
    n = save_to_db(rows)
    assert n == 1

    con = duckdb.connect(db_path)
    row = con.execute(
        "SELECT lv12_shares, lv12_pct, lv15_shares, lv15_pct "
        "FROM shareholder WHERE stock_id='2330' AND date='2026-07-03'"
    ).fetchone()
    con.close()
    assert row == (1_500_000, 6.0, 3_000_000, 12.0)
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `.venv/bin/pytest tests/test_shareholder.py::test_save_to_db_persists_lv12_and_lv15_tiers -v`
Expected: FAIL（`save_to_db` 目前 `df[[...]]` 選欄清單沒有這 4 個 key，`KeyError`）

- [ ] **Step 3: 修改 `screener/database.py` 的 schema**

找到（`screener/database.py:68-81`）：

```python
    con.execute("""
        CREATE TABLE IF NOT EXISTS shareholder (
            stock_id        VARCHAR NOT NULL,
            date            DATE NOT NULL,
            lv12_15_pct     DOUBLE,
            lv12_15_cnt     INTEGER,
            lv12_15_shares  BIGINT,
            total_shares    BIGINT,
            week_chg        DOUBLE,
            streak          INTEGER,
            PRIMARY KEY (stock_id, date)
        )
    """)
    con.execute("ALTER TABLE shareholder ADD COLUMN IF NOT EXISTS lv12_15_shares BIGINT")
```

改成：

```python
    con.execute("""
        CREATE TABLE IF NOT EXISTS shareholder (
            stock_id        VARCHAR NOT NULL,
            date            DATE NOT NULL,
            lv12_15_pct     DOUBLE,
            lv12_15_cnt     INTEGER,
            lv12_15_shares  BIGINT,
            total_shares    BIGINT,
            week_chg        DOUBLE,
            streak          INTEGER,
            lv12_shares     BIGINT,
            lv12_pct        DOUBLE,
            lv15_shares     BIGINT,
            lv15_pct        DOUBLE,
            PRIMARY KEY (stock_id, date)
        )
    """)
    con.execute("ALTER TABLE shareholder ADD COLUMN IF NOT EXISTS lv12_15_shares BIGINT")
    con.execute("ALTER TABLE shareholder ADD COLUMN IF NOT EXISTS lv12_shares BIGINT")
    con.execute("ALTER TABLE shareholder ADD COLUMN IF NOT EXISTS lv12_pct DOUBLE")
    con.execute("ALTER TABLE shareholder ADD COLUMN IF NOT EXISTS lv15_shares BIGINT")
    con.execute("ALTER TABLE shareholder ADD COLUMN IF NOT EXISTS lv15_pct DOUBLE")
```

- [ ] **Step 4: 修改 `scrapers/shareholder.py::save_to_db()`**

找到（`scrapers/shareholder.py:178-199`）：

```python
def save_to_db(rows: list[dict]) -> int:
    """upsert 集保資料到 DuckDB shareholder 表，回傳寫入筆數。"""
    if not rows:
        return 0
    import pandas as pd
    df = pd.DataFrame(rows)[["stock_id", "date", "lv12_15_pct", "lv12_15_cnt", "lv12_15_shares", "total_shares"]]
    df["date"] = pd.to_datetime(df["date"]).dt.date

    con = duckdb.connect(_DB_PATH)
    # 計算 week_change 和 streak
    _add_week_change_streak(con, df)
    con.execute("DELETE FROM shareholder WHERE (stock_id, date) IN (SELECT stock_id, date FROM df)")
    # 明列欄位名（by-name 對應）：既有 DB 的 lv12_15_shares 是 ALTER 加在最後一欄，
    # 位置跟全新 CREATE TABLE 的中間位置不同，用位置式 INSERT 會錯位，故明列欄位
    con.execute(
        "INSERT INTO shareholder "
        "(stock_id, date, lv12_15_pct, lv12_15_cnt, lv12_15_shares, total_shares, week_chg, streak) "
        "SELECT stock_id, date, lv12_15_pct, lv12_15_cnt, lv12_15_shares, total_shares, week_chg, streak FROM df"
    )
    n = len(df)
    con.close()
    return n
```

改成：

```python
def save_to_db(rows: list[dict]) -> int:
    """upsert 集保資料到 DuckDB shareholder 表，回傳寫入筆數。"""
    if not rows:
        return 0
    import pandas as pd
    df = pd.DataFrame(rows)[[
        "stock_id", "date", "lv12_15_pct", "lv12_15_cnt", "lv12_15_shares", "total_shares",
        "lv12_shares", "lv12_pct", "lv15_shares", "lv15_pct",
    ]]
    df["date"] = pd.to_datetime(df["date"]).dt.date

    con = duckdb.connect(_DB_PATH)
    # 計算 week_change 和 streak（只針對合計欄位，見 spec 第 3 節）
    _add_week_change_streak(con, df)
    con.execute("DELETE FROM shareholder WHERE (stock_id, date) IN (SELECT stock_id, date FROM df)")
    # 明列欄位名（by-name 對應）：既有 DB 的 lv12_15_shares 是 ALTER 加在最後一欄，
    # 位置跟全新 CREATE TABLE 的中間位置不同，用位置式 INSERT 會錯位，故明列欄位
    con.execute(
        "INSERT INTO shareholder "
        "(stock_id, date, lv12_15_pct, lv12_15_cnt, lv12_15_shares, total_shares, week_chg, streak, "
        "lv12_shares, lv12_pct, lv15_shares, lv15_pct) "
        "SELECT stock_id, date, lv12_15_pct, lv12_15_cnt, lv12_15_shares, total_shares, week_chg, streak, "
        "lv12_shares, lv12_pct, lv15_shares, lv15_pct FROM df"
    )
    n = len(df)
    con.close()
    return n
```

- [ ] **Step 5: 執行測試確認通過**

Run: `.venv/bin/pytest tests/test_shareholder.py -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add screener/database.py scrapers/shareholder.py tests/test_shareholder.py
git commit -m "feat: shareholder 表新增 lv12/lv15 分層欄位並寫入"
```

---

### Task 3: `get_shareholder_top()` 回傳 lv12/lv15 現況與週張數變化

**Files:**
- Modify: `screener/database.py:286-305`（`get_shareholder_top()`）
- Test: `tests/test_database.py`

**Interfaces:**
- Consumes：Task 2 新增的 `shareholder.lv12_shares`/`lv12_pct`/`lv15_shares`/`lv15_pct`
- Produces：`get_shareholder_top()` 回傳欄位新增 `lv12_shares`, `lv12_pct`, `lv12_chg`, `lv15_shares`, `lv15_pct`, `lv15_chg`（`lv12_chg`/`lv15_chg` 是股數差，查詢時現算，比照既有 `share_chg` 模式，不落地存表）

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_database.py` 修改 `_seed_shareholder()`（第 81-94 行）：

```python
def _seed_shareholder(con):
    con.execute("""
        CREATE TABLE shareholder (
            stock_id VARCHAR NOT NULL, date DATE NOT NULL,
            lv12_15_pct DOUBLE, lv12_15_cnt INTEGER, lv12_15_shares BIGINT,
            total_shares BIGINT, week_chg DOUBLE, streak INTEGER,
            lv12_shares BIGINT, lv12_pct DOUBLE, lv15_shares BIGINT, lv15_pct DOUBLE,
            PRIMARY KEY (stock_id, date)
        )
    """)
    con.execute("""
        INSERT INTO shareholder VALUES
        ('2330', '2026-06-26', 20.0, 100, 5000000, 25000000, NULL, 0, 1500000, 6.0, 3000000, 12.0),
        ('2330', '2026-07-03', 21.0, 105, 5250000, 25000000, 1.0, 1, 1600000, 6.4, 2900000, 11.6)
    """)
```

（既有兩個直接建表插入單週資料的測試——`test_get_shareholder_top_prev_date_null_for_single_week`（第 119-140 行）不呼叫 `_seed_shareholder`，是自己 CREATE TABLE，也要同步加上這 4 欄，見 Step 1b）

在 `tests/test_database.py` 結尾加入：

```python
def test_get_shareholder_top_returns_lv12_and_lv15_tiers(tmp_path, monkeypatch):
    """get_shareholder_top() 要回傳 400張(lv12)/1000張(lv15) 各自的現況張數、
    占比，以及查詢時現算的週張數變化（lv12_chg/lv15_chg），不落地存表。"""
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    con = duckdb.connect(db_path)
    _seed_shareholder(con)
    con.close()

    df = get_shareholder_top()
    assert len(df) == 1
    row = df.iloc[0]
    assert row["lv12_shares"] == 1_600_000
    assert row["lv12_pct"] == 6.4
    assert row["lv12_chg"] == 100_000     # 1,600,000 - 1,500,000
    assert row["lv15_shares"] == 2_900_000
    assert row["lv15_pct"] == 11.6
    assert row["lv15_chg"] == -100_000    # 2,900,000 - 3,000,000
```

- [ ] **Step 1b: 修改只有單週資料的既有測試，同步補欄位**

`tests/test_database.py::test_get_shareholder_top_prev_date_null_for_single_week`（第 119-140 行）目前：

```python
def test_get_shareholder_top_prev_date_null_for_single_week(tmp_path, monkeypatch):
    """只有一週資料時，prev_date/share_chg 應該是 NULL，不能報錯。"""
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    con = duckdb.connect(db_path)
    con.execute("""
        CREATE TABLE shareholder (
            stock_id VARCHAR NOT NULL, date DATE NOT NULL,
            lv12_15_pct DOUBLE, lv12_15_cnt INTEGER, lv12_15_shares BIGINT,
            total_shares BIGINT, week_chg DOUBLE, streak INTEGER,
            PRIMARY KEY (stock_id, date)
        )
    """)
    con.execute("INSERT INTO shareholder VALUES ('9999', '2026-07-03', 15.0, 10, 100000, 1000000, NULL, 0)")
    con.close()

    df = get_shareholder_top()
    assert len(df) == 1
    assert pd.isna(df.iloc[0]["prev_date"])
    assert pd.isna(df.iloc[0]["share_chg"])
```

改成（建表加 4 欄、INSERT 補值、新增 lv12_chg/lv15_chg 斷言）：

```python
def test_get_shareholder_top_prev_date_null_for_single_week(tmp_path, monkeypatch):
    """只有一週資料時，prev_date/share_chg/lv12_chg/lv15_chg 應該是 NULL，不能報錯。"""
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    con = duckdb.connect(db_path)
    con.execute("""
        CREATE TABLE shareholder (
            stock_id VARCHAR NOT NULL, date DATE NOT NULL,
            lv12_15_pct DOUBLE, lv12_15_cnt INTEGER, lv12_15_shares BIGINT,
            total_shares BIGINT, week_chg DOUBLE, streak INTEGER,
            lv12_shares BIGINT, lv12_pct DOUBLE, lv15_shares BIGINT, lv15_pct DOUBLE,
            PRIMARY KEY (stock_id, date)
        )
    """)
    con.execute(
        "INSERT INTO shareholder VALUES "
        "('9999', '2026-07-03', 15.0, 10, 100000, 1000000, NULL, 0, 60000, 6.0, 20000, 2.0)"
    )
    con.close()

    df = get_shareholder_top()
    assert len(df) == 1
    assert pd.isna(df.iloc[0]["prev_date"])
    assert pd.isna(df.iloc[0]["share_chg"])
    assert pd.isna(df.iloc[0]["lv12_chg"])
    assert pd.isna(df.iloc[0]["lv15_chg"])
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `.venv/bin/pytest tests/test_database.py -v`
Expected: FAIL（`get_shareholder_top()` 目前不回傳 `lv12_shares`/`lv12_pct`/`lv12_chg`/`lv15_shares`/`lv15_pct`/`lv15_chg`，`KeyError`）

- [ ] **Step 3: 修改 `get_shareholder_top()`**

找到（`screener/database.py:286-305`）：

```python
def get_shareholder_top(n: int = 50) -> pd.DataFrame:
    """取最新週大戶持倉資料，含週變化、連增週數、張數變化與上週日期，按 streak desc 排序。"""
    con = get_conn()
    df = con.execute("""
        WITH ranked AS (
            SELECT stock_id, date, lv12_15_pct, lv12_15_cnt, lv12_15_shares, week_chg, streak,
                   ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) AS rn
            FROM shareholder
        )
        SELECT latest.stock_id, latest.date, prev.date AS prev_date,
               latest.lv12_15_pct, latest.lv12_15_cnt, latest.lv12_15_shares,
               latest.week_chg, latest.streak,
               (latest.lv12_15_shares - prev.lv12_15_shares) AS share_chg
        FROM (SELECT * FROM ranked WHERE rn = 1) latest
        LEFT JOIN (SELECT * FROM ranked WHERE rn = 2) prev ON latest.stock_id = prev.stock_id
        ORDER BY latest.streak DESC, latest.lv12_15_pct DESC
    """).df()
    con.close()
    return df
```

改成：

```python
def get_shareholder_top(n: int = 50) -> pd.DataFrame:
    """取最新週大戶持倉資料，含週變化、連增週數、張數變化與上週日期，
    以及 400張(lv12)/1000張(lv15) 分層的現況與週張數變化，按 streak desc 排序。"""
    con = get_conn()
    df = con.execute("""
        WITH ranked AS (
            SELECT stock_id, date, lv12_15_pct, lv12_15_cnt, lv12_15_shares, week_chg, streak,
                   lv12_shares, lv12_pct, lv15_shares, lv15_pct,
                   ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) AS rn
            FROM shareholder
        )
        SELECT latest.stock_id, latest.date, prev.date AS prev_date,
               latest.lv12_15_pct, latest.lv12_15_cnt, latest.lv12_15_shares,
               latest.week_chg, latest.streak,
               (latest.lv12_15_shares - prev.lv12_15_shares) AS share_chg,
               latest.lv12_shares, latest.lv12_pct,
               (latest.lv12_shares - prev.lv12_shares) AS lv12_chg,
               latest.lv15_shares, latest.lv15_pct,
               (latest.lv15_shares - prev.lv15_shares) AS lv15_chg
        FROM (SELECT * FROM ranked WHERE rn = 1) latest
        LEFT JOIN (SELECT * FROM ranked WHERE rn = 2) prev ON latest.stock_id = prev.stock_id
        ORDER BY latest.streak DESC, latest.lv12_15_pct DESC
    """).df()
    con.close()
    return df
```

- [ ] **Step 4: 執行測試確認通過**

Run: `.venv/bin/pytest tests/test_database.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add screener/database.py tests/test_database.py
git commit -m "feat: get_shareholder_top 回傳 lv12/lv15 分層現況與週張數變化"
```

---

### Task 4: 新增 `recompute_all_history()` 修復歷史損毀資料

**Files:**
- Modify: `scrapers/shareholder.py`（在 `recompute_latest_streak()` 之後加入新函式，約第 292 行後）
- Test: `tests/test_shareholder.py`

**Interfaces:**
- Consumes：`shareholder` 表既有的 `lv12_15_pct` 序列（不需要重打 TDCC）
- Produces：`recompute_all_history(db_path: str = _DB_PATH) -> int`，對整張表逐股票、依日期排序，重算每一筆（不只最新一筆）的 `week_chg`/`streak`，回傳實際更新的列數

- [ ] **Step 1: 寫失敗測試 — 重現真實損毀模式並驗證修復**

在 `tests/test_shareholder.py` 結尾加入：

```python
def test_recompute_all_history_fixes_corrupted_historical_week_chg(tmp_path):
    """
    重現真實 bug：調查 2380 時發現，資料庫裡好幾筆歷史 week_chg 都精確等於
    「自己的 pct 減掉某個離群值（100.0）」，而不是跟真正前一週比較——
    等於每一筆都拿同一個錯誤基準去比，不是逐週正確比較。

    recompute_all_history 應該無視現有（已損毀）的 week_chg，完全依照
    lv12_15_pct 的日期序列重新計算每一筆，恢復成跟「真正前一週」的正確差值。
    """
    db_path = tmp_path / "t.db"
    con = duckdb.connect(str(db_path))
    _make_table(con)
    # 模擬損毀狀態：pct 序列本身是正常的緩步變化，但 week_chg 全部被寫壞成
    # 「自己 - 100.0」（100.0 是某個之後才出現、不相干的離群值）
    rows = [
        ("2380", "2026-05-08", 44.40, -55.60, 0),
        ("2380", "2026-05-15", 44.61, -55.39, 0),
        ("2380", "2026-05-22", 44.72, -55.28, 0),
        ("2380", "2026-06-26", 100.00, 55.21, 1),   # 離群值本身（真正的異常來源）保留不動
    ]
    for sid, d, pct, bad_chg, bad_streak in rows:
        con.execute(
            "INSERT INTO shareholder VALUES (?, ?, ?, 0, 0, 0, ?, ?)",
            [sid, pd.to_datetime(d).date(), pct, bad_chg, bad_streak],
        )
    con.close()

    updated = recompute_all_history(str(db_path))
    assert updated == len(rows)

    con = duckdb.connect(str(db_path))
    df = con.execute(
        "SELECT date, week_chg, streak FROM shareholder WHERE stock_id='2380' ORDER BY date"
    ).df()
    con.close()

    # 第一筆無前值可比 → week_chg 應為 NULL（不是 -55.60）
    assert pd.isna(df.iloc[0]["week_chg"])
    # 之後每一筆應該是跟「真正前一週」的差值，不是「自己 - 100.0」
    assert round(df.iloc[1]["week_chg"], 2) == round(44.61 - 44.40, 2)
    assert round(df.iloc[2]["week_chg"], 2) == round(44.72 - 44.61, 2)
    assert round(df.iloc[3]["week_chg"], 2) == round(100.00 - 44.72, 2)  # 100.0 本身沒被改，只修「跟它比較」的方式
    # streak：三週連續上升 0→1→2，第四週(100.0，繼續上升)累加成 3
    assert df.iloc[0]["streak"] == 0
    assert df.iloc[1]["streak"] == 1
    assert df.iloc[2]["streak"] == 2
    assert df.iloc[3]["streak"] == 3


def test_recompute_all_history_handles_single_week_stock(tmp_path):
    """只有一週資料的股票，第一筆 week_chg 應為 NULL、streak=0，不報錯。"""
    db_path = tmp_path / "t.db"
    con = duckdb.connect(str(db_path))
    _make_table(con)
    con.execute(
        "INSERT INTO shareholder VALUES (?, ?, ?, 0, 0, 0, ?, ?)",
        ["9999", pd.to_datetime("2026-07-03").date(), 20.0, -999.0, 5],
    )
    con.close()

    updated = recompute_all_history(str(db_path))
    assert updated == 1

    con = duckdb.connect(str(db_path))
    row = con.execute(
        "SELECT week_chg, streak FROM shareholder WHERE stock_id='9999'"
    ).fetchone()
    con.close()
    assert pd.isna(row[0])
    assert row[1] == 0
```

同時在檔案開頭 import 加入 `recompute_all_history`：

```python
from scrapers.shareholder import (
    _add_week_change_streak,
    _fetch_one_stock,
    fetch_shareholder_weekly,
    recompute_all_history,
    recompute_latest_streak,
    save_to_db,
)
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `.venv/bin/pytest tests/test_shareholder.py::test_recompute_all_history_fixes_corrupted_historical_week_chg -v`
Expected: FAIL（`ImportError: cannot import name 'recompute_all_history'`）

- [ ] **Step 3: 實作 `recompute_all_history()`**

在 `scrapers/shareholder.py` 的 `recompute_latest_streak()` 函式之後（`get_available_dates()` 之前，約第 292 行）加入：

```python
def recompute_all_history(db_path: str = _DB_PATH) -> int:
    """
    重算整張 shareholder 表**每一筆**（不只最新一筆）的 week_chg/streak，
    完全依照 lv12_15_pct 的日期序列由舊到新重新計算，覆蓋掉現有值。

    背景：調查大戶持倉顯示異常時發現，部分歷史列的 week_chg 是用錯誤的基準
    算出來的（例如整批被某次錯誤的批次運算覆蓋成「跟某個不相干的離群值比較」），
    不是跟真正的前一週比較。recompute_latest_streak() 只處理「每支股票目前最新
    一筆」，不會碰到已經寫壞的歷史列，所以需要這支獨立的全表重算工具。

    不需要重打 TDCC，lv12_15_pct 已經在 DB 裡，只是重算 week_chg/streak 兩個
    衍生欄位。回傳實際更新的列數。
    """
    con = duckdb.connect(db_path)
    df = con.execute("""
        SELECT stock_id, date, lv12_15_pct
        FROM shareholder
        ORDER BY stock_id, date
    """).df()

    updates = []
    for sid, grp in df.groupby("stock_id"):
        grp = grp.sort_values("date").reset_index(drop=True)
        prev_streak = 0
        prev_pct = None
        for _, row in grp.iterrows():
            if prev_pct is None:
                chg = None
                streak = 0
            else:
                chg = round(float(row["lv12_15_pct"]) - float(prev_pct), 4)
                streak = _streak_step(chg, prev_streak)
            updates.append((chg, streak, sid, row["date"]))
            prev_pct = row["lv12_15_pct"]
            prev_streak = streak

    if updates:
        con.executemany(
            "UPDATE shareholder SET week_chg = ?, streak = ? WHERE stock_id = ? AND date = ?",
            updates,
        )
    con.close()
    return len(updates)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `.venv/bin/pytest tests/test_shareholder.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add scrapers/shareholder.py tests/test_shareholder.py
git commit -m "feat: 新增 recompute_all_history 修復歷史 week_chg/streak 損毀資料"
```

---

### Task 5: `main.py` 組裝 `sh_rows` 帶入 lv12/lv15 分層資料

**Files:**
- Modify: `main.py`（組 `sh_rows` 的迴圈，約第 665-687 行，見下方 Global Constraints 之後的既有程式碼）

**Interfaces:**
- Consumes：Task 3 的 `get_shareholder_top()` 新回傳欄位（`lv12_shares`, `lv12_pct`, `lv12_chg`, `lv15_shares`, `lv15_pct`, `lv15_chg`）
- Produces：`sh_rows` 每筆新增這 6 個 key，餵給 `chips_generator.generate_chips_html`

- [ ] **Step 1: 修改 `sh_rows.append(...)`**

找到 `main.py` 裡組 `sh_rows` 的迴圈（約第 665-687 行）：

```python
                    sh_rows.append({
                        "stock_id":    sid,
                        "stock_name":  info.get("stock_name", ""),
                        "meta_sector": info.get("meta_sector", ""),
                        "lv12_15_pct": float(row["lv12_15_pct"]) if row["lv12_15_pct"] is not None else None,
                        "lv12_15_shares": int(row["lv12_15_shares"]) if pd.notna(row["lv12_15_shares"]) else None,
                        "share_chg":   int(share_chg) if share_chg is not None else None,
                        "week_chg":    None if pd.isna(row["week_chg"]) else float(row["week_chg"]),
                        "streak":      int(row["streak"]) if row["streak"] is not None else 0,
                        "date":        str(row["date"]),
                        "close":       float(close) if close is not None else None,
                        "change_pct":  price_week_chg,
                        "chg_5d":      roll.get(5),
                        "chg_7d":      roll.get(7),
                        "chg_10d":     roll.get(10),
                        "chg_14d":     roll.get(14),
                        "company_shares":          int(insider["company_shares"]) if insider is not None and pd.notna(insider["company_shares"]) else None,
                        "company_chg":             int(insider["company_chg"]) if insider is not None and pd.notna(insider["company_chg"]) else None,
                        "company_pledge_pct":      float(insider["company_pledge_pct"]) if insider is not None and pd.notna(insider["company_pledge_pct"]) else None,
                        "major_holder_shares":     int(insider["major_holder_shares"]) if insider is not None and pd.notna(insider["major_holder_shares"]) else None,
                        "major_holder_chg":        int(insider["major_holder_chg"]) if insider is not None and pd.notna(insider["major_holder_chg"]) else None,
                        "major_holder_pledge_pct": float(insider["major_holder_pledge_pct"]) if insider is not None and pd.notna(insider["major_holder_pledge_pct"]) else None,
                    })
```

改成（在 `major_holder_pledge_pct` 那行之後，`})` 之前加入 6 個新 key）：

```python
                    sh_rows.append({
                        "stock_id":    sid,
                        "stock_name":  info.get("stock_name", ""),
                        "meta_sector": info.get("meta_sector", ""),
                        "lv12_15_pct": float(row["lv12_15_pct"]) if row["lv12_15_pct"] is not None else None,
                        "lv12_15_shares": int(row["lv12_15_shares"]) if pd.notna(row["lv12_15_shares"]) else None,
                        "share_chg":   int(share_chg) if share_chg is not None else None,
                        "week_chg":    None if pd.isna(row["week_chg"]) else float(row["week_chg"]),
                        "streak":      int(row["streak"]) if row["streak"] is not None else 0,
                        "date":        str(row["date"]),
                        "close":       float(close) if close is not None else None,
                        "change_pct":  price_week_chg,
                        "chg_5d":      roll.get(5),
                        "chg_7d":      roll.get(7),
                        "chg_10d":     roll.get(10),
                        "chg_14d":     roll.get(14),
                        "company_shares":          int(insider["company_shares"]) if insider is not None and pd.notna(insider["company_shares"]) else None,
                        "company_chg":             int(insider["company_chg"]) if insider is not None and pd.notna(insider["company_chg"]) else None,
                        "company_pledge_pct":      float(insider["company_pledge_pct"]) if insider is not None and pd.notna(insider["company_pledge_pct"]) else None,
                        "major_holder_shares":     int(insider["major_holder_shares"]) if insider is not None and pd.notna(insider["major_holder_shares"]) else None,
                        "major_holder_chg":        int(insider["major_holder_chg"]) if insider is not None and pd.notna(insider["major_holder_chg"]) else None,
                        "major_holder_pledge_pct": float(insider["major_holder_pledge_pct"]) if insider is not None and pd.notna(insider["major_holder_pledge_pct"]) else None,
                        "lv12_shares": int(row["lv12_shares"]) if pd.notna(row["lv12_shares"]) else None,
                        "lv12_pct":    float(row["lv12_pct"]) if pd.notna(row["lv12_pct"]) else None,
                        "lv12_chg":    int(row["lv12_chg"]) if pd.notna(row["lv12_chg"]) else None,
                        "lv15_shares": int(row["lv15_shares"]) if pd.notna(row["lv15_shares"]) else None,
                        "lv15_pct":    float(row["lv15_pct"]) if pd.notna(row["lv15_pct"]) else None,
                        "lv15_chg":    int(row["lv15_chg"]) if pd.notna(row["lv15_chg"]) else None,
                    })
```

- [ ] **Step 2: 語法檢查**

Run: `.venv/bin/python -c "import ast; ast.parse(open('main.py').read())"`
Expected: 無輸出（無語法錯誤）

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: main.py sh_rows 組裝加入 lv12/lv15 分層資料"
```

---

### Task 6: `export/chips_generator.py::_shareholder_table()` 顯示新欄位

**Files:**
- Modify: `export/chips_generator.py:360-427`（`_shareholder_table()`）
- Test: `tests/test_chips_generator.py`

**Interfaces:**
- Consumes：Task 5 產出的 `sh_rows` 新欄位（`lv12_shares`, `lv12_pct`, `lv12_chg`, `lv15_shares`, `lv15_pct`, `lv15_chg`）
- Produces：`_shareholder_table(rows)` 回傳的 HTML 多兩欄：「400張大戶」「1000張大戶」

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_chips_generator.py`（既有的 `_SAMPLE_ROW` dict，約第 883-890 行）加入新欄位，並新增測試函式：

```python
_SAMPLE_ROW = {
    "stock_id": "2330", "stock_name": "台積電", "meta_sector": "半導體",
    "close": 950.0, "change_pct": 1.5,
    "lv12_15_pct": 20.0, "lv12_15_shares": 5_250_000, "share_chg": 250_000,
    "week_chg": 1.0, "streak": 2,
    "company_shares": 1_500_000, "company_chg": 100_000, "company_pledge_pct": 13.33,
    "major_holder_shares": 3_000_000, "major_holder_chg": -50_000, "major_holder_pledge_pct": 0.0,
    "lv12_shares": 1_600_000, "lv12_pct": 6.4, "lv12_chg": 100_000,
    "lv15_shares": 2_900_000, "lv15_pct": 11.6, "lv15_chg": -100_000,
}


def test_shareholder_table_includes_lv12_and_lv15_columns():
    html = _shareholder_table([_SAMPLE_ROW])
    assert "400張大戶" in html
    assert "1000張大戶" in html
    assert "1,600" in html   # lv12_shares / 1000 = 1,600 張
    assert "2,900" in html   # lv15_shares / 1000 = 2,900 張
    assert "6.4" in html     # lv12_pct
    assert "11.6" in html    # lv15_pct


def test_shareholder_table_handles_missing_lv12_lv15_data():
    """沒有分層資料的股票（舊資料，尚未跑過新版 --update-shareholder）要顯示「─」，不能報錯。"""
    row = dict(_SAMPLE_ROW)
    row["lv12_shares"] = None
    row["lv12_pct"] = None
    row["lv12_chg"] = None
    row["lv15_shares"] = None
    row["lv15_pct"] = None
    row["lv15_chg"] = None
    html = _shareholder_table([row])
    assert "─" in html
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `.venv/bin/pytest tests/test_chips_generator.py -v`
Expected: FAIL（目前 `_shareholder_table` 沒有「400張大戶」「1000張大戶」字樣）

- [ ] **Step 3: 修改 `_shareholder_table()`**

找到（`export/chips_generator.py:360-427`）：

```python
def _shareholder_table(rows: list) -> str:
    """大戶持倉排行表。rows: list of dicts with stock_id, stock_name, meta_sector,
    lv12_15_pct, lv12_15_shares, share_chg, week_chg, streak,
    company_shares, company_chg, company_pledge_pct,
    major_holder_shares, major_holder_chg, major_holder_pledge_pct"""
    if not rows:
        return "<div class='no-data'>無大戶持倉資料（尚未執行 --update-shareholder）</div>"
    html = (
        "<table class='ct'><thead><tr>"
        "<th>#</th><th>股票</th><th>族群</th><th>收盤(週漲跌)</th>"
        "<th>近5日</th><th>近7日</th><th>近10日</th><th>近14日</th>"
        "<th>大戶持倉%</th><th>週變化</th><th>大戶張數變化</th><th>連增週</th>"
        "<th>公司派持股</th><th>大股東持股</th>"
        "</tr></thead><tbody>"
    )
    for i, s in enumerate(rows, 1):
        pct = s.get("lv12_15_pct", 0) or 0
        chg = s.get("week_chg")
        streak = int(s.get("streak") or 0)

        chg_html = "<span style='color:#475569'>─</span>"
        if chg is not None:
            sign = "+" if chg > 0 else ""
            chg_color = "#f87171" if chg > 0 else ("#4ade80" if chg < 0 else "#64748b")
            chg_html = f"<span style='color:{chg_color};font-weight:700'>{sign}{chg:.2f}%</span>"

        share_chg = s.get("share_chg")
        share_chg_html = "<span style='color:#475569'>─</span>"
        if share_chg is not None:
            lots = share_chg / 1000  # 股數 → 張數
            sign = "+" if lots > 0 else ""
            color = "#f87171" if lots > 0 else ("#4ade80" if lots < 0 else "#64748b")
            share_chg_html = f"<span style='color:{color};font-weight:700'>{sign}{lots:,.0f}張</span>"

        if streak > 0:
            streak_html = (f"<span style='color:#f87171;background:rgba(127,29,29,.2);border:1px solid rgba(127,29,29,.4);"
                           f"border-radius:4px;padding:1px 7px;font-size:.7rem;font-weight:700'>↑{streak}週</span>")
        elif streak < 0:
            streak_html = (f"<span style='color:#4ade80;background:rgba(6,78,59,.2);border:1px solid rgba(6,78,59,.4);"
                           f"border-radius:4px;padding:1px 7px;font-size:.7rem;font-weight:700'>↓{abs(streak)}週</span>")
        else:
            streak_html = "<span style='color:#475569'>─</span>"

        pct_color = "#f87171" if pct >= 70 else ("#fbbf24" if pct >= 50 else "#94a3b8")

        company_html = _insider_cell(s.get("company_shares"), s.get("company_chg"), s.get("company_pledge_pct"))
        major_html = _insider_cell(s.get("major_holder_shares"), s.get("major_holder_chg"), s.get("major_holder_pledge_pct"))

        html += (
            f"<tr>"
            f"<td class='ct-rank'>{i}</td>"
            f"<td><span class='sid'>{_esc(s['stock_id'])}</span> {_esc(s.get('stock_name',''))}</td>"
            f"<td class='ct-meta'>{_meta_link(s.get('meta_sector',''))}</td>"
            f"{_price_cell(s.get('close'), s.get('change_pct'))}"
            f"{_chg_cell(s.get('chg_5d'))}"
            f"{_chg_cell(s.get('chg_7d'))}"
            f"{_chg_cell(s.get('chg_10d'))}"
            f"{_chg_cell(s.get('chg_14d'))}"
            f"<td style='color:{pct_color};font-weight:700'>{pct:.1f}%</td>"
            f"<td>{chg_html}</td>"
            f"<td>{share_chg_html}</td>"
            f"<td>{streak_html}</td>"
            f"{company_html}"
            f"{major_html}"
            f"</tr>"
        )
    html += "</tbody></table>"
    return html
```

改成：

```python
def _shareholder_table(rows: list) -> str:
    """大戶持倉排行表。rows: list of dicts with stock_id, stock_name, meta_sector,
    lv12_15_pct, lv12_15_shares, share_chg, week_chg, streak,
    company_shares, company_chg, company_pledge_pct,
    major_holder_shares, major_holder_chg, major_holder_pledge_pct,
    lv12_shares, lv12_pct, lv12_chg, lv15_shares, lv15_pct, lv15_chg"""
    if not rows:
        return "<div class='no-data'>無大戶持倉資料（尚未執行 --update-shareholder）</div>"
    html = (
        "<table class='ct'><thead><tr>"
        "<th>#</th><th>股票</th><th>族群</th><th>收盤(週漲跌)</th>"
        "<th>近5日</th><th>近7日</th><th>近10日</th><th>近14日</th>"
        "<th>大戶持倉%</th><th>週變化</th><th>大戶張數變化</th><th>連增週</th>"
        "<th>400張大戶</th><th>1000張大戶</th>"
        "<th>公司派持股</th><th>大股東持股</th>"
        "</tr></thead><tbody>"
    )
    for i, s in enumerate(rows, 1):
        pct = s.get("lv12_15_pct", 0) or 0
        chg = s.get("week_chg")
        streak = int(s.get("streak") or 0)

        chg_html = "<span style='color:#475569'>─</span>"
        if chg is not None:
            sign = "+" if chg > 0 else ""
            chg_color = "#f87171" if chg > 0 else ("#4ade80" if chg < 0 else "#64748b")
            chg_html = f"<span style='color:{chg_color};font-weight:700'>{sign}{chg:.2f}%</span>"

        share_chg = s.get("share_chg")
        share_chg_html = "<span style='color:#475569'>─</span>"
        if share_chg is not None:
            lots = share_chg / 1000  # 股數 → 張數
            sign = "+" if lots > 0 else ""
            color = "#f87171" if lots > 0 else ("#4ade80" if lots < 0 else "#64748b")
            share_chg_html = f"<span style='color:{color};font-weight:700'>{sign}{lots:,.0f}張</span>"

        if streak > 0:
            streak_html = (f"<span style='color:#f87171;background:rgba(127,29,29,.2);border:1px solid rgba(127,29,29,.4);"
                           f"border-radius:4px;padding:1px 7px;font-size:.7rem;font-weight:700'>↑{streak}週</span>")
        elif streak < 0:
            streak_html = (f"<span style='color:#4ade80;background:rgba(6,78,59,.2);border:1px solid rgba(6,78,59,.4);"
                           f"border-radius:4px;padding:1px 7px;font-size:.7rem;font-weight:700'>↓{abs(streak)}週</span>")
        else:
            streak_html = "<span style='color:#475569'>─</span>"

        pct_color = "#f87171" if pct >= 70 else ("#fbbf24" if pct >= 50 else "#94a3b8")

        company_html = _insider_cell(s.get("company_shares"), s.get("company_chg"), s.get("company_pledge_pct"))
        major_html = _insider_cell(s.get("major_holder_shares"), s.get("major_holder_chg"), s.get("major_holder_pledge_pct"))
        lv12_html = _insider_cell(s.get("lv12_shares"), s.get("lv12_chg"), s.get("lv12_pct"))
        lv15_html = _insider_cell(s.get("lv15_shares"), s.get("lv15_chg"), s.get("lv15_pct"))

        html += (
            f"<tr>"
            f"<td class='ct-rank'>{i}</td>"
            f"<td><span class='sid'>{_esc(s['stock_id'])}</span> {_esc(s.get('stock_name',''))}</td>"
            f"<td class='ct-meta'>{_meta_link(s.get('meta_sector',''))}</td>"
            f"{_price_cell(s.get('close'), s.get('change_pct'))}"
            f"{_chg_cell(s.get('chg_5d'))}"
            f"{_chg_cell(s.get('chg_7d'))}"
            f"{_chg_cell(s.get('chg_10d'))}"
            f"{_chg_cell(s.get('chg_14d'))}"
            f"<td style='color:{pct_color};font-weight:700'>{pct:.1f}%</td>"
            f"<td>{chg_html}</td>"
            f"<td>{share_chg_html}</td>"
            f"<td>{streak_html}</td>"
            f"{lv12_html}"
            f"{lv15_html}"
            f"{company_html}"
            f"{major_html}"
            f"</tr>"
        )
    html += "</tbody></table>"
    return html
```

（重用既有 `_insider_cell(shares, chg, pledge_pct)`——第三個參數本來是「質押%」，這裡傳入 `lv12_pct`/`lv15_pct`（持股佔比）沿用同一個 render 格式（張數／變化張數／第三行百分比），文字語意上是「持股占比」不是「質押」，但因為只是純數字加 `%`，沿用既有函式不需要新增參數；`_insider_cell` 目前的 docstring 沒有假設第三個參數一定是質押，只是格式化成 `質押{pct}%`——需要同步修一下 docstring 措辭或加一個可選 label，見下方 Step 3b）

- [ ] **Step 3b: `_insider_cell()` 加可選 label 參數，避免「質押」字樣誤植到持股占比欄**

找到 `export/chips_generator.py:430-443`：

```python
def _insider_cell(shares, chg, pledge_pct) -> str:
    """內部人持股欄位：張數（第一行）＋ 月變化張數／質押% （第二行）。缺值顯示「─」。"""
    if shares is None:
        return "<td style='color:#334155'>─</td>"
    lots = shares / 1000
    lines = [f"<span style='color:#e2e8f0;font-weight:600'>{lots:,.0f}張</span>"]
    if chg is not None:
        chg_lots = chg / 1000
        sign = "+" if chg_lots > 0 else ""
        color = "#f87171" if chg_lots > 0 else ("#4ade80" if chg_lots < 0 else "#64748b")
        lines.append(f"<span style='color:{color};font-size:.68rem'>{sign}{chg_lots:,.0f}張</span>")
    if pledge_pct is not None:
        lines.append(f"<span style='color:#64748b;font-size:.64rem'>質押{pledge_pct:.1f}%</span>")
    return f"<td>{'<br>'.join(lines)}</td>"
```

改成：

```python
def _insider_cell(shares, chg, pct, pct_label: str = "質押") -> str:
    """內部人/大戶分層持股欄位：張數（第一行）＋ 週/月變化張數（第二行）＋ 第三行百分比
    （預設當「質押%」用，大戶分層欄位改傳 pct_label='持股' 顯示「持股%」）。缺值顯示「─」。"""
    if shares is None:
        return "<td style='color:#334155'>─</td>"
    lots = shares / 1000
    lines = [f"<span style='color:#e2e8f0;font-weight:600'>{lots:,.0f}張</span>"]
    if chg is not None:
        chg_lots = chg / 1000
        sign = "+" if chg_lots > 0 else ""
        color = "#f87171" if chg_lots > 0 else ("#4ade80" if chg_lots < 0 else "#64748b")
        lines.append(f"<span style='color:{color};font-size:.68rem'>{sign}{chg_lots:,.0f}張</span>")
    if pct is not None:
        lines.append(f"<span style='color:#64748b;font-size:.64rem'>{pct_label}{pct:.1f}%</span>")
    return f"<td>{'<br>'.join(lines)}</td>"
```

並把 `_shareholder_table()` 裡新增的兩行呼叫改成明確傳 `pct_label="持股"`：

```python
        lv12_html = _insider_cell(s.get("lv12_shares"), s.get("lv12_chg"), s.get("lv12_pct"), pct_label="持股")
        lv15_html = _insider_cell(s.get("lv15_shares"), s.get("lv15_chg"), s.get("lv15_pct"), pct_label="持股")
```

（既有兩處呼叫 `_insider_cell(s.get("company_shares"), ...)`／`_insider_cell(s.get("major_holder_shares"), ...)` 不用改，`pct_label` 有預設值 `"質押"`，行為不變）

- [ ] **Step 4: 執行測試確認通過**

Run: `.venv/bin/pytest tests/test_chips_generator.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全專案回歸測試**

Run: `.venv/bin/pytest -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add export/chips_generator.py tests/test_chips_generator.py
git commit -m "feat: Section 8 大戶持倉表格新增 400張/1000張分層欄位"
```

---

## Out of scope（本次不做，跟 spec 一致）

- 400/1000 張 tier 的 streak（連增/連減週數）追蹤
- TDCC 該週離群值（2380 100.0%）成因調查——建議 Cody 之後人工核對
- 實際執行 `--update-shareholder`/`--backfill-shareholder`（Cody 自己跑，才能讓 `lv12_15_shares`/`lv12_shares`/`lv15_shares` 有真實非 NULL 資料）
