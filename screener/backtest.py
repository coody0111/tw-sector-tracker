"""
通用訊號回測框架

對 DuckDB 中每個有效交易日跑一次傳入的 scanner callable，
以 D+1 開盤價進場，計算多天期（預設 5/10/14 日）後的收盤報酬。
"""
import logging
from functools import lru_cache
from typing import Callable, List, Dict, Any

import duckdb
import pandas as pd

from screener.signals import scan_volume_turnover
from screener.institutional import (
    scan_institutional,
    rank_continuation_candidates,
    rank_joint_buy_candidates,
)

logger = logging.getLogger(__name__)

_DB_PATH = "data/screener.db"

# foreign/trust_continuation 的消融對照變體（2026-07-18 bug-reports.md 討論）：
# 排名公式原本是「連買天數排名 + 10日漲幅排名」各半，把「法人連買」跟「已經漲了多少」
# 兩個因子綁在一起，測不出籌碼資訊本身的貢獻。_streak_only/_price_only 沿用完全相同的
# 篩選門檻，只換排序依據，讓回測能把兩個因子拆開測。
_CONTINUATION_RULE_SPECS = {
    "foreign_continuation":             {"streak_field": "foreign_streak", "min_streak": 3, "weight_mode": "blended"},
    "foreign_continuation_streak_only": {"streak_field": "foreign_streak", "min_streak": 3, "weight_mode": "streak_only"},
    "foreign_continuation_price_only":  {"streak_field": "foreign_streak", "min_streak": 3, "weight_mode": "price_only"},
    "trust_continuation":               {"streak_field": "trust_streak", "min_streak": 5, "weight_mode": "blended"},
    "trust_continuation_streak_only":   {"streak_field": "trust_streak", "min_streak": 5, "weight_mode": "streak_only"},
    "trust_continuation_price_only":    {"streak_field": "trust_streak", "min_streak": 5, "weight_mode": "price_only"},
}

CHIPS_RULES = (
    "joint_buy",
    *_CONTINUATION_RULE_SPECS.keys(),
    "margin_bearish", "tdcc_accumulation",
)

# 每條規則的回測語意必須跟實際用途一致。偏多規則模擬 D+1 買進，所以扣來回
# 交易成本並剔除隔日漲停買不到的訊號；margin_bearish 是既有持股的風險警示，
# 不是放空策略，也沒有「買不到」問題，因此觀察未扣成本的後續相對表現。
# 消融變體（_streak_only/_price_only）跟其原始規則交易語意完全相同，只有選股排序不同，
# 沿用同一組 cost_pct/skip_no_fill/success_direction。
CHIPS_RULE_CONFIG = {
    "joint_buy": {"success_direction": "positive", "skip_no_fill": True, "cost_pct": 0.6},
    **{name: {"success_direction": "positive", "skip_no_fill": True, "cost_pct": 0.6}
       for name in _CONTINUATION_RULE_SPECS},
    "margin_bearish": {"success_direction": "negative", "skip_no_fill": False, "cost_pct": 0.0},
    "tdcc_accumulation": {"success_direction": "positive", "skip_no_fill": True, "cost_pct": 0.6},
}

_MIN_RULE_SIGNAL_DATES = 20
_MIN_BLOCK_SIGNAL_DATES = 10

# TDCC 集保股權分散表每週五更新，但實際「查得到」會晚幾個交易日（公布延遲）——沒有官方
# 精確公布時間表可查證，這是務實估計值（2026-07-18 bug-reports.md 記錄），可能需要之後
# 跟 Cody 確認 TDCC 官方公布時程後調整。回測若忽略這段延遲，會在「當時實際上還查不到這筆
# 資料」的那天就下單，是前瞻偏誤（look-ahead bias）。
_TDCC_PUBLISH_LAG_TRADING_DAYS = 3


@lru_cache(maxsize=1)
def _backtest_universe() -> pd.DataFrame:
    return pd.read_csv(
        "data/stock_universe.csv", dtype=str,
        usecols=["stock_id", "stock_name", "meta_sector"],
    )


