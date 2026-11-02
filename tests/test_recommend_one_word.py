"""推薦頁「一字鎖」：近 10 個交易日清單、連續天數、卡片提醒、頁面區塊、Telegram 一行。"""
import pandas as pd

from export.recommend_generator import render
from recommend.daily import build_payload
from recommend.one_word import locked_keys, one_word_list
from recommend.telegram_format import one_word_line, compose_recommend_message
from tests.test_recommend_daily import _FakeStrategy, _feat
from tests.test_recommend_page import _payload as _page_payload
from tests.test_recommend_telegram import _payload as _tg_payload


def _locked(f, d, sid, idx):
    """把 sid 在 d[idx] 那些天標成一字鎖。"""
    days = {d[i] for i in idx}
    return f.assign(one_word=f["one_word"] | ((f["stock_id"] == sid) & f["date"].isin(days)))


def test_list_counts_streak_and_orders_by_last_date():
    f, d = _feat()
    f = _locked(_locked(f, d, "A", [-12, -4, -3, -2]), d, "B", [-1])     # A 的 d[-12] 在 10 日外
    rows = one_word_list(f, d[-1])
    assert [r["stock_id"] for r in rows] == ["B", "A"]
    a = rows[1]
    assert (a["count"], a["streak"], a["last_date"], a["today"]) == (3, 3, d[-2].date().isoformat(), False)
    assert rows[0]["today"] is True and rows[0]["volume"] == 1000 and rows[0]["turnover20"] == 0.99   # 1000 張，18 天 100 元＋2 天 90 元


def test_streak_breaks_on_gap():
    f, d = _feat()
    rows = one_word_list(_locked(f, d, "A", [-5, -3, -2]), d[-1])
    assert (rows[0]["count"], rows[0]["streak"]) == (3, 2)


def test_no_lock_gives_empty_list():
    f, d = _feat()
    assert one_word_list(f, d[-1]) == [] and locked_keys(f, d[-1]) == set()


def test_card_alert_when_locked_on_signal_day_or_today(monkeypatch):
    f, d = _feat()
    f = _locked(_locked(f, d, "C", [-1]), d, "A", [-3])
    monkeypatch.setattr("recommend.daily.ALL_STRATEGIES", [_FakeStrategy([("C", d[-1]), ("A", d[-3])])])
    p = build_payload(f, d[-1])
    alerts = {c["stock_id"]: c["alerts"] for c in p["new"][0]["cards"] + p["active"]}
    assert "一字鎖" in alerts["C"] and "一字鎖" in alerts["A"]
    assert {r["stock_id"] for r in p["one_word"]} == {"A", "C"}


def test_card_without_lock_has_no_alert(monkeypatch):
    f, d = _feat()
    monkeypatch.setattr("recommend.daily.ALL_STRATEGIES", [_FakeStrategy([("C", d[-1])])])
    p = build_payload(f, d[-1])
    assert "一字鎖" not in p["new"][0]["cards"][0]["alerts"] and p["one_word"] == []


def _row(sid, name, **kw):
    r = {"stock_id": sid, "stock_name": name, "meta_sector": "軟體/雲端", "count": 2, "streak": 2,
         "last_date": "2026-11-02", "today": True, "volume": 204, "close": 85.9, "turnover20": 0.03}
    return {**r, **kw}


def test_page_section_lists_rows_and_escapes():
    html = render(_page_payload(one_word=[_row("8272", "全景<軟體>"), _row("8099", "大世科", today=False, last_date="2026-10-28")]))
    assert "一字鎖" in html and "全景<軟體>" not in html and "全景&lt;軟體&gt;" in html
    assert "10/28" in html and "不是策略訊號" in html
    assert html.index('id="new-h"') < html.index('id="lock-h"') < html.index('id="active-h"')


def test_page_without_one_word_shows_empty_state():
    assert "近 10 個交易日沒有一字鎖" in render(_page_payload())          # 舊 payload 沒有 one_word 也能產


def test_telegram_line_today_streak_and_none_today():
    assert one_word_line({"one_word": [_row("8272", "全景軟體"), _row("6865", "偉康科技", streak=1, count=1)]}) \
        == "一字鎖：全景軟體(連2)、偉康科技"
    assert one_word_line({"one_word": [_row("8099", "大世科", today=False)]}) == "一字鎖：今天沒有（近 10 日 1 檔見頁面）"
    assert one_word_line({}) is None


def test_telegram_message_includes_escaped_line():
    p = {**_tg_payload(3), "one_word": [_row("8272", "全景<軟體>")]}
    msg = compose_recommend_message(p, taiex_above_ma20=True, site_url="https://x/recommend.html")
    assert "一字鎖：全景&lt;軟體&gt;(連2)" in msg


def test_report_message_includes_line():
    from recommend.telegram_format import compose_report_message
    report = {"date": "2026-11-02", "tone": "偏空", "points": ["加權跌 2%。"]}
    msg = compose_report_message(report, "https://x/report.html", {"one_word": [_row("8272", "全景<軟體>")]})
    assert msg.index("加權跌 2%。") < msg.index("一字鎖：全景&lt;軟體&gt;(連2)") < msg.index("報告：")
    assert "一字鎖" not in compose_report_message(report, "https://x/report.html")


def test_scheduler_passes_payload_to_report_message(monkeypatch):
    import scripts.run_scheduled as sr
    sent = []
    monkeypatch.setattr(sr, "send_telegram_message", lambda msg, **k: sent.append(msg))
    rec = {"report": {"date": "2026-11-02", "points": ["重點"]}, "one_word": [_row("8272", "全景軟體")]}
    sr.send_recommend_message({"recommend": rec}, "https://x/")
    assert "一字鎖：全景軟體(連2)" in sent[0]
