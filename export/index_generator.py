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
from datetime import date, datetime
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
        return {"key": "hot", "label": f"增溫 +{accel:.1f}pt"}
    if accel <= -_TEMP_THRESHOLD_PT:
        return {"key": "cold", "label": f"退燒 {accel:.1f}pt"}
    return None


def heat_bg(pct: float, max_abs_pct: Optional[float] = None) -> str:
    """Top 10 卡片固定級距底色，不受當日最大漲跌幅影響。

    級距依絕對漲跌幅分成 0–1%、1–2%、2–4%、4%以上；紅漲綠跌且強度對稱。
    ``max_abs_pct`` 僅保留相容舊呼叫端，刻意不參與計算，確保同一漲跌幅跨日同色。
    """
    magnitude = abs(pct)
    if magnitude >= 4.0:
        alpha_pct = 62
    elif magnitude >= 2.0:
        alpha_pct = 46
    elif magnitude >= 1.0:
        alpha_pct = 30
    else:
        alpha_pct = 18
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


def find_rank_crossings(rank_history: Dict[str, Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    排名進出榜（視覺spec用語：族群近況新子類別）。比較每個meta的「本週排名」vs「上週排名」，
    找出剛跨過前10名門檻進榜/掉出榜的族群。跟轉折點列表(tier換級，見find_turning_points())
    是刻意並存的不同訊號——tier只看自身動能，這裡純粹比較相對排名，見
    docs/adr/0003-rank-crossing-signal-kept-separate-from-tier-signal.md。

    絕對報酬閘門：光跨過排名門檻還不夠，還要本週自身5日複利報酬方向跟排名方向一致，才算
    真的「進榜/掉出榜」——否則全市場普遍走弱時，「跌最少」的族群會被誤判成剛進榜(看起來
    像在噴，其實只是相對沒那麼差)，見
    docs/superpowers/specs/2026-08-03-rank-crossing-absolute-return-gate-design.md。
    剛進榜需本週weekly_returns > 0；剛掉出榜需本週weekly_returns < 0。沒有weekly_returns
    資料(例如舊格式rank_history)時視為不通過閘門，不列入任一份清單。

    rank_history: calc_meta_rank_history()的輸出。weekly_ranks長度<2(沒有『上週』可比較)
    的族群不參與判定。

    Returns
    -------
    {"just_in": [{"meta_name":.., "prev_rank":.., "cur_rank":..}, ...],
     "just_out": [{"meta_name":.., "prev_rank":.., "cur_rank":..}, ...]}
    各自依變動幅度(排名進步/退步的名次差)由大到小排序。
    """
    just_in = []
    just_out = []
    for meta_name, data in rank_history.items():
        ranks = data.get("weekly_ranks") or []
        returns = data.get("weekly_returns") or []
        if len(ranks) < 2:
            continue
        prev_rank, cur_rank = ranks[-2], ranks[-1]
        cur_return = returns[-1] if returns else None
        prev_in = prev_rank <= 10
        cur_in = cur_rank <= 10
        if not prev_in and cur_in and cur_return is not None and cur_return > 0:
            just_in.append({"meta_name": meta_name, "prev_rank": prev_rank, "cur_rank": cur_rank})
        elif prev_in and not cur_in and cur_return is not None and cur_return < 0:
            just_out.append({"meta_name": meta_name, "prev_rank": prev_rank, "cur_rank": cur_rank})

    just_in.sort(key=lambda r: r["prev_rank"] - r["cur_rank"], reverse=True)
    just_out.sort(key=lambda r: r["cur_rank"] - r["prev_rank"], reverse=True)
    return {"just_in": just_in, "just_out": just_out}


def find_anomaly_cards(
    meta_perf: List[Dict[str, Any]],
    meta_signals: Dict[str, Dict[str, Any]],
    heatgrid_windows: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    異動族群動態清單（視覺spec用語：頁面最上方快報，今日vs昨日的瞬間訊號）。不是固定5張卡，
    符合條件有幾檔就回傳幾檔。門檻是視覺 spec 定的經驗法則草案，待回測（見 Global Constraints）。

    爆量異常跳升(burst)：vol_ratio >= 1.5 且今日排名比昨日跳動 >= 10（今日排名依 avg_change_pct
    降冪計算，第1名跳動幅度最大）。
    動能加速(trend)：classify_temp(accel)=="hot" 且 streak_today >= 5（草案，要求持續而非
    曇花一現）。
    同一族群兩者都成立時，burst 優先（量能異常是更即時的訊號）。
    回傳結果依嚴重程度排序：burst 排在 trend 前面，同 kind 內依 abs(pct) 降冪。
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

    # 排序：burst(爆量異常跳升)優先於trend(動能加速)——量能異常是更即時的訊號；同kind內依
    # abs(pct)降冪(幅度大的優先)。用pct(卡片上本來就顯示給人看的數字)當排序依據，而不是
    # vol_ratio/accel，使用者比較看得懂「為什麼這張排前面」。卡片視覺大小不變，只調整順序。
    results.sort(key=lambda r: (r["kind"] != "burst", -abs(r["pct"])))
    return results


# 五級大盤方向 → 顯示樣式 + 對應筆記操作提示，從 export/html_generator.py::_REGIME_TIERS 原樣
# 搬過來（提示文字是既有、已核准的產品文案，不是這次改版新寫的，設計依據見
# docs/superpowers/specs/2026-07-09-market-regime-dashboard-design.md）。顏色改用新配色的
# var(--up)/var(--down)/var(--ink-2)，不再用舊版寫死的hex。
_REGIME_TIERS = {
    "大漲": {"color": "var(--up)",
             "tip": "漲時加碼，找主流族群最強一檔追（可追漲停）。"},
    "小漲": {"color": "var(--up)",
             "tip": "正常操作，續抱強勢股、汰弱留強。"},
    "持平": {"color": "var(--ink-2)",
             "tip": "均線上才買、觸發出場三原則就賣，反覆操作，不提前佈局盤整股。"},
    "小跌": {"color": "var(--down)",
             "tip": "持股健檢：均線空頭排列／下彎／跌破頸線任一成立就先出。"},
    "大跌": {"color": "var(--down)",
             "tip": "只找最後撐住的 5–10 檔換股，不接弱勢、不攤平、不抄底。"},
}


def _market_regime_html(market_regime: Optional[Dict[str, Any]]) -> str:
    """
    大盤分級儀表板：五級方向 + 資金集中度診斷 + 對應操作提示，從
    export/html_generator.py::_market_regime_section() 搬過來並改用新配色 CSS 變數。
    market_regime 為 None（TAIEX 抓取失敗）時回空字串，整塊不顯示，不擋頁面產生。
    """
    if not market_regime:
        return ""

    tier = market_regime.get("tier", "持平")
    style = _REGIME_TIERS.get(tier, _REGIME_TIERS["持平"])
    pct = market_regime.get("taiex_change_pct")
    pct_txt = f"{pct:+.2f}%" if pct is not None else "—"

    up = market_regime.get("up_count")
    total = market_regime.get("total")
    breadth = market_regime.get("breadth_ratio")
    breadth_html = ""
    if breadth is not None and total:
        breadth_html = (
            f'<span class="regime-breadth">上漲 <b>{up}</b> / 共 {total} 檔'
            f'（廣度 {breadth*100:.0f}%）</span>'
        )

    hw = market_regime.get("heavyweight_avg_pct")
    broad = market_regime.get("broad_avg_pct")
    conc_html = ""
    if hw is not None and broad is not None:
        direction = market_regime.get("concentration_direction")
        is_conc = market_regime.get("is_concentrated")
        divergence = market_regime.get("divergence")
        if is_conc and direction:
            head = f'<span class="regime-conc-head warn">資金集中 — {_esc(direction)}</span>'
        else:
            head = '<span class="regime-conc-head">資金分布均衡</span>'
        div_txt = f"{divergence:+.2f}" if divergence is not None else "—"
        hw_color = "var(--up)" if (hw or 0) >= 0 else "var(--down)"
        broad_color = "var(--up)" if (broad or 0) >= 0 else "var(--down)"
        conc_html = (
            '<div class="regime-conc">'
            f'{head}'
            '<div class="regime-conc-vals">'
            f'<span>權值股（前{market_regime.get("heavyweight_count", 20)}大）：'
            f'<b class="tabular" style="color:{hw_color}">{hw:+.2f}%</b></span>'
            f'<span>非權值股：<b class="tabular" style="color:{broad_color}">{broad:+.2f}%</b></span>'
            f'<span>落差：<b class="tabular">{div_txt} 個百分點</b></span>'
            '</div></div>'
        )

    return (
        f'<div class="market-regime" style="border-left-color:{style["color"]}">'
        '<div class="regime-label">大盤現況</div>'
        '<div class="regime-head">'
        f'<span class="regime-tier tabular" style="color:{style["color"]}">{_esc(tier)}</span>'
        f'<span class="regime-pct tabular" style="color:{style["color"]}">加權指數 {pct_txt}</span>'
        f'{breadth_html}'
        '</div>'
        f'<div class="regime-tip">{_esc(style["tip"])}</div>'
        f'{conc_html}'
        '</div>'
    )


def _vol_turnover_html(
    vol_turnover_signals: Optional[List[Dict[str, Any]]],
    *,
    is_intraday: bool = False,
) -> str:
    """
    巨量換手訊號（前日漲停→今日爆量收跌+三大法人確認），從
    export/html_generator.py::_vol_turnover_section() 搬過來並改用新配色 CSS 變數。
    沒有訊號時保留精簡空狀態；盤中模式改稱「疑似巨量換手」。
    """
    signal_label = "疑似巨量換手" if is_intraday else "巨量換手"
    signals = vol_turnover_signals or []

    rows = []
    for s in signals:
        chg = s.get("change_pct") or 0
        chg_color = "var(--up)" if chg >= 0 else "var(--down)"
        f_net = s.get("foreign_net")
        confirmed = s.get("inst_confirmed", False)
        inst_badge = '<span class="badge foreign">法人確認</span>' if confirmed else ""
        if f_net and f_net > 0:
            f_html = f'<span class="tabular" style="color:var(--up)">+{f_net // 1000:,}張</span>'
        elif f_net and f_net < 0:
            f_html = f'<span class="tabular" style="color:var(--down)">{f_net // 1000:,}張</span>'
        else:
            f_html = '<span class="tabular" style="color:var(--ink-3)">─</span>'
        rows.append(
            '<tr>'
            f'<td><span class="tabular" style="color:var(--ink-3)">{_esc(s["stock_id"])}</span> '
            f'<span>{_esc(s.get("stock_name", ""))}</span></td>'
            f'<td class="vt-sector">{_esc(s.get("meta_sector", ""))}</td>'
            f'<td class="tabular" style="color:{chg_color};font-weight:700">{chg:+.2f}%</td>'
            f'<td class="tabular" style="color:var(--accent);font-weight:700">{s["vol_multiple"]}x</td>'
            f'<td>{f_html}</td>'
            f'<td>{inst_badge}</td>'
            '</tr>'
        )
    rows_html = "".join(rows)
    if not rows_html:
        rows_html = f'<tr><td colspan="6" class="vt-empty">目前沒有{signal_label}訊號</td></tr>'
    return (
        '<section class="vol-turnover" aria-labelledby="vol-turnover-title">'
        f'<div class="event-head"><div><span class="eyebrow">VOLUME EVENT</span><h2 id="vol-turnover-title">{signal_label}</h2></div>'
        f'<span class="event-count tabular">{len(signals)} 檔</span></div>'
        '<div class="overflow-wrap"><table class="vt-table">'
        '<thead><tr><th>代號 / 名稱</th><th>族群</th><th>今日漲跌</th><th>量倍數</th><th>外資</th><th>確認</th></tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        '</table></div></section>'
    )


def build_heatgrid_cards(
    meta_perf: List[Dict[str, Any]],
    meta_signals: Dict[str, Dict[str, Any]],
    meta_chips: Dict[str, Dict[str, Any]],
    heatgrid_windows: Dict[str, Dict[str, Any]],
    cum_data: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    熱區格 41 張卡片資料（視覺 spec §3「族群排行」），依 avg_change_pct 降冪排列。組合
    meta_perf（今日漲跌/家數）+ meta_signals（量比+昨日排名，既有函式）+ meta_chips（外資/
    投信連買天數，既有函式）+ heatgrid_windows（processors/performance.py::calc_meta_heatgrid_windows()
    算的原始窗口值，這裡才做 classify_tier/classify_temp 分類）+ cum_data
    （processors/performance.py::calc_cumulative_meta() 的原始 list，這裡轉成 dict 查表）。

    cum_data 沒傳、或某族群沒有對應資料時，cum3/cum5/cum7 都是 None（前端不顯示該badge，
    不補假資料）。排名升降用 meta_signals 既有的 yesterday_rank 跟這次算出的今日排名比較，
    yesterday_rank 缺值時不顯示排名箭頭。
    """
    ranked = sorted(meta_perf, key=lambda r: r["avg_change_pct"], reverse=True)
    cum_map = {row["meta_name"]: row for row in (cum_data or [])}

    cards = []
    for i, row in enumerate(ranked):
        meta_name = row["meta_name"]
        sig = meta_signals.get(meta_name, {})
        chips = meta_chips.get(meta_name, {})
        window_data = heatgrid_windows.get(meta_name, {})
        cum = cum_map.get(meta_name, {})
        pct = row["avg_change_pct"]
        accel = _accel_from_windows(window_data)
        today_rank = i + 1
        yesterday_rank = sig.get("yesterday_rank")
        rank_delta = (yesterday_rank - today_rank) if yesterday_rank is not None else None

        cards.append({
            "rank": today_rank,
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
            "heat_bg": heat_bg(pct),
            "cum3": cum.get("cum3"),
            "cum5": cum.get("cum5"),
            "cum7": cum.get("cum7"),
            "rank_delta": rank_delta,
        })
    return cards


_SECTOR_RECAP_TOP_N = 5


# Cody回報「功率半導體排名#40→#1、今日+5.66%，卻被歸類成退燒」——accel(週對週5日
# 滾動窗比較)跟「今天是不是正在發生大事」是兩個不同問題，週對週看的是趨勢，不是單日
# 事件，兩者合法地可以背離(上週已經噴完、這幾天在打底、今天才又爆量;週對週平均因此
# 仍是負的，即使今天單日很強)。異動族群(find_anomaly_cards)的burst判定又同時要求
# vol_ratio>=1.5，功率半導體今天沒有這麼高的量比，兩邊都漏接。修法：
# 1. 新增「今日爆發」類別，只看排名跳動+今日漲跌，不要求量比同時成立。
# 2. cold_top5排除掉「今日爆發」的族群——同一族群不該同時被講成「退燒」又「爆發」，
#    這兩個標籤對使用者來說是矛盾的。
_BREAKOUT_RANK_JUMP_MIN = 10
_STEALTH_STREAK_MIN = 3
_STEALTH_PRICE_FLAT_MAX = 1.0
_VOL_ANOMALY_RATIO_MIN = 1.5
_VOL_ANOMALY_PRICE_FLAT_MAX = 2.0

_RESEARCH_BUCKET_LIMITS = {"research": 10, "watch": 5, "avoid": 5}


def build_sector_recap(
    cards: List[Dict[str, Any]],
    heatgrid_windows: Dict[str, Dict[str, Any]],
    rank_history: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    族群近況（視覺 spec §4 擴充版）：升溫/退燒/今日爆發/外資悄悄佈局/投信悄悄佈局/量能異常，
    共6類 Top5 + 轉折點列表。cards 是 build_heatgrid_cards() 的輸出（已經算好 pct/accel/
    vol_ratio/foreign_streak/trust_streak/rank_delta，這裡不重算，直接篩選分類）。

    每一類別互相獨立（同一族群理論上可以同時符合多個類別，例如今日爆發+量能異常），
    唯一的例外是cold_top5刻意排除today_breakout的族群（見上方模組註解）。任何一個
    分類條件所需的欄位是None（資料不足）都不參與該分類排序，不硬排。
    """
    with_accel = [c for c in cards if c["accel"] is not None]
    hot_top5 = sorted(with_accel, key=lambda r: r["accel"], reverse=True)[:_SECTOR_RECAP_TOP_N]

    breakout_names = {
        c["meta_name"] for c in cards
        if c["rank_delta"] is not None and c["rank_delta"] >= _BREAKOUT_RANK_JUMP_MIN and c["pct"] > 0
    }
    cold_candidates = [c for c in with_accel if c["meta_name"] not in breakout_names]
    cold_top5 = sorted(cold_candidates, key=lambda r: r["accel"])[:_SECTOR_RECAP_TOP_N]

    today_breakout = sorted(
        (c for c in cards if c["meta_name"] in breakout_names),
        key=lambda r: r["rank_delta"], reverse=True,
    )[:_SECTOR_RECAP_TOP_N]

    foreign_stealth = sorted(
        (c for c in cards if c["foreign_streak"] is not None and c["foreign_streak"] >= _STEALTH_STREAK_MIN
         and abs(c["pct"]) <= _STEALTH_PRICE_FLAT_MAX),
        key=lambda r: r["foreign_streak"], reverse=True,
    )[:_SECTOR_RECAP_TOP_N]

    trust_stealth = sorted(
        (c for c in cards if c["trust_streak"] is not None and c["trust_streak"] >= _STEALTH_STREAK_MIN
         and abs(c["pct"]) <= _STEALTH_PRICE_FLAT_MAX),
        key=lambda r: r["trust_streak"], reverse=True,
    )[:_SECTOR_RECAP_TOP_N]

    volume_anomaly = sorted(
        (c for c in cards if c["vol_ratio"] is not None and c["vol_ratio"] >= _VOL_ANOMALY_RATIO_MIN
         and abs(c["pct"]) <= _VOL_ANOMALY_PRICE_FLAT_MAX),
        key=lambda r: r["vol_ratio"], reverse=True,
    )[:_SECTOR_RECAP_TOP_N]

    # turning_points 傳入前先用 cards 的族群集合過濾 heatgrid_windows——
    # calc_meta_performance()/calc_meta_heatgrid_windows() 是main.py裡兩個獨立呼叫，
    # 理論上族群集合可能不完全一致，不過濾會讓同一個回傳值裡其他分類排除了某族群、
    # 但turning_points卻還顯示它，是自相矛盾的輸出。
    active_names = {c["meta_name"] for c in cards}
    active_windows = {name: data for name, data in heatgrid_windows.items() if name in active_names}
    active_rank_history = {
        name: data for name, data in (rank_history or {}).items() if name in active_names
    }

    return {
        "hot_top5": hot_top5,
        "cold_top5": cold_top5,
        "today_breakout": today_breakout,
        "foreign_stealth": foreign_stealth,
        "trust_stealth": trust_stealth,
        "volume_anomaly": volume_anomaly,
        "turning_points": find_turning_points(active_windows),
        "rank_crossings": find_rank_crossings(active_rank_history),
    }


def build_research_buckets(
    cards: List[Dict[str, Any]],
    anomaly_cards: List[Dict[str, Any]],
    rank_history: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """建立首頁互斥的研究分類，不改動底層既有 recap 計算。

    優先序固定為「值得研究 → 先觀察 → 避開」，避免同一族群重複出現。短線與週度
    訊號相反時仍保留主要分類，並以客觀衝突標記呈現。
    """
    anomaly_kind = {row["meta_name"]: row["kind"] for row in anomaly_cards}
    just_out_names = {
        row["meta_name"] for row in find_rank_crossings(rank_history or {})["just_out"]
    }
    buckets: Dict[str, List[Dict[str, Any]]] = {"research": [], "watch": [], "avoid": []}

    for card in cards:
        name = card["meta_name"]
        rank_delta = card.get("rank_delta")
        temp_key = (card.get("temp") or {}).get("key")
        vol_ratio = card.get("vol_ratio")
        is_rank_jump = rank_delta is not None and rank_delta >= _BREAKOUT_RANK_JUMP_MIN and card["pct"] > 0
        is_live_anomaly = name in anomaly_kind
        is_warming = temp_key == "hot"
        is_volume_anomaly = (
            vol_ratio is not None
            and vol_ratio >= _VOL_ANOMALY_RATIO_MIN
            and abs(card["pct"]) <= _VOL_ANOMALY_PRICE_FLAT_MAX
        )
        is_cooling = temp_key == "cold"
        just_out = name in just_out_names

        bucket = None
        primary_tag = ""
        conflicts: List[str] = []
        if is_live_anomaly or is_rank_jump:
            bucket = "research"
            if anomaly_kind.get(name) == "burst" or (is_rank_jump and vol_ratio is not None and vol_ratio >= _ANOMALY_VOL_RATIO_MIN):
                primary_tag = "爆量異常跳升"
            elif anomaly_kind.get(name) == "trend":
                primary_tag = "動能加速"
            else:
                primary_tag = "短線異常跳升"
            if is_cooling:
                conflicts.append("週度仍退燒")
            if just_out:
                conflicts.append("週排行剛掉出前10")
        elif is_warming or is_volume_anomaly:
            bucket = "watch"
            primary_tag = "週度增溫" if is_warming else "量能異常"
            if just_out:
                conflicts.append("週排行剛掉出前10")
        elif is_cooling or just_out:
            bucket = "avoid"
            primary_tag = "週度退燒" if is_cooling else "剛掉出前10"
            if card["pct"] > 0 and rank_delta is not None and rank_delta > 0:
                conflicts.append("今日仍走強")

        if bucket is None:
            continue
        buckets[bucket].append({
            **card,
            "bucket": bucket,
            "primary_tag": primary_tag,
            "conflict_tags": conflicts,
        })

    buckets["research"].sort(
        key=lambda row: row.get("rank_delta") if row.get("rank_delta") is not None else -10_000,
        reverse=True,
    )
    buckets["watch"].sort(
        key=lambda row: row.get("accel") if row.get("accel") is not None else -10_000,
        reverse=True,
    )
    buckets["avoid"].sort(
        key=lambda row: row.get("accel") if row.get("accel") is not None else 10_000,
    )
    return {
        key: rows[:_RESEARCH_BUCKET_LIMITS[key]]
        for key, rows in buckets.items()
    }


def _chips_num(value) -> Optional[int]:
    if value is None or pd.isna(value):
        return None
    return int(value)


def build_stock_detail_data(
    universe_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    stock_sparklines: Optional[Dict[str, dict]] = None,
    rolling_returns: Optional[Dict[str, dict]] = None,
    chips_df: Optional[pd.DataFrame] = None,
    total_shares_df: Optional[pd.DataFrame] = None,
    avg20_map: Optional[Dict[str, float]] = None,
    shareholder_df: Optional[pd.DataFrame] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    個股點開面板資料（視覺 spec §「點開個股清單」）。全部 meta_sector 都要有 key（即使該族群
    沒有任何股票有行情資料，回空 list），族群內依 change_pct 降冪排列（無行情的排在最後）。

    stock_sparklines：processors/performance.py::calc_stock_sparklines() 的輸出，供畫走勢圖，
    也是 volumes（近11日成交量歷史，供個股卡片走勢圖下方疊加量能柱狀圖）/volume（今日
    成交量，即volumes最後一筆）/vol_ratio（今日量/前10日均量，注意不是MA20，跟
    patterns.html的量比算法不同）/opens、highs、lows、closes（近11日OHLC歷史，供個股
    卡片畫K棒走勢圖，取代原本純%漲跌bar）的來源——沿用舊版
    html_generator.py::_stock_card_html() 的資料來源，不重算。
    rolling_returns：screener/database.py::get_rolling_returns((5,7,10,14)) 的輸出
    {stock_id: {5:pct或None, 7:.., 10:.., 14:..}}，跟chips.html「近N日」算法一致。
    chips_df：screener/database.py::get_chips_today() 的輸出（stock_id欄位，非index），
    供外資/投信/融資卡片摘要。以上三者任一沒傳、或這支股票沒有對應資料，都回傳None/空list，
    不補假資料、不crash。
    total_shares_df：screener/database.py::get_latest_total_shares() 的輸出（含
    stock_id/total_shares/date欄位），供financed_pct/shorted_pct的分母(已發行股數)
    +集保資料實際日期(total_shares_asof)。
    avg20_map：processors/performance.py::calc_avg20_close() 的輸出，供
    maintenance_est/short_maintenance_est的成本基準。兩者任一沒傳、或這支股票
    沒有對應資料，四個新欄位都回傳None（不補假資料）。
    shareholder_df：screener/database.py::get_shareholder_top() 的輸出（含stock_id/
    lv12_15_pct/week_chg欄位），供個股表格「大戶佔比」「大戶週變化」兩欄。這支函式已經
    內建離群值防護(_MAX_VALID_HOLDER_PCT)並過濾掉異常值，這裡不用再重覆過濾——沒傳、或
    這支股票不在裡面(被防護排除、或還沒有集保資料)，兩欄都回None，前端顯示「—」。

    無行情的個股不再跳過——改成標記 no_data=True（比照舊版html_generator.py的「無行情」
    佔位符慣例），close/change_pct/pcts/dates/roll*/chips都是None/空，前端顯示成灰階佔位卡。
    """
    universe_cols = ["stock_id", "stock_name", "meta_sector"]
    if "exchange" in universe_df.columns:
        universe_cols.append("exchange")
    universe = universe_df[universe_cols].copy()
    universe["stock_id"] = universe["stock_id"].astype(str)
    prices = prices_df.copy()
    if not prices.empty:
        prices["stock_id"] = prices["stock_id"].astype(str)
    prices_map = prices.set_index("stock_id") if not prices.empty else pd.DataFrame()
    sparklines = stock_sparklines or {}
    rolling = rolling_returns or {}
    chips = chips_df.copy() if chips_df is not None and not chips_df.empty else pd.DataFrame()
    if not chips.empty:
        chips["stock_id"] = chips["stock_id"].astype(str)
    chips_map = chips.set_index("stock_id") if not chips.empty else pd.DataFrame()
    total_shares = total_shares_df.copy() if total_shares_df is not None and not total_shares_df.empty else pd.DataFrame()
    if not total_shares.empty:
        total_shares["stock_id"] = total_shares["stock_id"].astype(str)
    total_shares_map = total_shares.set_index("stock_id") if not total_shares.empty else pd.DataFrame()
    avg20 = avg20_map or {}
    shareholder = shareholder_df.copy() if shareholder_df is not None and not shareholder_df.empty else pd.DataFrame()
    if not shareholder.empty:
        shareholder["stock_id"] = shareholder["stock_id"].astype(str)
    shareholder_map = shareholder.set_index("stock_id") if not shareholder.empty else pd.DataFrame()

    result: Dict[str, List[Dict[str, Any]]] = {
        meta_name: [] for meta_name in universe["meta_sector"].dropna().unique()
    }

    for _, row in universe.iterrows():
        sid = row["stock_id"]
        meta_name = row["meta_sector"]
        if pd.isna(meta_name):
            continue
        has_price = sid in prices_map.index
        spark = sparklines.get(sid, {})
        roll = rolling.get(sid, {})
        c = chips_map.loc[sid] if sid in chips_map.index else None
        close_price = float(prices_map.loc[sid]["close"]) if has_price else None

        # 融資成數：上市6成/上櫃5成，注意股/處置股例外不處理（見spec Out of Scope）
        exchange = row.get("exchange")
        financing_ratio = 0.6 if exchange == "TWSE" else 0.5

        margin_balance_lots = _chips_num(c["margin_balance"]) if c is not None else None
        short_balance_lots = _chips_num(c.get("short_balance")) if c is not None else None
        total_shares_val = (
            int(total_shares_map.loc[sid, "total_shares"]) if sid in total_shares_map.index else None
        )
        total_shares_asof_raw = (
            total_shares_map.loc[sid, "date"] if sid in total_shares_map.index else None
        )
        total_shares_asof = (
            pd.Timestamp(total_shares_asof_raw).strftime("%Y-%m-%d")
            if total_shares_asof_raw is not None and pd.notna(total_shares_asof_raw) else None
        )
        avg20_close = avg20.get(sid)
        holder_pct = (
            float(shareholder_map.loc[sid, "lv12_15_pct"])
            if sid in shareholder_map.index and pd.notna(shareholder_map.loc[sid, "lv12_15_pct"]) else None
        )
        holder_week_chg = (
            float(shareholder_map.loc[sid, "week_chg"])
            if sid in shareholder_map.index and pd.notna(shareholder_map.loc[sid, "week_chg"]) else None
        )

        financed_pct = (
            round(margin_balance_lots * 1000 / total_shares_val * 100, 2)
            if margin_balance_lots and total_shares_val else None
        )
        maintenance_est = (
            round(close_price / avg20_close / financing_ratio * 100, 1)
            if margin_balance_lots and avg20_close and close_price is not None else None
        )
        shorted_pct = (
            round(short_balance_lots * 1000 / total_shares_val * 100, 2)
            if short_balance_lots and total_shares_val else None
        )
        short_maintenance_est = (
            round(avg20_close / close_price / financing_ratio * 100, 1)
            if short_balance_lots and avg20_close and close_price is not None else None
        )

        entry: Dict[str, Any] = {
            "stock_id": sid,
            "stock_name": row["stock_name"],
            "no_data": not has_price,
            "close": close_price,
            "change_pct": float(prices_map.loc[sid]["change_pct"]) if has_price else None,
            "pcts": spark.get("pcts", []),
            "dates": spark.get("dates", []),
            "iso_dates": spark.get("iso_dates", []),
            "volumes": spark.get("volumes", []),
            "volume": spark.get("volumes", [None])[-1] if spark.get("volumes") else None,
            "vol_ratio": spark.get("vol_ratio"),
            "opens": spark.get("opens", []),
            "highs": spark.get("highs", []),
            "lows": spark.get("lows", []),
            "closes": spark.get("closes", []),
            "roll5": roll.get(5), "roll7": roll.get(7), "roll10": roll.get(10), "roll14": roll.get(14),
            "foreign_net": _chips_num(c["foreign_net"]) if c is not None else None,
            "trust_net": _chips_num(c["trust_net"]) if c is not None else None,
            "margin_balance": _chips_num(c["margin_balance"]) if c is not None else None,
            "margin_change": _chips_num(c["margin_change"]) if c is not None else None,
            "financed_pct": financed_pct,
            "maintenance_est": maintenance_est,
            "shorted_pct": shorted_pct,
            "short_maintenance_est": short_maintenance_est,
            "total_shares_asof": total_shares_asof,
            "holder_pct": holder_pct,
            "holder_week_chg": holder_week_chg,
        }
        result[meta_name].append(entry)

    for meta_name in result:
        result[meta_name].sort(
            key=lambda s: s["change_pct"] if s["change_pct"] is not None else float("-inf"),
            reverse=True,
        )

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

.topbar{position:sticky;top:0;z-index:30;display:flex;align-items:baseline;gap:16px;padding:16px 26px;border-bottom:1px solid var(--border);flex-wrap:wrap;background:color-mix(in srgb,var(--bg) 94%,transparent);backdrop-filter:blur(12px)}
.topbar h1{font-family:var(--serif);font-size:1.28rem;font-weight:600;color:var(--ink);letter-spacing:.01em;margin:0}
.topbar .kicker{font-size:.62rem;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--accent)}
.topbar .updated{font-size:.72rem;color:var(--ink-3);margin-left:auto;font-family:var(--mono)}
.topbar button{font-family:var(--mono);font-size:.68rem;background:var(--panel-2);border:1px solid var(--border);color:var(--ink-2);padding:5px 12px;border-radius:4px;cursor:pointer}
.search-wrap{position:relative;flex:1;min-width:160px;max-width:320px}
.stock-search{width:100%;background:var(--panel-2);border:1px solid var(--border);border-radius:6px;padding:6px 12px;color:var(--ink);font-family:var(--sans);font-size:.8rem;outline:none}
.stock-search:focus{border-color:var(--border-2)}
.search-dropdown{position:absolute;top:calc(100% + 4px);left:0;right:0;background:var(--panel-2);border:1px solid var(--border-2);border-radius:6px;box-shadow:var(--shadow-2);z-index:50;max-height:360px;overflow-y:auto}
.search-item{display:flex;align-items:center;gap:8px;padding:8px 12px;cursor:pointer;font-size:.8rem}
.search-item:hover{background:var(--panel-3)}
.search-item .si-id{font-family:var(--mono);color:var(--ink-3);font-size:.72rem;flex-shrink:0}
.search-item .si-meta-icon{color:var(--accent)}
.search-item .si-name{font-family:var(--serif);font-weight:600;color:var(--ink);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.search-item .si-meta{color:var(--ink-3);font-size:.7rem;flex-shrink:0}
.search-item .si-pct{font-family:var(--mono);font-weight:700;flex-shrink:0}
.nav-links{display:flex;align-items:center;gap:8px;white-space:nowrap}
.nav-link{display:inline-flex;align-items:center;min-height:32px;font-family:var(--sans);font-size:.78rem;font-weight:600;padding:5px 14px;border-radius:6px;border:1px solid var(--border);color:var(--ink-2);text-decoration:none;transition:color .15s,border-color .15s,background .15s}
.nav-link:hover{border-color:var(--ink-2);color:var(--ink)}
.nav-link.active{border-color:var(--accent);color:var(--ink);background:var(--panel-2)}
.nav-link:focus-visible,button:focus-visible,.heat-tile:focus-visible,.anomaly-card:focus-visible{outline:3px solid var(--accent);outline-offset:2px}

.section-head{display:flex;align-items:baseline;gap:12px;padding:26px 26px 8px}
.section-head h2{font-family:var(--serif);font-size:1.05rem;font-weight:600;color:var(--ink);margin:0}
.section-head .count{font-family:var(--mono);font-size:.7rem;color:var(--ink-3)}
.section-rule{height:1px;background:linear-gradient(to right,var(--ink) 0%,var(--border) 45%,transparent 100%);margin:0 26px 4px}
.section-sub{padding:0 26px 14px;font-size:.76rem;color:var(--ink-2);max-width:720px}

.market-regime{margin:0 26px 20px;padding:16px 18px;background:var(--panel);border:1px solid var(--border);border-left:3px solid var(--ink-3);border-radius:8px}
.regime-label{font-family:var(--mono);font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--ink-3);margin-bottom:8px}
.regime-head{display:flex;align-items:baseline;flex-wrap:wrap;gap:12px}
.regime-tier{font-size:1.3rem;font-weight:800}
.regime-pct{font-size:1rem;font-weight:700}
.regime-breadth{color:var(--ink-2);font-size:.8rem}
.regime-breadth b{color:var(--up)}
.regime-tip{margin-top:8px;font-size:.86rem;color:var(--ink-2)}
.regime-conc{margin-top:10px;padding-top:10px;border-top:1px solid var(--border);font-size:.82rem}
.regime-conc-head{font-weight:700;color:var(--ink-2)}
.regime-conc-head.warn{color:var(--accent)}
.regime-conc-vals{display:flex;gap:18px;margin-top:6px;color:var(--ink-2);flex-wrap:wrap}
.regime-conc-vals b{color:var(--ink)}

.vol-turnover{margin:18px 0 0;padding:14px 16px;background:var(--panel);border:1px solid var(--border);border-radius:8px}
table.vt-table{width:100%;border-collapse:collapse}
.vt-table th{text-align:left;padding:4px 8px;font-size:.65rem;color:var(--ink-3);border-bottom:1px solid var(--border)}
.vt-table td{padding:6px 8px;font-size:.8rem;border-bottom:1px solid var(--border)}
.vt-sector{color:var(--ink-3);font-size:.72rem;max-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

.heatgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(224px,1fr));gap:8px;padding:0 26px}
.heat-tile{
  border-radius:5px;padding:13px 14px;cursor:pointer;transition:transform .15s,box-shadow .15s;
  position:relative;border:1px solid rgba(255,255,255,.06);background:var(--panel);
  border-top:3px solid transparent;
}
.heat-tile:hover{transform:translateY(-2px);box-shadow:var(--shadow-2);z-index:2}
.heat-tile.active{outline:2px solid var(--accent);outline-offset:-2px}

.detail-panel{
  margin:20px 26px 0;background:var(--panel);border:1px solid var(--accent);border-radius:5px;
  padding:22px 26px;box-shadow:var(--shadow-2);scroll-margin-top:20px;
  animation:expandIn .22s ease-out;
}
@keyframes expandIn{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:translateY(0)}}
.detail-head{display:flex;align-items:baseline;gap:12px;margin-bottom:2px}
.detail-head h3{font-family:var(--sans);font-size:1.22rem;font-weight:700;margin:0;color:var(--ink)}
.detail-head .dpct{font-family:var(--mono);font-size:.98rem;font-weight:700}
.detail-close{margin-left:auto;font-family:var(--mono);font-size:.68rem;background:none;border:1px solid var(--border);color:var(--ink-3);padding:4px 10px;border-radius:4px;cursor:pointer}
.detail-sub{font-size:.75rem;color:var(--ink-3);margin-bottom:8px;font-family:var(--mono)}
.detail-three-col{display:grid;grid-template-columns:1fr 1fr 1.3fr;gap:12px;margin:10px 0 14px}
@media (max-width:768px){.detail-three-col{grid-template-columns:1fr}}
.tc-box{background:var(--panel-2);border-radius:5px;padding:10px 12px}
.meta-sparkline{margin:0;line-height:0}
.meta-sparkline svg{width:100%;height:auto;display:block}
.chips-summary{display:flex;flex-direction:column;gap:6px;flex-wrap:wrap;margin:0;padding:0;background:none;font-size:.76rem}
.cs-row{display:flex;align-items:center;gap:6px}
.cs-row .cs-label{color:var(--ink-3)}
.cs-row .cs-sub{color:var(--ink-3);font-size:.68rem}
.cs-row .cs-streak-up{color:var(--up);font-size:.68rem}
.cs-row .cs-streak-dn{color:var(--down);font-size:.68rem}
.cs-row .cs-alert{color:var(--accent);font-size:.68rem;font-weight:700}
.cs-row.cs-week{width:100%;border-top:1px solid var(--border);padding-top:8px;margin-top:2px;gap:14px}
.overflow-wrap{overflow-x:auto}
table.stock-list-table{width:100%;border-collapse:collapse}
.stock-list-table thead th{text-align:left;padding:0 12px 10px;border-bottom:1px solid var(--border-2)}
.stock-list-table thead th.num{text-align:right}
.stock-list-table .sort-button{display:inline-flex;align-items:center;gap:4px;background:none;border:0;
  padding:0;font-family:var(--mono);font-size:.74rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;
  color:var(--ink-3);cursor:pointer}
