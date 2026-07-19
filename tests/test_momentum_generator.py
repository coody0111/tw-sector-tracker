from export.momentum_generator import (
    rs_sample_confidence, market_permission, classify_sector_state, build_sector_priority,
)


def test_rs_sample_confidence_tiers():
    assert rs_sample_confidence(10) == "A"
    assert rs_sample_confidence(15) == "A"
    assert rs_sample_confidence(9) == "B"
    assert rs_sample_confidence(5) == "B"
    assert rs_sample_confidence(4) == "C"
    assert rs_sample_confidence(0) == "C"


def test_market_permission_normal_for_up_tiers():
    regime = {"tier": "大漲", "taiex_change_pct": 2.1, "breadth_ratio": 0.72, "concentration_direction": None}
    result = market_permission(regime, index_date="2026-07-19", price_date="2026-07-19")
    assert result["permission"] == "normal"
    assert result["tier_text"] == "大漲"
    assert result["divergence_text"] == ""


def test_market_permission_defensive_for_down_tiers():
    regime = {"tier": "大跌", "taiex_change_pct": -2.3, "breadth_ratio": 0.22, "concentration_direction": None}
    result = market_permission(regime, index_date="2026-07-19", price_date="2026-07-19")
    assert result["permission"] == "defensive"
    assert "反手放空" not in result["advice_text"]
    assert "立刻砍" not in result["advice_text"]


def test_market_permission_selective_for_flat_tier_no_divergence():
    regime = {"tier": "持平", "taiex_change_pct": 0.1, "breadth_ratio": 0.48, "concentration_direction": None}
    result = market_permission(regime, index_date="2026-07-19", price_date="2026-07-19")
    assert result["permission"] == "selective"
    assert result["divergence_text"] == ""


def test_market_permission_shows_divergence_text_when_index_directional_but_flat_tier():
    """指數有方向(+1.8%)但廣度不足(42%)導致 classify_market_regime 降級成「持平」時，
    必須額外顯示背離原因，不能簡化成一般持平（spec §2.1）。"""
    regime = {"tier": "持平", "taiex_change_pct": 1.8, "breadth_ratio": 0.42, "concentration_direction": None}
    result = market_permission(regime, index_date="2026-07-19", price_date="2026-07-19")
    assert result["permission"] == "selective"
    assert "上漲" in result["divergence_text"]
    assert "42%" in result["divergence_text"]


def test_market_permission_includes_concentration_direction_when_present():
    regime = {"tier": "小漲", "taiex_change_pct": 0.5, "breadth_ratio": 0.55, "concentration_direction": "權值股撐盤"}
    result = market_permission(regime, index_date="2026-07-19", price_date="2026-07-19")
    assert "權值股撐盤" in result["divergence_text"]


def test_market_permission_unknown_when_dates_mismatch():
    """指數資料日期與個股行情日期不同時，降級unknown，不輸出市場操作文案（spec §2.1）。"""
    regime = {"tier": "大漲", "taiex_change_pct": 2.0, "breadth_ratio": 0.7, "concentration_direction": None}
    result = market_permission(regime, index_date="2026-07-18", price_date="2026-07-19")
    assert result["permission"] == "unknown"
    assert result["advice_text"] == ""


def test_market_permission_skips_date_check_when_dates_not_provided():
    """呼叫端沒傳日期時（例如舊呼叫路徑），不做日期檢查，直接照 tier 判斷（向後相容）。"""
    regime = {"tier": "大漲", "taiex_change_pct": 2.0, "breadth_ratio": 0.7, "concentration_direction": None}
    result = market_permission(regime)
    assert result["permission"] == "normal"


def test_classify_sector_state_zhusheng_when_high_score_and_broad():
    data = {"observation_score": 80.0, "breadth_raw": 0.7, "continuation_raw": 4, "rs_raw": 3.0}
    assert classify_sector_state(data) == "主升"


def test_classify_sector_state_zhuanqiang_when_high_score_but_narrow():
    data = {"observation_score": 55.0, "breadth_raw": 0.3, "continuation_raw": 1, "rs_raw": 1.0}
    assert classify_sector_state(data) == "轉強"


def test_classify_sector_state_jitan_when_positive_rs_but_no_continuation():
    data = {"observation_score": 30.0, "breadth_raw": 0.4, "continuation_raw": 0, "rs_raw": 2.0}
    assert classify_sector_state(data) == "急彈"


