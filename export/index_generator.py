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
import json
from datetime import date
from html import escape as _html_escape
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

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


def build_stock_detail_data(
    universe_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    stock_sparklines: Optional[Dict[str, dict]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    個股點開面板資料（視覺 spec §「點開個股清單」）。全部 meta_sector 都要有 key（即使該族群
    沒有任何股票有行情資料，回空 list），族群內依 change_pct 降冪排列。沒行情的個股跳過，不補
    假資料（跟 processors/performance.py 現有 join 慣例一致）。

    stock_sparklines：processors/performance.py::calc_stock_sparklines() 的輸出
    {stock_id: {"pcts": [...], "dates": [...], ...}}，供前端畫個股卡片的 sparkline 走勢圖。
    沒有這支股票的資料、或整包沒傳，回傳的 pcts/dates 都是空 list（前端沒有走勢資料就不畫）。
    """
    universe = universe_df[["stock_id", "stock_name", "meta_sector"]].copy()
    universe["stock_id"] = universe["stock_id"].astype(str)
    prices = prices_df.copy()
    if not prices.empty:
        prices["stock_id"] = prices["stock_id"].astype(str)
    prices_map = prices.set_index("stock_id") if not prices.empty else pd.DataFrame()
    sparklines = stock_sparklines or {}

    result: Dict[str, List[Dict[str, Any]]] = {
        meta_name: [] for meta_name in universe["meta_sector"].dropna().unique()
    }

    for _, row in universe.iterrows():
        sid = row["stock_id"]
        meta_name = row["meta_sector"]
        if pd.isna(meta_name) or sid not in prices_map.index:
            continue
        p = prices_map.loc[sid]
        spark = sparklines.get(sid, {})
        result[meta_name].append({
            "stock_id": sid,
            "stock_name": row["stock_name"],
            "close": float(p["close"]),
            "change_pct": float(p["change_pct"]),
            "pcts": spark.get("pcts", []),
            "dates": spark.get("dates", []),
        })

    for meta_name in result:
        result[meta_name].sort(key=lambda s: s["change_pct"], reverse=True)

    return result


def _esc(value) -> str:
    """HTML-escape 外部資料（族群/股票名稱等），比照 chips_generator.py::_esc() 同一防護。"""
    return _html_escape(str(value)) if value else ""


_CSS = """
:root{
  --bg:#080B12; --panel:#0F1420; --panel-2:#161D2C; --panel-3:#1E2738;
  --border:#293346; --border-2:#37435C;
  --ink:#DADFE8; --ink-2:#98A0B4; --ink-3:#636B80;
  --up:#E6432F; --down:#37B25C;
  --accent:#F0BB55; --accent-dim:#B98A3A;
  --burst:#F0BB55; --trend:#C77FBD;
  --tier-super:#F0BB55; --tier-strong:#4FC46A; --tier-mid:#8B94AC; --tier-weak:#E08A3E; --tier-superweak:#E6432F;
  --heat-hot:#FF7A3D; --heat-cold:#4FA8E8;
  --serif: Georgia,"Iowan Old Style","Source Serif 4","Noto Serif TC",serif;
  --sans: "Public Sans",-apple-system,"PingFang TC","Microsoft JhengHei","Segoe UI",sans-serif;
  --mono: ui-monospace,"IBM Plex Mono","Cascadia Code","Roboto Mono",monospace;
  --shadow-1: 0 1px 2px rgba(0,0,0,.35);
  --shadow-2: 0 10px 28px rgba(0,0,0,.5), 0 2px 6px rgba(0,0,0,.35);
}
:root[data-theme="light"]{
  --bg:#EFE8D8; --panel:#F8F3E6; --panel-2:#EAE1CB; --panel-3:#E0D5B8;
  --border:#D6C9A3; --border-2:#C3B387;
  --ink:#241C10; --ink-2:#6B5B3D; --ink-3:#93825E;
  --up:#A8432C; --down:#3D7048;
  --accent:#93701E; --accent-dim:#C4A24E;
  --burst:#93701E; --trend:#7A4E6E;
  --tier-super:#93701E; --tier-strong:#3D7048; --tier-mid:#7A7260; --tier-weak:#9A5A24; --tier-superweak:#A8432C;
  --heat-hot:#C05A20; --heat-cold:#2E6FA3;
  --shadow-1: 0 1px 2px rgba(60,45,10,.1);
  --shadow-2: 0 10px 28px rgba(60,45,10,.16), 0 2px 6px rgba(60,45,10,.1);
}
*{box-sizing:border-box}
body{
  margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:14px;line-height:1.55;padding:0 0 80px;
  background-image:radial-gradient(ellipse at top left, rgba(255,255,255,.04), transparent 55%);
}
.tabular{font-family:var(--mono);font-variant-numeric:tabular-nums}
a{color:inherit}
.skip-link{position:absolute;left:-999px;top:0;background:var(--panel);color:var(--ink);padding:8px 14px;z-index:100}
.skip-link:focus{left:8px;top:8px}

.topbar{display:flex;align-items:baseline;gap:16px;padding:20px 26px;border-bottom:1px solid var(--border);flex-wrap:wrap}
.topbar h1{font-family:var(--serif);font-size:1.28rem;font-weight:600;color:var(--ink);letter-spacing:.01em;margin:0}
.topbar .kicker{font-size:.62rem;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--accent)}
.topbar .updated{font-size:.72rem;color:var(--ink-3);margin-left:auto;font-family:var(--mono)}
.topbar button{font-family:var(--mono);font-size:.68rem;background:var(--panel-2);border:1px solid var(--border);color:var(--ink-2);padding:5px 12px;border-radius:4px;cursor:pointer}
.nav-links{display:flex;gap:8px}
.nav-link{font-size:.78rem;padding:5px 14px;border-radius:6px;border:1px solid var(--border);color:var(--ink-2);text-decoration:none}
.nav-link:hover{border-color:var(--ink-2);color:var(--ink)}
.nav-link.active{border-color:var(--accent);color:var(--ink);background:var(--panel-2)}
.nav-link:focus-visible,button:focus-visible,.heat-tile:focus-visible,.anomaly-card:focus-visible{outline:3px solid var(--accent);outline-offset:2px}

.section-head{display:flex;align-items:baseline;gap:12px;padding:26px 26px 8px}
.section-head h2{font-family:var(--serif);font-size:1.05rem;font-weight:600;color:var(--ink);margin:0}
.section-head .count{font-family:var(--mono);font-size:.7rem;color:var(--ink-3)}
.section-rule{height:1px;background:linear-gradient(to right,var(--ink) 0%,var(--border) 45%,transparent 100%);margin:0 26px 4px}
.section-sub{padding:0 26px 14px;font-size:.76rem;color:var(--ink-2);max-width:720px}

.anomaly-wrap{position:relative;margin:0 26px}
.anomaly-strip{display:flex;gap:14px;overflow-x:auto;padding:2px 2px 6px}
.anomaly-wrap::after{content:"";position:absolute;top:0;right:0;bottom:6px;width:44px;pointer-events:none;background:linear-gradient(to right, transparent, var(--bg) 88%)}
.anomaly-card{flex:0 0 240px;background:var(--panel);border:1px solid var(--border);border-radius:4px;padding:15px 17px;position:relative;cursor:pointer;transition:box-shadow .2s,transform .2s,border-color .2s}
.anomaly-card:hover{border-color:var(--border-2);transform:translateY(-2px)}
.anomaly-card::before{content:"";position:absolute;left:0;top:15px;bottom:15px;width:2px;border-radius:2px}
.anomaly-card.burst::before{background:var(--burst)} .anomaly-card.trend::before{background:var(--trend)}
.anomaly-kind{font-size:.6rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;margin-bottom:8px}
.anomaly-kind.burst{color:var(--burst)} .anomaly-kind.trend{color:var(--trend)}
.anomaly-name{font-family:var(--serif);font-weight:600;font-size:1.0rem;color:var(--ink)}
.anomaly-pct{font-family:var(--mono);font-weight:600;font-size:1.02rem;color:var(--up);float:right}
.anomaly-reason{margin-top:10px;font-size:.72rem;color:var(--ink-2);line-height:1.6;padding-top:9px;border-top:1px solid var(--border)}
.anomaly-empty{color:var(--ink-3);font-size:.82rem;font-style:italic;padding:8px 2px}

.tier-legend{display:flex;gap:16px;padding:0 26px 16px;font-size:.68rem;color:var(--ink-2);flex-wrap:wrap;font-family:var(--mono)}
.tier-legend span{display:inline-flex;align-items:center;gap:5px}
.tier-legend .dot{width:8px;height:8px;border-radius:2px}

.heatgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(224px,1fr));gap:8px;padding:0 26px}
.heat-tile{
  border-radius:5px;padding:13px 14px;cursor:pointer;transition:transform .15s,box-shadow .15s;
  position:relative;border:1px solid rgba(255,255,255,.06);background:var(--panel);
  border-top:3px solid transparent;
}
.heat-tile:hover{transform:translateY(-2px);box-shadow:var(--shadow-2);z-index:2}
.heat-tile.active{outline:2px solid var(--accent);outline-offset:-2px}

