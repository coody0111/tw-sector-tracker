"""台股普通股跳動單位與漲停價（規格 §3）。ETF 規則不同，不適用。"""
import math

_TICKS = [(10, 0.01), (50, 0.05), (100, 0.1), (500, 0.5), (1000, 1.0)]


def tick_size(price: float) -> float:
    for upper, tick in _TICKS:
        if price < upper:
            return tick
    return 5.0


def limit_up_price(ref: float) -> float:
    """參考價 × 1.10，無條件捨去到「該價位」的跳動單位。"""
    raw = ref * 1.10
    tick = tick_size(raw)
    return round(math.floor(raw / tick + 1e-9) * tick, 2)


def limit_down_price(ref: float) -> float:
    """參考價 × 0.90，無條件進位到「該價位」的跳動單位。"""
    raw = ref * 0.90
    tick = tick_size(raw)
    return round(math.ceil(raw / tick - 1e-9) * tick, 2)
