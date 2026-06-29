"""
DuckDB 資料庫 - 存放每日行情歷史與技術指標。
直接從 data/daily_prices/*.csv 讀取，不需要手動 import。
"""
import duckdb
import pandas as pd
from pathlib import Path

DB_PATH = "data/screener.db"
CSV_GLOB = "data/daily_prices/*.csv"


def get_conn() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(DB_PATH)


def init_db() -> None:
    """建立資料庫 schema（冪等）。"""
    Path("data").mkdir(exist_ok=True)
    con = get_conn()
    con.execute("""
        CREATE TABLE IF NOT EXISTS daily_prices (
            stock_id    VARCHAR,
            date        DATE,
            open        DOUBLE,
            high        DOUBLE,
            low         DOUBLE,
            close       DOUBLE,
            volume      BIGINT,
            change      DOUBLE,
            change_pct  DOUBLE,
            PRIMARY KEY (stock_id, date)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS sector_stocks (
            sector_code VARCHAR,
            sector_name VARCHAR,
            stock_id    VARCHAR,
            stock_name  VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS institutional (
            stock_id    VARCHAR,
            date        DATE,
            foreign_net BIGINT,
            trust_net   BIGINT,
            dealer_net  BIGINT,
            total_net   BIGINT,
            PRIMARY KEY (stock_id, date)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS margin (
            stock_id        VARCHAR,
            date            DATE,
            margin_balance  BIGINT,
            margin_change   BIGINT,
            short_balance   BIGINT,
            short_change    BIGINT,
            PRIMARY KEY (stock_id, date)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS shareholder (
            stock_id        VARCHAR NOT NULL,
            date            DATE NOT NULL,
            lv12_15_pct     DOUBLE,
            lv12_15_cnt     INTEGER,
            total_shares    BIGINT,
            week_chg        DOUBLE,
            streak          INTEGER,
            PRIMARY KEY (stock_id, date)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS broker_branch (
            stock_id        VARCHAR NOT NULL,
            date            DATE NOT NULL,
            broker_id       VARCHAR NOT NULL,
            broker_name     VARCHAR,
            buy_shares      BIGINT,
            sell_shares     BIGINT,
            net_shares      BIGINT,
            PRIMARY KEY (stock_id, date, broker_id)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            stock_id        VARCHAR,
            stock_name      VARCHAR,
            sector_name     VARCHAR,
            date            DATE,
            close           DOUBLE,
            signal_type     VARCHAR,
            support         DOUBLE,
            resistance      DOUBLE,
            range_pct       DOUBLE,
            adx             DOUBLE,
            rsi             DOUBLE,
            ma20            DOUBLE,
            score           INTEGER,
            notes           VARCHAR,
            PRIMARY KEY (stock_id, date)
        )
    """)
    con.close()


def import_csv_prices() -> int:
    """把 data/daily_prices/*.csv 的資料全部 upsert 進 daily_prices 表。"""
    con = get_conn()

    # 從 CSV 讀取所有資料，日期從檔名抓
    raw = con.execute(f"""
        SELECT
            CAST(stock_id AS VARCHAR)   AS stock_id,
            CAST(regexp_extract(filename, '(\\d{{4}}-\\d{{2}}-\\d{{2}})', 1) AS DATE) AS date,
            NULL::DOUBLE AS open,
            NULL::DOUBLE AS high,
            NULL::DOUBLE AS low,
            CAST(close AS DOUBLE)        AS close,
            CAST(volume AS BIGINT)       AS volume,
            CAST(change AS DOUBLE)       AS change,
            CAST(change_pct AS DOUBLE)   AS change_pct
        FROM read_csv_auto('{CSV_GLOB}', filename=true, types={{'stock_id': 'VARCHAR'}})
        WHERE close IS NOT NULL
    """).df()

    if raw.empty:
        return 0

    # 去重：同一 (stock_id, date) 保留最後一筆
    raw = raw.drop_duplicates(subset=["stock_id", "date"], keep="last")

    # Upsert：先刪同一 (stock_id, date)，再插入
    con.execute("DELETE FROM daily_prices WHERE (stock_id, date) IN (SELECT stock_id, date FROM raw)")
    con.execute("INSERT INTO daily_prices SELECT * FROM raw")
    count = len(raw)
    con.close()
    return count


def import_sector_stocks(sectors_csv: str = "data/sectors/industry_sectors.csv") -> int:
    """把族群成份股匯入資料庫（每次全部覆蓋）。"""
    if not Path(sectors_csv).exists():
        return 0
    con = get_conn()
    con.execute("DELETE FROM sector_stocks")
    con.execute(f"""
        INSERT INTO sector_stocks
        SELECT
            CAST(sector_code AS VARCHAR) AS sector_code,
            CAST(sector_name AS VARCHAR) AS sector_name,
            CAST(stock_id    AS VARCHAR) AS stock_id,
            CAST(stock_name  AS VARCHAR) AS stock_name
        FROM read_csv_auto('{sectors_csv}')
    """)
    count = con.execute("SELECT COUNT(*) FROM sector_stocks").fetchone()[0]
    con.close()
    return count


def get_price_history(stock_id: str, days: int = 90) -> pd.DataFrame:
    """取單支股票最近 N 天的行情，按日期升序排列。"""
    con = get_conn()
    df = con.execute("""
        SELECT date, open, high, low, close, volume, change, change_pct
        FROM daily_prices
        WHERE stock_id = ?
        ORDER BY date DESC
        LIMIT ?
    """, [stock_id, days]).df()
    con.close()
    return df.sort_values("date").reset_index(drop=True)


def get_chips_today(trade_date: str) -> pd.DataFrame:
    """
    取今日籌碼資料（三大法人 + 融資融券），以 stock_id 為 key 回傳。
    trade_date: 'YYYY-MM-DD'
    """
    con = get_conn()
    df = con.execute("""
        SELECT
            COALESCE(i.stock_id, m.stock_id) AS stock_id,
            i.foreign_net,
            i.trust_net,
            i.dealer_net,
            i.total_net,
            m.margin_balance,
            m.margin_change,
            m.short_balance,
            m.short_change
        FROM
            (SELECT * FROM institutional WHERE date = ?) i
            FULL OUTER JOIN
            (SELECT * FROM margin WHERE date = ?) m
            ON i.stock_id = m.stock_id
    """, [trade_date, trade_date]).df()
    con.close()
    return df


def get_shareholder_top(n: int = 50) -> pd.DataFrame:
    """取最新週大戶持倉資料，含週變化與連增週數，按 streak desc 排序。"""
    con = get_conn()
    df = con.execute("""
        WITH latest AS (
            SELECT stock_id, MAX(date) AS max_date
            FROM shareholder GROUP BY stock_id
        )
        SELECT s.stock_id, s.date, s.lv12_15_pct, s.lv12_15_cnt,
               s.week_chg, s.streak
        FROM shareholder s
        JOIN latest l ON s.stock_id = l.stock_id AND s.date = l.max_date
        ORDER BY s.streak DESC, s.lv12_15_pct DESC
    """).df()
    con.close()
    return df


def get_all_stocks_latest(min_days: int = 10) -> pd.DataFrame:
    """取所有至少有 min_days 天資料的股票清單。"""
    con = get_conn()
    df = con.execute("""
        SELECT stock_id, COUNT(*) as day_count, MAX(date) as latest_date
        FROM daily_prices
        GROUP BY stock_id
        HAVING COUNT(*) >= ?
        ORDER BY stock_id
    """, [min_days]).df()
    con.close()
    return df
