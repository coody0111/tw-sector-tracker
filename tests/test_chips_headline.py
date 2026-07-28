from export.chips_headline import build_candidate_cards, render_headline_zone


def test_build_candidate_cards_uses_rank_joint_buy_candidates_output():
    """候選觀察卡片必須是rank_joint_buy_candidates()的輸出前3名，不是重新排序。"""
    from screener.institutional import rank_joint_buy_candidates
    inst_scan = [
        {"stock_id": "2317", "stock_name": "鴻海", "meta_sector": "AI伺服器",
         "close": 257.0, "change_pct": 2.4, "foreign_streak": 5, "trust_streak": 3,
         "both_streak": 3, "foreign_net": 24000000, "trust_net": 559000,
         "total_net": 25000000, "institutional_flow_ratio_pct": 39.3,
         "price_cum_pct": 8.5, "volume": 50000},
        {"stock_id": "8114", "stock_name": "振樺電", "meta_sector": "工業電腦",
         "close": 232.0, "change_pct": 5.0, "foreign_streak": 4, "trust_streak": 2,
         "both_streak": 2, "foreign_net": 390000, "trust_net": 108000,
         "total_net": 497000, "institutional_flow_ratio_pct": 12.4,
         "price_cum_pct": 6.2, "volume": 8000},
    ]
    expected = rank_joint_buy_candidates(inst_scan, limit=3)

    cards = build_candidate_cards(inst_scan, limit=3)

    assert [c["stock_id"] for c in cards] == [r["stock_id"] for r in expected]


def test_build_candidate_cards_returns_empty_list_when_no_candidates():
    assert build_candidate_cards([], limit=3) == []


def test_render_headline_zone_includes_disclosure_text():
    """誠實揭露文案是強制要求(Global Constraints)，不能被省略。"""
    html = render_headline_zone(candidate_cards=[], holder_focus=[])
    assert "不是投資建議" in html
    assert "尚未完成" in html or "未完成" in html


def test_render_headline_zone_shows_empty_state_when_no_candidates():
    """今天沒有符合條件的候選時，顯示誠實的空狀態文字，不是留空白區塊。"""
    html = render_headline_zone(candidate_cards=[], holder_focus=[])
    assert "無符合條件" in html or "今日無" in html


def test_render_headline_zone_escapes_malicious_stock_name():
    html = render_headline_zone(
        candidate_cards=[{
            "stock_id": "9999", "stock_name": "<script>alert(1)</script>",
            "meta_sector": "測試", "close": 10.0, "change_pct": 1.0,
            "both_streak": 3, "institutional_flow_ratio_pct": 5.0,
            "price_cum_pct": 3.0, "total_net": 1000,
        }],
        holder_focus=[],
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
