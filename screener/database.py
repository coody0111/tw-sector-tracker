"""
DuckDB 資料庫 - 存放每日行情歷史與技術指標。
直接從 data/daily_prices/*.csv 讀取，不需要手動 import。
"""
import glob
import logging
import re
import duckdb
import pandas as pd
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Union

from screener.data_integrity import window_is_reliable

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
        CREATE TABLE IF NOT EXISTS monthly_revenue (
            stock_id                 VARCHAR NOT NULL,
            stock_name               VARCHAR,
            exchange                 VARCHAR NOT NULL,
            industry                 VARCHAR,
            revenue_month            DATE NOT NULL,
            revenue                  BIGINT,
            previous_month_revenue   BIGINT,
            previous_year_revenue    BIGINT,
            reported_mom_pct         DOUBLE,
            reported_yoy_pct         DOUBLE,
            ytd_revenue              BIGINT,
            previous_ytd_revenue     BIGINT,
            reported_ytd_yoy_pct     DOUBLE,
            note                     VARCHAR,
            report_date              DATE,
            first_seen_at            TIMESTAMP NOT NULL,
            fetched_at               TIMESTAMP NOT NULL,
            source                   VARCHAR NOT NULL,
            PRIMARY KEY (stock_id, revenue_month)
        )
    """)
    con.execute("DROP VIEW IF EXISTS monthly_revenue_growth")
    monthly_report_date_is_not_null = any(
        "report_date" in (columns or [])
        for (columns,) in con.execute("""
            SELECT constraint_column_names
            FROM duckdb_constraints()
            WHERE table_name = 'monthly_revenue' AND constraint_type = 'NOT NULL'
        """).fetchall()
    )
    if monthly_report_date_is_not_null:
        con.execute("ALTER TABLE monthly_revenue ALTER COLUMN report_date DROP NOT NULL")
    con.execute("""
        CREATE TABLE IF NOT EXISTS monthly_revenue_pages (
            page_sha256   VARCHAR PRIMARY KEY,
            exchange      VARCHAR NOT NULL,
            revenue_month DATE NOT NULL,
            source_url    VARCHAR NOT NULL,
            local_path    VARCHAR NOT NULL,
            byte_size     BIGINT NOT NULL,
            first_seen_at TIMESTAMP NOT NULL,
            retrieved_at  TIMESTAMP NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS monthly_revenue_versions (
            page_sha256              VARCHAR NOT NULL,
            stock_id                 VARCHAR NOT NULL,
            stock_name               VARCHAR,
            exchange                 VARCHAR NOT NULL,
            industry                 VARCHAR,
            revenue_month            DATE NOT NULL,
            revenue                  BIGINT,
            previous_month_revenue   BIGINT,
            previous_year_revenue    BIGINT,
            reported_mom_pct         DOUBLE,
            reported_yoy_pct         DOUBLE,
            ytd_revenue              BIGINT,
            previous_ytd_revenue     BIGINT,
            reported_ytd_yoy_pct     DOUBLE,
            note                     VARCHAR,
            report_date              DATE,
            first_seen_at            TIMESTAMP NOT NULL,
            source                   VARCHAR NOT NULL,
            PRIMARY KEY (page_sha256, stock_id)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS financial_facts (
            stock_id         VARCHAR NOT NULL,
            stock_name       VARCHAR,
            exchange         VARCHAR NOT NULL,
            period_end       DATE NOT NULL,
            fiscal_year      INTEGER NOT NULL,
            quarter          INTEGER NOT NULL,
            statement_type   VARCHAR NOT NULL,
            industry_schema  VARCHAR NOT NULL,
            metric_key       VARCHAR NOT NULL,
            raw_name         VARCHAR NOT NULL,
            value            DOUBLE,
            unit             VARCHAR NOT NULL,
            is_ytd           BOOLEAN NOT NULL,
            report_date      DATE,
            first_seen_at    TIMESTAMP NOT NULL,
            fetched_at       TIMESTAMP NOT NULL,
            source           VARCHAR NOT NULL,
            PRIMARY KEY (stock_id, period_end, statement_type, metric_key, industry_schema)
        )
    """)
    # DuckDB 不允許有 dependent view 時 ALTER table；先移除、下方會用新定義重建。
    con.execute("DROP VIEW IF EXISTS financial_fact_growth")
    con.execute("DROP VIEW IF EXISTS financial_ratios")
    # Phase 1 已建立的本機 DB 曾把 report_date 設為 NOT NULL；MOPS 批次 ZIP 沒有官方保證的
    # 申報日，不能拿抓取日冒充，因此 migration 明確允許 NULL。
    report_date_is_not_null = any(
        "report_date" in (columns or [])
        for (columns,) in con.execute("""
            SELECT constraint_column_names
            FROM duckdb_constraints()
            WHERE table_name = 'financial_facts' AND constraint_type = 'NOT NULL'
        """).fetchall()
    )
    if report_date_is_not_null:
        con.execute("ALTER TABLE financial_facts ALTER COLUMN report_date DROP NOT NULL")
    con.execute("""
        CREATE TABLE IF NOT EXISTS xbrl_archives (
            archive_sha256     VARCHAR PRIMARY KEY,
            accounting_standard VARCHAR NOT NULL,
            fiscal_year        INTEGER NOT NULL,
            quarter            INTEGER NOT NULL,
            period_end         DATE NOT NULL,
            source_url         VARCHAR NOT NULL,
            source_filename    VARCHAR NOT NULL,
            local_path         VARCHAR NOT NULL,
            byte_size          BIGINT NOT NULL,
            etag               VARCHAR,
            last_modified      VARCHAR,
            first_seen_at      TIMESTAMP NOT NULL,
            retrieved_at       TIMESTAMP NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS xbrl_filings (
            filing_sha256      VARCHAR PRIMARY KEY,
            archive_sha256     VARCHAR NOT NULL,
            entry_path         VARCHAR NOT NULL,
            stock_id           VARCHAR NOT NULL,
            stock_name         VARCHAR,
            period_end         DATE NOT NULL,
            fiscal_year        INTEGER NOT NULL,
            quarter            INTEGER NOT NULL,
            content_format     VARCHAR NOT NULL,
            taxonomy_refs_json VARCHAR NOT NULL,
            reported_at        TIMESTAMP,
            first_seen_at      TIMESTAMP NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS xbrl_archive_entries (
            archive_sha256 VARCHAR NOT NULL,
            entry_path     VARCHAR NOT NULL,
            filing_sha256  VARCHAR NOT NULL,
            PRIMARY KEY (archive_sha256, entry_path)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS xbrl_archive_entries (
            archive_sha256 VARCHAR NOT NULL,
            entry_path     VARCHAR NOT NULL,
            filing_sha256  VARCHAR NOT NULL,
            PRIMARY KEY (archive_sha256, entry_path)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS xbrl_facts (
            filing_sha256 VARCHAR NOT NULL,
            fact_index    INTEGER NOT NULL,
            stock_id      VARCHAR NOT NULL,
            qname         VARCHAR NOT NULL,
            namespace_uri VARCHAR NOT NULL,
            local_name    VARCHAR NOT NULL,
            context_id    VARCHAR NOT NULL,
            period_start  DATE,
            period_end    DATE,
            instant       DATE,
            unit_id       VARCHAR,
            unit          VARCHAR,
            decimals      VARCHAR,
            dimensions_json VARCHAR NOT NULL,
            raw_value     VARCHAR,
            numeric_value DOUBLE,
            is_nil        BOOLEAN NOT NULL,
            PRIMARY KEY (filing_sha256, fact_index)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS xbrl_canonical_facts (
            filing_sha256 VARCHAR NOT NULL,
            stock_id      VARCHAR NOT NULL,
            period_end    DATE NOT NULL,
            fiscal_year   INTEGER NOT NULL,
            quarter       INTEGER NOT NULL,
            statement_type VARCHAR NOT NULL,
            industry_schema VARCHAR NOT NULL,
            metric_key    VARCHAR NOT NULL,
            qname         VARCHAR NOT NULL,
            context_id    VARCHAR NOT NULL,
            value         DOUBLE,
            unit          VARCHAR NOT NULL,
            is_ytd        BOOLEAN NOT NULL,
            first_seen_at TIMESTAMP NOT NULL,
            reported_at   TIMESTAMP,
            PRIMARY KEY (filing_sha256, statement_type, metric_key)
        )
    """)
    con.execute("""
        CREATE OR REPLACE VIEW xbrl_current_facts AS
        WITH ranked_archives AS (
            SELECT archive_sha256, fiscal_year, quarter,
                   ROW_NUMBER() OVER (
                       PARTITION BY accounting_standard, fiscal_year, quarter
                       ORDER BY retrieved_at DESC, archive_sha256 DESC
                   ) AS version_rank
            FROM xbrl_archives
            WHERE accounting_standard = 'IFRS'
        ), latest_archive AS (
            SELECT archive_sha256
            FROM ranked_archives
            WHERE version_rank = 1
        ), ranked AS (
            SELECT canonical.*, filing.stock_name,
                   ROW_NUMBER() OVER (
                       PARTITION BY canonical.stock_id, canonical.period_end,
                                    canonical.statement_type, canonical.metric_key
                       ORDER BY filing.first_seen_at DESC, canonical.filing_sha256 DESC
                   ) AS version_rank
            FROM xbrl_canonical_facts canonical
            JOIN xbrl_filings filing USING (filing_sha256)
            JOIN xbrl_archive_entries entry USING (filing_sha256)
            JOIN latest_archive
              ON latest_archive.archive_sha256 = entry.archive_sha256
        )
        SELECT filing_sha256, stock_id, stock_name, period_end, fiscal_year, quarter,
               statement_type, industry_schema, metric_key, qname, context_id,
               value, unit, is_ytd, first_seen_at, reported_at
        FROM ranked
        WHERE version_rank = 1
    """)
    con.execute("""
        CREATE OR REPLACE VIEW monthly_revenue_growth AS
        SELECT
            current.*,
            CASE
                WHEN previous.revenue IS NULL OR previous.revenue = 0 THEN NULL
                ELSE (current.revenue / previous.revenue::DOUBLE - 1) * 100
            END AS calculated_mom_pct,
            CASE
                WHEN previous_year.revenue IS NULL OR previous_year.revenue = 0 THEN NULL
                ELSE (current.revenue / previous_year.revenue::DOUBLE - 1) * 100
            END AS calculated_yoy_pct
        FROM monthly_revenue current
        LEFT JOIN monthly_revenue previous
          ON previous.stock_id = current.stock_id
         AND previous.revenue_month = CAST(current.revenue_month - INTERVAL '1 month' AS DATE)
        LEFT JOIN monthly_revenue previous_year
          ON previous_year.stock_id = current.stock_id
         AND previous_year.revenue_month = CAST(current.revenue_month - INTERVAL '1 year' AS DATE)
    """)
    con.execute("""
        CREATE OR REPLACE VIEW financial_fact_growth AS
        WITH single_period AS (
            SELECT
                current.*,
                CASE
                    WHEN current.statement_type = 'balance' THEN current.value
                    WHEN current.metric_key IN ('eps', 'diluted_eps') THEN NULL
                    WHEN current.quarter = 1 THEN current.value
                    WHEN previous_ytd.value IS NULL THEN NULL
                    ELSE current.value - previous_ytd.value
                END AS single_quarter_value
            FROM financial_facts current
            LEFT JOIN financial_facts previous_ytd
              ON previous_ytd.stock_id = current.stock_id
             AND previous_ytd.statement_type = current.statement_type
             AND previous_ytd.industry_schema = current.industry_schema
             AND previous_ytd.metric_key = current.metric_key
             AND previous_ytd.fiscal_year = current.fiscal_year
             AND previous_ytd.quarter = current.quarter - 1
        ), compared AS (
            SELECT
                current.*,
                previous_quarter.single_quarter_value AS previous_quarter_value,
                previous_year.single_quarter_value AS previous_year_quarter_value,
                previous_year.value AS previous_year_reported_value
            FROM single_period current
            LEFT JOIN single_period previous_quarter
              ON previous_quarter.stock_id = current.stock_id
             AND previous_quarter.statement_type = current.statement_type
             AND previous_quarter.industry_schema = current.industry_schema
             AND previous_quarter.metric_key = current.metric_key
              AND previous_quarter.period_end = CAST(
                    date_trunc('quarter', current.period_end) - INTERVAL '1 day' AS DATE
                  )
            LEFT JOIN single_period previous_year
              ON previous_year.stock_id = current.stock_id
             AND previous_year.statement_type = current.statement_type
             AND previous_year.industry_schema = current.industry_schema
             AND previous_year.metric_key = current.metric_key
             AND previous_year.fiscal_year = current.fiscal_year - 1
             AND previous_year.quarter = current.quarter
        )
        SELECT
            compared.*,
            CASE
                WHEN metric_key IN ('eps', 'diluted_eps')
                     OR previous_quarter_value IS NULL OR previous_quarter_value = 0 THEN NULL
                ELSE (single_quarter_value / previous_quarter_value - 1) * 100
            END AS calculated_qoq_pct,
            CASE
                WHEN metric_key IN ('eps', 'diluted_eps')
                     OR previous_year_quarter_value IS NULL OR previous_year_quarter_value = 0 THEN NULL
                ELSE (single_quarter_value / previous_year_quarter_value - 1) * 100
            END AS calculated_quarter_yoy_pct,
            CASE
                WHEN NOT is_ytd OR previous_year_reported_value IS NULL
                     OR previous_year_reported_value = 0 THEN NULL
                ELSE (value / previous_year_reported_value - 1) * 100
            END AS calculated_ytd_yoy_pct
        FROM compared
    """)
    con.execute("""
        CREATE OR REPLACE VIEW financial_ratios AS
        WITH pivoted AS (
            SELECT stock_id, period_end, fiscal_year, quarter,
                   MAX(CASE WHEN metric_key = 'revenue' THEN value END) AS revenue,
                   MAX(CASE WHEN metric_key = 'gross_profit' THEN value END) AS gross_profit,
                   MAX(CASE WHEN metric_key = 'operating_income' THEN value END) AS operating_income,
                   MAX(CASE WHEN metric_key = 'net_income_parent' THEN value END) AS net_income_parent,
                   MAX(CASE WHEN metric_key = 'net_income' THEN value END) AS net_income
            FROM financial_facts
            WHERE is_ytd
            GROUP BY stock_id, period_end, fiscal_year, quarter
        )
        SELECT *,
               CASE WHEN revenue IS NULL OR revenue = 0 THEN NULL
                    ELSE gross_profit / revenue * 100 END AS gross_margin_pct,
               CASE WHEN revenue IS NULL OR revenue = 0 THEN NULL
                    ELSE operating_income / revenue * 100 END AS operating_margin_pct,
               CASE WHEN revenue IS NULL OR revenue = 0 THEN NULL
                    ELSE COALESCE(net_income_parent, net_income) / revenue * 100 END AS net_margin_pct
        FROM pivoted
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


def _incremental_csv_files(con) -> Optional[List[str]]:
    """算出「這次真的需要匯入」的 CSV 檔清單，回 None 代表要走全量。

    每日流程只寫當天的 CSV，卻每次重讀全部 400+ 個檔、41 萬筆 upsert 回去，
    等於拿一模一樣的資料覆蓋自己（實測 6.69 秒，且隨歷史線性變慢：
    2026-08-25 是 3 秒、08-31 已 10 秒）。但全量匯入有個不能弄丟的副作用——
    它每天把所有歷史重新確保一次，某天匯入失敗（例如 TPEx 5xx、DuckDB 例外）
    留下的洞，隔天會自動補上。缺交易日正是「近N日漲跌幅失真」的根因，
    所以增量不能只匯今天，要匯：

      1. CSV 有、但 daily_prices 沒有的日期（不限多久以前）→ 保留自我修復
      2. 最新兩個日期 → 盤中 --realtime 寫的是即時價，收盤後要被收盤價覆蓋；
         取兩天是因為 main.py「市場尚未更新」防呆會把 trade_date 切回前一交易日

    比對成本約 40 毫秒（403 個檔名 vs 一次 DISTINCT date）。
    """
    files = sorted(Path(p) for p in glob.glob(CSV_GLOB))
    if not files:
        # 一個 CSV 都沒有＝沒東西可匯（回空清單），不是「退回全量」——退回全量會讓
        # read_csv_auto 對空目錄拋 IOException，重演 2026-08-28 那種匯入炸掉的情況
        return []

    def _date_of(path: Path) -> Optional[str]:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
        return m.group(1) if m else None

    by_date = {}
    for f in files:
        d = _date_of(f)
        if d is None:      # 檔名沒有日期就無從比對，保守起見退回全量
            return None
        by_date[d] = f

    db_dates = {
        str(r[0]) for r in con.execute("SELECT DISTINCT date FROM daily_prices").fetchall()
    }
    all_dates = sorted(by_date)
    todo = (set(all_dates) - db_dates) | set(all_dates[-2:])

    filled = sorted(set(all_dates) - db_dates)
    if filled:
        logger.info("增量匯入：補上 daily_prices 缺的 %d 天（%s）", len(filled), ", ".join(filled[:5]))
    return [str(by_date[d]) for d in sorted(todo)]


def import_csv_prices(filter_stale: bool = False, incremental: bool = False) -> int:
    """把 data/daily_prices/*.csv 的資料 upsert 進 daily_prices 表。

    filter_stale=True 時自動排除連續多天完全相同的假資料。
    incremental=True（每日流程用）只匯入 _incremental_csv_files() 算出來的那幾天，
    其餘（reimport_db()／backfill 收尾）維持全量，語意不變。
    """
    con = get_conn()

    # 從 CSV 讀取所有資料，日期從檔名抓。union_by_name=true 讓舊格式CSV(沒有
    # open/high/low欄位，例如scrapers/daily_prices.py早期輸出)跟新格式CSV(有
    # open/high/low，例如scrapers/realtime.py)混在同一批glob讀取時，缺欄位的
    # 檔案自動補NULL，而不是像原本那樣不管CSV裡有沒有這3欄一律寫死NULL、
    # 把scraper真的抓到的OHLC資料在匯入這關直接丟掉。
    target_files = _incremental_csv_files(con) if incremental else None
    if target_files is not None and not target_files:
        con.close()
        return 0
    csv_arg = repr(target_files) if target_files is not None else f"'{CSV_GLOB}'"
    source = (
        f"read_csv_auto({csv_arg}, filename=true, union_by_name=true, "
        f"types={{'stock_id': 'VARCHAR'}})"
    )

    # union_by_name 只能在「有些檔案有、有些沒有」時補 NULL；若**所有** CSV 都缺某欄
    # （例如 backfill_yfinance 早期只寫 close/volume，又剛好 _clear_price_csvs() 把含
    # OHLC 的舊檔全刪了），那欄在來源表根本不存在，直接寫 `TRY_CAST(open ...)` 會讓
    # DuckDB 把它解讀成同名別名的自我參照而拋 Binder Error，整批匯入失敗——而這一步
    # 是在 reimport_db() 已經清空 daily_prices 之後才執行的，炸掉就等於資料全空。
    # 所以先問來源表實際有哪些欄位，缺的用 NULL 補，讓匯入永遠不會因為欄位缺席而死。
    available = {
        str(r[0]).lower()
        for r in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()
    }

    def _col(name: str, sql_type: str, cast: str = "TRY_CAST") -> str:
        if name in available:
            return f"{cast}(src.{name} AS {sql_type}) AS {name}"
        return f"CAST(NULL AS {sql_type}) AS {name}"

    missing = [c for c in ("open", "high", "low") if c not in available]
    if missing:
        logger.warning(
            "CSV 缺少 %s 欄位，這些欄位匯入後為 NULL（K 棒等需要 OHLC 的功能會失效）。"
            "來源是 backfill 寫檔時沒帶上 OHLC，補資料時請確認 scrapers/backfill.py 有寫出這些欄位。",
            "/".join(missing),
        )

    raw = con.execute(f"""
        SELECT
            {_col('stock_id', 'VARCHAR', 'CAST')},
            CAST(regexp_extract(src.filename, '(\\d{{4}}-\\d{{2}}-\\d{{2}})', 1) AS DATE) AS date,
            {_col('open', 'DOUBLE')},
            {_col('high', 'DOUBLE')},
            {_col('low', 'DOUBLE')},
            {_col('close', 'DOUBLE')},
            {_col('volume', 'BIGINT')},
            {_col('change', 'DOUBLE')},
            {_col('change_pct', 'DOUBLE')}
        FROM {source} AS src
        WHERE src.close IS NOT NULL
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


def get_shareholder_trend(weeks: int = 5) -> dict:
    """每支股票近 N 週的 400張以上大戶%（lv12_15_pct）歷史，舊到新排序，供大戶持倉卡片
    的迷你趨勢走勢圖使用。實際筆數可能少於 weeks（歷史不足時，例如新上市股或剛納入
    追蹤的股票），不強制補齊——回傳筆數就是真實可用的資料點數。

    離群值防護跟 get_shareholder_top() 一致：>=_MAX_VALID_HOLDER_PCT 視為 TDCC 集保
    股權分散表解析異常，整筆排除。

    回傳 {stock_id: [{"date": str, "lv12_15_pct": float}, ...]}（舊到新）。
    """
    from scrapers.shareholder import _MAX_VALID_HOLDER_PCT
    con = get_conn()
    df = con.execute(f"""
        WITH ranked AS (
            SELECT stock_id, date, lv12_15_pct,
                   ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) AS rn
            FROM shareholder
            WHERE lv12_15_pct < {_MAX_VALID_HOLDER_PCT}
        )
        SELECT stock_id, date, lv12_15_pct
        FROM ranked
        WHERE rn <= {weeks}
        ORDER BY stock_id, date ASC
    """).df()
    con.close()

    result: dict = {}
    for _, row in df.iterrows():
        sid = str(row["stock_id"])
        result.setdefault(sid, []).append({
            "date": str(row["date"])[:10],
            "lv12_15_pct": float(row["lv12_15_pct"]),
        })
    return result


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
    實際跨到更早一天，近N日會多算。**這個前提不再靠假設**——每個窗口都會用
    `data_integrity.window_is_reliable()` 檢查實際跨了幾個日曆天，跨太多就回 None，
    寧可顯示「—」也不要給出跨了一個月卻標成「近5日」的假漲幅
    （2026-08-28 金居 8358 顯示 +100.37% 事件，見 data_integrity.py 模組說明）。"""
    periods = tuple(periods)
    max_rn = max({1} | {p + 1 for p in periods})
    con = get_conn()
    df = con.execute(f"""
        SELECT stock_id, close, date, rn FROM (
            SELECT stock_id, close, date,
                   ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) AS rn
            FROM daily_prices
        ) WHERE rn <= {max_rn}
    """).df()
    con.close()

    def _ret(c0, cn):
        if c0 is None or cn is None or pd.isna(c0) or pd.isna(cn) or cn == 0:
            return None
        return round((c0 - cn) / cn * 100, 2)

    def _as_date(value):
        """DuckDB 經 pandas 取回可能是 Timestamp／date／NaT，統一成 date 或 None。"""
        if value is None or pd.isna(value):
            return None
        return value.date() if hasattr(value, "date") else value

    out = {}
    blocked = 0
    for sid, g in df.groupby("stock_id"):
        rn = g["rn"].astype(int)
        rn_close = dict(zip(rn, g["close"]))
        rn_date = dict(zip(rn, g["date"]))
        c0 = rn_close.get(1)
        d0 = _as_date(rn_date.get(1))
        result = {}
        for p in periods:
            if window_is_reliable(d0, _as_date(rn_date.get(p + 1)), p):
                result[p] = _ret(c0, rn_close.get(p + 1))
            else:
                # 窗口跨度異常（中間有交易日缺漏）或資料不足——不給數字
                result[p] = None
                blocked += 1
        out[str(sid)] = result

    if blocked:
        logger.warning(
            "get_rolling_returns：%d 個「近N日」窗口因交易日缺漏被擋下（顯示為無資料）。"
            "請補齊 daily_prices 後重跑，詳見 data_integrity.check_price_continuity()",
            blocked,
        )
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


# ---------------------------------------------------------------------------
# 季報基本面快照
# spec: docs/superpowers/specs/2026-09-04-fundamentals-display-design.md
# ADR : docs/adr/0007-fundamentals-availability-uses-statutory-deadline.md
# ---------------------------------------------------------------------------

# 法定申報期限。DB 裡完全沒有真實申報日（financial_facts.report_date 填了 0/1,735,031、
# xbrl_filings.reported_at 填了 0/65,182），所以可得日一律假設公司拖到最後一天才申報：
# 只會晚看到、不會早看到，任何情況下都不可能製造前視偏誤。Q4(年報)是「隔年」3/31。
_STATUTORY_DEADLINE = {1: (5, 15), 2: (8, 14), 3: (11, 14), 4: (3, 31)}

# 成長率/比率的離群上限，依 2026Q2 對正式 DB 的實測分佈訂定（spec §8.2）：
# 單季營收 YoY 1016 檔裡只有 2 檔 >999%（所以營收不設限），但稅後淨利 573 檔裡有 45 檔
# (7.9%) >999%，最大 +199,700%——那不是髒值，是去年同季虧損、基期趨近 0 的數學結果。
_MAX_ABS_GROWTH_PCT = 999.0
_MAX_ABS_RATIO_PCT = 999.0

_FUNDAMENTALS_METRICS = ("revenue", "gross_profit", "pretax_income", "eps")

_FUNDAMENTALS_COLUMNS = [
    "stock_id", "fiscal_year", "quarter", "period_label", "available_date",
    "revenue", "revenue_yoy", "revenue_qoq",
    "gross_margin", "pretax_margin", "eps_ytd", "eps_yoy",
]


def _statutory_available_date(fiscal_year: int, quarter: int) -> date:
    """某一季的財報最早哪一天算「市場已經看得到」。

    Q1→當年 5/15、Q2→當年 8/14、Q3→當年 11/14、Q4(年報)→**隔年** 3/31。
    純函式、無 I/O：同一份資料在桌電與筆電必定得到相同答案。這是刻意的——
    `data/` 被 gitignore、兩台機器各一份 DB，用 first_seen_at 會讓同一天產出的頁面
    在兩台機器上不一樣（詳見 ADR 0007）。
    """
    if quarter not in _STATUTORY_DEADLINE:
        raise ValueError(f"quarter 必須是 1~4，收到 {quarter!r}")
    month, day = _STATUTORY_DEADLINE[quarter]
    return date(int(fiscal_year) + 1 if quarter == 4 else int(fiscal_year), month, day)


def _single_quarter(cur_ytd: Optional[float], prev_ytd: Optional[float],
                    quarter: int) -> Optional[float]:
    """把累計數換算成單季數。

    損益表 100% 都是累計值（is_ytd=true，DB 裡沒有任何一筆單季原始損益值），所以
    Q2~Q4 必須「本期累計 − 前一期累計」。Q1 的累計本身就是單季。
    前一期累計缺漏時回 None——不猜、不補 0，缺值優於錯值。
    """
    if cur_ytd is None:
        return None
    if quarter == 1:
        return float(cur_ytd)
    if prev_ytd is None:
        return None
    return float(cur_ytd) - float(prev_ytd)


def _revenue_growth(cur: Optional[float], base: Optional[float]) -> Optional[float]:
    """營收成長率(%)，**不設離群上限**。

    實測 2026Q2 單季營收 YoY：1016 檔裡只有 2 檔超過 999%，防護幾乎沒有作用，
    加了反而會把兩個真實的高成長案例藏起來。基期 <= 0 回 None（營收非正數本身就是
    異常資料，算不出有意義的成長率）。
    """
    if cur is None or base is None or base <= 0:
        return None
    return (cur / base - 1) * 100


def _profit_growth(cur: Optional[float], base: Optional[float]) -> Union[float, str, None]:
    """獲利類成長率。回傳 float(%)、文字標籤、或 None——呼叫端要用 isinstance 分辨。

    虧轉盈時基期趨近 0，成長率在數學上必然噴出六位數（實測 2026Q2 稅後淨利最大
    +199,700%）。那個數字計算正確但沒有資訊量，還會撐爆版面，所以改回文字：

    - 基期虧損、本期獲利 → 「轉盈」
    - 基期獲利、本期虧損 → 「轉虧」
    - 兩期都虧損         → None（成長率無意義，不硬算）
    - 兩期都獲利但成長 >999% → 「>999%」，**不是**「轉盈」
      （它本來就在賺錢，標成「轉盈」會是錯的描述）
    """
    if cur is None or base is None:
        return None
    if base <= 0 and cur > 0:
        return "轉盈"
    if base > 0 and cur <= 0:
        return "轉虧"
    if base <= 0:
        return None
    pct = (cur / base - 1) * 100
    # base>0 且 cur>0 時 pct 恆 > -100，所以只可能從上方越界
    return f">{int(_MAX_ABS_GROWTH_PCT)}%" if pct > _MAX_ABS_GROWTH_PCT else pct


def _margin_ratio(numerator: Optional[float], revenue: Optional[float]) -> Optional[float]:
    """利潤率(%)。超出 ±999% 一律回 None。

    毛利率本質上不該超過 100%，出現三位數以上必定是單位或 metric 映射出錯——
    這種情況缺值優於錯值，跟成長率的「轉盈/轉虧」處理方式刻意不同。
    """
    if numerator is None or revenue is None or revenue <= 0:
        return None
    pct = numerator / revenue * 100
    return None if abs(pct) > _MAX_ABS_RATIO_PCT else pct


def build_fundamentals_snapshot(facts: pd.DataFrame, as_of) -> pd.DataFrame:
    """把 financial_facts 的累計損益列，換算成每檔一列的「最新可見季」快照。

    純函式（不碰 DB），方便 pytest 用合成資料直接測。facts 需要
    stock_id / fiscal_year / quarter / metric_key / value 五欄。

    as_of：判斷「哪一季已經可見」的基準日，應該傳 daily_prices 的最新交易日而不是
    date.today()——頁面上收盤、籌碼、近N日全部對齊最新交易日，用 today() 會讓週末或
    連假產頁時出現「行情停在週五、基本面用週日判斷」的時間軸不一致。

    回傳欄位裡 revenue 是**單季**（千元）、eps_ytd 是**累計**（元）。兩者期間不同是
    資料本身的限制（累計 EPS 不能相減，期間內股數會因增資/減資/庫藏股而變動），
    呈現時必須在版面上標明，不能讓讀者以為同期間。

    revenue_yoy / revenue_qoq 恆為 float 或 None；eps_yoy 可能是 float、
    「轉盈」/「轉虧」/「>999%」字串、或 None。
    """
    as_of_date = as_of if isinstance(as_of, date) else \
        datetime.strptime(str(as_of)[:10], "%Y-%m-%d").date()

    if facts is None or facts.empty:
        return pd.DataFrame(columns=_FUNDAMENTALS_COLUMNS)

    # seq = fiscal_year*4 + quarter-1。用連續序號當 key，「上一季」就是 seq-1、
    # 「去年同季」就是 seq-4，跨年(Q1 的上一季是去年 Q4)完全不用特判。
    by_key: dict = {}
    seqs_by_stock: dict = {}
    for r in facts.itertuples(index=False):
        if pd.isna(r.value):
            continue
        sid = str(r.stock_id)
        seq = int(r.fiscal_year) * 4 + int(r.quarter) - 1
        by_key.setdefault((sid, seq), {})[str(r.metric_key)] = float(r.value)
        seqs_by_stock.setdefault(sid, set()).add(seq)

    def _ytd(sid: str, seq: int, metric: str) -> Optional[float]:
        return by_key.get((sid, seq), {}).get(metric)

    def _sq(sid: str, seq: int, metric: str) -> Optional[float]:
        return _single_quarter(_ytd(sid, seq, metric), _ytd(sid, seq - 1, metric),
                               seq % 4 + 1)

    rows = []
    for sid, seqs in seqs_by_stock.items():
        # 只考慮已經過了法定申報期限的期別；比較基期(seq-1 / seq-4)一定更早，
        # 而期限隨 seq 單調遞增，所以基期必然也已可見，不用再檢查一次。
        visible = [s for s in seqs
                   if _statutory_available_date(s // 4, s % 4 + 1) <= as_of_date]
        if not visible:
            continue
        seq = max(visible)
        fy, q = seq // 4, seq % 4 + 1

        revenue = _sq(sid, seq, "revenue")
        rows.append({
            "stock_id": sid,
            "fiscal_year": fy,
            "quarter": q,
            "period_label": f"{fy}Q{q}",
            "available_date": _statutory_available_date(fy, q),
            "revenue": revenue,
            "revenue_yoy": _revenue_growth(revenue, _sq(sid, seq - 4, "revenue")),
            "revenue_qoq": _revenue_growth(revenue, _sq(sid, seq - 1, "revenue")),
            "gross_margin": _margin_ratio(_sq(sid, seq, "gross_profit"), revenue),
            "pretax_margin": _margin_ratio(_sq(sid, seq, "pretax_income"), revenue),
            # EPS 只取累計、絕不相減：期間內股數會變動，累計 EPS 相減在數學上不成立
            "eps_ytd": _ytd(sid, seq, "eps"),
            "eps_yoy": _profit_growth(_ytd(sid, seq, "eps"), _ytd(sid, seq - 4, "eps")),
        })

    return pd.DataFrame(rows, columns=_FUNDAMENTALS_COLUMNS)


def get_fundamentals_snapshot(as_of: str) -> pd.DataFrame:
    """每檔股票「最新一季已可見」的季報基本面快照，供 index.html 個股 modal 使用。

    as_of: 'YYYY-MM-DD'，應傳 daily_prices 的最新交易日（見 build_fundamentals_snapshot）。

    ⚠️ sector_stocks 是 4,762 筆 / 1,039 檔——**一檔股票會屬於多個族群**，直接 join
    會把結果放大約 4.6 倍，所以這裡先 SELECT DISTINCT 收成 universe 再 join。
    """
    as_of_date = as_of if isinstance(as_of, date) else \
        datetime.strptime(str(as_of)[:10], "%Y-%m-%d").date()
    # 只需回看兩年：YoY 要去年同季，Q1 的 QoQ 要去年 Q4(而它的單季又要去年 Q3 累計)。
    min_year = as_of_date.year - 2
    metric_list = ", ".join(f"'{m}'" for m in _FUNDAMENTALS_METRICS)

    con = get_conn()
    facts = con.execute(f"""
        WITH universe AS (SELECT DISTINCT stock_id FROM sector_stocks)
        SELECT f.stock_id, f.fiscal_year, f.quarter, f.metric_key, f.value
        FROM financial_facts f
        JOIN universe u ON u.stock_id = f.stock_id
        WHERE f.statement_type = 'income'
          AND f.is_ytd
          AND f.metric_key IN ({metric_list})
          AND f.fiscal_year >= ?
    """, [min_year]).df()
    con.close()
    return build_fundamentals_snapshot(facts, as_of_date)
