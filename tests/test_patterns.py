import numpy as np
import pandas as pd
import pytest
from screener.patterns import _calc_streak, _calc_vol_price_score, _calc_chips_score


def test_streak_consecutive_buy():
    s = pd.Series([100, -50, 200, 300, 400])
    assert _calc_streak(s) == 3   # 最後3日連續正


def test_streak_consecutive_sell():
    s = pd.Series([100, 200, -100, -200, -300])
    assert _calc_streak(s) == -3


def test_streak_zero():
    s = pd.Series([100, 200, 0])
    assert _calc_streak(s) == 0


def _make_price_series(closes, volumes):
    return pd.Series(closes, dtype=float), pd.Series(volumes, dtype=float)


def test_vol_price_score_up():
    # 量增價漲 → +2
    closes = [10.0] * 20 + [10.5]   # 今日漲 5%
    volumes = [1_000_000] * 20 + [2_000_000]  # 今日量 2x 均量
    c, v = _make_price_series(closes, volumes)
    assert _calc_vol_price_score(c, v) == 2


def test_vol_price_score_down():
    # 量增價跌 → -2
    closes = [10.0] * 20 + [9.5]
    volumes = [1_000_000] * 20 + [2_000_000]
    c, v = _make_price_series(closes, volumes)
    assert _calc_vol_price_score(c, v) == -2


def test_vol_price_score_diverge():
    # 量減價漲（背離）→ -1
    closes = [10.0] * 20 + [10.5]
    volumes = [1_000_000] * 20 + [500_000]   # 量減
    c, v = _make_price_series(closes, volumes)
    assert _calc_vol_price_score(c, v) == -1


def test_chips_score_foreign_streak():
    inst = pd.DataFrame({
        'foreign_net': [100_000, 200_000, 150_000],
        'trust_net': [0, 0, 0],
    })
    # 外資連買 3 日 → +3
    assert _calc_chips_score(inst) == 3


def test_chips_score_both_streaks():
    inst = pd.DataFrame({
        'foreign_net': [100_000, 200_000],
        'trust_net': [50_000, 80_000],
    })
    # 外資連買 2 + 投信連買 2 → +4
    assert _calc_chips_score(inst) == 4


from screener.patterns import detect_double_bottom, detect_double_top


def _make_ohlcv(closes, volumes=None):
    """Build minimal DataFrame for pattern detection."""
    n = len(closes)
    if volumes is None:
        volumes = [1_000_000] * n
    return pd.DataFrame({
        'close':  closes,
        'high':   [c * 1.005 for c in closes],
        'low':    [c * 0.995 for c in closes],
        'volume': volumes,
    })


def test_double_bottom_detected():
    # 前置高點 106（106/90=1.178 ≥ 1.15 ✓），兩底間距 25 根 ≥ 10 ✓，第二底距今 6 根 ≤ 10 ✓
    closes = (
        [106.0] * 12 +
        [95.0, 92.0, 90.0, 92.0, 94.0] +      # first bottom ~idx 14 (90)
        [96.0, 98.0, 98.0, 97.0, 98.0] * 4 +  # bounce / neckline ~98 (8.9%+ bounce from 90)
        [95.0, 92.0, 90.5, 92.0, 94.0] +      # second bottom ~idx 39 (90.5)
        [95.0, 96.0, 99.0]                     # today 99 > neckline 98
    )
    vols = [1_000_000] * (len(closes) - 1) + [2_000_000]
    df = _make_ohlcv(closes, vols)
    assert detect_double_bottom(df)


def test_double_bottom_not_detected_no_bounce():
    # Two lows but bounce only 2% (< 5%)
    closes = [100.0] * 10 + [90.0, 91.0, 90.5] + [92.0] * 10 + [90.2, 91.0, 92.5]
    df = _make_ohlcv(closes)
    assert detect_double_bottom(df) is False


def test_double_top_detected():
    closes = (
        [90.0] * 12 +
        [95.0, 98.0, 100.0, 98.0, 95.0] +   # first top ~100
        [92.0, 91.0, 91.0, 92.0, 91.0] * 4 +  # pullback / neckline ~91
        [94.0, 97.0, 99.8, 97.0, 94.0] +   # second top ~99.8
        [92.0, 91.0, 90.0]                  # today breaks neckline downward
    )
    vols = [1_000_000] * (len(closes) - 1) + [2_000_000]
    df = _make_ohlcv(closes, vols)
    assert detect_double_top(df)


def test_double_top_not_detected_when_price_holds():
    closes = [90.0] * 10 + [100.0, 98.0, 100.5] + [92.0] * 10 + [99.5, 98.0, 95.0]
    df = _make_ohlcv(closes)
    assert detect_double_top(df) is False


