import pytest

from recommend.ticks import limit_up_price, tick_size


@pytest.mark.parametrize("price,tick", [
    (9.99, 0.01), (10, 0.05), (49.95, 0.05), (50, 0.1), (99.9, 0.1),
    (100, 0.5), (499.5, 0.5), (500, 1), (999, 1), (1000, 5), (2400, 5),
])
def test_tick_size_boundaries(price, tick):
    assert tick_size(price) == tick


@pytest.mark.parametrize("ref,limit", [
    (306.5, 337.0),    # 306.5×1.1=337.15 → 100～500 跳 0.5 → 337.0
    (541.0, 595.0),    # 595.1 → 500～1000 跳 1 → 595
    (9.5, 10.45),      # 10.45 → 10～50 跳 0.05 → 10.45
    (45.6, 50.1),      # 50.16 → 50～100 跳 0.1 → 50.1
    (2200.0, 2420.0),  # ≥1000 跳 5
])
def test_limit_up_price_rounds_down_to_tick_of_result(ref, limit):
    assert limit_up_price(ref) == pytest.approx(limit)
