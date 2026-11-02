"""Telegram 查股：股號／名稱比對、精簡個股資訊、快捷指令、只回指定聊天室、offset。"""
import json

import duckdb
import pandas as pd

from notifications.stock_lookup import BUSY, HELP, find_stocks, handle


def _setup(tmp_path, days=70):
    db, uni, payload = tmp_path / "s.db", tmp_path / "u.csv", tmp_path / "p.json"
    pd.DataFrame([{"stock_id": "3147", "stock_name": "大綜", "exchange": "TPEx", "meta_sector": "雲端/系統整合"},
                  {"stock_id": "6214", "stock_name": "精誠", "exchange": "TWSE", "meta_sector": "雲端/系統整合"},
                  {"stock_id": "7819", "stock_name": "精誠金融", "exchange": "TPEx", "meta_sector": "網路服務"}]
                 ).to_csv(uni, index=False, encoding="utf-8-sig")
    d = pd.bdate_range("2026-07-01", periods=days)
    px = pd.DataFrame({"stock_id": "3147", "date": d, "close": [100.0] * (days - 1) + [110.0],
                       "change_pct": [0.0] * (days - 1) + [10.0], "volume": [1000] * (days - 1) + [3000]})
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE daily_prices AS SELECT * FROM px")
    con.execute("CREATE TABLE institutional AS SELECT '3147' AS stock_id, date, 100000 AS foreign_net, "
                "-30000 AS trust_net FROM px")
    con.execute("CREATE TABLE foreign_holdings AS SELECT '3147' AS stock_id, date, 10.0 AS foreign_pct FROM px")
    con.execute("CREATE TABLE shareholder AS SELECT '3147' AS stock_id, DATE '2026-09-25' AS date, 0.6 AS week_chg")
    con.execute("CREATE TABLE margin AS SELECT '3147' AS stock_id, date, -10 AS margin_change FROM px")
    con.execute("CREATE TABLE monthly_revenue AS SELECT '3147' AS stock_id, DATE '2026-09-01' AS revenue_month, "
                "287.9 AS reported_yoy_pct")
    con.close()
    payload.write_text(json.dumps({
        "trade_date": d[-1].date().isoformat(), "new": [{"sector": "x", "count": 1, "cards": [
            {"stock_id": "3147", "stock_name": "大綜"}]}], "active": [], "invalid": [],
        "one_word": [{"stock_id": "3147", "stock_name": "大綜", "count": 2, "streak": 2, "last_date": "2026-10-06",
                      "volume": 204}],
        "heat": {"sectors": [{"sector": "雲端/系統整合", "rank": 1}],
                 "top": [{"rank": 1, "sector": "雲端/系統整合", "score": 88.0, "ret21": 5.0, "status": "上攻中"}]}},
        ensure_ascii=False), encoding="utf-8")
    return str(db), str(uni), payload


def test_find_by_id_exact_name_and_partial():
    uni = pd.DataFrame({"stock_id": ["6214", "7819", "5278"], "stock_name": ["精誠", "精誠金融", "尚凡*"]})
    assert list(find_stocks("6214", uni)["stock_id"]) == ["6214"]
    assert list(find_stocks("精誠", uni)["stock_id"]) == ["6214"]          # 名稱完全相同優先
    assert list(find_stocks("精誠金", uni)["stock_id"]) == ["7819"]
    assert list(find_stocks("尚凡", uni)["stock_id"]) == ["5278"]          # 忽略 *


def test_card_is_title_pre_block_and_marks(tmp_path):
    """2026-11-03 排版：粗體標題、<pre> 等寬區塊（標籤對齊）、標記在最後一行。"""
    db, uni, payload = _setup(tmp_path)
    out = handle("大綜", db, uni, payload)
    lines = out.split("\n")
    assert lines[0] == "<b>3147 大綜</b>  雲端/系統整合" and lines[-1] == "標記：今日新訊號｜一字鎖 近10日2次(連2)｜族群熱度 #1"
    assert out.count("<pre>") == 1 and out.count("</pre>") == 1
    for row in ("收盤    110.00  +10.00%", "成交量      3,000 張  量比 3.0", "季線            站上",
                "法人 5 日    +350 張", "融資 5 日     −50 張", "大戶週增     +0.60pp  集保 09/25", "營收年增     +287.9%  9 月"):
        assert row in out, row


