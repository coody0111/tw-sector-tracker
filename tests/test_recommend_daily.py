import pandas as pd

from recommend.daily import build_payload


class _FakeStrategy:
    name = "測試策略"

    def __init__(self, hits):
        self.hits = hits

    def scan(self, features):
        rows = [{"stock_id": sid, "date": d, "strategy": self.name, "type": "整理", "routes": "法人", "n_routes": 1}
                for sid, d in self.hits]
        return pd.DataFrame(rows, columns=["stock_id", "date", "strategy", "type", "routes", "n_routes"])


def _feat():
    d = pd.bdate_range("2026-01-01", periods=70)
    rows = []
    for sid, sector, tail in (("A", "銅箔基板", [100, 101, 102]), ("B", "散熱", [100, 90, 90]),
                              ("C", "銅箔基板", [100, 100, 100])):
        closes = [100.0] * 67 + [float(x) for x in tail]
        for dt, c in zip(d, closes):
            rows.append({"stock_id": sid, "stock_name": sid, "meta_sector": sector, "date": dt, "open": c, "close": c,
                         "change": 0.0, "volume": 1000.0, "limit_up": False, "liq": True,
                         "one_word": False})
    return pd.DataFrame(rows), d


def test_build_payload_splits_new_active_invalid(monkeypatch):
    f, d = _feat()
    strat = _FakeStrategy([("C", d[-1]), ("A", d[-3]), ("B", d[-3]), ("A", d[-10])])
    monkeypatch.setattr("recommend.daily.ALL_STRATEGIES", [strat])
    p = build_payload(f, d[-1])
    assert [(g["sector"], g["count"]) for g in p["new"]] == [("銅箔基板", 1)]
    assert [(c["stock_id"], c["day_n"]) for c in p["active"]] == [("A", 3)]
    assert [c["stock_id"] for c in p["invalid"]] == ["B"]           # 100 → 90 失效
    assert set(p["header"]) >= {"above_ma20_pct", "limit_up", "limit_down", "fail_rate"}
    assert [r["stock_id"] for r in p["leaders"]["stocks"]][0] == "A"   # 近 21 天漲最多
    assert p["new"][0]["cards"][0]["top21"] is True                     # C 也在前 20 名內


def test_json_safe_turns_nan_and_numpy_into_json_values():
    import json
    import numpy as np
    from recommend.daily import json_safe
    out = json_safe({"a": float("nan"), "b": [np.float64(1.5), np.int64(2), np.bool_(True)], "c": "x"})
    assert out == {"a": None, "b": [1.5, 2, True], "c": "x"}
    json.dumps(out, allow_nan=False)
