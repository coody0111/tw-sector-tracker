"""
生成 docs/momentum.html — 逆轟動能策略 v2 決策支援頁
資料來源：scan_momentum_health() + scan_bullish_alignment_new_high() +
         scan_consecutive_limit_up() + classify_market_regime() +
         calc_meta_observation_scores()
設計依據：docs/superpowers/specs/2026-07-16-momentum-strategy-page-v2-design.md（v2，取代
         2026-07-14/2026-07-15 兩份舊 spec）。

⚠️ docs/superpowers/plans/2026-07-16-momentum-strategy-page.md 是 v2 spec 定案前的舊 plan，
裡面的函式（tier_action_text/regime_banner_content/resilience_candidates）使用 v2 明文禁止
的命令式文案且誤用5日rs_market_score，本檔案函式名稱與邏輯跟那份舊 plan 完全不同、不相容，
不要混用。
"""
from html import escape as _html_escape
from datetime import date
from pathlib import Path

# v2 spec §4.2：上線前必須全文搜尋並禁止這些命令式字樣，generate() 的輸出不得含有任何一個。
BANNED_PHRASES = ("隨時加碼", "一定續抱", "直接出清", "立刻砍", "可換入", "反手放空")

# 跌停/重挫 proxy 門檻，跟 screener/signals.py 的同名私有常數同步維護（v2 spec §3.3/§3.6）。
_LIMIT_DOWN_PCT = -9.5
_EXIT_BIG_BLACK_PCT = -4.0

# classify_sector_state() 草案門檻——spec §2.2 只有質化描述，沒有精確切點，這些數字是
# writing-plans 階段新增的草案，待回測校準，見本計畫 Global Constraints 說明。
_SECTOR_STATE_SCORE_STRONG = 65.0
_SECTOR_STATE_SCORE_TURNING = 50.0
_SECTOR_STATE_BREADTH_BROAD = 0.5


def _esc(value) -> str:
    """HTML-escape 外部資料（股票/族群名稱等），比照 chips_generator.py::_esc() 同一防護。"""
    return _html_escape(str(value)) if value else ""


def rs_sample_confidence(rs_sample_count: int) -> str:
    """
    族群內 RS 樣本信心分級（v2 spec §3.2）。單一成分股必然 rs_rank_pct=1.0、兩檔股票最差
    也可能是0.5，會產生假精準，這裡分三級供消費端判斷是否能單靠 rs_rank_pct 升級成進場候選。

    ≥10 檔 → "A"；5~9 檔 → "B"；<5 檔 → "C"（低樣本，見 determine_final_label() 的
    § 3.4 進場閘門：C 時不能單靠 RS 排名升級成進場候選）。
    """
    if rs_sample_count >= 10:
        return "A"
    if rs_sample_count >= 5:
        return "B"
    return "C"


def market_permission(market_regime: dict, index_date: str = None, price_date: str = None) -> dict:
    """
    市場操作許可（v2 spec §2.1）。market_regime 是既有
    processors/performance.py::classify_market_regime() 的回傳 dict，外加呼叫端已合併的
    taiex_change_pct/breadth_ratio/concentration_direction（main.py::run() 既有合併方式）。

    index_date/price_date 由呼叫端傳入實際資料日期；兩者不同時降級為 "unknown"，不輸出市場
    操作文案（v2 spec §2.1：這個一致性檢查必須由呼叫端提供真實日期，這支函式只負責比較，不
    猜測資料是否新鮮）。任一為 None（呼叫端未提供）時跳過日期檢查，直接依 tier 判斷。

    Returns
    -------
    {permission, tier_text, divergence_text, advice_text}
    permission ∈ {"normal", "selective", "defensive", "unknown"}
    """
    if index_date is not None and price_date is not None and index_date != price_date:
        return {
            "permission": "unknown",
            "tier_text": "資料日期不一致",
            "divergence_text": f"指數資料日期 {index_date} 與個股行情日期 {price_date} 不同，暫不輸出市場操作許可。",
            "advice_text": "",
        }

    tier = market_regime.get("tier", "持平")
    if tier in ("大漲", "小漲"):
        permission = "normal"
    elif tier in ("小跌", "大跌"):
        permission = "defensive"
    else:
        permission = "selective"

    taiex_pct = market_regime.get("taiex_change_pct")
    breadth = market_regime.get("breadth_ratio")
    concentration_direction = market_regime.get("concentration_direction")

    divergence_text = ""
    if tier == "持平" and taiex_pct is not None and abs(taiex_pct) >= 0.3:
        direction = "上漲" if taiex_pct > 0 else "下跌"
        breadth_str = f"{breadth * 100:.0f}%" if breadth is not None else "─"
        divergence_text = (
            f"指數{direction} {taiex_pct:+.2f}%，但個股上漲家數比僅 {breadth_str}，"
            f"廣度未確認方向，暫列為持平／選擇性操作。"
        )
    if concentration_direction:
        prefix = f"{divergence_text} " if divergence_text else ""
        divergence_text = f"{prefix}資金集中診斷：{concentration_direction}。"

    if permission == "normal":
        advice_text = "市場許可正常尋找進場候選；仍須逐項確認個股進場閘門，非全面買進。"
    elif permission == "selective":
        advice_text = "只看條件完整的強勢候選；訊號不足的個股維持觀察，不追價。"
    else:
        advice_text = "停止一般追價，優先檢視抗跌個股與持有風險；本區不輸出進場策略。"

    return {
        "permission": permission,
        "tier_text": tier,
        "divergence_text": divergence_text,
        "advice_text": advice_text,
    }


