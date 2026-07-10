"""
集保大戶持倉 streak 計算的回歸測試。

重點：`_add_week_change_streak` 的 streak 基準必須是「嚴格更舊的週」，
不能是正在寫入的同一週——否則同一週被重跑（每日 cron、或 TDCC 尚未出新週
仍抓到同一週）時會拿自己當基準，把 streak 洗成 0。
"""
import duckdb
import pandas as pd
import requests

from scrapers.shareholder import (
    _add_week_change_streak,
    _fetch_one_stock,
    fetch_shareholder_weekly,
    recompute_latest_streak,
    save_to_db,
)


def _make_table(con):
    con.execute("""
        CREATE TABLE shareholder (
            stock_id VARCHAR NOT NULL, date DATE NOT NULL,
            lv12_15_pct DOUBLE, lv12_15_cnt INTEGER, lv12_15_shares BIGINT,
            total_shares BIGINT, week_chg DOUBLE, streak INTEGER,
            PRIMARY KEY (stock_id, date)
        )
    """)


def _insert(con, sid, d, pct, streak):
    con.execute(
        "INSERT INTO shareholder VALUES (?, ?, ?, 0, 0, 0, 0.0, ?)",
        [sid, pd.to_datetime(d).date(), pct, streak],
    )


def _week_df(sid, d, pct):
    return pd.DataFrame([{
        "stock_id": sid,
        "date": pd.to_datetime(d).date(),
        "lv12_15_pct": pct,
    }])


def test_streak_accumulates_across_increasing_weeks(tmp_path):
    """由舊到新逐週寫入、大戶比例連續上升時，streak 應 0→1→2 累加。"""
    con = duckdb.connect(str(tmp_path / "t.db"))
    _make_table(con)

    df1 = _week_df("2330", "2026-05-01", 10.0)   # 首週無前值
    _add_week_change_streak(con, df1)
    assert df1["streak"].iloc[0] == 0
    _insert(con, "2330", "2026-05-01", 10.0, 0)

    df2 = _week_df("2330", "2026-05-08", 11.0)   # 續升
    _add_week_change_streak(con, df2)
    assert df2["streak"].iloc[0] == 1
    _insert(con, "2330", "2026-05-08", 11.0, 1)

    df3 = _week_df("2330", "2026-05-15", 12.0)   # 再升
    _add_week_change_streak(con, df3)
    assert df3["streak"].iloc[0] == 2
    con.close()


def test_rerun_same_week_does_not_corrupt_streak(tmp_path):
    """同一週被重跑（同 date）時，streak 不應被自己洗成 0。"""
    con = duckdb.connect(str(tmp_path / "t.db"))
    _make_table(con)
    # 已有兩週，streak 累到 2
    _insert(con, "2330", "2026-05-01", 10.0, 1)
    _insert(con, "2330", "2026-05-08", 11.0, 2)

    # 重跑第二週（同 date、同資料）
    df_rerun = _week_df("2330", "2026-05-08", 11.0)
    _add_week_change_streak(con, df_rerun)

    # 應拿「嚴格更舊的 2026-05-01(streak 1)」當基準 → 11>10 → streak 2
    # 若沒有 date< guard，會拿自己(streak 2)當基準 → chg=0 → streak 洗成 0（bug）
    assert df_rerun["streak"].iloc[0] == 2, (
        f"重跑同週後 streak 被弄壞：{df_rerun['streak'].iloc[0]}（應為 2）"
    )
    con.close()


def test_streak_flips_direction_on_decrease(tmp_path):
    """連增後轉為下降，streak 應從正翻成 -1（方向重置）。"""
    con = duckdb.connect(str(tmp_path / "t.db"))
    _make_table(con)
    _insert(con, "2330", "2026-05-01", 10.0, 1)
    _insert(con, "2330", "2026-05-08", 12.0, 2)

    df = _week_df("2330", "2026-05-15", 11.0)   # 由升轉降
    _add_week_change_streak(con, df)
    assert df["streak"].iloc[0] == -1
    con.close()


def test_recompute_latest_streak_fixes_week_frozen_before_backfill(tmp_path):
    """
    重現真實 bug：--update-shareholder 先寫入最新週（當時 DB 是空的，沒有更舊的
    週可比，streak 被記成 0），之後 --backfill-shareholder 才把更舊的週補進來。
    最新週的 streak 不會自動更新，因為沒有任何呼叫再重寫那一批——
    recompute_latest_streak() 應該把它重算成正確值。
    """
    db_path = tmp_path / "t.db"
    con = duckdb.connect(str(db_path))
    _make_table(con)
    _insert(con, "2330", "2026-06-26", 15.0, 0)   # 先寫最新週，當時無前值 → streak=0（凍結前）
    con.close()

    # 之後才 backfill 補進更舊的週
    con = duckdb.connect(str(db_path))
    _insert(con, "2330", "2026-06-12", 13.0, 1)
    con.close()

    updated = recompute_latest_streak(str(db_path))
    assert updated == 1

    con = duckdb.connect(str(db_path))
    row = con.execute(
        "SELECT week_chg, streak FROM shareholder WHERE stock_id='2330' AND date='2026-06-26'"
    ).fetchone()
    con.close()
    assert row[0] == 2.0   # 15.0 - 13.0
    assert row[1] == 2     # 上一週 streak=1（正）且本週續升 → 累加成 2


