"""
DuckDB 資料庫 - 存放每日行情歷史與技術指標。
直接從 data/daily_prices/*.csv 讀取，不需要手動 import。
"""
import logging
import duckdb
import pandas as pd
from pathlib import Path

logger = logging.getLogger(__name__)

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
            lv12_15_shares  BIGINT,
            total_shares    BIGINT,
            week_chg        DOUBLE,
            streak          INTEGER,
            lv12_shares     BIGINT,
            lv12_pct        DOUBLE,
            lv15_shares     BIGINT,
            lv15_pct        DOUBLE,
            PRIMARY KEY (stock_id, date)
        )
    """)
    con.execute("ALTER TABLE shareholder ADD COLUMN IF NOT EXISTS lv12_15_shares BIGINT")
    con.execute("ALTER TABLE shareholder ADD COLUMN IF NOT EXISTS lv12_shares BIGINT")
    con.execute("ALTER TABLE shareholder ADD COLUMN IF NOT EXISTS lv12_pct DOUBLE")
    con.execute("ALTER TABLE shareholder ADD COLUMN IF NOT EXISTS lv15_shares BIGINT")
    con.execute("ALTER TABLE shareholder ADD COLUMN IF NOT EXISTS lv15_pct DOUBLE")
    con.execute("""
        CREATE TABLE IF NOT EXISTS foreign_holdings (
            stock_id    VARCHAR NOT NULL,
            date        DATE NOT NULL,
            foreign_pct DOUBLE,
            PRIMARY KEY (stock_id, date)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS insider_holdings (
            stock_id                VARCHAR NOT NULL,
            report_date             DATE NOT NULL,
            company_shares          BIGINT,
            company_chg             BIGINT,
            company_pledge_pct      DOUBLE,
            major_holder_shares     BIGINT,
            major_holder_chg        BIGINT,
            major_holder_pledge_pct DOUBLE,
            PRIMARY KEY (stock_id, report_date)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS pattern_signals (
            stock_id     VARCHAR NOT NULL,
            pattern      VARCHAR NOT NULL,
            signal_date  DATE    NOT NULL,
            anchor       DOUBLE,
            stop         DOUBLE,
            target       DOUBLE,
            rr           DOUBLE,
            status       VARCHAR DEFAULT 'active',
            last_check   DATE,
            days_held    INTEGER DEFAULT 0,
            consec_below INTEGER DEFAULT 0,
            PRIMARY KEY (stock_id, pattern, signal_date)
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


def _filter_stale(df: pd.DataFrame, min_streak: int = 5) -> pd.DataFrame:
    """
    排除假資料：同一股票若有「連續」≥ min_streak 天 close+volume 完全相同，
    整批視為 placeholder，從 df 中移除。
    只計連續出現（日期排序後相鄰相同才累計），避免誤刪合法的偶發重複收盤。
    """
    df = df.copy().sort_values(["stock_id", "date"]).reset_index(drop=True)
    df["_cv"] = df["close"].astype(str) + "_" + df["volume"].astype(str)

    # 連續出現計數：換 stock 或換 _cv 就重置
    df["_streak"] = (
        (df["_cv"] != df["_cv"].shift()) | (df["stock_id"] != df["stock_id"].shift())
    ).cumsum()
    streak_max = df.groupby(["stock_id", "_cv", "_streak"]).size().reset_index(name="run")
    stale_keys = streak_max[streak_max["run"] >= min_streak][["stock_id", "_cv"]].drop_duplicates()

    if stale_keys.empty:
        return df.drop(columns=["_cv", "_streak"])

    stale_index = set(zip(stale_keys["stock_id"], stale_keys["_cv"]))
    mask = df.apply(lambda r: (r["stock_id"], r["_cv"]) in stale_index, axis=1)
    removed = mask.sum()
    if removed:
        logger.info("_filter_stale: 排除 %d 筆連續假資料（%d 個 stock×key）", removed, len(stale_index))
    return df[~mask].drop(columns=["_cv", "_streak"])


def import_csv_prices(filter_stale: bool = False) -> int:
    """把 data/daily_prices/*.csv 的資料全部 upsert 進 daily_prices 表。
    filter_stale=True 時自動排除連續多天完全相同的假資料。
    """
    con = get_conn()

    # 從 CSV 讀取所有資料，日期從檔名抓。union_by_name=true 讓舊格式CSV(沒有
    # open/high/low欄位，例如scrapers/daily_prices.py早期輸出)跟新格式CSV(有
    # open/high/low，例如scrapers/realtime.py)混在同一批glob讀取時，缺欄位的
    # 檔案自動補NULL，而不是像原本那樣不管CSV裡有沒有這3欄一律寫死NULL、
    # 把scraper真的抓到的OHLC資料在匯入這關直接丟掉。
    raw = con.execute(f"""
        SELECT
            CAST(stock_id AS VARCHAR)   AS stock_id,
            CAST(regexp_extract(filename, '(\\d{{4}}-\\d{{2}}-\\d{{2}})', 1) AS DATE) AS date,
            TRY_CAST(open AS DOUBLE)    AS open,
            TRY_CAST(high AS DOUBLE)    AS high,
            TRY_CAST(low AS DOUBLE)     AS low,
            CAST(close AS DOUBLE)        AS close,
            CAST(volume AS BIGINT)       AS volume,
            CAST(change AS DOUBLE)       AS change,
            CAST(change_pct AS DOUBLE)   AS change_pct
        FROM read_csv_auto('{CSV_GLOB}', filename=true, union_by_name=true, types={{'stock_id': 'VARCHAR'}})
        WHERE close IS NOT NULL
    """).df()

    if raw.empty:
        return 0

    # 去重：同一 (stock_id, date) 保留最後一筆
    raw = raw.drop_duplicates(subset=["stock_id", "date"], keep="last")

    if filter_stale:
        raw = _filter_stale(raw)

    # Upsert：先刪同一 (stock_id, date)，再插入
    con.execute("DELETE FROM daily_prices WHERE (stock_id, date) IN (SELECT stock_id, date FROM raw)")
    con.execute("INSERT INTO daily_prices SELECT * FROM raw")
    count = len(raw)
    con.close()
    return count


def reimport_db() -> int:
    """完整重建 daily_prices：清空後從所有 CSV 重新匯入。"""
    import logging as _log
    _logger = _log.getLogger(__name__)
    con = get_conn()
    con.execute("DELETE FROM daily_prices")
    con.close()
    _logger.info("daily_prices 已清空，開始重新匯入...")
    n = import_csv_prices()
    _logger.info("reimport 完成：共 %d 筆", n)
    return n


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

    三大法人/融資融券是盤後才發布，比盤中就有的股價晚一天。且 TWSE / TPEx 兩個
    來源可能停在不同日期（例如某天只有 TWSE margin、TPEx margin 更慢一天）。

    因此對 institutional / margin 各自做 **per-stock** fallback：每支股票取自己
    <= trade_date 的最新一筆，而不是整張表取單一最新日期——否則若表的最新日剛好
    缺某個交易所（例：07-07 margin 只有 TWSE），那個交易所的個股就會被漏掉、
    頁面仍顯示「─」。兩張表獨立 fallback。
    """
    con = get_conn()
    df = con.execute("""
        WITH latest_inst AS (
            SELECT stock_id, foreign_net, trust_net, dealer_net, total_net
            FROM institutional
            WHERE date <= ?
            QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) = 1
        ),
        latest_margin AS (
            SELECT stock_id, margin_balance, margin_change, short_balance, short_change
            FROM margin
            WHERE date <= ?
            QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) = 1
        )
        SELECT
            COALESCE(i.stock_id, m.stock_id) AS stock_id,
            i.foreign_net, i.trust_net, i.dealer_net, i.total_net,
            m.margin_balance, m.margin_change, m.short_balance, m.short_change
        FROM latest_inst i
        FULL OUTER JOIN latest_margin m ON i.stock_id = m.stock_id
    """, [trade_date, trade_date]).df()
    con.close()
    return df


def get_latest_total_shares(trade_date: str) -> pd.DataFrame:
    """
    取每支股票最新一筆(<= trade_date)集保已發行股數(total_shares)，供融資/融券佔比計算。
    trade_date: 'YYYY-MM-DD'

    跟 get_chips_today() 一樣做 per-stock fallback：每支股票各自取 <= trade_date 的
    最新一筆，不是整張表取單一最新日期——shareholder 表是每週更新，同一批股票裡
    不同股票的「最新一筆」日期可能不同（例如某股某週資料抓取失敗、跳過一週）。
    """
    con = get_conn()
    df = con.execute("""
        SELECT stock_id, total_shares, date
        FROM shareholder
        WHERE date <= ?
        QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) = 1
    """, [trade_date]).df()
    con.close()
    return df


def get_shareholder_top(n: int = 50) -> pd.DataFrame:
    """取最新週大戶持倉資料，含週變化、連增週數、張數變化與上週日期，
    以及 400張(lv12)/1000張(lv15) 分層的現況與週張數變化，按 streak desc 排序。"""
    from scrapers.shareholder import _MAX_VALID_HOLDER_PCT
    con = get_conn()
    df = con.execute(f"""
        WITH ranked AS (
            SELECT stock_id, date, lv12_15_pct, lv12_15_cnt, lv12_15_shares, week_chg, streak,
                   lv12_shares, lv12_pct, lv15_shares, lv15_pct,
                   ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) AS rn
            FROM shareholder
        )
        SELECT latest.stock_id, latest.date, prev.date AS prev_date,
               latest.lv12_15_pct, latest.lv12_15_cnt, latest.lv12_15_shares,
               latest.week_chg, latest.streak,
               (latest.lv12_15_shares - prev.lv12_15_shares) AS share_chg,
               latest.lv12_shares, latest.lv12_pct,
               (latest.lv12_shares - prev.lv12_shares) AS lv12_chg,
               latest.lv15_shares, latest.lv15_pct,
               (latest.lv15_shares - prev.lv15_shares) AS lv15_chg
        FROM (SELECT * FROM ranked WHERE rn = 1) latest
        LEFT JOIN (SELECT * FROM ranked WHERE rn = 2) prev ON latest.stock_id = prev.stock_id
        WHERE latest.lv12_15_pct < {_MAX_VALID_HOLDER_PCT}
            -- 離群值防護(#2)：>=門檻幾乎不可能(TDCC解析異常)，排除離榜；
            -- NULL(被改寫的異常)也一併排除(NULL<閾值→false)
        ORDER BY latest.streak DESC, latest.lv12_15_pct DESC
    """).df()
    con.close()
    return df


def get_rolling_returns(periods=(5, 7, 10, 14)) -> dict:
    """各股「近 N 交易日累積漲跌幅」，用**收盤價比值法**（非複利 change_pct，避免逐日四捨五入
    連乘的捨入漂移）：`近N日% = (最新交易日收盤 / N 個交易日前收盤 − 1) × 100`。
    定義：最新交易日 = rn1，N 交易日前 = rn(N+1)。資料不足／NULL(→nan)／除零一律回 None。
    回傳 `{stock_id: {5: pct 或 None, 7: ..., 10: ..., 14: ...}}`。

    chips.html Section 8 大戶持倉表（近5/7/10/14日）沿用本函式。
    ⚠️ index.html 2026-07-22 改成熱區格版面（`export/index_generator.py::build_stock_detail_data()`）
    後，個股點開面板只顯示單日 `change_pct`，不再呼叫本函式——這裡不再是「兩頁共用一致」的
    說法，若之後 index.html 想恢復近N日欄位，記得回頭接這支函式維持跟 chips.html 一致。

    ⚠️ rn 數的是 daily_prices 裡「實際存在的日期」：若某交易日缺資料（gap），「N 交易日前」會
    實際跨到更早一天，近N日會多算。前提是 daily_prices 沒有交易日缺漏。"""
    periods = tuple(periods)
    max_rn = max({1} | {p + 1 for p in periods})
    con = get_conn()
    df = con.execute(f"""
        SELECT stock_id, close, rn FROM (
            SELECT stock_id, close,
                   ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) AS rn
            FROM daily_prices
        ) WHERE rn <= {max_rn}
    """).df()
    con.close()

    def _ret(c0, cn):
        if c0 is None or cn is None or pd.isna(c0) or pd.isna(cn) or cn == 0:
            return None
        return round((c0 - cn) / cn * 100, 2)

    out = {}
    for sid, g in df.groupby("stock_id"):
        rn_close = dict(zip(g["rn"].astype(int), g["close"]))
        c0 = rn_close.get(1)
        out[str(sid)] = {p: _ret(c0, rn_close.get(p + 1)) for p in periods}
    return out


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
