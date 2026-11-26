"""資料健康檢查（2026-11-26，harness 第 4 步：給 agent 用的指令，取代 CLAUDE.md「📊 定期確認資料是否正常」的手抄程式）。

只讀 DB（read_only），不抓資料、不寫檔。每項回 ok／warn／fail，有問題時附上「下一步跑什麼」。
- 行情：缺交易日、只抓到一部分的日子、最新一天落後（15 點前今天的行情還不算該有）
- 籌碼：三大法人／融資／外資持股，上市上櫃各自落後 > 1 個交易日（當天的晚上才公布）
- 集保：落後 > 14 天；月營收、董監持股：落後 > 2 個月，或 2 個月且已過 12 號

用法（dev 資料夾沒有 data/，用 --data-dir 指 master 的）：
    python scripts/healthcheck.py
    python scripts/healthcheck.py --json --data-dir C:\\Users\\Cody\\Desktop\\tw-sector-tracker\\data
exit code：0 全部正常、1 有 warn、2 有 fail、3 DB 正被排程寫入（稍後再跑）。
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from functools import partial
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers.trading_calendar import calendar_status  # noqa: E402
from screener.data_integrity import check_price_continuity, chips_freshness  # noqa: E402
from storage.duck import _is_lock_error  # noqa: E402

PRICE_READY_HOUR = 15          # 收盤行情 13:30 後才完整；排程 15:00 那輪才寫進當天
SHAREHOLDER_MAX_LAG_DAYS = 14  # 集保每週五資料、週六公布
MONTHLY_MAX_LAG_MONTHS = 2     # 10 月的資料 12 月 12 號後還沒有就算落後（月營收 10 號前公布）
MONTHLY_DUE_DAY = 12
OFFICIAL_BACKFILL_MAX_DAYS = 2  # 只缺一兩天優先官方來源（CLAUDE.md「資料跑掉時」）


def _result(name: str, status: str, detail: str, next_step: str | None = None) -> dict:
    return {"name": name, "status": status, "detail": detail, "next_step": next_step}


def _latest(con, table: str, col: str) -> date | None:
    v = con.execute(f"SELECT max({col}) FROM {table}").fetchone()[0]
    return pd.Timestamp(v).date() if v is not None else None


def check_prices(con, now: datetime, is_trading=calendar_status) -> dict:
    as_of = now.date() if now.hour >= PRICE_READY_HOUR else now.date() - timedelta(days=1)
    r = check_price_continuity(con, today=as_of, is_trading=is_trading)
    if r["ok"]:
        # 日曆還沒收今天（排程整輪沒跑時也不會更新）→ _stale_days 不算今天；平日 15 點後沒行情要提醒
        today = now.date()
        if (as_of == today and today.weekday() < 5 and is_trading(today) is None
                and r["latest"] is not None and r["latest"] < today):
            return _result("行情", "warn", f"最新 {r['latest']}，今天（平日）還沒有行情；日曆也還沒確認今天有沒有開盤",
                           "先查排程有沒有跑（logs/run.log、Get-ScheduledTaskInfo）；真的有開盤再 --backfill-official 今天")
        return _result("行情", "ok", f"最新 {r['latest']}，連續")
    parts = []
    if r["missing"]:
        parts.append("缺 " + "、".join(map(str, r["missing"])))
    elif r["gaps"]:
        parts.append("有斷層 " + "、".join(f"{a}→{b}" for a, b in r["gaps"]))
    if r["stale"]:
        parts.append(f"最新只到 {r['latest']}，之後缺 " + "、".join(map(str, r["stale"])))
    if r["partial"]:
        parts.append("只抓到一部分 " + "、".join(f"{d}（{n} 筆）" for d, n in r["partial"]))
    bad_days = sorted(set(r["missing"]) | set(r["stale"]) | {d for d, _ in r["partial"]})
    if bad_days and len(bad_days) <= OFFICIAL_BACKFILL_MAX_DAYS:
        step = f"python main.py --backfill-official {bad_days[0]}"
    else:
        step = ("python main.py --backfill-yf 20 --workers 3"
                "（20 個月，整段換成 Yahoo 資料，先看 CLAUDE.md「資料跑掉時」；要 Cody 同意）")
    return _result("行情", "fail", "；".join(parts), step)


def check_chips(con, now: datetime, ids_by_market: dict, is_trading=calendar_status) -> dict:
    msgs = chips_freshness(con, now.date(), ids_by_market, is_trading=is_trading)
    if not msgs:
        return _result("籌碼", "ok", "三大法人／融資／外資持股都在 1 個交易日內")
    return _result("籌碼", "fail", "；".join(msgs), "python main.py --backfill-chips 14")


def check_shareholder(con, today: date) -> dict:
    latest = _latest(con, "shareholder", "date")
    if latest is None:
        return _result("集保", "fail", "shareholder 沒有資料", "python main.py --backfill-shareholder 4")
    lag = (today - latest).days
    if lag > SHAREHOLDER_MAX_LAG_DAYS:
        return _result("集保", "warn", f"最新 {latest}（{lag} 天前）", "python main.py --backfill-shareholder 4")
    return _result("集保", "ok", f"最新 {latest}")


def _months_behind(latest: date, today: date) -> int:
    return (today.year - latest.year) * 12 + today.month - latest.month


def check_monthly(con, today: date, name: str, table: str, col: str, step: str) -> dict:
    latest = _latest(con, table, col)
    if latest is None:
        return _result(name, "fail", f"{table} 沒有資料", step)
    behind = _months_behind(latest, today)
    if behind > MONTHLY_MAX_LAG_MONTHS or (behind == MONTHLY_MAX_LAG_MONTHS and today.day > MONTHLY_DUE_DAY):
        return _result(name, "warn", f"最新 {latest:%Y-%m}（落後 {behind} 個月）", step)
    return _result(name, "ok", f"最新 {latest:%Y-%m}")


def load_ids_by_market(universe_path: Path) -> dict:
    df = pd.read_csv(universe_path, dtype={"stock_id": str}, encoding="utf-8-sig")
    return {ex: set(g["stock_id"]) for ex, g in df.groupby("exchange")}


def run(data_dir: Path, now: datetime, universe_path: Path = ROOT / "data" / "stock_universe.csv") -> list[dict]:
    is_trading = partial(calendar_status, path=data_dir / "trading_calendar.csv")
    con = duckdb.connect(str(data_dir / "screener.db"), read_only=True)
    try:
        today = now.date()
        return [
            check_prices(con, now, is_trading),
            check_chips(con, now, load_ids_by_market(universe_path), is_trading),
            check_shareholder(con, today),
            check_monthly(con, today, "月營收", "monthly_revenue", "revenue_month",
                          "python main.py --update-fundamentals"),
            check_monthly(con, today, "董監持股", "insider_holdings", "report_date",
                          "python main.py --update-insider-holdings（逐股查詢約 38 分鐘）"),
        ]
    finally:
        con.close()


def exit_code(results: list[dict]) -> int:
    statuses = {r["status"] for r in results}
    return 2 if "fail" in statuses else 1 if "warn" in statuses else 0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="資料健康檢查（只讀）")
    p.add_argument("--json", action="store_true", help="輸出 JSON（給 agent）")
    p.add_argument("--data-dir", type=Path, default=ROOT / "data", help="放 screener.db 的資料夾")
    args = p.parse_args(argv)
    if not (args.data_dir / "screener.db").exists():
        print(f"找不到 {args.data_dir / 'screener.db'}；dev 資料夾沒有 data/，"
              r"請加 --data-dir C:\Users\Cody\Desktop\tw-sector-tracker\data")
        return 2
    try:
        results = run(args.data_dir, datetime.now())
    except duckdb.IOException as exc:
        if not _is_lock_error(exc):
            raise
        print("DB 正被排程寫入（盤中一輪約 2.5 分鐘），稍後再跑。")
        return 3
    code = exit_code(results)
    if args.json:
        print(json.dumps({"exit_code": code, "checks": results}, ensure_ascii=False, indent=2))
        return code
    icon = {"ok": "✅", "warn": "⚠️", "fail": "❌"}
    for r in results:
        print(f"{icon[r['status']]} {r['name']}：{r['detail']}")
        if r["next_step"]:
            print(f"   → {r['next_step']}")
    return code


if __name__ == "__main__":
    sys.exit(main())
