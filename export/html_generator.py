import pandas as pd
from pathlib import Path
from datetime import date
from config import classify_sector, SECTOR_GROUPS


def _pct_color(pct: float) -> str:
    """漲跌幅強弱對應不同深淺顏色（台灣：漲紅跌綠）"""
    abs_pct = abs(pct)
    if pct > 0:
        if abs_pct >= 7:   return "#ff2d2d"
        if abs_pct >= 5:   return "#f54040"
        if abs_pct >= 3:   return "#e85555"
        if abs_pct >= 1.5: return "#d97070"
        return "#c49090"
    elif pct < 0:
        if abs_pct >= 7:   return "#00d966"
        if abs_pct >= 5:   return "#00c255"
        if abs_pct >= 3:   return "#00aa44"
        if abs_pct >= 1.5: return "#009933"
        return "#007722"
    return "#64748b"


def _pct_cell(pct: float, large: bool = False) -> str:
    sign = "+" if pct >= 0 else ""
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "─")
    color = _pct_color(pct)
    size = "font-size:1.5rem;font-weight:800" if large else "font-size:.9rem;font-weight:700"
    return f'<span style="color:{color};{size};white-space:nowrap">{arrow} {sign}{pct:.2f}%</span>'


def _heatmap_bg(pct: float) -> str:
    abs_pct = abs(pct)
    if pct > 0:
        if abs_pct >= 5:   return "rgba(220,38,38,.85)"
        if abs_pct >= 3:   return "rgba(220,38,38,.6)"
        if abs_pct >= 1.5: return "rgba(220,38,38,.38)"
        if abs_pct >= 0.5: return "rgba(220,38,38,.2)"
        return "rgba(220,38,38,.1)"
    elif pct < 0:
        if abs_pct >= 5:   return "rgba(22,163,74,.85)"
        if abs_pct >= 3:   return "rgba(22,163,74,.6)"
        if abs_pct >= 1.5: return "rgba(22,163,74,.38)"
        if abs_pct >= 0.5: return "rgba(22,163,74,.2)"
        return "rgba(22,163,74,.1)"
    return "rgba(100,116,139,.15)"


def _breadth(meta_perf: list) -> str:
    if not meta_perf:
        return ""
    total = len(meta_perf)
    up   = sum(1 for r in meta_perf if r["avg_change_pct"] > 0)
    dn   = sum(1 for r in meta_perf if r["avg_change_pct"] < 0)
    flat = total - up - dn
    best  = max(meta_perf, key=lambda r: r["avg_change_pct"])
    worst = min(meta_perf, key=lambda r: r["avg_change_pct"])
    b_s = "+" if best["avg_change_pct"] >= 0 else ""
    w_s = "+" if worst["avg_change_pct"] >= 0 else ""
    up_w = round(up / total * 100)
    dn_w = round(dn / total * 100)
    fl_w = 100 - up_w - dn_w
    def bar(w, color):
        return f'<div style="width:{w}%;background:{color};height:100%;border-radius:2px"></div>'
    return (
        f'<div class="breadth">'
        f'<div class="br-bars">'
        f'<div class="br-row"><span class="br-lbl up-c">上漲 {up}</span>'
        f'<div class="br-track">{bar(up_w,"#b91c1c")}</div></div>'
        f'<div class="br-row"><span class="br-lbl dn-c">下跌 {dn}</span>'
        f'<div class="br-track">{bar(dn_w,"#15803d")}</div></div>'
        f'<div class="br-row"><span class="br-lbl fl-c">平盤 {flat}</span>'
        f'<div class="br-track">{bar(fl_w,"#334155")}</div></div>'
        f'</div>'
        f'<div class="br-ext">'
        f'<span>最強 <b style="color:#f87171">{best["meta_name"]}</b>'
        f' <span style="color:#f87171">{b_s}{best["avg_change_pct"]:.2f}%</span></span>'
        f'<span>最弱 <b style="color:#4ade80">{worst["meta_name"]}</b>'
        f' <span style="color:#4ade80">{w_s}{worst["avg_change_pct"]:.2f}%</span></span>'
        f'</div>'
        f'</div>'
    )


