"""Telegram 查股（2026-11-02 Cody）：打股號或名稱回一則精簡個股資訊；另有 /推薦 /一字鎖 /熱度 /報告。
只讀 DB 與 data/recommend_payload.json，不跑任何資料更新。回覆是純文字（不用 parse_mode），內容不必跳脫。"""
import json
import os
from pathlib import Path

import duckdb
import pandas as pd

from recommend.data import DB_PATH, EVENTS_PATH, UNIVERSE_PATH, adj_multiplier, event_factors

PAYLOAD_PATH = Path("data/recommend_payload.json")
SITE_URL = os.environ.get("SITE_URL", "https://coody0111.github.io/tw-sector-tracker/").rstrip("/") + "/"
MAX_CANDIDATES = 8
HISTORY_DAYS = 260
WINDOW = 5                 # 法人、融資、外資持股都看 5 個交易日
BUSY = "資料庫正在更新，請 1～2 分鐘後再試。"
HELP = ("查股：直接打股號或名稱，例如 3147、大綜。\n"
        "指令：/推薦 /一字鎖 /熱度 /報告")


def _md(d) -> str:
    s = str(d)[:10]
    return f"{s[5:7]}/{s[8:10]}"


def _pct(v, nd: int = 1, suffix: str = "%") -> str:
    return "—" if v is None or pd.isna(v) else f"{v:+.{nd}f}{suffix}".replace("-", "−")


def _load_payload(path: Path = PAYLOAD_PATH) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def find_stocks(query: str, universe: pd.DataFrame) -> pd.DataFrame:
    """股號完全相同優先；否則名稱完全相同；再來名稱包含（忽略 * 與大小寫）。"""
    q = query.strip()
    hit = universe[universe["stock_id"] == q]
    if len(hit):
        return hit
    names = universe["stock_name"].str.replace("*", "", regex=False).str.lower()
    key = q.replace("*", "").lower()
    exact = universe[names == key]
    return exact if len(exact) else universe[names.str.contains(key, regex=False)]


def _marks(sid: str, sector: str, payload: dict) -> str:
    marks = []
    for g in payload.get("new") or []:
        if any(c["stock_id"] == sid for c in g["cards"]):
            marks.append("今日新訊號")
    for c in payload.get("active") or []:
        if c["stock_id"] == sid:
            marks.append(f"推薦第 {c['day_n']} 天")
    if any(c["stock_id"] == sid for c in payload.get("invalid") or []):
        marks.append("推薦已失效")
    for r in payload.get("one_word") or []:
        if r["stock_id"] == sid:
            marks.append(f"一字鎖 近10日{r['count']}次" + (f"(連{r['streak']})" if r["streak"] > 1 else ""))
    for s in (payload.get("heat") or {}).get("sectors") or []:
        if s["sector"] == sector:
            marks.append(f"族群熱度 #{s['rank']}")
    return "｜".join(marks) or "無"


def _ema(s: pd.Series, n: int) -> float:
    return float(s.ewm(span=n, adjust=False).mean().iloc[-1])


def _adjusted(px: pd.DataFrame, sid: str, events_path: str) -> pd.Series:
    """均線、52 週高、21 日用還原價（除權息的下跳不算跌）；沒有事件表就用原始價。顯示的收盤仍是原始價。"""
    try:
        events = pd.read_csv(events_path, dtype={"stock_id": str})
    except FileNotFoundError:
        return px["close"]
    x = px.assign(stock_id=sid, date=pd.to_datetime(px["date"]))
    return px["close"] * adj_multiplier(x, event_factors(events[events["stock_id"] == sid], x)).to_numpy()


def _days(con, table: str, peers: list, n: int) -> list:
    """籌碼的 n 個交易日窗口（新到舊）：同市場（上市／上櫃）這張表最新的資料日往回數 daily_prices 的交易日。
    表裡只存有變動的日子，不能用 LIMIT n 筆（bug-reports 2026-11-02：8272 跨了 8 個交易日）；窗口內沒資料的日子算 0。"""
    last = con.execute(f"SELECT max(date) FROM {table} WHERE stock_id = ANY(?)", [peers]).fetchone()[0]
    if last is None:
        return []
    return [r[0] for r in con.execute("SELECT DISTINCT date FROM daily_prices WHERE date <= ? ORDER BY date DESC LIMIT ?",
                                      [last, n]).fetchall()]