def classify_sector_state(observation_data: dict) -> str:
    """
    族群狀態五級分類（v2 spec §2.2 prose 描述，草案門檻，見 Global Constraints）。
    只用來決定 determine_final_label() 的進場閘門（sector_state in {主升,轉強}）及頁面顯示
    文字，不直接產生買賣動作。

    observation_data 是 calc_meta_observation_scores() 回傳 dict 裡單一族群的 value。
    """
    score = observation_data.get("observation_score")
    breadth = observation_data.get("breadth_raw")
    continuation = observation_data.get("continuation_raw")
    rs_raw = observation_data.get("rs_raw")

    if score is None:
        return "等待確認"
    if score >= _SECTOR_STATE_SCORE_STRONG and breadth is not None and breadth >= _SECTOR_STATE_BREADTH_BROAD:
        return "主升"
    if score >= _SECTOR_STATE_SCORE_TURNING:
        return "轉強"
    if rs_raw is not None and rs_raw > 0 and (continuation is None or continuation <= 1):
        return "急彈"
    if rs_raw is not None and rs_raw < 0:
        return "轉弱"
    return "等待確認"


def build_sector_priority(observation_scores: dict, top_n: int = 5) -> list:
    """
    主流族群 Top N（v2 spec §2.2/§4）。observation_scores 是既有
    processors/observation_scores.py::calc_meta_observation_scores() 的回傳 dict。

    observation_score 為 None 的族群排最後（5因子全不可用，見該函式邊界情況），依
    observation_score 降冪排列，回傳前 top_n 筆，每筆含 rank（1-based，只在回傳的
    top_n 筆內編號，不是全族群排名）。
    """
    rows = []
    for meta_name, data in observation_scores.items():
        rows.append({
            "meta_name": meta_name,
            "observation_score": data.get("observation_score"),
            "score_coverage": data.get("score_coverage", 0.0),
            "rs_raw": data.get("rs_raw"),
            "breadth_raw": data.get("breadth_raw"),
            "continuation_raw": data.get("continuation_raw"),
            "volume_raw": data.get("volume_raw"),
            "chips_raw": data.get("chips_raw"),
            "partial_coverage": data.get("partial_coverage", False),
            "sector_state": classify_sector_state(data),
        })
    rows.sort(key=lambda r: r["observation_score"] if r["observation_score"] is not None else -1.0, reverse=True)
    top_rows = rows[:top_n]
    for i, row in enumerate(top_rows):
        row["rank"] = i + 1
    return top_rows


_RS_CONFIDENCE_BLOCKING = "C"

_TIER_ORDER = {"超強": 0, "強": 1, "整理": 2, "弱": 3, "超弱": 4}