.stock-list-table thead th.num .sort-button{margin-left:auto}
.stock-list-table .sort-button::after{content:"↕";color:var(--ink-3);font-size:.7rem}
.stock-list-table th[aria-sort="ascending"] .sort-button::after{content:"↑";color:var(--accent)}
.stock-list-table th[aria-sort="descending"] .sort-button::after{content:"↓";color:var(--accent)}
.stock-list-table tbody td{padding:10px 12px;border-bottom:1px solid var(--border);font-size:.95rem}
.stock-item{cursor:pointer;transition:background .15s}
.stock-item:hover{background:var(--panel-2)}
.stock-item:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.stock-item.no-data{opacity:.5;cursor:default}
.stock-item .si-id{font-family:var(--mono);color:var(--ink-3);font-size:.8rem;margin-right:8px}
.stock-item .si-name{font-family:var(--sans);font-weight:650;color:var(--ink);font-size:.94rem}
.stock-item td.num{font-family:var(--mono);font-variant-numeric:tabular-nums;text-align:right}

.stock-card-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:200;
  display:flex;align-items:center;justify-content:center;padding:20px}
.stock-card-modal{background:var(--panel);border:1px solid var(--border-2);border-radius:8px;
  padding:22px 24px;box-shadow:var(--shadow-2);max-width:920px;width:100%;max-height:88vh;overflow-y:auto}
