"""每日推薦：跑所有策略、記成績單、組推薦頁／Telegram 用的 payload（規格 §10）。"""
import duckdb
import pandas as pd

from recommend.cards import build_cards, group_by_sector
from recommend.data import DB_PATH, load_panel
from recommend.features import add_chip_features, add_price_features
from recommend.leaders import leaders
from recommend.market import market_header
from recommend.scorecard import detail, ensure_table, record_signals, refresh, summary
from recommend.strategies import ALL_STRATEGIES

KEEP_DAYS = 3        # C16：推薦在頁面保留 3 個交易日
WARMUP_DAYS = 400    # 日曆天；hi90、MA60、籌碼視窗的預熱


def build_payload(features: pd.DataFrame, day: pd.Timestamp, keep_days: int = KEEP_DAYS, rally_pct=None) -> dict:
    """純函式：new（當天、有效，依族群分組）、active（第 2～N 天有效）、invalid（已失效）、header、
    leaders（近 21 天最強，§10.1）、signals。卡片在近 21 天個股前 20 名時標 top21。"""
    day = pd.Timestamp(day)
    trade_days = sorted(features.loc[features["date"] <= day, "date"].unique())
    window = trade_days[-keep_days:]
    day_n = {pd.Timestamp(d): len(window) - i for i, d in enumerate(window)}
    signals = pd.concat([s.scan(features) for s in ALL_STRATEGIES], ignore_index=True)
    recent = signals[signals["date"].isin(window)]
    cards = build_cards(features, recent, day, rally_pct=rally_pct)
    lead = leaders(features, day)
    top_ids = {r["stock_id"] for r in lead["stocks"]}
    for c in cards:
        c["day_n"] = day_n[pd.Timestamp(c["signal_date"])]
        c["top21"] = c["stock_id"] in top_ids
    valid = [c for c in cards if c["status"] == "有效"]
    return {
        "trade_date": day.date().isoformat(),
        "header": market_header(features, signals, day),
        "new": group_by_sector([c for c in valid if c["day_n"] == 1]),
        "active": sorted([c for c in valid if c["day_n"] > 1], key=lambda c: (c["day_n"], c["stock_id"])),
        "invalid": [c for c in cards if c["status"] == "失效"],
        "leaders": lead,
        "signals": signals,
    }


def run_daily(day=None, db_path: str = DB_PATH, keep_days: int = KEEP_DAYS) -> dict:
    """收盤流程用：載入（含預熱）→ 特徵 → payload → 寫成績單。回傳可 JSON 序列化的 payload（含 scorecard）。"""
    start = None
    if day is not None:
        start = (pd.Timestamp(day) - pd.Timedelta(days=WARMUP_DAYS)).date().isoformat()
    feats = add_chip_features(add_price_features(load_panel(db_path=db_path, start=start)))
    day = pd.Timestamp(day) if day is not None else feats["date"].max()
    payload = build_payload(feats, day, keep_days)
    con = duckdb.connect(db_path)
    try:
        ensure_table(con)
        signals = payload.pop("signals")
        # 記保留期內所有訊號（已存在的會跳過）：某天收盤失敗時，隔天還能補記那天的訊號
        window = sorted(feats.loc[feats["date"] <= day, "date"].unique())[-keep_days:]
        record_signals(con, signals[signals["date"].isin(window)], feats)
        refresh(con, feats)
        payload["scorecard"] = {s.name: summary(con, s.name) for s in ALL_STRATEGIES}
        names = feats.drop_duplicates("stock_id", keep="last").set_index("stock_id")["stock_name"]
        payload["scorecard_rows"] = {s.name: [{**r, "stock_name": names.get(r["stock_id"], "")}
                                              for r in detail(con, s.name)] for s in ALL_STRATEGIES}
    finally:
        con.close()
    return json_safe(payload)


def json_safe(obj):
    """NaN／numpy 數字轉成 JSON 合法值（NaN → None），瀏覽器 JSON.parse 才不會報錯。"""
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, float) or hasattr(obj, "item"):
        v = obj.item() if hasattr(obj, "item") else obj
        return None if isinstance(v, float) and v != v else v
    return obj