def determine_final_label(
    stock_row: dict,
    market_permission_state: str,
    sector_state: str,
    bullish_new_high_map: dict,
) -> str:
    """
    最終決策標籤（v2 spec §2.4），六選一，全部為非命令式狀態描述。stock_row 是
    scan_momentum_health() 單筆輸出。bullish_new_high_map 是
    {stock_id: scan_bullish_alignment_new_high()單筆輸出}，供判斷 B3 清單成員資格與
    volume_confirmed（不能只傳一個 set，因為還需要讀 volume_confirmed 的值）。

    優先序（由上到下，符合就回傳，不繼續往下判斷）：
    1. 跌停風險：change_pct <= _LIMIT_DOWN_PCT（流動性風險最急迫，跟其他狀態互斥，
       即使同時符合出場條件命中或其他狀態也只顯示這個）
    2. 出場條件命中：exit_3_rule_triggered
    3. 進場候選：spec §3.4 六項閘門同時成立
    4. 風險升高：strength_tier=="弱" 或 market_permission_state=="defensive"
    5. 續強觀察：strength_tier in {"超強","強"}（但進場閘門未全部成立）
    6. 等待確認：其餘情況（整理、急彈、資料不足）
    """
    change_pct = stock_row.get("change_pct")
    if change_pct is not None and change_pct <= _LIMIT_DOWN_PCT:
        return "跌停風險"

    if stock_row.get("exit_3_rule_triggered"):
        return "出場條件命中"

    sid = stock_row.get("stock_id")
    confidence = rs_sample_confidence(stock_row.get("rs_sample_count", 0))
    b3_row = bullish_new_high_map.get(sid)
    entry_gate = (
        market_permission_state in ("normal", "selective")
        and sector_state in ("主升", "轉強")
        and stock_row.get("strength_tier") in ("超強", "強")
        and bool(stock_row.get("entry_confirmed"))
        and b3_row is not None
        and bool(b3_row.get("volume_confirmed"))
        and confidence != _RS_CONFIDENCE_BLOCKING
    )
    if entry_gate:
        return "進場候選"

    if stock_row.get("strength_tier") in ("弱", "超弱") or market_permission_state == "defensive":
        return "風險升高"

    if stock_row.get("strength_tier") in ("超強", "強"):
        return "續強觀察"

    return "等待確認"


def build_decision_table(
    momentum_results: list,
    bullish_new_high_results: list,
    market_permission_state: str,
    sector_states: dict,
) -> list:
    """
    個股決策主表（v2 spec §4/§4.1）。組合 scan_momentum_health() +
    scan_bullish_alignment_new_high() + 族群狀態 + 市場許可 → 每檔股票的最終標籤與證據。

    sector_states：{meta_name: sector_state_str}，呼叫端先對 calc_meta_observation_scores()
    的**全量**輸出（不只 build_sector_priority() 的 top_n）逐族群跑過 classify_sector_state()——
    個股不會因為所屬族群沒排進首頁Top5就被排除在主表外。

    排序：先依族群內最強個股的技術狀態排序分組（族群整體越強，組別排越前面），組內再依
    strength_tier（超強>強>整理>弱>超弱）與 rs_rank_pct 降冪排列。
    """
    bullish_map = {r["stock_id"]: r for r in bullish_new_high_results}

    rows = []
    for row in momentum_results:
        meta_name = row.get("meta_sector")
        sector_state = sector_states.get(meta_name, "等待確認")
        label = determine_final_label(row, market_permission_state, sector_state, bullish_map)
        confidence = rs_sample_confidence(row.get("rs_sample_count", 0))
        b3_row = bullish_map.get(row["stock_id"])
        rows.append({
            "stock_id": row["stock_id"],
            "stock_name": row["stock_name"],
            "meta_sector": meta_name,
            "sector_state": sector_state,
            "close": row["close"],
            "change_pct": row["change_pct"],
            "strength_tier": row["strength_tier"],
            "rs_rank_pct": row["rs_rank_pct"],
            "rs_sample_count": row.get("rs_sample_count", 0),
            "rs_confidence": confidence,
            "rs_market_score": row.get("rs_market_score"),
            "daily_excess_pct": row.get("daily_excess_pct"),
            "final_label": label,
            "entry_evidence": [
                ("多頭排列＋創新高（B3清單內）", b3_row is not None),
                ("量能確認（B3量比≥1.5）", bool(b3_row.get("volume_confirmed")) if b3_row else False),
                ("動能確認：MA5/MA10皆上揚", bool(row.get("entry_confirmed"))),
            ],
            "exit_evidence": [
                ("跌破五日線", bool(row.get("below_ma5"))),
                ("五日線下彎", bool(row.get("ma5_slope_down"))),
                ("重挫proxy（單日跌幅近似，非完整K棒長黑）", bool(row.get("big_black_proxy"))),
            ],
            "ma": {"ma5": row["ma5"], "ma10": row["ma10"], "ma20": row["ma20"], "ma60": row["ma60"]},
        })

    sector_best_rank: dict = {}
    for row in rows:
        combo = (_TIER_ORDER.get(row["strength_tier"], 5), -(row["rs_rank_pct"] or 0))
        s = row["meta_sector"]
        if s not in sector_best_rank or combo < sector_best_rank[s]:
            sector_best_rank[s] = combo

    rows.sort(key=lambda r: (
        sector_best_rank[r["meta_sector"]],
        _TIER_ORDER.get(r["strength_tier"], 5),
        -(r["rs_rank_pct"] or 0),
    ))
    return rows


