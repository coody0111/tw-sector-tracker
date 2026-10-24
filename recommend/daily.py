"""每日推薦：跑所有策略、記成績單、組推薦頁／Telegram 用的 payload（規格 §10）。"""
import duckdb
import pandas as pd

from recommend.cards import build_cards, group_by_sector
from recommend.data import DB_PATH, load_panel
from recommend.features import add_chip_features, add_price_features
from recommend.market import market_header
from recommend.scorecard import ensure_table, record_signals, refresh, summary
from recommend.strategies import ALL_STRATEGIES

KEEP_DAYS = 3        # C16：推薦在頁面保留 3 個交易日
WARMUP_DAYS = 400    # 日曆天；hi90、MA60、籌碼視窗的預熱


def build_payload(features: pd.DataFrame, day: pd.Timestamp, keep_days: int = KEEP_DAYS, rally_pct=None) -> dict:
    """純函式：new（當天、有效，依族群分組）、active（第 2～N 天有效）、invalid（已失效）、header、signals。"""
    day = pd.Timestamp(day)
    trade_days = sorted(features.loc[features["date"] <= day, "date"].unique())
    window = trade_days[-keep_days:]
    day_n = {pd.Timestamp(d): len(window) - i for i, d in enumerate(window)}
    signals = pd.concat([s.scan(features) for s in ALL_STRATEGIES], ignore_index=True)
    recent = signals[signals["date"].isin(window)]
    cards = build_cards(features, recent, day, rally_pct=rally_pct)
    for c in cards:
        c["day_n"] = day_n[pd.Timestamp(c["signal_date"])]
    valid = [c for c in cards if c["status"] == "有效"]
    return {
        "trade_date": day.date().isoformat(),
        "header": market_header(features, signals, day),
        "new": group_by_sector([c for c in valid if c["day_n"] == 1]),
        "active": sorted([c for c in valid if c["day_n"] > 1], key=lambda c: (c["day_n"], c["stock_id"])),
        "invalid": [c for c in cards if c["status"] == "失效"],
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
        record_signals(con, signals[signals["date"] == day], feats)
        refresh(con, feats)
        payload["scorecard"] = {s.name: summary(con, s.name) for s in ALL_STRATEGIES}
    finally:
        con.close()
    return payload