def _bar(up: int, down: int, flat: int) -> str:
    total = up + down + flat or 1
    w_up = int(up / total * 60)
    w_dn = int(down / total * 60)
    w_fl = max(0, 60 - w_up - w_dn)
    return (
        f'<span style="display:inline-block;height:6px;width:{w_up}px;background:#d97070;border-radius:2px 0 0 2px;vertical-align:middle"></span>'
        f'<span style="display:inline-block;height:6px;width:{w_dn}px;background:#009933;vertical-align:middle"></span>'
        f'<span style="display:inline-block;height:6px;width:{w_fl}px;background:#1e293b;border-radius:0 2px 2px 0;vertical-align:middle"></span>'
    )


def _fmt_price(val: float) -> str:
    if val >= 100 and val == int(val):
        return f"{int(val):,}"
    return f"{val:.2f}"


def _fmt_chips_num(val) -> str:
    """籌碼數字格式化：1,234,567 → +1,234K 或 -234K"""
    try:
        n = int(val)
        if n == 0:
            return "<span style='color:#475569'>─</span>"
        k = n // 1000
        sign = "+" if n > 0 else ""
        color = "#f87171" if n > 0 else "#4ade80"
        return f"<span style='color:{color}'>{sign}{k:,}K</span>"
    except (TypeError, ValueError):
        return "<span style='color:#334155'>-</span>"


def _fmt_margin(balance, change) -> str:
    """融資餘額 + 增減"""
    try:
        b = int(balance)
        c = int(change)
        sign = "+" if c > 0 else ""
        color = "#f87171" if c > 0 else ("#4ade80" if c < 0 else "#475569")
        arrow = "↑" if c > 0 else ("↓" if c < 0 else "─")
        return f"{b:,} <span style='color:{color};font-size:.75rem'>{arrow}{sign}{c:,}</span>"
    except (TypeError, ValueError):
        return "-"


def _stock_cards(sector_name: str, sectors_df: pd.DataFrame, prices_df: pd.DataFrame, chips_df: pd.DataFrame = None) -> str:
    if sectors_df is None or prices_df is None:
        return ""
    sector_stocks = sectors_df[sectors_df["sector_name"] == sector_name]
    if sector_stocks.empty:
        return ""

    name_map = dict(zip(
        sector_stocks["stock_id"].astype(str),
        sector_stocks["stock_name"].astype(str)
    ))
    prices_map = prices_df.set_index("stock_id") if not prices_df.empty else pd.DataFrame()
    chips_map = chips_df.set_index("stock_id") if chips_df is not None and not chips_df.empty else pd.DataFrame()

    cards = []
    for sid in sorted(name_map.keys()):
        stock_name = name_map[sid]
        if sid in prices_map.index:
            p = prices_map.loc[sid]
            close = float(p["close"])
            pct = float(p["change_pct"])
            vol = int(p["volume"])
            color = _pct_color(pct)
            sign = "+" if pct >= 0 else ""
            arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "─")

            # 籌碼區塊
            chips_html = ""
            if sid in chips_map.index:
                c = chips_map.loc[sid]
                foreign = _fmt_chips_num(c.get("foreign_net"))
                trust = _fmt_chips_num(c.get("trust_net"))
                margin = _fmt_margin(c.get("margin_balance"), c.get("margin_change"))
                chips_html = (
                    f'<div class="sc-chips">'
                    f'<span class="chip-label">外資</span>{foreign} '
                    f'<span class="chip-label">投信</span>{trust}'
                    f'</div>'
                    f'<div class="sc-chips">'
                    f'<span class="chip-label">融資</span>{margin}'
                    f'</div>'
                )

            cards.append(
                f'<div class="stock-card" style="border-color:{color}33">'
                f'<div class="sc-header">'
                f'<span class="sc-id">{sid}</span>'
                f'<span class="sc-name">{stock_name}</span>'
                f'</div>'
                f'<div class="sc-body">'
                f'<span class="sc-price">{_fmt_price(close)}</span>'
                f'<span class="sc-pct" style="color:{color}">{arrow} {sign}{pct:.2f}%</span>'
                f'</div>'
                f'<div class="sc-vol">{vol:,} 張</div>'
                f'{chips_html}'
                f'</div>'
            )
        else:
            cards.append(
                f'<div class="stock-card no-data">'
                f'<div class="sc-header">'
                f'<span class="sc-id">{sid}</span>'
                f'<span class="sc-name">{stock_name}</span>'
                f'</div>'
                f'<div class="sc-body"><span class="sc-price" style="color:#334155">無行情</span></div>'
                f'</div>'
            )

    return (
        f'<tr class="detail-row" style="display:none">'
        f'<td colspan="4">'
        f'<div class="stock-cards-wrap">{"".join(cards)}</div>'
        f'</td></tr>'
    )