def test_week_chg_null_roundtrips_as_nan_not_none(tmp_path):
    """main.py 組 sh_rows 時用 `None if pd.isna(row['week_chg']) else float(...)` 轉換
    week_chg（DuckDB DOUBLE NULL 經 pandas .df() 轉換後是 float('nan')，不是 None——
    跟先前修過的 pd.NA 那個 bug是同一類問題，只是這裡是 NaN 版本）。
    這裡直接驗證 DuckDB NULL DOUBLE 的真實 round-trip 行為，確保修法用的 pd.isna()
    正確處理，而舊寫法 `value is not None` 會誤判成「有值」、讓 nan 流到下游渲染成 "nan%"。
    """
    db_path = tmp_path / "test.db"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE t (week_chg DOUBLE)")
    con.execute("INSERT INTO t VALUES (NULL)")
    df = con.execute("SELECT week_chg FROM t").df()
    con.close()

    raw = df.loc[0, "week_chg"]
    assert pd.isna(raw)

    fixed = None if pd.isna(raw) else float(raw)
    assert fixed is None

    buggy = float(raw) if raw is not None else None
    assert buggy is not None and pd.isna(buggy)  # 證明舊寫法會讓 nan 流過去，不是 None


def test_recompute_latest_streak_skips_stock_with_only_one_week(tmp_path):
    """只有一週資料（無前值可比）的股票，recompute 應跳過、不報錯。"""
    db_path = tmp_path / "t.db"
    con = duckdb.connect(str(db_path))
    _make_table(con)
    _insert(con, "9999", "2026-06-26", 20.0, 0)
    con.close()

    updated = recompute_latest_streak(str(db_path))
    assert updated == 0


def test_transient_post_failure_is_retried(monkeypatch):
    """
    重現真實 bug：`_fetch_one_stock` 原本自己 catch POST 的例外並 return None，
    導致 `fetch_shareholder_weekly` 外層的重試迴圈永遠看不到例外、`ok=True` 在
    第一次嘗試就成立，重試機制（_MAX_RETRIES=3）形同虛設——TDCC 偶發的 SSL 斷線
    /限流不會被重試，跟修這個 bug 之前「零重試」的行為一樣。

    這裡驗證：第一次 POST 拋出 ConnectionError 時，應該被外層重試迴圈接住重打，
    而不是被內層默默吞掉、直接判定成「無資料」放棄。
    """
    call_count = {"n": 0}

    class FakeResp:
        text = (
            "<table></table>"
            "<table>"
            "<tr><td>1</td><td>1-999</td><td>10</td><td>1000</td><td>1.0</td></tr>"
            "<tr><td>16</td><td>合計</td><td>20</td><td>100000</td><td>100.0</td></tr>"
            "</table>"
        )

        def raise_for_status(self):
            pass

    class FakeSession:
        def post(self, *args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise requests.exceptions.ConnectionError("transient TDCC disconnect")
            return FakeResp()

    def fake_get_session_tokens():
        return FakeSession(), "tok", "uri", ["20260703"]

    import scrapers.shareholder as shareholder_mod
    monkeypatch.setattr(shareholder_mod, "_get_session_tokens", fake_get_session_tokens)
    monkeypatch.setattr(shareholder_mod.time, "sleep", lambda *a, **kw: None)

    results = fetch_shareholder_weekly(["2330"], date_str="20260703", delay=0)

    assert call_count["n"] == 2, (
        f"POST 應該在第一次 ConnectionError 後被重試迴圈接住重打一次才成功，"
        f"實際呼叫次數={call_count['n']}（若=1，代表重試機制沒生效，bug 還在）"
    )
    assert len(results) == 1
    assert results[0]["stock_id"] == "2330"


def test_save_to_db_persists_lv12_15_shares(tmp_path, monkeypatch):
    """save_to_db 應該把 lv12_15_shares（大戶實際張數）寫進 shareholder 表，
    不能像現在這樣只存 lv12_15_pct/lv12_15_cnt/total_shares 三個欄位、丟掉張數。"""
    import scrapers.shareholder as shareholder_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(shareholder_mod, "_DB_PATH", db_path)

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
