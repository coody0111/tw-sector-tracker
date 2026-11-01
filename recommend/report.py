"""每日報告資料（規格 docs/superpowers/specs/2026-11-01-daily-report.md）。
輸入是推薦 payload，再加上籌碼彙總；今日重點與明日觀察都由固定規則產生，數字跟表格同源。
籌碼金額是股票池合計（約 1,036 檔），不是全市場官方總額。"""
import duckdb
import pandas as pd

from recommend.daily import KEEP_DAYS
from recommend.data import DB_PATH, UNIVERSE_PATH

TOP_SECTORS = 5
TOP_BIG = 3
BREADTH_LINE = 0.5        # 站上 20 日線比例的多空分界（Cody 2026-11-01 第 7 題 A）


def market_tone(taiex_above_ma20: bool | None, above_ma20_pct: float | None) -> str | None:
    """兩項都偏多→偏多、都偏空→偏空、其他→中性；缺資料回 None（頁面不下判斷）。只描述現況，不是買賣訊號。"""
    if taiex_above_ma20 is None or above_ma20_pct is None:
        return None
    wide = above_ma20_pct >= BREADTH_LINE
    if taiex_above_ma20 and wide:
        return "偏多"
    if not taiex_above_ma20 and not wide:
        return "偏空"
    return "中性"


def chips_summary(day: str, missing: list | None = None, db_path: str = DB_PATH,
                  universe_path: str = UNIVERSE_PATH) -> dict | None:
    """當日外資、投信買賣超（億）、族群買賣超前 5、融資增減（張）；當天沒有法人資料回 None。
    暫定版缺一邊市場的三大法人時也回 None：只算另一邊會寫成合計，10-27 實測方向相反（Debugger 2026-11-01）。
    融資不在發布檢查內，只到一邊市場時融資顯示「—」。"""
    if any("三大法人" in m for m in missing or []):
        return None
    uni = pd.read_csv(universe_path, dtype=str, encoding="utf-8-sig")[["stock_id", "meta_sector", "exchange"]]
    con = duckdb.connect(db_path, read_only=True)
    try:
        inst = con.execute(
            "SELECT i.stock_id, i.foreign_net, i.trust_net, p.close FROM institutional i "
            "JOIN daily_prices p ON i.stock_id = p.stock_id AND i.date = p.date WHERE i.date = ?", [day]).df()
        margin = con.execute("SELECT stock_id, margin_change FROM margin WHERE date = ?", [day]).df()
    finally:
        con.close()
    inst = inst.merge(uni, on="stock_id")
    if inst.empty:
        return None
    foreign = inst["foreign_net"] * inst["close"] / 1e8
    trust = inst["trust_net"] * inst["close"] / 1e8
    by_sector = (foreign + trust).groupby(inst["meta_sector"]).sum().sort_values()
    margin = margin.merge(uni, on="stock_id")
    return {
        "foreign": round(float(foreign.sum()), 1),
        "trust": round(float(trust.sum()), 1),
        "margin_change": int(margin["margin_change"].sum()) if margin["exchange"].nunique() == 2 else None,
        "buy": [{"sector": k, "net": round(float(v), 1)}
                for k, v in by_sector[by_sector > 0].iloc[::-1].head(TOP_SECTORS).items()],
        "sell": [{"sector": k, "net": round(float(v), 1)} for k, v in by_sector[by_sector < 0].head(TOP_SECTORS).items()],
    }


def _big_holders(payload: dict) -> dict | None:
    """週資料日才有：大戶增加、減少最多的族群各 3 個。"""
    if payload.get("shareholder_date") != payload["trade_date"]:
        return None
    rows = [s for s in (payload.get("heat") or {}).get("sectors") or [] if s.get("big_chg") is not None]
    rows = sorted(rows, key=lambda s: s["big_chg"], reverse=True)
    pick = lambda xs: [{"sector": s["sector"], "chg": s["big_chg"]} for s in xs]
    return {"up": pick([s for s in rows if s["big_chg"] > 0][:TOP_BIG]),
            "down": pick([s for s in reversed(rows) if s["big_chg"] < 0][:TOP_BIG])} if rows else None


