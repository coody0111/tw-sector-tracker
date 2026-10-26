import duckdb
import pandas as pd

from recommend.scorecard import ensure_table, record_signals, summary
from recommend.withdraw import mark_withdrawn, withdraw_reasons

DAY = pd.Timestamp("2026-10-23")


def _feat(rows):
    base = {"date": DAY, "inst5_pr": 0.95, "fpct5_pr": 0.5, "trust_days10": 2.0, "big1w_pr": 0.5}
    return pd.DataFrame([{**base, **r} for r in rows])


def test_reason_names_each_lost_route_with_value_and_threshold():
    f = _feat([{"stock_id": "3537", "inst5_pr": 0.88, "big1w_pr": 0.95},
               {"stock_id": "3701", "trust_days10": 5.0},
               {"stock_id": "6155"},
               {"stock_id": "2368", "big1w_pr": 0.896}])
    cards = [{"stock_id": "3537", "stock_name": "晶相光", "routes": "法人,大戶"},
             {"stock_id": "3701", "stock_name": "大眾控", "routes": "投信"},
             {"stock_id": "6155", "stock_name": "鈞寶", "routes": "法人"},
             {"stock_id": "9999", "stock_name": "停牌", "routes": "法人"},
             {"stock_id": "2368", "stock_name": "金像電", "routes": "大戶"}]
    out = {w["stock_id"]: w["reason"] for w in withdraw_reasons(f, DAY, cards)}
    assert out["3537"] == "法人買超占股本排名前 12.0%（需前 10%）"        # 大戶仍命中，不列
    assert out["3701"] == "投信 10 日買超 5 天（需 ≥ 6 天）"
    assert out["6155"] == "籌碼路線仍命中，其他條件改變"
    assert out["9999"] == "籌碼路線仍命中，其他條件改變"
    assert out["2368"] == "大戶週增排名前 10.4%（需前 10%）"            # 差一點點也看得出來沒過


def test_mark_withdrawn_excluded_from_scorecard():
    con = duckdb.connect(":memory:")
    ensure_table(con)
    d = pd.bdate_range("2026-10-21", periods=3)
    f = pd.DataFrame({"stock_id": "3537", "date": d, "open": 100.0, "close": 100.0, "one_word": False})
    sig = pd.DataFrame([{"stock_id": "3537", "date": d[-1], "strategy": "突破策略", "type": "整理",
                         "routes": "法人", "n_routes": 1}])
    record_signals(con, sig, f)
    assert mark_withdrawn(con, [{"stock_id": "3537", "strategy": "突破策略"}], d[-1]) == 1
    assert con.execute("SELECT exit_reason FROM recommendations").fetchone()[0] == "撤回"
    s = summary(con, "突破策略")
    assert s["n"] == 0 and s["withdrawn_n"] == 1 and s["open_n"] == 0
