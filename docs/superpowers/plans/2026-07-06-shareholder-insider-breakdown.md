# 大戶張數化 + 內部人持股（公司派/大股東）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 TDCC 大戶持倉補上實際張數變化，新增內部人持股（公司派/大股東）月頻資料源，並把 Section 8「大戶持倉」表格的股價欄位對齊集保週期、加上週股價變化。

**Architecture:** 沿用 `scrapers/shareholder.py` 既有的「fetch → save_to_db（含衍生欄位計算）」模式新增一個獨立模組 `scrapers/insider_holdings.py`（月頻，公開資訊觀測站 `ajax_stapap1`）。兩個資料源（`shareholder` 週頻、`insider_holdings` 月頻）各自獨立更新，只在 `main.py` 組資料要餵給 `chips_generator.py` 時才 join 在一起。

**Tech Stack:** Python, DuckDB, requests（既有依賴，無新套件）

## Global Constraints

- 對照 spec：`docs/superpowers/specs/2026-07-05-shareholder-insider-breakdown-design.md`
- 內部人持股資料源已實際打過真實請求驗證（見下方 Task 3），**不需要**像 TDCC 那樣先取一次性 SYNCHRONIZER_TOKEN，直接 POST 到 `https://mopsov.twse.com.tw/mops/web/ajax_stapap1` 即可，每支股票只需 1 個 request（比 TDCC 簡單）
- 「公司派」= 董事＋監察人＋經理人＋其職稱下的「配偶、未成年子女及利用他人名義持有」欄；「大股東」= 職稱含「大股東」或未分類職稱（例如「其他」）的持股人
- 新增的所有欄位（張數變化、公司派/大股東持股與月變化、質押比例）一律沿用現有紅漲綠跌配色慣例（`_pct_color`/既有 `chg_color` 寫法），不做特殊警示色
- 本次不做 streak（連增/連減月數）追蹤，只做「最新值＋月變化」
- 排序/篩選邏輯維持不變：仍用 TDCC `streak` 分 Top 30 連增／Top 20 連減，新欄位純資訊呈現

---

### Task 1: `shareholder` 表新增 `lv12_15_shares` 欄位（大戶實際張數）

**Files:**
- Modify: `screener/database.py`（`init_db()` 裡 `shareholder` 表的 CREATE TABLE，約第 68-77 行）
- Modify: `scrapers/shareholder.py`（`save_to_db()`，約第 178-193 行）
- Test: `tests/test_shareholder.py`

**Interfaces:**
- Consumes：`_fetch_one_stock()` 已回傳的 `lv12_15_shares`（現有欄位，目前被 `save_to_db()` 丟棄）
- Produces：`shareholder` 表新增 `lv12_15_shares BIGINT` 欄位，`save_to_db(rows)` 會把它寫入 DB

- [ ] **Step 1: 寫失敗測試 — `save_to_db` 應該把 `lv12_15_shares` 寫進 DB**

在 `tests/test_shareholder.py` 檔案開頭加入 import：

```python
from scrapers.shareholder import save_to_db
```

在檔案結尾加入：

