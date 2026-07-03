"""
集保大戶持倉 streak 計算的回歸測試。

重點：`_add_week_change_streak` 的 streak 基準必須是「嚴格更舊的週」，
不能是正在寫入的同一週——否則同一週被重跑（每日 cron、或 TDCC 尚未出新週
仍抓到同一週）時會拿自己當基準，把 streak 洗成 0。
"""
import duckdb
import pandas as pd

from scrapers.shareholder import _add_week_change_streak


def _make_table(con):
    con.execute("""
        CREATE TABLE shareholder (
            stock_id VARCHAR NOT NULL, date DATE NOT NULL,
            lv12_15_pct DOUBLE, lv12_15_cnt INTEGER, total_shares BIGINT,
            week_chg DOUBLE, streak INTEGER,
            PRIMARY KEY (stock_id, date)
        )
    """)


def _insert(con, sid, d, pct, streak):
    con.execute(
        "INSERT INTO shareholder VALUES (?, ?, ?, 0, 0, 0.0, ?)",
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
