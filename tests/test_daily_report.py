"""每日報告：多空判定、今日重點、暫定發布期限、頁面與 Telegram。"""
import inspect
from datetime import date, datetime

from export.report_generator import generate, render
from recommend.publish import past_deadline
from recommend.report import build_report, market_tone
from recommend.telegram_format import compose_report_message

CHIPS = {"foreign": -1080.0, "trust": 232.0, "margin_change": -115364,
         "buy": [{"sector": "電信", "net": 19.3}], "sell": [{"sector": "晶圓代工", "net": -213.3}, {"sector": "AI晶片", "net": -105.9}]}


def _card(day_n=1):
    return {"stock_id": "2330", "stock_name": "台積電", "meta_sector": "晶圓代工", "type": "整理", "close": 100.0,
            "signal_date": "2026-10-28", "since_signal_pct": 5.0, "alerts": ["乖離大"], "day_n": day_n}


def _payload(**kw):
    return {"trade_date": "2026-10-30", "new": [], "active": [], "invalid": [], "taiex_above_ma20": False, "taiex_close": 45211.83,
            "taiex_change": -1156.5, "taiex_change_pct": -2.49, "taiex_ma20_gap": -0.053,
            "header": {"above_ma20_pct": 0.138, "limit_up": 12, "limit_down": 18, "fail_rate": 0.82, "fail_n": 22},
            "heat": {"top": [], "sectors": []}, **kw}


def test_market_tone_rule():
    assert market_tone(True, 0.5) == "偏多"
    assert market_tone(False, 0.49) == "偏空"
    assert market_tone(True, 0.3) == "中性" and market_tone(False, 0.6) == "中性"
    assert market_tone(None, 0.6) is None and market_tone(True, None) is None


def test_points_use_same_numbers_as_tables():
    r = build_report(_payload(), CHIPS)
    assert r["title"] == "大盤偏空，今天沒有新訊號"
    assert r["points"][0] == "加權 45,211.83，跌 2.49%，低於 20 日線 5.3%。13.8% 的股票站上 20 日線。"
    assert r["points"][1] == "外資賣超 1,080 億，投信買超 232 億。賣壓集中在晶圓代工、AI晶片。"
    assert r["points"][2] == "新訊號 0 檔，有效中 0 檔。近期突破失敗率 82%（22 筆）。"


def test_missing_chips_still_builds_report():
    r = build_report(_payload(), None)
    assert len(r["points"]) == 2
    assert "籌碼資料未到" in render(r, ["2026-10-30"])


def test_provisional_is_labelled():
    r = build_report(_payload(missing=["上市外資持股"]), CHIPS)
    assert "暫定：缺上市外資持股" in render(r, ["2026-10-30"])
    assert "暫定：缺上市外資持股，資料到齊後更新" in compose_report_message(r, "https://x/report.html")
    assert any("暫定" in x for x in r["watch"])


def test_last_valid_day_goes_to_watch():
    r = build_report(_payload(active=[_card(day_n=3)]), CHIPS)
    assert "台積電 已是第 3 天，下個交易日起不再列入有效名單。" in r["watch"]


def test_deadline_is_night_before_next_trading_day():
    is_td = lambda d: date.fromisoformat(d).weekday() < 5
    tue, fri = date(2026, 10, 27), date(2026, 10, 30)
    assert not past_deadline(datetime(2026, 10, 27, 23, 30), tue, is_td)
    assert past_deadline(datetime(2026, 10, 27, 23, 45), tue, is_td)
    assert not past_deadline(datetime(2026, 10, 31, 23, 45), fri, is_td)      # 週五的期限是週日晚上
    assert past_deadline(datetime(2026, 11, 1, 23, 45), fri, is_td)


def test_escapes_and_archive(tmp_path):
    r = build_report(_payload(new=[{"cards": [{**_card(), "stock_name": "<b>x"}]}]), CHIPS)
    latest, folder = tmp_path / "report.html", tmp_path / "reports"
    generate(r, str(latest), str(folder))
    assert "<b>x" not in latest.read_text(encoding="utf-8")
    assert '<base href="../">' in (folder / "2026-10-30.html").read_text(encoding="utf-8")
    assert '<base href' not in latest.read_text(encoding="utf-8")
    assert (folder / "index.json").read_text(encoding="utf-8") == '["2026-10-30"]'


def test_publish_wiring():
    import main
    source = inspect.getsource(main.publish_recommend)
    assert "past_deadline(datetime.now(), day, is_trading_day)" in source
    assert 'prev.get("missing") == waiting' in source
    assert '"docs/reports"' in inspect.getsource(main._push_html)
