import pandas as pd

from recommend.strategies import ALL_STRATEGIES
from recommend.strategies.breakout import BreakoutStrategy


def _feat(**over):
    base = {"stock_id": "6672", "date": pd.Timestamp("2026-09-24"), "close": 337.5, "hi90": 310.0,
            "limit_up": True, "liq": True, "rng20": 0.179, "ret20_prev": 0.05,
            "inst5_pr": 1.0, "fpct5_pr": 1.0, "trust_days10": 4, "big1w_pr": 0.94}
    base.update(over)
    return pd.DataFrame([base])


def test_6672_0924_is_consolidation_with_three_routes():
    r = BreakoutStrategy().scan(_feat()).iloc[0]
    assert (r["strategy"], r["type"], r["routes"], r["n_routes"]) == ("突破策略", "整理", "法人,外資,大戶", 3)


def test_continuation_type_and_rejections():
    s = BreakoutStrategy()
    assert s.scan(_feat(rng20=0.45, ret20_prev=0.25)).iloc[0]["type"] == "續攻"
    assert s.scan(_feat(rng20=0.45, ret20_prev=0.10)).empty        # 大起大落沒漲
    assert s.scan(_feat(rng20=0.75, ret20_prev=0.40)).empty        # 區間 ≥ 70%
    assert s.scan(_feat(close=300.0)).empty                        # 沒創 90 日高
    assert s.scan(_feat(limit_up=False)).empty
    assert s.scan(_feat(liq=False)).empty
    assert s.scan(_feat(inst5_pr=0.5, fpct5_pr=0.5, trust_days10=2, big1w_pr=0.5)).empty  # 沒有籌碼路線


def test_registry_contains_breakout():
    assert [s.name for s in ALL_STRATEGIES] == ["突破策略"]
