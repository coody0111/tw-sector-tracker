import pandas as pd

from export.index_generator import classify_tier, classify_temp, heat_bg, build_stock_detail_data


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
    assert classify_temp(5.0) == {"key": "hot", "label": "增溫 +5.0pt"}
    assert classify_temp(7.3) == {"key": "hot", "label": "增溫 +7.3pt"}
    assert classify_temp(-5.0) == {"key": "cold", "label": "退燒 -5.0pt"}
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


from export.index_generator import find_turning_points, find_anomaly_cards


def test_find_turning_points_detects_flip_and_labels_direction():
    heatgrid_windows = {
        "族群A": {  # 5天前弱(streak<0,accel<-2)，今天超強(streak>0,accel>3)
            "streak_today": 3, "last_week_pct_today": 1.0, "this_week_pct_today": 6.0,
            "streak_5d_ago": -2, "last_week_pct_5d_ago": 3.5,
        },
        "族群B": {  # 5天前強，今天弱
            "streak_today": -2, "last_week_pct_today": -1.0, "this_week_pct_today": -5.0,
            "streak_5d_ago": 3, "last_week_pct_5d_ago": -0.5,
        },
        "族群C": {  # 前後都整理(mid)，沒變化
            "streak_today": 0, "last_week_pct_today": 1.0, "this_week_pct_today": 1.5,
            "streak_5d_ago": 0, "last_week_pct_5d_ago": 1.0,
        },
    }
    result = find_turning_points(heatgrid_windows)

    names = {r["meta_name"] for r in result}
    assert names == {"族群A", "族群B"}
    a = next(r for r in result if r["meta_name"] == "族群A")
    assert a["direction"] == "轉強訊號"
    assert a["cur_key"] == "super" and a["prev_key"] == "weak"
    b = next(r for r in result if r["meta_name"] == "族群B")
    assert b["direction"] == "轉弱訊號，留意"


def test_find_turning_points_skips_when_five_days_ago_data_is_none():
    heatgrid_windows = {
        "資料不足族群": {
            "streak_today": 3, "last_week_pct_today": 1.0, "this_week_pct_today": 6.0,
            "streak_5d_ago": None, "last_week_pct_5d_ago": None,
        },
    }
    result = find_turning_points(heatgrid_windows)
    assert result == []