def selloff_risk_zone(momentum_results: list) -> dict:
    """
    急殺風險區資料（v2 spec §3.1/§3.6/§4「僅defensive顯示」）。這支函式本身不檢查市場
    許可狀態，純資料整理，呼叫端（generate()）決定要不要渲染這個區塊。

    抗跌候選：daily_excess_pct > 0（今日抗跌優於大盤單日均值），依 daily_excess_pct 降冪
    排列。**必須用 daily_excess_pct，不能用 rs_market_score**（v2 spec §3.1：急殺模式候選
    條件使用單日 daily_excess_pct，rs_market_score 是5日週期，兩者不可互相代替）。
    跌停風險：change_pct <= _LIMIT_DOWN_PCT，優先權高於抗跌候選（同時符合兩邊時只算跌停
    風險，流動性風險比抗跌排名更急迫）。
    """
    limit_down = [
        r for r in momentum_results
        if r.get("change_pct") is not None and r["change_pct"] <= _LIMIT_DOWN_PCT
    ]
    limit_down_ids = {r["stock_id"] for r in limit_down}

    resilient = [
        r for r in momentum_results
        if r.get("daily_excess_pct") is not None and r["daily_excess_pct"] > 0
        and r["stock_id"] not in limit_down_ids
    ]
    resilient.sort(key=lambda r: r["daily_excess_pct"], reverse=True)

    return {
        "resilient": [
            {"stock_id": r["stock_id"], "stock_name": r["stock_name"], "meta_sector": r["meta_sector"],
             "change_pct": r["change_pct"], "daily_excess_pct": r["daily_excess_pct"]}
            for r in resilient
        ],
        "limit_down": [
            {"stock_id": r["stock_id"], "stock_name": r["stock_name"], "meta_sector": r["meta_sector"],
             "change_pct": r["change_pct"]}
            for r in limit_down
        ],
    }


def build_streak_cards(limit_up_results: list) -> list:
    """
    連續收近漲停卡片資料（v2 spec §3.5，顯示名稱固定用「連續收近漲停」，不再稱「鎖死」，
    因為現有資料無法證明盤中全程鎖死）。直接沿用 scan_consecutive_limit_up() 既有降冪排序。
    """
    return [
        {
            "stock_id": row["stock_id"],
            "stock_name": row["stock_name"],
            "meta_sector": row["meta_sector"],
            "limit_up_streak": row["limit_up_streak"],
            "volume_declining_streak": row["volume_declining_streak"],
            "breakout_volume_confirmed": row["breakout_volume_confirmed"],
        }
        for row in limit_up_results
    ]