.detail-panel{
  grid-column:1/-1;background:var(--panel);border:1px solid var(--border-2);border-radius:5px;
  padding:22px 26px;box-shadow:var(--shadow-2);scroll-margin-top:20px;
  animation:expandIn .22s ease-out;
}
@keyframes expandIn{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:translateY(0)}}
.detail-head{display:flex;align-items:baseline;gap:12px;margin-bottom:2px}
.detail-head h3{font-family:var(--serif);font-size:1.22rem;font-weight:600;margin:0;color:var(--ink)}
.detail-head .dpct{font-family:var(--mono);font-size:.98rem;font-weight:700}
.detail-close{margin-left:auto;font-family:var(--mono);font-size:.68rem;background:none;border:1px solid var(--border);color:var(--ink-3);padding:4px 10px;border-radius:4px;cursor:pointer}
.detail-sub{font-size:.75rem;color:var(--ink-3);margin-bottom:18px;font-family:var(--mono)}
.stock-cards-wrap{display:grid;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));gap:8px}
.stock-card{border:1px solid var(--border);border-radius:5px;padding:10px 11px;background:var(--panel-3)}
.sc-header{display:flex;align-items:baseline;gap:6px;margin-bottom:4px}
.sc-id{font-family:var(--mono);color:var(--ink-3);font-size:.68rem}
.sc-name{font-family:var(--serif);font-weight:600;color:var(--ink);font-size:.86rem;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sc-body{display:flex;align-items:baseline;justify-content:space-between;font-family:var(--mono);font-variant-numeric:tabular-nums}
.sc-price{font-size:.86rem;color:var(--ink-2)}
.sc-pct{font-size:.86rem;font-weight:700}
.sc-sparkline{margin-top:6px;line-height:0}
.sc-sparkline svg{width:100%;height:auto;display:block}
.detail-empty{color:var(--ink-3);font-size:.86rem;padding:20px 0;font-family:var(--serif)}

.ht-top{display:flex;align-items:baseline;gap:8px}
.ht-rank{font-family:var(--mono);font-size:.6rem;color:var(--ink-3);flex-shrink:0}
.ht-name{font-family:var(--serif);font-weight:700;font-size:.96rem;color:var(--ink);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;letter-spacing:.01em}
.ht-pct{font-family:var(--mono);font-weight:700;font-size:1.0rem;flex-shrink:0}
.ht-status-row{display:flex;align-items:center;gap:6px;margin-top:8px;flex-wrap:wrap}
.ht-tier{display:inline-flex;align-items:center;gap:5px;padding:3px 8px;border-radius:20px;font-size:.62rem;font-weight:700;letter-spacing:.02em}
.ht-tier .dot{width:6px;height:6px;border-radius:50%}
.ht-temp{display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:20px;font-family:var(--mono);font-size:.62rem;font-weight:700}
.ht-temp.hot{background:color-mix(in srgb, var(--heat-hot) 20%, transparent);color:var(--heat-hot)}
.ht-temp.cold{background:color-mix(in srgb, var(--heat-cold) 20%, transparent);color:var(--heat-cold)}
.ht-temp.flat{background:rgba(255,255,255,.06);color:var(--ink-3)}
.ht-streak{font-family:var(--mono);font-size:.68rem;color:var(--ink-2);margin-top:7px;font-weight:600}
.ht-streak .n{font-weight:800}
.ht-streak .cnt{color:var(--ink-3);font-weight:400}
.ht-badges{display:flex;gap:5px;margin-top:7px;flex-wrap:wrap}
.badge{font-family:var(--mono);font-size:.58rem;font-weight:700;padding:2px 6px;border-radius:3px;display:inline-flex;align-items:center;gap:3px}
.badge.foreign{background:rgba(212,162,78,.16);color:var(--accent);border:1px solid rgba(212,162,78,.3)}
.badge.trust{background:rgba(169,120,154,.16);color:var(--trend);border:1px solid rgba(169,120,154,.3)}
.badge.vol{background:rgba(255,255,255,.06);color:var(--ink-2);border:1px solid var(--border)}
.ht-week{display:flex;align-items:center;justify-content:space-between;margin-top:9px;padding-top:8px;border-top:1px solid rgba(255,255,255,.08);font-family:var(--mono);font-size:.62rem}
.ht-week .lbl{color:var(--ink-3)}
.ht-week .vals{font-weight:700}
.legend-note{padding:14px 26px 0;font-size:.7rem;color:var(--ink-3);max-width:760px}

.role-note{margin:0 26px 20px;padding:11px 15px;background:var(--panel);border:1px solid var(--border);border-radius:4px;font-size:.74rem;color:var(--ink-2);display:flex;gap:18px;flex-wrap:wrap}
.role-note b{color:var(--ink)}
.status-cols{display:grid;grid-template-columns:1fr 1fr;gap:20px;padding:0 26px}
@media (max-width:760px){.status-cols{grid-template-columns:1fr}}
.status-col-head{display:flex;align-items:center;gap:8px;font-family:var(--serif);font-weight:700;font-size:1rem;margin-bottom:12px;padding-bottom:10px;border-bottom:2px solid}
.status-col-head.hot{color:var(--heat-hot);border-color:var(--heat-hot)}
.status-col-head.cold{color:var(--heat-cold);border-color:var(--heat-cold)}
.status-row{display:flex;align-items:center;gap:10px;padding:9px 4px;border-bottom:1px solid var(--border)}
.status-row .sr-name{font-family:var(--serif);font-weight:600;font-size:.88rem;color:var(--ink);flex:1}
.status-row .sr-today{font-family:var(--mono);font-size:.74rem;width:56px;text-align:right}
.status-row .sr-pt{font-family:var(--mono);font-weight:800;font-size:.86rem;width:66px;text-align:right}

.turning-wrap{margin:26px 26px 0;background:var(--panel);border:1px solid var(--border-2);border-radius:5px;padding:18px 22px}
.turning-head{font-family:var(--serif);font-weight:700;font-size:1rem;color:var(--ink);margin-bottom:4px}
.turning-sub{font-size:.72rem;color:var(--ink-3);margin-bottom:14px}
.turning-row{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border)}
.turning-row:last-child{border-bottom:none}
.turning-name{font-family:var(--serif);font-weight:700;font-size:.9rem;color:var(--ink);width:110px;flex-shrink:0}
.turning-transition{display:flex;align-items:center;gap:8px;font-family:var(--mono);font-size:.72rem}
.turning-pill{padding:3px 9px;border-radius:20px;font-weight:700}
.turning-arrow{color:var(--ink-3)}
.turning-desc{margin-left:auto;font-size:.72rem;color:var(--ink-2);font-style:italic;font-family:var(--serif)}
"""

_TIER_COLOR_VAR = {
    "super": "var(--tier-super)", "strong": "var(--tier-strong)", "mid": "var(--tier-mid)",
    "weak": "var(--tier-weak)", "superweak": "var(--tier-superweak)",
}


def _pct_str(pct: float) -> str:
    return f"{pct:+.2f}%"


def _anomaly_cards_html(anomaly_cards: List[Dict[str, Any]]) -> str:
    if not anomaly_cards:
        return '<div class="anomaly-empty">目前沒有族群符合爆量暴衝或連續噴出的條件</div>'
    cards = []
    for c in anomaly_cards:
        kind_label = "爆量暴衝" if c["kind"] == "burst" else "連續噴出"
        cards.append(
            f'<div class="anomaly-card {c["kind"]}" data-meta-name="{_esc(c["meta_name"])}" '
            f'role="button" tabindex="0" onclick="selectGroup(this.dataset.metaName)" '
            f'onkeydown="if(event.key===\'Enter\'||event.key===\' \'){{event.preventDefault();selectGroup(this.dataset.metaName)}}">'
            f'<div class="anomaly-kind {c["kind"]}">{kind_label}</div>'
            f'<span class="anomaly-pct tabular">{_pct_str(c["pct"])}</span>'
            f'<div class="anomaly-name">{_esc(c["meta_name"])}</div>'
            f'<div class="anomaly-reason">{_esc(c["reason"])}</div>'
            f'</div>'
        )
    return "".join(cards)


def _heatgrid_html(cards: List[Dict[str, Any]]) -> str:
    tiles = []
    for c in cards:
        tier = c["tier"]
        temp = c["temp"]
        tier_html = ""
        if tier is not None:
            color = _TIER_COLOR_VAR[tier["key"]]
            tier_html = (
                f'<div class="ht-tier" style="background:{color}22;color:{color}">'
                f'<span class="dot" style="background:{color}"></span>{tier["label"]}</div>'
            )
        else:
            tier_html = '<div class="ht-tier" style="color:var(--ink-3)">資料不足</div>'

        if temp is not None:
            temp_html = f'<div class="ht-temp {temp["key"]}">{temp["icon"]} {temp["label"]}</div>'
        elif c["accel"] is not None:
            temp_html = f'<div class="ht-temp flat tabular">→ {c["accel"]:+.1f}pt</div>'
        else:
            temp_html = ""

        streak = c["streak"]
        if streak is None:
            streak_html = "資料不足"
        elif streak > 0:
            streak_html = f'連漲 <span class="n" style="color:var(--up)">{streak}</span> 日'
        elif streak < 0:
            streak_html = f'連跌 <span class="n" style="color:var(--down)">{abs(streak)}</span> 日'
        else:
            streak_html = "持平"

        badges = []
        if c["foreign_streak"] is not None and c["foreign_streak"] >= 2:
            badges.append(f'<span class="badge foreign">外資連買{c["foreign_streak"]}日</span>')
        if c["trust_streak"] is not None and c["trust_streak"] >= 2:
            badges.append(f'<span class="badge trust">投信連買{c["trust_streak"]}日</span>')
        if c["vol_ratio"] is not None and c["vol_ratio"] >= 1.5:
            badges.append(f'<span class="badge vol">量能{c["vol_ratio"]}x</span>')
        badges_html = f'<div class="ht-badges">{"".join(badges)}</div>' if badges else ""

        week_html = ""
        if c["last_week_pct"] is not None and c["this_week_pct"] is not None:
            lw, tw = c["last_week_pct"], c["this_week_pct"]
            lw_color = "var(--up)" if lw >= 0 else "var(--down)"
            tw_color = "var(--up)" if tw >= 0 else "var(--down)"
            week_html = (
                f'<div class="ht-week"><span class="lbl">近5日→前5日</span>'
                f'<span class="vals tabular"><span style="color:{lw_color}">{_pct_str(lw)}</span>'
                f'<span class="lbl">→</span><span style="color:{tw_color}">{_pct_str(tw)}</span></span></div>'
            )

        pct_color = "var(--up)" if c["pct"] >= 0 else "var(--down)"
        meta_name_safe = _esc(c["meta_name"])
        tiles.append(
            f'<div class="heat-tile" data-meta-name="{meta_name_safe}" '
            f'role="button" tabindex="0" onclick="selectGroup(this.dataset.metaName)" '
            f'onkeydown="if(event.key===\'Enter\'||event.key===\' \'){{event.preventDefault();selectGroup(this.dataset.metaName)}}" '
            f'style="background:{c["heat_bg"]};border-top-color:{_TIER_COLOR_VAR[tier["key"]] if tier else "transparent"}">'
            f'<div class="ht-top"><span class="ht-rank tabular">#{c["rank"]}</span>'
            f'<span class="ht-name" title="{meta_name_safe}">{meta_name_safe}</span>'
            f'<span class="ht-pct tabular" style="color:{pct_color}">{_pct_str(c["pct"])}</span></div>'
            f'<div class="ht-status-row">{tier_html}{temp_html}</div>'
            f'<div class="ht-streak">{streak_html}<span class="cnt">　'
            f'<span style="color:var(--up)">▲{c["up_count"]}檔</span> '
            f'<span style="color:var(--down)">▼{c["down_count"]}檔</span></span></div>'
            f'{badges_html}{week_html}</div>'
        )
    return "".join(tiles)


def _sector_recap_html(recap: Dict[str, Any]) -> str:
    def _status_row(r: Dict[str, Any], is_hot: bool) -> str:
        color = "var(--heat-hot)" if is_hot else "var(--heat-cold)"
        pct_color = "var(--up)" if r["pct"] >= 0 else "var(--down)"
        return (
            f'<div class="status-row"><span class="sr-name">{_esc(r["meta_name"])}</span>'
            f'<span class="sr-today tabular" style="color:{pct_color}">{_pct_str(r["pct"])}</span>'
            f'<span class="sr-pt tabular" style="color:{color}">{r["accel"]:+.1f}pt</span></div>'
        )

    hot_html = "".join(_status_row(r, True) for r in recap["hot_top5"]) or '<div class="detail-empty">資料不足</div>'
    cold_html = "".join(_status_row(r, False) for r in recap["cold_top5"]) or '<div class="detail-empty">資料不足</div>'

    turning = recap["turning_points"]
    if turning:
        turning_html = "".join(
            f'<div class="turning-row"><span class="turning-name">{_esc(tp["meta_name"])}</span>'
            f'<span class="turning-transition">'
            f'<span class="turning-pill" style="background:{_TIER_COLOR_VAR[tp["prev_key"]]}22;color:{_TIER_COLOR_VAR[tp["prev_key"]]}">{tp["prev_label"]}</span>'
            f'<span class="turning-arrow">→</span>'
            f'<span class="turning-pill" style="background:{_TIER_COLOR_VAR[tp["cur_key"]]}22;color:{_TIER_COLOR_VAR[tp["cur_key"]]}">{tp["cur_label"]}</span>'
            f'</span><span class="turning-desc">{tp["direction"]}</span></div>'
            for tp in turning
        )
    else:
        turning_html = '<div class="detail-empty">本週沒有族群發生等級翻轉</div>'

    return f"""
