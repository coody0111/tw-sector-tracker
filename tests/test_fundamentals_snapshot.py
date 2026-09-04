"""季報基本面快照（screener/database.py）的純函式測試。

不碰 DB：build_fundamentals_snapshot() 刻意設計成吃 DataFrame 的純函式，
所有規則都能用合成資料鎖住。

spec: docs/superpowers/specs/2026-09-04-fundamentals-display-design.md
ADR : docs/adr/0007-fundamentals-availability-uses-statutory-deadline.md
"""
from datetime import date

import pandas as pd
import pytest

from screener.database import (
    _margin_ratio,
    _profit_growth,
    _revenue_growth,
    _single_quarter,
    _statutory_available_date,
    build_fundamentals_snapshot,
)


def _facts(rows):
    """rows: (stock_id, fiscal_year, quarter, metric_key, value) 的 list。"""
    return pd.DataFrame(
        rows, columns=["stock_id", "fiscal_year", "quarter", "metric_key", "value"]
    )


# --------------------------------------------------------------------------
# 可得日（ADR 0007）
# --------------------------------------------------------------------------

def test_statutory_deadline_all_four_quarters():
    assert _statutory_available_date(2026, 1) == date(2026, 5, 15)
    assert _statutory_available_date(2026, 2) == date(2026, 8, 14)
    assert _statutory_available_date(2026, 3) == date(2026, 11, 14)
    # Q4 是年報，法定期限落在「隔年」3/31——最容易寫錯的一個
    assert _statutory_available_date(2026, 4) == date(2027, 3, 31)


def test_statutory_deadline_rejects_bad_quarter():
    for bad in (0, 5, -1):
        with pytest.raises(ValueError):
            _statutory_available_date(2026, bad)


def test_available_on_deadline_day_but_not_the_day_before():
    """邊界：可得日當天視為已可見，前一天不可見。"""
    facts = _facts([("2330", 2026, 2, "revenue", 100.0),
                    ("2330", 2026, 1, "revenue", 40.0)])

    same_day = build_fundamentals_snapshot(facts, "2026-08-14")
    assert same_day.loc[0, "period_label"] == "2026Q2"

    day_before = build_fundamentals_snapshot(facts, "2026-08-13")
    # 2026Q2 還看不到，往前落到 2026Q1（5/15 已過）
    assert day_before.loc[0, "period_label"] == "2026Q1"


def test_q4_falls_back_to_q3_before_march_31():
    """跨年：年報要到隔年 3/31，在那之前最新可見季是前一年 Q3。"""
    facts = _facts([("1101", 2025, 3, "revenue", 300.0),
                    ("1101", 2025, 4, "revenue", 400.0)])

    before = build_fundamentals_snapshot(facts, "2026-03-30")
    assert before.loc[0, "period_label"] == "2025Q3"

    on_time = build_fundamentals_snapshot(facts, "2026-03-31")
    assert on_time.loc[0, "period_label"] == "2025Q4"


def test_no_visible_quarter_yields_empty_frame():
    """全部期別都還沒到可得日 → 該股整列不出現（不是回一列全 None）。"""
    facts = _facts([("9999", 2026, 2, "revenue", 100.0)])
    out = build_fundamentals_snapshot(facts, "2026-01-01")
    assert out.empty


# --------------------------------------------------------------------------
# 單季換算（損益表 100% 是累計數）
# --------------------------------------------------------------------------

def test_single_quarter_q1_is_the_ytd_value_itself():
    assert _single_quarter(40.0, None, 1) == 40.0
    # Q1 就算前一期(去年Q4累計)存在也不該被減掉
    assert _single_quarter(40.0, 999.0, 1) == 40.0


def test_single_quarter_q2_to_q4_subtracts_previous_ytd():
    assert _single_quarter(100.0, 40.0, 2) == 60.0
    assert _single_quarter(180.0, 100.0, 3) == 80.0


def test_single_quarter_returns_none_when_previous_ytd_missing():
    """缺前一期累計時回 None——不猜、不補 0。"""
    assert _single_quarter(100.0, None, 2) is None
    assert _single_quarter(None, 40.0, 2) is None


def test_snapshot_revenue_is_single_quarter_not_ytd():
    facts = _facts([("2330", 2026, 1, "revenue", 40.0),
                    ("2330", 2026, 2, "revenue", 100.0)])
    out = build_fundamentals_snapshot(facts, "2026-08-14")
    assert out.loc[0, "revenue"] == 60.0   # 不是 100.0


def test_eps_is_ytd_and_never_subtracted():
    """累計 EPS 相減在數學上不成立（期間內股數會變動），必須原樣呈現。"""
    facts = _facts([("2330", 2026, 1, "eps", 2.0),
                    ("2330", 2026, 2, "eps", 5.0)])
    out = build_fundamentals_snapshot(facts, "2026-08-14")
    assert out.loc[0, "eps_ytd"] == 5.0    # 不是 3.0