@lru_cache(maxsize=16)
def _all_trading_dates(db_path: str) -> tuple[str, ...]:
    """全市場交易日曆（daily_prices 實際有資料的日期），供計算「快照日之後第N個交易日」
    （模擬 TDCC 公布延遲）使用。缺表或查詢失敗時回傳空 tuple（安全，不產生訊號)。"""
    try:
        con = duckdb.connect(db_path, read_only=True)
        rows = con.execute("SELECT DISTINCT date FROM daily_prices ORDER BY date").fetchall()
        con.close()
    except Exception:
        return ()
    return tuple(str(row[0])[:10] for row in rows if row and row[0])


@lru_cache(maxsize=16)
def _table_date_range(db_path: str, table: str) -> tuple[str | None, str | None]:
    """回測資料源日期範圍；讓來源尚未開始前的日期安靜跳過。"""
    if table not in {"institutional", "margin", "shareholder"}:
        raise ValueError(f"不允許的資料表: {table}")
    try:
        con = duckdb.connect(db_path, read_only=True)
        row = con.execute(f"SELECT MIN(date), MAX(date) FROM {table}").fetchone()
        con.close()
    except Exception:
        return None, None
    return (
        str(row[0])[:10] if row and row[0] else None,
        str(row[1])[:10] if row and row[1] else None,
    )


@lru_cache(maxsize=16)
def _table_dates(db_path: str, table: str) -> frozenset[str]:
    """資料表實際有發布資料的日期；避免 fallback 日重掃同一批訊號。"""
    if table not in {"institutional", "margin", "shareholder"}:
        raise ValueError(f"不允許的資料表: {table}")
    try:
        con = duckdb.connect(db_path, read_only=True)
        dates = con.execute(f"SELECT DISTINCT date FROM {table}").fetchall()
        con.close()
    except Exception:
        return frozenset()
    return frozenset(str(row[0])[:10] for row in dates if row and row[0])


def scan_chips_rule(date_str: str, db_path: str, rule: str) -> List[Dict[str, Any]]:
    """依籌碼頁實際門檻產生單一規則訊號，供逐規則回測。"""
    if rule == "joint_buy" or rule in _CONTINUATION_RULE_SPECS:
        first_date, _ = _table_date_range(db_path, "institutional")
        if first_date and date_str < first_date:
            return []
        available_dates = _table_dates(db_path, "institutional")
        if available_dates and date_str not in available_dates:
            return []
        rows = scan_institutional(date_str, db_path=db_path, lookback=40, price_window=10)
        # scan_institutional 為即時頁面會 fallback 到前一個發布日；回測若照單全收，會把同一批
        # 法人資料在尚未發布的新交易日再次當成新訊號。至少一檔資料日必須等於訊號日才發訊號。
        if not any(r.get("date") == date_str for r in rows):
            return []
        if rule == "joint_buy":
            return rank_joint_buy_candidates([r for r in rows if r.get("meta_sector")], limit=30)
        spec = _CONTINUATION_RULE_SPECS[rule]
        candidates = [r for r in rows if r.get("meta_sector") and (r.get(spec["streak_field"]) or 0) >= spec["min_streak"]
                      and (r.get("price_cum_pct") or 0) >= 5]
        return rank_continuation_candidates(
            candidates, spec["streak_field"], limit=15, weight_mode=spec["weight_mode"],
        )

    if rule == "margin_bearish":
        first_date, _ = _table_date_range(db_path, "margin")
        if first_date and date_str < first_date:
            return []
        available_dates = _table_dates(db_path, "margin")
        if available_dates and date_str not in available_dates:
            return []
        from processors.performance import get_margin_divergence
        return get_margin_divergence(
            _backtest_universe(), db_path=db_path, lookback=10, as_of_date=date_str,
        )["bearish"]

    if rule == "tdcc_accumulation":
        first_date, _ = _table_date_range(db_path, "shareholder")
        if first_date and date_str < first_date:
            return []
        # 集保資料有公布延遲（見 _TDCC_PUBLISH_LAG_TRADING_DAYS 說明）：訊號日不能直接等於
        # 快照日，要往前找「快照日 + 延遲天數」剛好等於今天的那個快照，模擬「這天才真的
        # 查得到」的時序，避免在資料實際公布前就搶先下單（look-ahead bias）。
        trading_dates = _all_trading_dates(db_path)
        if date_str not in trading_dates:
            return []
        lag_idx = trading_dates.index(date_str) - _TDCC_PUBLISH_LAG_TRADING_DAYS
        if lag_idx < 0:
            return []
        snapshot_date = trading_dates[lag_idx]
        con = duckdb.connect(db_path, read_only=True)
        latest = con.execute("SELECT MAX(date) FROM shareholder WHERE date <= ?", [snapshot_date]).fetchone()[0]
        # 只在「快照日 + 公布延遲」對應的那個交易日發訊號一次，避免同一份 TDCC 資料
        # 被後續每天重複計數。
        if latest is None or str(latest)[:10] != snapshot_date:
            con.close()
            return []
        df = con.execute("""
            SELECT stock_id, streak, week_chg
            FROM shareholder WHERE date = ? AND streak > 0
            ORDER BY streak DESC, ABS(week_chg) DESC LIMIT 30
        """, [latest]).fetchdf()
        con.close()
        return df.to_dict("records")

    raise ValueError(f"未知籌碼回測規則: {rule}")