from screener.patterns import (
    detect_triangle_up, detect_triangle_down,
    detect_ascending_triangle, detect_falling_wedge,
    detect_breakout_confirm, detect_box_consolidation,
    detect_vcp,
)

# ── Triangle / Wedge helpers ─────────────────────────────────────────────────
# All tests need 62 bars (1 padding + 60 hist + 1 today).
# hist = df.iloc[-61:-1]; hist[i] == df[i+1] when len(df)==62.
# Peaks/troughs placed at hist[15]/hist[45] and hist[20]/hist[50]
# with _TRI_PIVOT_R=4 neighbours on each side set to enforce strict local extrema.

def _tri_df(highs, lows, closes, vols):
    return pd.DataFrame({'close': closes, 'high': highs, 'low': lows, 'volume': vols})


def _set_peak(highs, df_idx, peak_val, surround_val):
    highs[df_idx] = peak_val
    for j in range(df_idx - 4, df_idx + 5):
        if j != df_idx:
            highs[j] = surround_val


def _set_trough(lows, df_idx, trough_val, surround_val):
    lows[df_idx] = trough_val
    for j in range(df_idx - 4, df_idx + 5):
        if j != df_idx:
            lows[j] = surround_val


def test_triangle_up_detected():
    # 收斂三角：高點 hist[15]=108→hist[45]=104（遞減），低點 hist[20]=92→hist[50]=96（遞增）
    # hs=-0.133, hi=110; ls=+0.133, li=89.33; res_today=102.0, res_yest=102.13
    N = 62
    highs  = [100.0] * N
    lows   = [100.0] * N
    closes = [100.0] * N
    vols   = [1_000_000] * N

    _set_peak(highs,   16, 108.0, 105.0)   # hist[15]: peak1
    _set_peak(highs,   46, 104.0, 101.5)   # hist[45]: peak2 (lower → hs<0)
    _set_trough(lows,  21,  92.0,  95.0)   # hist[20]: trough1
    _set_trough(lows,  51,  96.0,  98.0)   # hist[50]: trough2 (higher → ls>0)

    closes[60] = 100.0   # yesterday: below res_yest ≈ 102.13
    highs[60]  = 101.0
    lows[60]   = 99.0

    closes[61] = 103.0   # today: above res_today=102.0 and above yesterday
    highs[61]  = 104.0
    lows[61]   = 101.5

    for j in range(1, 31): vols[j] = 1_200_000   # early hist: higher vol
    vols[61] = 1_800_000                           # breakout vol ≥ MA20×1.5

    assert detect_triangle_up(_tri_df(highs, lows, closes, vols))


def test_triangle_down_detected():
    # 下降三角：高點 hist[15]=108→hist[45]=104（遞減），低點 hist[20]=95→hist[50]=95.5（近水平）
    # |t2-t1|/t1=0.005<3%; ls≈0.017; |ls|/mean=0.00017<0.002
    # sup_today=95.667, sup_yest=95.65; yesterday close=96 (above), today=94 (below)
    N = 62
    highs  = [100.0] * N
    lows   = [100.0] * N
    closes = [100.0] * N
    vols   = [1_000_000] * N

    _set_peak(highs,   16, 108.0, 105.0)   # hist[15]: peak1
    _set_peak(highs,   46, 104.0, 101.5)   # hist[45]: peak2 (lower → hs<0)
    _set_trough(lows,  21,  95.0,  97.5)   # hist[20]: trough1
    _set_trough(lows,  51,  95.5,  97.5)   # hist[50]: trough2 (flat ≈ trough1)

    closes[60] = 96.0    # yesterday: above flat support ≈ 95.65
    highs[60]  = 97.0
    lows[60]   = 95.8

    closes[61] = 94.0    # today: below sup_today=95.667 and below yesterday
    highs[61]  = 95.5
    lows[61]   = 93.5

    vols[61] = 1_800_000   # breakdown vol ≥ MA20×1.5

    assert detect_triangle_down(_tri_df(highs, lows, closes, vols))


def test_ascending_triangle_detected():
    # 上升三角：高點 hist[15]=105→hist[45]=105.5（水平，差0.5%<3%），低點遞增
    # hs≈+0.017→|hs|/mean=0.00017<0.002; res_today=105.75, yesterday=104.0
    N = 62
    highs  = [102.0] * N
    lows   = [100.0] * N
    closes = [100.0] * N
    vols   = [1_000_000] * N

    _set_peak(highs,   16, 105.0, 103.0)   # hist[15]: peak1
    _set_peak(highs,   46, 105.5, 103.0)   # hist[45]: peak2 (nearly same height)
    _set_trough(lows,  21,  92.0,  95.0)   # hist[20]: trough1
    _set_trough(lows,  51,  96.0,  98.0)   # hist[50]: trough2 (higher → ls>0)

    closes[60] = 104.0   # yesterday: below res_yest≈105.73
    highs[60]  = 105.0
    lows[60]   = 103.0

    closes[61] = 107.0   # today: above res_today=105.75 and above yesterday
    highs[61]  = 108.0
    lows[61]   = 106.0

    for j in range(1, 31): vols[j] = 1_200_000
    vols[61] = 1_800_000

    assert detect_ascending_triangle(_tri_df(highs, lows, closes, vols))


