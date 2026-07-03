import json
import pandas as pd
from datetime import date
from export.data_generator import generate

def test_generate_writes_expected_json_shape(tmp_path):
    output_path = tmp_path / "data.json"

    meta_perf = [{
        "meta_name": "先進封裝設備",
        "sub_names": ["半導體製程設備"],
        "avg_change_pct": 4.77,
        "up_count": 9,
        "down_count": 0,
        "flat_count": 0,
        "stock_ids": ["3583"],
    }]
    universe_df = pd.DataFrame([
        {"stock_id": "3583", "stock_name": "辛耘", "meta_sector": "先進封裝設備",
         "sub_sector": "半導體製程設備"},
    ])
    prices_df = pd.DataFrame([
        {"stock_id": "3583", "close": 905.0, "change_pct": 0.11, "volume": 3000},
    ])
    chips_df = pd.DataFrame([
        {"stock_id": "3583", "foreign_net": 336398, "trust_net": -82000,
         "margin_balance": 0, "margin_change": 0},
    ])
    cum_data = [{"meta_name": "先進封裝設備", "cum1": 0.1, "cum3": 12.0, "cum5": 10.9, "cum7": 9.4}]
    meta_signals = {"先進封裝設備": {
        "daily_pct": [0.1, 4.99], "dates": ["6/30", "7/1"],
        "streak": 3, "vol_ratio": 2.5, "yesterday_rank": 10,
    }}
    weekly_rank = {"先進封裝設備": {"this_week_rank": 1, "last_week_rank": 8}}
    stock_sparklines = {"3583": [0.1, 4.99, 4.99, 4.99, 4.99, 4.99]}

    generate(
        trade_date=date(2026, 7, 1),
        meta_perf=meta_perf,
        universe_df=universe_df,
        prices_df=prices_df,
        chips_df=chips_df,
        cum_data=cum_data,
        meta_signals=meta_signals,
        weekly_rank=weekly_rank,
        stock_sparklines=stock_sparklines,
        output_path=str(output_path),
    )

    data = json.loads(output_path.read_text(encoding="utf-8"))

    assert data["date"] == "2026-07-01"
    assert data["market"]["up"] == 9
    meta = data["metaSectors"][0]
    assert meta["name"] == "先進封裝設備"
    assert meta["avgChangePct"] == 4.77
    assert meta["todayRank"] == 1
    assert meta["yesterdayRank"] == 10
    assert meta["thisWeekRank"] == 1
    assert meta["lastWeekRank"] == 8
    assert meta["streak"] == 3
    assert meta["volRatio"] == 2.5
    sub = meta["subGroups"][0]
    assert sub["name"] == "半導體製程設備"
    stock = sub["stocks"][0]
    assert stock["id"] == "3583"
    assert stock["close"] == 905.0
    assert stock["foreignNet"] == 336   # 股 → 張，除以 1000
    assert stock["trustNet"] == -82
    assert stock["sparkline"] == [0.1, 4.99, 4.99, 4.99, 4.99, 4.99]