def _sector_row(row, sectors_df=None, prices_df=None, chips_df=None, compact=False) -> str:
    pct = row["avg_change_pct"]
    up, down, flat = int(row["up_count"]), int(row["down_count"]), int(row["flat_count"])
    detail = _stock_cards(row["sector_name"], sectors_df, prices_df, chips_df)
    has_detail = bool(detail)

    chevron = '<span class="chevron">›</span>' if has_detail else ""
    clickable = ' class="clickable-sector"' if has_detail else ""
    onclick = ' onclick="toggleDetail(this)"' if has_detail else ""

    return (
        f'<tr{clickable}{onclick}>'
        f'<td class="name">{row["sector_name"]}{chevron}</td>'
        f'<td>{_pct_cell(pct)}</td>'
        f'<td><span class="cnt" style="color:#f87171">▲{up}</span> '
        f'<span class="cnt" style="color:#4ade80">▼{down}</span> '
        f'<span class="cnt" style="color:#475569">─{flat}</span></td>'
        f'<td class="bar-cell">{_bar(up, down, flat)}</td>'
        f'</tr>'
        + detail
    )


def _top10_card(row, rank: int, sectors_df=None, prices_df=None, chips_df=None) -> str:
    pct = row["avg_change_pct"]
    up, down, flat = int(row["up_count"]), int(row["down_count"]), int(row["flat_count"])
    detail = _stock_cards(row["sector_name"], sectors_df, prices_df, chips_df)
    has_detail = bool(detail)
    onclick = ' onclick="toggleDetail(this)"' if has_detail else ""
    chevron = '<span class="chevron">›</span>' if has_detail else ""
    color = _pct_color(pct)

    return (
        f'<tr class="top-row clickable-sector"{onclick}>'
        f'<td class="top-rank" style="color:{color}">{rank}</td>'
        f'<td class="top-name">{row["sector_name"]}{chevron}</td>'
        f'<td class="top-pct">{_pct_cell(pct, large=True)}</td>'
        f'<td class="top-counts">'
        f'<span style="color:#f87171">▲{up}</span> '
        f'<span style="color:#4ade80">▼{down}</span>'
        f'</td>'
        f'</tr>'
        + detail
    )