def test_classify_sector_state_zhuanruo_when_negative_rs():
    data = {"observation_score": 20.0, "breadth_raw": 0.3, "continuation_raw": 0, "rs_raw": -1.5}
    assert classify_sector_state(data) == "轉弱"


def test_classify_sector_state_wait_when_score_none():
    data = {"observation_score": None, "breadth_raw": None, "continuation_raw": None, "rs_raw": None}
    assert classify_sector_state(data) == "等待確認"


def test_build_sector_priority_sorts_desc_and_limits_top_n():
    observation_scores = {
        "記憶體": {"observation_score": 82.0, "score_coverage": 1.0, "rs_raw": 4.1, "breadth_raw": 0.8,
                  "continuation_raw": 3, "volume_raw": 1.6, "chips_raw": 0.7, "partial_coverage": False},
        "航運": {"observation_score": 55.0, "score_coverage": 1.0, "rs_raw": 1.2, "breadth_raw": 0.6,
                "continuation_raw": 1, "volume_raw": 1.1, "chips_raw": 0.5, "partial_coverage": False},
        "金融": {"observation_score": 20.0, "score_coverage": 0.9, "rs_raw": -1.0, "breadth_raw": 0.2,
                "continuation_raw": 0, "volume_raw": 0.8, "chips_raw": None, "partial_coverage": True},
    }
    result = build_sector_priority(observation_scores, top_n=2)

    assert len(result) == 2
    assert result[0]["meta_name"] == "記憶體"
    assert result[0]["rank"] == 1
    assert result[1]["meta_name"] == "航運"
    assert result[1]["rank"] == 2


def test_build_sector_priority_none_score_sorts_last():
    observation_scores = {
        "A": {"observation_score": 10.0, "score_coverage": 1.0, "rs_raw": None, "breadth_raw": None,
              "continuation_raw": None, "volume_raw": None, "chips_raw": None, "partial_coverage": False},
        "B": {"observation_score": None, "score_coverage": 0.0, "rs_raw": None, "breadth_raw": None,
              "continuation_raw": None, "volume_raw": None, "chips_raw": None, "partial_coverage": False},
    }
    result = build_sector_priority(observation_scores, top_n=5)
    assert [r["meta_name"] for r in result] == ["A", "B"]


from export.momentum_generator import determine_final_label, build_decision_table


def _base_stock_row(**overrides):
    row = {
        "stock_id": "2330", "stock_name": "台積電", "meta_sector": "半導體",
        "close": 900.0, "change_pct": 2.0, "ma5": 890.0, "ma10": 870.0, "ma20": 850.0, "ma60": 800.0,
        "ma_alignment": "多頭排列", "ma5_slope_down": False, "below_ma5": False, "big_black_proxy": False,
        "ma5_rising": True, "ma10_rising": True, "exit_3_rule_triggered": False, "entry_confirmed": True,
        "rs_score": 3.0, "rs_rank_pct": 0.9, "rs_market_score": 4.0, "rs_sample_count": 12,
        "daily_excess_pct": 1.5, "strength_tier": "超強",
    }
    row.update(overrides)
    return row


def test_determine_final_label_limit_down_takes_top_priority():
    """跌停風險優先權最高：即使同時符合出場條件命中，也只顯示跌停風險（流動性風險最急迫）。"""
    row = _base_stock_row(change_pct=-9.6, exit_3_rule_triggered=True, strength_tier="超弱")
    label = determine_final_label(row, "defensive", "轉弱", {})
    assert label == "跌停風險"


def test_determine_final_label_exit_condition_hit():
    row = _base_stock_row(change_pct=-5.0, exit_3_rule_triggered=True, strength_tier="超弱")
    label = determine_final_label(row, "normal", "主升", {})
    assert label == "出場條件命中"


def test_determine_final_label_entry_candidate_when_all_gates_pass():
    row = _base_stock_row()
    bullish_map = {"2330": {"stock_id": "2330", "volume_confirmed": True}}
    label = determine_final_label(row, "normal", "主升", bullish_map)
    assert label == "進場候選"


def test_determine_final_label_blocked_by_low_rs_confidence():
    """RS樣本信心是C（<5檔）時，即使其他閘門都成立，也不能升級成進場候選（spec §3.2/§3.4）。"""
    row = _base_stock_row(rs_sample_count=3)
    bullish_map = {"2330": {"stock_id": "2330", "volume_confirmed": True}}
    label = determine_final_label(row, "normal", "主升", bullish_map)
    assert label != "進場候選"
    assert label == "續強觀察"


