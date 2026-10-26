import pandas as pd

from recommend.cards import build_cards, group_by_sector


def _feat(closes, sid="6672", sector="銅箔基板"):
    d = pd.bdate_range("2026-06-01", periods=len(closes))
    return pd.DataFrame({"stock_id": sid, "stock_name": "名稱", "meta_sector": sector, "date": d,
                         "close": closes, "change": [0.0] + [closes[i] - closes[i - 1] for i in range(1, len(closes))]})


def _sig(sid, day):
    return pd.DataFrame([{"stock_id": sid, "date": day, "strategy": "突破策略", "type": "整理",
                          "routes": "法人,外資", "n_routes": 2}])


def test_card_alerts_bias_and_below_ma60():
    closes = [200.0] * 60 + [100.0] * 9 + [140.0]           # MA10=104 → 乖離 34.6%；MA60=184 > 140
    f = _feat(closes)
    day = f["date"].iloc[-1]
    c = build_cards(f, _sig("6672", day), day)[0]
    assert c["alerts"] == ["乖離大", "季線下"]
    assert c["status"] == "有效" and c["since_signal_pct"] == 0.0


def test_card_status_invalid_after_six_percent_drop_and_no_rally_alert():
    f = _feat([100.0] * 70 + [110.0, 103.0])
    sig_day, today = f["date"].iloc[-2], f["date"].iloc[-1]
    c = build_cards(f, _sig("6672", sig_day), today)[0]
    assert c["status"] == "失效"                                   # 103 ≤ 110 × 0.94
    f2 = _feat([100.0] * 70 + [110.0, 125.0])
    c2 = build_cards(f2, _sig("6672", sig_day), today)[0]
    assert "已漲多" not in c2["alerts"] and c2["status"] == "有效"  # 13.13：漲多沒有變差，拿掉這個提醒


def test_group_by_sector_orders_by_count():
    cards = [{"meta_sector": "散熱"}, {"meta_sector": "銅箔基板"}, {"meta_sector": "銅箔基板"}]
    g = group_by_sector(cards)
    assert [(x["sector"], x["count"]) for x in g] == [("銅箔基板", 2), ("散熱", 1)]
