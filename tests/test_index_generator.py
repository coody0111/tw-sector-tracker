from export.index_generator import classify_tier, classify_temp, heat_bg


def test_classify_tier_superweak_when_streak_very_negative():
    assert classify_tier(-5, 1.0, -3.0) == {"key": "superweak", "label": "超弱"}
    assert classify_tier(-8, 1.0, -3.0) == {"key": "superweak", "label": "超弱"}


def test_classify_tier_super_when_streak_positive_and_accel_strong():
    # accel = this_week(6.0) - last_week(1.0) = 5.0 > 3
    assert classify_tier(3, 1.0, 6.0) == {"key": "super", "label": "超強"}


def test_classify_tier_strong_when_streak_positive_and_accel_stable():
    # accel = 2.0 - 1.0 = 1.0，介於-2~3之間
    assert classify_tier(3, 1.0, 2.0) == {"key": "strong", "label": "強"}


def test_classify_tier_weak_when_streak_negative_and_accel_declining():
    # accel = -5.0 - (-1.0) = -4.0 < -2
    assert classify_tier(-2, -1.0, -5.0) == {"key": "weak", "label": "弱"}


def test_classify_tier_mid_as_fallback():
    # streak=0（持平），不符合任何超強/強/弱/超弱條件
    assert classify_tier(0, 1.0, 1.5) == {"key": "mid", "label": "整理"}


def test_classify_tier_returns_none_when_any_input_is_none():
    assert classify_tier(None, 1.0, 2.0) is None
    assert classify_tier(3, None, 2.0) is None
    assert classify_tier(3, 1.0, None) is None


def test_classify_tier_boundary_at_super_accel_threshold():
    """accel剛好等於_TIER_SUPER_ACCEL(3)時：>3才算super，==3不算，要落到strong
    （streak>0時strong的下限是accel>=-2，包含3.0）。"""
    assert classify_tier(3, 1.0, 4.0) == {"key": "strong", "label": "強"}  # accel=3.0剛好卡在邊界
    assert classify_tier(3, 1.0, 4.01) == {"key": "super", "label": "超強"}  # accel剛超過3才算super


def test_classify_tier_boundary_at_weak_accel_threshold_differs_by_streak_sign():
    """accel剛好等於-2時：streak>0落在strong(accel>=-2包含-2)，streak<0落到mid
    (weak要求accel<-2，嚴格小於，不含-2)——這是code review特別點名要鎖住的不對稱行為，
    避免以後有人「統一」兩個分支的比較運算子時不小心改變邊界行為。"""
    assert classify_tier(3, 1.0, -1.0) == {"key": "strong", "label": "強"}  # accel=-2.0, streak>0
    assert classify_tier(-2, 1.0, -1.0) == {"key": "mid", "label": "整理"}  # accel=-2.0, streak<0，不算weak
    assert classify_tier(-2, 1.0, -1.01) == {"key": "weak", "label": "弱"}  # accel剛小於-2才算weak


def test_classify_temp_hot_and_cold_thresholds():
    assert classify_temp(5.0) == {"key": "hot", "label": "增溫 +5.0pt", "icon": "🔥"}
    assert classify_temp(7.3) == {"key": "hot", "label": "增溫 +7.3pt", "icon": "🔥"}
    assert classify_temp(-5.0) == {"key": "cold", "label": "退燒 -5.0pt", "icon": "❄️"}
    assert classify_temp(4.9) is None  # 未達門檻
    assert classify_temp(-4.9) is None
    assert classify_temp(None) is None


def test_heat_bg_scales_alpha_by_relative_magnitude():
    up_full = heat_bg(10.0, max_abs_pct=10.0)  # t=1.0, alpha=0.66
    up_half = heat_bg(5.0, max_abs_pct=10.0)   # t=0.5, alpha=0.41
    down = heat_bg(-10.0, max_abs_pct=10.0)
    assert "var(--up)" in up_full and "66%" in up_full
    assert "var(--up)" in up_half and "41%" in up_half
    assert "var(--down)" in down


def test_heat_bg_handles_zero_max_abs_without_crash():
    """全市場今日漲跌全部剛好0%的極端情況（理論上不會發生，但不能讓除以0直接crash）。"""
    result = heat_bg(0.0, max_abs_pct=0.0)
    assert "var(--up)" in result  # pct=0視為非負，走up分支，alpha取t=0的最低值