```python
def test_save_to_db_persists_lv12_15_shares(tmp_path, monkeypatch):
    """save_to_db 應該把 lv12_15_shares（大戶實際張數）寫進 shareholder 表，
    不能像現在這樣只存 lv12_15_pct/lv12_15_cnt/total_shares 三個欄位、丟掉張數。"""
    import scrapers.shareholder as shareholder_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(shareholder_mod, "_DB_PATH", db_path)

    import duckdb
    con = duckdb.connect(db_path)
    con.execute("""
        CREATE TABLE shareholder (
            stock_id VARCHAR NOT NULL, date DATE NOT NULL,
            lv12_15_pct DOUBLE, lv12_15_cnt INTEGER, lv12_15_shares BIGINT,
            total_shares BIGINT, week_chg DOUBLE, streak INTEGER,
            PRIMARY KEY (stock_id, date)
        )
    """)
    con.close()

    rows = [{
        "stock_id": "2330", "date": "2026-07-03",
        "lv12_15_pct": 20.0, "lv12_15_cnt": 100,
        "lv12_15_shares": 5_000_000, "total_shares": 25_000_000,
    }]
    n = save_to_db(rows)
    assert n == 1

    con = duckdb.connect(db_path)
    row = con.execute(
        "SELECT lv12_15_shares FROM shareholder WHERE stock_id='2330' AND date='2026-07-03'"
    ).fetchone()
    con.close()
    assert row[0] == 5_000_000
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `.venv/bin/pytest tests/test_shareholder.py::test_save_to_db_persists_lv12_15_shares -v`
Expected: FAIL（`lv12_15_shares` 欄位不存在於 INSERT 的欄位清單，或 DataFrame 選欄時 KeyError）

- [ ] **Step 3: 修改 `screener/database.py` 的 schema**

在 `init_db()` 裡找到 `shareholder` 表的 CREATE TABLE：

```python
    con.execute("""
        CREATE TABLE IF NOT EXISTS shareholder (
            stock_id        VARCHAR NOT NULL,
            date            DATE NOT NULL,
            lv12_15_pct     DOUBLE,
            lv12_15_cnt     INTEGER,
            total_shares    BIGINT,
            week_chg        DOUBLE,
            streak          INTEGER,
            PRIMARY KEY (stock_id, date)
        )
    """)
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
            PRIMARY KEY (stock_id, date)
        )
    """)
    con.execute("ALTER TABLE shareholder ADD COLUMN IF NOT EXISTS lv12_15_shares BIGINT")
```

`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 是為了既有已經建過的 `data/screener.db`（CREATE TABLE IF NOT EXISTS 對已存在的表不會生效，需要額外補一欄）。

- [ ] **Step 4: 修改 `scrapers/shareholder.py::save_to_db()`**

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
    con.execute("INSERT INTO shareholder SELECT stock_id, date, lv12_15_pct, lv12_15_cnt, lv12_15_shares, total_shares, week_chg, streak FROM df")
    n = len(df)
    con.close()
    return n
```

（只改了 `df = pd.DataFrame(rows)[[...]]` 加入 `"lv12_15_shares"`，跟 INSERT 的欄位順序跟著 SELECT 欄位順序調整，對齊新 schema 的欄位順序）

- [ ] **Step 5: 執行測試確認通過**

Run: `.venv/bin/pytest tests/test_shareholder.py -v`
Expected: 全部 PASS（含新測試與既有測試都要過，既有測試不依賴 `lv12_15_shares` 但共用同一個 `_make_table` schema，注意 Step 6 會一併更新既有測試的建表 schema）

- [ ] **Step 6: 同步更新既有測試的建表 schema，避免欄位對不上**

`tests/test_shareholder.py` 裡 `_make_table()` 函式（現有的 helper，被其他測試共用）也要加上 `lv12_15_shares` 欄位，維持 schema 一致：

```python
def _make_table(con):
    con.execute("""
        CREATE TABLE shareholder (
            stock_id VARCHAR NOT NULL, date DATE NOT NULL,
            lv12_15_pct DOUBLE, lv12_15_cnt INTEGER, lv12_15_shares BIGINT,
            total_shares BIGINT, week_chg DOUBLE, streak INTEGER,
            PRIMARY KEY (stock_id, date)
        )
    """)
```

`_insert()` helper 目前是 `"INSERT INTO shareholder VALUES (?, ?, ?, 0, 0, 0.0, ?)"`（7 個值對應 7 欄，現在變 8 欄），改成：

```python
def _insert(con, sid, d, pct, streak):
    con.execute(
        "INSERT INTO shareholder VALUES (?, ?, ?, 0, 0, 0, 0.0, ?)",
        [sid, pd.to_datetime(d).date(), pct, streak],
    )
```

（多補一個 `0` 給 `lv12_15_shares`，這些既有測試不關心張數，補 0 即可）

Run: `.venv/bin/pytest tests/test_shareholder.py -v`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add screener/database.py scrapers/shareholder.py tests/test_shareholder.py
git commit -m "feat: shareholder 表新增 lv12_15_shares，補上大戶實際張數"
```

---

### Task 2: `get_shareholder_top()` 回傳本週/上週日期＋張數變化

**Files:**
- Modify: `screener/database.py`（`get_shareholder_top()`，約第 258-272 行）
- Test: `tests/test_database.py`（新檔）

**Interfaces:**
- Consumes：Task 1 新增的 `shareholder.lv12_15_shares` 欄位
- Produces：`get_shareholder_top(n: int = 50) -> pd.DataFrame`，回傳欄位變成 `stock_id, date, prev_date, lv12_15_pct, lv12_15_cnt, lv12_15_shares, week_chg, streak, share_chg`（新增 `prev_date`、`lv12_15_shares`、`share_chg`，`share_chg` 是股數差，不是張數，呼叫端要自己 `/1000`）

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_database.py`：

```python
# tests/test_database.py
import duckdb
import pandas as pd

from screener.database import get_shareholder_top


def _seed_shareholder(con):
    con.execute("""
        CREATE TABLE shareholder (
            stock_id VARCHAR NOT NULL, date DATE NOT NULL,
            lv12_15_pct DOUBLE, lv12_15_cnt INTEGER, lv12_15_shares BIGINT,
            total_shares BIGINT, week_chg DOUBLE, streak INTEGER,
            PRIMARY KEY (stock_id, date)
        )
    """)
    con.execute("""
        INSERT INTO shareholder VALUES
        ('2330', '2026-06-26', 20.0, 100, 5000000, 25000000, NULL, 0),
        ('2330', '2026-07-03', 21.0, 105, 5250000, 25000000, 1.0, 1)
    """)


def test_get_shareholder_top_returns_prev_date_and_share_chg(tmp_path, monkeypatch):
    """get_shareholder_top() 要回傳上週日期跟張數變化（股數差），
    才能算出『大戶張數變化』跟『對齊集保週期的週股價變化』。"""
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    con = duckdb.connect(db_path)
    _seed_shareholder(con)
    con.close()

    df = get_shareholder_top()
    assert len(df) == 1
    row = df.iloc[0]
    assert str(row["date"]) == "2026-07-03"
    assert str(row["prev_date"]) == "2026-06-26"
    assert row["lv12_15_shares"] == 5250000
    assert row["share_chg"] == 250000   # 5,250,000 - 5,000,000


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

- [ ] **Step 2: 執行測試確認失敗**

Run: `.venv/bin/pytest tests/test_database.py -v`
Expected: FAIL（`get_shareholder_top()` 目前不回傳 `prev_date`/`lv12_15_shares`/`share_chg` 欄位，`KeyError`）

- [ ] **Step 3: 修改 `get_shareholder_top()`**

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

（`n` 參數目前沒被既有實作使用，維持原樣不動，不在本次範圍內處理）

- [ ] **Step 4: 執行測試確認通過**

Run: `.venv/bin/pytest tests/test_database.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add screener/database.py tests/test_database.py
git commit -m "feat: get_shareholder_top 回傳上週日期與大戶張數變化"
```

---

### Task 3: 新增 `scrapers/insider_holdings.py`（內部人持股，月頻）

**Files:**
- Create: `scrapers/insider_holdings.py`
- Modify: `screener/database.py`（`init_db()` 新增 `insider_holdings` 表）
- Test: `tests/test_insider_holdings.py`（新檔）

**Interfaces:**
- Consumes：無（獨立新資料源）
- Produces：
  - `fetch_insider_holdings_monthly(stock_ids: list[str]) -> list[dict]`，每筆 `{stock_id, report_date, company_shares, company_pledge_shares, major_holder_shares, major_holder_pledge_shares}`
  - `save_to_db(rows: list[dict]) -> int`，upsert 進 `insider_holdings` 表並算出 `company_chg`/`major_holder_chg`/`company_pledge_pct`/`major_holder_pledge_pct`

**已驗證的真實資料源格式**（用 curl 實際打過 `https://mopsov.twse.com.tw/mops/web/ajax_stapap1`，POST body：`step=1&firstin=true&off=1&keyword4=&code1=&TYPEK2=&checkbtn=&queryName=co_id&inpuType=co_id&TYPEK=all&isnew=true&co_id=<stock_id>&year=&month=`，**不需要 session token**）：

- 回應 HTML 裡有 `資料年月:11505` 這樣的字串（民國年月，5 碼：3 碼年+2碼月）
- 資料列格式（大小寫混用 `<TR>`/`<TD>`，跟 TDCC 的 `<tr>`/`<td>` 不同，要用 case-insensitive）：
  ```html
  <TR class='odd'><TD style='...'>董事本人</td><TD align='left'>王小明</td><TD style='...'>0</td><TD style='...'>1,000,000</td><TD style='...'>0</td><TD>0.00%</td><TD style='...'>0</td><TD style='...'>0</td><TD>0.00%</td></TR>
  ```
  9 欄依序：職稱、姓名、選任時持股、目前持股、設質股數、設質股數佔持股比例、關係人持股、關係人設質股數、關係人設質比例
- 職稱實際出現過的值（依公司而異）：`董事本人`、`董事之法人代表人`、`獨立董事本人`、`監察人本人`、`總經理本人`、`副總經理本人`、`協理本人`、`財務部門主管本人`、`會計部門主管本人`、`大股東本人`、`其他`
- 查無資料時回應包含 `查無此公司資料` 或 `資料庫中查無資料`
- 頁尾另外有一段「非獨立董監持股合計／設質合計／設質比例」等預先算好的彙總（`<TR>`，不含 `class='odd'/'even'`），**這次不使用**（不含經理人/大股東，不夠完整），改成自己逐列解析加總

- [ ] **Step 1: 寫失敗測試 — 逐列解析分類與加總**

建立 `tests/test_insider_holdings.py`：

```python
# tests/test_insider_holdings.py
from scrapers.insider_holdings import _parse_response, fetch_insider_holdings_monthly

_SAMPLE_HTML = """
<table class='noBorder'><tr><td class='reportCont' style='text-align:right !important;'>資料年月:11505</td></tr></table>
<table class='hasBorder'>
<TR class='odd'><TD style='text-align:left !important;'>董事本人</td><TD align='left'>王小明</td><TD style='text-align:right !important;'>0</td><TD style='text-align:right !important;'>1,000,000</td><TD style='text-align:right !important;'>0</td><TD>0.00%</td><TD style='text-align:right !important;'>0</td><TD style='text-align:right !important;'>0</td><TD>0.00%</td></TR>
<TR class='even'><TD style='text-align:left !important;'>獨立董事本人</td><TD align='left'>陳小華</td><TD style='text-align:right !important;'>0</td><TD style='text-align:right !important;'>0</td><TD style='text-align:right !important;'>0</td><TD>0.00%</td><TD style='text-align:right !important;'>0</td><TD style='text-align:right !important;'>0</td><TD>0.00%</td></TR>
<TR class='odd'><TD style='text-align:left !important;'>總經理本人</td><TD align='left'>林大方</td><TD style='text-align:right !important;'>0</td><TD style='text-align:right !important;'>500,000</td><TD style='text-align:right !important;'>200,000</td><TD>40.00%</td><TD style='text-align:right !important;'>0</td><TD style='text-align:right !important;'>0</td><TD>0.00%</td></TR>
<TR class='even'><TD style='text-align:left !important;'>大股東本人</td><TD align='left'>某投資公司</td><TD style='text-align:right !important;'>0</td><TD style='text-align:right !important;'>3,000,000</td><TD style='text-align:right !important;'>0</td><TD>0.00%</td><TD style='text-align:right !important;'>0</td><TD style='text-align:right !important;'>0</td><TD>0.00%</td></TR>
</table>
"""

_NO_DATA_HTML = "<center> <font color='red'><B>查無此公司資料</B></font></center>"


def test_parse_response_classifies_company_vs_major_holder():
    """董事/獨董/總經理歸『公司派』加總；大股東歸『大股東』加總，
    數字要對得起來（含關係人欄一起加，這個範例都是 0 不影響）。"""
    result = _parse_response(_SAMPLE_HTML)
    assert result is not None
    assert result["report_date"] == "2026-05-01"
    assert result["company_shares"] == 1_000_000 + 0 + 500_000   # 董事+獨董+總經理
    assert result["company_pledge_shares"] == 200_000            # 只有總經理有設質
    assert result["major_holder_shares"] == 3_000_000
    assert result["major_holder_pledge_shares"] == 0


def test_parse_response_returns_none_when_no_data():
    """查無資料時回傳 None，不能拋例外或誤判成 0。"""
    assert _parse_response(_NO_DATA_HTML) is None
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `.venv/bin/pytest tests/test_insider_holdings.py -v`
Expected: FAIL（`scrapers.insider_holdings` 模組不存在，`ModuleNotFoundError`）

- [ ] **Step 3: 實作 `scrapers/insider_holdings.py`**

```python
"""
內部人持股（公司派／大股東）scraper — 公開資訊觀測站每月更新。
抓董事/監察人/經理人（公司派）與大股東(10%+) 的持股與設質(質押)比例。
"""
import logging
import random
import re
import time
from typing import Optional

import duckdb
import requests

logger = logging.getLogger(__name__)

_URL = "https://mopsov.twse.com.tw/mops/web/ajax_stapap1"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
}
_DB_PATH = "data/screener.db"

_MAX_RETRIES = 3
_RETRY_BACKOFF = (3.0, 7.0)
_JITTER = 0.8

_ROW_RE = re.compile(r"<TR class=['\"](?:odd|even)['\"]>(.*?)</TR>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"<TD[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_DATE_RE = re.compile(r"資料年月[:：](\d{5})")

# 大股東/未分類職稱一律歸「大股東」桶；董事/監察人/經理人相關頭銜歸「公司派」桶
_COMPANY_KEYWORDS = ("董事", "監察人", "經理", "協理", "主管")


def _to_int(text: str) -> int:
    text = text.strip().replace(",", "")
    return int(text) if text else 0


def _classify_role(title: str) -> str:
    if "大股東" in title:
        return "major_holder"
    if any(kw in title for kw in _COMPANY_KEYWORDS):
        return "company"
    return "major_holder"  # 「其他」等未分類頭銜，預設歸大股東桶


def _parse_response(html: str) -> Optional[dict]:
    if "查無" in html:
        return None

    date_m = _DATE_RE.search(html)
    if not date_m:
        return None
    roc = date_m.group(1)
    year_ad = int(roc[:3]) + 1911
    month = int(roc[3:])
    report_date = f"{year_ad:04d}-{month:02d}-01"

    company_shares = 0
    company_pledge = 0
    major_shares = 0
    major_pledge = 0

    for row_html in _ROW_RE.findall(html):
        cells = _CELL_RE.findall(row_html)
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        if len(cells) != 9:
            continue
        title = cells[0]
        current_shares = _to_int(cells[3])
        pledge_shares = _to_int(cells[4])
        related_shares = _to_int(cells[6])
        related_pledge = _to_int(cells[7])

        bucket = _classify_role(title)
        shares = current_shares + related_shares
        pledge = pledge_shares + related_pledge
        if bucket == "company":
            company_shares += shares
            company_pledge += pledge
        else:
            major_shares += shares
            major_pledge += pledge

    return {
        "report_date": report_date,
        "company_shares": company_shares,
        "company_pledge_shares": company_pledge,
        "major_holder_shares": major_shares,
        "major_holder_pledge_shares": major_pledge,
    }


def _fetch_one_stock(stock_id: str) -> Optional[dict]:
    data = {
        "step": "1", "firstin": "true", "off": "1",
        "keyword4": "", "code1": "", "TYPEK2": "", "checkbtn": "",
        "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all",
        "isnew": "true", "co_id": stock_id, "year": "", "month": "",
    }
    # 注意：不要在這裡 catch POST 的例外——讓例外往上冒給呼叫端的重試迴圈接住重打
    # （比照 shareholder.py 修過的教訓，內層吞例外會讓外層重試機制形同虛設）
    r = requests.post(_URL, data=data, headers=_HEADERS, timeout=30, verify=False)
    r.raise_for_status()
    return _parse_response(r.text)


def fetch_insider_holdings_monthly(stock_ids: list[str], delay: float = 1.0) -> list[dict]:
    """抓一批股票最新一期的內部人持股資料，回傳 list of dict。"""
    import warnings
    warnings.filterwarnings("ignore")

    logger.info("內部人持股更新，共 %d 支股票", len(stock_ids))
    results = []
    failed = 0

    for i, sid in enumerate(stock_ids, 1):
        rec = None
        ok = False
        for attempt in range(_MAX_RETRIES):
            try:
                rec = _fetch_one_stock(sid)
                ok = True
                break
            except Exception as e:
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(random.uniform(*_RETRY_BACKOFF))
                else:
                    logger.warning("  [%d] 抓取失敗（重試 %d 次）: %s，跳過 %s",
                                   i, _MAX_RETRIES, e, sid)
        if not ok:
            failed += 1
            time.sleep(delay + random.uniform(0, _JITTER))
            continue

        if rec:
            rec["stock_id"] = sid
            results.append(rec)
        else:
            failed += 1

        if i % 50 == 0 or i == len(stock_ids):
            logger.info("  [%d/%d] 成功 %d，失敗 %d", i, len(stock_ids), len(results), failed)

        time.sleep(delay + random.uniform(0, _JITTER))

    return results


def save_to_db(rows: list[dict], db_path: str = _DB_PATH) -> int:
    """upsert 內部人持股到 DuckDB insider_holdings 表，算出月變化，回傳寫入筆數。"""
    if not rows:
        return 0
    import pandas as pd

    con = duckdb.connect(db_path)
    sids = [r["stock_id"] for r in rows]
    write_date = max(r["report_date"] for r in rows)
    prev_rows = con.execute("""
        SELECT stock_id, company_shares, major_holder_shares
        FROM insider_holdings
        WHERE stock_id IN (SELECT UNNEST(?)) AND report_date < ?
        QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY report_date DESC) = 1
    """, [sids, write_date]).df()
    prev_map = {r["stock_id"]: r for _, r in prev_rows.iterrows()} if not prev_rows.empty else {}

    out_rows = []
    for r in rows:
        company_shares = r["company_shares"]
        major_shares = r["major_holder_shares"]
        company_pledge_pct = (
            round(r["company_pledge_shares"] / company_shares * 100, 4) if company_shares > 0 else None
        )
        major_holder_pledge_pct = (
            round(r["major_holder_pledge_shares"] / major_shares * 100, 4) if major_shares > 0 else None
        )
        prev = prev_map.get(r["stock_id"])
        company_chg = int(company_shares - prev["company_shares"]) if prev is not None else None
        major_holder_chg = int(major_shares - prev["major_holder_shares"]) if prev is not None else None

        out_rows.append({
            "stock_id": r["stock_id"],
            "report_date": r["report_date"],
            "company_shares": company_shares,
            "company_chg": company_chg,
            "company_pledge_pct": company_pledge_pct,
            "major_holder_shares": major_shares,
            "major_holder_chg": major_holder_chg,
            "major_holder_pledge_pct": major_holder_pledge_pct,
        })

    df = pd.DataFrame(out_rows)
    df["report_date"] = pd.to_datetime(df["report_date"]).dt.date
    con.execute("DELETE FROM insider_holdings WHERE (stock_id, report_date) IN (SELECT stock_id, report_date FROM df)")
    con.execute("""
        INSERT INTO insider_holdings
        SELECT stock_id, report_date, company_shares, company_chg, company_pledge_pct,
               major_holder_shares, major_holder_chg, major_holder_pledge_pct
        FROM df
    """)
    n = len(df)
    con.close()
    return n
```

- [ ] **Step 4: 執行測試確認通過**

Run: `.venv/bin/pytest tests/test_insider_holdings.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 新增 `insider_holdings` 表 schema**

在 `screener/database.py::init_db()` 裡，`shareholder` 表 CREATE TABLE 之後加入：

```python
    con.execute("""
        CREATE TABLE IF NOT EXISTS insider_holdings (
            stock_id                VARCHAR NOT NULL,
            report_date             DATE NOT NULL,
            company_shares          BIGINT,
            company_chg             BIGINT,
            company_pledge_pct      DOUBLE,
            major_holder_shares     BIGINT,
            major_holder_chg        BIGINT,
            major_holder_pledge_pct DOUBLE,
            PRIMARY KEY (stock_id, report_date)
        )
    """)
```

- [ ] **Step 6: 寫 `save_to_db` 的 DB 整合測試（月變化計算）**

在 `tests/test_insider_holdings.py` 加入：

```python
def test_save_to_db_computes_month_over_month_change(tmp_path):
    from scrapers.insider_holdings import save_to_db
    import duckdb

    db_path = str(tmp_path / "t.db")
    con = duckdb.connect(db_path)
    con.execute("""
        CREATE TABLE insider_holdings (
            stock_id VARCHAR NOT NULL, report_date DATE NOT NULL,
            company_shares BIGINT, company_chg BIGINT, company_pledge_pct DOUBLE,
            major_holder_shares BIGINT, major_holder_chg BIGINT, major_holder_pledge_pct DOUBLE,
            PRIMARY KEY (stock_id, report_date)
        )
    """)
    con.close()

    # 第一個月：無前值可比
    rows1 = [{
        "stock_id": "2330", "report_date": "2026-04-01",
        "company_shares": 1_000_000, "company_pledge_shares": 0,
        "major_holder_shares": 3_000_000, "major_holder_pledge_shares": 0,
    }]
    save_to_db(rows1, db_path=db_path)

    # 第二個月：公司派持股增加、大股東減少
    rows2 = [{
        "stock_id": "2330", "report_date": "2026-05-01",
        "company_shares": 1_100_000, "company_pledge_shares": 0,
        "major_holder_shares": 2_500_000, "major_holder_pledge_shares": 0,
    }]
    n = save_to_db(rows2, db_path=db_path)
    assert n == 1

    con = duckdb.connect(db_path)
    row = con.execute(
        "SELECT company_chg, major_holder_chg FROM insider_holdings WHERE stock_id='2330' AND report_date='2026-05-01'"
    ).fetchone()
    first_row = con.execute(
        "SELECT company_chg, major_holder_chg FROM insider_holdings WHERE stock_id='2330' AND report_date='2026-04-01'"
    ).fetchone()
    con.close()

    assert row[0] == 100_000     # 1,100,000 - 1,000,000
    assert row[1] == -500_000    # 2,500,000 - 3,000,000
    assert first_row[0] is None  # 第一個月無前值，chg 應為 NULL
```

Run: `.venv/bin/pytest tests/test_insider_holdings.py -v`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add scrapers/insider_holdings.py tests/test_insider_holdings.py screener/database.py
git commit -m "feat: 新增內部人持股（公司派/大股東）scraper 與 insider_holdings 表"
```

---

### Task 4: `main.py` CLI 串接（`--update-insider-holdings`）＋ 資料組裝（價格對齊＋內部人 join）

**Files:**
- Modify: `main.py`

**Interfaces:**
- Consumes：Task 2 的 `get_shareholder_top()`（新增 `prev_date`/`lv12_15_shares`/`share_chg`）、Task 3 的 `scrapers.insider_holdings.fetch_insider_holdings_monthly`/`save_to_db`
- Produces：CLI flag `--update-insider-holdings`；`sh_rows`（餵給 `generate_chips_html`）每筆新增 `lv12_15_shares`、`share_chg`、`price_week_chg`、`company_shares`、`company_chg`、`company_pledge_pct`、`major_holder_shares`、`major_holder_chg`、`major_holder_pledge_pct`

- [ ] **Step 1: 新增 `_update_insider_holdings()` 函式**

在 `main.py` 的 `_update_shareholder()` 函式之後加入：

```python
def _update_insider_holdings() -> None:
    """抓公開資訊觀測站內部人持股（公司派/大股東），計算月變化並存入 DB。"""
    from scrapers.insider_holdings import fetch_insider_holdings_monthly, save_to_db as ih_save
    init_db()
    stock_ids = pd.read_csv(UNIVERSE_PATH, dtype=str)["stock_id"].tolist()
    logger.info("=== 內部人持股更新（%d 支股票）===", len(stock_ids))
    rows = fetch_insider_holdings_monthly(stock_ids)
    n = ih_save(rows)
    logger.info("=== 內部人持股更新完成，寫入 %d 筆 ===", n)
```

- [ ] **Step 2: 新增 CLI flag**

在 `main.py` 的 argparse 區塊，`--backfill-shareholder` 那行之後加入：

```python
    parser.add_argument("--update-insider-holdings", action="store_true",
                        help="抓公開資訊觀測站內部人持股（公司派/大股東），計算月變化")
```

在 dispatch 區塊（`elif args.backfill_shareholder:` 之後）加入：

```python
    elif args.update_insider_holdings:
        _update_insider_holdings()
```

- [ ] **Step 3: 改寫 `sh_rows` 組裝邏輯（價格對齊＋內部人 join）**

找到現有這段（大約在 `_update_shareholder`/`_backfill_shareholder` 定義之後、`run()` 內部組 `sh_rows` 的地方）：

```python
        try:
            from screener.database import get_shareholder_top
            import duckdb as _ddb
            sh_df = get_shareholder_top()
            if not sh_df.empty:
                universe = pd.read_csv(UNIVERSE_PATH, dtype=str, usecols=["stock_id", "stock_name", "meta_sector"])
                name_map = universe.set_index("stock_id")[["stock_name", "meta_sector"]].to_dict("index")
                # 取最近一個交易日的股價
                try:
                    _con = _ddb.connect("data/screener.db", read_only=True)
                    _pdate = _con.execute("SELECT MAX(date) FROM daily_prices").fetchone()[0]
                    _pdf = _con.execute(
                        "SELECT stock_id, close, change_pct FROM daily_prices WHERE date = ?", [_pdate]
                    ).fetchdf() if _pdate else pd.DataFrame()
                    _con.close()
                    sh_price_map = _pdf.set_index("stock_id")[["close", "change_pct"]].to_dict("index") if not _pdf.empty else {}
                except Exception:
                    sh_price_map = {}
                sh_rows = []
                for _, row in sh_df.iterrows():
                    sid = str(row["stock_id"])
                    info = name_map.get(sid, {})
                    px = sh_price_map.get(sid, {})
                    sh_rows.append({
                        "stock_id":    sid,
                        "stock_name":  info.get("stock_name", ""),
                        "meta_sector": info.get("meta_sector", ""),
                        "lv12_15_pct": float(row["lv12_15_pct"]) if row["lv12_15_pct"] is not None else None,
                        "week_chg":    float(row["week_chg"]) if row["week_chg"] is not None else None,
                        "streak":      int(row["streak"]) if row["streak"] is not None else 0,
                        "date":        str(row["date"]),
                        "close":       float(px["close"]) if px.get("close") is not None else None,
                        "change_pct":  float(px["change_pct"]) if px.get("change_pct") is not None else None,
                    })
            else:
                sh_rows = []
        except Exception as exc:
            logger.warning("大戶持倉資料載入失敗: %s", exc)
            sh_rows = []
```

整段改成：

```python
        try:
            from screener.database import get_shareholder_top
            import duckdb as _ddb
            sh_df = get_shareholder_top()
            if not sh_df.empty:
                universe = pd.read_csv(UNIVERSE_PATH, dtype=str, usecols=["stock_id", "stock_name", "meta_sector"])
                name_map = universe.set_index("stock_id")[["stock_name", "meta_sector"]].to_dict("index")

                # 價格對齊集保週期：本週/上週各自查對應日期的收盤價（不是「最新交易日」）
                _dates = pd.unique(pd.concat([sh_df["date"], sh_df["prev_date"].dropna()]))
                try:
                    _con = _ddb.connect("data/screener.db", read_only=True)
                    _pdf = _con.execute(
                        "SELECT stock_id, date, close FROM daily_prices WHERE date IN (SELECT UNNEST(?))",
                        [list(_dates)],
                    ).fetchdf() if len(_dates) else pd.DataFrame()
                    _con.close()
                    _price_map = {(str(r["stock_id"]), str(r["date"])): r["close"] for _, r in _pdf.iterrows()}
                except Exception:
                    _price_map = {}

                # 內部人持股（公司派/大股東）：取每支股票最新一筆月資料
                try:
                    _con = _ddb.connect("data/screener.db", read_only=True)
                    _ihdf = _con.execute("""
                        SELECT stock_id, company_shares, company_chg, company_pledge_pct,
                               major_holder_shares, major_holder_chg, major_holder_pledge_pct
                        FROM insider_holdings
                        QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY report_date DESC) = 1
                    """).fetchdf()
                    _con.close()
                    _insider_map = {str(r["stock_id"]): r for _, r in _ihdf.iterrows()}
                except Exception:
                    _insider_map = {}

                sh_rows = []
                for _, row in sh_df.iterrows():
                    sid = str(row["stock_id"])
                    info = name_map.get(sid, {})
                    close = _price_map.get((sid, str(row["date"])))
                    prev_close = _price_map.get((sid, str(row["prev_date"]))) if pd.notna(row["prev_date"]) else None
                    price_week_chg = (
                        round((close - prev_close) / prev_close * 100, 2)
                        if close is not None and prev_close is not None and prev_close != 0 else None
                    )
                    share_chg = row["share_chg"] if pd.notna(row["share_chg"]) else None
                    insider = _insider_map.get(sid)

                    sh_rows.append({
                        "stock_id":    sid,
                        "stock_name":  info.get("stock_name", ""),
                        "meta_sector": info.get("meta_sector", ""),
                        "lv12_15_pct": float(row["lv12_15_pct"]) if row["lv12_15_pct"] is not None else None,
                        "lv12_15_shares": int(row["lv12_15_shares"]) if pd.notna(row["lv12_15_shares"]) else None,
                        "share_chg":   int(share_chg) if share_chg is not None else None,
                        "week_chg":    float(row["week_chg"]) if row["week_chg"] is not None else None,
                        "streak":      int(row["streak"]) if row["streak"] is not None else 0,
                        "date":        str(row["date"]),
                        "close":       float(close) if close is not None else None,
                        "change_pct":  price_week_chg,
                        "company_shares":          int(insider["company_shares"]) if insider is not None and pd.notna(insider["company_shares"]) else None,
                        "company_chg":             int(insider["company_chg"]) if insider is not None and pd.notna(insider["company_chg"]) else None,
                        "company_pledge_pct":      float(insider["company_pledge_pct"]) if insider is not None and pd.notna(insider["company_pledge_pct"]) else None,
                        "major_holder_shares":     int(insider["major_holder_shares"]) if insider is not None and pd.notna(insider["major_holder_shares"]) else None,
                        "major_holder_chg":        int(insider["major_holder_chg"]) if insider is not None and pd.notna(insider["major_holder_chg"]) else None,
                        "major_holder_pledge_pct": float(insider["major_holder_pledge_pct"]) if insider is not None and pd.notna(insider["major_holder_pledge_pct"]) else None,
                    })
            else:
                sh_rows = []
        except Exception as exc:
            logger.warning("大戶持倉資料載入失敗: %s", exc)
            sh_rows = []
```

（`close`/`change_pct` 這兩個既有 key 名稱維持不變，只是語意從「最新交易日」改成「對齊集保週期的本週/週漲跌」——`_price_cell()`／`_shareholder_table()` 已經是通用消費這兩個 key，不需要跟著改名）

- [ ] **Step 4: 語法檢查**

Run: `.venv/bin/python -c "import ast; ast.parse(open('main.py').read())"`
Expected: 無輸出（無語法錯誤）

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat: main.py 串接內部人持股 CLI，Section 8 資料組裝加上價格對齊與內部人 join"
```

---

### Task 5: `export/chips_generator.py::_shareholder_table()` 新增欄位

**Files:**
- Modify: `export/chips_generator.py`（`_shareholder_table()`，約第 332-372 行）
- Test: `tests/test_chips_generator.py`（新檔）

**Interfaces:**
- Consumes：Task 4 產出的 `sh_rows` 新欄位（`lv12_15_shares`, `share_chg`, `company_shares`, `company_chg`, `company_pledge_pct`, `major_holder_shares`, `major_holder_chg`, `major_holder_pledge_pct`）
- Produces：`_shareholder_table(rows)` 回傳的 HTML 多 3 欄：大戶張數變化、公司派持股、大股東持股

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_chips_generator.py`：

```python
# tests/test_chips_generator.py
from export.chips_generator import _shareholder_table

_SAMPLE_ROW = {
    "stock_id": "2330", "stock_name": "台積電", "meta_sector": "半導體",
    "close": 950.0, "change_pct": 1.5,
    "lv12_15_pct": 20.0, "lv12_15_shares": 5_250_000, "share_chg": 250_000,
    "week_chg": 1.0, "streak": 2,
    "company_shares": 1_500_000, "company_chg": 100_000, "company_pledge_pct": 13.33,
    "major_holder_shares": 3_000_000, "major_holder_chg": -50_000, "major_holder_pledge_pct": 0.0,
}


def test_shareholder_table_includes_share_chg_column():
    html = _shareholder_table([_SAMPLE_ROW])
    assert "大戶張數變化" in html
    assert "250" in html  # 250,000 股 = 250 張


def test_shareholder_table_includes_insider_columns():
    html = _shareholder_table([_SAMPLE_ROW])
    assert "公司派" in html
    assert "大股東" in html
    assert "13.3" in html  # 質押比例


def test_shareholder_table_handles_missing_insider_data():
    """沒有 insider_holdings 資料的股票（新股/還沒跑過 --update-insider-holdings）要顯示「─」，不能報錯。"""
    row = dict(_SAMPLE_ROW)
    row["company_shares"] = None
    row["company_chg"] = None
    row["company_pledge_pct"] = None
    row["major_holder_shares"] = None
    row["major_holder_chg"] = None
    row["major_holder_pledge_pct"] = None
    html = _shareholder_table([row])
    assert "─" in html
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `.venv/bin/pytest tests/test_chips_generator.py -v`
Expected: FAIL（目前 `_shareholder_table` 沒有「大戶張數變化」「公司派」「大股東」字樣）

- [ ] **Step 3: 修改 `_shareholder_table()`**

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
            f"<td><span class='sid'>{s['stock_id']}</span> {s.get('stock_name','')}</td>"
            f"<td class='ct-meta'>{_meta_link(s.get('meta_sector',''))}</td>"
            f"{_price_cell(s.get('close'), s.get('change_pct'))}"
            f"<td style='color:{pct_color};font-weight:700'>{pct:.1f}%</td>"
            f"<td>{chg_html}</td>"
            f"<td>{share_chg_html}</td>"
            f"<td>{streak_html}</td>"
            f"<td>{company_html}</td>"
            f"<td>{major_html}</td>"
            f"</tr>"
        )
    html += "</tbody></table>"
    return html


def _insider_cell(shares, chg, pledge_pct) -> str:
    """內部人持股欄位：張數（第一行）＋ 月變化張數／質押% （第二行）。"""
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

- [ ] **Step 4: 執行測試確認通過**

Run: `.venv/bin/pytest tests/test_chips_generator.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全專案回歸測試**

Run: `.venv/bin/pytest -v`
Expected: 全部 PASS（新增的測試 + 既有全部測試都要過，注意 Task 1 Step 6 已經同步更新過 `tests/test_shareholder.py` 的 schema helper，如果還有其他地方直接建 `shareholder` 表的測試也要一併檢查欄位數對不對）

- [ ] **Step 6: Commit**

```bash
git add export/chips_generator.py tests/test_chips_generator.py
git commit -m "feat: Section 8 大戶持倉表格新增張數變化與內部人持股(公司派/大股東)欄位"
```

---

## Out of scope（本次不做，跟 spec 一致）

- 內部人持股／設質資料的 streak（連增/連減月數）追蹤
- 內部人持股歷史回補（backfill）
- `index.html`／`patterns.html` 的呈現調整
