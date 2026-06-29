"""
scripts/update_exchange.py
為 data/stock_universe.csv 補上 exchange 欄位（TWSE=上市 / TPEx=上櫃）。

做法：
  1. 呼叫 TWSE STOCK_DAY_ALL API 取得今日所有上市股票 ID
  2. universe 中不在 TWSE 清單的，標記為 TPEx
  3. 寫回 stock_universe.csv

跑一次即可，之後新增股票時手動補。
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from scrapers.twse import fetch_daily_prices as fetch_twse_all


def _get_twse_ids(d: date) -> set[str]:
    """取得指定交易日所有上市股票 ID。若失敗則往前找最近一個交易日。"""
    for offset in range(5):
        try:
            df = fetch_twse_all(d - timedelta(days=offset))
            if not df.empty:
                return set(df["stock_id"].astype(str).str.strip())
        except Exception:
            continue
    return set()


def update() -> None:
    universe_path = Path("data/stock_universe.csv")
    universe = pd.read_csv(universe_path, dtype=str)

    if "exchange" in universe.columns:
        existing = universe["exchange"].notna() & (universe["exchange"] != "")
        if existing.sum() > len(universe) * 0.9:
            print(f"[OK] exchange 欄位已存在（{existing.sum()}/{len(universe)} 已填），跳過 API 呼叫")
            return

    print("正在取得 TWSE 上市股票清單…")
    twse_ids = _get_twse_ids(date.today())
    if not twse_ids:
        print("[ERR] 無法取得 TWSE 清單，請確認今日是否為交易日")
        return
    print(f"  TWSE 上市：{len(twse_ids)} 支")

    universe["exchange"] = universe["stock_id"].apply(
        lambda sid: "TWSE" if str(sid).strip() in twse_ids else "TPEx"
    )

    twse_cnt = (universe["exchange"] == "TWSE").sum()
    tpex_cnt = (universe["exchange"] == "TPEx").sum()
    print(f"  Universe 上市 {twse_cnt} 支 / 上櫃 {tpex_cnt} 支")

    # 重新排欄位順序：stock_id, stock_name, exchange, meta_sector, sub_sector, note
    cols = ["stock_id", "stock_name", "exchange", "meta_sector", "sub_sector", "note"]
    universe = universe[[c for c in cols if c in universe.columns]]
    universe.to_csv(universe_path, index=False, encoding="utf-8-sig")
    print(f"[OK] 已寫回 {universe_path}")


if __name__ == "__main__":
    update()