<div class="section-head"><h2>族群近況</h2><span class="count">升溫/退燒排行・轉折點</span></div>
<div class="section-rule"></div>
<div class="role-note">
  <span>🔥❄️ <b>族群近況</b>＝週度趨勢訊號（加速度、等級翻轉），時間尺度是「這週 vs 上週」</span>
  <span>⚡ <b>異動族群</b>（頁面最上方）＝瞬間訊號（爆量+排名跳動），時間尺度是「今天 vs 昨天」</span>
  <span>兩者角色不同，故意分開兩個區塊，不是重複資訊</span>
</div>
<div class="status-cols">
  <div><div class="status-col-head hot">🔥 近期增溫 Top 5</div><div>{hot_html}</div></div>
  <div><div class="status-col-head cold">❄️ 近期退燒 Top 5</div><div>{cold_html}</div></div>
</div>
<div class="turning-wrap">
  <div class="turning-head">⚠ 轉折點：等級真的翻轉的族群</div>
  <div class="turning-sub">不是看誰漲最多，是看「上週的等級」跟「這週的等級」是否真的換了一級。</div>
  <div>{turning_html}</div>
</div>"""


def generate(
    trade_date: date,
    meta_perf: List[Dict[str, Any]],
    universe_df: pd.DataFrame,
    meta_signals: Dict[str, Dict[str, Any]],
    meta_chips: Dict[str, Dict[str, Any]],
    prices_df: pd.DataFrame,
    heatgrid_windows: Dict[str, Dict[str, Any]],
    stock_sparklines: Optional[Dict[str, dict]] = None,
    output_path: str = "docs/index.html",
) -> None:
    """
    產生 docs/index.html（族群總覽頁熱區格版面）。meta_perf 為空時不寫檔（比照舊
    export/html_generator.py::generate() 既有慣例）。

    stock_sparklines：processors/performance.py::calc_stock_sparklines() 的輸出，供個股
    卡片畫走勢圖用；None 時個股卡片一樣正常顯示，只是沒有 sparkline（跟舊版
    html_generator.py::_sparkline() 沒資料時回傳空字串的慣例一致）。
    """
    if not meta_perf:
        return

    date_str = trade_date.strftime("%Y-%m-%d")
    weekday = ["一", "二", "三", "四", "五", "六", "日"][trade_date.weekday()]

    cards = build_heatgrid_cards(meta_perf, meta_signals, meta_chips, heatgrid_windows)
    anomaly_cards = find_anomaly_cards(meta_perf, meta_signals, heatgrid_windows)
    recap = build_sector_recap(meta_perf, heatgrid_windows)
    stock_detail = build_stock_detail_data(universe_df, prices_df, stock_sparklines)

    stock_detail_js = json.dumps(stock_detail, ensure_ascii=False).replace("</", "<\\/")
    card_meta_js = json.dumps(
        {c["meta_name"]: {"pct": c["pct"], "up_count": c["up_count"], "down_count": c["down_count"]} for c in cards},
        ensure_ascii=False,
    ).replace("</", "<\\/")

    html = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<title>族群總覽 {date_str}</title>
<style>{_CSS}</style>
</head>
<body>
<a class="skip-link" href="#main-content">跳到主要內容</a>
<header class="topbar">
  <div><div class="kicker">台股電子半導體族群追蹤</div><h1>族群總覽</h1></div>
  <button onclick="toggleTheme()" id="themeToggle">切換亮色預覽</button>
  <div class="updated">{date_str}（週{weekday}）更新</div>
  <nav class="nav-links" aria-label="主要功能">
    <a class="nav-link active" href="index.html" aria-current="page">族群績效</a>
    <a class="nav-link" href="chips.html">籌碼分析</a>
    <a class="nav-link" href="patterns.html">形態掃描</a>
    <a class="nav-link" href="momentum.html">逆轟策略</a>
  </nav>
</header>
<main id="main-content">
<div class="section-head"><h2>⚡ 異動族群</h2><span class="count">{len(anomaly_cards)} 檔符合</span></div>
<div class="section-sub">「現在正在發生」的瞬間訊號——爆量排名跳動、或連續多週噴出。跟下面「族群近況」不同：這裡是單日事件，族群近況是週度趨勢。</div>
<div class="anomaly-wrap"><div class="anomaly-strip">{_anomaly_cards_html(anomaly_cards)}</div></div>

<div class="section-head"><h2>族群排行</h2><span class="count">今日漲跌% ・{len(cards)} 個族群</span></div>
<div class="section-rule"></div>
<div class="section-sub">動能狀態標籤是這版的重點：不是只看今日漲跌，而是綜合「連漲天數＋本週比上週是否加速」判斷這個族群現在的動能還在不在。</div>
<div class="tier-legend">
  <span><span class="dot" style="background:var(--tier-super)"></span>超強＝多頭排列+持續加速</span>
  <span><span class="dot" style="background:var(--tier-strong)"></span>強＝多頭排列，動能穩定</span>
  <span><span class="dot" style="background:var(--tier-mid)"></span>整理＝方向不明</span>
  <span><span class="dot" style="background:var(--tier-weak)"></span>弱＝動能減弱中</span>
  <span><span class="dot" style="background:var(--tier-superweak)"></span>超弱＝轉弱+連跌</span>
</div>
<div class="heatgrid" id="heatgrid">{_heatgrid_html(cards)}</div>
<div class="legend-note">⚠️ 動能狀態標籤（超強/強/整理/弱/超弱）是族群層級獨立算的草案規則（連漲天數+本週比上週加速度），跟個股層級或觀察分頁面的五級分類不共用計算依據，門檻未經回測驗證。「近5日→前5日」是滾動5個交易日的複利累積漲跌幅，不是自然日曆週。</div>

{_sector_recap_html(recap)}
</main>
<script>
const STOCKS = {stock_detail_js};
const CARD_META = {card_meta_js};

// escHtml：innerHTML拼字串前一律過這支，把字串當純文字塞進暫時的div再讀回escape過的innerHTML。
// 這裡一定要用，不能省——name(族群名)是從data-meta-name屬性讀回來的(瀏覽器解析HTML屬性時
// 已經把&lt;還原成<，所以.dataset.metaName拿到的是「解過碼的原始字串」)，s.stock_name是從
// 內嵌JSON讀的(json.dumps只做JSON字串轉義，從來沒被HTML-escape過)——這兩個字串如果直接
// 內插進innerHTML模板字串，等於繞過Python端generate()裡_esc()做過的escaping，是真的可以
// 執行的DOM XSS路徑(尤其<img onerror=...>/<svg onload=...>這類非<script>標籤，瀏覽器插入
// innerHTML後event handler真的會觸發，不是<script>標籤那種inert的假象全)。
function escHtml(s) {{
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}}

// pcts/dates 是 calc_stock_sparklines() 算出的數值/日期字串（"%m/%d"），不是使用者輸入，
// 不用經過 escHtml 也不會有 XSS 風險——跟這個檔案其他數值型欄位（pct/rank等）的處理一致。
function buildSparkline(pcts, dates) {{
  if (!pcts || !pcts.length) return '';
  const n = pcts.length, chartH = 26, gap = 2;
  const barW = Math.max(4, Math.floor(140 / n) - gap);
  const totalW = n * (barW + gap) - gap;
  const mid = chartH / 2;
  const maxAbs = Math.max(...pcts.map(p => Math.abs(p))) || 1;
  let bars = '';
  for (let i = 0; i < n; i++) {{
    const pct = pcts[i];
    const d = (dates && dates[i]) || '';
    const barH = Math.max(1.5, Math.abs(pct) / maxAbs * (mid - 2));
    const y = pct >= 0 ? mid - barH : mid;
    const color = pct > 0 ? 'var(--up)' : (pct < 0 ? 'var(--down)' : 'var(--ink-3)');
    const x = i * (barW + gap);
    const sign = pct >= 0 ? '+' : '';
    bars += `<rect x="${{x}}" y="${{y}}" width="${{barW}}" height="${{barH}}" fill="${{color}}" rx="1"><title>${{d}} ${{sign}}${{pct.toFixed(2)}}%</title></rect>`;
  }}
  return `<div class="sc-sparkline"><svg viewBox="0 0 ${{totalW}} ${{chartH}}" xmlns="http://www.w3.org/2000/svg">`
    + `<line x1="0" y1="${{mid}}" x2="${{totalW}}" y2="${{mid}}" stroke="var(--border)" stroke-width="1"/>${{bars}}</svg></div>`;
}}

function selectGroup(name) {{
  const existing = document.getElementById('detailPanel');
  if (existing) existing.remove();
  document.querySelectorAll('.heat-tile').forEach(t => t.classList.remove('active'));

  const tiles = [...document.querySelectorAll('.heat-tile')];
  const tile = tiles.find(t => t.dataset.metaName === name);
  if (!tile) return;
  tile.classList.add('active');

  const meta = CARD_META[name];
  if (!meta) return;
  const stocks = STOCKS[name] || [];
  const safeName = escHtml(name);

  const panel = document.createElement('div');
  panel.id = 'detailPanel';
  panel.className = 'detail-panel';
  const pctColor = meta.pct >= 0 ? 'var(--up)' : 'var(--down)';
  const pctStr = (meta.pct >= 0 ? '+' : '') + meta.pct.toFixed(2) + '%';
  // 收合按鈕故意不再靠interpolate name進onclick字串或事後從DOM文字反查——直接閉包捕捉
  // selectGroup自己的name參數，同一個安全等級的做法比「從text內容讀回名字再傳一次」更直接。
  const closeBtn = document.createElement('button');
  closeBtn.className = 'detail-close';
  closeBtn.textContent = '收合';
  closeBtn.onclick = () => selectGroup(name);

  if (!stocks.length) {{
    panel.innerHTML = `
      <div class="detail-head"><h3>${{safeName}}</h3><span class="dpct" style="color:${{pctColor}}">${{pctStr}}</span></div>
      <div class="detail-sub">▲${{meta.up_count}}檔 ▼${{meta.down_count}}檔</div>
      <div class="detail-empty">這個族群目前沒有個股行情資料。</div>`;
  }} else {{
    const cards = stocks.map(s => {{
      const color = s.change_pct >= 0 ? 'var(--up)' : 'var(--down)';
      const sign = s.change_pct >= 0 ? '+' : '';
      const spark = buildSparkline(s.pcts, s.dates);
      return `<div class="stock-card">
        <div class="sc-header"><span class="sc-id">${{escHtml(s.stock_id)}}</span><span class="sc-name">${{escHtml(s.stock_name)}}</span></div>
        <div class="sc-body"><span class="sc-price">${{s.close.toFixed(1)}}</span><span class="sc-pct" style="color:${{color}}">${{sign}}${{s.change_pct.toFixed(2)}}%</span></div>
        ${{spark}}</div>`;
    }}).join('');
    panel.innerHTML = `
      <div class="detail-head"><h3>${{safeName}}</h3><span class="dpct" style="color:${{pctColor}}">${{pctStr}}</span></div>
      <div class="detail-sub">▲${{meta.up_count}}檔 ▼${{meta.down_count}}檔　・　共 ${{stocks.length}} 檔</div>
      <div class="stock-cards-wrap">${{cards}}</div>`;
  }}
  panel.querySelector('.detail-head').appendChild(closeBtn);

  const rowTop = tile.offsetTop;
  const rowTiles = tiles.filter(t => t.offsetTop === rowTop);
  const lastInRow = rowTiles[rowTiles.length - 1];
  lastInRow.insertAdjacentElement('afterend', panel);
  panel.scrollIntoView({{behavior:'smooth', block:'nearest'}});
}}

function toggleTheme() {{
  const root = document.documentElement;
  const isLight = root.getAttribute('data-theme') === 'light';
  root.setAttribute('data-theme', isLight ? 'dark' : 'light');
  document.getElementById('themeToggle').textContent = isLight ? '切換亮色預覽' : '切換深色預覽';
}}
</script>
</body></html>"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
