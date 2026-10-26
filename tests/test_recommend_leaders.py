import pandas as pd

from recommend.leaders import leaders


def _panel():
    d = pd.bdate_range("2026-09-01", periods=30)
    series = {
        # 前 25 天 100 → 150，最後 5 天 150 附近橫盤、量縮 → 整理中
        "A": ([100 + 2 * k for k in range(25)] + [149, 150, 148, 150, 149], [1000] * 25 + [400] * 5, True),
        # 每天 +3% → 上攻中
        "B": ([100 * 1.03 ** k for k in range(30)], [1000] * 30, True),
        # 漲到 160 後回到 140 → 回檔中（離高點 −12.5%）
        "C": ([100 + 3 * k for k in range(21)] + [160, 155, 150, 146, 143, 141, 140, 140, 140], [1000] * 30, True),
        # 漲最多但沒流動性 → 不列
        "D": ([100 * 1.05 ** k for k in range(30)], [10] * 30, False),
    }
    rows = []
    for sid, (closes, vols, liq) in series.items():
        sector = "銅箔基板" if sid != "D" else "冷門"
        for dt, c, v in zip(d, closes, vols):
            rows.append({"stock_id": sid, "stock_name": sid, "meta_sector": sector, "date": dt,
                         "close": float(c), "volume": float(v), "liq": liq})
    return pd.DataFrame(rows), d


def test_stock_leaders_rank_and_status():
    f, d = _panel()
    out = leaders(f, d[-1])
    stocks = {r["stock_id"]: r for r in out["stocks"]}
    assert set(stocks) == {"A", "B", "C"}                              # D 沒流動性
    assert [r["stock_id"] for r in out["stocks"]] == ["B", "A", "C"]   # 依 21 日漲幅
    assert stocks["A"]["status"] == "整理中" and stocks["A"]["vr5_20"] < 1
    assert stocks["B"]["status"] == "上攻中"
    assert stocks["C"]["status"] == "回檔中" and stocks["C"]["from_high"] == -12.5
    assert stocks["B"]["ret21"] == round((1.03 ** 21 - 1) * 100, 1)
    assert out["stocks"][0]["rank"] == 1


def test_sector_needs_three_members_and_clips_fake_jumps():
    f, d = _panel()
    out = leaders(f, d[-1])
    assert [s["sector"] for s in out["sectors"]] == ["銅箔基板"]        # 冷門只有 1 檔
    assert out["sectors"][0]["n"] == 3
    # 除權／減資造成的單日 +600% 不能把族群灌爆（單日截在 ±11%）
    f2 = f.copy()
    f2.loc[(f2["stock_id"] == "A") & (f2["date"] == d[-1]), "close"] = 1000.0
    assert leaders(f2, d[-1])["sectors"][0]["ret21"] < out["sectors"][0]["ret21"] + 10


def test_not_enough_history_returns_empty():
    f, d = _panel()
    assert leaders(f, d[10]) == {"stocks": [], "sectors": []}
