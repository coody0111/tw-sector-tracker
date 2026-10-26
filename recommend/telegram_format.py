"""Telegram 推薦訊息（規格 E21）：精簡、不用 emoji、等寬表格、中文放每列最後（手機上中文佔兩格會對不齊）。"""
import unicodedata
from html import escape

MAX_ROWS = 15
SHORT_ALERTS = {"族群獨漲": "獨漲"}   # 提醒欄寬 6（「乖離大」）；「族群獨漲」寬 8 會把名稱欄推歪，Telegram 用簡寫


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def _width(s: str) -> int:
    """等寬字體裡的顯示寬度：全形／中文算 2 格。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def _pad(s: str, width: int, right: bool = False) -> str:
    gap = " " * max(0, width - _width(s))
    return gap + s if right else s + gap


def _row(cols: list) -> str:
    """cols：(文字, 寬度, 是否靠右)。依顯示寬度補空白，中文欄也能對齊。"""
    return " ".join(_pad(text, w, right) for text, w, right in cols).rstrip()


def _card_row(c: dict) -> str:
    chg = "—" if c.get("change_pct") is None else f"{c['change_pct']:+.1f}%"
    return _row([(str(c["stock_id"]), 6, False), (c["type"], 4, False), (str(c["n_routes"]), 2, True),
                 (f"{c['close']:.1f}", 8, True), (chg, 7, True), ("、".join(SHORT_ALERTS.get(a, a) for a in c["alerts"]), 6, False),
                 (str(c["stock_name"]), 0, False)])


def compose_recommend_message(payload: dict, taiex_above_ma20: bool | None, site_url: str, label: str = "收盤") -> str:
    """parse_mode=HTML：表格放 <pre>，所有內容都做 HTML 跳脫。label：「收盤」或「開盤前更新」。"""
    d = payload["trade_date"]
    h = payload["header"]
    market = [f"MA20上 {_pct(h.get('above_ma20_pct'))}", f"失敗率 {_pct(h.get('fail_rate'))}"]
    if taiex_above_ma20 is not None:
        market.append("加權>MA20" if taiex_above_ma20 else "加權<MA20")
    market.append(f"漲停 {h.get('limit_up', 0)} 跌停 {h.get('limit_down', 0)}")
    header = _row([("股號", 6, False), ("型態", 4, False), ("條", 2, True), ("收盤", 8, True),
                   ("漲幅", 7, True), ("提醒", 6, False), ("名稱", 0, False)])
    rule = "-" * 46
    lines = [header, rule]
    shown = total = 0
    for g in payload["new"]:
        total += g["count"]
        if shown >= MAX_ROWS:
            continue
        lines.append(f"[{g['sector']} {g['count']}檔]")
        for c in g["cards"]:
            if shown >= MAX_ROWS:
                break
            lines.append(_card_row(c))
            shown += 1
    lines.append(rule)
    if total > shown:
        lines.append(f"另 {total - shown} 檔見頁面")
    table = escape("\n".join(lines))
    head = escape(f"個股推薦 {d[5:7]}/{d[8:10]} {label}\n{'｜'.join(market)}")
    tail = escape(f"新 {total} 檔｜有效中 {len(payload['active'])} 檔｜失效 {len(payload['invalid'])} 檔\n{site_url}")
    return f"{head}\n\n<pre>{table}</pre>\n{tail}"


def compose_preopen_message(payload: dict, added: list, withdrawn: list, site_url: str) -> str | None:
    """開盤前更新：只列比收盤版多出來的新訊號（表格）＋撤回的股票與理由；兩者都沒有回 None（不發）。"""
    added = set(added or [])
    if not added and not withdrawn:
        return None
    label = "開盤前更新（集保）"
    if added:
        groups = [{**g, "count": len(cs), "cards": cs} for g in payload.get("new") or []
                  if (cs := [c for c in g["cards"] if c["stock_id"] in added])]
        msg = compose_recommend_message({**payload, "new": groups}, payload.get("taiex_above_ma20"), site_url, label)
    else:
        d = payload["trade_date"]
        msg = escape(f"個股推薦 {d[5:7]}/{d[8:10]} {label}\n{site_url}")
    if withdrawn:
        lines = [f"撤回 {len(withdrawn)} 檔（集保更新後不再符合，開盤先不要買）："]
        lines += [f"{w['stock_id']} {w.get('stock_name') or ''}：{w['reason']}" for w in withdrawn]
        msg += "\n\n" + escape("\n".join(lines))
    return msg
