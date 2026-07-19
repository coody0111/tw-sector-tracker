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
