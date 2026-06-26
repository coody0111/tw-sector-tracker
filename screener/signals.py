"""
選股訊號掃描器

巨量換手訊號（三條件同時成立）：
  ① 爆量：今日量 == 過去 N 交易日最大值
  ② 收跌不鎖跌停：close < prev_close 且 change_pct > -9.5%
  ③ 前日漲停：prev_change_pct >= 9.5%

附帶資訊（非過濾條件，供人工判斷）：
  ✦ 量倍數（今日量 / lookback 均量）
  ✦ 外資/投信/三大法人當日買賣超
  ✦ inst_confirmed：外資 + 投信同日皆買超
"""
import logging
from typing import List, Dict, Any

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

_DB_PATH = "data/screener.db"
_UNIVERSE_PATH = "data/stock_universe.csv"


def _load_universe_map() -> dict:
    try:
        df = pd.read_csv(_UNIVERSE_PATH, usecols=["stock_id", "stock_name", "meta_sector"], dtype=str)
        return df.set_index("stock_id")[["stock_name", "meta_sector"]].to_dict("index")
    except Exception:
        return {}


def scan_volume_turnover(
    trade_date: str,
    lookback: int = 126,
    db_path: str = _DB_PATH,
) -> List[Dict[str, Any]]:
    """
    掃描巨量換手訊號，並附上三大法人確認評級。

    Parameters
    ----------
    trade_date : str   e.g. "2026-06-24"
    lookback   : int   成交量比較窗口（交易日數，預設 126）

    Returns
    -------
    list of dict，依量倍數降序排列，每筆含：
        stock_id, close, change_pct, volume,
        prev_close, prev_change_pct,
        vol_multiple (今日量 / 均量),
        vol_window_days (實際窗口天數),
        foreign_net, trust_net, total_net,   ← 當日三大法人（無資料為 None）
        inst_confirmed                        ← 外資 + 投信同日皆買超
    """
    con = duckdb.connect(db_path, read_only=True)

    price_df = con.execute(f"""
        SELECT stock_id, date, close, change_pct, volume
        FROM daily_prices
        WHERE date <= '{trade_date}'
        ORDER BY stock_id, date
    """).df()

    # 三大法人：只取訊號當日
    inst_df = con.execute(f"""
        SELECT stock_id, foreign_net, trust_net, total_net
        FROM institutional
        WHERE date = '{trade_date}'
    """).df()

    con.close()

    if price_df.empty:
        logger.warning("scan_volume_turnover: DuckDB 無行情資料")
        return []

    # 建立三大法人查詢字典
    inst_map: dict = {}
    if not inst_df.empty:
        inst_map = inst_df.set_index("stock_id")[["foreign_net", "trust_net", "total_net"]].to_dict("index")

    universe_map = _load_universe_map()
    price_df["date"] = pd.to_datetime(price_df["date"])
    target = pd.to_datetime(trade_date)

    results = []

    for sid, grp in price_df.groupby("stock_id"):
        grp = grp.sort_values("date").reset_index(drop=True)

        today_rows = grp[grp["date"] == target]
        if today_rows.empty:
            continue
        today_idx = today_rows.index[0]
        if today_idx < 1:
            continue

        today = grp.iloc[today_idx]
        prev  = grp.iloc[today_idx - 1]

        # ── 硬性三條件 ──────────────────────────────────────────
        # ② 收跌不鎖跌停
        if not (today["close"] < prev["close"] and today["change_pct"] > -9.5):
            continue

        # ③ 前日漲停
        if prev["change_pct"] < 9.5:
            continue

        # ① 爆量：今日量 = 過去 lookback 日最大值
        window_start = max(0, today_idx - lookback + 1)
        window = grp.iloc[window_start: today_idx + 1]
        if len(window) < 2:
            continue
        vol_max = window["volume"].max()
        if int(today["volume"]) < int(vol_max):
            continue

        # ── 附帶資訊 ────────────────────────────────────────────
        vol_avg = window["volume"].mean()
        vol_multiple = round(today["volume"] / vol_avg, 1) if vol_avg > 0 else 0

        # 量倍數過低 → 雜訊，不納入
        if vol_multiple < 1.5:
            continue

        inst = inst_map.get(sid, {})
        foreign_net = inst.get("foreign_net")
        trust_net   = inst.get("trust_net")
        total_net   = inst.get("total_net")

        inst_confirmed = (
            foreign_net is not None and foreign_net > 0 and
            trust_net   is not None and trust_net   > 0
        )

        uinfo = universe_map.get(str(sid), {})
        results.append({
            "stock_id":        sid,
            "stock_name":      uinfo.get("stock_name", ""),
            "meta_sector":     uinfo.get("meta_sector", ""),
            "close":           today["close"],
            "change_pct":      today["change_pct"],
            "volume":          int(today["volume"]),
            "prev_close":      prev["close"],
            "prev_change_pct": prev["change_pct"],
            "vol_multiple":    vol_multiple,
            "vol_window_days": len(window),
            "foreign_net":     foreign_net,
            "trust_net":       trust_net,
            "total_net":       total_net,
            "inst_confirmed":  inst_confirmed,
        })

    # 量倍數越大排越前面
    results.sort(key=lambda x: -x["vol_multiple"])

    has_inst = len(inst_map) > 0
    logger.info(
        "巨量換手掃描 %s：命中 %d 檔（三大法人資料%s）",
        trade_date, len(results), "已取得" if has_inst else "尚未發布"
    )
    return results