_CSS = """
:root{--bg:#080B12;--panel:#0F1420;--panel-2:#161D2C;--border:#293346;
  --ink:#DADFE8;--ink-2:#98A0B4;--ink-3:#636B80;--up:#E6432F;--down:#37B25C;
  --accent:#F0BB55;--tier-super:#F0BB55;--tier-strong:#4FC46A;--tier-mid:#8B94AC;
  --tier-weak:#E08A3E;--tier-superweak:#E6432F;
  --sans:"Public Sans",-apple-system,"PingFang TC","Microsoft JhengHei","Segoe UI",sans-serif;
  --mono:ui-monospace,"IBM Plex Mono","Cascadia Code","Roboto Mono",monospace;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:14px;line-height:1.55;padding:0 0 80px}
.tabular{font-family:var(--mono);font-variant-numeric:tabular-nums}
a{color:inherit}
.skip-link{position:absolute;left:-999px;top:0;background:var(--panel);color:var(--ink);padding:8px 14px;z-index:100}
.skip-link:focus{left:8px;top:8px}
.topbar{display:flex;align-items:baseline;gap:16px;padding:18px 24px;border-bottom:1px solid var(--border);flex-wrap:wrap}
.topbar h1{font-size:1.2rem;font-weight:700;margin:0}
.topbar .sub{font-size:.72rem;color:var(--ink-3)}
.nav-links{display:flex;gap:8px;margin-left:auto}
.nav-link{font-size:.78rem;padding:5px 14px;border-radius:6px;border:1px solid var(--border);color:var(--ink-2);text-decoration:none}
.nav-link:hover{border-color:var(--ink-2);color:var(--ink)}
.nav-link.active{border-color:var(--accent);color:var(--ink);background:var(--panel-2)}
.nav-link:focus-visible,button:focus-visible,summary:focus-visible,a:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.notice{margin:16px 24px;padding:10px 16px;border:1px solid var(--border);border-radius:8px;color:var(--ink-2);font-size:.8rem}
.permission-banner{margin:0 24px 20px;padding:18px 20px;border-radius:10px;border:1px solid var(--border);border-left:4px solid var(--tier-mid)}
.permission-banner[data-permission="normal"]{border-left-color:var(--tier-strong)}
.permission-banner[data-permission="selective"]{border-left-color:var(--accent)}
.permission-banner[data-permission="defensive"]{border-left-color:var(--tier-superweak)}
.permission-banner[data-permission="unknown"]{border-left-color:var(--ink-3)}
.permission-banner h2{margin:0 0 6px;font-size:1.1rem}
.permission-banner p{margin:4px 0;color:var(--ink-2);font-size:.85rem}
.section-head{margin:28px 24px 10px}
.section-head h2{font-size:1rem;margin:0}
.sector-grid{display:flex;gap:10px;flex-wrap:wrap;margin:0 24px}
.sector-card{border:1px solid var(--border);border-radius:8px;padding:10px 14px;background:var(--panel);min-width:150px}
.sector-card .rank{color:var(--accent);font-weight:700;font-family:var(--mono)}
.sector-card .state{font-size:.72rem;color:var(--ink-2)}
table.decision-table{width:100%;border-collapse:collapse;margin:0 24px;max-width:calc(100% - 48px)}
.decision-table th,.decision-table td{padding:8px 10px;border-bottom:1px solid var(--border);text-align:left;font-size:.82rem}
.decision-table th{color:var(--ink-3);font-weight:600;font-size:.72rem;text-transform:uppercase}
.tier-badge{padding:2px 8px;border-radius:4px;font-size:.72rem;font-weight:600}
.tier-badge[data-tier="超強"]{color:var(--tier-super)}
.tier-badge[data-tier="強"]{color:var(--tier-strong)}
.tier-badge[data-tier="整理"]{color:var(--tier-mid)}
.tier-badge[data-tier="弱"]{color:var(--tier-weak)}
.tier-badge[data-tier="超弱"]{color:var(--tier-superweak)}
.label-badge{padding:3px 10px;border-radius:12px;font-size:.72rem;font-weight:600;border:1px solid var(--border)}
.up{color:var(--up)}.down{color:var(--down)}
details.evidence{margin-top:4px}
details.evidence summary{cursor:pointer;font-size:.76rem;color:var(--ink-2)}
.evidence-list{margin:6px 0 0;padding-left:18px;font-size:.78rem;color:var(--ink-2)}
.evidence-list li[data-pass="true"]{color:var(--tier-strong)}
.evidence-list li[data-pass="false"]{color:var(--ink-3)}
.risk-zone{margin:28px 24px;padding:16px 20px;border:1px solid var(--tier-superweak);border-radius:10px}
.risk-zone h2{margin:0 0 10px;font-size:1rem}
.streak-grid{display:flex;gap:10px;flex-wrap:wrap;margin:0 24px}
.streak-card{border:1px solid var(--border);border-radius:8px;padding:10px 14px;background:var(--panel)}
.overflow-wrap{overflow-x:auto}
"""


