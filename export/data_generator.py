"""
產生 docs/data.json — 供前端 React app 執行期 fetch 讀取的族群總覽資料。
不產生 HTML；HTML 由 frontend/（Vite build）另外產生。
"""
import json
from datetime import date
from pathlib import Path

import pandas as pd


def _weekly_pct(spark: list) -> float:
    """複利計算 sparkline 最後 5 個交易日的週漲跌幅。"""
    if not spark:
        return 0.0
    last5 = spark[-5:]
    result = 1.0
    for p in last5:
        result *= (1 + p / 100)
    return round((result - 1) * 100, 2)


def generate(
    trade_date: date,
    meta_perf: list,
    universe_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    chips_df: pd.DataFrame = None,
    cum_data: list = None,
    meta_signals: dict = None,
    weekly_rank: dict = None,
    stock_sparklines: dict = None,
    output_path: str = "docs/data.json",
) -> None:
    if not meta_perf:
        return

    universe = universe_df.copy()
    universe["stock_id"] = universe["stock_id"].astype(str)
    name_map = dict(zip(universe["stock_id"], universe["stock_name"]))
    sub_map = dict(zip(universe["stock_id"], universe["sub_sector"]))

    prices_map = (
        prices_df.assign(stock_id=prices_df["stock_id"].astype(str)).set_index("stock_id")
        if prices_df is not None and not prices_df.empty else pd.DataFrame()
    )
    chips_map = (
        chips_df.assign(stock_id=chips_df["stock_id"].astype(str)).set_index("stock_id")
        if chips_df is not None and not chips_df.empty else pd.DataFrame()
    )
    cum_map = {r["meta_name"]: r for r in (cum_data or [])}
    meta_signals = meta_signals or {}
    weekly_rank = weekly_rank or {}
    stock_sparklines = stock_sparklines or {}

    sorted_meta = sorted(meta_perf, key=lambda r: r["avg_change_pct"], reverse=True)

    total = sum(r["up_count"] + r["down_count"] + r["flat_count"] for r in meta_perf)
    up = sum(r["up_count"] for r in meta_perf)
    down = sum(r["down_count"] for r in meta_perf)
    flat = total - up - down
    mkt_avg = round(sum(r["avg_change_pct"] for r in meta_perf) / len(meta_perf), 2) if meta_perf else 0.0

    meta_sectors_json = []
    for today_rank, row in enumerate(sorted_meta, start=1):
        meta_name = row["meta_name"]
        cum = cum_map.get(meta_name, {})
        sig = meta_signals.get(meta_name, {})
        wr = weekly_rank.get(meta_name, {})

        sub_groups: dict = {}
        for sid in row.get("stock_ids", []):
            sid = str(sid)
            sub_name = sub_map.get(sid, "其他")
            stock_name = name_map.get(sid, "")

            close = pct = volume = None
            if sid in prices_map.index:
                p = prices_map.loc[sid]
                close = float(p["close"])
                pct = float(p["change_pct"])
                volume = int(p["volume"])

            fn = tn = mb = mc = 0
            if sid in chips_map.index:
                c = chips_map.loc[sid]
                fn = int(c.get("foreign_net") or 0) // 1000
                tn = int(c.get("trust_net") or 0) // 1000
                mb = int(c.get("margin_balance") or 0)
                mc = int(c.get("margin_change") or 0)

            spark = stock_sparklines.get(sid, [])

            sub_groups.setdefault(sub_name, []).append({
                "id": sid,
                "name": stock_name,
                "close": close,
                "changePct": pct,
                "volume": volume,
                "weeklyPct": _weekly_pct(spark),
                "foreignNet": fn,
                "trustNet": tn,
                "marginBalance": mb,
                "marginChange": mc,
                "sparkline": spark,
            })

        meta_sectors_json.append({
            "name": meta_name,
            "avgChangePct": row["avg_change_pct"],
            "upCount": row["up_count"],
            "downCount": row["down_count"],
            "cum3": cum.get("cum3"),
            "cum5": cum.get("cum5"),
            "cum7": cum.get("cum7"),
            "todayRank": today_rank,
            "yesterdayRank": sig.get("yesterday_rank"),
            "thisWeekRank": wr.get("this_week_rank"),
            "lastWeekRank": wr.get("last_week_rank"),
            "streak": sig.get("streak", 0),
            "volRatio": sig.get("vol_ratio"),
            "subGroups": [
                {"name": name, "stocks": stocks}
                for name, stocks in sub_groups.items()
            ],
        })

    payload = {
        "date": trade_date.isoformat(),
        "market": {"avgPct": mkt_avg, "up": up, "down": down, "flat": flat},
        "metaSectors": meta_sectors_json,
    }

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=None), encoding="utf-8")