.stock-card-modal .sc-header{display:flex;align-items:baseline;gap:8px;margin-bottom:6px}
.stock-card-modal .sc-id{font-family:var(--mono);color:var(--ink-3);font-size:.72rem}
.stock-card-modal .sc-name{font-family:var(--sans);font-weight:700;color:var(--ink);font-size:1.05rem;flex:1;min-width:0}
.stock-card-modal .sc-body{display:flex;align-items:baseline;gap:12px;font-family:var(--mono);font-variant-numeric:tabular-nums;margin-bottom:10px}
.stock-card-modal .sc-price{font-size:1rem;color:var(--ink-2)}
.stock-card-modal .sc-pct{font-size:1rem;font-weight:700}
.sc-volume-row{display:flex;align-items:center;gap:10px;margin-bottom:10px;font-family:var(--mono);font-size:.76rem;color:var(--ink-3);flex-wrap:wrap}
.vol-ratio{color:var(--ink-3)}
.vol-ratio.strong{color:var(--accent);font-weight:700}
.vol-burst-badge{display:inline-block;padding:1px 5px;border-radius:3px;font-size:.68rem;font-weight:700;
  background:color-mix(in srgb, var(--accent) 20%, transparent);color:var(--accent);vertical-align:middle}
.maint-badge{display:inline-block;padding:1px 5px;border-radius:3px;font-size:.68rem;font-weight:700;
  background:color-mix(in srgb, var(--down) 20%, transparent);color:var(--down);vertical-align:middle;margin-left:3px}
.asof-note{font-size:.68rem;color:var(--ink-3);margin:6px 0 0;font-family:var(--mono)}
.sc-spark-empty{display:block;margin-bottom:10px;font-size:.76rem;color:var(--ink-3);font-family:var(--serif)}
.sc-sparkline{margin-bottom:10px;line-height:0}
.sc-sparkline svg{width:100%;height:auto;display:block}
.tv-chart-shell{position:relative;margin:14px 0 12px;padding:10px 10px 6px;border:1px solid var(--border);border-radius:6px;background:var(--panel-2)}
.tv-chart{width:100%;height:360px}
.tv-chart-status{position:absolute;z-index:2;inset:10px 10px 27px;display:grid;place-items:center;background:var(--panel-2);color:var(--ink-3);font-family:var(--sans);font-size:.78rem}
.tv-chart-status[hidden]{display:none}
.tv-attribution{display:inline-flex;margin-top:5px;color:var(--ink-3);font-size:.62rem;text-decoration:none}
.tv-attribution:hover{color:var(--ink-2);text-decoration:underline}
.sc-roll{display:flex;gap:10px;margin-bottom:10px;font-family:var(--mono);font-size:.72rem;flex-wrap:wrap}
.sc-roll-item .lbl{color:var(--ink-3);margin-right:3px}
.sc-chips{display:flex;gap:10px;font-family:var(--mono);font-size:.72rem;flex-wrap:wrap;color:var(--ink-3)}
.detail-empty{color:var(--ink-3);font-size:.86rem;padding:20px 0;font-family:var(--serif)}

.ht-top{display:flex;align-items:baseline;gap:8px}
.ht-rank{font-family:var(--mono);font-size:.6rem;color:var(--ink-3);flex-shrink:0}
.ht-name{font-family:var(--serif);font-weight:700;font-size:.96rem;color:var(--ink);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;letter-spacing:.01em}
.ht-pct{font-family:var(--mono);font-weight:700;font-size:1.0rem;flex-shrink:0}
.ht-status-row{display:flex;align-items:center;gap:6px;margin-top:8px;flex-wrap:wrap}
.badge{font-family:var(--mono);font-size:.58rem;font-weight:700;padding:2px 6px;border-radius:3px;display:inline-flex;align-items:center;gap:3px}
.badge.foreign{background:rgba(212,162,78,.16);color:var(--accent);border:1px solid rgba(212,162,78,.3)}
.ht-rank-delta{font-size:.6rem;font-weight:700}
.ht-rank-delta.up{color:var(--up)}
.ht-rank-delta.down{color:var(--down)}
.history-wrap{margin-top:16px}
.history-summary{font-family:var(--serif);font-size:.92rem;color:var(--ink);margin-bottom:10px;
  padding:9px 13px;background:var(--panel-2);border-left:3px solid var(--accent);border-radius:0 4px 4px 0}