def _pct_str(value) -> str:
    if value is None:
        return "─"
    cls = "up" if value > 0 else ("down" if value < 0 else "")
    sign = "+" if value > 0 else ""
    return f'<span class="tabular {cls}">{sign}{value:.2f}%</span>'


def _evidence_list(items: list) -> str:
    lis = "".join(
        f'<li data-pass="{"true" if passed else "false"}">{"✓" if passed else "✗"} {_esc(label)}</li>'
        for label, passed in items
    )
    return f'<ul class="evidence-list">{lis}</ul>'


def _sector_priority_html(sector_priority: list) -> str:
    if not sector_priority:
        return ""
    cards = []
    for row in sector_priority:
        score = row.get("observation_score")
        score_str = f"{score:.1f}" if score is not None else "─"
        coverage = row.get("score_coverage", 0.0)
        cards.append(
            f'<div class="sector-card" id="sector-{_esc(row["meta_name"])}">'
            f'<span class="rank">#{row["rank"]}</span> '
            f'<strong>{_esc(row["meta_name"])}</strong>'
            f'<div class="state">觀察分 {score_str}（涵蓋率 {coverage*100:.0f}%）· {_esc(row.get("sector_state", ""))}</div>'
            f'</div>'
        )
    return (
        '<div class="section-head"><h2>主流族群 Top 5</h2>'
        '<p style="color:var(--ink-3);font-size:.78rem">觀察分為實驗性分數，用於決定優先展開順序，不直接產生買賣動作。</p></div>'
        f'<div class="sector-grid">{"".join(cards)}</div>'
    )


def _decision_table_html(decision_table: list) -> str:
    rows = []
    for row in decision_table:
        rs_cell = (
            f'<td class="tabular">{row["rs_rank_pct"]:.2f}（{_esc(row["rs_confidence"])}）</td>'
            if row["rs_rank_pct"] is not None else '<td>─</td>'
        )
        rows.append(
            "<tr>"
            f'<td><strong>{_esc(row["stock_name"])}</strong> {_esc(row["stock_id"])}'
            f'<div style="color:var(--ink-3);font-size:.72rem">{_esc(row["meta_sector"])} · {_esc(row["sector_state"])}</div></td>'
            f'<td><span class="tier-badge" data-tier="{_esc(row["strength_tier"])}">{_esc(row["strength_tier"])}</span></td>'
            + rs_cell
            + f'<td>{_pct_str(row.get("daily_excess_pct"))}</td>'
            f'<td><span class="label-badge">{_esc(row["final_label"])}</span></td>'
            "<td><details class=\"evidence\"><summary>展開證據</summary>"
            f'<strong style="font-size:.76rem">進場</strong>{_evidence_list(row["entry_evidence"])}'
            f'<strong style="font-size:.76rem">出場</strong>{_evidence_list(row["exit_evidence"])}'
            f'<div style="font-size:.74rem;color:var(--ink-3);margin-top:6px" class="tabular">'
            f'MA5 {row["ma"]["ma5"]} · MA10 {row["ma"]["ma10"]} · MA20 {row["ma"]["ma20"]} · MA60 {row["ma"]["ma60"]}</div>'
            "</details></td></tr>"
        )
    return "".join(rows)


def _risk_zone_html(risk_zone: dict) -> str:
    resilient = risk_zone.get("resilient", [])
    limit_down = risk_zone.get("limit_down", [])
    if not resilient and not limit_down:
        return ""
    resilient_rows = "".join(
        f'<li>{_esc(r["stock_name"])} {_esc(r["stock_id"])}（{_esc(r["meta_sector"])}）'
        f'今日抗跌差 {_pct_str(r["daily_excess_pct"])}</li>'
        for r in resilient
    )
    limit_down_rows = "".join(
        f'<li>{_esc(r["stock_name"])} {_esc(r["stock_id"])}（{_esc(r["meta_sector"])}）'
        f'{_pct_str(r["change_pct"])}</li>'
        for r in limit_down
    )
    return (
        '<div class="risk-zone"><h2>急殺風險區</h2>'
        '<p style="color:var(--ink-2);font-size:.8rem">僅市場許可為防禦模式時顯示。以下為抗跌候選與流動性風險提醒，'
        '不代表放空或出場委託指令。</p>'
        f'<div><strong>抗跌候選（今日抗跌差 &gt; 0）</strong><ul class="evidence-list">{resilient_rows or "<li>無</li>"}</ul></div>'
        f'<div><strong>跌停風險（流動性受限，實際委託可能無法成交）</strong><ul class="evidence-list">{limit_down_rows or "<li>無</li>"}</ul></div>'
        '</div>'
    )


