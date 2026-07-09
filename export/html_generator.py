import json
import pandas as pd
from html import escape as _html_escape
from pathlib import Path
from datetime import date
from config import classify_sector, SECTOR_GROUPS


def _na(v):
    return 0 if (v is None or pd.isna(v)) else v


def _esc(value) -> str:
    """HTML-escape 外部資料（股票名稱/族群名稱等來自 TWSE/TPEx API 回應的字串），
    避免被竄改的回應內容注入進發布到 GitHub Pages 的 index.html。"""
    return _html_escape(str(value)) if value else ""


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
        if abs_pct >= 5:   return "rgba(127,29,29,.75)"
        if abs_pct >= 3:   return "rgba(127,29,29,.45)"
        if abs_pct >= 1.5: return "rgba(127,29,29,.22)"
        if abs_pct >= 0.5: return "rgba(127,29,29,.10)"
        return "rgba(127,29,29,.05)"
    elif pct < 0:
        if abs_pct >= 5:   return "rgba(6,78,59,.75)"
        if abs_pct >= 3:   return "rgba(6,78,59,.45)"
        if abs_pct >= 1.5: return "rgba(6,78,59,.22)"
        if abs_pct >= 0.5: return "rgba(6,78,59,.10)"
        return "rgba(6,78,59,.05)"
    return "rgba(100,116,139,.12)"


def _make_cum_ranks(cum_data: list) -> dict:
    """建立各時間段的排名 lookup：{meta_name: rank}（1-based），回傳 dict of dicts。"""
    if not cum_data:
        return {"r3": {}, "r5": {}, "r7": {}, "v": {}}
    r3 = {r["meta_name"]: i + 1 for i, r in enumerate(
        sorted(cum_data, key=lambda x: x["cum3"], reverse=True))}
    r5 = {r["meta_name"]: i + 1 for i, r in enumerate(
        sorted(cum_data, key=lambda x: (x["cum5"] if x["cum5"] is not None else -999), reverse=True))}
    r7 = {r["meta_name"]: i + 1 for i, r in enumerate(
        sorted(cum_data, key=lambda x: (x["cum7"] if x["cum7"] is not None else -999), reverse=True))}
    return {"r3": r3, "r5": r5, "r7": r7, "v": {r["meta_name"]: r for r in cum_data}}


def _sparkline(daily_pct: list, dates: list) -> str:
    """近 N 日每日漲跌幅 SVG bar chart，出現在展開面板頂部。"""
    if not daily_pct:
        return ""
    n = len(daily_pct)
    chart_h = 72
    label_h = 13
    h = chart_h + label_h
    mid = chart_h // 2          # zero line y = 36
    max_abs = max(abs(p) for p in daily_pct) or 1
    bar_w = max(8, int(420 / n) - 3)
    gap = 3
    total_w = n * (bar_w + gap) - gap + 24

    bars = []
    labels = []
    for i, (pct, label) in enumerate(zip(daily_pct, dates)):
        x = 12 + i * (bar_w + gap)
        bar_h = max(3, int(abs(pct) / max_abs * (mid - 5)))
        if pct >= 0:
            y = mid - bar_h
            color = "#ef4444" if abs(pct) >= 1 else "#fca5a5"
        else:
            y = mid
            color = "#22c55e" if abs(pct) >= 1 else "#86efac"
        sign = "+" if pct >= 0 else ""
        bars.append(
            f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bar_h}" fill="{color}" rx="2">'
            f'<title>{sign}{pct:.2f}%</title></rect>'
        )
        labels.append(
            f'<text x="{x + bar_w // 2}" y="{h - 1}" text-anchor="middle" '
            f'fill="#64748b" font-size="8">{label}</text>'
        )

    zero_line = (
        f'<line x1="10" y1="{mid}" x2="{total_w - 10}" y2="{mid}" '
        f'stroke="#334155" stroke-width="0.8"/>'
    )
    svg = (
        f'<svg width="{total_w}" height="{h}" xmlns="http://www.w3.org/2000/svg">'
        f'{zero_line}{"".join(bars)}{"".join(labels)}'
        f'</svg>'
    )
    return f'<div class="sparkline-wrap">{svg}</div>'


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


def _weekly_pct(spark: list) -> float:
    """複利計算 sparkline 最後 5 個交易日的週漲跌幅。"""
    if not spark:
        return 0.0
    last5 = spark[-5:]
    result = 1.0
    for p in last5:
        result *= (1 + p / 100)
    return round((result - 1) * 100, 2)


# 近5/7/10/14日累積漲跌幅（收盤價比值法）：{stock_id: {5:pct, 7:.., 10:.., 14:..}}。
# 由 generate() 於頁面產生前一次性塞入（來自 screener.database.get_rolling_returns()），
# _stock_table / _meta_stock_cards 直接讀，避免把此 map 穿過整條 8 層渲染呼叫鏈的參數。
# 跟 chips.html Section 8 用同一個算法（get_rolling_returns），確保兩頁「近N日」一致。
_ROLLING_RETURNS: dict = {}


def _chg_pct_cell(pct) -> str:
    """近N日累積漲跌 <td>：紅漲綠跌、缺值（資料不足/None）顯示「─」。"""
    if pct is None:
        return '<td><span style="color:#334155">─</span></td>'
    color = _pct_color(pct)
    sign = "+" if pct >= 0 else ""
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "─")
    return (f'<td><span style="color:{color};font-weight:700;font-size:1.05rem">'
            f'{arrow} {sign}{pct:.2f}%</span></td>')


_CHIPS_BADGE_MIN = 1_000_000   # 外資/投信股數超過此值才加 badge 框
_TRUST_BADGE_MIN = 500_000

def _fmt_lots_text(k: int, sign: str) -> str:
    """k 為原始股數已除以 1000 的張數，>=10000 張時改顯示「萬張」，跟 chips_generator.py::_fmt_net() 一致。"""
    if abs(k) >= 10000:
        return f"{sign}{k / 10000:.1f}萬張"
    return f"{sign}{k:,}張"


def _fmt_chips_num(val, badge_threshold: int = 0) -> str:
    """籌碼數字格式化：1,234,567 → +1,234張；達門檻時加外框 badge"""
    try:
        n = int(val)
        if n == 0:
            return "<span style='color:#475569'>─</span>"
        k = n // 1000
        sign = "+" if n > 0 else ""
        color = "#f87171" if n > 0 else "#4ade80"
        text = _fmt_lots_text(k, sign)
        if badge_threshold > 0 and abs(n) >= badge_threshold:
            label = "大買" if n > 0 else "大賣"
            return (
                f'<span style="color:{color};background:{"rgba(127,29,29,.18)" if n > 0 else "rgba(6,78,59,.18)"}'
                f';border:1px solid {"rgba(127,29,29,.5)" if n > 0 else "rgba(6,78,59,.5)"}'
                f';border-radius:3px;padding:0 4px;font-size:.7rem;font-weight:700">'
                f'{label}{text}</span>'
            )
        return f"<span style='color:{color}'>{text}</span>"
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


