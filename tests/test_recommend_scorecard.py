import duckdb
import pandas as pd

from recommend.scorecard import ensure_table, record_signals, refresh, summary


def _feat(closes, one_word=None):
    d = pd.bdate_range("2026-01-01", periods=len(closes))
    return pd.DataFrame({"stock_id": "6672", "date": d, "open": closes, "close": closes,
                         "one_word": one_word or [False] * len(closes)})


def _sig(day):
    return pd.DataFrame([{"stock_id": "6672", "date": day, "strategy": "突破策略", "type": "整理",
                          "routes": "法人", "n_routes": 1}])


def test_record_refresh_and_summary_track_until_exit():
    con = duckdb.connect(":memory:")
    ensure_table(con)
    f = _feat([100.0, 100.0, 102.0])
    record_signals(con, _sig(f["date"][0]), f)
    assert record_signals(con, _sig(f["date"][0]), f) == 0              # 重複寫入不會多一列
    refresh(con, f)
    row = con.execute("SELECT signal_close, entry_price, exit_reason FROM recommendations").fetchone()
    assert row == (100.0, 100.0, "持有中")
    f2 = _feat([100.0, 100.0, 102.0, 93.0])                             # 隔天資料進來 → 停損
    refresh(con, f2)
    assert con.execute("SELECT exit_reason FROM recommendations").fetchone()[0] == "停損"
    s = summary(con, "突破策略")
    assert s["n"] == 1 and s["open_n"] == 0 and s["win_rate"] == 0.0


def test_unfillable_next_day_one_word_marked_and_excluded():
    con = duckdb.connect(":memory:")
    ensure_table(con)
    f = _feat([100.0, 110.0, 111.0], one_word=[False, True, False])
    record_signals(con, _sig(f["date"][0]), f)
    refresh(con, f)
    assert con.execute("SELECT exit_reason FROM recommendations").fetchone()[0] == "買不到"
    assert summary(con, "突破策略")["n"] == 0