def _meta_stock_cards(sub_names: list, sectors_df, prices_df, chips_df=None,
                      universe_df=None, stock_ids: list = None, as_row: bool = True) -> str:
    """合併所有子族群的個股卡片。
    若傳入 universe_df + stock_ids，直接從 universe 查詢（無重複）；
    否則 fallback 到舊的 sectors_df + sub_names 查詢。
    """
    if prices_df is None:
        return ""

    if universe_df is not None and stock_ids is not None:
        sub_df = universe_df[universe_df["stock_id"].astype(str).isin(
            [str(s) for s in stock_ids]
        )]
        if sub_df.empty:
            return ""
        name_map = dict(zip(sub_df["stock_id"].astype(str), sub_df["stock_name"].astype(str)))
    elif sectors_df is not None:
        sub_df = sectors_df[sectors_df["sector_name"].isin(sub_names)]
        if sub_df.empty:
            return ""
        name_map = dict(zip(sub_df["stock_id"].astype(str), sub_df["stock_name"].astype(str)))
    else:
        return ""
    prices_map = prices_df.set_index("stock_id") if not prices_df.empty else pd.DataFrame()
    chips_map = chips_df.set_index("stock_id") if chips_df is not None and not chips_df.empty else pd.DataFrame()

    cards = []
    for sid in sorted(name_map.keys()):
        stock_name = name_map[sid]
        if sid in prices_map.index:
            p = prices_map.loc[sid]
            close = float(p["close"])
            pct = float(p["change_pct"])
            vol = int(p["volume"])
            color = _pct_color(pct)
            sign = "+" if pct >= 0 else ""
            arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "─")

            chips_html = ""
            if sid in chips_map.index:
                c = chips_map.loc[sid]
                foreign = _fmt_chips_num(c.get("foreign_net"))
                trust = _fmt_chips_num(c.get("trust_net"))
                margin = _fmt_margin(c.get("margin_balance"), c.get("margin_change"))
                chips_html = (
                    f'<div class="sc-chips">'
                    f'<span class="chip-label">外資</span>{foreign} '
                    f'<span class="chip-label">投信</span>{trust}'
                    f'</div>'
                    f'<div class="sc-chips">'
                    f'<span class="chip-label">融資</span>{margin}'
                    f'</div>'
                )

            cards.append(
                f'<div class="stock-card" style="border-color:{color}33">'
                f'<div class="sc-header">'
                f'<span class="sc-id">{sid}</span>'
                f'<span class="sc-name">{stock_name}</span>'
                f'</div>'
                f'<div class="sc-body">'
                f'<span class="sc-price">{_fmt_price(close)}</span>'
                f'<span class="sc-pct" style="color:{color}">{arrow} {sign}{pct:.2f}%</span>'
                f'</div>'
                f'<div class="sc-vol">{vol:,} 張</div>'
                f'{chips_html}'
                f'</div>'
            )
        else:
            cards.append(
                f'<div class="stock-card no-data">'
                f'<div class="sc-header">'
                f'<span class="sc-id">{sid}</span>'
                f'<span class="sc-name">{stock_name}</span>'
                f'</div>'
                f'<div class="sc-body"><span class="sc-price" style="color:#334155">無行情</span></div>'
                f'</div>'
            )

    cards_html = f'<div class="stock-cards-wrap">{"".join(cards)}</div>'
    if not as_row:
        return cards_html
    return (
        f'<tr class="detail-row" style="display:none">'
        f'<td colspan="4">{cards_html}</td></tr>'
    )


def _meta_card(row: dict, rank: int, card_id: str, sectors_df=None, prices_df=None,
               chips_df=None, universe_df=None) -> tuple:
    """小卡片，回傳 (card_html, panel_html)"""
    pct = row["avg_change_pct"]
    up, down = int(row["up_count"]), int(row["down_count"])
    color = _pct_color(pct)
    bg = _heatmap_bg(pct)
    sign = "+" if pct >= 0 else ""
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "─")

    detail_inner = _meta_stock_cards(
        row["sub_names"], sectors_df, prices_df, chips_df,
        universe_df=universe_df, stock_ids=row.get("stock_ids"), as_row=False,
    )
    onclick = f' onclick="selectMeta(\'{card_id}\')"' if detail_inner else ""

    card = (
        f'<div class="mc-card" data-meta="{card_id}"'
        f' style="border-top:2px solid {color};background:{bg}"{onclick}>'
        f'<div class="mc-hd">'
        f'<span class="mc-rank">#{rank}</span>'
        f'<span class="mc-pct" style="color:{color}">{arrow}{sign}{pct:.2f}%</span>'
        f'</div>'
        f'<div class="mc-name">{row["meta_name"]}</div>'
        f'<div class="mc-cnt">'
        f'<span style="color:#f87171">▲{up}</span> '
        f'<span style="color:#4ade80">▼{down}</span>'
        f'</div>'
        f'</div>'
    )
    panel = (
        f'<div class="mc-panel" id="{card_id}" style="display:none">{detail_inner}</div>'
        if detail_inner else ""
    )
    return card, panel