def _asof_value(con, col: str, table: str, sid: str, d):
    """sid 在 d（含）之前最後一筆的值；沒有就 None。"""
    r = con.execute(f"SELECT {col} FROM {table} WHERE stock_id = ? AND date <= ? ORDER BY date DESC LIMIT 1",
                    [sid, d]).fetchone()
    return None if r is None else r[0]


def stock_card(row: pd.Series, con, payload: dict, events_path: str = EVENTS_PATH,
               universe_ids: dict | None = None) -> str:
    """精簡版 8 行：行情、均線、位置、法人與外資、大戶與融資、營收、系統標記。籌碼日期跟行情不同天時標出來。"""
    sid = row["stock_id"]
    universe_ids = universe_ids or {}
    px = con.execute("SELECT date, close, change_pct, volume FROM daily_prices WHERE stock_id = ? "
                     "ORDER BY date DESC LIMIT ?", [sid, HISTORY_DAYS]).df().iloc[::-1].reset_index(drop=True)
    head = f"{sid} {row['stock_name']}｜{row['meta_sector']}"
    if px.empty:
        return f"{head}\n沒有行情資料。"
    c, last = _adjusted(px, sid, events_path), px.iloc[-1]
    day = _md(last["date"])
    vr = last["volume"] / px["volume"].iloc[-21:-1].mean() if len(px) > 21 else None
    ma60 = c.iloc[-60:].mean() if len(c) >= 60 else None
    lines = [
        f"{head}｜{day} 收盤",
        f"{last['close']:,.2f}  {_pct(last['change_pct'], 2)}  量 {int(last['volume']):,} 張"
        + ("" if vr is None else f"（量比 {vr:.1f}）"),
        f"距 10EMA {_pct((c.iloc[-1] / _ema(c, 10) - 1) * 100)}｜20EMA {_pct((c.iloc[-1] / _ema(c, 20) - 1) * 100)}｜"
        + ("季線資料不足" if ma60 is None else ("季線上" if c.iloc[-1] >= ma60 else "季線下")),
        f"離 52 週高 {_pct((c.iloc[-1] / c.iloc[-250:].max() - 1) * 100)}｜21 日 "
        + (_pct((c.iloc[-1] / c.iloc[-22] - 1) * 100) if len(c) > 21 else "—"),
    ]
    peers = list(universe_ids.get(row.get("exchange"), [sid]))
    inst_days = _days(con, "institutional", peers, WINDOW)
    inst = con.execute("SELECT sum(foreign_net + trust_net) FROM institutional WHERE stock_id = ? AND date = ANY(?)",
                       [sid, inst_days]).fetchone()[0] if inst_days else None
    inst_txt = "法人 5 日 —" if not inst_days else (
        f"法人 5 日 {int((inst or 0) / 1000):+,} 張" + _asof(inst_days[0], day))
    fh_days = _days(con, "foreign_holdings", peers, WINDOW + 1)
    fh = [_asof_value(con, "foreign_pct", "foreign_holdings", sid, d) for d in (fh_days[:1] + fh_days[-1:])]         if len(fh_days) == WINDOW + 1 else [None, None]
    fh_txt = "外資持股 —" if None in fh else (
        f"外資持股 {_pct(fh[0] - fh[1], 2, 'pp')}" + _asof(fh_days[0], day))
    lines.append(f"{inst_txt}｜{fh_txt}".replace("-", "−"))
    big = con.execute("SELECT date, week_chg FROM shareholder WHERE stock_id = ? ORDER BY date DESC LIMIT 1", [sid]).df()
    mg_days = _days(con, "margin", peers, WINDOW)
    mg = con.execute("SELECT sum(margin_change) FROM margin WHERE stock_id = ? AND date = ANY(?)",
                     [sid, mg_days]).fetchone()[0] if mg_days else None
    big_txt = "大戶週增 —" if big.empty or pd.isna(big["week_chg"].iloc[0]) else (
        f"大戶週增 {_pct(big['week_chg'].iloc[0], 2, 'pp')}（集保 {_md(big['date'].iloc[0])}）")
    mg_txt = "融資 5 日 —" if not mg_days else f"融資 5 日 {int(mg or 0):+,} 張" + _asof(mg_days[0], day)
    lines.append(f"{big_txt}｜{mg_txt}".replace("-", "−"))
    rev = con.execute("SELECT revenue_month, reported_yoy_pct FROM monthly_revenue WHERE stock_id = ? "
                      "ORDER BY revenue_month DESC LIMIT 1", [sid]).df()
    lines.append("營收 —" if rev.empty else
                 f"營收 {int(str(rev['revenue_month'].iloc[0])[5:7])} 月 年增 {_pct(rev['reported_yoy_pct'].iloc[0])}")
    lines.append(f"標記：{_marks(sid, row['meta_sector'], payload)}")
    return "\n".join(lines)


