"""每週籌碼報告資料（規格 docs/superpowers/specs/2026-11-01-weekly-chips.md）。
集保資料日 D 到齊後產一次：指數、台指期、融資維持率(估)的大盤與個股、大戶與融資增減。
融資維持率是估計值（docs/adr/0002-margin-maintenance-ratio-is-an-estimate.md），融資與大戶都是股票池合計。"""
import json
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd

from recommend.data import DB_PATH, UNIVERSE_PATH
from screener.data_integrity import market_day_complete

FUTURES_PATH = Path("data/futures_daily.csv")
ARCHIVE_DIR = Path("docs/weekly")
WEEKLY_PATH = Path("data/weekly_chips.json")          # 最新一份報告，通知失敗時下次排程直接重發
NOTIFIED_PATH = Path("data/weekly_notified.txt")      # 已成功通知的資料日；只有排程發送成功才寫
TOP_HOLDERS = 10
TOP_SECTORS = 5
TOP_MARGIN = 5
MA_DAYS = 60
AVG_DAYS = 20
DANGER = 130
WATCH = 150
FINANCING = {"TWSE": 0.6, "TPEx": 0.5}      # 注意股、處置股的例外成數不處理，同 export/index_generator.py


def notified_date(path: Path = NOTIFIED_PATH) -> str | None:
    return path.read_text(encoding="utf-8").strip() if path.exists() else None


