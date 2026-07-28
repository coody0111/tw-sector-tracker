"""
籌碼頁（docs/chips.html）今日焦點 headline zone
設計依據：docs/superpowers/mockups/2026-07-23-chips-v3-final.html（定案版）
實作計畫：docs/superpowers/plans/2026-07-29-chips-headline-and-holder-redesign.md

候選觀察卡片資料源是既有 screener/institutional.py::rank_joint_buy_candidates()（跟
export/chips_generator.py::_build_section6() 的「法人同步買超觀察」完整榜單同一份資料，
只是這裡只取前3名、用更大的視覺呈現），不是重新設計一套排序邏輯。

⚠️ 誠實揭露原則：候選觀察是條件篩選出的觀察名單，籌碼策略的配對組/bootstrap/樣本外驗證
（見 debug-tasks.md「桌電待驗：籌碼策略是否真的有增益」）都還沒做完，UI 文案不能暗示這是
已證實有效的投資建議。render_headline_zone() 的揭露文字是強制項，修改時不要拿掉。
"""
from html import escape as _html_escape

from screener.institutional import rank_joint_buy_candidates


def _esc(value) -> str:
    return _html_escape(str(value)) if value else ""


def build_candidate_cards(inst_scan: list[dict], limit: int = 3) -> list[dict]:
    """候選觀察卡片資料，直接沿用 rank_joint_buy_candidates() 的排序結果，只是限制筆數
    給headline zone用（完整榜單仍在「法人同步觀察」分頁）。"""
    return rank_joint_buy_candidates(inst_scan, limit=limit)


def _candidate_card_html(row: dict, rank: int) -> str:
    price_pct = row.get("change_pct")
    price_pct_str = f"{price_pct:+.1f}%" if price_pct is not None else "─"
    flow_ratio = row.get("institutional_flow_ratio_pct")
    flow_str = f"{flow_ratio:.2f}%" if flow_ratio is not None else "─"
    price_cum = row.get("price_cum_pct")
    price_cum_str = f"{price_cum:+.1f}%" if price_cum is not None else "─"
    both_streak = row.get("both_streak") or 0
    total_net = row.get("total_net") or 0
    total_net_lots = round(total_net / 1000)

    cls = "primary" if rank == 1 else ""
    return f"""<div class="pick-row {cls}">
  <span class="pr-rank">{rank}</span>
  <div>
    <span class="pr-name">{_esc(row.get('stock_name', ''))}<span class="pr-sid">{_esc(row['stock_id'])}</span></span>
    <div class="pr-evidence">{_esc(row.get('meta_sector', ''))} · 連買{both_streak}日 · 淨買{total_net_lots:+,}張 · 買超占量{flow_str}</div>
  </div>
  <div class="pr-pct">{price_cum_str}<span class="lbl">10日</span></div>
</div>"""


def render_headline_zone(candidate_cards: list[dict], holder_focus: list[dict]) -> str:
    """組裝完整的「今日焦點」headline zone：候選觀察 + 大戶持倉本週焦點，兩欄並排。"""
    if not candidate_cards:
        candidate_html = '<div class="detail-empty">今日無符合條件的候選（篩選條件：連買≥2日、成交量≥500張、買超占量≥0.1%、10日價格不弱於0%）</div>'
    else:
        candidate_html = "".join(
            _candidate_card_html(row, i + 1) for i, row in enumerate(candidate_cards)
        )

    if not holder_focus:
        holder_html = '<div class="detail-empty">今日無資料</div>'
    else:
        rows_html = []
        for row in holder_focus[:5]:
            week_chg = row.get("week_chg") or 0.0
            direction = "up" if week_chg >= 0 else "down"
            max_abs = max((abs(r.get("week_chg") or 0) for r in holder_focus[:5]), default=1.0) or 1.0
            bar_pct = abs(week_chg) / max_abs * 50
            rows_html.append(f"""<div class="holder-mini-row">
  <span class="hm-name">{_esc(row.get('stock_name', ''))}</span>
  <div class="hm-divbar"><span class="{direction}" style="width:{bar_pct:.1f}%"></span></div>
  <span class="hm-delta {direction}">{week_chg:+.1f}%</span>
  <span class="hm-abs">{row.get('lv12_15_pct', 0):.1f}%</span>
</div>""")
        holder_html = "".join(rows_html)

    return f"""<div class="hero">
  <div class="hero-panel">
    <div class="hero-head"><h2>候選觀察</h2><span class="count">法人同步觀察 · {len(candidate_cards)}檔</span></div>
    <div class="disclosure"><span><b>條件篩選觀察名單，不是投資建議。</b>排序邏輯尚未完成配對組／統計顯著性驗證，命中率無法保證優於隨機選股。</span></div>
    {candidate_html}
    <div class="hero-footnote">篩選條件：連買≥2日、成交量≥500張、買超占量≥0.1%、10日價格不弱於0%。完整榜單見「法人同步觀察」分頁。</div>
  </div>
  <div class="hero-panel">
    <div class="hero-head"><h2>大戶持倉本週焦點</h2><span class="count">400張以上大戶% 週變化 Top5</span></div>
    {holder_html}
    <div class="hero-footnote">完整增倉/減倉榜單見「大戶籌碼」分頁。</div>
  </div>
</div>"""
