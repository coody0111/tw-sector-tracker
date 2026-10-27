import pandas as pd
import pytest

from recommend.sector_heat import sector_heat

DAYS = pd.bdate_range("2026-08-03", periods=40)


def _stock(sid, sector, closes, net=0.0, liq=True):
    return pd.DataFrame({
        "stock_id": sid, "stock_name": sid, "meta_sector": sector, "date": DAYS, "close": closes, "aclose": closes,
        "foreign_net": net, "trust_net": 0.0, "total_shares": 1_000_000.0, "fpct5": 0.1, "big1w": 0.2,
        "liq": liq, "limit_up": False,
    })


def _panel(hot_net=50_000.0):
    rows = []
    # 熱族群：最後 21 天每天 +1%，法人每天買 5 萬股（5 日 25 萬股 × 價格 ÷ 市值 100 萬股 × 價格 ＝ 25%）
    hot = [100.0] * 18 + [100 * 1.01 ** k for k in range(1, 23)]
    for i in range(5):
        rows.append(_stock(f"H{i}", "熱族群", hot, net=hot_net))
    # 冷族群：平盤、沒有法人
    for i in range(5):
        rows.append(_stock(f"C{i}", "冷族群", [100.0] * 40))
    # 前段熱、最近冷：前 5 天前很熱，之後下跌
    cool = [100 * 1.02 ** k for k in range(1, 36)] + [100 * 1.02 ** 35 * 0.97 ** k for k in range(1, 6)]
    for i in range(5):
        rows.append(_stock(f"W{i}", "退燒族群", cool))
    # 只有 4 檔 → 不排
    for i in range(4):
        rows.append(_stock(f"S{i}", "小族群", hot, net=hot_net))
    return pd.concat(rows, ignore_index=True)


def test_score_ranks_hot_sector_first_and_skips_small_sector():
    h = sector_heat(_panel(), DAYS[-1])
    assert [s["sector"] for s in h["sectors"]][0] == "熱族群"
    assert "小族群" not in {s["sector"] for s in h["sectors"]}
    hot = h["sectors"][0]
    assert hot["n"] == 5 and hot["score"] == 100.0
    assert hot["ret21"] == pytest.approx((1.01 ** 21 - 1) * 100, abs=0.01)
    assert hot["inst_ratio"] == pytest.approx(25.0)               # 25 萬股 ÷ 100 萬股
    assert hot["inst_breadth"] == 100.0 and hot["above_ma20"] == 100.0
    assert hot["foreign_chg"] == pytest.approx(0.1) and hot["big_chg"] == pytest.approx(0.2)   # 只顯示
    assert [m["stock_id"] for m in hot["leaders"]] == ["H0", "H1", "H2"] and len(hot["members"]) == 5


def test_heating_and_cooling_compare_with_five_days_ago():
    h = sector_heat(_panel(), DAYS[-1])
    assert h["compare_date"] == DAYS[-6].date().isoformat()
    by = {s["sector"]: s for s in h["sectors"]}
    assert by["退燒族群"]["status"] == "拉回中"
    assert all(s["sector"] in {x["sector"] for x in h["top"]} for s in h["heating"])


def test_missing_chip_columns_or_short_history_returns_empty():
    p = _panel()
    assert sector_heat(p.drop(columns=["foreign_net"]), DAYS[-1])["sectors"] == []
    assert sector_heat(p, DAYS[15])["top"] == []


def test_member_with_liquidity_only_today_uses_full_22_day_window():
    """Debugger 2026-10-27：成員＝今天有流動性；21 日漲幅用整段價格，不逐日看流動性（6925 意藍曾被漏掉）。"""
    p = _panel()
    late = _stock("H9", "熱族群", [100.0] * 18 + [100.0 * 2 ** (k / 21) for k in range(1, 23)])
    late["liq"] = [False] * 39 + [True]                       # 今天才有流動性
    h = sector_heat(pd.concat([p, late], ignore_index=True), DAYS[-1])
    hot = next(s for s in h["sectors"] if s["sector"] == "熱族群")
    top = hot["members"][0]
    assert top["stock_id"] == "H9" and top["ret21"] == pytest.approx(100.0, abs=0.1)   # 21 日前 → 今天剛好翻倍