def test_falling_wedge_detected():
    # 下降楔型：高點 hist[15]=110→hist[45]=100（hs=-10/30=-0.333），低點 hist[20]=95→hist[50]=88（ls=-7/30=-0.233）
    # hs(-0.333) < ls(-0.233) < 0 ✓; gap收斂(15.33→9.43)
    # res_today=95.0, res_yest=95.33; yesterday=94.0 (below), today=97.0 (above)
    N = 62
    highs  = [95.0] * N   # default below all surroundings
    lows   = [100.0] * N
    closes = [100.0] * N
    vols   = [1_000_000] * N

    _set_peak(highs,   16, 110.0, 107.0)   # hist[15]: peak1=110
    _set_peak(highs,   46, 100.0,  97.0)   # hist[45]: peak2=100 → hs=-10/30=-0.333
    _set_trough(lows,  21,  95.0,  98.0)   # hist[20]: trough1
    _set_trough(lows,  51,  88.0,  91.0)   # hist[50]: trough2 (lower → ls<0, but less steep)

    closes[60] = 94.0    # yesterday: below res_yest≈95.33
    highs[60]  = 94.5
    lows[60]   = 93.0

    closes[61] = 97.0    # today: above res_today=95.0 and above yesterday
    highs[61]  = 98.0
    lows[61]   = 95.5

    for j in range(1, 31): vols[j] = 1_200_000
    vols[61] = 1_800_000

    assert detect_falling_wedge(_tri_df(highs, lows, closes, vols))


def test_breakout_confirm_detected():
    # Stage 2 起漲：bars 0-19 高位(120)→ bars 20-59 低位整理(88)→ bars 60-79 回升(95→130)
    # 20日前：MA20(88) < MA60(98.3) ✓；今日：MA20(112) > MA60(96) > MA60走平(-2.4%) ✓
    closes = (
        [120.0] * 20                              # 高位（拉高 MA60_20d_ago）
        + [88.0] * 40                             # 整理低位（MA20 被壓低）
        + list(np.linspace(95, 130, 20))          # 回升起漲
    )
    vols = [1_000_000] * 69 + [2_000_000] + [1_000_000] * 10  # 爆量在 bar 69
    df = _make_ohlcv(closes, vols)
    assert detect_breakout_confirm(df)


def test_breakout_confirm_not_detected_already_bullish():
    # 20日前 MA20 已 > MA60（早已多頭）→ 不是拐點，拒絕
    closes = list(np.linspace(80, 130, 80))   # 全段線性上升
    vols   = [1_000_000] * 79 + [2_000_000]
    df = _make_ohlcv(closes, vols)
    assert not detect_breakout_confirm(df)


def test_breakout_confirm_not_detected_bearish():
    # MA60 強烈下跌（空頭趨勢）→ 拒絕
    closes = list(np.linspace(150, 80, 80))   # 全段下跌
    vols   = [1_000_000] * 79 + [2_000_000]
    df = _make_ohlcv(closes, vols)
    assert not detect_breakout_confirm(df)


def test_breakout_confirm_not_detected_no_vol_spike():
    # 條件全過但無爆量 → 拒絕
    closes = (
        [120.0] * 20
        + [88.0] * 40
        + list(np.linspace(95, 130, 20))
    )
    vols = [1_000_000] * 80   # 量均勻，無爆量
    df = _make_ohlcv(closes, vols)
    assert not detect_breakout_confirm(df)


def test_box_consolidation_detected():
    # 20 days tight range: 99-101 (2%), today still inside
    closes = [99.0, 100.0, 101.0, 100.5] * 5 + [100.2]
    df = _make_ohlcv(closes)
    assert detect_box_consolidation(df) is True


def test_box_consolidation_broken():
    # Range tight but today broke out above
    closes = [99.0, 100.0, 101.0, 100.5] * 5 + [108.0]
    df = _make_ohlcv(closes)
    assert detect_box_consolidation(df) is False


