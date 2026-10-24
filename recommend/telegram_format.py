"""Telegram 推薦訊息（規格 E21）：精簡、不用 emoji、等寬表格、中文放每列最後（手機上中文佔兩格會對不齊）。"""
from html import escape

MAX_ROWS = 15


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def compose_recommend_message(payload: dict, taiex_above_ma20: bool | None, site_url: str) -> str:
    """parse_mode=HTML：表格放 <pre>，所有內容都做 HTML 跳脫。"""
    d = payload["trade_date"]
    h = payload["header"]
    market = [f"MA20上 {_pct(h.get('above_ma20_pct'))}", f"失敗率 {_pct(h.get('fail_rate'))}"]
    if taiex_above_ma20 is not None:
        market.append("加權>MA20" if taiex_above_ma20 else "加權<MA20")
    market.append(f"漲停 {h.get('limit_up', 0)} 跌停 {h.get('limit_down', 0)}")
    lines = ["股號   型態 條  收盤     漲幅    提醒     名稱", "-" * 46]
    shown = total = 0
    for g in payload["new"]:
        total += g["count"]
        if shown >= MAX_ROWS:
            continue
        lines.append(f"[{g['sector']} {g['count']}檔]")
        for c in g["cards"]:
            if shown >= MAX_ROWS:
                break
            alert = "、".join(c["alerts"])
            lines.append(f"{c['stock_id']:<6} {c['type']} {c['n_routes']:>2} {c['close']:>8.1f} "
                         f"{c['change_pct']:>+6.1f}%  {alert:<6} {c['stock_name']}")
            shown += 1
    lines.append("-" * 46)
    if total > shown:
        lines.append(f"另 {total - shown} 檔見頁面")
    table = escape("\n".join(lines))
    head = escape(f"個股推薦 {d[5:7]}/{d[8:10]} 收盤\n{'｜'.join(market)}")
    tail = escape(f"新 {total} 檔｜有效中 {len(payload['active'])} 檔｜失效 {len(payload['invalid'])} 檔\n{site_url}")
    return f"{head}\n\n<pre>{table}</pre>\n{tail}"