.history-summary b{color:var(--accent)}
.history-weekline-label{font-family:var(--mono);font-size:.6rem;font-weight:700;color:var(--ink-3);
  letter-spacing:.06em;text-transform:uppercase;margin-bottom:6px}
.history-weekline{display:grid;grid-template-columns:repeat(5,1fr);gap:6px}
.history-week{border:1px solid var(--border);border-radius:5px;padding:7px 8px;background:var(--panel-3);
  font-family:var(--mono);font-size:.64rem;color:var(--ink-2);text-align:center}
.history-week .hw-label{display:block;color:var(--ink-3)}
.history-week .hw-rank{display:block;margin-top:3px;font-size:.86rem;font-weight:700;color:var(--ink)}
.history-week .hw-pct{display:block;margin-top:2px;font-size:.62rem;font-weight:600}
.history-week.in-top10{border-color:color-mix(in srgb, var(--accent) 45%, var(--border))}
.history-week.in-top10 .hw-rank{color:var(--accent)}

/* 2026-09 desktop research workspace */
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
[hidden]{display:none!important}
.topbar{align-items:center;gap:14px;padding:10px 26px;background:color-mix(in srgb,var(--bg) 96%,transparent)}
.topbar .brand{display:flex;align-items:baseline;gap:10px;white-space:nowrap}
.topbar .brand h1{font-size:1.08rem}
.topbar .updated{display:flex;flex-direction:column;align-items:flex-end;gap:2px;line-height:1.2}
.topbar .updated strong{font-size:.68rem;color:var(--accent);font-weight:700}
.topbar .updated span{font-size:.64rem;color:var(--ink-3)}
.page-shell{max-width:1560px;margin:0 auto;padding:20px 26px 48px}
.market-section .market-regime{margin:0}
.data-error{max-width:1560px;margin:14px auto 0;padding:12px 26px;background:color-mix(in srgb,var(--down) 12%,var(--panel));border-block:1px solid color-mix(in srgb,var(--down) 45%,var(--border));font-size:.76rem;color:var(--ink)}
.data-error span{display:block;margin-top:3px;color:var(--ink-3)}
.eyebrow{display:block;margin-bottom:4px;font-family:var(--mono);font-size:.58rem;font-weight:700;letter-spacing:.15em;color:var(--accent)}
.vol-turnover{margin:14px 0 24px;padding:0;background:var(--panel);border:1px solid var(--border);border-left:3px solid var(--accent);border-radius:5px;overflow:hidden}
.event-head{display:flex;align-items:center;justify-content:space-between;padding:14px 16px 10px}
.event-head h2{margin:0;font-family:var(--serif);font-size:1rem;color:var(--ink)}
.event-count{font-size:.7rem;color:var(--ink-3)}
.vol-turnover .overflow-wrap{padding:0 16px 14px}
.vt-empty{text-align:center!important;padding:18px!important;color:var(--ink-3)!important}
.ranking-section,.research-section{background:color-mix(in srgb,var(--panel) 72%,transparent);border:1px solid var(--border);border-radius:6px}
.ranking-section{padding:0 16px 18px}
.section-head.ranking-head,.section-head.compact{padding:18px 0 12px;align-items:flex-end}
.section-head.ranking-head h2,.section-head.compact h2{font-size:1.05rem}
.ranking-toolbar{display:flex;align-items:flex-end;gap:8px;padding:10px 0 14px;border-top:1px solid var(--border);flex-wrap:wrap}
.control-field{display:flex;flex-direction:column;gap:5px;min-width:140px;font-size:.62rem;color:var(--ink-3)}
.control-field.compact{min-width:128px}.control-field.grow{flex:1;min-width:180px;max-width:320px}
.control-field input,.control-field select{height:38px;min-width:0;padding:0 10px;border:1px solid var(--border);border-radius:4px;background:var(--panel-2);color:var(--ink);font:inherit;font-size:.76rem}
.toolbar-button,.icon-button,.segment{min-height:38px;padding:0 12px;border:1px solid var(--border);border-radius:4px;background:var(--panel-2);color:var(--ink-2);font-family:var(--mono);font-size:.67rem;cursor:pointer;transition:background .18s,color .18s,border-color .18s}
.toolbar-button:hover,.icon-button:hover,.segment:hover{background:var(--panel);color:var(--ink);border-color:var(--ink-3)}
.toolbar-button.primary,.segment.active{background:color-mix(in srgb,var(--accent) 16%,var(--panel));color:var(--accent);border-color:color-mix(in srgb,var(--accent) 55%,var(--border))}
.toolbar-button.quiet{background:transparent}.icon-button{width:38px;padding:0;font-size:.82rem;font-weight:700}
.segmented{display:flex;align-items:center}.segmented .segment{border-radius:0}.segmented .segment:first-child{border-radius:4px 0 0 4px}.segmented .segment:last-child{border-radius:0 4px 4px 0;margin-left:-1px}
.advanced-filters{display:flex;align-items:flex-end;gap:12px;padding:14px;margin:0 0 14px;background:var(--panel-2);border:1px solid var(--border);border-radius:5px;flex-wrap:wrap}
.advanced-filters .control-field{min-width:120px}.advanced-filters .check-field{display:flex;align-items:center;min-height:38px;gap:7px;font-size:.72rem;color:var(--ink-2)}
.advanced-filters input[type=checkbox]{width:17px;height:17px;accent-color:var(--accent)}
.heatgrid{grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;padding:0}
.heat-tile{display:flex;flex-direction:column;min-height:104px;padding:14px 13px;border-radius:4px;box-shadow:none;transition:transform .18s,box-shadow .18s,opacity .18s}
.heat-tile:hover{transform:translateY(-1px)}
.heat-tile.active{outline:2px solid var(--accent);outline-offset:2px}
.ht-top{grid-template-columns:auto minmax(0,1fr) auto;gap:8px}.ht-name{font-size:.92rem}.ht-pct{font-size:.9rem}
.ht-status-row{margin-top:auto;padding-top:20px;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.signal-chip{display:inline-flex;align-items:center;min-height:22px;padding:2px 7px;border:1px solid var(--border);border-radius:999px;font-size:.62rem;font-weight:700;background:color-mix(in srgb,var(--panel) 72%,transparent)}
.signal-chip.temp.hot{color:var(--heat-hot)}.signal-chip.temp.cold{color:var(--heat-cold)}.signal-chip.muted{color:var(--ink-3)}
.filter-empty{padding:28px;text-align:center;color:var(--ink-3);font-family:var(--serif)}
.research-section{margin-top:18px;padding:0 16px 16px}
.research-grid{display:grid;grid-template-columns:2fr 1fr 1fr;gap:12px}
.research-column{min-width:0;border:1px solid var(--border);border-radius:5px;background:var(--panel-2);overflow:hidden}
.research-column-head{display:flex;align-items:baseline;justify-content:space-between;padding:12px;border-bottom:1px solid var(--border)}
.research-column-head h3{margin:0;font-size:.84rem;color:var(--ink)}.research-column-head span{font-size:.6rem;color:var(--ink-3)}
.research-column.research{border-top:2px solid var(--accent)}.research-column.watch{border-top:2px solid var(--heat-hot)}.research-column.avoid{border-top:2px solid var(--down)}
.research-row{display:grid;grid-template-columns:minmax(96px,1fr) auto auto;gap:7px;width:100%;padding:10px 11px;border:0;border-bottom:1px solid var(--border);background:transparent;color:var(--ink);text-align:left;cursor:pointer}
.research-row:last-child{border-bottom:0}.research-row:hover{background:var(--panel)}
.research-name{font-size:.76rem;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.research-pct,.research-metric{font-size:.68rem}.research-metric{color:var(--ink-3)}
.research-tags{grid-column:1/-1;display:flex;gap:5px;flex-wrap:wrap}.research-tag{padding:2px 6px;border-radius:999px;background:color-mix(in srgb,var(--accent) 12%,var(--panel));color:var(--accent);font-size:.58rem}.research-tag.conflict{background:var(--panel);color:var(--ink-3);border:1px solid var(--border)}
.research-empty{padding:18px 12px;color:var(--ink-3);font-size:.7rem}
.sector-drawer{position:fixed;z-index:80;inset:0 0 0 auto;width:min(1180px,80vw);padding:14px 20px 28px;background:var(--bg);border-left:1px solid var(--border);box-shadow:-18px 0 50px rgba(0,0,0,.38);overflow:auto;font-family:var(--sans);transform:translateX(102%);visibility:hidden;transition:transform .22s ease-out,visibility 0s linear .22s}
.sector-drawer.open{transform:translateX(0);visibility:visible;transition:transform .22s ease-out}
.drawer-top{position:sticky;top:-14px;z-index:3;display:flex;align-items:center;justify-content:space-between;padding:12px 0;background:color-mix(in srgb,var(--bg) 96%,transparent);backdrop-filter:blur(10px);border-bottom:1px solid var(--border)}
.drawer-close{min-height:38px;padding:0 12px;border:1px solid var(--border);border-radius:4px;background:var(--panel-2);color:var(--ink-2);cursor:pointer}
.sector-drawer .detail-panel{display:block;margin:0;padding:18px 0 0;border:0;border-radius:0;background:transparent}
.drawer-summary{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin:12px 0}
.drawer-summary span{display:flex;flex-direction:column;gap:3px;padding:9px 10px;background:var(--panel-2);border:1px solid var(--border);border-radius:4px}.drawer-summary b{font-size:.58rem;color:var(--ink-3);font-weight:500}.drawer-summary strong{font-size:.72rem;color:var(--ink);font-weight:700}
.sector-drawer .detail-three-col{grid-template-columns:1fr 1fr;}.sector-drawer .detail-three-col .tc-box:last-child{grid-column:1/-1}
.sector-drawer .stock-list-table{min-width:1120px}
.stock-card-backdrop{z-index:120}
.indicator-dialog{width:min(620px,calc(100vw - 32px));padding:0;border:1px solid var(--border);border-radius:6px;background:var(--panel);color:var(--ink);box-shadow:var(--shadow-2)}
.indicator-dialog::backdrop{background:rgba(0,0,0,.58)}
.dialog-head{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--border)}.dialog-head h2{margin:0;font-size:1rem}
.indicator-dialog dl{margin:0;padding:8px 16px 18px}.indicator-dialog dt{margin-top:12px;font-size:.76rem;font-weight:700;color:var(--accent)}.indicator-dialog dd{margin:4px 0 0;font-size:.74rem;line-height:1.65;color:var(--ink-2)}
@media (max-width:1180px){.heatgrid{grid-template-columns:repeat(4,minmax(0,1fr))}.research-grid{grid-template-columns:1fr 1fr}.research-column.research{grid-column:1/-1}.topbar{padding-inline:18px}.page-shell{padding-inline:18px}}
@media (max-width:820px){body.drawer-open{overflow:hidden}.topbar{position:static}.topbar .updated{margin-left:0;align-items:flex-start}.nav-links{width:100%;overflow-x:auto}.nav-link{min-height:44px}.page-shell{padding:12px}.heatgrid{grid-template-columns:repeat(2,minmax(0,1fr))}.research-grid{grid-template-columns:1fr}.research-column.research{grid-column:auto}.sector-drawer{width:100vw;padding-inline:12px}.sector-drawer .detail-three-col{grid-template-columns:1fr}.sector-drawer .detail-three-col .tc-box:last-child{grid-column:auto}.drawer-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.ranking-toolbar>*{flex:1 1 140px}.ranking-toolbar .icon-button{flex:0 0 44px}.toolbar-button,.icon-button,.segment,.drawer-close,.control-field input,.control-field select{min-height:44px}.stock-card-backdrop{padding:10px}.stock-card-modal{padding:18px 14px;max-height:94vh}.tv-chart{height:300px}}
@media (max-width:520px){.heatgrid{grid-template-columns:1fr}.research-row{grid-template-columns:minmax(90px,1fr) auto}.research-metric{grid-column:1}.topbar .search-wrap{order:4;width:100%;max-width:none}.market-regime{padding:14px}.regime-head{gap:6px}.advanced-filters>*{flex:1 1 100%}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;transition-duration:.01ms!important;animation-duration:.01ms!important;animation-iteration-count:1!important}}
"""

_TIER_COLOR_VAR = {
    "super": "var(--tier-super)", "strong": "var(--tier-strong)", "mid": "var(--tier-mid)",
    "weak": "var(--tier-weak)", "superweak": "var(--tier-superweak)",
}


def _pct_str(pct: float) -> str:
    return f"{pct:+.2f}%"


_TIER_HELP = {
    "super": "超強：連漲且近 5 日動能持續加速",
    "strong": "強：連漲且動能維持穩定",
    "mid": "整理：目前方向不明確",
    "weak": "弱：下跌且動能仍在減弱",
    "superweak": "超弱：連跌至少 5 日",
}


def _filter_attrs(card: Dict[str, Any], bucket: str = "") -> str:
    """供瀏覽器端排序／篩選使用；所有值只來自已正規化數字或固定 enum。"""
    tier_key = (card.get("tier") or {}).get("key", "")
    previous_rank = ""
    if card.get("rank_delta") is not None:
        previous_rank = card["rank"] + card["rank_delta"]
    values = {
        "pct": card.get("pct"),
        "cum5": card.get("cum5"),
        "rank_delta": card.get("rank_delta"),
        "vol_ratio": card.get("vol_ratio"),
        "foreign_streak": card.get("foreign_streak"),
        "trust_streak": card.get("trust_streak"),
    }
    numeric = " ".join(
        f'data-{key.replace("_", "-")}="{value if value is not None else ""}"'
        for key, value in values.items()
    )
    return (
        f'{numeric} data-tier="{tier_key}" data-bucket="{bucket}" '
        f'data-current-rank="{card.get("rank", "")}" data-prev-rank="{previous_rank}"'
    )


def _heatgrid_html(cards: List[Dict[str, Any]]) -> str:
    tiles = []
    for card in cards:
        tier = card.get("tier")
        temp = card.get("temp")
        rank_delta = card.get("rank_delta")
        rank_change = ""
        if rank_delta is not None and rank_delta != 0:
            direction = "up" if rank_delta > 0 else "down"
            arrow = "↑" if rank_delta > 0 else "↓"
            rank_change = f'<span class="ht-rank-delta {direction}">{arrow}{abs(rank_delta)}</span>'

        if tier:
            tier_color = _TIER_COLOR_VAR[tier["key"]]
            tier_html = (
                f'<span class="signal-chip tier" title="{_esc(_TIER_HELP[tier["key"]])}" '
                f'style="color:{tier_color};border-color:color-mix(in srgb,{tier_color} 50%,var(--border))">'
                f'{tier["label"]}</span>'
            )
            border_color = tier_color
        else:
            tier_html = '<span class="signal-chip tier muted">資料不足</span>'
            border_color = "transparent"

        temp_html = ""
        if temp:
            temp_html = f'<span class="signal-chip temp {temp["key"]}">{_esc(temp["label"])}</span>'

        safe_name = _esc(card["meta_name"])
        pct_color = "var(--up)" if card["pct"] >= 0 else "var(--down)"
        attrs = _filter_attrs(card, card.get("research_bucket", ""))
        tiles.append(
            f'<article class="heat-tile" data-meta-name="{safe_name}" {attrs} '
            f'role="button" tabindex="0" aria-label="開啟 {safe_name} 個股詳情" '
            f'onclick="selectGroup(this.dataset.metaName,true)" '
            f'onkeydown="if(event.key===\'Enter\'||event.key===\' \'){{event.preventDefault();selectGroup(this.dataset.metaName,true)}}" '
            f'style="background:{card["heat_bg"]};border-top-color:{border_color}">'
            f'<div class="ht-top"><span class="ht-rank tabular"><span class="rank-value">#{card["rank"]}</span> {rank_change}</span>'
            f'<span class="ht-name" title="{safe_name}">{safe_name}</span>'
            f'<span class="ht-pct tabular" style="color:{pct_color}">{_pct_str(card["pct"])}</span></div>'
            f'<div class="ht-status-row">{tier_html}{temp_html}</div>'
            f'</article>'
        )
    return "".join(tiles)


def _research_buckets_html(buckets: Dict[str, List[Dict[str, Any]]]) -> str:
    def _row(card: Dict[str, Any]) -> str:
        safe_name = _esc(card["meta_name"])
        pct_color = "var(--up)" if card["pct"] >= 0 else "var(--down)"
        if card["bucket"] == "research" and card.get("rank_delta") is not None:
            metric = f'排名 ↑{card["rank_delta"]}'
        elif card.get("accel") is not None:
            metric = f'{card["accel"]:+.1f}pt'
        elif card.get("vol_ratio") is not None:
            metric = f'{card["vol_ratio"]:.2f}x'
        else:
            metric = "—"
        tags = [card["primary_tag"], *card.get("conflict_tags", [])]
        tags_html = "".join(
            f'<span class="research-tag{" conflict" if i else ""}">{_esc(tag)}</span>'
            for i, tag in enumerate(tags) if tag
        )
        return (
            f'<button type="button" class="research-row" data-meta-name="{safe_name}" '
            f'{_filter_attrs(card, card["bucket"])} onclick="selectGroup(this.dataset.metaName)">'
            f'<span class="research-name">{safe_name}</span>'
            f'<span class="research-pct tabular" style="color:{pct_color}">{_pct_str(card["pct"])}</span>'
            f'<span class="research-metric tabular">{metric}</span>'
            f'<span class="research-tags">{tags_html}</span></button>'
        )

    def _column(key: str, title: str, hint: str) -> str:
        rows = "".join(_row(card) for card in buckets[key])
        if not rows:
            rows = '<div class="research-empty">目前沒有符合條件的族群</div>'
        return (
            f'<section class="research-column {key}" data-bucket-group="{key}">'
            f'<div class="research-column-head"><h3>{title}</h3><span>{hint}</span></div>{rows}</section>'
        )

    return f"""