def _stock_card_html(sid: str, stock_name: str, prices_map, chips_map, stock_sparklines: dict = None) -> str:
    """單一個股卡片 HTML（帶 modal data attributes）。"""
    import json as _json
    if sid in prices_map.index:
        p = prices_map.loc[sid]
        close = float(p["close"])
        pct = float(p["change_pct"])
        vol = int(p["volume"])
        color = _pct_color(pct)
        sign = "+" if pct >= 0 else ""
        arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "─")

        # chips data for modal
        chips_data: dict = {}
        chips_html = ""
        if sid in chips_map.index:
            c = chips_map.loc[sid]
            fn = int(_na(c.get("foreign_net")))
            tn = int(_na(c.get("trust_net")))
            mb = int(_na(c.get("margin_balance")))
            mc = int(_na(c.get("margin_change")))
            chips_data = {"foreign": fn, "trust": tn, "marginBal": mb, "marginChg": mc}
            foreign = _fmt_chips_num(c.get("foreign_net"), _CHIPS_BADGE_MIN)
            trust = _fmt_chips_num(c.get("trust_net"), _TRUST_BADGE_MIN)
            margin = _fmt_margin(c.get("margin_balance"), c.get("margin_change"))
            try:
                margin_badge = (
                    f' <span style="font-size:.65rem;color:#fb923c;background:rgba(124,45,18,.25);'
                    f'border:1px solid rgba(124,45,18,.5);border-radius:3px;padding:0 4px">↑{mc/mb*100:.1f}%</span>'
                    if mb > 0 and mc / mb > 0.05 else ""
                )
            except (ZeroDivisionError, TypeError):
                margin_badge = ""
            chips_html = (
                f'<div class="sc-chips">'
                f'<span class="chip-label">外資</span>{foreign} '
                f'<span class="chip-label">投信</span>{trust}'
                f'</div>'
                f'<div class="sc-chips">'
                f'<span class="chip-label">融資</span>{margin}{margin_badge}'
                f'</div>'
            )

        spark = (stock_sparklines or {}).get(sid, [])
        spark_json = _json.dumps(spark)
        chips_json = _json.dumps(chips_data)
        name_safe = _esc(stock_name)

        return (
            f'<div class="stock-card" data-sid="{sid}"'
            f' data-name="{name_safe}" data-close="{close}" data-pct="{pct}" data-vol="{vol}"'
            f' data-sparkline=\'{spark_json}\' data-chips=\'{chips_json}\''
            f' style="border-color:{color}33;cursor:pointer" onclick="openStockModal(this)">'
            f'<div class="sc-header">'
            f'<span class="sc-id">{sid}</span>'
            f'<span class="sc-name">{_esc(stock_name)}</span>'
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
        return (
            f'<div class="stock-card no-data">'
            f'<div class="sc-header">'
            f'<span class="sc-id">{sid}</span>'
            f'<span class="sc-name">{_esc(stock_name)}</span>'
            f'</div>'
            f'<div class="sc-body"><span class="sc-price" style="color:#334155">無行情</span></div>'
            f'</div>'
        )


def _stock_cards(sector_name: str, sectors_df: pd.DataFrame, prices_df: pd.DataFrame,
                 chips_df: pd.DataFrame = None, as_row: bool = True,
                 stock_sparklines: dict = None) -> str:
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

    cards = [_stock_card_html(sid, name_map[sid], prices_map, chips_map, stock_sparklines)
             for sid in sorted(name_map.keys())]

    cards_html = f'<div class="stock-cards-wrap">{"".join(cards)}</div>'
    if as_row:
        return f'<tr class="detail-row" style="display:none"><td colspan="4">{cards_html}</td></tr>'
    return cards_html


def _stock_table(sector_name: str, sectors_df: pd.DataFrame, prices_df: pd.DataFrame,
                 chips_df: pd.DataFrame = None, stock_sparklines: dict = None,
                 as_row: bool = True) -> str:
    """可排序個股列表 table（子族群展開用）。"""
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

    rows_html = []
    for sid in sorted(name_map.keys()):
        stock_name = name_map[sid]
        if sid not in prices_map.index:
            rows_html.append(
                f'<tr>'
                f'<td style="color:#475569;font-size:.78rem">{sid}</td>'
                f'<td style="color:#334155">{_esc(stock_name)}</td>'
                f'<td colspan="9" style="color:#334155;font-size:.75rem">無行情</td>'
                f'</tr>'
            )
            continue

        p = prices_map.loc[sid]
        close = float(p["close"])
        pct = float(p["change_pct"])
        vol = int(p["volume"])
        color = _pct_color(pct)
        sign = "+" if pct >= 0 else ""
        arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "─")

        spark = (stock_sparklines or {}).get(sid, [])
        _rr = _ROLLING_RETURNS.get(sid, {})
        c5, c7, c10, c14 = _rr.get(5), _rr.get(7), _rr.get(10), _rr.get(14)
        _a5 = "" if c5 is None else c5
        _a7 = "" if c7 is None else c7
        _a10 = "" if c10 is None else c10
        _a14 = "" if c14 is None else c14

        fn = tn = mb = mc = 0
        chips_data: dict = {}
        if sid in chips_map.index:
            c = chips_map.loc[sid]
            fn = int(_na(c.get("foreign_net")))
            tn = int(_na(c.get("trust_net")))
            mb = int(_na(c.get("margin_balance")))
            mc = int(_na(c.get("margin_change")))
            chips_data = {"foreign": fn, "trust": tn, "marginBal": mb, "marginChg": mc}

        spark_json = json.dumps(spark)
        chips_json = json.dumps(chips_data)
        name_safe = _esc(stock_name)
        margin_html = _fmt_margin(mb, mc) if mb > 0 else "<span style='color:#334155'>─</span>"

        rows_html.append(
            f'<tr class="st-row" data-sid="{sid}" data-name="{name_safe}"'
            f' data-close="{close}" data-pct="{pct}" data-vol="{vol}"'
            f' data-sparkline=\'{spark_json}\' data-chips=\'{chips_json}\''
            f' data-code="{sid}" data-wpct="{_a5}" data-chg7="{_a7}" data-chg10="{_a10}" data-chg14="{_a14}"'
            f' data-foreign="{fn}" data-trust="{tn}" data-margin="{mb}"'
            f' onclick="openStockModal(this)" style="cursor:pointer">'
            f'<td style="color:#64748b;font-size:.92rem;font-weight:600">{sid}</td>'
            f'<td style="color:#cbd5e1;font-size:1.1rem;font-weight:600">{_esc(stock_name)}</td>'
            f'<td style="color:#f1f5f9;font-weight:700;font-size:1.15rem">{_fmt_price(close)}</td>'
            f'<td><span style="color:{color};font-weight:700;font-size:1.1rem">{arrow} {sign}{pct:.2f}%</span></td>'
            f'{_chg_pct_cell(c5)}{_chg_pct_cell(c7)}{_chg_pct_cell(c10)}{_chg_pct_cell(c14)}'
            f'<td>{_fmt_chips_num(fn, _CHIPS_BADGE_MIN)}</td>'
            f'<td>{_fmt_chips_num(tn, _TRUST_BADGE_MIN)}</td>'
            f'<td style="font-size:.95rem">{margin_html}</td>'
            f'</tr>'
        )

    if not rows_html:
        return ""

    thead = (
        f'<thead><tr>'
        f'<th onclick="sortStockTable(this)" data-key="code">代號</th>'
        f'<th onclick="sortStockTable(this)" data-key="name">股名</th>'
        f'<th onclick="sortStockTable(this)" data-key="close">收盤</th>'
        f'<th onclick="sortStockTable(this)" data-key="pct">今日%</th>'
        f'<th onclick="sortStockTable(this)" data-key="wpct">近5日</th>'
        f'<th onclick="sortStockTable(this)" data-key="chg7">近7日</th>'
        f'<th onclick="sortStockTable(this)" data-key="chg10">近10日</th>'
        f'<th onclick="sortStockTable(this)" data-key="chg14">近14日</th>'
        f'<th onclick="sortStockTable(this)" data-key="foreign">外資</th>'
        f'<th onclick="sortStockTable(this)" data-key="trust">投信</th>'
        f'<th onclick="sortStockTable(this)" data-key="margin">融資</th>'
        f'</tr></thead>'
    )
    tbody = f'<tbody>{"".join(rows_html)}</tbody>'
    table = f'<table class="stock-table">{thead}{tbody}</table>'
    if as_row:
        return f'<tr class="detail-row" style="display:none"><td colspan="4">{table}</td></tr>'
    return table


def _sector_row(row, sectors_df=None, prices_df=None, chips_df=None, compact=False, stock_sparklines=None) -> str:
    pct = row["avg_change_pct"]
    up, down, flat = int(row["up_count"]), int(row["down_count"]), int(row["flat_count"])
    detail = _stock_table(row["sector_name"], sectors_df, prices_df, chips_df, stock_sparklines=stock_sparklines)
    has_detail = bool(detail)

    chevron = '<span class="chevron">›</span>' if has_detail else ""
    clickable = ' class="clickable-sector"' if has_detail else ""
    onclick = ' onclick="toggleDetail(this)"' if has_detail else ""

    return (
        f'<tr{clickable}{onclick}>'
        f'<td class="name">{_esc(row["sector_name"])}{chevron}</td>'
        f'<td>{_pct_cell(pct)}</td>'
        f'<td><span class="cnt" style="color:#f87171">▲{up}</span> '
        f'<span class="cnt" style="color:#4ade80">▼{down}</span> '
        f'<span class="cnt" style="color:#475569">─{flat}</span></td>'
        f'<td class="bar-cell">{_bar(up, down, flat)}</td>'
        f'</tr>'
        + detail
    )


def _sector_mini_card(row, card_id: str, sectors_df=None, prices_df=None, chips_df=None, stock_sparklines=None) -> tuple:
    """分組區子族群 mini-card，回傳 (card_html, panel_html)"""
    pct = row["avg_change_pct"]
    up, down = int(row["up_count"]), int(row["down_count"])
    color = _pct_color(pct)
    bg = _heatmap_bg(pct)
    sign = "+" if pct >= 0 else ""
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "─")

    detail_inner = _stock_table(row["sector_name"], sectors_df, prices_df, chips_df, stock_sparklines=stock_sparklines, as_row=False)
    has_detail = bool(detail_inner)
    onclick = f' onclick="selectMiniCard(\'{card_id}\')"' if has_detail else ""

    card = (
        f'<div class="sc-mini-card" data-mini="{card_id}"'
        f' style="border-top:2px solid {color};background:{bg}"{onclick}>'
        f'<div class="sc-mini-pct" style="color:{color}">{arrow}{sign}{pct:.2f}%</div>'
        f'<div class="sc-mini-name">{_esc(row["sector_name"])}</div>'
        f'<div class="sc-mini-cnt">'
        f'<span style="color:#f87171">▲{up}</span> '
        f'<span style="color:#4ade80">▼{down}</span>'
        f'</div>'
        f'</div>'
    )
    panel = (
        f'<div class="sc-mini-panel" id="{card_id}" style="display:none">{detail_inner}</div>'
        if has_detail else ""
    )
    return card, panel


def _top10_card(row, rank: int, sectors_df=None, prices_df=None, chips_df=None, stock_sparklines=None) -> str:
    pct = row["avg_change_pct"]
    up, down, flat = int(row["up_count"]), int(row["down_count"]), int(row["flat_count"])
    detail = _stock_table(row["sector_name"], sectors_df, prices_df, chips_df, stock_sparklines=stock_sparklines)
    has_detail = bool(detail)
    onclick = ' onclick="toggleDetail(this)"' if has_detail else ""
    chevron = '<span class="chevron">›</span>' if has_detail else ""
    color = _pct_color(pct)

    return (
        f'<tr class="top-row clickable-sector"{onclick}>'
        f'<td class="top-rank" style="color:{color}">{rank}</td>'
        f'<td class="top-name">{_esc(row["sector_name"])}{chevron}</td>'
        f'<td class="top-pct">{_pct_cell(pct, large=True)}</td>'
        f'<td class="top-counts">'
        f'<span style="color:#f87171">▲{up}</span> '
        f'<span style="color:#4ade80">▼{down}</span>'
        f'</td>'
        f'</tr>'
        + detail
    )