def test_qoq_crosses_year_boundary_into_previous_q4():
    """Q1 的上一季是去年 Q4，跨年不能斷掉。"""
    facts = _facts([
        ("1234", 2025, 3, "revenue", 300.0),   # 去年 Q3 累計
        ("1234", 2025, 4, "revenue", 400.0),   # 去年 Q4 累計 → 單季 100
        ("1234", 2026, 1, "revenue", 120.0),   # 今年 Q1 單季 120
    ])
    out = build_fundamentals_snapshot(facts, "2026-05-15")
    assert out.loc[0, "period_label"] == "2026Q1"
    assert out.loc[0, "revenue"] == 120.0
    assert out.loc[0, "revenue_qoq"] == pytest.approx(20.0)   # 120 vs 100


# --------------------------------------------------------------------------
# 成長率與離群規則（spec §8.2）
# --------------------------------------------------------------------------

def test_revenue_growth_has_no_upper_cap():
    """營收不設離群上限：1016 檔裡只有 2 檔 >999%，加防護反而藏掉真實高成長。"""
    assert _revenue_growth(20000.0, 100.0) == pytest.approx(19900.0)


def test_revenue_growth_none_when_base_not_positive():
    assert _revenue_growth(100.0, 0.0) is None
    assert _revenue_growth(100.0, -50.0) is None
    assert _revenue_growth(None, 100.0) is None


def test_profit_growth_labels_turnaround_instead_of_huge_number():
    assert _profit_growth(500.0, -10.0) == "轉盈"
    assert _profit_growth(-500.0, 10.0) == "轉虧"


def test_profit_growth_none_when_both_periods_lose_money():
    """兩期都虧損，成長率沒有意義，不硬算。"""
    assert _profit_growth(-50.0, -10.0) is None


def test_profit_growth_over_cap_is_not_labelled_turnaround():
    """本來就在賺錢、只是暴增 → 「>999%」，標成「轉盈」會是錯的描述。"""
    assert _profit_growth(2000.0, 100.0) == ">999%"


def test_profit_growth_keeps_normal_values_as_float():
    got = _profit_growth(128.3, 100.0)
    assert isinstance(got, float)
    assert got == pytest.approx(28.3)


def test_margin_ratio_rejects_impossible_values():
    """毛利率不該超過 100%，三位數以上必是單位或映射出錯 → 缺值優於錯值。"""
    assert _margin_ratio(42.1, 100.0) == pytest.approx(42.1)
    assert _margin_ratio(50000.0, 100.0) is None      # 50000%
    assert _margin_ratio(10.0, 0.0) is None
    assert _margin_ratio(None, 100.0) is None


def test_eps_yoy_uses_profit_rules():
    facts = _facts([("5678", 2025, 2, "eps", -1.0),
                    ("5678", 2026, 2, "eps", 3.0)])
    out = build_fundamentals_snapshot(facts, "2026-08-14")
    assert out.loc[0, "eps_yoy"] == "轉盈"


# --------------------------------------------------------------------------
# 缺值不 crash
# --------------------------------------------------------------------------

def test_empty_input_returns_empty_frame_with_columns():
    out = build_fundamentals_snapshot(pd.DataFrame(), "2026-08-14")
    assert out.empty
    assert "revenue" in out.columns and "eps_ytd" in out.columns


def test_partial_metrics_do_not_crash():
    """只有 EPS、沒有營收 → 卡片仍該產出，缺的欄位是 None。"""
    facts = _facts([("4444", 2026, 2, "eps", 1.5)])
    out = build_fundamentals_snapshot(facts, "2026-08-14")
    assert out.loc[0, "eps_ytd"] == 1.5
    assert out.loc[0, "revenue"] is None or pd.isna(out.loc[0, "revenue"])
    assert out.loc[0, "gross_margin"] is None or pd.isna(out.loc[0, "gross_margin"])


def test_nan_values_are_skipped():
    facts = _facts([("4444", 2026, 2, "revenue", float("nan")),
                    ("4444", 2026, 2, "eps", 1.5)])
    out = build_fundamentals_snapshot(facts, "2026-08-14")
    assert out.loc[0, "eps_ytd"] == 1.5


def test_one_row_per_stock_even_with_many_periods():
    """一檔多期只回最新可見季一列——族群一檔多屬時上層再 join 也不會放大。"""
    facts = _facts([("1111", 2025, q, "revenue", 100.0 * q) for q in (1, 2, 3)]
                   + [("2222", 2026, 1, "revenue", 50.0)])
    out = build_fundamentals_snapshot(facts, "2026-05-15")
    assert len(out) == 2
    assert set(out["stock_id"]) == {"1111", "2222"}
