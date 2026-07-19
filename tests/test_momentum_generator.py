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
