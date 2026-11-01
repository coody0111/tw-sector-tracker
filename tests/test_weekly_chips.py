"""每週籌碼報告：台指期解析、指數、融資維持率、頁面、發布一次。"""
from pathlib import Path

import pandas as pd

from export.weekly_chips_generator import generate, render
from recommend.telegram_format import compose_weekly_message
from recommend.weekly_chips import index_row, load_futures_rows, maintenance, save_futures_snapshot
from scrapers.taifex import parse_snapshot


def _quote(month, session="一般", last="45301"):
    return {"Date": "20261030", "Contract": "TX", "ContractMonth(Week)": month, "Last": last, "SettlementPrice": "45300",
            "Change": "-1268", "Volume": "73987", "OpenInterest": "119040", "TradingSession": session}


def _inst(item, net):
    return {"Date": "20261030", "ContractCode": "臺股期貨", "Item": item, "OpenInterest(Net)": net}


INST = [_inst("外資及陸資", "-92241"), _inst("投信", "89211"), _inst("自營商", "1736")]


def test_parse_snapshot_takes_near_month_regular_session():
    q = [_quote("202612"), _quote("202611", "盤後", "1"), _quote("202611W1"), _quote("202611/202612"), _quote("202611")]
    s = parse_snapshot(q, INST)
    assert s["date"] == "2026-10-30" and s["contract"] == "202611" and s["close"] == 45301
    assert s["foreign_net"] == -92241 and s["trust_net"] == 89211 and s["dealer_net"] == 1736


def test_parse_snapshot_none_when_institutions_are_another_day():
    assert parse_snapshot([_quote("202611")], [{**x, "Date": "20261029"} for x in INST]) is None


def test_futures_csv_overwrites_same_day_and_finds_last_week(tmp_path):
    path = tmp_path / "f.csv"
    for d, net in (("2026-10-22", -80000), ("2026-10-30", -1), ("2026-10-30", -92241)):
        save_futures_snapshot({"date": d, "contract": "202611", "foreign_net": net}, path)
    now, prev = load_futures_rows("2026-10-30", path)
    assert now["foreign_net"] == -92241 and prev["date"] == "2026-10-22" and len(pd.read_csv(path)) == 2


def test_index_row_week_base_is_last_close_before_monday():
    rows = [{"date": f"2026-08-{d:02d}", "close": 100.0} for d in range(1, 30)] + \
           [{"date": f"2026-09-{d:02d}", "close": 100.0} for d in range(1, 29)] + \
           [{"date": "2026-10-22", "close": 200.0}, {"date": "2026-10-29", "close": 210.0}, {"date": "2026-10-30", "close": 189.0}]
    r = index_row("加權", rows, "2026-10-30")
    assert round(r["day_pct"], 2) == -10.0 and round(r["week_pct"], 2) == -5.5 and r["ma60_pct"] is not None
    assert index_row("加權", rows, "2026-10-31") is None


def test_maintenance_uses_exchange_financing_and_weights_by_value():
    df = pd.DataFrame([
        {"stock_id": "1", "stock_name": "甲", "close": 60.0, "avg": 100.0, "balance": 10, "exchange": "TWSE"},
        {"stock_id": "2", "stock_name": "乙", "close": 100.0, "avg": 100.0, "balance": 10, "exchange": "TPEx"},
        {"stock_id": "3", "stock_name": "丙", "close": 1.0, "avg": 100.0, "balance": 0, "exchange": "TWSE"},
    ])
    m = maintenance(df)
    assert m["n"] == 2 and round(m["twse"], 1) == 100.0 and round(m["tpex"], 1) == 200.0
    assert round(m["all"], 1) == round(1600 / 1100 * 100, 1) and [x["stock_id"] for x in m["danger"]] == ["1"]


def _weekly(**kw):
    row = {"stock_id": "2330", "stock_name": "<b>台積電", "meta_sector": "晶圓代工", "lv12_15_pct": 80.0, "week_chg": 1.0, "streak": 2}
    ratio = {"stock_id": "3665", "stock_name": "貿聯", "balance": 100, "close": 1625.0, "avg": 2132.8, "ratio": 127.0}
    w = {"date": "2026-10-30", "indices": [{"name": "櫃買", "close": 370.26, "day_pct": -4.42, "week_pct": -2.99, "ma60_pct": None}],
         "futures": {"contract": "202611", "close": 45301, "change": -1268, "volume": 73987, "open_interest": 119040,
                     "foreign_net": -92241, "trust_net": 89211, "dealer_net": 1736},
         "futures_oi_change": None, "maintenance": {"all": 158.2, "twse": 151.4, "tpex": 181.5, "n": 932, "below_watch": 137, "below_danger": 1,
                                                    "danger": [ratio], "largest": [ratio]},
         "holders_up_n": 1, "holders_down_n": 0, "holders_up": [row], "holders_down": [], "sectors_up": [{"sector": "記憶體", "big_chg": 0.5}],
         "sectors_down": [], "margin_total": -100, "margin_up": [], "margin_down": [{"name": "友達", "chg": -100}], "points": ["融資本週減少 100 張"]}
    return {**w, **kw}


