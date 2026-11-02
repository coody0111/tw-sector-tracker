"""大盤融資維持率(估)：算法、只在找得到完整融資日時給值、推薦頁與每日報告顯示（2026-11-03）。"""
import duckdb
import pandas as pd

from recommend.market import MARGIN_LOW, margin_note, market_margin_ratio


def _db(tmp_path, tpex_rows_last_day=10):
    """上市 10 檔、上櫃 10 檔；20 天收盤都 100、最後一天 90；每檔融資 10 張。最後一天上櫃融資只寫 tpex_rows_last_day 檔。"""
    days = pd.bdate_range("2026-10-01", periods=21)
    uni = [{"stock_id": f"A{i}", "stock_name": f"A{i}", "exchange": "TWSE"} for i in range(10)] + \
          [{"stock_id": f"B{i}", "stock_name": f"B{i}", "exchange": "TPEx"} for i in range(10)]
    up = tmp_path / "u.csv"
    pd.DataFrame(uni).to_csv(up, index=False, encoding="utf-8-sig")
    px = pd.DataFrame([{"stock_id": u["stock_id"], "date": d, "close": 90.0 if d == days[-1] else 100.0}
                       for u in uni for d in days])
    mg = pd.DataFrame([{"stock_id": u["stock_id"], "date": d, "margin_balance": 10}
                       for u in uni for d in days
                       if not (d == days[-1] and u["exchange"] == "TPEx" and int(u["stock_id"][1:]) >= tpex_rows_last_day)])
    db = str(tmp_path / "s.db")
    con = duckdb.connect(db)
    con.execute("CREATE TABLE daily_prices AS SELECT * FROM px")
    con.execute("CREATE TABLE margin AS SELECT * FROM mg")
    con.close()
    return db, str(up), days


def test_ratio_matches_formula(tmp_path):
    db, up, days = _db(tmp_path)
    r = market_margin_ratio(days[-1].date(), db, up)
    avg = (100 * 19 + 90) / 20
    assert r["date"] == days[-1].date().isoformat()
    assert round(r["twse"], 2) == round(90 / avg / 0.6 * 100, 2) and round(r["tpex"], 2) == round(90 / avg / 0.5 * 100, 2)


def test_partial_margin_day_falls_back_to_previous_complete_day(tmp_path):
    db, up, days = _db(tmp_path, tpex_rows_last_day=2)
    assert market_margin_ratio(days[-1].date(), db, up)["date"] == days[-2].date().isoformat()


def test_note_text_and_low_warning():
    normal = {"margin_ratio": {"date": "2026-10-30", "all": 158.2}}
    low = {"margin_ratio": {"date": "2025-04-09", "all": MARGIN_LOW - 20.3}}
    assert margin_note(normal) == "大盤融資維持率(估) 158.2%（10/30）。"
    assert margin_note(normal, always=False) is None
    assert "斷頭潮" in margin_note(low, always=False) and "不是買進訊號" in margin_note(low)
    assert margin_note({}) is None and margin_note({"margin_ratio": None}) is None


def test_pages_show_ratio():
    import inspect

    import main
    from export import recommend_generator, report_generator
    from recommend import report
    assert "market_margin_ratio(day)" in inspect.getsource(main._run_and_publish)
    assert "margin_note(p)" in inspect.getsource(recommend_generator.render)
    assert "margin_note(payload, always=False)" in inspect.getsource(report.build_report)
    html = report_generator._margin_stat({"date": "2026-11-02", "all": 158.6})
    assert "融資維持率" in html and "158.6%" in html and "斷頭潮" not in html
    assert "斷頭潮" in report_generator._margin_stat({"date": "2025-04-09", "all": 129.7})
    assert report_generator._margin_stat(None) == ""