def _meta_stock_cards(sub_names: list, sectors_df, prices_df, chips_df=None,
                      universe_df=None, stock_ids: list = None, as_row: bool = True,
                      stock_sparklines: dict = None) -> str:
    """合併所有子族群的個股排行表（可排序）。"""
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

    rows_html = []
    for sid in sorted(name_map.keys(), key=lambda s: float(prices_map.loc[s, "change_pct"]) if s in prices_map.index else -999, reverse=True):
        stock_name = name_map[sid]
        if sid not in prices_map.index:
            rows_html.append(
                f'<tr><td style="color:#475569;font-size:.78rem">{sid}</td>'
                f'<td style="color:#334155">{_esc(stock_name)}</td>'
                f'<td colspan="6" style="color:#334155;font-size:.75rem">無行情</td></tr>'
            )
            continue

        p = prices_map.loc[sid]
        close = float(p["close"])
        pct = float(p["change_pct"])
        vol = int(p["volume"])
        color = _pct_color(pct)
        sign = "+" if pct >= 0 else ""
        arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "─")

        spark = (stock_sparklines or {}).get(sid, [])
        _rr = _ROLLING_RETURNS.get(sid, {})
        c5, c7, c10, c14 = _rr.get(5), _rr.get(7), _rr.get(10), _rr.get(14)
        _a5 = "" if c5 is None else c5
        _a7 = "" if c7 is None else c7
        _a10 = "" if c10 is None else c10
        _a14 = "" if c14 is None else c14

        fn = tn = mb = mc = 0
        chips_data: dict = {}
        if sid in chips_map.index:
            c = chips_map.loc[sid]
            fn = int(_na(c.get("foreign_net")))
            tn = int(_na(c.get("trust_net")))
            mb = int(_na(c.get("margin_balance")))
            mc = int(_na(c.get("margin_change")))
            chips_data = {"foreign": fn, "trust": tn, "marginBal": mb, "marginChg": mc}

        spark_json = json.dumps(spark)
        chips_json = json.dumps(chips_data)
        name_safe = _esc(stock_name)
        margin_html = _fmt_margin(mb, mc) if mb > 0 else "<span style='color:#334155'>─</span>"

        rows_html.append(
            f'<tr class="st-row" data-sid="{sid}" data-name="{name_safe}"'
            f' data-close="{close}" data-pct="{pct}" data-vol="{vol}"'
            f' data-sparkline=\'{spark_json}\' data-chips=\'{chips_json}\''
            f' data-code="{sid}" data-wpct="{_a5}" data-chg7="{_a7}" data-chg10="{_a10}" data-chg14="{_a14}"'
            f' data-foreign="{fn}" data-trust="{tn}" data-margin="{mb}"'
            f' onclick="openStockModal(this)" style="cursor:pointer">'
            f'<td style="color:#64748b;font-size:.92rem;font-weight:600">{sid}</td>'
            f'<td style="color:#cbd5e1;font-size:1.1rem;font-weight:600">{_esc(stock_name)}</td>'
            f'<td style="color:#f1f5f9;font-weight:700;font-size:1.15rem">{_fmt_price(close)}</td>'
            f'<td><span style="color:{color};font-weight:700;font-size:1.1rem">{arrow} {sign}{pct:.2f}%</span></td>'
            f'{_chg_pct_cell(c5)}{_chg_pct_cell(c7)}{_chg_pct_cell(c10)}{_chg_pct_cell(c14)}'
            f'<td>{_fmt_chips_num(fn, _CHIPS_BADGE_MIN)}</td>'
            f'<td>{_fmt_chips_num(tn, _TRUST_BADGE_MIN)}</td>'
            f'<td style="font-size:.95rem">{margin_html}</td>'
            f'</tr>'
        )

    if not rows_html:
        return ""

    thead = (
        f'<thead><tr>'
        f'<th onclick="sortStockTable(this)" data-key="code">代號</th>'
        f'<th onclick="sortStockTable(this)" data-key="name">股名</th>'
        f'<th onclick="sortStockTable(this)" data-key="close">收盤</th>'
        f'<th onclick="sortStockTable(this)" data-key="pct">今日%</th>'
        f'<th onclick="sortStockTable(this)" data-key="wpct">近5日</th>'
        f'<th onclick="sortStockTable(this)" data-key="chg7">近7日</th>'
        f'<th onclick="sortStockTable(this)" data-key="chg10">近10日</th>'
        f'<th onclick="sortStockTable(this)" data-key="chg14">近14日</th>'
        f'<th onclick="sortStockTable(this)" data-key="foreign">外資</th>'
        f'<th onclick="sortStockTable(this)" data-key="trust">投信</th>'
        f'<th onclick="sortStockTable(this)" data-key="margin">融資</th>'
        f'</tr></thead>'
    )
    tbody = f'<tbody>{"".join(rows_html)}</tbody>'
    table = f'<table class="stock-table">{thead}{tbody}</table>'
    if as_row:
        return f'<tr class="detail-row" style="display:none"><td colspan="4">{table}</td></tr>'
    return table


_CUM_THRESHOLD = 15     # 累積排名超過此數字則不顯示 badge
_CHIPS_STREAK_MIN = 2   # 外資/投信連買連賣最少幾日才顯示


def _chips_summary(meta_name: str, meta_chips: dict) -> str:
    """籌碼摘要 HTML block，置於展開面板 sparkline 下方。"""
    c = (meta_chips or {}).get(meta_name)
    if not c:
        return ""

    rows = []

    fn = c.get("foreign_net_today", 0)
    if fn != 0:
        k = fn // 1000
        sign = "+" if fn > 0 else ""
        color = "#f87171" if fn > 0 else "#4ade80"
        buy_count = c.get("foreign_buy_count", 0)
        total = c.get("total_stocks", 0)
        streak = c.get("foreign_streak", 0)

        ratio_html = (
            f'<span class="cs-sub">買超{buy_count}/{total}股</span>' if fn > 0 and total > 0
            else (f'<span class="cs-sub">賣超{total - buy_count}/{total}股</span>' if fn < 0 and total > 0 else "")
        )
        streak_html = ""
        if abs(streak) >= _CHIPS_STREAK_MIN:
            cls = "cs-streak-up" if streak > 0 else "cs-streak-dn"
            word = f"連買{streak}日" if streak > 0 else f"連賣{abs(streak)}日"
            streak_html = f'<span class="{cls}">{word}</span>'

        rows.append(
            f'<div class="cs-row">'
            f'<span class="cs-label">外資</span>'
            f'<span style="color:{color};font-weight:700">{_fmt_lots_text(k, sign)}</span>'
            f'{ratio_html}{streak_html}'
            f'</div>'
        )

    tn = c.get("trust_net_today", 0)
    if tn != 0:
        k = tn // 1000
        sign = "+" if tn > 0 else ""
        color = "#f87171" if tn > 0 else "#4ade80"
        streak = c.get("trust_streak", 0)
        streak_html = ""
        if abs(streak) >= _CHIPS_STREAK_MIN:
            cls = "cs-streak-up" if streak > 0 else "cs-streak-dn"
            word = f"連買{streak}日" if streak > 0 else f"連賣{abs(streak)}日"
            streak_html = f'<span class="{cls}">{word}</span>'
        rows.append(
            f'<div class="cs-row">'
            f'<span class="cs-label">投信</span>'
            f'<span style="color:{color};font-weight:700">{_fmt_lots_text(k, sign)}</span>'
            f'{streak_html}'
            f'</div>'
        )

    mc = c.get("margin_change_today", 0)
    mb = c.get("margin_balance_today", 0)
    if mc != 0 and mb > 0:
        pct = mc / mb * 100
        arrow = "↑" if mc > 0 else "↓"
        color = "#fb923c" if mc > 0 else "#64748b"
        alert_html = '<span class="cs-alert">融資擴張</span>' if c.get("margin_alert") else ""
        rows.append(
            f'<div class="cs-row">'
            f'<span class="cs-label">融資</span>'
            f'<span style="color:{color};font-weight:700">{arrow}{abs(pct):.1f}%</span>'
            f'{alert_html}'
            f'</div>'
        )

    if not rows:
        return ""
    return f'<div class="chips-summary">{"".join(rows)}</div>'