def _make_vcp_df(
    prior_close_override: float | None = None,
    second_pullback_pct: float = 0.031,
) -> pd.DataFrame:
    """
    建立 70 列 VCP 測試資料（手工設計，確保嚴格局部高/低點）。

    結構：
      rows  0-24:  前置上升趨勢  80→104
      rows 25-26:  急漲 108→111（peak1 at row 26）
      rows 27-35:  第一波回檔 110→97（trough at row 33）
      rows 36-43:  反彈 101.5→107（peak2 at row 41）
      rows 44-49:  第二波回檔 105→pb2_low（trough at row 49）
      rows 50-68:  收縮整理（明確高於 pb2_low）
      row  69:     突破日 109
    """
    n = 70
    closes  = np.zeros(n, dtype=float)
    volumes = np.full(n, 1_200_000.0)

    # 前置上升
    for i in range(25):
        closes[i] = 80.0 + i

    # 急漲至峰值1
    closes[25] = 108.0
    closes[26] = 111.0   # ← PEAK 1

    # 第一波回檔（讓 97.0 嚴格低於周圍5根）
    pb1 = [110.0, 107.0, 105.0, 102.0, 100.0, 98.0, 97.0, 98.5, 100.0]
    for i, c in enumerate(pb1):
        closes[27 + i] = c
        volumes[27 + i] = 1_800_000   # 量大
    # closes[33] = 97.0 ← TROUGH 1 (strictly lower than [30..36])

    # 反彈至峰值2（明確高低，不與相鄰重複）
    rec2 = [101.5, 103.0, 104.5, 105.8, 106.5, 107.0, 106.2, 105.0]
    for i, c in enumerate(rec2):
        closes[36 + i] = c
    # closes[41] = 107.0 ← PEAK 2

    # 第二波回檔（從 105.0 起始，不等於 peak2=107.0）
    pk2 = 107.0
    pb2_low = pk2 * (1 - second_pullback_pct)
    pb2_vals = np.linspace(105.0, pb2_low, 6)
    for i, c in enumerate(pb2_vals):
        closes[44 + i] = c
        volumes[44 + i] = 900_000     # 量縮
    # closes[49] = pb2_low ← TROUGH 2

    # 收縮整理（從 pb2_low+0.3 開始，嚴格高於 trough2）
    for i in range(19):
        closes[50 + i] = pb2_low + 0.3 + i * 0.05
        volumes[50 + i] = 700_000

    # 突破日（突破 peak2=107.0）
    closes[69] = 109.0
    volumes[69] = 3_000_000

    if prior_close_override is not None:
        closes[5] = prior_close_override

    return pd.DataFrame({
        'close':  closes,
        'high':   closes * 1.005,
        'low':    closes * 0.995,
        'volume': volumes,
    })


def test_vcp_detected():
    """標準兩波量縮突破 → 應偵測為 VCP。"""
    df = _make_vcp_df()
    assert detect_vcp(df)


def test_vcp_not_detected_downtrend():
    """前置收盤價偏高（股票已在高位或下跌中）→ 非 VCP。"""
    # prior_close (row 5) = 112, first peak ≈ 111 → prior_close >= first_peak * 0.95 → 拒絕
    df = _make_vcp_df(prior_close_override=112.0)
    assert detect_vcp(df) is False


def test_vcp_not_detected_pullback_not_contracting():
    """第二波回檔 > 第一波 × 80% → 不符合量縮收斂條件。"""
    # second_pullback_pct=0.12: 第二波回檔 12% > 第一波 11.7% * 80% = 9.4%
    df = _make_vcp_df(second_pullback_pct=0.12)
    assert detect_vcp(df) is False


def test_scan_patterns_returns_list():
    """Integration smoke test: scan_patterns 回傳 list，每筆有必要欄位。"""
    from screener.patterns import scan_patterns
    results = scan_patterns("2026-06-26")   # 用已知有資料的日期
    assert isinstance(results, list)
    if results:
        r = results[0]
        for key in ("stock_id", "stock_name", "score", "patterns", "vol_ratio"):
            assert key in r, f"Missing key: {key}"
        assert isinstance(r["patterns"], list)
        # Score range sanity check
        assert -20 <= r["score"] <= 20


import duckdb
from screener.patterns import calc_composite_score, scan_and_track
from screener.patterns import calc_accumulation_score


def _base_score_kwargs(**overrides):
    kwargs = dict(
        foreign_streak=0, trust_streak=0, patterns=[], vol_ratio=1.0,
        lv12_15_pct=None, sh_streak=0, margin_alert_pct=0.0, margin_divergence=False,
    )
    kwargs.update(overrides)
    return kwargs


def test_calc_composite_score_margin_divergence_is_strongest_margin_penalty():
    """margin_divergence=True 該扣 15 分，比 margin_alert_pct>=10 的 -10 分更重——
    這是這次修復前 scan_patterns()/scan_and_track() 永遠傳 False、導致這個分支
    永遠不會被觸發的那個 bug 對應的分數邏輯，直接測 calc_composite_score() 本身
    確保公式正確，不用依賴會寫入真實 DB 的 scan_and_track() 整合測試。"""
    with_divergence = calc_composite_score(**_base_score_kwargs(margin_divergence=True))
    with_high_alert = calc_composite_score(**_base_score_kwargs(margin_alert_pct=10.0))
    with_low_alert = calc_composite_score(**_base_score_kwargs(margin_alert_pct=5.0))
    baseline = calc_composite_score(**_base_score_kwargs())

    assert with_divergence == baseline - 15
    assert with_high_alert == baseline - 10
    assert with_low_alert == baseline - 5
    assert with_divergence < with_high_alert < with_low_alert < baseline