def test_page_escapes_and_marks_estimate():
    html = render(_weekly(), ["2026-10-30"])
    assert "<b>台積電" not in html and "這是估計值" in html and "−92,241" in html and "櫃買" in html


def test_page_without_futures_or_danger():
    w = _weekly(futures=None)
    w["maintenance"] = {**w["maintenance"], "danger": []}
    html = render(w, ["2026-10-30"])
    assert "台指期資料未到" in html and "沒有低於 130% 的股票" in html


def test_archive_and_message(tmp_path):
    latest, folder = tmp_path / "weekly.html", tmp_path / "weekly"
    generate(_weekly(), str(latest), str(folder))
    assert '<base href="../">' in (folder / "2026-10-30.html").read_text(encoding="utf-8")
    assert (folder / "index.json").read_text(encoding="utf-8") == '["2026-10-30"]'
    msg = compose_weekly_message(_weekly(), "https://x/weekly.html")
    assert "10/30 每週籌碼報告" in msg and "融資本週減少 100 張" in msg and "https://x/weekly.html" in msg


def _env(monkeypatch, tmp_path, ready=True):
    import main as m
    import recommend.weekly_chips as wc
    import scrapers.taifex as tf
    monkeypatch.setattr(wc, "ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr(wc, "FUTURES_PATH", tmp_path / "f.csv")
    monkeypatch.setattr(wc, "WEEKLY_PATH", tmp_path / "w.json")
    monkeypatch.setattr(wc, "NOTIFIED_PATH", tmp_path / "n.txt")
    monkeypatch.setattr(wc, "latest_shareholder_date", lambda: "2026-10-30")
    monkeypatch.setattr(wc, "inputs_ready", lambda d: ready)
    monkeypatch.setattr(wc, "build_weekly", lambda *a: _weekly())
    monkeypatch.setattr(tf, "fetch_futures_snapshot", lambda: None)
    monkeypatch.setattr(m, "fetch_taiex_history", lambda d, months: [])
    monkeypatch.setattr("scrapers.taiex.fetch_tpex_index_history", lambda d, months: [])
    monkeypatch.setattr(m, "RECOMMEND_PAYLOAD_PATH", tmp_path / "none.json")
    built, pushed = [], []
    monkeypatch.setattr("export.weekly_chips_generator.generate", lambda w: built.append(w))
    monkeypatch.setattr(m, "_push_html", lambda d: pushed.append(d) or True)
    return m, built, pushed


def test_unsent_report_is_resent_without_rebuilding_until_marked(monkeypatch, tmp_path):
    import recommend.weekly_chips as wc
    m, built, pushed = _env(monkeypatch, tmp_path)
    assert m._publish_weekly_chips(True)["date"] == "2026-10-30" and len(built) == len(pushed) == 1
    (tmp_path / "2026-10-30.html").write_text("x", encoding="utf-8")
    assert m._publish_weekly_chips(True)["points"] and len(built) == 1          # 手動跑或發送失敗：下次補發
    wc.mark_notified("2026-10-30", wc.NOTIFIED_PATH)
    assert m._publish_weekly_chips(True) is None and len(built) == 1


def test_scheduler_marks_only_after_successful_send(monkeypatch):
    import scripts.run_scheduled as sr
    marks = []
    monkeypatch.setattr(sr, "mark_notified", marks.append)
    monkeypatch.setattr(sr, "send_telegram_message", lambda *a, **k: False)
    sr.send_weekly_message({"weekly_chips": _weekly()}, "https://x/")
    assert marks == []
    monkeypatch.setattr(sr, "send_telegram_message", lambda *a, **k: True)
    sr.send_weekly_message({"weekly_chips": _weekly()}, "https://x/")
    assert marks == ["2026-10-30"]


def test_publish_waits_for_inputs(monkeypatch, tmp_path):
    m, built, _ = _env(monkeypatch, tmp_path, ready=False)
    assert m._publish_weekly_chips(True) is None and not built


def test_publish_failure_does_not_raise(monkeypatch, tmp_path):
    m, built, _ = _env(monkeypatch, tmp_path)
    monkeypatch.setattr("recommend.weekly_chips.build_weekly", lambda *a: 1 / 0)
    assert m._publish_weekly_chips(True) is None and not built


def test_new_page_is_pushed_and_linked():
    import inspect
    import main as m
    from export.ui_theme import NAV_PAGES
    assert '"docs/weekly"' in inspect.getsource(m._push_html) and ("weekly.html", "每週籌碼") in NAV_PAGES
    assert 'href="weekly.html"' in Path("export/index_generator.py").read_text(encoding="utf-8")