def test_card_escapes_html(tmp_path):
    db, uni, payload = _setup(tmp_path)
    u = pd.read_csv(uni, dtype=str, encoding="utf-8-sig")
    u.loc[u["stock_id"] == "3147", "stock_name"] = "大<綜>"
    u.to_csv(uni, index=False, encoding="utf-8-sig")
    out = handle("3147", db, uni, payload)
    assert "大&lt;綜&gt;" in out and "大<綜>" not in out


def test_ambiguous_and_not_found(tmp_path):
    db, uni, payload = _setup(tmp_path)
    assert handle("精誠", db, uni, payload).startswith("<b>6214 精誠</b>")       # 名稱完全相同，不列候選
    assert handle("精", db, uni, payload).startswith("有 2 檔符合，請打股號：6214 精誠、7819 精誠金融")
    assert handle("xyz", db, uni, payload) == f"找不到「xyz」。\n{HELP}"


def test_db_locked_returns_busy(tmp_path, monkeypatch):
    db, uni, payload = _setup(tmp_path)

    def locked(*a, **k):
        raise duckdb.IOException("Could not set lock")
    monkeypatch.setattr("notifications.stock_lookup.duckdb.connect", locked)
    assert handle("3147", db, uni, payload) == BUSY


def test_commands(tmp_path):
    db, uni, payload = _setup(tmp_path)
    rec = handle("/推薦", db, uni, payload)
    assert "<pre>股號   名稱       族群" in rec and "新訊號 1｜仍有效 0｜已失效 0" in rec
    assert "3147   大綜     10/06  2  2     204" in handle("一字鎖", db, uni, payload)
    assert " 1 雲端/系統整合    88   +5.0% 上攻中" in handle("/熱度", db, uni, payload)
    assert "report.html" in handle("/報告", db, uni, payload) and "weekly.html" in handle("/報告", db, uni, payload)
    assert handle("/start", db, uni, payload) == HELP and handle("  ", db, uni, payload) == HELP


def test_bot_only_replies_to_configured_chat(monkeypatch, tmp_path):
    import scripts.telegram_bot as bot
    monkeypatch.setattr(bot, "handle", lambda text: f"答:{text}")
    monkeypatch.setattr(bot, "OFFSET_PATH", tmp_path / "o.txt")
    monkeypatch.setattr(bot, "save_offset", lambda o, path=tmp_path / "o.txt": path.write_text(str(o)))
    updates = [{"update_id": 10, "message": {"chat": {"id": 999}, "text": "3147"}},
               {"update_id": 11, "message": {"chat": {"id": 123}, "text": "3147"}},
               {"update_id": 12, "message": {"chat": {"id": 123}}}]

    class Resp:
        status_code = 200

        def json(self):
            return {"result": updates}
    sent = []
    offset = bot.poll_once("T", "123", 0, send=lambda text, chat_id, parse_mode=None: sent.append((text, chat_id, parse_mode)), get=lambda *a, **k: Resp())
    assert sent == [("答:3147", "123", "HTML")] and offset == 13 and (tmp_path / "o.txt").read_text() == "13"


def test_bot_reply_error_is_caught(monkeypatch):
    import scripts.telegram_bot as bot
    monkeypatch.setattr(bot, "handle", lambda text: 1 / 0)
    assert bot.reply_for({"message": {"chat": {"id": 1}, "text": "x"}}, "1") == "查詢失敗，請稍後再試。"


def test_offset_roundtrip(tmp_path):
    import scripts.telegram_bot as bot
    p = tmp_path / "o.txt"
    assert bot.read_offset(p) == 0
    bot.save_offset(42, p)
    assert bot.read_offset(p) == 42


def test_chips_use_trading_day_window_not_last_rows(tmp_path):
    """institutional 只存有買賣超的日子：5 日要用交易日窗口，不能加最近 5 筆（bug-reports 2026-11-02）。"""
    db, uni, payload = _setup(tmp_path)
    con = duckdb.connect(db)
    con.execute("DELETE FROM institutional")
    days = [r[0] for r in con.execute("SELECT DISTINCT date FROM daily_prices ORDER BY date DESC").fetchall()]
    con.execute("INSERT INTO institutional VALUES ('3147', ?, 1000, 0), ('3147', ?, 5000, 0), ('3147', ?, 7000, 0)",
                [days[0], days[4], days[8]])                     # 第 9 個交易日前那筆不能算進來
    con.execute("INSERT INTO institutional VALUES ('6214', ?, 0, 0)", [days[0]])
    con.close()
    assert "法人 5 日      +6 張" in handle("3147", db, uni, payload)