def generate(
    trade_date: date,
    perf_df: pd.DataFrame,
    sectors_df: pd.DataFrame = None,
    prices_df: pd.DataFrame = None,
    chips_df: pd.DataFrame = None,
    meta_perf: list = None,
    universe_df: pd.DataFrame = None,
    output_path: str = "docs/index.html",
) -> None:
    if perf_df.empty and not meta_perf:
        return

    if sectors_df is not None and not sectors_df.empty:
        sectors_df = sectors_df.copy()
        sectors_df["stock_id"] = sectors_df["stock_id"].astype(str)
    if prices_df is not None and not prices_df.empty:
        prices_df = prices_df.copy()
        prices_df["stock_id"] = prices_df["stock_id"].astype(str)

    df = perf_df.sort_values("avg_change_pct", ascending=False).reset_index(drop=True) if not perf_df.empty else pd.DataFrame()
    date_str = trade_date.strftime("%Y-%m-%d")
    weekday = ["一", "二", "三", "四", "五", "六", "日"][trade_date.weekday()]

    if not df.empty:
        total = len(df)
        up_cnt = int((df["avg_change_pct"] > 0).sum())
        dn_cnt = int((df["avg_change_pct"] < 0).sum())
        flat_cnt = total - up_cnt - dn_cnt
        mkt_avg = df["avg_change_pct"].mean()
    elif meta_perf:
        total = len(meta_perf)
        up_cnt = sum(1 for r in meta_perf if r["avg_change_pct"] > 0)
        dn_cnt = sum(1 for r in meta_perf if r["avg_change_pct"] < 0)
        flat_cnt = total - up_cnt - dn_cnt
        mkt_avg = sum(r["avg_change_pct"] for r in meta_perf) / total
    else:
        total = up_cnt = dn_cnt = flat_cnt = 0
        mkt_avg = 0.0
    mkt_color = _pct_color(mkt_avg)
    mkt_sign = "+" if mkt_avg >= 0 else ""

    # 廣度儀表板
    breadth_html = _breadth(meta_perf) if meta_perf else ""

    # Top10 / Bottom10
    if meta_perf:
        meta_sorted = sorted(meta_perf, key=lambda r: r["avg_change_pct"], reverse=True)
        top_source = meta_sorted[:10]
        bot_source = list(reversed(meta_sorted))[:10]

        top_cards, top_panels = [], []
        for i, r in enumerate(top_source):
            c, p = _meta_card(r, i+1, f"t{i}", sectors_df, prices_df, chips_df, universe_df)
            top_cards.append(c); top_panels.append(p)

        bot_cards, bot_panels = [], []
        for i, r in enumerate(bot_source):
            c, p = _meta_card(r, i+1, f"b{i}", sectors_df, prices_df, chips_df, universe_df)
            bot_cards.append(c); bot_panels.append(p)

        top10_block = (
            f'<div class="mc-label up-label">▲ 漲幅 Top 10</div>'
            f'<div class="mc-grid">{"".join(top_cards)}</div>'
            f'{"".join(top_panels)}'
        )
        bot10_block = (
            f'<div class="mc-label dn-label">▼ 跌幅 Top 10</div>'
            f'<div class="mc-grid">{"".join(bot_cards)}</div>'
            f'{"".join(bot_panels)}'
        )
        top_section_inner = f'{top10_block}<div style="margin-top:10px">{bot10_block}</div>'
    else:
        top10_html = "".join(_top10_card(r, i+1, sectors_df, prices_df, chips_df) for i, (_, r) in enumerate(df.head(10).iterrows()))
        bot10_html = "".join(_top10_card(r, i+1, sectors_df, prices_df, chips_df) for i, (_, r) in enumerate(df.tail(10).iloc[::-1].iterrows()))
        top_section_inner = (
            f'<div class="top-card"><div class="top-card-title up-title">▲ 今日漲幅 Top 10</div><table><tbody>{top10_html}</tbody></table></div>'
            f'<div class="top-card"><div class="top-card-title down-title">▼ 今日跌幅 Top 10</div><table><tbody>{bot10_html}</tbody></table></div>'
        )

    # Groups
    groups_html = ""
    if not df.empty:
        df["group"] = df["sector_name"].apply(classify_sector)
    for group_name, _ in (SECTOR_GROUPS if not df.empty else []):
        subset = df[df["group"] == group_name].copy()
        if subset.empty:
            continue
        count = len(subset)
        avg = subset["avg_change_pct"].mean()
        g_color = _pct_color(avg)
        sign = "+" if avg >= 0 else ""

        preview_rows = "".join(_sector_row(r, sectors_df, prices_df, chips_df) for _, r in subset.head(3).iterrows())
        rest = subset.iloc[3:]
        rest_rows = "".join(_sector_row(r, sectors_df, prices_df, chips_df) for _, r in rest.iterrows()) if not rest.empty else ""
        expand_btn = (
            f'<button class="expand-btn" onclick="toggleGroup(this)">展開全部（{count}）<span style="font-size:.8rem">⌄</span></button>'
            if not rest.empty else ""
        )

        groups_html += f"""
<details class="group-block">
  <summary class="group-header">
    <span class="g-chevron">›</span>
    <span class="g-name">{group_name}</span>
    <span class="g-avg" style="color:{g_color}">{sign}{avg:.2f}%</span>
    <span class="g-count">{count} 族群</span>
  </summary>
  <table class="sector-table">
    <thead><tr><th>族群</th><th>漲跌幅</th><th>漲跌平</th><th>分布</th></tr></thead>
    <tbody class="preview-rows">{preview_rows}</tbody>
    <tbody class="rest-rows" style="display:none">{rest_rows}</tbody>
  </table>
  {f'<div class="group-footer">{expand_btn}</div>' if expand_btn else ''}
</details>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>台股電子族群 {date_str}</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,"Segoe UI",sans-serif;background:#0b0f18;color:#e2e8f0;padding:12px 20px}}

    /* Header */
    .header{{margin-bottom:24px}}
    h1{{font-size:1.1rem;font-weight:600;color:#94a3b8;letter-spacing:.05em;text-transform:uppercase}}
    .mkt-bar{{display:flex;align-items:center;gap:20px;margin-top:8px;padding:12px 16px;background:#141c2e;border-radius:10px;flex-wrap:wrap}}
    .mkt-date{{font-size:1rem;font-weight:600;color:#f1f5f9}}
    .mkt-avg{{font-size:1.3rem;font-weight:800;color:{mkt_color}}}
    .mkt-stat{{font-size:.82rem;color:#64748b}}
    .mkt-stat span{{font-weight:600}}

    /* 廣度儀表板 */
    .breadth{{display:flex;align-items:center;gap:24px;padding:10px 14px;background:#0f1624;border:1px solid #1e293b;border-radius:10px;margin-bottom:14px;flex-wrap:wrap}}
    .br-bars{{display:flex;flex-direction:column;gap:5px;flex:1;min-width:200px}}
    .br-row{{display:flex;align-items:center;gap:8px}}
    .br-lbl{{font-size:.72rem;font-weight:600;min-width:52px}}
    .br-track{{flex:1;height:6px;background:#1e293b;border-radius:3px;overflow:hidden}}
    .up-c{{color:#f87171}} .dn-c{{color:#4ade80}} .fl-c{{color:#475569}}
    .br-ext{{display:flex;flex-direction:column;gap:4px;font-size:.78rem;color:#94a3b8}}

    /* Top10 小卡片 */
    .top-section{{margin-bottom:24px}}
    .mc-label{{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;margin-bottom:6px}}
    .up-label{{color:#f87171}} .dn-label{{color:#4ade80}}
    .mc-grid{{display:grid;grid-template-columns:repeat(10,1fr);gap:5px}}
    @media(max-width:1000px){{.mc-grid{{grid-template-columns:repeat(5,1fr)}}}}
    @media(max-width:540px){{.mc-grid{{grid-template-columns:repeat(3,1fr)}}}}
    .mc-card{{padding:8px 10px;border-radius:8px;border:1px solid #1e293b;cursor:pointer;transition:filter .12s}}
    .mc-card:hover,.mc-card.active{{filter:brightness(1.15);border-color:#475569}}
    .mc-hd{{display:flex;align-items:center;justify-content:space-between;margin-bottom:3px}}
    .mc-rank{{font-size:.6rem;color:#475569;font-weight:600}}
    .mc-pct{{font-size:.88rem;font-weight:800}}
    .mc-name{{font-size:.72rem;color:#94a3b8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:3px}}
    .mc-cnt{{font-size:.65rem;color:#64748b}}
    .mc-panel{{background:#070b12;border:1px solid #1e293b;border-radius:8px;padding:12px 16px;margin-top:5px}}

    /* Fallback table Top10 */
    .top-card{{background:#0f1624;border:1px solid #1e293b;border-radius:12px;overflow:hidden;margin-bottom:10px}}
    .top-card-title{{padding:10px 16px;font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;border-bottom:1px solid #1e293b}}
    .up-title{{color:#d97070}} .down-title{{color:#009933}}
    .top-row{{cursor:pointer}} .top-row:hover > td{{background:#1a2235}}
    .top-rank{{width:28px;padding:10px 0 10px 14px;font-size:.75rem;font-weight:700;color:#334155;text-align:center}}
    .top-name{{padding:10px 8px;font-size:.88rem;font-weight:500;color:#cbd5e1;max-width:120px}}
    .top-pct{{padding:10px 8px;text-align:right}}
    .top-counts{{padding:10px 14px 10px 4px;font-size:.75rem;white-space:nowrap;color:#64748b;text-align:right}}

    /* Chevron */
    .chevron{{font-size:1rem;color:#334155;margin-left:4px;display:inline-block;transition:transform .2s;vertical-align:middle}}
    .clickable-sector.open .chevron{{transform:rotate(90deg)}}
    .g-chevron{{font-size:1.1rem;color:#475569;margin-right:2px;transition:transform .2s;display:inline-block}}
    details[open] .g-chevron{{transform:rotate(90deg)}}

    /* Sector table */
    table{{width:100%;border-collapse:collapse}}
    th{{text-align:left;padding:6px 12px;font-size:.7rem;color:#475569;text-transform:uppercase;border-bottom:1px solid #1e293b}}
    td{{padding:9px 12px;border-bottom:1px solid #0b0f18;font-size:.85rem}}
    .name{{font-weight:500;color:#e2e8f0;max-width:160px}}
    .cnt{{font-size:.78rem;margin-right:4px}}
    .bar-cell{{width:70px}}
    .clickable-sector{{cursor:pointer}}
    .clickable-sector:hover > td{{background:#141c2e}}

    /* Stock cards */
    .detail-row > td{{padding:12px 16px;background:#070b12}}
    .stock-cards-wrap{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}}
    .stock-card{{background:#0f1624;border:1px solid #1e293b;border-radius:8px;padding:10px 12px;transition:border-color .15s}}
    .stock-card:hover{{border-color:#334155}}
    .no-data{{opacity:.5}}
    .sc-header{{display:flex;align-items:baseline;gap:6px;margin-bottom:6px}}
    .sc-id{{font-size:.72rem;color:#475569;font-weight:600}}
    .sc-name{{font-size:.82rem;color:#94a3b8;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
    .sc-body{{display:flex;align-items:baseline;justify-content:space-between;gap:6px;margin-bottom:4px}}
    .sc-price{{font-size:1rem;font-weight:700;color:#f1f5f9}}
    .sc-pct{{font-size:.82rem;font-weight:700}}
    .sc-vol{{font-size:.7rem;color:#334155}}
    .sc-chips{{font-size:.72rem;color:#64748b;margin-top:4px;line-height:1.6}}
    .chip-label{{color:#334155;margin-right:2px}}

    /* Groups */
    .section-bar{{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}}
    .groups-grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px;align-items:start}}
    @media(max-width:900px){{.groups-grid{{grid-template-columns:1fr}}}}
    .section-title{{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;color:#475569}}
    .collapse-all-btn{{background:none;border:1px solid #1e293b;color:#475569;padding:4px 12px;border-radius:6px;cursor:pointer;font-size:.75rem;transition:all .15s}}
    .collapse-all-btn:hover{{border-color:#334155;color:#94a3b8}}
    .group-block{{border:1px solid #1e293b;border-radius:10px;margin-bottom:8px;overflow:hidden}}
    .group-header{{display:flex;align-items:center;gap:10px;padding:11px 16px;cursor:pointer;list-style:none;background:#0f1624;user-select:none}}
    .group-header:hover{{background:#141c2e}}
    .group-header::-webkit-details-marker{{display:none}}
    details[open] > .group-header{{border-bottom:1px solid #1e293b}}
    .g-name{{font-weight:600;color:#e2e8f0;flex:1;font-size:.9rem}}
    .g-avg{{font-weight:800;font-size:1rem}}
    .g-count{{font-size:.72rem;color:#334155}}
    .sector-table td,.sector-table th{{padding:8px 16px}}
    .group-footer{{padding:8px 16px;text-align:right;background:#0b0f18}}
    .expand-btn{{background:none;border:1px solid #1e293b;color:#475569;padding:5px 14px;border-radius:6px;cursor:pointer;font-size:.78rem;transition:all .15s}}
    .expand-btn:hover{{border-color:#334155;color:#94a3b8}}

    .footer{{margin-top:28px;font-size:.7rem;color:#1e293b;text-align:center;padding-bottom:20px}}

    /* ── RWD Mobile ── */
    @media(max-width:540px){{
      body{{padding:12px}}
      h1{{font-size:.95rem}}
      .mkt-bar{{gap:12px;padding:10px 12px}}
      .mkt-avg{{font-size:1.1rem}}
      .mkt-stat{{font-size:.75rem}}

      /* Top 10: 隱藏漲跌平欄 */
      .top-counts{{display:none}}
      .top-pct{{padding:10px 10px 10px 4px}}
      .top-name{{font-size:.82rem;max-width:none}}

      /* 族群表: 隱藏分布欄，漲跌平縮小 */
      .bar-cell{{display:none}}
      th:last-child{{display:none}}
      .cnt{{font-size:.72rem}}
      .sector-table td,.sector-table th{{padding:7px 10px}}

      /* 個股 card: 固定2欄 */
      .stock-cards-wrap{{grid-template-columns:1fr 1fr;gap:8px}}
      .sc-price{{font-size:.9rem}}
      .sc-pct{{font-size:.75rem}}

      /* 分組 */
      .group-header{{padding:10px 12px}}
      .g-name{{font-size:.85rem}}
      .g-avg{{font-size:.9rem}}
      .g-count{{display:none}}
    }}
  </style>
</head>
<body>
  <div class="header">
    <h1>台股電子半導體族群追蹤</h1>
    <div class="mkt-bar">
      <span class="mkt-date">📅 {date_str}（週{weekday}）</span>
      <span class="mkt-avg">{mkt_sign}{mkt_avg:.2f}%</span>
      <span class="mkt-stat">上漲 <span style="color:#d97070">{up_cnt}</span></span>
      <span class="mkt-stat">下跌 <span style="color:#009933">{dn_cnt}</span></span>
      <span class="mkt-stat">平盤 <span style="color:#475569">{flat_cnt}</span></span>
    </div>
  </div>

  {breadth_html}
  <div class="top-section">{top_section_inner}</div>

  <div class="section-bar">
    <span class="section-title">所有族群 / 依分類</span>
    <button class="collapse-all-btn" onclick="collapseAll()">⊟ 全部收合</button>
  </div>
  <div class="groups-grid">{groups_html}</div>

  <div class="footer">點擊族群名稱可展開個股 ｜ 台灣：漲紅跌綠</div>

  <script>
    function selectMeta(id) {{
      const panel = document.getElementById(id);
      const isOpen = panel && panel.style.display !== 'none';
      document.querySelectorAll('.mc-panel').forEach(p => p.style.display = 'none');
      document.querySelectorAll('.mc-card.active').forEach(c => c.classList.remove('active'));
      if (!isOpen && panel) {{
        panel.style.display = '';
        document.querySelector('[data-meta="' + id + '"]').classList.add('active');
      }}
    }}
    function toggleDetail(row) {{
      const next = row.nextElementSibling;
      if (!next || !next.classList.contains('detail-row')) return;
      const open = next.style.display !== 'none';
      next.style.display = open ? 'none' : '';
      row.classList.toggle('open', !open);
    }}
    function toggleGroup(btn) {{
      const rest = btn.closest('.group-block').querySelector('.rest-rows');
      const open = rest.style.display !== 'none';
      rest.style.display = open ? 'none' : '';
      btn.innerHTML = open ? '展開全部 <span style="font-size:.8rem">⌄</span>' : '收合 <span style="font-size:.8rem">⌃</span>';
    }}
    function collapseAll() {{
      // 收合所有 <details> 分組
      document.querySelectorAll('details.group-block').forEach(d => d.open = false);
      // 收合所有展開的個股
      document.querySelectorAll('.detail-row').forEach(r => r.style.display = 'none');
      document.querySelectorAll('.clickable-sector.open').forEach(r => r.classList.remove('open'));
      // 重置展開按鈕文字
      document.querySelectorAll('.expand-btn').forEach(btn => {{
        btn.innerHTML = btn.innerHTML.replace('收合', '展開全部').replace('⌃', '⌄');
      }});
    }}
  </script>
</body>
</html>"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