def test_calc_composite_score_margin_divergence_overrides_alert_pct_branch():
    """margin_divergence=True 時就算 margin_alert_pct 也很高，也只扣 15 分
    （elif 分支，不會兩個都扣），跟 calc_composite_score() 的 docstring/實作一致。"""
    score = calc_composite_score(**_base_score_kwargs(margin_divergence=True, margin_alert_pct=20.0))
    baseline = calc_composite_score(**_base_score_kwargs())
    assert score == baseline - 15


def _base_acc_kwargs(**overrides):
    kwargs = dict(
        foreign_streak=0, trust_streak=0, sh_streak=0,
        holder_net_lots=0, recent_return=1.0,
    )
    kwargs.update(overrides)
    return kwargs


def test_calc_accumulation_score_only_counts_buying_not_selling():
    """只算進貨、不猜出貨：連賣（streak<0）不倒扣分，foreign_pts 應為 0（不是負數）。"""
    selling = calc_accumulation_score(**_base_acc_kwargs(foreign_streak=-5))
    baseline = calc_accumulation_score(**_base_acc_kwargs(foreign_streak=0))
    assert selling["score"] == baseline["score"], "連賣(-5)跟不買(0)的外資貢獻應該一樣，都是 0 分，不倒扣"
    assert selling["foreign_buy_days"] == 0


def test_calc_accumulation_score_price_gate_halves_score_when_not_confirmed():
    """同樣的進貨強度，recent_return<=0（未 confirm）分數應是 confirm 時的一半，
    price_confirmed 旗標要對應正確。"""
    confirmed = calc_accumulation_score(**_base_acc_kwargs(foreign_streak=5, recent_return=1.0))
    not_confirmed = calc_accumulation_score(**_base_acc_kwargs(foreign_streak=5, recent_return=-1.0))

    assert confirmed["price_confirmed"] is True
    assert not_confirmed["price_confirmed"] is False
    assert not_confirmed["score"] == round(confirmed["score"] / 2)


def test_calc_accumulation_score_recent_return_none_is_not_confirmed():
    """recent_return 為 None（新股/資料不足）要視為未 confirm，不是當作 confirmed。"""
    result = calc_accumulation_score(**_base_acc_kwargs(foreign_streak=5, recent_return=None))
    assert result["price_confirmed"] is False


def test_calc_accumulation_score_caps_foreign_trust_holder_points():
    """封頂：foreign_streak=10 時 foreign_pts 應封頂在 40（不是 10*8=80）。
    用 foreign_streak=5(40分,封頂) vs foreign_streak=10(仍40分,封頂) 比較分數相同來驗證。"""
    at_cap = calc_accumulation_score(**_base_acc_kwargs(foreign_streak=5, recent_return=1.0))
    over_cap = calc_accumulation_score(**_base_acc_kwargs(foreign_streak=10, recent_return=1.0))
    assert at_cap["score"] == over_cap["score"], "foreign_streak 超過封頂對應的日數，分數不該再增加"
    assert over_cap["foreign_buy_days"] == 10, "foreign_buy_days 本身如實回傳，只有算分時封頂"


def test_calc_accumulation_score_weakening_when_both_streaks_non_positive():
    """外資與投信 streak 皆 <= 0 時應標記 weakening=True，holder_pts 也應被歸零
    （即使 sh_streak 本身是正數）。"""
    result = calc_accumulation_score(**_base_acc_kwargs(
        foreign_streak=0, trust_streak=0, sh_streak=3, holder_net_lots=100, recent_return=1.0,
    ))
    assert result["weakening"] is True


def test_calc_accumulation_score_weakening_when_holder_net_lots_turns_negative():
    """大戶當週由增轉減（holder_net_lots < 0）應標記 weakening=True，
    即使外資/投信仍在連買。"""
    result = calc_accumulation_score(**_base_acc_kwargs(
        foreign_streak=3, trust_streak=3, sh_streak=2, holder_net_lots=-500, recent_return=1.0,
    ))
    assert result["weakening"] is True


def test_calc_accumulation_score_not_weakening_when_any_source_buying_and_holder_not_negative():
    """外資或投信有連買、且大戶張數沒有轉負，不該標記 weakening。"""
    result = calc_accumulation_score(**_base_acc_kwargs(
        foreign_streak=3, trust_streak=0, sh_streak=2, holder_net_lots=100, recent_return=1.0,
    ))
    assert result["weakening"] is False