def test_find_anomaly_cards_burst_requires_volume_and_rank_jump():
    meta_perf = [
        {"meta_name": "爆量族群", "avg_change_pct": 5.0, "up_count": 1, "down_count": 0, "flat_count": 0},
        {"meta_name": "普通族群", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    meta_signals = {
        "爆量族群": {"vol_ratio": 1.8, "yesterday_rank": 15},  # 今日依avg_change_pct排序是#1，跳動14
        "普通族群": {"vol_ratio": 1.2, "yesterday_rank": 2},
    }
    heatgrid_windows = {
        "爆量族群": {"streak_today": 3, "last_week_pct_today": 1.0, "this_week_pct_today": 2.0,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},
        "普通族群": {"streak_today": 3, "last_week_pct_today": 1.0, "this_week_pct_today": 2.0,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},
    }
    result = find_anomaly_cards(meta_perf, meta_signals, heatgrid_windows)

    assert [r["meta_name"] for r in result] == ["爆量族群"]
    assert result[0]["kind"] == "burst"


def test_find_anomaly_cards_trend_requires_hot_temp_and_sustained_streak():
    meta_perf = [
        {"meta_name": "噴出族群", "avg_change_pct": 2.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    meta_signals = {"噴出族群": {"vol_ratio": 1.0, "yesterday_rank": 1}}
    heatgrid_windows = {
        # accel = 9.0 - 1.0 = 8.0 (>=5, hot)，streak_today=6 (>=5)
        "噴出族群": {"streak_today": 6, "last_week_pct_today": 1.0, "this_week_pct_today": 9.0,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},
    }

    result = find_anomaly_cards(meta_perf, meta_signals, heatgrid_windows)

    assert [r["meta_name"] for r in result] == ["噴出族群"]
    assert result[0]["kind"] == "trend"


def test_find_anomaly_cards_trend_not_triggered_when_streak_below_threshold():
    """accel達到hot門檻但streak<5(不夠持續)，不算連續噴出。"""
    meta_perf = [
        {"meta_name": "曇花一現", "avg_change_pct": 2.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    meta_signals = {"曇花一現": {"vol_ratio": 1.0, "yesterday_rank": 1}}
    heatgrid_windows = {
        "曇花一現": {"streak_today": 2, "last_week_pct_today": 1.0, "this_week_pct_today": 9.0,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},
    }

    result = find_anomaly_cards(meta_perf, meta_signals, heatgrid_windows)
    assert result == []


def test_find_anomaly_cards_burst_takes_precedence_over_trend_for_same_sector():
    meta_perf = [
        {"meta_name": "雙重訊號", "avg_change_pct": 5.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    meta_signals = {"雙重訊號": {"vol_ratio": 2.0, "yesterday_rank": 20}}  # burst條件成立
    heatgrid_windows = {
        # accel=8.0(hot), streak_today=6(>=5) → trend條件也成立
        "雙重訊號": {"streak_today": 6, "last_week_pct_today": 1.0, "this_week_pct_today": 9.0,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},
    }

    result = find_anomaly_cards(meta_perf, meta_signals, heatgrid_windows)
    assert len(result) == 1
    assert result[0]["kind"] == "burst"


def test_find_anomaly_cards_returns_empty_list_when_nothing_qualifies():
    meta_perf = [
        {"meta_name": "平淡族群", "avg_change_pct": 0.1, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    meta_signals = {"平淡族群": {"vol_ratio": 1.0, "yesterday_rank": 1}}
    heatgrid_windows = {
        "平淡族群": {"streak_today": 1, "last_week_pct_today": 1.0, "this_week_pct_today": 1.5,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},
    }

    result = find_anomaly_cards(meta_perf, meta_signals, heatgrid_windows)
    assert result == []


def test_find_anomaly_cards_silently_excludes_sector_missing_from_signals_and_windows():
    """meta_perf有這個族群，但meta_signals/heatgrid_windows完全沒有這個族群的key
    (不是欄位缺值，是整個dict entry都不存在)——這是main.py實際production路徑會發生的情況：
    calc_meta_performance()跟calc_meta_heatgrid_windows()是獨立呼叫，兩邊的族群集合理論上
    可能因為各自獨立的失敗模式而不完全一致。要確認這種情況會被安靜排除，不會crash。"""
    meta_perf = [
        {"meta_name": "完全缺資料族群", "avg_change_pct": 5.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    result = find_anomaly_cards(meta_perf, meta_signals={}, heatgrid_windows={})
    assert result == []


from export.index_generator import build_heatgrid_cards


def test_build_heatgrid_cards_ranks_by_avg_change_pct_and_includes_all_fields():
    meta_perf = [
        {"meta_name": "族群A", "avg_change_pct": 5.0, "up_count": 10, "down_count": 2, "flat_count": 1},
        {"meta_name": "族群B", "avg_change_pct": -3.0, "up_count": 2, "down_count": 10, "flat_count": 0},
    ]
    meta_signals = {
        "族群A": {"streak": 5, "vol_ratio": 1.8, "yesterday_rank": 3},
        "族群B": {"streak": -2, "vol_ratio": 1.1, "yesterday_rank": 1},
    }
    meta_chips = {
        "族群A": {"foreign_streak": 3, "trust_streak": 0},
        "族群B": {"foreign_streak": -1, "trust_streak": 2},
    }
    heatgrid_windows = {
        "族群A": {"streak_today": 3, "last_week_pct_today": 1.0, "this_week_pct_today": 6.0,
                  "streak_5d_ago": None, "last_week_pct_5d_ago": None},
        "族群B": {"streak_today": -2, "last_week_pct_today": -1.0, "this_week_pct_today": -3.5,
                  "streak_5d_ago": None, "last_week_pct_5d_ago": None},
    }

    cards = build_heatgrid_cards(meta_perf, meta_signals, meta_chips, heatgrid_windows)

    assert [c["meta_name"] for c in cards] == ["族群A", "族群B"]
    assert cards[0]["rank"] == 1
    assert cards[1]["rank"] == 2

    a = cards[0]
    assert a["pct"] == 5.0
    assert a["up_count"] == 10 and a["down_count"] == 2
    assert a["streak"] == 3  # window_data["streak_today"]，不是meta_signals的streak(5)
    assert a["vol_ratio"] == 1.8
    assert a["tier"] == {"key": "super", "label": "超強"}  # streak=3>0, accel=6.0-1.0=5.0>3
    assert a["temp"] == {"key": "hot", "label": "增溫 +5.0pt"}  # accel=5.0>=5.0門檻
    assert a["foreign_streak"] == 3 and a["trust_streak"] == 0
    assert a["last_week_pct"] == 1.0 and a["this_week_pct"] == 6.0
    assert a["accel"] == 5.0
    assert "color-mix" in a["heat_bg"]

    b = cards[1]
    assert b["pct"] == -3.0
    assert b["up_count"] == 2 and b["down_count"] == 10
    assert b["streak"] == -2
    assert b["vol_ratio"] == 1.1
    # streak=-2<0, accel=-3.5-(-1.0)=-2.5 < -2 → weak（走跟族群A完全不同的分支）
    assert b["tier"] == {"key": "weak", "label": "弱"}
    assert b["temp"] is None  # |accel|=2.5 < 5.0門檻，不顯示徽章
    assert b["foreign_streak"] == -1 and b["trust_streak"] == 2
    assert b["last_week_pct"] == -1.0 and b["this_week_pct"] == -3.5
    assert b["accel"] == -2.5
    assert "color-mix" in b["heat_bg"]


def test_build_heatgrid_cards_handles_missing_signals_gracefully():
    """meta_signals/meta_chips/heatgrid_windows某族群缺資料時(例如新族群還沒被算過)不crash，
    相關欄位回None/預設值，不是KeyError。"""
    meta_perf = [
        {"meta_name": "新族群", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    cards = build_heatgrid_cards(meta_perf, {}, {}, {})

    card = cards[0]
    assert card["meta_name"] == "新族群"
    assert card["tier"] is None
    assert card["temp"] is None
    assert card["foreign_streak"] is None
    assert card["trust_streak"] is None
    assert card["streak"] is None
    assert card["vol_ratio"] is None
    assert card["last_week_pct"] is None and card["this_week_pct"] is None
    assert card["accel"] is None
    assert card["cum3"] is None and card["cum5"] is None and card["cum7"] is None
    assert card["rank_delta"] is None
    assert "color-mix" in card["heat_bg"]  # 就算完全沒有enrichment資料，heat_bg仍要能算(靠pct本身)


def test_build_heatgrid_cards_attaches_cum_badges_and_rank_delta():
    """Cody回報「族群近況都是錯誤的」之前，先確認稽核發現的3/5/7日累積漲跌badge+排名
    升降箭頭有正確接上：cum_data是calc_cumulative_meta()的原始list，這裡轉成dict查表；
    排名升降是拿meta_signals既有的yesterday_rank跟這次算出的今日排名比較。"""
    meta_perf = [
        {"meta_name": "族群A", "avg_change_pct": 5.0, "up_count": 10, "down_count": 2, "flat_count": 1},
        {"meta_name": "族群B", "avg_change_pct": -3.0, "up_count": 2, "down_count": 10, "flat_count": 0},
    ]
    meta_signals = {
        "族群A": {"yesterday_rank": 3},  # 今天#1，昨天#3 → 排名進步2名
        "族群B": {"yesterday_rank": 1},  # 今天#2，昨天#1 → 排名退步1名
    }
    cum_data = [
        {"meta_name": "族群A", "cum1": 1.0, "cum3": 8.0, "cum5": 10.0, "cum7": None},
        {"meta_name": "族群B", "cum1": -1.0, "cum3": -5.0, "cum5": None, "cum7": -9.0},
    ]

    cards = build_heatgrid_cards(meta_perf, meta_signals, {}, {}, cum_data)

    a = next(c for c in cards if c["meta_name"] == "族群A")
    assert a["cum3"] == 8.0 and a["cum5"] == 10.0 and a["cum7"] is None
    assert a["rank_delta"] == 2  # yesterday_rank(3) - today_rank(1)

    b = next(c for c in cards if c["meta_name"] == "族群B")
    assert b["cum3"] == -5.0 and b["cum5"] is None and b["cum7"] == -9.0
    assert b["rank_delta"] == -1  # yesterday_rank(1) - today_rank(2)


def test_build_heatgrid_cards_defaults_cum_to_none_without_cum_data():
    """cum_data沒傳(None)時cum3/5/7都要是None，不能crash——跟其他enrichment參數的
    fail-soft慣例一致。"""
    meta_perf = [
        {"meta_name": "族群A", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    cards = build_heatgrid_cards(meta_perf, {}, {}, {})

    assert cards[0]["cum3"] is None and cards[0]["cum5"] is None and cards[0]["cum7"] is None


from export.index_generator import build_sector_recap


def test_build_sector_recap_sorts_hot_and_cold_by_accel():
    meta_perf = [
        {"meta_name": "升溫族群", "avg_change_pct": 3.0, "up_count": 1, "down_count": 0, "flat_count": 0},
        {"meta_name": "退燒族群", "avg_change_pct": -1.0, "up_count": 0, "down_count": 1, "flat_count": 0},
        {"meta_name": "普通族群", "avg_change_pct": 0.5, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    heatgrid_windows = {
        "升溫族群": {"streak_today": 3, "last_week_pct_today": 1.0, "this_week_pct_today": 9.0,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},  # accel=8.0
        "退燒族群": {"streak_today": -2, "last_week_pct_today": 1.0, "this_week_pct_today": -5.0,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},  # accel=-6.0
        "普通族群": {"streak_today": 1, "last_week_pct_today": 1.0, "this_week_pct_today": 1.5,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},  # accel=0.5
    }

    cards = build_heatgrid_cards(meta_perf, {}, {}, heatgrid_windows)
    recap = build_sector_recap(cards, heatgrid_windows)

    assert recap["hot_top5"][0]["meta_name"] == "升溫族群"
    assert recap["cold_top5"][0]["meta_name"] == "退燒族群"


def test_build_sector_recap_excludes_none_accel_from_hot_cold_ranking():
    meta_perf = [
        {"meta_name": "資料不足", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
        {"meta_name": "正常族群", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    heatgrid_windows = {
        "資料不足": {"streak_today": None, "last_week_pct_today": None, "this_week_pct_today": None,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},
        "正常族群": {"streak_today": 1, "last_week_pct_today": 1.0, "this_week_pct_today": 3.0,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},
    }

    cards = build_heatgrid_cards(meta_perf, {}, {}, heatgrid_windows)
    recap = build_sector_recap(cards, heatgrid_windows)

    hot_names = [r["meta_name"] for r in recap["hot_top5"]]
    assert "資料不足" not in hot_names
    assert "正常族群" in hot_names


def test_build_sector_recap_includes_turning_points():
    meta_perf = [
        {"meta_name": "翻轉族群", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    heatgrid_windows = {
        "翻轉族群": {"streak_today": 3, "last_week_pct_today": 1.0, "this_week_pct_today": 6.0,
                    "streak_5d_ago": -2, "last_week_pct_5d_ago": 3.5},
    }
    cards = build_heatgrid_cards(meta_perf, {}, {}, heatgrid_windows)
    recap = build_sector_recap(cards, heatgrid_windows)
    assert recap["turning_points"][0]["meta_name"] == "翻轉族群"
    assert recap["turning_points"][0]["direction"] == "轉強訊號"


def test_build_sector_recap_excludes_stale_sector_from_turning_points():
    """heatgrid_windows有某族群的翻轉資料，但meta_perf(當下有效族群清單)已經不包含它
    (例如calc_meta_performance()跟calc_meta_heatgrid_windows()兩個獨立呼叫，某次族群集合
    不一致)——turning_points不能顯示這個已經不在meta_perf裡的族群，要跟hot_top5/cold_top5
    的過濾邏輯一致(這是Task 4 code review提前發現的落地前風險，Task 6一開始就要防)。

    同時驗證正面案例：仍在meta_perf裡的「有效族群」若真的有翻轉，要正確出現在turning_points
    （不能因為過濾邏輯寫錯、把active_windows整個濾成空的，導致這個測試表面上通過但其實
    什麼都沒篩選對——code review抓到：只斷言「已下架族群不在」無法區分「正確過濾」跟
    「過濾過頭變空dict」這兩種情況，因為兩者都會讓「已下架族群 not in []」成立）。"""
    meta_perf = [
        {"meta_name": "有效族群", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    heatgrid_windows = {
        "有效族群": {  # 也有真實翻轉(弱→超強)，且仍在meta_perf裡，應該要出現在turning_points
            "streak_today": 3, "last_week_pct_today": 1.0, "this_week_pct_today": 6.0,
            "streak_5d_ago": -2, "last_week_pct_5d_ago": 3.5,
        },
        "已下架族群": {  # 有真實翻轉(弱→超強)，但不在meta_perf裡
            "streak_today": 3, "last_week_pct_today": 1.0, "this_week_pct_today": 6.0,
            "streak_5d_ago": -2, "last_week_pct_5d_ago": 3.5,
        },
    }
    cards = build_heatgrid_cards(meta_perf, {}, {}, heatgrid_windows)
    recap = build_sector_recap(cards, heatgrid_windows)
    turning_names = [r["meta_name"] for r in recap["turning_points"]]

    assert "已下架族群" not in turning_names
    assert "有效族群" in turning_names
    valid = next(r for r in recap["turning_points"] if r["meta_name"] == "有效族群")
    assert valid["direction"] == "轉強訊號"


def test_build_sector_recap_excludes_today_breakout_sector_from_cold_top5():
    """Cody回報實際案例：功率半導體今日排名#40→#1、+5.66%，卻被歸類成「退燒」——
    因為accel(週對週5日滾動窗比較)本質上跟「今天是不是正在發生大事」是兩個不同問題，
    兩者合法地可以背離。修法：新增「今日爆發」類別(只看排名跳動+今日漲跌，不要求
    量比)，並且cold_top5要排除掉「今日爆發」的族群——不能讓同一族群同時被講成
    「退燒」又「今日爆發」，這對使用者是矛盾的訊號。"""
    meta_perf = [
        {"meta_name": "功率半導體", "avg_change_pct": 5.66, "up_count": 30, "down_count": 5, "flat_count": 0},
        {"meta_name": "真退燒族群", "avg_change_pct": -1.0, "up_count": 2, "down_count": 20, "flat_count": 0},
    ]
    meta_signals = {
        "功率半導體": {"yesterday_rank": 40},  # 今天#1(avg_change_pct最高) → rank_delta = 40-1 = 39
        "真退燒族群": {"yesterday_rank": 2},   # 今天#2 → rank_delta = 2-2 = 0，不算爆發
    }
    heatgrid_windows = {
        "功率半導體": {"streak_today": 1, "last_week_pct_today": 20.0, "this_week_pct_today": 5.0,
                     "streak_5d_ago": None, "last_week_pct_5d_ago": None},  # accel=-15.0，本來會被算成退燒
        "真退燒族群": {"streak_today": -3, "last_week_pct_today": 1.0, "this_week_pct_today": -5.0,
                     "streak_5d_ago": None, "last_week_pct_5d_ago": None},  # accel=-6.0，真的退燒
    }

    cards = build_heatgrid_cards(meta_perf, meta_signals, {}, heatgrid_windows)
    recap = build_sector_recap(cards, heatgrid_windows)

    cold_names = [r["meta_name"] for r in recap["cold_top5"]]
    assert "功率半導體" not in cold_names  # 今日爆發的族群不該同時被講成退燒
    assert "真退燒族群" in cold_names  # 真正退燒的族群還是要留著

    breakout_names = [r["meta_name"] for r in recap["today_breakout"]]
    assert "功率半導體" in breakout_names
    assert "真退燒族群" not in breakout_names
    breakout_row = next(r for r in recap["today_breakout"] if r["meta_name"] == "功率半導體")
    assert breakout_row["rank_delta"] == 39


def test_build_sector_recap_identifies_foreign_and_trust_stealth_accumulation():
    """Cody要求新增「外資悄悄佈局/投信悄悄佈局」——股價還沒明顯反應但法人連買好幾天的
    族群，用既有的meta_chips(foreign_streak/trust_streak)資料，不需要新的資料來源。"""
    meta_perf = [
        {"meta_name": "外資佈局中", "avg_change_pct": 0.3, "up_count": 5, "down_count": 5, "flat_count": 0},
        {"meta_name": "投信佈局中", "avg_change_pct": -0.5, "up_count": 3, "down_count": 7, "flat_count": 0},
        {"meta_name": "已經噴出", "avg_change_pct": 5.0, "up_count": 10, "down_count": 0, "flat_count": 0},
    ]
    meta_chips = {
        "外資佈局中": {"foreign_streak": 5, "trust_streak": 0},
        "投信佈局中": {"foreign_streak": 0, "trust_streak": 4},
        "已經噴出": {"foreign_streak": 6, "trust_streak": 5},  # 連買天數更高，但股價已經噴出，不算「悄悄」
    }

    cards = build_heatgrid_cards(meta_perf, {}, meta_chips, {})
    recap = build_sector_recap(cards, {})

    foreign_names = [r["meta_name"] for r in recap["foreign_stealth"]]
    trust_names = [r["meta_name"] for r in recap["trust_stealth"]]
    assert "外資佈局中" in foreign_names
    assert "已經噴出" not in foreign_names  # 股價已經動了(+5%)，不算悄悄佈局
    assert "投信佈局中" in trust_names
    assert "已經噴出" not in trust_names


def test_build_sector_recap_identifies_volume_anomaly():
    """量能異常：今日量比高但股價還沒明顯反應。"""
    meta_perf = [
        {"meta_name": "量能異常族群", "avg_change_pct": 0.8, "up_count": 5, "down_count": 5, "flat_count": 0},
        {"meta_name": "正常量能族群", "avg_change_pct": 0.5, "up_count": 5, "down_count": 5, "flat_count": 0},
    ]
    meta_signals = {
        "量能異常族群": {"vol_ratio": 2.5},
        "正常量能族群": {"vol_ratio": 1.0},
    }

    cards = build_heatgrid_cards(meta_perf, meta_signals, {}, {})
    recap = build_sector_recap(cards, {})

    volume_names = [r["meta_name"] for r in recap["volume_anomaly"]]
    assert "量能異常族群" in volume_names
    assert "正常量能族群" not in volume_names


def test_build_stock_detail_data_groups_by_meta_and_sorts_by_change_pct():
    universe_df = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "股票甲", "meta_sector": "族群A"},
        {"stock_id": "1001", "stock_name": "股票乙", "meta_sector": "族群A"},
        {"stock_id": "2000", "stock_name": "股票丙", "meta_sector": "族群B"},
    ])
    prices_df = pd.DataFrame([
        {"stock_id": "1000", "close": 100.0, "change_pct": 2.0},
        {"stock_id": "1001", "close": 50.0, "change_pct": 5.0},
        {"stock_id": "2000", "close": 30.0, "change_pct": -1.0},
    ])

    result = build_stock_detail_data(universe_df, prices_df)

    assert [s["stock_id"] for s in result["族群A"]] == ["1001", "1000"]  # 5.0 > 2.0
    assert result["族群B"][0]["stock_id"] == "2000"


def test_build_stock_detail_data_includes_all_meta_sectors_even_with_no_price_data():
    """族群存在universe裡但完全沒有對應行情資料時，仍要有這個key，個股以no_data=True
    佔位卡呈現（比照舊版html_generator.py「無行情」佔位符慣例，Cody回報這點也是這次
    改版遺漏的項目之一），不能整個族群消失，也不能整檔股票消失。"""
    universe_df = pd.DataFrame([
        {"stock_id": "9999", "stock_name": "無行情股", "meta_sector": "空資料族群"},
    ])
    prices_df = pd.DataFrame(columns=["stock_id", "close", "change_pct"])

    result = build_stock_detail_data(universe_df, prices_df)

    assert len(result["空資料族群"]) == 1
    assert result["空資料族群"][0]["no_data"] is True
    assert result["空資料族群"][0]["close"] is None
    assert result["空資料族群"][0]["change_pct"] is None


def test_build_stock_detail_data_marks_individual_stock_missing_price_as_no_data():
    """族群內部分股票有行情、部分沒有：有行情的股票正常列出(no_data=False)，沒行情的
    那檔標記no_data=True但仍然出現在清單裡(不再跳過)，且排在有行情的股票後面。"""
    universe_df = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "有行情", "meta_sector": "族群C"},
        {"stock_id": "1001", "stock_name": "無行情", "meta_sector": "族群C"},
    ])
    prices_df = pd.DataFrame([{"stock_id": "1000", "close": 10.0, "change_pct": 1.0}])

    result = build_stock_detail_data(universe_df, prices_df)

    assert len(result["族群C"]) == 2
    assert result["族群C"][0]["stock_id"] == "1000"
    assert result["族群C"][0]["no_data"] is False
    assert result["族群C"][1]["stock_id"] == "1001"
    assert result["族群C"][1]["no_data"] is True


def test_build_stock_detail_data_attaches_rolling_returns_and_chips():
    """Cody回報「近5/7/10/14天都不見了」跟個股外資/投信摘要——這裡確認
    rolling_returns(get_rolling_returns()格式)跟chips_df(get_chips_today()格式)
    都有正確附加到對應股票上。"""
    universe_df = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "股票甲", "meta_sector": "族群A"},
    ])
    prices_df = pd.DataFrame([{"stock_id": "1000", "close": 100.0, "change_pct": 2.0}])
    rolling_returns = {"1000": {5: 3.0, 7: 4.0, 10: None, 14: 6.0}}
    chips_df = pd.DataFrame([
        {"stock_id": "1000", "foreign_net": 500000, "trust_net": -200000,
         "margin_balance": 1000000, "margin_change": 50000},
    ])

    result = build_stock_detail_data(universe_df, prices_df, rolling_returns=rolling_returns, chips_df=chips_df)

    stock = result["族群A"][0]
    assert stock["roll5"] == 3.0 and stock["roll7"] == 4.0 and stock["roll10"] is None and stock["roll14"] == 6.0
    assert stock["foreign_net"] == 500000
    assert stock["trust_net"] == -200000
    assert stock["margin_balance"] == 1000000
    assert stock["margin_change"] == 50000


def test_build_stock_detail_data_defaults_rolling_and_chips_to_none_without_data():
    """rolling_returns/chips_df沒傳、或這支股票不在裡面時，都要是None，不能crash。"""
    universe_df = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "股票甲", "meta_sector": "族群A"},
    ])
    prices_df = pd.DataFrame([{"stock_id": "1000", "close": 100.0, "change_pct": 2.0}])

    stock = build_stock_detail_data(universe_df, prices_df)["族群A"][0]

    assert stock["roll5"] is None and stock["roll7"] is None
    assert stock["foreign_net"] is None and stock["trust_net"] is None
    assert stock["margin_balance"] is None and stock["margin_change"] is None


def test_build_stock_detail_data_attaches_volume_and_vol_ratio():
    """Cody回報「個股相關量價都不見了」——這裡確認stock_sparklines的volumes(今日成交量)/
    vol_ratio(今日量/5日均量)有正確附加到對應股票上，不是只有pcts/dates。"""
    universe_df = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "股票甲", "meta_sector": "族群A"},
    ])
    prices_df = pd.DataFrame([{"stock_id": "1000", "close": 100.0, "change_pct": 2.0}])
    stock_sparklines = {
        "1000": {"pcts": [1.0, 2.0], "dates": ["7/21", "7/22"],
                 "volumes": [800, 1000, 1800], "avg_volume": 900, "vol_ratio": 2.0},
    }

    stock = build_stock_detail_data(universe_df, prices_df, stock_sparklines=stock_sparklines)["族群A"][0]

    assert stock["volume"] == 1800  # volumes最後一筆(今日)
    assert stock["vol_ratio"] == 2.0


def test_build_stock_detail_data_defaults_volume_and_vol_ratio_to_none_without_sparklines():
    """stock_sparklines沒傳、或這支股票沒有volumes資料時，volume/vol_ratio要是None，不能
    crash（例如volumes是空list時不能對負index取值）。"""
    universe_df = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "股票甲", "meta_sector": "族群A"},
    ])
    prices_df = pd.DataFrame([{"stock_id": "1000", "close": 100.0, "change_pct": 2.0}])

    stock_no_arg = build_stock_detail_data(universe_df, prices_df)["族群A"][0]
    assert stock_no_arg["volume"] is None and stock_no_arg["vol_ratio"] is None

    stock_empty_volumes = build_stock_detail_data(
        universe_df, prices_df, stock_sparklines={"1000": {"pcts": [], "dates": [], "volumes": []}},
    )["族群A"][0]
    assert stock_empty_volumes["volume"] is None


def test_build_stock_detail_data_attaches_sparkline_when_provided():
    """Cody回報「個股卡片怎麼不見」——熱區格改版把個股sparkline拿掉了，這裡補回來：
    stock_sparklines有這支股票的資料時，pcts/dates要正確附加到對應的股票dict上。"""
    universe_df = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "股票甲", "meta_sector": "族群A"},
    ])
    prices_df = pd.DataFrame([{"stock_id": "1000", "close": 100.0, "change_pct": 2.0}])
    stock_sparklines = {
        "1000": {"pcts": [1.0, -0.5, 2.0], "dates": ["7/20", "7/21", "7/22"], "avg_volume": 1000, "vol_ratio": 1.2},
    }

    result = build_stock_detail_data(universe_df, prices_df, stock_sparklines)

    assert result["族群A"][0]["pcts"] == [1.0, -0.5, 2.0]
    assert result["族群A"][0]["dates"] == ["7/20", "7/21", "7/22"]


def test_build_stock_detail_data_defaults_to_empty_sparkline_when_missing():
    """stock_sparklines整包沒傳、或這支股票不在裡面時，pcts/dates要是空list，不能crash。"""
    universe_df = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "股票甲", "meta_sector": "族群A"},
        {"stock_id": "1001", "stock_name": "股票乙", "meta_sector": "族群A"},
    ])
    prices_df = pd.DataFrame([
        {"stock_id": "1000", "close": 100.0, "change_pct": 2.0},
        {"stock_id": "1001", "close": 50.0, "change_pct": 1.0},
    ])

    result_no_arg = build_stock_detail_data(universe_df, prices_df)
    result_partial = build_stock_detail_data(universe_df, prices_df, {"1000": {"pcts": [1.0], "dates": ["7/22"]}})

    assert result_no_arg["族群A"][0]["pcts"] == []
    assert result_no_arg["族群A"][0]["dates"] == []
    stock_1001 = next(s for s in result_partial["族群A"] if s["stock_id"] == "1001")
    assert stock_1001["pcts"] == []


from datetime import date
from export.index_generator import generate


def _sample_meta_perf():
    return [
        {"meta_name": "測試族群", "avg_change_pct": 3.5, "up_count": 5, "down_count": 1, "flat_count": 0},
    ]


def _sample_universe_df():
    return pd.DataFrame([
        {"stock_id": "1000", "stock_name": "測試股", "meta_sector": "測試族群"},
    ])


def _sample_prices_df():
    return pd.DataFrame([
        {"stock_id": "1000", "close": 100.0, "change_pct": 3.5},
    ])


def test_generate_returns_early_and_skips_write_when_meta_perf_empty(tmp_path):
    output_path = tmp_path / "index.html"

    generate(date(2026, 7, 22), [], pd.DataFrame(), {}, {}, pd.DataFrame(), {}, output_path=str(output_path))

    assert not output_path.exists()


def test_generate_writes_page_with_all_41_style_sectors_present(tmp_path):
    """41個族群全部要有卡片，這裡用3個族群模擬同樣的「全部要出現」要求
    （呼應2026-07-09 index.html只render部分族群導致連結靜默失敗的回歸測試精神）。"""
    output_path = tmp_path / "index.html"
    meta_perf = [
        {"meta_name": f"族群{i}", "avg_change_pct": float(i) - 1, "up_count": 1, "down_count": 0, "flat_count": 0}
        for i in range(3)
    ]
    universe_df = pd.DataFrame([
        {"stock_id": f"100{i}", "stock_name": f"股票{i}", "meta_sector": f"族群{i}"} for i in range(3)
    ])
    prices_df = pd.DataFrame([
        {"stock_id": f"100{i}", "close": 10.0 + i, "change_pct": float(i) - 1} for i in range(3)
    ])

    generate(date(2026, 7, 22), meta_perf, universe_df, {}, {}, prices_df, {}, output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    import re
    names_present = set(re.findall(r'data-meta-name="(族群\d)"', html))
    assert names_present == {"族群0", "族群1", "族群2"}


def test_generate_escapes_malicious_meta_and_stock_name(tmp_path):
    """族群名稱/股票名稱來自stock_universe.csv，頁面發布到GitHub Pages，比照既有generator防護。

    meta_name 會被 Python 端 _esc() 渲染進實際 HTML markup（熱區格/異動族群卡片），必須
    對<script>這類會斷開標籤的payload做HTML escape。stock_name只出現在<script>區塊內嵌的
    JSON資料裡（build_stock_detail_data()故意不escape，見generate()註解），瀏覽器HTML
    parser不會解析<script>內容為標籤，只要沒有</就無法逃逸出script邊界——真正的防護是
    JS端selectGroup()在寫進innerHTML前呼叫escHtml()，這裡改成驗證escHtml()確實有被套用
    在stock_id/stock_name上，而不是斷言payload完全不出現在整份文件裡（那個斷言對這個安全
    模型來說是錯的，這是code review跟coordinator一起釐清後修正的地方，不是設計有洞）。"""
    output_path = tmp_path / "index.html"
    meta_perf = [
        {"meta_name": "<script>alert(1)</script>", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    universe_df = pd.DataFrame([
        {"stock_id": "9999", "stock_name": "<img onerror=alert(2)>", "meta_sector": "<script>alert(1)</script>"},
    ])
    prices_df = pd.DataFrame([{"stock_id": "9999", "close": 1.0, "change_pct": 1.0}])

    generate(date(2026, 7, 22), meta_perf, universe_df, {}, {}, prices_df, {}, output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")

    # meta_name 渲染進實際HTML markup（熱區格卡片等），必須被_esc()完整escape
    assert "<script>alert(1)</script>" not in html

    # meta_name/meta_sector 即使出現在<script>內嵌JSON裡，也不能真的斷開script標籤本身
    # （這才是json.dumps().replace("</","<\\/")要防的唯一逃逸路徑）
    assert "</script>alert(1)" not in html

    # stock_name 的真正防護在JS端：確認escHtml()確實被用在渲染stock_name/stock_id的地方，
    # 而不是斷言payload完全不出現在文件裡（它會安全地出現在<script>內嵌JSON中，這是預期行為）
    assert "escHtml(s.stock_name)" in html
    assert "escHtml(s.stock_id)" in html


def test_generate_uses_this_dataset_metaname_not_raw_string_interpolation(tmp_path):
    """族群名稱含斜線(例如「機器人/自動化」)時，onclick不能直接內插原始名稱字串，
    必須用this.dataset.metaName讀DOM屬性——這是最容易在改版時不小心退化回不安全寫法的地方。"""
    output_path = tmp_path / "index.html"
    meta_perf = [
        {"meta_name": "機器人/自動化", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    universe_df = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "測試股", "meta_sector": "機器人/自動化"},
    ])
    prices_df = pd.DataFrame([{"stock_id": "1000", "close": 10.0, "change_pct": 1.0}])

    generate(date(2026, 7, 22), meta_perf, universe_df, {}, {}, prices_df, {}, output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert "onclick=\"selectGroup('機器人/自動化')\"" not in html
    assert "onclick=\"selectGroup(this.dataset.metaName)\"" in html


def test_generate_includes_nav_links_to_other_three_pages(tmp_path):
    output_path = tmp_path / "index.html"
    generate(date(2026, 7, 22), _sample_meta_perf(), _sample_universe_df(), {}, {}, _sample_prices_df(), {}, output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert 'href="chips.html"' in html
    assert 'href="patterns.html"' in html
    assert 'href="momentum.html"' in html


def test_generate_renders_anomaly_section_empty_state_when_no_cards_qualify(tmp_path):
    output_path = tmp_path / "index.html"
    generate(date(2026, 7, 22), _sample_meta_perf(), _sample_universe_df(), {}, {}, _sample_prices_df(), {}, output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert "目前沒有族群符合" in html  # 0張異動族群卡片時的誠實空狀態文案


def test_pct_str_does_not_double_sign_negative_zero():
    """pct=-0.0(浮點數負零，例如round(-0.001,2)產生的值)不能render成"+-0.00%"這種
    語法上矛盾的雙重符號——code review抓到：手動組"+"字串再讓:.2f格式化仍帶負號的
    浮點數會產生這個bug，改用Python原生:+.2f格式旗標可以避免。"""
    from export.index_generator import _pct_str
    assert _pct_str(-0.0) == "-0.00%"
    assert "+-" not in _pct_str(-0.0)


def test_generate_renders_populated_tier_temp_badges_and_recap_data(tmp_path):
    """所有前7個Task組裝出來的「有資料」分支都要至少被render一次，不能只測「沒資料」
    的空狀態分支——code review抓到：先前6個測試全部傳{}給meta_signals/meta_chips/
    heatgrid_windows，導致tier徽章/temp徽章/法人badge/週對比/異動族群populated分支/
    族群近況populated分支完全沒有測試覆蓋，dict key對不上都不會被抓到。"""
    output_path = tmp_path / "index.html"
    meta_perf = [
        {"meta_name": "強勢族群", "avg_change_pct": 5.0, "up_count": 10, "down_count": 1, "flat_count": 0},
    ]
    universe_df = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "測試股", "meta_sector": "強勢族群"},
    ])
    prices_df = pd.DataFrame([{"stock_id": "1000", "close": 100.0, "change_pct": 5.0}])
    meta_signals = {"強勢族群": {"vol_ratio": 1.8, "yesterday_rank": 20}}
    meta_chips = {"強勢族群": {"foreign_streak": 3, "trust_streak": 2}}
    heatgrid_windows = {
        "強勢族群": {"streak_today": 3, "last_week_pct_today": 1.0, "this_week_pct_today": 6.0,
                    "streak_5d_ago": -2, "last_week_pct_5d_ago": 3.5},
    }

    generate(date(2026, 7, 22), meta_perf, universe_df, meta_signals, meta_chips, prices_df, heatgrid_windows, output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert "超強" in html  # tier badge：streak=3>0, accel=6.0-1.0=5.0>3 → super
    assert "增溫" in html  # temp badge：accel=5.0達hot門檻
    assert "外資連買3日" in html  # 法人badge
    assert "投信連買2日" in html
    assert "近5日→前5日" in html  # 週對比區塊
    assert "強勢族群" in html  # 出現在族群近況hot_top5（accel=5.0升溫）
    assert "轉強訊號" in html  # 轉折點：5天前弱(streak=-2,accel=-2.5)→今天超強


def test_generate_embeds_stock_sparklines_and_renders_card_js(tmp_path):
    """Cody回報「個股卡片怎麼不見」，確認stock_sparklines參數會流進STOCKS JSON、
    sparkline有render在個股卡片(彈窗)裡。個股列表(不是卡片)是可排序的<table>，
    用來承載代號/收盤/漲跌%，跟卡片彈窗是兩個不同的東西。"""
    output_path = tmp_path / "index.html"
    meta_perf = [
        {"meta_name": "族群A", "avg_change_pct": 2.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    universe_df = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "測試股", "meta_sector": "族群A"},
    ])
    prices_df = pd.DataFrame([{"stock_id": "1000", "close": 100.0, "change_pct": 2.0}])
    stock_sparklines = {"1000": {"pcts": [1.0, 2.0], "dates": ["7/21", "7/22"]}}

    generate(date(2026, 7, 22), meta_perf, universe_df, {}, {}, prices_df, {},
             stock_sparklines=stock_sparklines, output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert '"pcts": [1.0, 2.0]' in html
    assert "function buildSparkline" in html
    assert 'class="stock-list-table"' in html


def test_generate_defaults_stock_sparklines_to_none_without_crashing(tmp_path):
    """main.py呼叫generate()時萬一stock_sparklines計算失敗傳{}，或呼叫端沒傳這個參數，
    都不能crash——沿用舊有generator的fail-soft慣例。"""
    output_path = tmp_path / "index.html"
    meta_perf = [{"meta_name": "族群A", "avg_change_pct": 2.0, "up_count": 1, "down_count": 0, "flat_count": 0}]
    universe_df = pd.DataFrame([{"stock_id": "1000", "stock_name": "測試股", "meta_sector": "族群A"}])
    prices_df = pd.DataFrame([{"stock_id": "1000", "close": 100.0, "change_pct": 2.0}])

    result = generate(date(2026, 7, 22), meta_perf, universe_df, {}, {}, prices_df, {}, output_path=str(output_path))

    assert output_path.exists()


def test_generate_renders_market_regime_dashboard_when_provided(tmp_path):
    """Cody稽核發現的大盤分級儀表板——market_regime有傳時要render對應的五級方向+
    操作提示；沒傳(None)時整塊不顯示（比照舊版html_generator.py::_market_regime_section()
    TAIEX抓取失敗時的fail-soft行為）。"""
    output_path = tmp_path / "index.html"
    meta_perf = [{"meta_name": "族群A", "avg_change_pct": 2.0, "up_count": 1, "down_count": 0, "flat_count": 0}]
    universe_df = pd.DataFrame([{"stock_id": "1000", "stock_name": "測試股", "meta_sector": "族群A"}])
    prices_df = pd.DataFrame([{"stock_id": "1000", "close": 100.0, "change_pct": 2.0}])
    market_regime = {
        "tier": "小漲", "taiex_change_pct": 0.5, "up_count": 600, "total": 1000, "breadth_ratio": 0.6,
        "heavyweight_avg_pct": 0.3, "broad_avg_pct": 0.8, "divergence": -0.5,
        "concentration_direction": None, "is_concentrated": False, "heavyweight_count": 20,
    }

    generate(date(2026, 7, 22), meta_perf, universe_df, {}, {}, prices_df, {},
             market_regime=market_regime, output_path=str(output_path))
    html = output_path.read_text(encoding="utf-8")
    assert "大盤現況" in html
    assert "小漲" in html
    assert "資金分布均衡" in html

    output_path2 = tmp_path / "index2.html"
    generate(date(2026, 7, 22), meta_perf, universe_df, {}, {}, prices_df, {},
             market_regime=None, output_path=str(output_path2))
    html2 = output_path2.read_text(encoding="utf-8")
    assert "大盤現況" not in html2


def test_generate_renders_volume_turnover_section_when_provided(tmp_path):
    """Cody稽核發現的巨量換手訊號區塊——vol_turnover_signals有資料時要render表格，
    空list或None時整塊不顯示。"""
    output_path = tmp_path / "index.html"
    meta_perf = [{"meta_name": "族群A", "avg_change_pct": 2.0, "up_count": 1, "down_count": 0, "flat_count": 0}]
    universe_df = pd.DataFrame([{"stock_id": "1000", "stock_name": "測試股", "meta_sector": "族群A"}])
    prices_df = pd.DataFrame([{"stock_id": "1000", "close": 100.0, "change_pct": 2.0}])
    vol_turnover_signals = [
        {"stock_id": "2330", "stock_name": "台積電", "meta_sector": "半導體", "change_pct": -3.5,
         "vol_multiple": 4.2, "foreign_net": -500000, "inst_confirmed": True},
    ]

    generate(date(2026, 7, 22), meta_perf, universe_df, {}, {}, prices_df, {},
             vol_turnover_signals=vol_turnover_signals, output_path=str(output_path))
    html = output_path.read_text(encoding="utf-8")
    assert "巨量換手訊號" in html
    assert "台積電" in html
    assert "外資+投信確認" in html

    output_path2 = tmp_path / "index2.html"
    generate(date(2026, 7, 22), meta_perf, universe_df, {}, {}, prices_df, {},
             vol_turnover_signals=[], output_path=str(output_path2))
    html2 = output_path2.read_text(encoding="utf-8")
    assert "巨量換手訊號" not in html2


def test_generate_includes_search_box_and_meta_hash_routing(tmp_path):
    """Cody稽核發現的兩個項目：(1)個股搜尋框不見了 (2)chips.html的#meta=連結深連結失效
    （chips_generator.py:_meta_link()還在產生index.html#meta={name}格式的連結，但舊版
    selectGroup()進來讀取location.hash的IIFE在改版時漏掉了）。這裡確認搜尋框HTML跟
    hash-routing的JS都有正確產生。"""
    output_path = tmp_path / "index.html"
    meta_perf = [{"meta_name": "族群A", "avg_change_pct": 2.0, "up_count": 1, "down_count": 0, "flat_count": 0}]
    universe_df = pd.DataFrame([{"stock_id": "1000", "stock_name": "測試股", "meta_sector": "族群A"}])
    prices_df = pd.DataFrame([{"stock_id": "1000", "close": 100.0, "change_pct": 2.0}])

    generate(date(2026, 7, 22), meta_perf, universe_df, {}, {}, prices_df, {}, output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert 'id="stock-search"' in html
    assert "function searchStocks" in html
    assert "const STOCK_INDEX" in html
    assert "const META_INDEX" in html
    assert "decodeURIComponent(location.hash)" in html
    assert "h.startsWith('#meta=')" in html


def test_generate_renders_stock_list_items_with_click_to_open_card(tmp_path):
    """Cody釐清「卡片」的意思：個股列表本身只顯示基本資訊(代號/名稱/收盤/漲跌%)，
    點擊才彈出「個股卡片」(彈窗)顯示走勢圖/量價/籌碼等列表之外的詳細資訊——兩層式設計，
    不是把所有資訊都塞在列表格子上。這裡確認list item跟modal彈窗的JS函式都有正確產生。"""
    output_path = tmp_path / "index.html"
    meta_perf = [{"meta_name": "族群A", "avg_change_pct": 2.0, "up_count": 1, "down_count": 0, "flat_count": 0}]
    universe_df = pd.DataFrame([{"stock_id": "1000", "stock_name": "測試股", "meta_sector": "族群A"}])
    prices_df = pd.DataFrame([{"stock_id": "1000", "close": 100.0, "change_pct": 2.0}])

    generate(date(2026, 7, 22), meta_perf, universe_df, {}, {}, prices_df, {}, output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert "function renderStockListItem" in html
    assert "function openStockCard" in html
    assert "function closeStockCard" in html
    assert "stock-card-backdrop" in html
    assert "stock-card-modal" in html
    assert "onclick=\"openStockCard(" in html


def test_generate_renders_sortable_column_headers_not_dropdown(tmp_path):
    """Cody明確要求拿掉排序下拉選單，改成「點選欄位名稱就排序」——確認個股列表是
    <table>搭配可點擊的欄位標題(sortStockList)，不是<select>下拉選單。"""
    output_path = tmp_path / "index.html"
    meta_perf = [{"meta_name": "族群A", "avg_change_pct": 2.0, "up_count": 1, "down_count": 0, "flat_count": 0}]
    universe_df = pd.DataFrame([{"stock_id": "1000", "stock_name": "測試股", "meta_sector": "族群A"}])
    prices_df = pd.DataFrame([{"stock_id": "1000", "close": 100.0, "change_pct": 2.0}])

    generate(date(2026, 7, 22), meta_perf, universe_df, {}, {}, prices_df, {}, output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert "function sortStockList" in html
    assert 'class="stock-list-table"' in html
    assert "onclick=\"sortStockList(this.parentElement,'pct')\"" in html
    assert "onclick=\"sortStockList(this.parentElement,'close')\"" in html
    assert "onclick=\"sortStockList(this.parentElement,'id')\"" in html
    assert "<select" not in html
    assert "sortPanelStocks" not in html  # 下拉選單機制已經整個拿掉


def test_generate_calls_render_panel_stocks_after_panel_is_attached_to_dom(tmp_path):
    """Cody回報「族群點開後列表要點欄位才會出現」——實際用jsdom模擬點擊重現過：
    renderPanelStocks()在selectGroup()裡原本是在panel.insertAdjacentElement()「之前」
    呼叫，這時panel還是離線節點，document.getElementById('panelStocksWrap')找不到東西，
    wrap===null的guard擋掉，表格永遠是空的，直到點擊欄位排序時panel已經在DOM裡、
    renderPanelStocks()才第一次真的render出東西。這裡用原始碼順序守住這個修正：
    selectGroup()裡renderPanelStocks()呼叫必須出現在insertAdjacentElement()「之後」。"""
    output_path = tmp_path / "index.html"
    meta_perf = [{"meta_name": "族群A", "avg_change_pct": 2.0, "up_count": 1, "down_count": 0, "flat_count": 0}]
    universe_df = pd.DataFrame([{"stock_id": "1000", "stock_name": "測試股", "meta_sector": "族群A"}])
    prices_df = pd.DataFrame([{"stock_id": "1000", "close": 100.0, "change_pct": 2.0}])

    generate(date(2026, 7, 22), meta_perf, universe_df, {}, {}, prices_df, {}, output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    select_group_start = html.index("function selectGroup(")
    select_group_end = html.index("\n}", html.index("/* ── 個股/族群搜尋 ── */")) if "/* ── 個股/族群搜尋 ── */" in html else len(html)
    select_group_body = html[select_group_start:select_group_end]

    insert_pos = select_group_body.index("insertAdjacentElement(")
    render_pos = select_group_body.index("renderPanelStocks();")
    assert render_pos > insert_pos, (
        "renderPanelStocks() 必須在 panel.insertAdjacentElement() 之後呼叫，"
        "否則panel還沒掛進document，document.getElementById找不到tbody，表格永遠是空的"
    )
