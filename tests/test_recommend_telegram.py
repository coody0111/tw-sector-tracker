from recommend.telegram_format import compose_recommend_message


def _card(sid, sector, alerts=()):
    return {"stock_id": sid, "stock_name": "名<稱>", "meta_sector": sector, "type": "整理", "n_routes": 3,
            "close": 337.5, "change_pct": 10.0, "alerts": list(alerts)}


def _payload(n_new):
    cards = [_card(f"{1000 + k}", "銅箔基板" if k < 2 else "散熱", ["乖離大"] if k == 2 else []) for k in range(n_new)]
    groups = [{"sector": "銅箔基板", "count": 2, "cards": cards[:2]},
              {"sector": "散熱", "count": n_new - 2, "cards": cards[2:]}]
    return {"trade_date": "2026-10-22",
            "header": {"above_ma20_pct": 0.61, "fail_rate": 0.33, "limit_up": 18, "limit_down": 3},
            "new": groups, "active": [{}] * 4, "invalid": [{}] * 2}


def test_message_has_table_groups_and_escaping():
    msg = compose_recommend_message(_payload(3), taiex_above_ma20=True, site_url="https://x/recommend.html")
    assert msg.startswith("個股推薦 10/22 收盤")
    assert "MA20上 61%｜失敗率 33%｜加權&gt;MA20｜漲停 18 跌停 3" in msg
    assert "<pre>" in msg and "[銅箔基板 2檔]" in msg and "[散熱 1檔]" in msg
    assert "乖離大" in msg and "名&lt;稱&gt;" in msg
    assert "新 3 檔｜有效中 4 檔｜失效 2 檔" in msg and msg.rstrip().endswith("https://x/recommend.html")
    assert "點火" not in msg


def test_message_truncates_after_fifteen():
    msg = compose_recommend_message(_payload(20), taiex_above_ma20=None, site_url="u")
    assert "另 5 檔見頁面" in msg and "加權" not in msg


def test_none_change_pct_and_columns_align_by_display_width():
    from recommend.telegram_format import _width
    p = _payload(3)
    p["new"][1]["cards"][0]["change_pct"] = None
    msg = compose_recommend_message(p, taiex_above_ma20=None, site_url="u")
    table = msg.split("<pre>")[1].split("</pre>")[0]
    rows = [r for r in table.split("\n") if r[:1].isdigit() or r.startswith("股號")]
    starts = {r[:r.index("名&lt;") if "名&lt;" in r else r.index("名稱")] for r in rows}
    assert len({_width(s.replace("&lt;", "<")) for s in starts}) == 1    # 名稱欄起點的顯示寬度都一樣
    assert "—" in table


def test_solo_alert_is_shortened_and_keeps_alignment():
    from recommend.telegram_format import _width
    p = _payload(3)
    p["new"][1]["cards"][0]["alerts"] = ["族群獨漲"]
    table = compose_recommend_message(p, taiex_above_ma20=None, site_url="u").split("<pre>")[1].split("</pre>")[0]
    assert "獨漲" in table and "族群獨漲" not in table
    rows = [r for r in table.split("\n") if r[:1].isdigit() or r.startswith("股號")]
    starts = {r[:r.index("名&lt;") if "名&lt;" in r else r.index("名稱")] for r in rows}
    assert len({_width(s.replace("&lt;", "<")) for s in starts}) == 1