def test_calc_accumulation_score_label_progression():
    """label 導出優先序：weakening 最優先覆蓋一切；其次未 confirm 是「整理」；
    否則依 score>=40 分「進貨」或「整理」。"""
    weakening_case = calc_accumulation_score(**_base_acc_kwargs(
        foreign_streak=0, trust_streak=0, sh_streak=0, holder_net_lots=0, recent_return=1.0,
    ))
    assert weakening_case["label"] == "轉弱"

    not_confirmed_case = calc_accumulation_score(**_base_acc_kwargs(
        foreign_streak=5, trust_streak=5, sh_streak=2, holder_net_lots=100, recent_return=-1.0,
    ))
    assert not_confirmed_case["weakening"] is False
    assert not_confirmed_case["label"] == "整理"

    strong_buy_case = calc_accumulation_score(**_base_acc_kwargs(
        foreign_streak=5, trust_streak=5, sh_streak=2, holder_net_lots=100, recent_return=1.0,
    ))
    assert strong_buy_case["score"] >= 40
    assert strong_buy_case["label"] == "進貨"

    weak_buy_case = calc_accumulation_score(**_base_acc_kwargs(
        foreign_streak=1, trust_streak=0, sh_streak=0, holder_net_lots=100, recent_return=1.0,
    ))
    assert weak_buy_case["weakening"] is False
    assert weak_buy_case["score"] < 40
    assert weak_buy_case["label"] == "整理"