def _signal_badges(meta_name: str, cum_ranks: dict, meta_signals: dict, today_rank: int) -> str:
    """合併所有 badge：累積排名 + 排名升降 + 連漲連跌 + 成交量異常。"""
    badges = []

    # 累積漲跌幅 badges (3d/5d/7d)
    vals = cum_ranks.get("v", {}).get(meta_name, {}) if cum_ranks else {}
    for period, val_key in [("3d", "cum3"), ("5d", "cum5"), ("7d", "cum7")]:
        val = vals.get(val_key)
        if val is None:
            continue
        sign = "+" if val > 0 else ""
        pct_color = "#f87171" if val > 0 else "#4ade80"
        badges.append(
            f'<span class="cum-badge">'
            f'<span style="color:#475569">{period}</span>'
            f'<span class="cum-val" style="color:{pct_color}">{sign}{val:.1f}%</span>'
            f'</span>'
        )

    sig = (meta_signals or {}).get(meta_name, {})

    # 排名升降
    yest_rank = sig.get("yesterday_rank")
    if yest_rank and today_rank:
        delta = yest_rank - today_rank  # 正 = 今天名次更好
        if delta > 0:
            badges.append(f'<span class="sig-badge rank-up" title="昨日排名#{yest_rank}">↑{delta}</span>')
        elif delta < 0:
            badges.append(f'<span class="sig-badge rank-dn" title="昨日排名#{yest_rank}">↓{abs(delta)}</span>')

    # 連漲/連跌
    streak = sig.get("streak", 0)
    if abs(streak) >= 2:
        if streak > 0:
            badges.append(f'<span class="sig-badge streak-up" title="連續上漲{streak}個交易日">連漲{streak}日</span>')
        else:
            badges.append(f'<span class="sig-badge streak-dn" title="連續下跌{abs(streak)}個交易日">連跌{abs(streak)}日</span>')

    # 成交量異常
    vol_ratio = sig.get("vol_ratio")
    if vol_ratio and vol_ratio >= 1.5:
        badges.append(f'<span class="sig-badge vol-spike" title="今日量能{vol_ratio}x 5日均量">量↑{vol_ratio:.1f}x</span>')

    if not badges:
        return ""
    return f'<div class="mc-badges">{"".join(badges)}</div>'


def _meta_card(row: dict, rank: int, card_id: str, sectors_df=None, prices_df=None,
               chips_df=None, universe_df=None, cum_ranks: dict = None,
               meta_signals: dict = None, meta_chips: dict = None,
               stock_sparklines: dict = None) -> tuple:
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
        stock_sparklines=stock_sparklines,
    )
    onclick = f' onclick="selectMeta(\'{card_id}\')"' if detail_inner else ""
    badges = _signal_badges(row["meta_name"], cum_ranks or {}, meta_signals or {}, rank)

    # Sparkline + 籌碼摘要加在展開面板頂部
    sig = (meta_signals or {}).get(row["meta_name"], {})
    sparkline = _sparkline(sig.get("daily_pct", []), sig.get("dates", []))
    chips_sum = _chips_summary(row["meta_name"], meta_chips)
    panel_content = sparkline + chips_sum + detail_inner if (sparkline or chips_sum or detail_inner) else ""

    meta_name_safe = _esc(row["meta_name"])
    card = (
        f'<div class="mc-card" data-meta="{card_id}" data-meta-name="{meta_name_safe}"'
        f' style="border-top:2px solid {color};background:{bg}"{onclick}>'
        f'<div class="mc-hd">'
        f'<span class="mc-name">{meta_name_safe}</span>'
        f'<span class="mc-pct" style="color:{color}">{arrow}{sign}{pct:.2f}%</span>'
        f'</div>'
        f'<div class="mc-cnt">'
        f'<span style="color:#f87171">▲{up}</span> '
        f'<span style="color:#4ade80">▼{down}</span>'
        f'<span class="mc-rank" style="float:right">#{rank}</span>'
        f'</div>'
        f'{badges}'
        f'</div>'
    )
    panel = (
        f'<div class="mc-panel" id="{card_id}" data-meta-name="{meta_name_safe}" style="display:none">{panel_content}</div>'
        if panel_content else ""
    )
    return card, panel


def _vol_turnover_section(signals: list) -> str:
    if not signals:
        return ""
    rows_html = ""
    for s in signals:
        sid = s["stock_id"]
        chg = s.get("change_pct") or 0
        chg_color = _pct_color(chg)
        sign = "+" if chg >= 0 else ""
        f_net = s.get("foreign_net")
        t_net = s.get("trust_net")
        confirmed = s.get("inst_confirmed", False)
        inst_badge = (
            "<span style='color:#fbbf24;background:rgba(120,53,15,.3);border:1px solid rgba(120,53,15,.5);"
            "border-radius:4px;padding:1px 6px;font-size:.65rem;font-weight:700'>外資+投信✓</span>"
            if confirmed else ""
        )
        f_html = (
            f"<span style='color:#f87171;font-size:.72rem'>+{f_net//1000:,}張</span>" if f_net and f_net > 0
            else f"<span style='color:#4ade80;font-size:.72rem'>{f_net//1000:,}張</span>" if f_net and f_net < 0
            else "<span style='color:#475569;font-size:.72rem'>─</span>"
        )
        stock_name = s.get("stock_name", "")
        meta_sector = s.get("meta_sector", "")
        rows_html += (
            f"<tr>"
            f"<td style='white-space:nowrap'>"
            f"<span style='color:#475569;font-size:.7rem;font-weight:600'>{sid}</span>"
            f"<span style='color:#94a3b8;font-size:.78rem;margin-left:5px'>{_esc(stock_name)}</span>"
            f"</td>"
            f"<td style='color:#64748b;font-size:.72rem;max-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>{_esc(meta_sector)}</td>"
            f"<td style='color:{chg_color};font-weight:700'>{sign}{chg:.2f}%</td>"
            f"<td style='color:#60a5fa;font-weight:700'>{s['vol_multiple']}x</td>"
            f"<td>{f_html}</td>"
            f"<td>{inst_badge}</td>"
            f"</tr>"
        )
    return f"""
<div style='background:#080c14;border:1px solid #1a2436;border-radius:10px;padding:14px 16px;margin-bottom:16px'>
  <div style='font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#475569;margin-bottom:10px'>
    ⚡ 巨量換手訊號（前日漲停 → 今日爆量收跌，共 {len(signals)} 檔）
  </div>
  <table style='width:100%;border-collapse:collapse'>
    <thead><tr>
      <th style='text-align:left;padding:4px 8px;font-size:.65rem;color:#334155;border-bottom:1px solid #1a2436'>代號 / 名稱</th>
      <th style='text-align:left;padding:4px 8px;font-size:.65rem;color:#334155;border-bottom:1px solid #1a2436'>族群</th>
      <th style='text-align:left;padding:4px 8px;font-size:.65rem;color:#334155;border-bottom:1px solid #1a2436'>今日漲跌</th>
      <th style='text-align:left;padding:4px 8px;font-size:.65rem;color:#334155;border-bottom:1px solid #1a2436'>量倍數</th>
      <th style='text-align:left;padding:4px 8px;font-size:.65rem;color:#334155;border-bottom:1px solid #1a2436'>外資</th>
      <th style='text-align:left;padding:4px 8px;font-size:.65rem;color:#334155;border-bottom:1px solid #1a2436'>確認</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>"""


# 五級大盤方向 → 顯示樣式 + 對應筆記操作提示（逆轟動能派學習筆記章節）。
# 提示文字 hard-code 在此（跟著 git 走），因為來源 notes/ 是 gitignored、不會發布到
# 產出頁那台。設計文件：docs/superpowers/specs/2026-07-09-market-regime-dashboard-design.md
_REGIME_TIERS = {
    "大漲": {"emoji": "🚀", "color": "#ff2d2d",
             "tip": "漲時加碼，找主流族群最強一檔追（可追漲停）。", "ref": "筆記 §二、§七"},
    "小漲": {"emoji": "🔴", "color": "#d97070",
             "tip": "正常操作，續抱強勢股、汰弱留強。", "ref": "筆記 全篇通用"},
    "持平": {"emoji": "⚪", "color": "#94a3b8",
             "tip": "均線上才買、觸發出場三原則就賣，反覆操作，不提前佈局盤整股。", "ref": "筆記 §七 盤整盤8步驟"},
    "小跌": {"emoji": "🟢", "color": "#009933",
             "tip": "持股健檢：均線空頭排列／下彎／跌破頸線任一成立就先出。", "ref": "筆記 §二十二 持股健檢三要素"},
    "大跌": {"emoji": "⛔", "color": "#00c255",
             "tip": "只找最後撐住的 5–10 檔換股，不接弱勢、不攤平、不抄底。", "ref": "筆記 §十四、§二十三"},
}