def mark_notified(day: str, path: Path = NOTIFIED_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(day, encoding="utf-8")


def save_weekly(weekly: dict, path: Path = WEEKLY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(weekly, ensure_ascii=False, default=str), encoding="utf-8")


def load_weekly(day: str, path: Path = WEEKLY_PATH) -> dict | None:
    if not path.exists():
        return None
    weekly = json.loads(path.read_text(encoding="utf-8"))
    return weekly if weekly.get("date") == day else None


def save_futures_snapshot(row: dict, path: Path = FUTURES_PATH) -> None:
    """同一天重跑覆蓋，只留最新一筆。"""
    old = pd.read_csv(path, dtype={"date": str, "contract": str}) if path.exists() else pd.DataFrame()
    keep = old[old["date"] != row["date"]] if len(old) else old
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.concat([keep, pd.DataFrame([row])], ignore_index=True).sort_values("date").to_csv(path, index=False)


def load_futures_rows(day: str, path: Path = FUTURES_PATH) -> tuple[dict | None, dict | None]:
    """回傳 D 當天的台指期，以及上一週最後一筆（算未平倉週變化；還沒累積到就是 None）。"""
    if not path.exists():
        return None, None
    df = pd.read_csv(path, dtype={"date": str, "contract": str})
    now = df[df["date"] == day]
    prev = df[df["date"] < _monday(day)]
    to_dict = lambda x: x.iloc[-1].to_dict() if len(x) else None
    return to_dict(now), to_dict(prev)


def _monday(day: str) -> str:
    d = date.fromisoformat(day)
    return (d - timedelta(days=d.weekday())).isoformat()


def latest_shareholder_date(db_path: str = DB_PATH) -> str | None:
    con = duckdb.connect(db_path, read_only=True)
    try:
        d = con.execute("SELECT max(date) FROM shareholder").fetchone()[0]
    finally:
        con.close()
    return str(d)[:10] if d else None


def inputs_ready(day: str, db_path: str = DB_PATH, universe_path: str = UNIVERSE_PATH) -> bool:
    """D 的行情與兩邊市場的融資都到齊（筆數到門檻，不是只有幾檔）才出報告。"""
    uni = pd.read_csv(universe_path, dtype=str, encoding="utf-8-sig")[["stock_id", "exchange"]]
    ids = {ex: set(uni.loc[uni["exchange"] == ex, "stock_id"]) for ex in ("TWSE", "TPEx")}
    con = duckdb.connect(db_path, read_only=True)
    try:
        return all(market_day_complete(con, table, day, ids[ex]) for table in ("daily_prices", "margin") for ex in ids)
    finally:
        con.close()


def index_row(name: str, rows: list, day: str) -> dict | None:
    """當日、本週（對上週最後收盤）、距 60 日線；D 當天沒有資料回 None。"""
    x = sorted(((str(r["date"])[:10], r["close"]) for r in rows if str(r["date"])[:10] <= day))
    if not x or x[-1][0] != day or len(x) < 2:
        return None
    close = x[-1][1]
    base = [c for d, c in x if d < _monday(day)]
    return {"name": name, "close": close, "day_pct": (close / x[-2][1] - 1) * 100,
            "week_pct": (close / base[-1] - 1) * 100 if base else None,
            "ma60_pct": (close / (sum(c for _, c in x[-MA_DAYS:]) / MA_DAYS) - 1) * 100 if len(x) >= MA_DAYS else None}


def maintenance(df: pd.DataFrame) -> dict:
    """df 欄位 close、avg、balance、exchange。大盤值用融資市值加權：總市值 ÷ 總融資額。"""
    x = df[(df["balance"] > 0) & df["exchange"].isin(FINANCING)].copy()
    x["financing"] = x["exchange"].map(FINANCING)
    x["ratio"] = x["close"] / x["avg"] / x["financing"] * 100
    x["value"] = x["close"] * x["balance"]

    def pooled(p: pd.DataFrame) -> float | None:
        loan = (p["avg"] * p["balance"] * p["financing"]).sum()
        return float(p["value"].sum() / loan * 100) if loan else None

    cols = ["stock_id", "stock_name", "balance", "close", "avg", "ratio"]
    return {"all": pooled(x), "twse": pooled(x[x["exchange"] == "TWSE"]), "tpex": pooled(x[x["exchange"] == "TPEx"]),
            "n": len(x), "below_watch": int((x["ratio"] < WATCH).sum()), "below_danger": int((x["ratio"] < DANGER).sum()),
            "danger": x[x["ratio"] < DANGER].sort_values("ratio")[cols].to_dict("records"),
            "largest": x.nlargest(TOP_HOLDERS, "value")[cols].to_dict("records")}


def _points(w: dict) -> list:
    points = [f"大戶增加 {w['holders_up_n']} 檔、減少 {w['holders_down_n']} 檔。"]
    weekly = [f"{r['name']}本週 {r['week_pct']:+.2f}%" for r in w["indices"] if r["week_pct"] is not None]
    if weekly:
        points.append("、".join(weekly).replace("-", "−") + "。")
    f = w["futures"]
    if f:
        points.append(f"外資台指期淨{'多' if f['foreign_net'] >= 0 else '空'}單 {abs(int(f['foreign_net'])):,} 口。")
    verb = "增加" if w["margin_total"] >= 0 else "減少"
    ratio = w["maintenance"]["all"]
    points.append(f"融資本週{verb} {abs(w['margin_total']):,} 張" + (f"，大盤融資維持率（估）{ratio:.1f}%。" if ratio else "。"))
    points.append(f"融資維持率（估）低於 {DANGER}% 有 {w['maintenance']['below_danger']} 檔。")
    return points


def build_weekly(day: str, indices: list, futures: dict | None, futures_prev: dict | None, sectors: list,
                 db_path: str = DB_PATH, universe_path: str = UNIVERSE_PATH) -> dict:
    uni = pd.read_csv(universe_path, dtype=str, encoding="utf-8-sig")[["stock_id", "stock_name", "meta_sector", "exchange"]]
    con = duckdb.connect(db_path, read_only=True)
    try:
        holders = con.execute("SELECT stock_id, lv12_15_pct, week_chg, streak FROM shareholder WHERE date = ?", [day]).df()
        margin = con.execute("SELECT stock_id, sum(margin_change) AS chg FROM margin WHERE date >= ? AND date <= ? GROUP BY 1",
                             [_monday(day), day]).df()
        balance = con.execute("SELECT stock_id, margin_balance AS balance FROM margin WHERE date = ?", [day]).df()
        days = [r[0] for r in con.execute("SELECT DISTINCT date FROM daily_prices WHERE date <= ? ORDER BY date DESC LIMIT ?",
                                          [day, AVG_DAYS]).fetchall()]
        px = con.execute("SELECT stock_id, avg(close) AS avg, arg_max(close, date) AS close FROM daily_prices "
                         "WHERE date >= ? AND date <= ? GROUP BY 1", [min(days), day]).df()
    finally:
        con.close()
    holders = holders.dropna(subset=["week_chg"]).merge(uni, on="stock_id")
    margin = margin.merge(uni, on="stock_id")
    pick = lambda df: df[["stock_id", "stock_name", "meta_sector", "lv12_15_pct", "week_chg", "streak"]].to_dict("records")
    rise, fall = holders[holders["week_chg"] > 0], holders[holders["week_chg"] < 0]
    sectors = sorted((s for s in sectors if s.get("big_chg") is not None), key=lambda s: s["big_chg"])
    move = lambda df: [{"name": r.stock_name, "chg": int(r.chg)} for r in df.itertuples()]
    report = {
        "date": day,
        "indices": indices,
        "futures": futures,
        "futures_oi_change": (int(futures["foreign_net"] - futures_prev["foreign_net"]) if futures and futures_prev else None),
        "maintenance": maintenance(px.merge(balance, on="stock_id").merge(uni, on="stock_id")),
        "holders_up_n": len(rise),
        "holders_down_n": len(fall),
        "holders_up": pick(rise.nlargest(TOP_HOLDERS, "week_chg")),
        "holders_down": pick(fall.nsmallest(TOP_HOLDERS, "week_chg")),
        "sectors_up": [s for s in sectors[::-1][:TOP_SECTORS] if s["big_chg"] > 0],
        "sectors_down": [s for s in sectors[:TOP_SECTORS] if s["big_chg"] < 0],
        "margin_total": int(margin["chg"].sum()),
        "margin_up": move(margin[margin["chg"] > 0].nlargest(TOP_MARGIN, "chg")),
        "margin_down": move(margin[margin["chg"] < 0].nsmallest(TOP_MARGIN, "chg")),
    }
    return {**report, "points": _points(report)}