def _seed_scan_and_track_db(db_path):
    """建立 scan_and_track() 需要的最小 schema，並預先塞一筆 'active' 的
    pattern_signals 訊號（繞過真的觸發形態偵測器的複雜度），讓 stock_id
    直接出現在最終結果裡，藉此驗證 margin_divergence_data 有沒有正確接上。"""
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE daily_prices (
            stock_id VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE,
            close DOUBLE, volume BIGINT, change_pct DOUBLE
        )
    """)
    con.execute("CREATE TABLE institutional (stock_id VARCHAR, date DATE, foreign_net BIGINT, trust_net BIGINT)")
    con.execute("CREATE TABLE margin (stock_id VARCHAR, date DATE, margin_balance BIGINT, margin_change BIGINT)")
    con.execute("CREATE TABLE shareholder (stock_id VARCHAR, date DATE, lv12_15_pct DOUBLE, streak INTEGER)")
    for d in ["2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02", "2026-07-03"]:
        con.execute(
            "INSERT INTO daily_prices VALUES ('9999', ?, 100, 101, 99, 100, 1000, 0.0)", [d]
        )
    con.execute("""
        CREATE TABLE pattern_signals (
            stock_id     VARCHAR NOT NULL, pattern VARCHAR NOT NULL, signal_date DATE NOT NULL,
            anchor DOUBLE, stop DOUBLE, target DOUBLE, rr DOUBLE,
            status VARCHAR DEFAULT 'active', last_check DATE,
            days_held INTEGER DEFAULT 0, consec_below INTEGER DEFAULT 0,
            PRIMARY KEY (stock_id, pattern, signal_date)
        )
    """)
    con.execute("""
        INSERT INTO pattern_signals VALUES
        ('9999', '雙底', '2026-07-01', 95.0, 90.0, 110.0, 3.0, 'active', NULL, 0, 0)
    """)
    con.close()


def test_scan_and_track_applies_margin_divergence_penalty_for_flagged_stock(tmp_path):
    """main.py 已經算好的 get_margin_divergence() 結果（bearish 清單）要能讓
    scan_and_track() 對名單內的股票套用真正的 margin_divergence 扣分，
    不再是修復前那樣永遠寫死 False。"""
    db_with = tmp_path / "with.db"
    _seed_scan_and_track_db(db_with)
    results_with = scan_and_track(
        "2026-07-03", db_path=str(db_with),
        margin_divergence_data={"bearish": [{"stock_id": "9999"}], "bullish": [], "days_used": 5},
    )

    db_without = tmp_path / "without.db"
    _seed_scan_and_track_db(db_without)
    results_without = scan_and_track(
        "2026-07-03", db_path=str(db_without),
        margin_divergence_data={"bearish": [], "bullish": [], "days_used": 5},
    )

    assert len(results_with) == 1
    assert len(results_without) == 1
    assert results_with[0]["composite_score"] == results_without[0]["composite_score"] - 15


def test_scan_and_track_defaults_to_no_divergence_when_data_not_passed(tmp_path):
    """沒有傳 margin_divergence_data（例如舊呼叫端）時，視同沒有背離資料，
    不該報錯，也不該誤扣分。"""
    db_path = tmp_path / "test.db"
    _seed_scan_and_track_db(db_path)

    results = scan_and_track("2026-07-03", db_path=str(db_path))

    assert len(results) == 1


import math


def test_calc_accumulation_score_handles_none_sh_streak_without_crash():
    """sh_streak 為 None（新股，集保資料還沒有這檔）不該 crash，holder_pts 當 0 貢獻。
    foreign_streak=3 讓 weakening=False，確保 sh_streak 的值真的會流到最終 round()，
    不會被 weakening 的 holder_pts=0 短路掉（回歸：原本兩個測試 foreign/trust_streak 都是
    預設 0，weakening 恆為 True，NaN 根本沒機會進到 round()，測試沒真正驗證到防呆）。"""
    result = calc_accumulation_score(**_base_acc_kwargs(foreign_streak=3, sh_streak=None, recent_return=1.0))
    assert result["score"] is not None
    assert not (isinstance(result["score"], float) and math.isnan(result["score"]))


def test_calc_accumulation_score_handles_nan_sh_streak_without_crash():
    """sh_streak 為 NaN（DuckDB NULL 經 pandas 讀回）不該 crash，等同 None 處理。
    foreign_streak=3 讓 weakening=False（理由同上一個測試），這是真正會 crash 的路徑：
    pre-guard 版本對這個輸入實測會拋 ValueError: cannot convert float NaN to integer。"""
    result = calc_accumulation_score(**_base_acc_kwargs(foreign_streak=3, sh_streak=float("nan"), recent_return=1.0))
    assert result["score"] is not None
    assert not (isinstance(result["score"], float) and math.isnan(result["score"]))


def test_calc_accumulation_score_handles_none_holder_net_lots():
    """holder_net_lots 為 None（還沒有兩週大戶資料可比較）：holder_pts 仍走 sh_streak
    正常計算，但 weakening 的『大戶由增轉減』判斷略過（不因為 None 就觸發或跳過整體 weakening，
    只是那個 OR 分支不成立）。"""
    result = calc_accumulation_score(**_base_acc_kwargs(
        foreign_streak=3, trust_streak=3, sh_streak=2, holder_net_lots=None, recent_return=1.0,
    ))
    assert result["weakening"] is False
    assert result["holder_net_lots"] is None
    assert result["score"] > 0, "holder_net_lots=None 不該讓 holder_pts 被歸零，sh_streak 仍要計分"


from screener.patterns import (
    _shareholder_history_index, _shareholder_as_of,
    _recent_return_index, _recent_return_as_of,
)


def _make_shareholder_db(tmp_path, rows):
    """rows: list of (stock_id, 'YYYY-MM-DD', streak, lv12_shares, lv15_shares)"""
    db = str(tmp_path / "sh.db")
    con = duckdb.connect(db)
    con.execute("""
        CREATE TABLE shareholder (
            stock_id VARCHAR, date DATE, lv12_15_pct DOUBLE, lv12_15_cnt INTEGER,
            lv12_15_shares BIGINT, total_shares BIGINT, week_chg DOUBLE, streak INTEGER,
            lv12_shares BIGINT, lv12_pct DOUBLE, lv15_shares BIGINT, lv15_pct DOUBLE
        )
    """)
    con.executemany(
        "INSERT INTO shareholder (stock_id, date, streak, lv12_shares, lv15_shares) VALUES (?, ?, ?, ?, ?)",
        [(s, pd.to_datetime(d).date(), streak, lv12, lv15) for (s, d, streak, lv12, lv15) in rows],
    )
    con.close()
    return db


def test_shareholder_as_of_uses_historical_week_not_latest(tmp_path):
    """驗證「as of 某日」查的是那天當下最新的一週資料，不是資料庫裡整體最新一筆
    （最容易犯的 bug：forward-fill 方向抓錯，見設計 spec 測試策略#2）。"""
    rows = [
        ("2330", "2026-05-01", 1, 100000, 50000),   # 第1週
        ("2330", "2026-05-08", 2, 120000, 55000),   # 第2週：lv12_chg=+20000, lv15_chg=+5000
        ("2330", "2026-05-15", 3, 150000, 40000),   # 第3週：lv12_chg=+30000, lv15_chg=-15000
    ]
    db = _make_shareholder_db(tmp_path, rows)
    index = _shareholder_history_index(db)

    streak, holder_net_lots = _shareholder_as_of(index, "2330", pd.Timestamp("2026-05-10"))
    assert streak == 2
    assert holder_net_lots == 25000  # 用第2週的變化，不是第3週的 15000

    streak1, holder1 = _shareholder_as_of(index, "2330", pd.Timestamp("2026-05-03"))
    assert streak1 == 1
    assert holder1 is None  # 第1週沒有前一週可比

    streak0, holder0 = _shareholder_as_of(index, "2330", pd.Timestamp("2026-04-01"))
    assert streak0 is None
    assert holder0 is None  # 所有資料之前，查無資料