def test_determine_final_label_blocked_by_missing_volume_confirmed():
    row = _base_stock_row()
    bullish_map = {"2330": {"stock_id": "2330", "volume_confirmed": False}}
    label = determine_final_label(row, "normal", "主升", bullish_map)
    assert label != "進場候選"


def test_determine_final_label_blocked_when_not_in_bullish_new_high_list():
    row = _base_stock_row()
    label = determine_final_label(row, "normal", "主升", {})  # 2330不在B3清單
    assert label != "進場候選"


def test_determine_final_label_blocked_when_market_defensive():
    row = _base_stock_row()
    bullish_map = {"2330": {"stock_id": "2330", "volume_confirmed": True}}
    label = determine_final_label(row, "defensive", "主升", bullish_map)
    assert label == "風險升高"


def test_determine_final_label_risk_elevated_for_weak_tier():
    row = _base_stock_row(strength_tier="弱", ma_alignment="空頭排列", entry_confirmed=False)
    label = determine_final_label(row, "normal", "轉弱", {})
    assert label == "風險升高"


def test_determine_final_label_risk_elevated_for_superweak_without_exit_trigger():
    """超弱(strength_tier)但exit_3_rule_triggered=False時（例如未來呼叫端資料組成方式改變，
    不再保證兩者一定同時成立）仍要被分類成風險升高，不能悄悄落到最中性的等待確認
    （這是code review抓到的邊界情況：determine_final_label()本身不應該依賴
    screener/signals.py目前「超弱一定伴隨exit_3_rule_triggered=True」這個外部巧合）。"""
    row = _base_stock_row(strength_tier="超弱", exit_3_rule_triggered=False, entry_confirmed=False)
    label = determine_final_label(row, "normal", "轉弱", {})
    assert label == "風險升高"


def test_determine_final_label_continued_strength_watch_when_gate_incomplete():
    """超強/強但進場閘門不完整（例如不在B3清單）時，顯示續強觀察，不是進場候選。"""
    row = _base_stock_row(strength_tier="強")
    label = determine_final_label(row, "normal", "轉強", {})
    assert label == "續強觀察"


def test_determine_final_label_wait_for_confirmation_default():
    row = _base_stock_row(strength_tier="整理", ma_alignment="糾結", entry_confirmed=False, rs_rank_pct=None)
    label = determine_final_label(row, "selective", "等待確認", {})
    assert label == "等待確認"


def test_build_decision_table_groups_by_sector_strength_and_sorts():
    momentum_results = [
        _base_stock_row(stock_id="2330", stock_name="台積電", meta_sector="半導體", rs_rank_pct=0.9, strength_tier="超強"),
        _base_stock_row(stock_id="2454", stock_name="聯發科", meta_sector="半導體", rs_rank_pct=0.5, strength_tier="強"),
        _base_stock_row(stock_id="2603", stock_name="長榮", meta_sector="航運", rs_rank_pct=0.3, strength_tier="整理", ma_alignment="糾結"),
    ]
    sector_states = {"半導體": "主升", "航運": "等待確認"}
    table = build_decision_table(momentum_results, [], "normal", sector_states)

    ids = [r["stock_id"] for r in table]
    assert ids == ["2330", "2454", "2603"]  # 半導體(較強族群)優先，組內2330>2454
    assert table[0]["sector_state"] == "主升"
    assert table[0]["rs_confidence"] == "A"  # rs_sample_count=12


def test_build_decision_table_includes_entry_and_exit_evidence():
    momentum_results = [_base_stock_row()]
    bullish_results = [{"stock_id": "2330", "stock_name": "台積電", "meta_sector": "半導體",
                         "close": 900.0, "change_pct": 2.0, "ma5": 890.0, "ma10": 870.0, "ma60": 800.0,
                         "lookback_days": 60, "volume_ratio_20d": 1.8, "volume_confirmed": True}]
    sector_states = {"半導體": "主升"}
    table = build_decision_table(momentum_results, bullish_results, "normal", sector_states)

    row = table[0]
    assert row["final_label"] == "進場候選"
    assert ("多頭排列＋創新高（B3清單內）", True) in row["entry_evidence"]
    assert ("量能確認（B3量比≥1.5）", True) in row["entry_evidence"]
    assert ("跌破五日線", False) in row["exit_evidence"]


