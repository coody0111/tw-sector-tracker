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


_TIER_RANK = {"superweak": 0, "weak": 1, "mid": 2, "strong": 3, "super": 4}
_ANOMALY_VOL_RATIO_MIN = 1.5
_ANOMALY_RANK_JUMP_MIN = 10
_ANOMALY_TREND_STREAK_MIN = 5


def _accel_from_windows(window_data: Dict[str, Any]) -> Optional[float]:
    """this_week_pct_today - last_week_pct_today，任一為None時回None。"""
    this_week = window_data.get("this_week_pct_today")
    last_week = window_data.get("last_week_pct_today")
    if this_week is None or last_week is None:
        return None
    return round(this_week - last_week, 2)


def _tiers_from_windows(window_data: Dict[str, Any]) -> Dict[str, Optional[Dict[str, str]]]:
    """從calc_meta_heatgrid_windows()的原始數值算出tier_today/tier_last_week。
    tier_last_week重用last_week_pct_today當this_week(見窗口重疊關係)。"""
    tier_today = classify_tier(
        window_data.get("streak_today"),
        window_data.get("last_week_pct_today"),
        window_data.get("this_week_pct_today"),
    )
    tier_last_week = classify_tier(
        window_data.get("streak_5d_ago"),
        window_data.get("last_week_pct_5d_ago"),
        window_data.get("last_week_pct_today"),
    )
    return {"tier_today": tier_today, "tier_last_week": tier_last_week}