def make_chips_rule_scanner(rule: str) -> Callable[[str, str], List[Dict[str, Any]]]:
    if rule not in CHIPS_RULES:
        raise ValueError(f"未知籌碼回測規則: {rule}")
    return lambda date_str, db_path: scan_chips_rule(date_str, db_path, rule)


def run_chips_rule_backtests(
    rule: str = "all", db_path: str = _DB_PATH, horizons=(5, 10, 14),
) -> Dict[str, pd.DataFrame]:
    """分別回測籌碼頁規則；all 會依序執行全部規則，不把不同訊號混成總分。"""
    rules = CHIPS_RULES if rule == "all" else (rule,)
    results = {}
    for name in rules:
        config = CHIPS_RULE_CONFIG[name]
        results[name] = run_backtest(
            make_chips_rule_scanner(name),
            db_path=db_path,
            horizons=horizons,
            cost_pct=config["cost_pct"],
        )
    return results


def _build_price_index(db_path: str):
    """
    讀出整張 daily_prices，建立 (stock_id, date) → open/close 的快查 dict，
    以及每支股票的有序交易日清單，供 _forward_return 查詢用。
    """
    con = duckdb.connect(db_path, read_only=True)
    df = con.execute(
        "SELECT stock_id, date, open, close FROM daily_prices ORDER BY stock_id, date"
    ).df()
    con.close()

    df["date"] = pd.to_datetime(df["date"])
    close_map = {(r.stock_id, r.date): r.close for r in df.itertuples()}
    open_map = {(r.stock_id, r.date): r.open for r in df.itertuples()}
    stock_dates = {sid: sorted(g["date"].tolist()) for sid, g in df.groupby("stock_id")}
    return close_map, open_map, stock_dates


def _forward_return(close_map, open_map, stock_dates, sid, d_ts, horizon):
    """
    以訊號日 d_ts 的 D+1 開盤價進場（缺值時退回 D+1 收盤），
    以 D+1+horizon 收盤價出場，回傳 (entry_price, ret_pct)。
    資料不足時回傳 (None, None)。
    """
    future = [t for t in stock_dates.get(sid, []) if t > d_ts]
    if len(future) < horizon + 1:          # 需要 D+1(進場) 與 D+1+horizon(出場)
        return None, None
    entry_date, exit_date = future[0], future[horizon]
    entry = open_map.get((sid, entry_date))
    if entry is None or pd.isna(entry):    # open 缺(import 丟掉)→退回 D+1 收盤
        entry = close_map.get((sid, entry_date))
    exit_close = close_map.get((sid, exit_date))
    if entry is None or pd.isna(entry) or entry == 0 or exit_close is None or pd.isna(exit_close):
        return entry, None
    return entry, round((exit_close - entry) / entry * 100, 2)


