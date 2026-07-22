"""
產生 docs/index.html — 族群總覽頁（熱區格版面）
資料來源：processors/performance.py 的 calc_meta_performance()/calc_meta_signals()/
         calc_meta_chips_signals()/calc_cumulative_meta()/calc_meta_heatgrid_windows()
視覺/互動設計：docs/superpowers/specs/2026-07-15-sector-overview-heatmap-redesign.md
技術落地設計：docs/superpowers/specs/2026-07-22-sector-overview-heatmap-implementation-design.md

刻意的設計決定：這個模組取代 export/html_generator.py 在 main.py::run() 裡的角色，但不刪除
舊檔案（沒有其他模組依賴它，保留當 rollback 用）。這個檔案完全不呼叫 duckdb.connect()——跟
專案其他 export/*_generator.py 檔案一致的分層慣例，DB 查詢一律在 processors/ 完成，這裡只吃
已經算好的原始數值做分類/渲染。

classify_tier() 是這個模組獨有的第三套「五級動能狀態」分類邏輯，跟
screener/signals.py::scan_momentum_health() 的 strength_tier、
export/momentum_generator.py::classify_sector_state() 都不共用計算依據——這裡故意只吃
streak + 5日窗口加速度，不查法人資料，換取 41 個族群卡片能快速全部算完。
"""
from typing import Any, Dict, List, Optional

_TIER_LABEL = {"super": "超強", "strong": "強", "mid": "整理", "weak": "弱", "superweak": "超弱"}

# 動能五級/溫度變化門檻：視覺spec定的經驗法則草案，沒有回測驗證（見 Global Constraints）。
_TIER_SUPERWEAK_STREAK = -5
_TIER_SUPER_ACCEL = 3
_TIER_STRONG_ACCEL_FLOOR = -2
_TIER_WEAK_ACCEL_CEIL = -2
_TEMP_THRESHOLD_PT = 5.0


def classify_tier(
    streak: Optional[int],
    last_week_pct: Optional[float],
    this_week_pct: Optional[float],
) -> Optional[Dict[str, str]]:
    """
    族群層級動能五級分類（草案，待回測，見 Global Constraints）。跟 scan_momentum_health()/
    classify_sector_state() 是獨立的第三套邏輯，只吃 streak + 本週比上週加速度，不查法人資料。

    任一輸入為 None 時回傳 None（資料不足，不硬湊等級）。
    """
    if streak is None or last_week_pct is None or this_week_pct is None:
        return None

    accel = this_week_pct - last_week_pct

    if streak <= _TIER_SUPERWEAK_STREAK:
        key = "superweak"
    elif streak > 0 and accel > _TIER_SUPER_ACCEL:
        key = "super"
    elif streak > 0 and accel >= _TIER_STRONG_ACCEL_FLOOR:
        key = "strong"
    elif streak < 0 and accel < _TIER_WEAK_ACCEL_CEIL:
        key = "weak"
    else:
        key = "mid"

    return {"key": key, "label": _TIER_LABEL[key]}


def classify_temp(accel: Optional[float]) -> Optional[Dict[str, str]]:
    """
    溫度變化徽章（草案門檻 ±5pt，見 Global Constraints）。刻意跟今日漲跌紅綠色系分開
    （橙=增溫/藍=退燒），因為這兩件事回答不同問題：一個族群今天可能還是紅的，但已經在退燒。
    |accel| < 5pt 或 accel 為 None 時回傳 None（不顯示徽章）。
    """
    if accel is None:
        return None
    if accel >= _TEMP_THRESHOLD_PT:
        return {"key": "hot", "label": f"增溫 +{accel:.1f}pt", "icon": "🔥"}
    if accel <= -_TEMP_THRESHOLD_PT:
        return {"key": "cold", "label": f"退燒 {accel:.1f}pt", "icon": "❄️"}
    return None


def heat_bg(pct: float, max_abs_pct: float) -> str:
    """
    熱區格卡片底色（紅漲綠跌，飽和度依當日漲跌幅相對全市場最大值算），直接對應視覺 spec 的
    heatBg() JS 函式。max_abs_pct=0（全市場今日漲跌全部剛好0%的極端情況）時 t 視為 0，
    不除以0。
    """
    t = min(abs(pct) / max_abs_pct, 1.0) if max_abs_pct > 0 else 0.0
    alpha = 0.16 + t * 0.5
    alpha_pct = round(alpha * 100)
    color_var = "var(--up)" if pct >= 0 else "var(--down)"
    return f"color-mix(in srgb, {color_var} {alpha_pct}%, var(--panel))"
