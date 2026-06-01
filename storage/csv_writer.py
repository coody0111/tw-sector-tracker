import pandas as pd
from pathlib import Path
from datetime import date
from typing import List, Dict, Any

ENC = "utf-8-sig"  # BOM ensures Excel opens Chinese correctly


class CsvWriter:
    def __init__(self, base_dir: str = "data"):
        self.base = Path(base_dir)
        for sub in ("sectors", "daily_prices", "sector_performance", "changes"):
            (self.base / sub).mkdir(parents=True, exist_ok=True)

    def write_sector_stocks(self, records: List[Dict[str, Any]], trade_date: date) -> None:
        if not records:
            return
        df = pd.DataFrame(records)
        df.insert(0, "date", trade_date.isoformat())

        industry = df[df["sector_type"] == "industry"]
        concept = df[df["sector_type"] == "concept"]

        industry.to_csv(self.base / "sectors" / "industry_sectors.csv", index=False, encoding=ENC)
        concept.to_csv(self.base / "sectors" / "concept_sectors.csv", index=False, encoding=ENC)

    def write_daily_prices(self, df: pd.DataFrame, trade_date: date) -> None:
        path = self.base / "daily_prices" / f"{trade_date.isoformat()}.csv"
        df.to_csv(path, index=False, encoding=ENC)

    def append_changes(self, changes: List[Dict[str, Any]]) -> None:
        path = self.base / "changes" / "changes_log.csv"
        df = pd.DataFrame(changes)
        write_header = not path.exists()
        df.to_csv(path, mode="a", header=write_header, index=False, encoding=ENC)

    def write_sector_performance(self, records: List[Dict[str, Any]], trade_date: date) -> None:
        path = self.base / "sector_performance" / f"{trade_date.isoformat()}.csv"
        pd.DataFrame(records).to_csv(path, index=False, encoding=ENC)

    def read_sector_stocks(self, sector_type: str) -> pd.DataFrame:
        fname = "industry_sectors.csv" if sector_type == "industry" else "concept_sectors.csv"
        path = self.base / "sectors" / fname
        if not path.exists():
            return pd.DataFrame()
        return pd.read_csv(path, encoding=ENC)