def test_build_decision_table_defaults_to_wait_for_confirmation_when_sector_missing_from_states():
    """momentum_results裡的股票所屬族群沒有出現在sector_states dict時（例如新族群還沒被
    calc_meta_observation_scores()算過），sector_state要保守預設為等待確認，不能crash
    或誤判成主升/轉強讓它意外通過進場閘門。"""
    momentum_results = [
        _base_stock_row(stock_id="9999", stock_name="新族群股", meta_sector="新族群"),
    ]
    table = build_decision_table(momentum_results, [], "normal", {})  # sector_states為空dict

    assert table[0]["sector_state"] == "等待確認"
    assert table[0]["final_label"] != "進場候選"  # 等待確認不在entry_gate允許的{主升,轉強}內


from export.momentum_generator import selloff_risk_zone, build_streak_cards


def test_selloff_risk_zone_uses_daily_excess_pct_not_rs_market_score():
    """關鍵回歸：急殺風險區必須用daily_excess_pct（單日抗跌），不能誤用5日rs_market_score
    （v2 spec §3.1 明訂，這是舊plan犯過的錯）。這檔股票今日抗跌(daily_excess_pct>0)但
    5日相對大盤是負的(rs_market_score<0)，應該被列入抗跌候選。"""
    momentum_results = [
        {"stock_id": "2609", "stock_name": "陽明", "meta_sector": "航運",
         "change_pct": -0.5, "daily_excess_pct": 1.2, "rs_market_score": -2.0},
    ]
    result = selloff_risk_zone(momentum_results)
    assert [r["stock_id"] for r in result["resilient"]] == ["2609"]


def test_selloff_risk_zone_splits_resilient_and_limit_down():
    momentum_results = [
        {"stock_id": "2609", "stock_name": "陽明", "meta_sector": "航運",
         "change_pct": 1.2, "daily_excess_pct": 3.0, "rs_market_score": 1.0},
        {"stock_id": "2617", "stock_name": "台航", "meta_sector": "航運",
         "change_pct": -0.4, "daily_excess_pct": 1.4, "rs_market_score": 0.5},
        {"stock_id": "2023", "stock_name": "燁輝", "meta_sector": "鋼鐵",
         "change_pct": -9.7, "daily_excess_pct": -8.0, "rs_market_score": -7.0},
        {"stock_id": "9999", "stock_name": "無關股", "meta_sector": "其他",
         "change_pct": -1.0, "daily_excess_pct": -0.5, "rs_market_score": -0.2},
    ]
    result = selloff_risk_zone(momentum_results)

    resilient_ids = [r["stock_id"] for r in result["resilient"]]
    limit_down_ids = [r["stock_id"] for r in result["limit_down"]]
    assert resilient_ids == ["2609", "2617"]  # daily_excess_pct>0，依分數降冪
    assert limit_down_ids == ["2023"]
    assert "9999" not in resilient_ids and "9999" not in limit_down_ids


def test_selloff_risk_zone_limit_down_takes_precedence_over_resilient():
    momentum_results = [
        {"stock_id": "1111", "stock_name": "極端股", "meta_sector": "測試",
         "change_pct": -9.6, "daily_excess_pct": 2.0, "rs_market_score": 3.0},
    ]
    result = selloff_risk_zone(momentum_results)
    assert [r["stock_id"] for r in result["limit_down"]] == ["1111"]
    assert result["resilient"] == []


def test_build_streak_cards_carries_breakout_volume_confirmed():
    limit_up_results = [
        {"stock_id": "6770", "stock_name": "力積電", "meta_sector": "半導體", "close": 50.0,
         "change_pct": 9.8, "volume": 100000, "limit_up_streak": 4,
         "volume_declining_streak": True, "breakout_volume_confirmed": True},
        {"stock_id": "1560", "stock_name": "中砂", "meta_sector": "工具機", "close": 80.0,
         "change_pct": 9.9, "volume": 50000, "limit_up_streak": 3,
         "volume_declining_streak": True, "breakout_volume_confirmed": False},
    ]
    cards = build_streak_cards(limit_up_results)

    assert cards[0]["stock_id"] == "6770"
    assert cards[0]["breakout_volume_confirmed"] is True
    assert cards[1]["breakout_volume_confirmed"] is False