def _market_index(db_path: str) -> dict:
    """
    大盤等權指數：daily_prices.change_pct 逐日平均、(1+avg/100) 連乘出指數 level。
    """
    con = duckdb.connect(db_path, read_only=True)
    df = con.execute(
        "SELECT date, AVG(change_pct) AS c FROM daily_prices GROUP BY date ORDER BY date"
    ).df()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    df["idx"] = (1 + df["c"].fillna(0) / 100).cumprod()
    return dict(zip(df["date"], df["idx"]))


def _bench_return(idx_map, stock_dates, sid, d_ts, horizon):
    """大盤等權指數在該股 D+1→D+1+horizon 同一進出日的報酬%。"""
    future = [t for t in stock_dates.get(sid, []) if t > d_ts]
    if len(future) < horizon + 1:
        return None
    e, x = future[0], future[horizon]
    ie, ix = idx_map.get(e), idx_map.get(x)
    if ie is None or ix is None or ie == 0:
        return None
    return round((ix / ie - 1) * 100, 2)


def _regime_at(idx_map, sorted_dates, d_ts, lookback=20, up=3.0, down=-3.0) -> str:
    """
    大盤等權指數在訊號日 d_ts 當下的氛圍：回看 lookback 個交易日的累積報酬，
    >=up% 判「多頭」、<=down% 判「空頭」，中間「盤整」；資料不足回「?」。
    """
    past = [t for t in sorted_dates if t <= d_ts]
    if len(past) < lookback + 1:
        return "?"
    now, ref = idx_map[past[-1]], idx_map[past[-1 - lookback]]
    if ref == 0:
        return "?"
    r = (now / ref - 1) * 100
    return "多頭" if r >= up else ("空頭" if r <= down else "盤整")


def run_backtest(
    scanner: Callable[[str, str], List[Dict[str, Any]]] | None = None,
    db_path: str = _DB_PATH,
    horizons=(5, 10, 14),
    limit_up_skip: bool = True,
    cost_pct: float = 0.6,
) -> pd.DataFrame:
    """
    對 DuckDB 中所有交易日逐日呼叫 scanner(date_str, db_path)，
    並以 D+1 開盤進場計算多天期報酬。

    Parameters
    ----------
    scanner : Callable[[str, str], list[dict]]
        (date_str, db_path) -> [{"stock_id": ..., "close": ...}, ...]
    limit_up_skip : bool
        True 時標記 no_fill（D+1 開盤 ≥ D 收盤 ×1.095，代表一開盤就鎖漲停買不到）。
    cost_pct : float
        來回交易成本（%），從 ret 扣一次；excess 用「已扣成本的 ret」再減 bench。

    Returns
    -------
    DataFrame，每列一個訊號，含：
        signal_date, stock_id, entry_price, no_fill,
        ret_5/bench_5/excess_5, ret_10/..., ret_14/...（依 horizons 而定）
        bench_H 為大盤等權指數同進出區間報酬%，excess_H = ret_H - bench_H
        no_fill 為 True 代表 D+1 開盤即漲停鎖死，實際上買不到，主結果可用這欄剔除
        regime 為訊號日當下的大盤氛圍（多頭/盤整/空頭/?），供 print_summary 分段
    """
    scanner = scanner or scan_volume_turnover
    close_map, open_map, stock_dates = _build_price_index(db_path)
    idx_map = _market_index(db_path)
    sorted_mkt = sorted(idx_map.keys())
    con = duckdb.connect(db_path, read_only=True)
    dates = [str(r[0])[:10] for r in con.execute(
        "SELECT DISTINCT date FROM daily_prices ORDER BY date").fetchall()]
    con.close()

    rows = []
    for d_str in dates:
        picks = scanner(d_str, db_path)
        if not picks:
            continue
        d_ts = pd.Timestamp(d_str)
        for sig in picks:
            sid = sig["stock_id"]
            d_close = close_map.get((sid, d_ts))
            future = [t for t in stock_dates.get(sid, []) if t > d_ts]
            d1_open = open_map.get((sid, future[0])) if future else None
            if d1_open is None or pd.isna(d1_open):
                d1_open = close_map.get((sid, future[0])) if future else None
            no_fill = bool(limit_up_skip and d_close and d1_open
                           and d1_open >= d_close * 1.095)
            row = {"signal_date": d_str, "stock_id": sid,
                   "entry_price": None, "no_fill": no_fill,
                   "regime": _regime_at(idx_map, sorted_mkt, d_ts)}
            for h in horizons:
                entry, ret = _forward_return(close_map, open_map, stock_dates, sid, d_ts, h)
                if entry is not None:
                    row["entry_price"] = entry
                if ret is not None:
                    ret = round(ret - cost_pct, 2)
                row[f"ret_{h}"] = ret
                bench = _bench_return(idx_map, stock_dates, sid, d_ts, h)
                row[f"bench_{h}"] = bench
                row[f"excess_{h}"] = (round(ret - bench, 2)
                                      if ret is not None and bench is not None else None)
            rows.append(row)
    return pd.DataFrame(rows)


