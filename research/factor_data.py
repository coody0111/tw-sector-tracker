"""價量資料載入與未來報酬計算。

鐵律：本模組是唯一碰「未來」的地方（forward_returns）。因子端一律只能看 <= t。
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "screener.db"
UNIVERSE_CSV = Path(__file__).resolve().parent.parent / "data" / "stock_universe.csv"

# 連續覆蓋的起點。之前為零星稀疏值（2017-12 只有 2 檔），非連續資料。
DEFAULT_START = "2025-01-01"
# 原本卡在2026-08-06是因為之後有19天缺口；該缺口已被commit a769463的
# 近N日窗口跨斷層防護+backfill匯入修復解決，2026-09-02驗證資料連續覆蓋到2026-09-01
# （欄位覆蓋率99.2%，跟修復前同一水準，不是新缺口），往後跟著往上調。
DEFAULT_END = "2026-09-01"

FIELDS = ("close", "high", "low", "volume")


def load_price_panel(
    db_path: Path | str = DB_PATH,
    start: str | None = DEFAULT_START,
    end: str | None = DEFAULT_END,
) -> dict[str, pd.DataFrame]:
    """載入價量，回傳 {欄位: date×stock 的 DataFrame}。

    只讀，不寫。索引為交易日（升冪），欄位為 stock_id。
    """
    where = ["1=1"]
    if start:
        where.append(f"date >= DATE '{start}'")
    if end:
        where.append(f"date <= DATE '{end}'")

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = con.execute(
            f"""
            SELECT date, stock_id, close, high, low, volume
            FROM daily_prices
            WHERE {' AND '.join(where)}
            ORDER BY date, stock_id
            """
        ).df()
    finally:
        con.close()

    df["date"] = pd.to_datetime(df["date"])
    panel = {f: df.pivot(index="date", columns="stock_id", values=f).sort_index() for f in FIELDS}
    return panel


def forward_returns(
    panel: dict[str, pd.DataFrame], horizons: tuple[int, ...] = (1, 5, 10, 20)
) -> dict[int, pd.DataFrame]:
    """未來 h 個交易日的報酬：fwd[t] = close[t+h] / close[t] - 1。

    以「面板列位置」定義 h，不是日曆天。最後 h 列必然為 NaN（沒有未來可看）。
    """
    close = panel["close"]
    return {h: close.shift(-h) / close - 1.0 for h in horizons}


def sector_map(universe_csv: Path | str = UNIVERSE_CSV) -> pd.Series:
    """stock_id -> meta_sector 的對應。"""
    uni = pd.read_csv(universe_csv, dtype=str, encoding="utf-8-sig")
    return uni.set_index("stock_id")["meta_sector"].dropna()


def trading_days(panel: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
    return panel["close"].index


def field_coverage(panel: dict[str, pd.DataFrame]) -> pd.Series:
    """每個欄位「有值的格子」占比。

    存在的意義：2026-07 之前 high/low 全是 NULL，害 range_pos 整段算不出來。
    只看「表有幾筆」會漏掉這種欄位級缺漏，所以每次跑都要報一次。
    """
    return pd.Series({f: float(df.notna().to_numpy().mean()) for f, df in panel.items()})


def usable_factors(
    panel: dict[str, pd.DataFrame],
    requires: dict[str, tuple[str, ...]],
    min_coverage: float = 0.5,
) -> tuple[list[str], dict[str, str]]:
    """依欄位覆蓋率決定哪些因子可算。回傳 (可用因子, {不可用因子: 原因})。"""
    cov = field_coverage(panel)
    usable, skipped = [], {}
    for name, fields in requires.items():
        bad = [f for f in fields if cov.get(f, 0.0) < min_coverage]
        if bad:
            skipped[name] = "、".join(f"{f} 覆蓋率僅 {cov.get(f, 0.0):.1%}" for f in bad)
        else:
            usable.append(name)
    return usable, skipped


def split_date(panel: dict[str, pd.DataFrame], in_sample_frac: float = 2 / 3) -> pd.Timestamp:
    """時間切分點（非隨機）。研究期:樣本外 ≈ 2:1。

    回傳「樣本外的第一天」。樣本內 = date < 切分點。
    """
    days = trading_days(panel)
    return days[int(len(days) * in_sample_frac)]