def _market_regime_section(regime: dict) -> str:
    """大盤分級儀表板：五級方向 + 資金集中度診斷 + 對應筆記操作提示。

    regime 為 None（TAIEX 抓取失敗）時回空字串——這個區塊整塊不顯示，不讓整頁掛掉。
    """
    if not regime:
        return ""

    tier = regime.get("tier", "持平")
    style = _REGIME_TIERS.get(tier, _REGIME_TIERS["持平"])
    pct = regime.get("taiex_change_pct")
    pct_txt = f"{'+' if (pct or 0) >= 0 else ''}{pct:.2f}%" if pct is not None else "—"

    # 廣度：上漲家數 / 總家數
    up = regime.get("up_count")
    total = regime.get("total")
    breadth = regime.get("breadth_ratio")
    breadth_txt = ""
    if breadth is not None and total:
        breadth_txt = (
            f"<span style='color:#64748b;font-size:.8rem;margin-left:12px'>"
            f"上漲 <b style='color:#d97070'>{up}</b> / 共 {total} 檔"
            f"（廣度 {breadth*100:.0f}%）</span>"
        )

    # 資金集中度診斷（兩邊都有資料才顯示）
    hw = regime.get("heavyweight_avg_pct")
    broad = regime.get("broad_avg_pct")
    conc_html = ""
    if hw is not None and broad is not None:
        direction = regime.get("concentration_direction")
        is_conc = regime.get("is_concentrated")
        divergence = regime.get("divergence")
        if is_conc and direction:
            head_color = "#fbbf24" if direction == "權值股撐盤" else "#60a5fa"
            head = (f"<span style='color:{head_color};font-weight:700'>資金集中 ⚠️ — "
                    f"{_esc(direction)}</span>")
        else:
            head = "<span style='color:#64748b;font-weight:600'>資金分布均衡</span>"
        div_txt = f"{'+' if (divergence or 0) >= 0 else ''}{divergence:.2f}" if divergence is not None else "—"
        conc_html = f"""
    <div style='margin-top:10px;padding-top:10px;border-top:1px solid #1a2436;font-size:.82rem'>
      {head}
      <div style='display:flex;gap:18px;margin-top:6px;color:#94a3b8'>
        <span>權值股（前{regime.get('heavyweight_count', 20)}大）：
          <b style='color:{_pct_color(hw)}'>{'+' if hw >= 0 else ''}{hw:.2f}%</b></span>
        <span>非權值股：
          <b style='color:{_pct_color(broad)}'>{'+' if broad >= 0 else ''}{broad:.2f}%</b></span>
        <span>落差：<b style='color:#e2e8f0'>{div_txt} 個百分點</b></span>
      </div>
    </div>"""

    return f"""
<div style='background:#080c14;border:1px solid #1a2436;border-left:3px solid {style['color']};border-radius:10px;padding:16px 18px;margin-bottom:16px'>
  <div style='font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#475569;margin-bottom:8px'>
    大盤現況
  </div>
  <div style='display:flex;align-items:baseline;flex-wrap:wrap'>
    <span style='font-size:1.6rem;font-weight:800;color:{style['color']}'>{style['emoji']} {_esc(tier)}</span>
    <span style='font-size:1.1rem;font-weight:700;color:{style['color']};margin-left:12px'>加權指數 {pct_txt}</span>
    {breadth_txt}
  </div>
  <div style='margin-top:8px;font-size:.86rem;color:#cbd5e1'>
    💡 {_esc(style['tip'])}
    <span style='color:#475569;font-size:.72rem;margin-left:6px'>（{_esc(style['ref'])}）</span>
  </div>
  {conc_html}
</div>"""