def _streak_cards_html(streak_cards: list) -> str:
    if not streak_cards:
        return ""
    cards = "".join(
        f'<div class="streak-card"><strong>{_esc(c["stock_name"])}</strong> {_esc(c["stock_id"])}'
        f'<div class="tabular" style="font-size:.78rem;color:var(--ink-2)">連續收近漲停 {c["limit_up_streak"]} 天'
        f' · 量縮 {"是" if c["volume_declining_streak"] else ("否" if c["volume_declining_streak"] is False else "─")}'
        f' · 起漲量能確認 {"是" if c["breakout_volume_confirmed"] else ("否" if c["breakout_volume_confirmed"] is False else "─")}</div></div>'
        for c in streak_cards
    )
    return f'<div class="section-head"><h2>連續收近漲停</h2></div><div class="streak-grid">{cards}</div>'


def generate(
    trade_date: date,
    market_permission_data: dict,
    sector_priority: list,
    decision_table: list,
    risk_zone: dict,
    streak_cards: list,
    index_date: str = None,
    price_date: str = None,
    chips_date: str = None,
    output_path: str = "docs/momentum.html",
) -> bool:
    """
    產生 docs/momentum.html。decision_table 為空時不寫檔、回傳 False（比照
    chips_generator.py::generate() 既有慣例，代表本次每日流程 momentum 相關資料源失敗）。
    """
    if not decision_table:
        return False

    date_str = trade_date.strftime("%Y-%m-%d")
    permission = market_permission_data.get("permission", "unknown")
    tier_text = _esc(market_permission_data.get("tier_text", ""))
    divergence_text = _esc(market_permission_data.get("divergence_text", ""))
    advice_text = _esc(market_permission_data.get("advice_text", ""))

    freshness_bits = []
    if index_date:
        freshness_bits.append(f"指數 {index_date}")
    if price_date:
        freshness_bits.append(f"個股行情 {price_date}")
    if chips_date:
        freshness_bits.append(f"籌碼 {chips_date}")
    freshness_text = "　·　".join(freshness_bits) if freshness_bits else date_str

    risk_zone_html = _risk_zone_html(risk_zone) if permission == "defensive" else ""

    html = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<title>逆轟動能策略 {date_str}</title>
<style>{_CSS}</style>
</head>
<body>
<a class="skip-link" href="#main-content">跳到主要內容</a>
<header class="topbar">
  <h1>逆轟動能策略</h1>
  <span class="sub">{freshness_text}</span>
  <nav class="nav-links" aria-label="主要功能">
    <a class="nav-link" href="index.html">族群績效</a>
    <a class="nav-link" href="chips.html">籌碼分析</a>
    <a class="nav-link" href="patterns.html">形態掃描</a>
    <a class="nav-link active" href="momentum.html" aria-current="page">逆轟策略</a>
  </nav>
</header>
<div class="notice">本頁為全市場動能掃描與決策支援，不是自動交易或個人化投資建議。所有分數與門檻標記為實驗性，尚未回測校準。</div>
<main id="main-content">
<div class="permission-banner" data-permission="{permission}">
  <h2>市場操作許可：{tier_text}</h2>
  {f'<p>{divergence_text}</p>' if divergence_text else ''}
  {f'<p>{advice_text}</p>' if advice_text else ''}
</div>
{_sector_priority_html(sector_priority)}
<div class="section-head"><h2>個股決策主表</h2></div>
<div class="overflow-wrap">
<table class="decision-table">
<thead><tr><th>股票</th><th>技術狀態</th><th>族群內RS（信心）</th><th>今日抗跌差</th><th>最終標籤</th><th>證據</th></tr></thead>
<tbody>{_decision_table_html(decision_table)}</tbody>
</table>
</div>
{risk_zone_html}
{_streak_cards_html(streak_cards)}
</main>
</body></html>"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    return True