def find_turning_points(heatgrid_windows: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    轉折點列表（視覺spec用語：族群近況②）。比對 tier_today vs tier_last_week，真的換了一級
    才列入（不是幅度排序）。任一為 None（資料不足）或兩者相同時跳過。
    """
    results = []
    for meta_name, window_data in heatgrid_windows.items():
        tiers = _tiers_from_windows(window_data)
        cur = tiers["tier_today"]
        prev = tiers["tier_last_week"]
        if cur is None or prev is None or cur["key"] == prev["key"]:
            continue
        direction = "轉強訊號" if _TIER_RANK[cur["key"]] > _TIER_RANK[prev["key"]] else "轉弱訊號，留意"
        results.append({
            "meta_name": meta_name,
            "prev_key": prev["key"], "prev_label": prev["label"],
            "cur_key": cur["key"], "cur_label": cur["label"],
            "direction": direction,
        })
    return results


def find_anomaly_cards(
    meta_perf: List[Dict[str, Any]],
    meta_signals: Dict[str, Dict[str, Any]],
    heatgrid_windows: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    異動族群動態清單（視覺spec用語：頁面最上方快報，今日vs昨日的瞬間訊號）。不是固定5張卡，
    符合條件有幾檔就回傳幾檔。門檻是視覺 spec 定的經驗法則草案，待回測（見 Global Constraints）。

    爆量暴衝(burst)：vol_ratio >= 1.5 且今日排名比昨日跳動 >= 10（今日排名依 avg_change_pct
    降冪計算，第1名跳動幅度最大）。
    連續噴出(trend)：classify_temp(accel)=="hot" 且 streak_today >= 5（草案，要求持續而非
    曇花一現）。
    同一族群兩者都成立時，burst 優先（量能異常是更即時的訊號）。
    """
    ranked = sorted(meta_perf, key=lambda r: r["avg_change_pct"], reverse=True)
    today_rank = {row["meta_name"]: i + 1 for i, row in enumerate(ranked)}
    pct_map = {row["meta_name"]: row["avg_change_pct"] for row in meta_perf}

    results = []
    for meta_name in pct_map:
        sig = meta_signals.get(meta_name, {})
        window_data = heatgrid_windows.get(meta_name, {})
        vol_ratio = sig.get("vol_ratio")
        yesterday_rank = sig.get("yesterday_rank")
        accel = _accel_from_windows(window_data)
        streak_today = window_data.get("streak_today")

        is_burst = (
            vol_ratio is not None and vol_ratio >= _ANOMALY_VOL_RATIO_MIN
            and yesterday_rank is not None
            and (yesterday_rank - today_rank[meta_name]) >= _ANOMALY_RANK_JUMP_MIN
        )
        if is_burst:
            results.append({
                "kind": "burst", "meta_name": meta_name, "pct": pct_map[meta_name],
                "reason": f"今日量能 {vol_ratio}x 於5日均量，昨日#{yesterday_rank}→今日#{today_rank[meta_name]}",
            })
            continue

        temp = classify_temp(accel) if accel is not None else None
        is_trend = (
            temp is not None and temp["key"] == "hot"
            and streak_today is not None and streak_today >= _ANOMALY_TREND_STREAK_MIN
        )
        if is_trend:
            last_week_pct = window_data.get("last_week_pct_today")
            this_week_pct = window_data.get("this_week_pct_today")
            results.append({
                "kind": "trend", "meta_name": meta_name, "pct": pct_map[meta_name],
                "reason": f"上週 {last_week_pct:+.1f}% → 本週 {this_week_pct:+.1f}%　加速 {accel:+.1f}pt",
            })

    return results


def build_heatgrid_cards(
    meta_perf: List[Dict[str, Any]],
    meta_signals: Dict[str, Dict[str, Any]],
    meta_chips: Dict[str, Dict[str, Any]],
    heatgrid_windows: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    熱區格 41 張卡片資料（視覺 spec §3「族群排行」），依 avg_change_pct 降冪排列。組合
    meta_perf（今日漲跌/家數）+ meta_signals（量比，既有函式）+ meta_chips（外資/投信連買
    天數，既有函式）+ heatgrid_windows（processors/performance.py::calc_meta_heatgrid_windows()
    算的原始窗口值，這裡才做 classify_tier/classify_temp 分類）。
    """
    ranked = sorted(meta_perf, key=lambda r: r["avg_change_pct"], reverse=True)
    max_abs_pct = max((abs(r["avg_change_pct"]) for r in ranked), default=0.0)

    cards = []
    for i, row in enumerate(ranked):
        meta_name = row["meta_name"]
        sig = meta_signals.get(meta_name, {})
        chips = meta_chips.get(meta_name, {})
        window_data = heatgrid_windows.get(meta_name, {})
        pct = row["avg_change_pct"]
        accel = _accel_from_windows(window_data)

        cards.append({
            "rank": i + 1,
            "meta_name": meta_name,
            "pct": pct,
            "up_count": row["up_count"],
            "down_count": row["down_count"],
            "streak": window_data.get("streak_today"),
            "vol_ratio": sig.get("vol_ratio"),
            "foreign_streak": chips.get("foreign_streak"),
            "trust_streak": chips.get("trust_streak"),
            "last_week_pct": window_data.get("last_week_pct_today"),
            "this_week_pct": window_data.get("this_week_pct_today"),
            "accel": accel,
            "tier": classify_tier(
                window_data.get("streak_today"),
                window_data.get("last_week_pct_today"),
                window_data.get("this_week_pct_today"),
            ),
            "temp": classify_temp(accel),
            "heat_bg": heat_bg(pct, max_abs_pct),
        })
    return cards


_SECTOR_RECAP_TOP_N = 5


def build_sector_recap(
    meta_perf: List[Dict[str, Any]],
    heatgrid_windows: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    族群近況（視覺 spec §4）：升溫/退燒雙欄 Top5 + 轉折點列表。accel 為 None（資料不足）的
    族群不參與升溫/退燒排序（沒有依據判斷是升溫還是退燒，不能硬排進去）。
    """
    pct_map = {row["meta_name"]: row["avg_change_pct"] for row in meta_perf}
    with_accel = []
    for meta_name, window_data in heatgrid_windows.items():
        if meta_name not in pct_map:
            continue
        accel = _accel_from_windows(window_data)
        if accel is None:
            continue
        with_accel.append({"meta_name": meta_name, "pct": pct_map[meta_name], "accel": accel})

    hot_top5 = sorted(with_accel, key=lambda r: r["accel"], reverse=True)[:_SECTOR_RECAP_TOP_N]
    cold_top5 = sorted(with_accel, key=lambda r: r["accel"])[:_SECTOR_RECAP_TOP_N]

    # turning_points 傳入前先用 pct_map（衍生自 meta_perf）過濾 heatgrid_windows，跟上面
    # hot_top5/cold_top5 的排除邏輯保持一致——calc_meta_performance()/calc_meta_heatgrid_windows()
    # 是main.py裡兩個獨立呼叫，理論上族群集合可能不完全一致，不過濾會讓同一個回傳值裡
    # hot_top5/cold_top5排除了某族群、但turning_points卻還顯示它，是自相矛盾的輸出。
    active_windows = {name: data for name, data in heatgrid_windows.items() if name in pct_map}

    return {
        "hot_top5": hot_top5,
        "cold_top5": cold_top5,
        "turning_points": find_turning_points(active_windows),
    }