def test_recent_return_as_of_uses_only_past_data(tmp_path):
    """近5日報酬「as of d_ts」只能用 <= d_ts 的收盤價，不能偷看未來
    （回測最基本的 no-lookahead 要求，見設計 spec 資料索引細節段落）。"""
    db = str(tmp_path / "px.db")
    con = duckdb.connect(db)
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, close DOUBLE)")
    rows = [("2330", f"2026-05-{d:02d}", 100.0 + d) for d in range(1, 11)]
    con.executemany("INSERT INTO daily_prices VALUES (?, ?, ?)",
                     [(s, pd.to_datetime(d).date(), c) for (s, d, c) in rows])
    con.close()

    index = _recent_return_index(db)
    ret = _recent_return_as_of(index, "2330", pd.Timestamp("2026-05-06"), days=5)
    assert ret == round((106.0 - 101.0) / 101.0 * 100, 2)

    ret_insufficient = _recent_return_as_of(index, "2330", pd.Timestamp("2026-05-03"), days=5)
    assert ret_insufficient is None


from screener.patterns import scan_accumulation_score


def _make_full_accumulation_db(tmp_path):
    """建 institutional + shareholder + daily_prices 三張最小表，模擬 2330 在
    訊號日 2026-05-08 當下：外資連買5日(全正)、投信連買3日(前2天賣、後3天買)、
    大戶第2週資料(streak=2, holder_net_lots=20000+5000=25000)、近5日報酬>0。"""
    db = str(tmp_path / "acc.db")
    con = duckdb.connect(db)
    con.execute("CREATE TABLE institutional (stock_id VARCHAR, date DATE, foreign_net BIGINT, trust_net BIGINT, dealer_net BIGINT, total_net BIGINT)")
    con.execute("""
        CREATE TABLE shareholder (
            stock_id VARCHAR, date DATE, lv12_15_pct DOUBLE, lv12_15_cnt INTEGER,
            lv12_15_shares BIGINT, total_shares BIGINT, week_chg DOUBLE, streak INTEGER,
            lv12_shares BIGINT, lv12_pct DOUBLE, lv15_shares BIGINT, lv15_pct DOUBLE
        )
    """)
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT, change DOUBLE, change_pct DOUBLE)")

    inst_rows = [
        ("2330", "2026-05-04", 1000, -500),
        ("2330", "2026-05-05", 1000, -500),
        ("2330", "2026-05-06", 1000, 800),
        ("2330", "2026-05-07", 1000, 800),
        ("2330", "2026-05-08", 1000, 800),
    ]
    con.executemany(
        "INSERT INTO institutional VALUES (?, ?, ?, ?, 0, ?)",
        [(s, pd.to_datetime(d).date(), f, t, f + t) for (s, d, f, t) in inst_rows],
    )

    sh_rows = [
        ("2330", "2026-05-01", 1, 100000, 50000),
        ("2330", "2026-05-08", 2, 120000, 55000),
    ]
    con.executemany(
        "INSERT INTO shareholder (stock_id, date, streak, lv12_shares, lv15_shares) VALUES (?, ?, ?, ?, ?)",
        [(s, pd.to_datetime(d).date(), streak, lv12, lv15) for (s, d, streak, lv12, lv15) in sh_rows],
    )

    px_rows = [("2330", f"2026-05-{d:02d}", 100.0 + d) for d in range(1, 9)]
    con.executemany(
        "INSERT INTO daily_prices (stock_id, date, close, change_pct) VALUES (?, ?, ?, 0.0)",
        [(s, pd.to_datetime(d).date(), c) for (s, d, c) in px_rows],
    )
    con.close()
    return db


def test_scan_accumulation_score_computes_score_for_signal_date(tmp_path):
    """驗證 scan_accumulation_score() 在某一天的訊號清單裡，每檔股票的分數是用
    calc_accumulation_score() 對「as of 那天」的五個輸入算出來的，cache 存了完整明細。
    手動推演：foreign_streak=5(40分) + trust_streak=3(18分) + sh_streak=2(14分)
    = 72分；weakening=False(holder_net_lots=25000>0)；近5日報酬(108-103)/103*100=4.85%>0
    → confirmed → gate=1.0 → score=72 → label='進貨'。"""
    db = _make_full_accumulation_db(tmp_path)
    scanner, cache = scan_accumulation_score(db_path=db)

    picks = scanner("2026-05-08", db)
    assert len(picks) == 1
    assert picks[0]["stock_id"] == "2330"

    result = cache[("2026-05-08", "2330")]
    assert result["score"] == 72
    assert result["weakening"] is False
    assert result["label"] == "進貨"
    assert result["holder_net_lots"] == 25000