def _money(v: float) -> str:
    return f"{abs(v):,.0f} 億"


def _market_point(p: dict) -> str | None:
    if p.get("taiex_close") is None:
        return None
    gap = p.get("taiex_ma20_gap")
    side = "" if gap is None else f"，{'高於' if gap >= 0 else '低於'} 20 日線 {abs(gap) * 100:.1f}%"
    pct = p["header"].get("above_ma20_pct")
    breadth = "" if pct is None else f"。{pct * 100:.1f}% 的股票站上 20 日線"
    chg = p.get("taiex_change_pct")
    move = "" if chg is None else f"，{'漲' if chg >= 0 else '跌'} {abs(chg):.2f}%"
    return f"加權 {p['taiex_close']:,.2f}{move}{side}{breadth}。"


def _chips_point(c: dict | None) -> str | None:
    if not c:
        return None
    verb = lambda v: "買超" if v >= 0 else "賣超"
    text = f"外資{verb(c['foreign'])} {_money(c['foreign'])}，投信{verb(c['trust'])} {_money(c['trust'])}"
    flow, label = (c["buy"], "買盤") if c["foreign"] + c["trust"] >= 0 else (c["sell"], "賣壓")
    names = "、".join(s["sector"] for s in flow[:2])
    return f"{text}。{label}集中在{names}。" if names else f"{text}。"


def _signal_point(p: dict, new_n: int) -> str:
    fail = p["header"].get("fail_rate")
    tail = "" if fail is None else f"。近期突破失敗率 {fail * 100:.0f}%（{p['header'].get('fail_n', 0)} 筆）"
    return f"新訊號 {new_n} 檔，有效中 {len(p['active'])} 檔{tail}。"


def _watch(p: dict, tone: str | None, missing: list) -> list:
    renewed = {c["stock_id"] for g in p["new"] for c in g["cards"]}      # 同股又出新訊號，舊訊號到期不用提醒
    lines = [f"{c['stock_name']} 已是第 {c['day_n']} 天，下個交易日起不再列入有效名單。"
             for c in p["active"] if c["day_n"] >= KEEP_DAYS and c["stock_id"] not in renewed]
    if tone == "偏空":
        lines.append("大盤在 20 日線下、站上比例偏低，新倉位要保守。")
    lines.append(f"暫定：缺{'、'.join(missing)}。資料到齊後會更新這份報告。" if missing else "資料已到齊。")
    return lines


def build_report(payload: dict, chips: dict | None) -> dict:
    missing = payload.get("missing") or []
    tone = market_tone(payload.get("taiex_above_ma20"), payload["header"].get("above_ma20_pct"))
    new = [c for g in payload["new"] for c in g["cards"]]
    signal = f"新訊號 {len(new)} 檔" if new else "今天沒有新訊號"
    return {
        "date": payload["trade_date"],
        "tone": tone,
        "title": f"大盤{tone}，{signal}" if tone else signal,
        "points": [x for x in (_market_point(payload), _chips_point(chips), _signal_point(payload, len(new))) if x],
        "market": {**payload["header"], **{k: payload.get(k) for k in
                                           ("taiex_close", "taiex_change", "taiex_change_pct", "taiex_ma20_gap")}},
        "chips": chips,
        "big_holders": _big_holders(payload),
        "sectors": ((payload.get("heat") or {}).get("top") or [])[:TOP_SECTORS],
        "new": new,
        "active": payload["active"],
        "withdrawn": payload.get("withdrawn") or [],
        "invalid_n": len(payload["invalid"]),
        "watch": _watch(payload, tone, missing),
        "missing": missing,
    }