def print_summary(
    df: pd.DataFrame,
    horizons=(5, 10, 14),
    skip_no_fill: bool = True,
    success_direction: str = "positive",
) -> None:
    """
    印出超額報酬摘要，並依 regime（多頭/盤整/空頭）分段。
    skip_no_fill=True 時，統計會剔除 no_fill（漲停買不到）的訊號。
    success_direction=negative 時以「超額報酬 < 0」計算風險警示命中率。
    """
    if df.empty:
        print("無訊號資料")
        return
    used = df[~df["no_fill"]] if (skip_no_fill and "no_fill" in df.columns) else df
    n_skip = len(df) - len(used)
    if success_direction not in {"positive", "negative"}:
        raise ValueError("success_direction 必須是 positive 或 negative")

    signal_dates = used["signal_date"].nunique() if "signal_date" in used.columns else 0
    unique_stocks = used["stock_id"].nunique() if "stock_id" in used.columns else 0
    fill_note = (f"漲停剔除 {n_skip}" if skip_no_fill
                 else f"風險警示不剔除漲停 {int(df['no_fill'].sum()) if 'no_fill' in df.columns else 0}")
    print("=" * 78)
    print(f"  回測結果  訊號 {len(used)} 筆（{fill_note}）  "
          f"訊號日 {signal_dates} 個  股票 {unique_stocks} 檔")
    print(f"  日期 {df['signal_date'].min()} ~ {df['signal_date'].max()}")
    if signal_dates < _MIN_RULE_SIGNAL_DATES:
        print(f"  注意：僅涵蓋 {signal_dates} 個訊號日，樣本期偏短，結果只適合列為觀察。")
    print("=" * 78)

    def _block(sub, tag):
        for h in horizons:
            col, exc = f"ret_{h}", f"excess_{h}"
            if exc not in sub.columns:
                continue
            s = sub[sub[exc].notna()]
            if s.empty:
                continue
            success = s[exc] > 0 if success_direction == "positive" else s[exc] < 0
            win = success.mean() * 100
            avg_ex = s[exc].mean()
            avg_ret = s[col].mean()
            median_ex = s[exc].median()
            q25, q75 = s[exc].quantile([0.25, 0.75])
            dates_n = s["signal_date"].nunique() if "signal_date" in s.columns else 0
            stocks_n = s["stock_id"].nunique() if "stock_id" in s.columns else 0
            hit_label = "勝率(超額>0)" if success_direction == "positive" else "避險命中(超額<0)"
            sample_note = "  [訊號日不足]" if dates_n < _MIN_BLOCK_SIGNAL_DATES else ""
            print(f"  [{tag}] D+{h:<2}  n={len(s):<4} 日={dates_n:<3} 股={stocks_n:<4} "
                  f"{hit_label} {win:4.0f}%{sample_note}")
            print(f"           平均超額 {avg_ex:+.2f}%  中位數 {median_ex:+.2f}%  "
                  f"P25/P75 {q25:+.2f}%/{q75:+.2f}%  平均報酬 {avg_ret:+.2f}%")

    _block(used, "全部")
    if "regime" in used.columns:
        print("-" * 78)
        for reg in ["多頭", "盤整", "空頭"]:
            sub = used[used["regime"] == reg]
            if not sub.empty:
                _block(sub, reg)