def generate(
    trade_date: date,
    perf_df: pd.DataFrame,
    sectors_df: pd.DataFrame = None,
    prices_df: pd.DataFrame = None,
    chips_df: pd.DataFrame = None,
    meta_perf: list = None,
    universe_df: pd.DataFrame = None,
    cum_data: list = None,
    meta_signals: dict = None,
    meta_chips: dict = None,
    stock_sparklines: dict = None,
    vol_turnover: list = None,
    rolling_returns: dict = None,
    market_regime: dict = None,
    output_path: str = "docs/index.html",
) -> None:
    if perf_df.empty and not meta_perf:
        return

    # 近5/7/10/14日累積漲跌幅（get_rolling_returns）一次性塞入 module 級 map，供 _stock_table /
    # _meta_stock_cards 直接讀，避免穿整條渲染呼叫鏈的參數。
    global _ROLLING_RETURNS
    _ROLLING_RETURNS = rolling_returns or {}

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

    # JS 資料：個股搜尋索引 + META 索引
    stock_index_js = "[]"
    meta_index_js = "[]"
    if universe_df is not None:
        prices_map = prices_df.set_index("stock_id") if prices_df is not None and not prices_df.empty else pd.DataFrame()
        idx = []
        for _, r in universe_df.iterrows():
            sid = str(r["stock_id"])
            pct = round(float(prices_map.loc[sid]["change_pct"]), 2) if sid in prices_map.index else 0.0
            idx.append({"id": sid, "name": str(r["stock_name"]), "meta": str(r["meta_sector"]), "pct": pct})
        # 用 "</" -> "<\/" 避免股票/族群名稱裡剛好含有 "</script>" 時提前結束這個 &lt;script&gt; 區塊
        # （這段 JSON 是直接內嵌進 &lt;script&gt; 標籤，不是走 innerHTML，所以只需要防這一種逃逸方式）
        stock_index_js = json.dumps(idx, ensure_ascii=False).replace("</", "<\\/")
    if meta_perf:
        midx = [{"name": r["meta_name"], "subs": r.get("sub_names", []), "pct": r.get("avg_change_pct", 0.0)} for r in meta_perf]
        meta_index_js = json.dumps(midx, ensure_ascii=False).replace("</", "<\\/")

    # 累積排名 lookup（用於卡片上的 badge）
    cum_ranks = _make_cum_ranks(cum_data) if cum_data else {}

    # Top10 / Bottom10
    if meta_perf:
        meta_sorted = sorted(meta_perf, key=lambda r: r["avg_change_pct"], reverse=True)
        top_source = meta_sorted[:10]
        bot_source = list(reversed(meta_sorted))[:10]

        top_cards, top_panels = [], []
        for i, r in enumerate(top_source):
            c, p = _meta_card(r, i+1, f"t{i}", sectors_df, prices_df, chips_df, universe_df, cum_ranks, meta_signals, meta_chips, stock_sparklines=stock_sparklines)
            top_cards.append(c); top_panels.append(p)

        bot_cards, bot_panels = [], []
        for i, r in enumerate(bot_source):
            c, p = _meta_card(r, i+1, f"b{i}", sectors_df, prices_df, chips_df, universe_df, cum_ranks, meta_signals, meta_chips, stock_sparklines=stock_sparklines)
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
        top10_html = "".join(_top10_card(r, i+1, sectors_df, prices_df, chips_df, stock_sparklines=stock_sparklines) for i, (_, r) in enumerate(df.head(10).iterrows()))
        bot10_html = "".join(_top10_card(r, i+1, sectors_df, prices_df, chips_df, stock_sparklines=stock_sparklines) for i, (_, r) in enumerate(df.tail(10).iloc[::-1].iterrows()))
        top_section_inner = (
            f'<div class="top-card"><div class="top-card-title up-title">▲ 今日漲幅 Top 10</div><table><tbody>{top10_html}</tbody></table></div>'
            f'<div class="top-card"><div class="top-card-title down-title">▼ 今日跌幅 Top 10</div><table><tbody>{bot10_html}</tbody></table></div>'
        )

    # Groups
    groups_html = ""
    if not df.empty:
        df["group"] = df["sector_name"].apply(classify_sector)
    for g_idx, (group_name, _) in enumerate(SECTOR_GROUPS if not df.empty else []):
        subset = df[df["group"] == group_name].copy()
        if subset.empty:
            continue
        count = len(subset)
        avg = subset["avg_change_pct"].mean()
        g_color = _pct_color(avg)
        sign = "+" if avg >= 0 else ""

        mini_cards, mini_panels = [], []
        for s_idx, (_, r) in enumerate(subset.iterrows()):
            cid = f"sg{g_idx}s{s_idx}"
            mc, mp = _sector_mini_card(r, cid, sectors_df, prices_df, chips_df, stock_sparklines=stock_sparklines)
            mini_cards.append(mc)
            mini_panels.append(mp)

        groups_html += f"""
<details class="group-block" data-gname="{group_name}">
  <summary class="group-header">
    <span class="g-chevron">›</span>
    <span class="g-name">{group_name}</span>
    <span class="g-avg" style="color:{g_color}">{sign}{avg:.2f}%</span>
    <span class="g-count">{count} 族群</span>
  </summary>
  <div class="sc-mini-grid">{"".join(mini_cards)}</div>
  {"".join(mini_panels)}
</details>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <!-- 禁止瀏覽器快取：頁面每天重產、檔名固定 index.html，這個大檔不加會被啟發式快取，
       普通 F5 看到舊族群/股價、要 Ctrl+F5 才更新。加了之後普通 F5 就會抓最新。 -->
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <title>台股電子族群 {date_str}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:"Fira Sans",-apple-system,"Segoe UI",sans-serif;background:#020617;color:#e2e8f0;padding:12px 20px}}
    .mono{{font-family:"Fira Code",monospace;font-variant-numeric:tabular-nums}}

    /* Header */
    .header{{margin-bottom:24px}}
    h1{{font-family:"Fira Sans",sans-serif;font-size:1.1rem;font-weight:600;color:#94a3b8;letter-spacing:.05em;text-transform:uppercase}}
    .mkt-bar{{display:flex;align-items:center;gap:20px;margin-top:8px;padding:12px 16px;background:#0a0e1a;border:1px solid #1e293b;border-radius:10px;flex-wrap:wrap}}
    .mkt-date{{font-size:1rem;font-weight:600;color:#f1f5f9}}
    .mkt-avg{{font-family:"Fira Code",monospace;font-size:1.3rem;font-weight:800;color:{mkt_color};text-shadow:0 0 12px {mkt_color}55}}
    .mkt-stat{{font-size:.82rem;color:#64748b}}
    .mkt-stat span{{font-weight:600}}

    /* 累積排名 badge */
    .mc-badges{{display:flex;gap:3px;margin-top:5px;flex-wrap:wrap}}
    .cum-badge{{font-family:"Fira Code",monospace;font-size:.58rem;color:#475569;background:#04070f;border:1px solid #1a2436;border-radius:3px;padding:1px 5px;white-space:nowrap;cursor:default}}
    .cum-badge b{{color:#94a3b8;font-weight:700;margin-left:1px}}
    .cum-val{{font-family:"Fira Code",monospace;font-size:.58rem;font-weight:600;margin-left:3px}}
    .sig-badge{{font-family:"Fira Code",monospace;font-size:.58rem;border-radius:3px;padding:1px 5px;white-space:nowrap;cursor:default;border:1px solid}}
    .rank-up{{color:#f87171;background:rgba(127,29,29,.18);border-color:rgba(127,29,29,.4)}}
    .rank-dn{{color:#4ade80;background:rgba(6,78,59,.18);border-color:rgba(6,78,59,.4)}}
    .streak-up{{color:#fbbf24;background:rgba(120,53,15,.25);border-color:rgba(120,53,15,.5);font-weight:700}}
    .streak-dn{{color:#60a5fa;background:rgba(30,58,138,.25);border-color:rgba(30,58,138,.5);font-weight:700}}
    .vol-spike{{color:#fb923c;background:rgba(124,45,18,.25);border-color:rgba(124,45,18,.5);font-weight:700}}
    /* Sparkline */
    .sparkline-wrap{{padding:8px 0 4px;overflow-x:auto;margin-bottom:8px}}

    /* 籌碼摘要（展開面板頂部）*/
    .chips-summary{{background:#04070f;border:1px solid #1a2436;border-radius:6px;padding:8px 12px;margin-bottom:8px}}
    .cs-row{{display:flex;align-items:center;gap:8px;font-size:.75rem;line-height:2}}
    .cs-label{{color:#475569;font-size:.65rem;text-transform:uppercase;letter-spacing:.05em;min-width:28px}}
    .cs-sub{{color:#475569;font-size:.65rem}}
    .cs-streak-up{{font-size:.65rem;color:#f87171;background:rgba(127,29,29,.18);border:1px solid rgba(127,29,29,.4);border-radius:3px;padding:0 5px}}
    .cs-streak-dn{{font-size:.65rem;color:#4ade80;background:rgba(6,78,59,.18);border:1px solid rgba(6,78,59,.4);border-radius:3px;padding:0 5px}}
    .cs-alert{{font-size:.65rem;color:#fb923c;background:rgba(124,45,18,.25);border:1px solid rgba(124,45,18,.5);border-radius:3px;padding:0 5px;font-weight:700}}

    /* Top10 小卡片 */
    .top-section{{margin-bottom:24px}}
    .mc-label{{font-size:.9rem;font-weight:700;letter-spacing:.04em;margin-bottom:6px}}
    .up-label{{color:#f87171}} .dn-label{{color:#4ade80}}
    .mc-grid{{display:grid;grid-template-columns:repeat(10,1fr);gap:5px}}
    @media(max-width:1000px){{.mc-grid{{grid-template-columns:repeat(5,1fr)}}}}
    @media(max-width:540px){{.mc-grid{{grid-template-columns:repeat(3,1fr)}}}}
    .mc-card{{padding:8px 10px;border-radius:8px;border:1px solid #1a2436;background:#080c14;cursor:pointer;transition:border-color .15s,background .15s}}
    .mc-card:hover,.mc-card.active{{border-color:#334155;background:#0d1525}}
    .mc-hd{{display:flex;align-items:baseline;justify-content:space-between;gap:4px;margin-bottom:2px}}
    .mc-rank{{font-size:.7rem;color:#475569;font-weight:600}}
    .mc-pct{{font-family:"Fira Code",monospace;font-size:1.05rem;font-weight:800;white-space:nowrap}}
    .mc-name{{font-size:.85rem;color:#94a3b8;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}}
    .mc-cnt{{font-size:.78rem;font-weight:600}}
    .mc-panel{{background:#04070f;border:1px solid #1a2436;border-radius:8px;padding:12px 16px;margin-top:5px}}

    /* Fallback table Top10 */
    .top-card{{background:#080c14;border:1px solid #1a2436;border-radius:12px;overflow:hidden;margin-bottom:10px}}
    .top-card-title{{padding:10px 16px;font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;border-bottom:1px solid #1a2436}}
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
    th{{text-align:left;padding:6px 12px;font-size:.7rem;color:#475569;text-transform:uppercase;border-bottom:1px solid #1a2436}}
    td{{padding:9px 12px;border-bottom:1px solid #020617;font-size:.85rem}}
    .name{{font-weight:500;color:#e2e8f0;max-width:160px}}
    .cnt{{font-size:.78rem;margin-right:4px}}
    .bar-cell{{width:70px}}
    .clickable-sector{{cursor:pointer;transition:background .12s}}
    .clickable-sector:hover > td{{background:#080c14}}

    /* Stock cards */
    .detail-row > td{{padding:12px 16px;background:#04070f}}
    .stock-cards-wrap{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}}
    .stock-card{{background:#080c14;border:1px solid #1a2436;border-radius:8px;padding:10px 12px;transition:border-color .15s,background .15s}}
    .stock-card:hover{{border-color:#334155;background:#0d1525}}
    .no-data{{opacity:.4}}
    .sc-header{{display:flex;align-items:baseline;gap:6px;margin-bottom:6px}}
    .sc-id{{font-family:"Fira Code",monospace;font-size:.72rem;color:#475569;font-weight:600}}
    .sc-name{{font-size:.82rem;color:#94a3b8;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
    .sc-body{{display:flex;align-items:baseline;justify-content:space-between;gap:6px;margin-bottom:4px}}
    .sc-price{{font-family:"Fira Code",monospace;font-size:1rem;font-weight:700;color:#f1f5f9}}
    .sc-pct{{font-family:"Fira Code",monospace;font-size:.82rem;font-weight:700}}
    .sc-vol{{font-family:"Fira Code",monospace;font-size:.7rem;color:#475569}}
    .sc-chips{{font-size:.72rem;color:#64748b;margin-top:4px;line-height:1.6}}
    .chip-label{{color:#334155;margin-right:2px}}

    /* Stock sortable table (sub-sector expand) */
    .stock-table{{width:100%;border-collapse:collapse;font-size:1.05rem}}
    .stock-table thead th{{text-align:left;padding:7px 14px;font-size:.8rem;color:#94a3b8;text-transform:uppercase;cursor:pointer;user-select:none;white-space:nowrap;border-bottom:1px solid #1a2436;transition:color .12s}}
    .stock-table thead th:hover{{color:#e2e8f0}}
    .stock-table td{{padding:10px 14px;border-bottom:1px solid #04070f}}
    .st-row{{cursor:pointer;transition:background .12s}}
    .st-row:hover>td{{background:#080c14}}

    /* Groups */
    .section-bar{{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}}
    .groups-grid{{display:grid;grid-template-columns:1fr;gap:8px}}
    .section-title{{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;color:#475569}}
    .collapse-all-btn{{background:none;border:1px solid #1a2436;color:#475569;padding:4px 12px;border-radius:6px;cursor:pointer;font-size:.75rem;transition:all .15s}}
    .collapse-all-btn:hover{{border-color:#334155;color:#94a3b8}}
    .group-block{{border:1px solid #1a2436;border-radius:10px;margin-bottom:8px;overflow:hidden}}
    .group-header{{display:flex;align-items:center;gap:10px;padding:11px 16px;cursor:pointer;list-style:none;background:#080c14;user-select:none;transition:background .15s}}
    .group-header:hover{{background:#0d1525}}
    .group-header::-webkit-details-marker{{display:none}}
    details[open] > .group-header{{border-bottom:1px solid #1a2436;background:#0d1525}}
    .g-name{{font-weight:600;color:#e2e8f0;flex:1;font-size:.9rem}}
    .g-avg{{font-family:"Fira Code",monospace;font-weight:800;font-size:1rem}}
    .g-count{{font-size:.72rem;color:#334155}}

    /* Sub-sector mini-card grid */
    .sc-mini-grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;padding:10px 12px}}
    @media(max-width:900px){{.sc-mini-grid{{grid-template-columns:repeat(4,1fr)}}}}
    @media(max-width:540px){{.sc-mini-grid{{grid-template-columns:repeat(3,1fr)}}}}
    .sc-mini-card{{padding:9px 11px;border-radius:6px;border:1px solid #1a2436;background:#080c14;cursor:pointer;transition:border-color .15s,background .15s}}
    .sc-mini-card:hover,.sc-mini-card.active{{border-color:#475569;background:#0d1525}}
    .sc-mini-pct{{font-family:"Fira Code",monospace;font-size:1rem;font-weight:800;white-space:nowrap}}
    .sc-mini-name{{font-size:.85rem;color:#94a3b8;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin:3px 0}}
    .sc-mini-cnt{{font-size:.75rem;color:#64748b}}
    .sc-mini-panel{{background:#04070f;border:1px solid #1a2436;border-radius:8px;padding:12px 16px;margin:0 12px 10px}}

    /* Search */
    .search-wrap{{position:relative;margin-top:10px;max-width:360px}}
    .stock-search{{width:100%;background:#080c14;border:1px solid #1a2436;border-radius:8px;padding:8px 14px;color:#e2e8f0;font-family:"Fira Sans",sans-serif;font-size:.85rem;outline:none;transition:border-color .15s}}
    .stock-search:focus{{border-color:#475569;box-shadow:0 0 0 2px rgba(71,85,105,.2)}}
    .search-dropdown{{position:absolute;top:calc(100% + 4px);left:0;right:0;background:#080c14;border:1px solid #1a2436;border-radius:8px;z-index:100;overflow:hidden;box-shadow:0 8px 32px rgba(0,0,0,.7)}}
    .search-item{{display:flex;align-items:center;gap:8px;padding:8px 12px;cursor:pointer;font-size:.8rem;transition:background .1s}}
    .search-item:hover{{background:#0d1525}}
    .si-id{{font-family:"Fira Code",monospace;color:#475569;font-size:.72rem;min-width:36px}}
    .si-name{{color:#e2e8f0;flex:1;font-weight:500}}
    .si-meta{{color:#334155;font-size:.7rem}}
    .si-pct{{font-family:"Fira Code",monospace;font-weight:700;font-size:.8rem;min-width:52px;text-align:right}}
    .search-item-meta{{border-top:1px solid #080c14}}
    .si-meta-icon{{color:#60a5fa;font-size:.65rem;font-weight:700;min-width:36px;background:rgba(30,58,138,.3);border-radius:3px;text-align:center;padding:1px 4px}}

    .search-highlight{{outline:2px solid #475569;outline-offset:2px;border-radius:8px}}

    /* Nav */
    .nav-links{{display:flex;gap:8px;margin-top:10px}}
    .nav-link{{font-size:.78rem;padding:5px 14px;border-radius:6px;border:1px solid #1a2436;color:#64748b;text-decoration:none;transition:all .15s}}
    .nav-link:hover{{border-color:#475569;color:#94a3b8;background:#080c14}}
    .nav-link.active{{border-color:#334155;color:#e2e8f0;background:#0d1525}}

    .footer{{margin-top:28px;font-size:.7rem;color:#1a2436;text-align:center;padding-bottom:20px}}

    /* ── RWD Mobile ── */
    @media(max-width:540px){{
      body{{padding:12px}}
      h1{{font-size:.95rem}}
      .mkt-bar{{gap:12px;padding:10px 12px}}
      .mkt-avg{{font-size:1.1rem}}
      .mkt-stat{{font-size:.75rem}}
      .top-counts{{display:none}}
      .top-pct{{padding:10px 10px 10px 4px}}
      .top-name{{font-size:.82rem;max-width:none}}
      .mc-grid{{grid-template-columns:repeat(2,1fr)}}
      .mc-card{{padding:6px 8px}}
      .mc-pct{{font-size:.9rem}}
      .mc-name{{font-size:.75rem}}
      .stock-cards-wrap{{grid-template-columns:1fr 1fr;gap:8px}}
      .sc-price{{font-size:.9rem}}
      .sc-pct{{font-size:.75rem}}
      .group-header{{padding:10px 12px}}
      .g-name{{font-size:.85rem}}
      .g-avg{{font-size:.9rem}}
      .g-count{{display:none}}
      .sc-mini-grid{{grid-template-columns:repeat(3,1fr)}}
      .sc-mini-panel{{margin:0 6px 8px}}
    }}

    /* ── Stock Modal ── */
    .smodal-overlay{{position:fixed;inset:0;z-index:2000;background:rgba(0,0,0,.85);backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center;padding:16px}}
    .smodal{{background:#080c14;border:1px solid #1a2436;border-radius:14px;width:100%;max-width:420px;max-height:90vh;overflow-y:auto;box-shadow:0 32px 80px rgba(0,0,0,.9)}}
    .smodal-hd{{display:flex;align-items:center;justify-content:space-between;padding:16px 18px 10px;border-bottom:1px solid #1a2436}}
    .smodal-sid{{font-family:"Fira Code",monospace;font-size:1.1rem;font-weight:700;color:#e2e8f0;margin-right:8px}}
    .smodal-name{{font-size:.9rem;color:#64748b}}
    .smodal-close{{background:none;border:none;color:#475569;font-size:1.2rem;cursor:pointer;padding:2px 6px;border-radius:4px;line-height:1;transition:all .15s}}
    .smodal-close:hover{{color:#94a3b8;background:#1a2436}}
    .smodal-price{{display:flex;align-items:baseline;gap:12px;padding:12px 18px 8px}}
    .smodal-val{{font-family:"Fira Code",monospace;font-size:1.6rem;font-weight:800;color:#f1f5f9}}
    .smodal-pct{{font-family:"Fira Code",monospace;font-size:1rem;font-weight:700}}
    .smodal-vol{{font-family:"Fira Code",monospace;font-size:.78rem;color:#64748b;margin-left:auto}}
    .smodal-spark{{padding:4px 18px 8px;overflow-x:auto}}
    .smodal-chips{{padding:10px 18px 18px}}
    .sm-chip-row{{display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #04070f;font-size:.85rem}}
    .sm-chip-row:last-child{{border-bottom:none}}
    .sm-chip-label{{color:#475569;font-size:.7rem;min-width:36px}}
    .sm-chip-val{{font-weight:600}}
    .sm-chip-sub{{font-size:.72rem;color:#64748b;margin-left:4px}}

  </style>
</head>
<body>
  <!-- Stock Detail Modal -->
  <div id="stock-modal" class="smodal-overlay" style="display:none" onclick="closeModalBg(event)">
    <div class="smodal">
      <div class="smodal-hd">
        <span><span id="sm-sid" class="smodal-sid"></span><span id="sm-name" class="smodal-name"></span></span>
        <button class="smodal-close" onclick="closeStockModal()">✕</button>
      </div>
      <div class="smodal-price">
        <span id="sm-close" class="smodal-val"></span>
        <span id="sm-pct" class="smodal-pct"></span>
        <span id="sm-vol" class="smodal-vol"></span>
      </div>
      <div id="sm-spark" class="smodal-spark"></div>
      <div id="sm-chips" class="smodal-chips"></div>
    </div>
  </div>
  <div class="header">
    <h1>台股電子半導體族群追蹤</h1>
    <div class="mkt-bar">
      <span class="mkt-date">📅 {date_str}（週{weekday}）</span>
      <span class="mkt-avg">{mkt_sign}{mkt_avg:.2f}%</span>
      <span class="mkt-stat">上漲 <span style="color:#d97070">{up_cnt}</span></span>
      <span class="mkt-stat">下跌 <span style="color:#009933">{dn_cnt}</span></span>
      <span class="mkt-stat">平盤 <span style="color:#475569">{flat_cnt}</span></span>
    </div>
    <div class="search-wrap">
      <input id="stock-search" class="stock-search" placeholder="🔍 搜尋股票代號 / 名稱…" oninput="searchStocks(this.value)" onblur="setTimeout(()=>hideSearch(),200)" autocomplete="off">
      <div id="search-dropdown" class="search-dropdown" style="display:none"></div>
    </div>
    <div class="nav-links">
      <a class="nav-link active" href="index.html">族群績效</a>
      <a class="nav-link" href="chips.html">籌碼分析</a>
      <a class="nav-link" href="patterns.html">形態掃描</a>
    </div>
  </div>

  {_market_regime_section(market_regime)}

  {_vol_turnover_section(vol_turnover or [])}

  <div class="top-section">{top_section_inner}</div>

  <div class="section-bar">
    <span class="section-title">所有族群 / 依分類</span>
    <button class="collapse-all-btn" onclick="collapseAll()">⊟ 全部收合</button>
  </div>
  <div class="groups-grid">{groups_html}</div>

  <div class="footer">點擊族群名稱可展開個股 ｜ 台灣：漲紅跌綠</div>

  <script>
    const STOCK_INDEX = {stock_index_js};
    const META_INDEX  = {meta_index_js};

    /* ── Search ── */
    function searchStocks(q) {{
      const dd = document.getElementById('search-dropdown');
      q = q.trim();
      if (!q) {{ dd.style.display='none'; return; }}

      const stockMatches = STOCK_INDEX.filter(s => s.id.startsWith(q) || s.name.includes(q)).slice(0,6);
      const metaMatches  = META_INDEX.filter(m =>
        m.name.includes(q) || (m.subs && m.subs.some(sub => sub.includes(q)))
      ).slice(0,5);

      if (!stockMatches.length && !metaMatches.length) {{ dd.style.display='none'; return; }}

      const stockHtml = stockMatches.map(s => {{
        const sign = s.pct>=0?'+':'', col = s.pct>0?'#f87171':(s.pct<0?'#4ade80':'#64748b');
        return `<div class="search-item" onmousedown="selectSearchStock('${{s.id}}')">`+
          `<span class="si-id">${{s.id}}</span>`+
          `<span class="si-name">${{s.name}}</span>`+
          `<span class="si-meta">${{s.meta}}</span>`+
          `<span class="si-pct" style="color:${{col}}">${{sign}}${{s.pct.toFixed(2)}}%</span>`+
          `</div>`;
      }}).join('');

      const metaHtml = metaMatches.map(m => {{
        const sign = m.pct>=0?'+':'', col = m.pct>0?'#f87171':(m.pct<0?'#4ade80':'#64748b');
        return `<div class="search-item search-item-meta" onmousedown="selectSearchMeta('${{m.name}}')">`+
          `<span class="si-id si-meta-icon">族群</span>`+
          `<span class="si-name">${{m.name}}</span>`+
          `<span class="si-meta">${{(m.subs||[]).slice(0,3).join('·')}}</span>`+
          `<span class="si-pct" style="color:${{col}}">${{sign}}${{m.pct.toFixed(2)}}%</span>`+
          `</div>`;
      }}).join('');

      dd.innerHTML = stockHtml + metaHtml;
      dd.style.display = '';
    }}
    function hideSearch() {{ document.getElementById('search-dropdown').style.display='none'; }}
    function selectSearchMeta(name) {{
      const block = document.querySelector('details.group-block[data-gname="'+name+'"]');
      if (block) {{
        block.open = true;
        setTimeout(()=>block.scrollIntoView({{behavior:'smooth',block:'start'}}),50);
      }}
      document.getElementById('search-dropdown').style.display='none';
      document.getElementById('stock-search').value='';
    }}
    function selectSearchStock(sid) {{
      const card = document.querySelector('.stock-card[data-sid="'+sid+'"]');
      if (card) {{
        const mcPanel = card.closest('.mc-panel');
        if (mcPanel) {{
          document.querySelectorAll('.mc-panel').forEach(p=>p.style.display='none');
          document.querySelectorAll('.mc-card.active').forEach(c=>c.classList.remove('active'));
          mcPanel.style.display='';
          const mc = document.querySelector('[data-meta="'+mcPanel.id+'"]');
          if (mc) mc.classList.add('active');
        }}
        const miniPanel = card.closest('.sc-mini-panel');
        if (miniPanel) {{
          miniPanel.style.display='';
          const det = miniPanel.closest('details');
          if (det) det.open=true;
        }}
        const detRow = card.closest('.detail-row');
        if (detRow) detRow.style.display='';
        setTimeout(()=>{{
          card.scrollIntoView({{behavior:'smooth',block:'center'}});
          card.classList.add('search-highlight');
          setTimeout(()=>card.classList.remove('search-highlight'),2000);
        }},80);
      }}
      document.getElementById('search-dropdown').style.display='none';
      document.getElementById('stock-search').value='';
    }}

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
    function openMetaByName(name) {{
      const card = document.querySelector('[data-meta-name="' + name + '"].mc-card');
      if (!card) return;
      const id = card.getAttribute('data-meta');
      const panel = document.getElementById(id);
      if (!panel) return;
      document.querySelectorAll('.mc-panel').forEach(p => p.style.display = 'none');
      document.querySelectorAll('.mc-card.active').forEach(c => c.classList.remove('active'));
      panel.style.display = '';
      card.classList.add('active');
      setTimeout(() => card.scrollIntoView({{behavior:'smooth', block:'center'}}), 50);
    }}
    (function() {{
      const h = decodeURIComponent(location.hash);
      if (h.startsWith('#meta=')) openMetaByName(h.slice(6));
    }})();
    function toggleDetail(row) {{
      const next = row.nextElementSibling;
      if (!next || !next.classList.contains('detail-row')) return;
      const open = next.style.display !== 'none';
      next.style.display = open ? 'none' : '';
      row.classList.toggle('open', !open);
    }}
    function selectMiniCard(id) {{
      const panel = document.getElementById(id);
      const isOpen = panel && panel.style.display !== 'none';
      const card = document.querySelector('[data-mini="' + id + '"]');
      const group = card ? card.closest('details') : null;
      if (group) {{
        group.querySelectorAll('.sc-mini-panel').forEach(p => p.style.display = 'none');
        group.querySelectorAll('.sc-mini-card').forEach(c => c.classList.remove('active'));
      }}
      if (!isOpen && panel) {{
        panel.style.display = '';
        if (card) card.classList.add('active');
      }}
    }}
    function collapseAll() {{
      document.querySelectorAll('details.group-block').forEach(d => d.open = false);
      document.querySelectorAll('.detail-row').forEach(r => r.style.display = 'none');
      document.querySelectorAll('.clickable-sector.open').forEach(r => r.classList.remove('open'));
      document.querySelectorAll('.sc-mini-panel').forEach(p => p.style.display = 'none');
      document.querySelectorAll('.sc-mini-card.active').forEach(c => c.classList.remove('active'));
    }}

    /* ── Stock Modal ── */
    function _modalSparkSVG(pcts) {{
      if (!pcts || !pcts.length) return '';
      const n = pcts.length;
      const maxAbs = Math.max(...pcts.map(Math.abs)) || 1;
      const chartH = 72, midY = chartH / 2;
      const barW = Math.max(8, Math.floor(360 / n) - 3);
      const gap = 3;
      const totalW = n * (barW + gap) - gap + 24;
      let bars = '';
      pcts.forEach((pct, i) => {{
        const x = 12 + i * (barW + gap);
        const barH = Math.max(3, Math.round(Math.abs(pct) / maxAbs * (midY - 5)));
        const up = pct >= 0;
        const y = up ? midY - barH : midY;
        const col = up ? (Math.abs(pct) >= 1 ? '#ef4444' : '#fca5a5') : (Math.abs(pct) >= 1 ? '#22c55e' : '#86efac');
        const sign = up ? '+' : '';
        bars += `<rect x="${{x}}" y="${{y}}" width="${{barW}}" height="${{barH}}" fill="${{col}}" rx="2"><title>${{sign}}${{pct.toFixed(2)}}%</title></rect>`;
      }});
      const zero = `<line x1="10" y1="${{midY}}" x2="${{totalW-10}}" y2="${{midY}}" stroke="#334155" stroke-width="0.8"/>`;
      return `<svg width="${{totalW}}" height="${{chartH}}" xmlns="http://www.w3.org/2000/svg">${{zero}}${{bars}}</svg>`;
    }}

    function openStockModal(el) {{
      const d = el.dataset;
      const pct = parseFloat(d.pct || 0);
      const col = pct > 0 ? '#ef4444' : (pct < 0 ? '#22c55e' : '#64748b');
      const sign = pct >= 0 ? '+' : '';
      const arrow = pct > 0 ? '▲' : (pct < 0 ? '▼' : '─');

      document.getElementById('sm-sid').textContent = d.sid || '';
      document.getElementById('sm-name').textContent = d.name || '';
      document.getElementById('sm-close').textContent = parseFloat(d.close || 0).toLocaleString();
      document.getElementById('sm-pct').innerHTML = `<span style="color:${{col}}">${{arrow}} ${{sign}}${{pct.toFixed(2)}}%</span>`;
      const vol = parseInt(d.vol || 0);
      document.getElementById('sm-vol').textContent = vol ? vol.toLocaleString() + ' 張' : '';

      const spark = d.sparkline ? JSON.parse(d.sparkline) : [];
      document.getElementById('sm-spark').innerHTML = _modalSparkSVG(spark);

      const chips = d.chips ? JSON.parse(d.chips) : {{}};
      let ch = '';
      if (chips.foreign !== undefined) {{
        const fLots = Math.round(chips.foreign / 1000);
        const fc = fLots >= 0 ? '#ef4444' : '#22c55e';
        const fs = fLots >= 0 ? '+' : '';
        ch += `<div class="sm-chip-row"><span class="sm-chip-label">外資</span><span class="sm-chip-val" style="color:${{fc}}">${{fs}}${{fLots.toLocaleString()}} 張</span></div>`;
      }}
      if (chips.trust !== undefined) {{
        const tLots = Math.round(chips.trust / 1000);
        const tc = tLots >= 0 ? '#ef4444' : '#22c55e';
        const ts = tLots >= 0 ? '+' : '';
        ch += `<div class="sm-chip-row"><span class="sm-chip-label">投信</span><span class="sm-chip-val" style="color:${{tc}}">${{ts}}${{tLots.toLocaleString()}} 張</span></div>`;
      }}
      if (chips.marginBal !== undefined) {{
        const mc = chips.marginChg > 0 ? '#f87171' : (chips.marginChg < 0 ? '#4ade80' : '#64748b');
        const ms = chips.marginChg >= 0 ? '+' : '';
        ch += `<div class="sm-chip-row"><span class="sm-chip-label">融資</span><span class="sm-chip-val">${{parseInt(chips.marginBal).toLocaleString()}} 張</span><span class="sm-chip-sub" style="color:${{mc}}">${{ms}}${{parseInt(chips.marginChg).toLocaleString()}}</span></div>`;
      }}
      document.getElementById('sm-chips').innerHTML = ch || '<span style="color:#334155;font-size:.8rem">無籌碼資料</span>';

      document.getElementById('stock-modal').style.display = 'flex';
      document.body.style.overflow = 'hidden';
    }}
    function closeStockModal() {{
      document.getElementById('stock-modal').style.display = 'none';
      document.body.style.overflow = '';
    }}
    function closeModalBg(e) {{
      if (e.target.id === 'stock-modal') closeStockModal();
    }}
    document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeStockModal(); }});

    /* ── Stock Table Sort ── */
    function sortStockTable(th) {{
      const table = th.closest('table');
      const tbody = table.querySelector('tbody');
      const ths = Array.from(th.parentElement.children);
      const key = th.dataset.key;
      const labels = {{'code':'代號','name':'股名','close':'收盤','pct':'今日%','wpct':'近5日','chg7':'近7日','chg10':'近10日','chg14':'近14日','foreign':'外資','trust':'投信','margin':'融資'}};
      const asc = th.dataset.sort !== 'asc';
      ths.forEach(t => {{ t.dataset.sort = ''; t.textContent = labels[t.dataset.key] || ''; }});
      th.dataset.sort = asc ? 'asc' : 'desc';
      th.textContent = labels[key] + (asc ? ' ▲' : ' ▼');
      const rows = Array.from(tbody.querySelectorAll('tr'));
      rows.sort((a, b) => {{
        const av = a.dataset[key] || '', bv = b.dataset[key] || '';
        const an = parseFloat(av), bn = parseFloat(bv);
        if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
        return asc ? av.localeCompare(bv, 'zh-TW') : bv.localeCompare(av, 'zh-TW');
      }});
      rows.forEach(r => tbody.appendChild(r));
    }}

  </script>
</body>
</html>"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