def _asof(d, price_day: str) -> str:
    return "" if _md(d) == price_day else f"（至 {_md(d)}）"


def lookup(query: str, db_path: str = DB_PATH, universe_path: str = UNIVERSE_PATH,
           payload_path: Path = PAYLOAD_PATH) -> str:
    universe = pd.read_csv(universe_path, dtype=str, encoding="utf-8-sig")
    hits = find_stocks(query, universe)
    if hits.empty:
        return f"找不到「{query}」。\n{HELP}"
    if len(hits) > 1:
        names = "、".join(f"{r.stock_id} {r.stock_name}" for r in hits.head(MAX_CANDIDATES).itertuples())
        more = f" 等 {len(hits)} 檔" if len(hits) > MAX_CANDIDATES else ""
        return f"有 {len(hits)} 檔符合，請打股號：{names}{more}"
    try:
        con = duckdb.connect(db_path, read_only=True)
    except duckdb.Error:                 # 排程正在寫 DB 時拿不到鎖
        return BUSY
    try:
        ids = universe.groupby("exchange")["stock_id"].apply(list).to_dict() if "exchange" in universe else {}
        return stock_card(hits.iloc[0], con, _load_payload(payload_path), universe_ids=ids)
    finally:
        con.close()


def _cmd_recommend(p: dict) -> str:
    if not p:
        return "還沒有推薦資料。"
    new = [c for g in p.get("new") or [] for c in g["cards"]]
    names = "、".join(f"{c['stock_id']} {c['stock_name']}" for c in new[:15]) or "沒有新訊號"
    return (f"{_md(p['trade_date'])} 推薦\n新訊號 {len(new)} 檔：{names}\n"
            f"仍有效 {len(p.get('active') or [])} 檔｜已失效 {len(p.get('invalid') or [])} 檔\n{SITE_URL}recommend.html")


def _cmd_one_word(p: dict) -> str:
    rows = p.get("one_word") or []
    if not rows:
        return "近 10 個交易日沒有一字鎖。"
    lines = [f"{r['stock_id']} {r['stock_name']} {_md(r['last_date'])} {r['count']}次"
             + (f" 連{r['streak']}" if r["streak"] > 1 else "") + f" 量{r['volume']:,}張" for r in rows]
    return "近 10 個交易日一字鎖：\n" + "\n".join(lines) + f"\n{SITE_URL}recommend.html"


def _cmd_heat(p: dict) -> str:
    top = ((p.get("heat") or {}).get("top") or [])[:5]
    if not top:
        return "還沒有熱度資料。"
    lines = [f"{s['rank']}. {s['sector']} 熱度{s['score']:.0f} 21日{_pct(s.get('ret21'))} {s['status']}" for s in top]
    return "族群熱度前 5：\n" + "\n".join(lines) + f"\n{SITE_URL}index.html#heat"


def _cmd_report(p: dict) -> str:
    return f"每日報告：{SITE_URL}report.html\n每週籌碼：{SITE_URL}weekly.html"


COMMANDS = {"推薦": _cmd_recommend, "一字鎖": _cmd_one_word, "熱度": _cmd_heat, "報告": _cmd_report}


def handle(text: str, db_path: str = DB_PATH, universe_path: str = UNIVERSE_PATH,
           payload_path: Path = PAYLOAD_PATH) -> str:
    """一則訊息 → 回覆文字。/help、/start、空白都回說明。"""
    t = (text or "").strip()
    key = t.lstrip("/").split("@")[0]
    if not key or key.lower() in ("help", "start", "說明"):
        return HELP
    if key in COMMANDS:
        return COMMANDS[key](_load_payload(payload_path))
    return lookup(key, db_path, universe_path, payload_path)