<section class="research-section" aria-labelledby="sector-recap-title">
  <div class="section-head compact"><div><span class="eyebrow">RESEARCH QUEUE</span><h2 id="sector-recap-title">今日研究順序</h2></div><span class="count">互斥分類</span></div>
  <div class="research-grid">
    {_column("research", "值得研究", "最多 10 個")}
    {_column("watch", "先觀察", "最多 5 個")}
    {_column("avoid", "避開", "最多 5 個")}
  </div>
</section>"""


def generate(
    trade_date: date,
    meta_perf: List[Dict[str, Any]],
    universe_df: pd.DataFrame,
    meta_signals: Dict[str, Dict[str, Any]],
    meta_chips: Dict[str, Dict[str, Any]],
    prices_df: pd.DataFrame,
    heatgrid_windows: Dict[str, Dict[str, Any]],
    stock_sparklines: Optional[Dict[str, dict]] = None,
    rolling_returns: Optional[Dict[str, dict]] = None,
    chips_df: Optional[pd.DataFrame] = None,
    cum_data: Optional[List[Dict[str, Any]]] = None,
    market_regime: Optional[Dict[str, Any]] = None,
    vol_turnover_signals: Optional[List[Dict[str, Any]]] = None,
    rank_history: Optional[Dict[str, Dict[str, Any]]] = None,
    total_shares_df: Optional[pd.DataFrame] = None,
    avg20_map: Optional[Dict[str, float]] = None,
    shareholder_df: Optional[pd.DataFrame] = None,
    data_mode: str = "close",
    generated_at: Optional[datetime] = None,
    update_error: Optional[str] = None,
    output_path: str = "docs/index.html",
) -> None:
    """
    產生 docs/index.html（族群總覽頁熱區格版面）。meta_perf 為空時不寫檔（比照舊
    export/html_generator.py::generate() 既有慣例）。

    以下都是「有就顯示、沒有就不顯示」的補充資料，全部None-safe，任何一個沒傳都不影響
    其餘部分正常產生（比照舊版 html_generator.py 各區塊的 fail-soft 慣例）：
    - stock_sparklines：calc_stock_sparklines() 輸出，個股卡片sparkline走勢圖。
    - rolling_returns：get_rolling_returns((5,7,10,14)) 輸出，個股卡片近5/7/10/14日。
    - chips_df：get_chips_today() 輸出，個股卡片外資/投信/融資摘要。
    - cum_data：calc_cumulative_meta() 輸出(list)，熱區格3/5/7日累積漲跌badge。
    - market_regime：main.py 算好的大盤分級dict，大盤現況儀表板。
    - vol_turnover_signals：scan_volume_turnover() 輸出(list)，巨量換手訊號區塊。
    - rank_history：calc_meta_rank_history() 輸出，族群近況「排名進出榜」跟單一族群
      「歷史出現紀錄」用。
    - total_shares_df：get_latest_total_shares() 輸出，個股融資/融券佔比的分母
      (已發行股數)+集保資料實際日期。
    - avg20_map：calc_avg20_close() 輸出，個股融資/融券維持率(估)的成本基準。
    - shareholder_df：get_shareholder_top() 輸出，個股表格「大戶佔比」「大戶週變化」兩欄。
    - data_mode：close／intraday，決定收盤快照或盤中暫定資料標示。
    - generated_at：頁面實際產生時間；未傳時使用本機現在時間。
    - update_error：上游保留最後成功資料時，可傳入錯誤摘要顯示 stale 狀態。
    """
    if not meta_perf:
        return

    date_str = trade_date.strftime("%Y-%m-%d")
    weekday = ["一", "二", "三", "四", "五", "六", "日"][trade_date.weekday()]
    is_intraday = data_mode == "intraday"
    generated_at = generated_at or datetime.now()
    updated_time = generated_at.strftime("%H:%M")
    mode_label = "盤中資料，尚未收盤確認" if is_intraday else "收盤快照"

    cards = build_heatgrid_cards(meta_perf, meta_signals, meta_chips, heatgrid_windows, cum_data)
    anomaly_cards = find_anomaly_cards(meta_perf, meta_signals, heatgrid_windows)
    research_buckets = build_research_buckets(cards, anomaly_cards, rank_history)
    bucket_by_name = {
        card["meta_name"]: bucket
        for bucket, rows in research_buckets.items()
        for card in rows
    }
    for card in cards:
        card["research_bucket"] = bucket_by_name.get(card["meta_name"], "")
    stock_detail = build_stock_detail_data(
        universe_df, prices_df, stock_sparklines, rolling_returns, chips_df,
        total_shares_df, avg20_map, shareholder_df,
    )

    stock_detail_js = json.dumps(stock_detail, ensure_ascii=False).replace("</", "<\\/")
    card_meta = {}
    for c in cards:
        meta_name = c["meta_name"]
        sig = meta_signals.get(meta_name, {})
        chips = meta_chips.get(meta_name, {})
        rank_row = (rank_history or {}).get(meta_name, {})
        card_meta[meta_name] = {
            "pct": c["pct"], "up_count": c["up_count"], "down_count": c["down_count"],
            "rank": c["rank"], "rank_delta": c["rank_delta"],
            "tier": c["tier"], "temp": c["temp"], "streak": c["streak"],
            "vol_ratio": c["vol_ratio"], "cum3": c["cum3"], "cum5": c["cum5"],
            "cum7": c["cum7"], "accel": c["accel"],
            "last_week_pct": c["last_week_pct"], "this_week_pct": c["this_week_pct"],
            "research_bucket": c["research_bucket"],
            "daily_pct": sig.get("daily_pct", []), "dates": sig.get("dates", []),
            "foreign_net_today": chips.get("foreign_net_today", 0),
            "trust_net_today": chips.get("trust_net_today", 0),
            "dealer_net_today": chips.get("dealer_net_today", 0),
            "foreign_net_week": chips.get("foreign_net_week", 0),
            "trust_net_week": chips.get("trust_net_week", 0),
            "foreign_buy_count": chips.get("foreign_buy_count", 0),
            "total_stocks": chips.get("total_stocks", 0),
            "foreign_streak": chips.get("foreign_streak", 0),
            "trust_streak": chips.get("trust_streak", 0),
            "margin_change_today": chips.get("margin_change_today", 0),
            "margin_balance_today": chips.get("margin_balance_today", 0),
            "margin_alert": bool(chips.get("margin_alert", False)),
            "weekly_ranks": rank_row.get("weekly_ranks", []),
            "weekly_returns": rank_row.get("weekly_returns", []),
            "in_top10_this_week": rank_row.get("in_top10_this_week", False),
            "consecutive_weeks_in_top10": rank_row.get("consecutive_weeks_in_top10", 0),
            "last_top10_week_index": rank_row.get("last_top10_week_index"),
            "last_top10_rank": rank_row.get("last_top10_rank"),
        }
    card_meta_js = json.dumps(card_meta, ensure_ascii=False).replace("</", "<\\/")

    stock_index = [
        {"id": s["stock_id"], "name": s["stock_name"], "meta": meta_name, "pct": s["change_pct"] or 0.0}
        for meta_name, stocks in stock_detail.items() for s in stocks if not s["no_data"]
    ]
    meta_index = [{"name": c["meta_name"], "pct": c["pct"]} for c in cards]
    stock_index_js = json.dumps(stock_index, ensure_ascii=False).replace("</", "<\\/")
    meta_index_js = json.dumps(meta_index, ensure_ascii=False).replace("</", "<\\/")

    ranking_mode_html = ""
    if is_intraday:
        ranking_mode_html = """
        <div class="segmented" role="group" aria-label="排行資料模式">
          <button type="button" class="segment active" data-rank-mode="live" onclick="setRankMode('live')">即時排行</button>
          <button type="button" class="segment" data-rank-mode="close" onclick="setRankMode('close')">上次收盤排行</button>
        </div>"""

    update_error_html = ""
    if update_error:
        update_error_html = (
            f'<div class="data-error" role="alert">更新失敗；目前保留 {date_str} {updated_time} 的最後成功資料。'
            f'<span>{_esc(update_error)}</span></div>'
        )

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
  <div class="brand"><div class="kicker">TW SECTOR TRACKER</div><h1>族群總覽</h1></div>
  <div class="search-wrap">
    <input id="stock-search" class="stock-search" placeholder="搜尋股票代號 / 名稱 / 族群…"
      aria-label="搜尋股票代號、名稱或族群" oninput="searchStocks(this.value)" onblur="setTimeout(hideSearch,200)" autocomplete="off">
    <div id="search-dropdown" class="search-dropdown" hidden></div>
  </div>
  <div class="updated"><strong>{mode_label}</strong><span>{date_str}（週{weekday}）{updated_time}</span></div>
  <nav class="nav-links" aria-label="主要功能">
    <a class="nav-link active" href="index.html" aria-current="page">族群績效</a>
    <a class="nav-link" href="chips.html">籌碼分析</a>
    <a class="nav-link" href="patterns.html">形態掃描</a>
    <a class="nav-link" href="momentum.html">逆轟策略</a>
  </nav>
</header>
<main id="main-content">
{update_error_html}
<div class="page-shell">
  <section class="market-section" aria-label="市場現況">
    {_market_regime_html(market_regime)}
  </section>

  <section class="ranking-section" aria-labelledby="sector-rank-title">
    <div class="section-head ranking-head">
      <div><span class="eyebrow">SECTOR RANKING</span><h2 id="sector-rank-title">族群 Top 10</h2></div>
      <span class="count"><span id="showingCount">10</span> / {len(cards)} 個族群</span>
    </div>
    <div class="ranking-toolbar" aria-label="族群排行控制">
      {ranking_mode_html}
      <label class="control-field compact"><span>研究分類</span>
        <select id="bucketFilter" onchange="applySectorView()">
          <option value="">全部分類</option><option value="research">值得研究</option>
          <option value="watch">先觀察</option><option value="avoid">避開</option>
        </select>
      </label>
      <label class="control-field grow"><span>族群名稱</span>
        <input id="sectorFilter" type="search" placeholder="輸入族群名稱" oninput="applySectorView()">
      </label>
      <label class="control-field compact"><span>排序</span>
        <select id="sectorSort" onchange="applySectorView()">
          <option value="pct">今日漲跌</option><option value="cum5">近 5 日報酬</option>
          <option value="rankDelta">排名變化</option><option value="volRatio">量比</option>
        </select>
      </label>
      <button type="button" class="toolbar-button" id="showAllToggle" aria-expanded="false" onclick="toggleShowAll()">顯示全部</button>
      <button type="button" class="toolbar-button" id="advancedToggle" aria-expanded="false" aria-controls="advancedFilters" onclick="toggleAdvanced()">進階篩選</button>
      <button type="button" class="icon-button" aria-label="開啟指標說明" title="指標說明" onclick="openIndicatorHelp()">?</button>
      <button type="button" class="toolbar-button quiet" onclick="resetSectorView()">重設</button>
    </div>
    <div class="advanced-filters" id="advancedFilters" hidden>
      <label class="control-field"><span>動能等級</span>
        <select id="tierFilter"><option value="">全部</option><option value="super">超強</option><option value="strong">強</option><option value="mid">整理</option><option value="weak">弱</option><option value="superweak">超弱</option></select>
      </label>
      <label class="control-field"><span>最低量比</span><input id="minVolFilter" type="number" min="0" step="0.1" value="1.5"></label>
      <label class="control-field"><span>排名最低跳升</span><input id="minRankFilter" type="number" min="0" step="1" value="10"></label>
      <label class="check-field"><input id="foreignFilter" type="checkbox"> 外資連買</label>
      <label class="check-field"><input id="trustFilter" type="checkbox"> 投信連買</label>
      <button type="button" class="toolbar-button primary" onclick="activateAdvancedFilters()">套用條件</button>
      <button type="button" class="toolbar-button quiet" onclick="clearAdvancedFilters()">停用進階條件</button>
    </div>
    <div class="heatgrid" id="heatgrid">{_heatgrid_html(cards)}</div>
    <div class="filter-empty" id="filterEmpty" hidden>目前沒有符合篩選條件的族群</div>
  </section>

  {_research_buckets_html(research_buckets)}
  {_vol_turnover_html(vol_turnover_signals, is_intraday=is_intraday)}
</div>
</main>

<aside class="sector-drawer" id="sectorDrawer" aria-hidden="true" aria-labelledby="drawerTitle">
  <div class="drawer-top"><span class="eyebrow">SECTOR DETAIL</span><button type="button" class="drawer-close" id="drawerClose" onclick="closeSectorDrawer()" aria-label="關閉族群詳情">關閉</button></div>
  <div id="drawerContent"></div>
</aside>

<dialog class="indicator-dialog" id="indicatorDialog" aria-labelledby="indicatorTitle">
  <div class="dialog-head"><h2 id="indicatorTitle">指標說明</h2><button type="button" class="drawer-close" onclick="closeIndicatorHelp()">關閉</button></div>
  <dl>
    <dt>動能等級</dt><dd>由連漲／連跌天數，以及近 5 日相對前 5 日的加速度分類；目前門檻尚未回測。</dd>
    <dt>增溫／退燒</dt><dd>近 5 日報酬相對前 5 日增加或減少至少 5 個百分點。</dd>
    <dt>即時異動</dt><dd>預設量比至少 1.5x、排名跳升至少 10 名；「動能加速」則表示連續走強。</dd>
    <dt>研究分類</dt><dd>值得研究、先觀察、避開是研究優先順序，不是買賣建議；同一族群只進入一個主要分類。</dd>
  </dl>
</dialog>
<script>
const STOCKS = {stock_detail_js};
const CARD_META = {card_meta_js};
const STOCK_INDEX = {stock_index_js};
const META_INDEX = {meta_index_js};
const DATA_MODE = '{"intraday" if is_intraday else "close"}';
const SECTOR_VIEW_KEY = 'tw-sector-index-view-v1';
const DEFAULT_SECTOR_VIEW = {{
  showAll:false, bucket:'', name:'', sort:'pct', rankMode:'live', advancedActive:false,
  tier:'', minVol:1.5, minRank:10, foreign:false, trust:false
}};
let sectorView = {{...DEFAULT_SECTOR_VIEW}};
let _drawerReturnFocus = null;

function loadSectorView() {{
  try {{
    const saved = JSON.parse(localStorage.getItem(SECTOR_VIEW_KEY) || 'null');
    if (saved && typeof saved === 'object') sectorView = {{...DEFAULT_SECTOR_VIEW, ...saved}};
  }} catch (_) {{ sectorView = {{...DEFAULT_SECTOR_VIEW}}; }}
}}

function saveSectorView() {{
  try {{ localStorage.setItem(SECTOR_VIEW_KEY, JSON.stringify(sectorView)); }} catch (_) {{}}
}}

function _numAttr(el, key) {{
  const raw = el.dataset[key];
  if (raw === undefined || raw === '') return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}}

function _matchesSectorFilters(el) {{
  const name = (el.dataset.metaName || '').toLocaleLowerCase('zh-Hant');
  if (sectorView.name && !name.includes(sectorView.name.toLocaleLowerCase('zh-Hant'))) return false;
  if (sectorView.bucket && el.dataset.bucket !== sectorView.bucket) return false;
  if (!sectorView.advancedActive) return true;
  if (sectorView.tier && el.dataset.tier !== sectorView.tier) return false;
  const vol = _numAttr(el, 'volRatio');
  const rankDelta = _numAttr(el, 'rankDelta');
  if (sectorView.minVol > 0 && (vol === null || vol < sectorView.minVol)) return false;
  if (sectorView.minRank > 0 && (rankDelta === null || rankDelta < sectorView.minRank)) return false;
  if (sectorView.foreign && (_numAttr(el, 'foreignStreak') || 0) < 1) return false;
  if (sectorView.trust && (_numAttr(el, 'trustStreak') || 0) < 1) return false;
  return true;
}}

function _sortSectorTiles(a, b) {{
  if (sectorView.rankMode === 'close') {{
    const av = _numAttr(a, 'prevRank'), bv = _numAttr(b, 'prevRank');
    if (av === null) return 1;
    if (bv === null) return -1;
    return av - bv;
  }}
  const key = {{pct:'pct', cum5:'cum5', rankDelta:'rankDelta', volRatio:'volRatio'}}[sectorView.sort] || 'pct';
  const av = _numAttr(a, key), bv = _numAttr(b, key);
  if (av === null) return 1;
  if (bv === null) return -1;
  return bv - av;
}}

function applySectorView() {{
  sectorView.bucket = document.getElementById('bucketFilter').value;
  sectorView.name = document.getElementById('sectorFilter').value.trim();
  sectorView.sort = document.getElementById('sectorSort').value;
  const grid = document.getElementById('heatgrid');
  const tiles = [...grid.querySelectorAll('.heat-tile')].sort(_sortSectorTiles);
  tiles.forEach(tile => grid.appendChild(tile));
  tiles.forEach(tile => {{
    const rankValue = tile.querySelector('.rank-value');
    const rankDelta = tile.querySelector('.ht-rank-delta');
    const previousRank = _numAttr(tile, 'prevRank');
    const currentRank = _numAttr(tile, 'currentRank');
    const showingClose = sectorView.rankMode === 'close' && previousRank !== null;
    rankValue.textContent = `#${{showingClose ? previousRank : currentRank}}`;
    if (rankDelta) rankDelta.hidden = sectorView.rankMode === 'close';
  }});
  const matching = tiles.filter(_matchesSectorFilters);
  const visibleLimit = sectorView.showAll ? matching.length : 10;
  tiles.forEach(tile => {{ tile.hidden = !matching.includes(tile) || matching.indexOf(tile) >= visibleLimit; }});

  document.querySelectorAll('.research-row').forEach(row => {{ row.hidden = !_matchesSectorFilters(row); }});
  document.querySelectorAll('[data-bucket-group]').forEach(column => {{
    const wrongBucket = sectorView.bucket && column.dataset.bucketGroup !== sectorView.bucket;
    column.hidden = Boolean(wrongBucket);
  }});

  const shown = Math.min(matching.length, visibleLimit);
  document.getElementById('showingCount').textContent = String(shown);
  document.getElementById('filterEmpty').hidden = shown !== 0;
  document.getElementById('sector-rank-title').textContent = sectorView.showAll ? '全部族群' : '族群 Top 10';
  const showAllButton = document.getElementById('showAllToggle');
  showAllButton.textContent = sectorView.showAll ? '只看 Top 10' : '顯示全部';
  showAllButton.setAttribute('aria-expanded', String(sectorView.showAll));
  document.getElementById('advancedToggle').classList.toggle('active', sectorView.advancedActive);
  saveSectorView();
}}

function syncSectorControls() {{
  document.getElementById('bucketFilter').value = sectorView.bucket;
  document.getElementById('sectorFilter').value = sectorView.name;
  document.getElementById('sectorSort').value = sectorView.sort;
  document.getElementById('tierFilter').value = sectorView.tier;
  document.getElementById('minVolFilter').value = sectorView.minVol;
  document.getElementById('minRankFilter').value = sectorView.minRank;
  document.getElementById('foreignFilter').checked = sectorView.foreign;
  document.getElementById('trustFilter').checked = sectorView.trust;
  document.querySelectorAll('[data-rank-mode]').forEach(button => button.classList.toggle('active', button.dataset.rankMode === sectorView.rankMode));
}}

function toggleShowAll() {{ sectorView.showAll = !sectorView.showAll; applySectorView(); }}
function toggleAdvanced() {{
  const panel = document.getElementById('advancedFilters');
  panel.hidden = !panel.hidden;
  document.getElementById('advancedToggle').setAttribute('aria-expanded', String(!panel.hidden));
}}
function activateAdvancedFilters() {{
  sectorView.advancedActive = true;
  sectorView.tier = document.getElementById('tierFilter').value;
  sectorView.minVol = Number(document.getElementById('minVolFilter').value) || 0;
  sectorView.minRank = Number(document.getElementById('minRankFilter').value) || 0;
  sectorView.foreign = document.getElementById('foreignFilter').checked;
  sectorView.trust = document.getElementById('trustFilter').checked;
  applySectorView();
}}
function clearAdvancedFilters() {{
  sectorView.advancedActive = false;
  sectorView.tier = '';
  sectorView.minVol = 1.5;
  sectorView.minRank = 10;
  sectorView.foreign = false;
  sectorView.trust = false;
  syncSectorControls();
  applySectorView();
}}
function resetSectorView() {{
  sectorView = {{...DEFAULT_SECTOR_VIEW}};
  syncSectorControls();
  applySectorView();
}}
function setRankMode(mode) {{
  sectorView.rankMode = mode === 'close' ? 'close' : 'live';
  syncSectorControls();
  applySectorView();
}}
function openIndicatorHelp() {{ document.getElementById('indicatorDialog').showModal(); }}
function closeIndicatorHelp() {{ document.getElementById('indicatorDialog').close(); }}

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

// pcts/dates/volumes 是 calc_stock_sparklines() 算出的數值/日期字串（"%m/%d"），不是使用者
// 輸入，不用經過 escHtml 也不會有 XSS 風險——跟這個檔案其他數值型欄位（pct/rank等）的處理
// 一致。volumes 是選填的第4個參數，只有個股卡片會傳（族群層級的sparkline沒有量能資料，
// 呼叫端不傳這個參數，函式自動退回原本只畫價格的版本，不影響既有呼叫）。
function buildSparkline(pcts, dates, cls, volumes) {{
  if (!pcts || !pcts.length) return '';
  cls = cls || 'sc-sparkline';
  const n = pcts.length, priceH = 26, gap = 2;
  const hasVol = volumes && volumes.length === n;
  const volH = hasVol ? 16 : 0, volGap = hasVol ? 4 : 0;
  const barW = Math.max(4, Math.floor(140 / n) - gap);
  const totalW = n * (barW + gap) - gap;
  const totalH = priceH + volGap + volH;
  const mid = priceH / 2;
  const maxAbs = Math.max(...pcts.map(p => Math.abs(p))) || 1;
  const maxVol = hasVol ? (Math.max(...volumes) || 1) : 1;
  let priceBars = '', volBars = '';
  for (let i = 0; i < n; i++) {{
    const pct = pcts[i];
    const d = (dates && dates[i]) || '';
    const barH = Math.max(1.5, Math.abs(pct) / maxAbs * (mid - 2));
    const y = pct >= 0 ? mid - barH : mid;
    const color = pct > 0 ? 'var(--up)' : (pct < 0 ? 'var(--down)' : 'var(--ink-3)');
    const x = i * (barW + gap);
    const sign = pct >= 0 ? '+' : '';
    priceBars += `<rect x="${{x}}" y="${{y}}" width="${{barW}}" height="${{barH}}" fill="${{color}}" rx="1"><title>${{d}} ${{sign}}${{pct.toFixed(2)}}%</title></rect>`;
    if (hasVol) {{
      const vol = volumes[i] || 0;
      const vBarH = Math.max(1, vol / maxVol * (volH - 1));
      const vY = priceH + volGap + (volH - vBarH);
      volBars += `<rect x="${{x}}" y="${{vY}}" width="${{barW}}" height="${{vBarH}}" fill="${{color}}" opacity="0.5" rx="1"><title>${{d}} 量 ${{vol.toLocaleString()}}張</title></rect>`;
    }}
  }}
  return `<div class="${{cls}}"><svg viewBox="0 0 ${{totalW}} ${{totalH}}" xmlns="http://www.w3.org/2000/svg">`
    + `<line x1="0" y1="${{mid}}" x2="${{totalW}}" y2="${{mid}}" stroke="var(--border)" stroke-width="1"/>${{priceBars}}${{volBars}}</svg></div>`;
}}

// 個股圖表只在第一次開啟個股詳情時載入；價格與成交量仍完全使用本專案資料。
// 固定版本避免 CDN 的 breaking change 讓已產生的靜態頁突然失效。
const LIGHTWEIGHT_CHARTS_SRC = 'https://cdn.jsdelivr.net/npm/lightweight-charts@5.2.0/dist/lightweight-charts.standalone.production.js';
let _lightweightChartsPromise = null;
let _stockChart = null;
let _stockChartResizeObserver = null;

function ensureLightweightCharts() {{
  if (window.LightweightCharts) return Promise.resolve(window.LightweightCharts);
  if (_lightweightChartsPromise) return _lightweightChartsPromise;
  _lightweightChartsPromise = new Promise((resolve, reject) => {{
    const script = document.createElement('script');
    script.src = LIGHTWEIGHT_CHARTS_SRC;
    script.async = true;
    script.dataset.lightweightCharts = '5.2.0';
    script.onload = () => window.LightweightCharts
      ? resolve(window.LightweightCharts)
      : reject(new Error('Lightweight Charts loaded without global API'));
    script.onerror = () => {{
      _lightweightChartsPromise = null;
      script.remove();
      reject(new Error('Lightweight Charts download failed'));
    }};
    document.head.appendChild(script);
  }});
  return _lightweightChartsPromise;
}}

function destroyStockChart() {{
  if (_stockChartResizeObserver) {{
    _stockChartResizeObserver.disconnect();
    _stockChartResizeObserver = null;
  }}
  if (_stockChart) {{
    _stockChart.remove();
    _stockChart = null;
  }}
}}

async function mountStockChart(s) {{
  const container = document.getElementById('stockTvChart');
  const status = document.getElementById('stockTvChartStatus');
  if (!container || !status) return;

  const times = s.iso_dates || [];
  const points = times.map((time, index) => ({{
    time,
    index,
    open: Number(s.opens[index]),
    high: Number(s.highs[index]),
    low: Number(s.lows[index]),
    close: Number(s.closes[index]),
  }})).filter(point => point.time && Number.isFinite(point.open) && Number.isFinite(point.high)
    && Number.isFinite(point.low) && Number.isFinite(point.close));

  if (points.length < 2) {{
    status.textContent = '走勢資料不足';
    return;
  }}

  try {{
    const LightweightCharts = await ensureLightweightCharts();
    if (!container.isConnected) return;
    const styles = getComputedStyle(document.documentElement);
    const color = name => styles.getPropertyValue(name).trim();
    const chart = LightweightCharts.createChart(container, {{
      width: container.clientWidth,
      height: container.clientHeight,
      layout: {{
        background: {{type: LightweightCharts.ColorType.Solid, color: color('--panel-2')}},
        textColor: color('--ink-2'),
        fontFamily: 'ui-monospace, "IBM Plex Mono", "Cascadia Code", monospace',
        attributionLogo: true,
      }},
      grid: {{
        vertLines: {{color: color('--border')}},
        horzLines: {{color: color('--border')}},
      }},
      rightPriceScale: {{borderColor: color('--border-2')}},
      timeScale: {{borderColor: color('--border-2'), timeVisible: false}},
      crosshair: {{mode: LightweightCharts.CrosshairMode.Normal}},
    }});
    const candles = chart.addSeries(LightweightCharts.CandlestickSeries, {{
      upColor: color('--up'), downColor: color('--down'), borderVisible: false,
      wickUpColor: color('--up'), wickDownColor: color('--down'),
    }});
    candles.setData(points.map(point => ({{
      time: point.time, open: point.open, high: point.high, low: point.low, close: point.close,
    }})));
    candles.priceScale().applyOptions({{scaleMargins: {{top: 0.08, bottom: 0.28}}}});

    const volumes = chart.addSeries(LightweightCharts.HistogramSeries, {{
      priceFormat: {{type: 'volume'}}, priceScaleId: '',
    }});
    volumes.priceScale().applyOptions({{scaleMargins: {{top: 0.78, bottom: 0}}}});
    volumes.setData(points.map(point => ({{
      time: point.time,
      value: Number.isFinite(Number(s.volumes[point.index])) ? Number(s.volumes[point.index]) : 0,
      color: point.close >= point.open ? 'rgba(230,67,47,.45)' : 'rgba(55,178,92,.45)',
    }})));
    chart.timeScale().fitContent();
    _stockChart = chart;
    if ('ResizeObserver' in window) {{
      _stockChartResizeObserver = new ResizeObserver(entries => {{
        const width = Math.floor(entries[0].contentRect.width);
        if (width > 0) chart.applyOptions({{width}});
      }});
      _stockChartResizeObserver.observe(container);
    }}
    status.hidden = true;
  }} catch (error) {{
    if (!container.isConnected) return;
    status.hidden = false;
    status.setAttribute('role', 'alert');
    status.textContent = 'K 線載入失敗，請重新開啟個股詳情。';
    console.error(error);
  }}
}}

// meta是CARD_META[name]，所有欄位都是Python端算好的數值/bool，不是使用者輸入，不用escHtml。
function buildChipsSummary(meta) {{
  const rows = [];
  if (meta.foreign_net_today) {{
    const fn = meta.foreign_net_today, k = Math.trunc(fn / 1000);
    const color = fn > 0 ? 'var(--up)' : 'var(--down)';
    const sign = fn > 0 ? '+' : '';
    let sub = '';
    if (fn > 0 && meta.total_stocks > 0) sub = `<span class="cs-sub">買超${{meta.foreign_buy_count}}/${{meta.total_stocks}}股</span>`;
    else if (fn < 0 && meta.total_stocks > 0) sub = `<span class="cs-sub">賣超${{meta.total_stocks - meta.foreign_buy_count}}/${{meta.total_stocks}}股</span>`;
    let streak = '';
    if (Math.abs(meta.foreign_streak) >= 2) {{
      const cls = meta.foreign_streak > 0 ? 'cs-streak-up' : 'cs-streak-dn';
      const word = meta.foreign_streak > 0 ? `連買${{meta.foreign_streak}}日` : `連賣${{Math.abs(meta.foreign_streak)}}日`;
      streak = `<span class="${{cls}}">${{word}}</span>`;
    }}
    rows.push(`<div class="cs-row"><span class="cs-label">外資</span><span style="color:${{color}};font-weight:700">${{sign}}${{k.toLocaleString()}}張</span>${{sub}}${{streak}}</div>`);
  }}
  if (meta.trust_net_today) {{
    const tn = meta.trust_net_today, k = Math.trunc(tn / 1000);
    const color = tn > 0 ? 'var(--up)' : 'var(--down)';
    const sign = tn > 0 ? '+' : '';
    let streak = '';
    if (Math.abs(meta.trust_streak) >= 2) {{
      const cls = meta.trust_streak > 0 ? 'cs-streak-up' : 'cs-streak-dn';
      const word = meta.trust_streak > 0 ? `連買${{meta.trust_streak}}日` : `連賣${{Math.abs(meta.trust_streak)}}日`;
      streak = `<span class="${{cls}}">${{word}}</span>`;
    }}
    rows.push(`<div class="cs-row"><span class="cs-label">投信</span><span style="color:${{color}};font-weight:700">${{sign}}${{k.toLocaleString()}}張</span>${{streak}}</div>`);
  }}
  if (meta.dealer_net_today) {{
    const dn = meta.dealer_net_today, k = Math.trunc(dn / 1000);
    const color = dn > 0 ? 'var(--up)' : 'var(--down)';
    const sign = dn > 0 ? '+' : '';
    rows.push(`<div class="cs-row"><span class="cs-label">自營商</span><span style="color:${{color}};font-weight:700">${{sign}}${{k.toLocaleString()}}張</span></div>`);
  }}
  if (meta.margin_change_today && meta.margin_balance_today > 0) {{
    const pct = meta.margin_change_today / meta.margin_balance_today * 100;
    const arrow = meta.margin_change_today > 0 ? '↑' : '↓';
    const color = meta.margin_change_today > 0 ? 'var(--accent)' : 'var(--ink-3)';
    const alert = meta.margin_alert ? '<span class="cs-alert">融資擴張</span>' : '';
    rows.push(`<div class="cs-row"><span class="cs-label">融資</span><span style="color:${{color}};font-weight:700">${{arrow}}${{Math.abs(pct).toFixed(1)}}%</span>${{alert}}</div>`);
  }}
  if (meta.foreign_net_week || meta.trust_net_week) {{
    const fw = meta.foreign_net_week || 0, tw = meta.trust_net_week || 0;
    const fwK = Math.trunc(fw / 1000), twK = Math.trunc(tw / 1000);
    const fColor = fw >= 0 ? 'var(--up)' : 'var(--down)';
    const tColor = tw >= 0 ? 'var(--up)' : 'var(--down)';
    rows.push(
      `<div class="cs-row cs-week"><span class="cs-label">本週累計</span>`
      + `<span>外資 <span style="color:${{fColor}};font-weight:700">${{fw>=0?'+':''}}${{fwK.toLocaleString()}}張</span></span>`
      + `<span>投信 <span style="color:${{tColor}};font-weight:700">${{tw>=0?'+':''}}${{twK.toLocaleString()}}張</span></span></div>`
    );
  }}
  return rows.length ? `<div class="chips-summary">${{rows.join('')}}</div>` : '';
}}

// 單一族群「歷史出現紀錄」：近幾週精確排名軌跡+文字摘要。meta是CARD_META[name]，
// weekly_ranks/in_top10_this_week/consecutive_weeks_in_top10/last_top10_week_index/
// last_top10_rank都是Python端calc_meta_rank_history()算好的數值，不是使用者輸入，不用escHtml。
function buildHistoryRecord(meta) {{
  const ranks = meta.weekly_ranks || [];
  if (!ranks.length) return '';
  const returns = meta.weekly_returns || [];

  let summary;
  if (meta.in_top10_this_week) {{
    summary = `連續 <b>${{meta.consecutive_weeks_in_top10}}</b> 週進榜（前10名）`;
  }} else if (meta.last_top10_week_index !== null && meta.last_top10_week_index !== undefined) {{
    const weeksAgo = ranks.length - 1 - meta.last_top10_week_index;
    summary = `上次進榜是 <b>W-${{weeksAgo}}</b>，當時排第 <b>#${{meta.last_top10_rank}}</b> 名`;
  }} else {{
    summary = `近${{ranks.length}}週都沒有進前10`;
  }}

  const weekCells = ranks.map((rank, i) => {{
    const isCurrent = i === ranks.length - 1;
    const label = isCurrent ? '本週' : `W-${{ranks.length - 1 - i}}`;
    const inTop10 = rank <= 10;
    const cls = 'history-week' + (inTop10 ? ' in-top10' : '');
    const ret = returns[i];
    const retHtml = (ret !== null && ret !== undefined)
      ? `<span class="hw-pct tabular" style="color:${{ret >= 0 ? 'var(--up)' : 'var(--down)'}}">${{ret>=0?'+':''}}${{ret.toFixed(1)}}%</span>`
      : '';
    return `<div class="${{cls}}"><span class="hw-label">${{label}}</span><span class="hw-rank tabular">#${{rank}}</span>${{retHtml}}</div>`;
  }}).join('');

  return `<div class="history-wrap">
    <div class="history-summary">${{summary}}</div>
    <div class="history-weekline-label">近${{ranks.length}}週排行軌跡</div>
    <div class="history-weekline">${{weekCells}}</div>
  </div>`;
}}

// 收盤價格式：>=100且整數才用千分位逗號分隔，其餘2位小數——比照舊版
// html_generator.py::_fmt_price() 的規則，避免小型股價位（例如12.35）被誤格式化。
function fmtPrice(v) {{
  if (v >= 100 && Number.isInteger(v)) return v.toLocaleString();
  return v.toFixed(2);
}}

// 個股列表(.stock-item)只顯示基本資訊(代號/名稱/收盤/漲跌%)，點擊後才彈出「個股卡片」
// (.stock-card-modal)顯示走勢圖/量價/籌碼等列表之外的詳細資訊——這是Cody要的兩層式設計
// (列表 vs 卡片是兩個不同東西，卡片是點選後才出現的彈窗，不是列表格子本身)。
function _rollTd(v) {{
  if (v === null || v === undefined) return '<td class="num tabular">─</td>';
  const c = v >= 0 ? 'var(--up)' : 'var(--down)';
  return `<td class="num tabular" style="color:${{c}}">${{v>=0?'+':''}}${{v.toFixed(2)}}%</td>`;
}}

// 量比>=1.5x視為「爆大量」，用強調色+粗體+文字徽章明確標示，不是只靠數字大小自己判斷。
function _volTd(v) {{
  if (v === null || v === undefined) return '<td class="num tabular">─</td>';
  const isBurst = v >= 1.5;
  const style = isBurst ? 'color:var(--accent);font-weight:700' : 'color:var(--ink-3)';
  const badge = isBurst ? ' <span class="vol-burst-badge">爆量</span>' : '';
  return `<td class="num tabular" style="${{style}}">${{v.toFixed(2)}}x${{badge}}</td>`;
}}

// 融資佔比/融券餘額佔比：純數字顯示，不設警示門檻(沒有客觀依據硬設門檻)。
function _plainPctTd(v) {{
  if (v === null || v === undefined) return '<td class="num tabular">─</td>';
  return `<td class="num tabular">${{v.toFixed(2)}}%</td>`;
}}

// 大戶佔比：純數字顯示，跟融資/融券佔比一樣不設門檻。
function _holderPctTd(v) {{
  if (v === null || v === undefined) return '<td class="num tabular">─</td>';
  return `<td class="num tabular">${{v.toFixed(2)}}%</td>`;
}}

// 大戶週變化：有正負號，紅漲綠跌配色(比照_rollTd的漲跌色慣例)。
function _holderChgTd(v) {{
  if (v === null || v === undefined) return '<td class="num tabular">─</td>';
  const c = v >= 0 ? 'var(--up)' : 'var(--down)';
  return `<td class="num tabular" style="color:${{c}}">${{v>=0?'+':''}}${{v.toFixed(2)}}%</td>`;
}}

// 融資/融券維持率(估)：低於130%(法規追繳門檻)視為警示，用警示色+粗體+文字徽章明確標示。
// 融資/融券兩欄共用同一套門檻邏輯(見docs/adr/0002-margin-maintenance-ratio-is-an-estimate.md)。
function _maintTd(v) {{
  if (v === null || v === undefined) return '<td class="num tabular">─</td>';
  const isDanger = v < 130;
  const style = isDanger ? 'color:var(--down);font-weight:700' : 'color:var(--ink-2)';
  const badge = isDanger ? ' <span class="maint-badge">追繳risk</span>' : '';
  return `<td class="num tabular" style="${{style}}">${{v.toFixed(1)}}%${{badge}}</td>`;
}}

function renderStockListItem(s) {{
  const sid = escHtml(s.stock_id);
  if (s.no_data) {{
    return `<tr class="stock-item no-data"><td><span class="si-id">${{sid}}</span><span class="si-name">${{escHtml(s.stock_name)}}</span></td><td colspan="13">無行情</td></tr>`;
  }}
  const color = s.change_pct >= 0 ? 'var(--up)' : 'var(--down)';
  const sign = s.change_pct >= 0 ? '+' : '';
  const arrow = s.change_pct > 0 ? '▲' : (s.change_pct < 0 ? '▼' : '─');
  return `<tr class="stock-item" tabindex="0" onclick="openStockCard('${{sid}}')" `
    + `onkeydown="if(event.key==='Enter'||event.key===' '){{event.preventDefault();openStockCard('${{sid}}')}}">`
    + `<td><span class="si-id">${{sid}}</span><span class="si-name">${{escHtml(s.stock_name)}}</span></td>`
    + `<td class="num tabular">${{fmtPrice(s.close)}}</td>`
    + `<td class="num tabular" style="color:${{color}}">${{arrow}} ${{sign}}${{s.change_pct.toFixed(2)}}%</td>`
    + `${{_volTd(s.vol_ratio)}}`
    + `${{_holderPctTd(s.holder_pct)}}`
    + `${{_holderChgTd(s.holder_week_chg)}}`
    + `${{_plainPctTd(s.financed_pct)}}`
    + `${{_maintTd(s.maintenance_est)}}`
    + `${{_plainPctTd(s.shorted_pct)}}`
    + `${{_maintTd(s.short_maintenance_est)}}`
    + `${{_rollTd(s.roll5)}}${{_rollTd(s.roll7)}}${{_rollTd(s.roll10)}}${{_rollTd(s.roll14)}}</tr>`;
}}

// 個股卡片：TradingView Lightweight Charts 日K+成交量、今日量價、近5/7/10/14日與籌碼，
// 點列表項目才彈出，跟舊版html_generator.py::openStockModal()同樣的「列表→點選→詳細卡片」
// 兩層式互動，不是永遠顯示在列表格子上。
function openStockCard(sid) {{
  const s = _panelStocks.find(x => x.stock_id === sid);
  if (!s || s.no_data) return;
  closeStockCard();

  const color = s.change_pct >= 0 ? 'var(--up)' : 'var(--down)';
  const sign = s.change_pct >= 0 ? '+' : '';
  const arrow = s.change_pct > 0 ? '▲' : (s.change_pct < 0 ? '▼' : '─');
  const rollItems = [['5日', s.roll5], ['7日', s.roll7], ['10日', s.roll10], ['14日', s.roll14]]
    .filter(([, v]) => v !== null && v !== undefined)
    .map(([lbl, v]) => {{
      const c = v >= 0 ? 'var(--up)' : 'var(--down)';
      return `<span class="sc-roll-item"><span class="lbl">${{lbl}}</span><span class="tabular" style="color:${{c}}">${{v>=0?'+':''}}${{v.toFixed(2)}}%</span></span>`;
    }}).join('');
  const rollHtml = rollItems ? `<div class="sc-roll">${{rollItems}}</div>` : '';
  const volHtml = s.volume !== null && s.volume !== undefined
    ? `<span class="sc-vol">今日 ${{s.volume.toLocaleString()}} 張</span>`
    : '';
  const volRatioHtml = s.vol_ratio !== null && s.vol_ratio !== undefined
    ? `<span class="vol-ratio${{s.vol_ratio >= 1.5 ? ' strong' : ''}}">量比 ${{s.vol_ratio.toFixed(2)}}x</span>`
    : '';
  const chipsParts = [];
  if (s.foreign_net) chipsParts.push(`<span style="color:${{s.foreign_net>0?'var(--up)':'var(--down)'}}">外資${{s.foreign_net>0?'+':''}}${{Math.trunc(s.foreign_net/1000).toLocaleString()}}張</span>`);
  if (s.trust_net) chipsParts.push(`<span style="color:${{s.trust_net>0?'var(--up)':'var(--down)'}}">投信${{s.trust_net>0?'+':''}}${{Math.trunc(s.trust_net/1000).toLocaleString()}}張</span>`);
  if (s.margin_change && s.margin_balance > 0) {{
    const pct = s.margin_change / s.margin_balance * 100;
    const marginArrow = s.margin_change > 0 ? '↑' : '↓';
    chipsParts.push(`<span style="color:var(--accent)">融資${{marginArrow}}${{Math.abs(pct).toFixed(1)}}%</span>`);
  }}
  const chipsHtml = chipsParts.length ? `<div class="sc-chips">${{chipsParts.join('')}}</div>` : '';

  const backdrop = document.createElement('div');
  backdrop.id = 'stockCardBackdrop';
  backdrop.className = 'stock-card-backdrop';
  backdrop.onclick = (e) => {{ if (e.target === backdrop) closeStockCard(); }};
  backdrop.innerHTML = `<div class="stock-card-modal" role="dialog" aria-modal="true">
      <div class="sc-header"><span class="sc-id">${{escHtml(sid)}}</span><span class="sc-name">${{escHtml(s.stock_name)}}</span>
        <button type="button" class="detail-close" onclick="closeStockCard()">收合</button></div>
      <div class="sc-body"><span class="sc-price">${{fmtPrice(s.close)}}</span><span class="sc-pct" style="color:${{color}}">${{arrow}} ${{sign}}${{s.change_pct.toFixed(2)}}%</span></div>
      <div class="sc-volume-row">${{volHtml}}${{volRatioHtml}}</div>
      <div class="tv-chart-shell">
        <div id="stockTvChartStatus" class="tv-chart-status" role="status">K 線載入中…</div>
        <div id="stockTvChart" class="tv-chart" aria-label="${{escHtml(s.stock_name)}}日 K 與成交量"></div>
        <a class="tv-attribution" href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">圖表技術由 TradingView 提供</a>
      </div>
      ${{rollHtml}}${{chipsHtml}}
    </div>`;
  document.body.appendChild(backdrop);
  document.addEventListener('keydown', _stockCardEscHandler);
  mountStockChart(s);
}}

function _stockCardEscHandler(e) {{
  if (e.key === 'Escape') closeStockCard();
}}

function closeStockCard() {{
  destroyStockChart();
  const el = document.getElementById('stockCardBackdrop');
  if (el) el.remove();
  document.removeEventListener('keydown', _stockCardEscHandler);
}}

let _panelStocks = [], _panelSortKey = 'pct', _panelSortAsc = false;

function _sortValue(s, key) {{
  if (key === 'pct') return s.change_pct;
  if (key === 'id') return s.stock_id;
  if (key === 'close') return s.close;
  if (key === 'vol') return s.vol_ratio;
  if (key === 'holder') return s.holder_pct;
  if (key === 'holderchg') return s.holder_week_chg;
  if (key === 'financed') return s.financed_pct;
  if (key === 'maint') return s.maintenance_est;
  if (key === 'shorted') return s.shorted_pct;
  if (key === 'shortmaint') return s.short_maintenance_est;
  if (key === '5' || key === '7' || key === '10' || key === '14') return s['roll' + key];
  return null;
}}

function renderPanelStocks() {{
  const wrap = document.getElementById('panelStocksWrap');
  if (!wrap) return;
  const key = _panelSortKey, asc = _panelSortAsc;
  const sorted = [..._panelStocks].sort((a, b) => {{
    const av = _sortValue(a, key), bv = _sortValue(b, key);
    if (av === null || av === undefined) return 1;
    if (bv === null || bv === undefined) return -1;
    const cmp = key === 'id' ? String(av).localeCompare(String(bv)) : av - bv;
    return asc ? cmp : -cmp;
  }});
  wrap.innerHTML = sorted.map(renderStockListItem).join('');
}}

// 點欄位名稱排序（由高到低起手，再點同一欄切換方向）——跟chips.html既有的
// .sort-button/aria-sort排序慣例一致，取代先前的下拉選單。
function sortStockList(th, key) {{
  if (_panelSortKey === key) {{
    _panelSortAsc = !_panelSortAsc;
  }} else {{
    _panelSortKey = key;
    _panelSortAsc = false;
  }}
  th.closest('table').querySelectorAll('th').forEach(h => h.setAttribute('aria-sort', 'none'));
  th.setAttribute('aria-sort', _panelSortAsc ? 'ascending' : 'descending');
  renderPanelStocks();
}}

function selectGroup(name, toggle) {{
  closeStockCard();
  const drawer = document.getElementById('sectorDrawer');
  const activeTile = document.querySelector('.heat-tile.active');
  const alreadyOpen = drawer.classList.contains('open') && activeTile && activeTile.dataset.metaName === name;
  if (toggle && alreadyOpen) {{ closeSectorDrawer(); return; }}

  const tiles = [...document.querySelectorAll('.heat-tile')];
  const tile = tiles.find(t => t.dataset.metaName === name);
  if (!tile) return;
  if (tile.hidden) {{
    sectorView.showAll = true;
    sectorView.bucket = '';
    sectorView.name = '';
    sectorView.advancedActive = false;
    syncSectorControls();
    applySectorView();
  }}
  document.querySelectorAll('.heat-tile').forEach(t => t.classList.remove('active'));
  tile.classList.add('active');
  if (!toggle) tile.scrollIntoView({{behavior:'smooth', block:'center'}});

  const meta = CARD_META[name];
  if (!meta) return;
  const stocks = STOCKS[name] || [];
  const safeName = escHtml(name);
  _panelStocks = stocks;
  _panelSortKey = 'pct';
  _panelSortAsc = false;

  const panel = document.createElement('div');
  panel.id = 'detailPanel';
  panel.className = 'detail-panel';
  const pctColor = meta.pct >= 0 ? 'var(--up)' : 'var(--down)';
  const pctStr = (meta.pct >= 0 ? '+' : '') + meta.pct.toFixed(2) + '%';
  const metaSpark = buildSparkline(meta.daily_pct, meta.dates, 'meta-sparkline');
  const chipsSum = buildChipsSummary(meta);
  const historyRecord = buildHistoryRecord(meta);
  const asofStock = stocks.find(s => s.total_shares_asof);
  const asofNote = asofStock ? `<div class="asof-note">集保資料：${{escHtml(asofStock.total_shares_asof)}}</div>` : '';
  const rankDelta = meta.rank_delta === null || meta.rank_delta === undefined ? '' : ` (${{meta.rank_delta>=0?'↑':'↓'}}${{Math.abs(meta.rank_delta)}})`;
  const tierLabel = meta.tier ? escHtml(meta.tier.label) : '資料不足';
  const tempLabel = meta.temp ? escHtml(meta.temp.label) : '溫度持平';
  const cum5 = meta.cum5 === null || meta.cum5 === undefined ? '—' : `${{meta.cum5>=0?'+':''}}${{meta.cum5.toFixed(2)}}%`;
  const volRatio = meta.vol_ratio === null || meta.vol_ratio === undefined ? '—' : `${{meta.vol_ratio.toFixed(2)}}x`;
  const summary = `<div class="drawer-summary">
      <span><b>排名</b><strong class="tabular">#${{meta.rank}}${{rankDelta}}</strong></span>
      <span><b>動能</b><strong>${{tierLabel}}</strong></span><span><b>溫度</b><strong>${{tempLabel}}</strong></span>
      <span><b>近 5 日</b><strong class="tabular">${{cum5}}</strong></span><span><b>量比</b><strong class="tabular">${{volRatio}}</strong></span>
    </div>`;

  if (!stocks.length) {{
    panel.innerHTML = `
      <div class="detail-head"><h3 id="drawerTitle">${{safeName}}</h3><span class="dpct" style="color:${{pctColor}}">${{pctStr}}</span></div>
      <div class="detail-sub">▲${{meta.up_count}}檔 ▼${{meta.down_count}}檔</div>
      ${{summary}}
      <div class="detail-three-col">
        <div class="tc-box">${{metaSpark}}</div>
        <div class="tc-box">${{chipsSum}}</div>
        <div class="tc-box">${{historyRecord}}</div>
      </div>
      <div class="detail-empty">這個族群目前沒有個股行情資料。</div>`;
  }} else {{
    panel.innerHTML = `
      <div class="detail-head"><h3 id="drawerTitle">${{safeName}}</h3><span class="dpct" style="color:${{pctColor}}">${{pctStr}}</span></div>
      <div class="detail-sub">▲${{meta.up_count}}檔 ▼${{meta.down_count}}檔　・　共 ${{stocks.length}} 檔</div>
      ${{summary}}
      <div class="detail-three-col">
        <div class="tc-box">${{metaSpark}}</div>
        <div class="tc-box">${{chipsSum}}</div>
        <div class="tc-box">${{historyRecord}}</div>
      </div>
      ${{asofNote}}
      <div class="overflow-wrap"><table class="stock-list-table">
        <thead><tr>
          <th aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'id')">股票</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'close')">收盤</button></th>
          <th class="num" aria-sort="descending"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'pct')">漲跌%</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'vol')">量比</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'holder')">大戶佔比</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'holderchg')">大戶週變化</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'financed')">融資佔比</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'maint')">融資維持率(估)</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'shorted')">融券餘額佔比</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'shortmaint')">融券維持率(估)</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'5')">5日</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'7')">7日</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'10')">10日</button></th>
          <th class="num" aria-sort="none"><button type="button" class="sort-button" onclick="sortStockList(this.parentElement,'14')">14日</button></th>
        </tr></thead>
        <tbody id="panelStocksWrap"></tbody>
      </table></div>`;
  }}

  if (!drawer.classList.contains('open')) {{
    _drawerReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : tile;
  }}
  document.getElementById('drawerContent').replaceChildren(panel);
  drawer.classList.add('open');
  document.body.classList.add('drawer-open');
  drawer.setAttribute('aria-hidden', 'false');
  if (stocks.length) renderPanelStocks();
  document.getElementById('drawerClose').focus();
}}

function closeSectorDrawer() {{
  closeStockCard();
  const drawer = document.getElementById('sectorDrawer');
  drawer.classList.remove('open');
  document.body.classList.remove('drawer-open');
  drawer.setAttribute('aria-hidden', 'true');
  document.querySelectorAll('.heat-tile').forEach(t => t.classList.remove('active'));
  document.getElementById('drawerContent').replaceChildren();
  if (_drawerReturnFocus && document.contains(_drawerReturnFocus)) _drawerReturnFocus.focus();
  _drawerReturnFocus = null;
}}

/* ── 個股/族群搜尋 ── */
function searchStocks(q) {{
  const dd = document.getElementById('search-dropdown');
  q = q.trim();
  if (!q) {{ dd.hidden = true; return; }}

  const stockMatches = STOCK_INDEX.filter(s => s.id.startsWith(q) || s.name.includes(q)).slice(0, 6);
  const metaMatches = META_INDEX.filter(m => m.name.includes(q)).slice(0, 5);
  if (!stockMatches.length && !metaMatches.length) {{ dd.hidden = true; return; }}

  const stockHtml = stockMatches.map(s => {{
    const col = s.pct > 0 ? 'var(--up)' : (s.pct < 0 ? 'var(--down)' : 'var(--ink-3)');
    const sign = s.pct >= 0 ? '+' : '';
    return `<div class="search-item" onmousedown="selectSearchStock('${{s.id}}')">`
      + `<span class="si-id">${{escHtml(s.id)}}</span><span class="si-name">${{escHtml(s.name)}}</span>`
      + `<span class="si-meta">${{escHtml(s.meta)}}</span>`
      + `<span class="si-pct" style="color:${{col}}">${{sign}}${{s.pct.toFixed(2)}}%</span></div>`;
  }}).join('');
  const metaHtml = metaMatches.map(m => {{
    const col = m.pct > 0 ? 'var(--up)' : (m.pct < 0 ? 'var(--down)' : 'var(--ink-3)');
    const sign = m.pct >= 0 ? '+' : '';
    return `<div class="search-item" onmousedown="selectSearchMeta('${{m.name.replace(/'/g, "\\\\'")}}')">`
      + `<span class="si-id si-meta-icon">族群</span><span class="si-name">${{escHtml(m.name)}}</span>`
      + `<span class="si-pct" style="color:${{col}}">${{sign}}${{m.pct.toFixed(2)}}%</span></div>`;
  }}).join('');
  dd.innerHTML = stockHtml + metaHtml;
  dd.hidden = false;
}}
function hideSearch() {{ document.getElementById('search-dropdown').hidden = true; }}
function selectSearchMeta(name) {{
  document.getElementById('search-dropdown').hidden = true;
  document.getElementById('stock-search').value = '';
  selectGroup(name);
}}
function selectSearchStock(sid) {{
  document.getElementById('search-dropdown').hidden = true;
  document.getElementById('stock-search').value = '';
  const entry = STOCK_INDEX.find(s => s.id === sid);
  if (entry) selectGroup(entry.meta);
}}

// chips.html的外資/投信連買族群連結會產生 index.html#meta=族群名（見
// export/chips_generator.py），舊版html_generator.py靠這段IIFE在載入時自動展開對應面板，
// 這次改版漏掉了，造成從chips.html點連結進來會停在空白頁——補回同等行為。
(function() {{
  loadSectorView();
  if (DATA_MODE !== 'intraday') sectorView.rankMode = 'live';
  syncSectorControls();
  applySectorView();
  document.addEventListener('keydown', event => {{
    if (event.key !== 'Escape' || document.getElementById('stockCardBackdrop')) return;
    if (document.getElementById('sectorDrawer').classList.contains('open')) closeSectorDrawer();
  }});
  const h = decodeURIComponent(location.hash);
  if (h.startsWith('#meta=')) selectGroup(h.slice(6));
}})();
</script>
</body></html>"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
