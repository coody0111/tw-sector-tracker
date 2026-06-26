"""
法人買進篩選器

支援多種過濾條件，可任意組合：
  foreign_streak   外資連買 ≥ N 日
  trust_streak     投信連買 ≥ N 日
  both_streak      外資+投信同時連買 ≥ N 日
  min_foreign_net  今日外資買超 ≥ N 元（負值為賣超）
  min_trust_net    今日投信買超 ≥ N 元
  min_total_net    今日三大法人合計 ≥ N 元
  cum_foreign_net  lookback 天內外資累計 ≥ N 元
  cum_trust_net    lookback 天內投信累計 ≥ N 元
"""
import logging
from typing import Any, Dict, List

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

_DB_PATH = "data/screener.db"


def _calc_streak(series: pd.Series) -> int:
    """回傳序列尾端連續正值天數（序列應按日期升序排列）。"""
    streak = 0
    for v in reversed(series.tolist()):
        if v is not None and v > 0:
            streak += 1
        else:
            break
    return streak


def scan_institutional(
    trade_date: str,
    lookback: int = 20,
    foreign_streak: int = 0,
    trust_streak: int = 0,
    both_streak: int = 0,
    min_foreign_net: int = 0,
    min_trust_net: int = 0,
    min_total_net: int = 0,
    cum_foreign_net: int = 0,
    cum_trust_net: int = 0,
    sort_by: str = "total_net",
    db_path: str = _DB_PATH,
) -> List[Dict[str, Any]]:
    """
    法人買進篩選，回傳符合條件的股票清單。

    Parameters
    ----------
    trade_date      : 目標日期 'YYYY-MM-DD'
    lookback        : 往回抓幾個交易日的法人資料（用於計算連買天數與累計）
    foreign_streak  : 外資連買 ≥ N 日（0 = 不限）
    trust_streak    : 投信連買 ≥ N 日（0 = 不限）
    both_streak     : 外資+投信同時連買 ≥ N 日（0 = 不限）
    min_foreign_net : 今日外資買超門檻（元，0 = 不限）
    min_trust_net   : 今日投信買超門檻（元，0 = 不限）
    min_total_net   : 今日三大合計門檻（元，0 = 不限）
    cum_foreign_net : lookback 天累計外資門檻（元，0 = 不限）
    cum_trust_net   : lookback 天累計投信門檻（元，0 = 不限）
    sort_by         : 排序欄位，可選 total_net / foreign_net / trust_net /
                      foreign_streak / trust_streak / both_streak /
                      cum_foreign / cum_trust

    Returns
    -------
    list of dict，每筆含：
        stock_id, date,
        foreign_net, trust_net, dealer_net, total_net,  ← 今日
        foreign_streak, trust_streak, both_streak,
        cum_foreign, cum_trust,                          ← lookback 天累計
        close, change_pct                                ← 今日行情（若有）
    """
    con = duckdb.connect(db_path, read_only=True)

    # 若目標日無法人資料，自動 fallback 到最新有資料的日期
    latest_row = con.execute(f"""
        SELECT MAX(date) FROM institutional WHERE date <= '{trade_date}'
    """).fetchone()
    latest_inst_date = str(latest_row[0])[:10] if latest_row and latest_row[0] else None
    if not latest_inst_date:
        logger.warning("scan_institutional: 無任何法人資料")
        con.close()
        return []
    if latest_inst_date != trade_date:
        logger.info("法人資料尚未發布，使用最新日期 %s（請求 %s）", latest_inst_date, trade_date)

    # 取 lookback 天的法人資料
    inst_df = con.execute(f"""
        SELECT stock_id, date, foreign_net, trust_net, dealer_net, total_net
        FROM institutional
        WHERE date <= '{latest_inst_date}'
        ORDER BY stock_id, date DESC
        LIMIT {lookback * 2000}
    """).df()

    # 行情：優先用目標日，fallback 到最新法人日
    price_df = con.execute(f"""
        SELECT stock_id, close, change_pct
        FROM daily_prices
        WHERE date = '{trade_date}'
    """).df()
    if price_df.empty:
        price_df = con.execute(f"""
            SELECT stock_id, close, change_pct
            FROM daily_prices
            WHERE date = '{latest_inst_date}'
        """).df()

    con.close()
    trade_date = latest_inst_date  # 掃描基準改為有資料的最新日

    if inst_df.empty:
        logger.warning("scan_institutional: 無法人資料 (%s)", trade_date)
        return []

    inst_df["date"] = pd.to_datetime(inst_df["date"])
    target = pd.to_datetime(trade_date)

    price_map: dict = {}
    if not price_df.empty:
        price_map = price_df.set_index("stock_id")[["close", "change_pct"]].to_dict("index")

    results = []

    for sid, grp in inst_df.groupby("stock_id"):
        grp = grp.sort_values("date").reset_index(drop=True)

        today_rows = grp[grp["date"] == target]
        if today_rows.empty:
            continue

        today = today_rows.iloc[0]
        f_net = today["foreign_net"]
        t_net = today["trust_net"]
        d_net = today["dealer_net"]
        tot   = today["total_net"]

        # ── 今日單日門檻 ─────────────────────────────────────────
        if min_foreign_net and (f_net is None or f_net < min_foreign_net):
            continue
        if min_trust_net and (t_net is None or t_net < min_trust_net):
            continue
        if min_total_net and (tot is None or tot < min_total_net):
            continue

        # ── 連買天數（只用 lookback 窗口內的資料）────────────────
        window = grp[grp["date"] <= target].tail(lookback)

        f_streak = _calc_streak(window["foreign_net"])
        t_streak = _calc_streak(window["trust_net"])

        # both_streak：外資+投信同日皆買超的連續天數
        b_streak = 0
        for _, row in window.iloc[::-1].iterrows():
            if row["foreign_net"] is not None and row["foreign_net"] > 0 \
               and row["trust_net"] is not None and row["trust_net"] > 0:
                b_streak += 1
            else:
                break

        if foreign_streak and f_streak < foreign_streak:
            continue
        if trust_streak and t_streak < trust_streak:
            continue
        if both_streak and b_streak < both_streak:
            continue

        # ── 累計金額 ─────────────────────────────────────────────
        cum_f = int(window["foreign_net"].fillna(0).sum())
        cum_t = int(window["trust_net"].fillna(0).sum())

        if cum_foreign_net and cum_f < cum_foreign_net:
            continue
        if cum_trust_net and cum_t < cum_trust_net:
            continue

        # ── 整合行情 ─────────────────────────────────────────────
        px = price_map.get(str(sid), {})

        results.append({
            "stock_id":       str(sid),
            "date":           trade_date,
            "foreign_net":    int(f_net) if f_net is not None else None,
            "trust_net":      int(t_net) if t_net is not None else None,
            "dealer_net":     int(d_net) if d_net is not None else None,
            "total_net":      int(tot)   if tot   is not None else None,
            "foreign_streak": f_streak,
            "trust_streak":   t_streak,
            "both_streak":    b_streak,
            "cum_foreign":    cum_f,
            "cum_trust":      cum_t,
            "close":          px.get("close"),
            "change_pct":     px.get("change_pct"),
        })

    # 排序
    _sort_key = {
        "total_net":      lambda x: -(x["total_net"]   or 0),
        "foreign_net":    lambda x: -(x["foreign_net"] or 0),
        "trust_net":      lambda x: -(x["trust_net"]   or 0),
        "foreign_streak": lambda x: -x["foreign_streak"],
        "trust_streak":   lambda x: -x["trust_streak"],
        "both_streak":    lambda x: -x["both_streak"],
        "cum_foreign":    lambda x: -x["cum_foreign"],
        "cum_trust":      lambda x: -x["cum_trust"],
    }
    key_fn = _sort_key.get(sort_by, _sort_key["total_net"])
    results.sort(key=key_fn)

    logger.info(
        "法人篩選 %s：%d 檔符合條件（lookback=%d）",
        trade_date, len(results), lookback,
    )
    return results
