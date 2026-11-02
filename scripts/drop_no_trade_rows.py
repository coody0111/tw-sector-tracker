"""刪掉 daily_prices 裡「整天沒有成交」的假列（2026-11-03）。

10/27 起每日流程把沒成交股票的買方掛單價寫成收盤（例如 3064 泰偉 11/02 寫成 13.20、−9.59%），
官方收盤其實是 ---。認定條件：成交量 0，而且開盤／最高／最低都是空的。
CSV（data/daily_prices/*.csv）和 DuckDB 兩邊都刪，不然下次 reimport 又會從 CSV 讀回來。

用法（Cody 在專案根目錄跑）：
    python scripts/drop_no_trade_rows.py          # 只列出會刪什麼，不動資料
    python scripts/drop_no_trade_rows.py --apply  # 真的刪
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from storage.duck import connect_rw  # noqa: E402

CSV_DIR = ROOT / "data" / "daily_prices"
DB_PATH = str(ROOT / "data" / "screener.db")
WHERE = "volume = 0 AND open IS NULL AND high IS NULL AND low IS NULL"


def no_trade(df: pd.DataFrame) -> pd.Series:
    return (df["volume"].fillna(0) == 0) & df["open"].isna() & df["high"].isna() & df["low"].isna()


def clean_csvs(apply: bool, csv_dir: Path = CSV_DIR) -> int:
    total = 0
    for path in sorted(csv_dir.glob("*.csv")):
        df = pd.read_csv(path, dtype={"stock_id": str}, encoding="utf-8-sig")
        if not {"volume", "open", "high", "low"} <= set(df.columns):
            continue
        bad = no_trade(df)
        if not bad.any():
            continue
        total += int(bad.sum())
        print(f"  {path.name}: {int(bad.sum())} 列（{'、'.join(df.loc[bad, 'stock_id'].head(8))}{' …' if bad.sum() > 8 else ''}）")
        if apply:
            df[~bad].to_csv(path, index=False, encoding="utf-8-sig")
    return total


def clean_db(apply: bool, db_path: str = DB_PATH) -> int:
    con = connect_rw(db_path)
    try:
        n = con.execute(f"SELECT count(*) FROM daily_prices WHERE {WHERE}").fetchone()[0]
        if apply and n:
            con.execute(f"DELETE FROM daily_prices WHERE {WHERE}")
    finally:
        con.close()
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的刪（不加只列出）")
    apply = ap.parse_args().apply
    print("CSV：")
    n_csv = clean_csvs(apply)
    n_db = clean_db(apply)
    verb = "已刪除" if apply else "會刪除（加 --apply 才會真的刪）"
    print(f"{verb}：CSV {n_csv} 列、DuckDB {n_db} 列")


if __name__ == "__main__":
    main()
