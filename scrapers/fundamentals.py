"""TWSE／TPEx 官方基本面 OpenAPI。

只負責最新一期月營收、綜合損益表與資產負債表；歷史 XBRL 回補是獨立流程。
上市與上櫃欄位名稱不同，所有資料先在此正規化後才可寫入 DuckDB。
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

import duckdb
import pandas as pd
import requests

logger = logging.getLogger(__name__)

_TWSE_BASE = "https://openapi.twse.com.tw/v1/opendata"
_TPEX_BASE = "https://www.tpex.org.tw/openapi/v1"
_MONTHLY_URLS = {
    "TWSE": f"{_TWSE_BASE}/t187ap05_L",
    "TPEx": f"{_TPEX_BASE}/mopsfin_t187ap05_O",
}
_INDUSTRY_SCHEMAS = ("basi", "bd", "ci", "fh", "ins", "mim")
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/125 Safari/537.36"
    ),
    "Accept": "application/json",
}
_DB_PATH = "data/screener.db"

_IDENTIFIER_FIELDS = {
    "出表日期", "Date", "年度", "Year", "季別", "Season",
    "公司代號", "SecuritiesCompanyCode", "公司名稱", "CompanyName",
}

_INCOME_METRICS = {
    "營業收入": "revenue",
    "收入": "revenue",
    "收益": "revenue",
    "營業成本": "cost_of_revenue",
    "營業毛利（毛損）": "gross_profit_before_adjustment",
    "營業毛利（毛損）淨額": "gross_profit",
    "營業費用": "operating_expenses",
    "營業利益（損失）": "operating_income",
    "營業外收入及支出": "nonoperating_income",
    "稅前淨利（淨損）": "pretax_income",
    "繼續營業單位稅前淨利（淨損）": "pretax_income",
    "繼續營業單位稅前純益（純損）": "pretax_income",
    "所得稅費用（利益）": "income_tax",
    "本期淨利（淨損）": "net_income",
    "淨利（淨損）歸屬於母公司業主": "net_income_parent",
    "淨利（損）歸屬於母公司業主": "net_income_parent",
    "基本每股盈餘（元）": "eps",
    "基本每股盈餘": "eps",
}

_BALANCE_METRICS = {
    "流動資產": "current_assets",
    "非流動資產": "noncurrent_assets",
    "資產總計": "total_assets",
    "資產總額": "total_assets",
    "流動負債": "current_liabilities",
    "非流動負債": "noncurrent_liabilities",
    "負債總計": "total_liabilities",
    "負債總額": "total_liabilities",
    "股本": "share_capital",
    "資本公積": "capital_surplus",
    "保留盈餘": "retained_earnings",
    "其他權益": "other_equity",
    "庫藏股票": "treasury_stock",
    "歸屬於母公司業主之權益合計": "equity_parent",
    "非控制權益": "noncontrolling_interests",
    "權益總計": "total_equity",
    "權益總額": "total_equity",
    "每股參考淨值": "book_value_per_share",
}


class FundamentalDataError(RuntimeError):
    """官方基本面回應無法安全使用。"""


def _pick(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


# 官方 OpenAPI 對「本期無資料」會回一列全空白，而不是空陣列。只有日期欄有值的列
# 才算佔位——判斷刻意跟欄位名稱無關（TPEx 各 schema 命名不一致：ci 用 Year/Season/
# SecuritiesCompanyCode，bd 卻用 年度/季別/公司代號 混 CompanyName），只看「除了日期
# 之外還有沒有任何一格有值」，這樣新增 schema 也不會漏。
_DATE_FIELDS = ("Date", "出表日期", "資料年月")


def _row_is_placeholder(row: dict[str, Any]) -> bool:
    return not any(
        _clean_text(value) is not None
        for name, value in row.items()
        if name not in _DATE_FIELDS
    )


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text in ("", "-", "--", "－", "N/A", "null") else text


def _to_number(value: Any) -> float | None:
    text = _clean_text(value)
    if text is None:
        return None
    text = text.replace(",", "").replace("－", "-").replace("(", "-").replace(")", "")
    try:
        number = Decimal(text)
        return float(number) if number.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    number = _to_number(value)
    return int(number) if number is not None else None


def _roc_year(value: Any) -> int:
    text = _clean_text(value)
    if text is None or not text.isdigit():
        raise FundamentalDataError(f"無法解析民國年度：{value!r}")
    year = int(text)
    return year + 1911 if year < 1911 else year


def _roc_date(value: Any) -> date:
    text = (_clean_text(value) or "").replace("/", "").replace("-", "")
    if len(text) == 7 and text.isdigit():
        return date(int(text[:3]) + 1911, int(text[3:5]), int(text[5:7]))
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    raise FundamentalDataError(f"無法解析出表日期：{value!r}")


def _roc_month(value: Any) -> date:
    text = (_clean_text(value) or "").replace("/", "").replace("-", "")
    if len(text) == 5 and text.isdigit():
        return date(int(text[:3]) + 1911, int(text[3:5]), 1)
    if len(text) == 6 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), 1)
    raise FundamentalDataError(f"無法解析資料年月：{value!r}")


def _period_end(year: int, quarter: int) -> date:
    if quarter not in (1, 2, 3, 4):
        raise FundamentalDataError(f"季別必須為 1~4：{quarter!r}")
    return date(year, quarter * 3, (31, 30, 30, 31)[quarter - 1])


# 一次更新要連打 12 個端點（損益表/資產負債表 × 6 個產業 schema），TPEx 對這種
# 連續請求會偶發性斷線（實測 SSLEOFError: UNEXPECTED_EOF_WHILE_READING）。
# 退避重試 + 端點之間留間隔，避免整支指令因為一次連線抖動就前功盡棄——
# TWSE 那圈已經寫進 DB 的資料會留著，但 TPEx 整批會全部沒進去。
_FETCH_RETRY_DELAYS = (2, 5, 10)
_FETCH_GAP_SECONDS = 0.6


def _fetch_json(url: str, timeout: int = 30) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    for attempt, delay in enumerate((0, *_FETCH_RETRY_DELAYS)):
        if delay:
            time.sleep(delay)
        try:
            response = requests.get(url, headers=_HEADERS, timeout=timeout)
            response.raise_for_status()
            break
        except requests.RequestException as exc:
            # 只對連線層錯誤重試。格式錯誤（非 JSON、擋頁）重試也不會變好，
            # 而且會把「官方改版」這種需要人介入的問題拖成慢速失敗。
            last_error = exc
            logger.warning("官方基本面端點第 %d 次請求失敗，%s：%s",
                           attempt + 1, url, str(exc)[:120])
    else:
        raise FundamentalDataError(f"官方基本面端點連線失敗（已重試 {len(_FETCH_RETRY_DELAYS)} 次）：{url}") from last_error
    try:
        payload = response.json()
    except ValueError as exc:
        raise FundamentalDataError(f"官方基本面端點回傳非 JSON：{url}") from exc
    if not isinstance(payload, list):
        raise FundamentalDataError(f"官方基本面端點格式錯誤（預期 list）：{url}")
    if any(not isinstance(row, dict) for row in payload):
        raise FundamentalDataError(f"官方基本面端點疑似回傳擋頁或錯誤文字：{url}")
    return payload


def normalize_monthly_revenue(
    rows: Iterable[dict[str, Any]], exchange: str, fetched_at: datetime | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """把 TWSE／TPEx 月營收統一成 monthly_revenue schema。"""
    if exchange not in _MONTHLY_URLS:
        raise ValueError(f"不支援的市場：{exchange}")
    fetched_at = fetched_at or datetime.now()
    source = source or ("twse_openapi" if exchange == "TWSE" else "tpex_openapi")
    result: list[dict[str, Any]] = []
    for row in rows:
        stock_id = _clean_text(_pick(row, "公司代號", "SecuritiesCompanyCode"))
        stock_name = _clean_text(_pick(row, "公司名稱", "CompanyName"))
        if not stock_id and not stock_name and _row_is_placeholder(row):
            # 同財報：官方用一列全空白表示「本期無資料」。月營收目前實測沒有出現過，
            # 但兩支端點同一套慣例，先一起擋住比之後再炸一次好。
            continue
        if not stock_id or not stock_name:
            raise FundamentalDataError(f"月營收缺少公司識別欄位：{row!r}")
        revenue = _to_int(_pick(row, "營業收入-當月營收", "CurrentMonthRevenue"))
        if revenue is None:
            raise FundamentalDataError(f"月營收缺少當月營收：{stock_id}")
        raw_report_date = _pick(row, "出表日期", "Date")
        result.append({
            "stock_id": stock_id,
            "stock_name": stock_name,
            "exchange": exchange,
            "industry": _clean_text(_pick(row, "產業別", "Industry")),
            "revenue_month": _roc_month(_pick(row, "資料年月", "RevenueMonth")),
            "revenue": revenue,
            "previous_month_revenue": _to_int(_pick(row, "營業收入-上月營收", "PreviousMonthRevenue")),
            "previous_year_revenue": _to_int(_pick(row, "營業收入-去年當月營收", "PreviousYearRevenue")),
            "reported_mom_pct": _to_number(_pick(row, "營業收入-上月比較增減(%)", "MoM")),
            "reported_yoy_pct": _to_number(_pick(row, "營業收入-去年同月增減(%)", "YoY")),
            "ytd_revenue": _to_int(_pick(row, "累計營業收入-當月累計營收", "YTDRevenue")),
            "previous_ytd_revenue": _to_int(_pick(row, "累計營業收入-去年累計營收", "PreviousYTDRevenue")),
            "reported_ytd_yoy_pct": _to_number(_pick(row, "累計營業收入-前期比較增減(%)", "YTDYoY")),
            "note": _clean_text(_pick(row, "備註", "Note")),
            "report_date": _roc_date(raw_report_date) if _clean_text(raw_report_date) else None,
            "first_seen_at": fetched_at,
            "fetched_at": fetched_at,
            "source": source,
        })
    return _dedupe_rows(result, ("stock_id", "revenue_month"), "月營收")


def _metric_key(raw_name: str, statement_type: str) -> str:
    mapping = _INCOME_METRICS if statement_type == "income" else _BALANCE_METRICS
    return mapping.get(raw_name, f"raw:{raw_name}")


def _metric_unit(raw_name: str, metric_key: str) -> str:
    if metric_key in ("eps", "book_value_per_share"):
        return "TWD/share"
    if "股數" in raw_name:
        return "shares"
    return "TWD_thousand"


def normalize_financial_statement(
    rows: Iterable[dict[str, Any]], exchange: str, statement_type: str,
    industry_schema: str, fetched_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """把一個官方財報 endpoint 展開成長表 facts。"""
    if exchange not in _MONTHLY_URLS:
        raise ValueError(f"不支援的市場：{exchange}")
    if statement_type not in ("income", "balance"):
        raise ValueError(f"不支援的報表：{statement_type}")
    if industry_schema not in _INDUSTRY_SCHEMAS:
        raise ValueError(f"不支援的產業 schema：{industry_schema}")
    fetched_at = fetched_at or datetime.now()
    source = "twse_openapi" if exchange == "TWSE" else "tpex_openapi"
    facts: list[dict[str, Any]] = []
    for row in rows:
        stock_id = _clean_text(_pick(row, "公司代號", "SecuritiesCompanyCode"))
        stock_name = _clean_text(_pick(row, "公司名稱", "CompanyName"))
        if not stock_id and not stock_name and _row_is_placeholder(row):
            # 官方對「該市場此產業別本期沒有任何公司」會回**一列全空白**的佔位列，
            # 而不是空陣列。實測上櫃的 basi/fh/ins/mim 四個 schema（損益表與資產負債表
            # 各一列，共 8 個端點）都是這樣——上櫃沒有金融／金控／保險／異業公司。
            # 這不是錯誤，跳過即可。⚠️ 條件刻意收得很緊：必須「識別欄位全空」**且**
            # 除日期外沒有任何欄位有值才算佔位；只要有一格數字，就仍然照舊拋錯，
            # 否則真的資料異常會被靜靜吞掉。
            continue
        year = _roc_year(_pick(row, "年度", "Year"))
        quarter_number = _to_int(_pick(row, "季別", "Season"))
        if not stock_id or not stock_name or quarter_number is None:
            raise FundamentalDataError(f"財報缺少必要識別欄位：{row!r}")
        report_date = _roc_date(_pick(row, "出表日期", "Date"))
        for raw_name, raw_value in row.items():
            if raw_name in _IDENTIFIER_FIELDS:
                continue
            value = _to_number(raw_value)
            if value is None:
                continue
            metric_key = _metric_key(raw_name, statement_type)
            facts.append({
                "stock_id": stock_id,
                "stock_name": stock_name,
                "exchange": exchange,
                "period_end": _period_end(year, quarter_number),
                "fiscal_year": year,
                "quarter": quarter_number,
                "statement_type": statement_type,
                "industry_schema": industry_schema,
                "metric_key": metric_key,
                "raw_name": raw_name,
                "value": value,
                "unit": _metric_unit(raw_name, metric_key),
                "is_ytd": statement_type == "income",
                "report_date": report_date,
                "first_seen_at": fetched_at,
                "fetched_at": fetched_at,
                "source": source,
            })
    return _dedupe_rows(
        facts,
        ("stock_id", "period_end", "statement_type", "metric_key", "industry_schema"),
        f"{exchange} {statement_type}/{industry_schema}",
    )


def _dedupe_rows(rows: list[dict[str, Any]], key_names: tuple[str, ...], label: str) -> list[dict[str, Any]]:
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(row[name] for name in key_names)
        previous = unique.get(key)
        if previous is not None and previous != row:
            comparable = {k: v for k, v in row.items() if k not in ("first_seen_at", "fetched_at")}
            previous_comparable = {
                k: v for k, v in previous.items() if k not in ("first_seen_at", "fetched_at")
            }
            if previous_comparable != comparable:
                raise FundamentalDataError(f"{label} 出現衝突的重複主鍵：{key}")
        unique[key] = row
    return list(unique.values())


def fetch_monthly_revenue(exchange: str) -> list[dict[str, Any]]:
    return normalize_monthly_revenue(_fetch_json(_MONTHLY_URLS[exchange]), exchange)


def _statement_url(exchange: str, statement_type: str, industry_schema: str) -> str:
    number = "06" if statement_type == "income" else "07"
    if exchange == "TWSE":
        return f"{_TWSE_BASE}/t187ap{number}_L_{industry_schema}"
    if exchange == "TPEx":
        return f"{_TPEX_BASE}/mopsfin_t187ap{number}_O_{industry_schema}"
    raise ValueError(f"不支援的市場：{exchange}")


def fetch_financial_facts(exchange: str) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    fetched_at = datetime.now()
    first = True
    for statement_type in ("income", "balance"):
        for industry_schema in _INDUSTRY_SCHEMAS:
            if not first:
                time.sleep(_FETCH_GAP_SECONDS)   # 不連續轟炸官方端點
            first = False
            url = _statement_url(exchange, statement_type, industry_schema)
            rows = _fetch_json(url)
            parsed = normalize_financial_statement(
                rows, exchange, statement_type, industry_schema, fetched_at=fetched_at,
            )
            # 印正規化後的公司數，不印原始列數——原始列數會把「本期無資料」的空白
            # 佔位列算成 1 家公司（先前的 log「TPEx income/basi：1 公司」就是這樣來的，
            # 看起來像有資料，其實整列是空的）。
            logger.info("官方基本面 %s %s/%s：%d 公司", exchange, statement_type,
                        industry_schema, len({f["stock_id"] for f in parsed}))
            facts.extend(parsed)
    return _dedupe_rows(
        facts,
        ("stock_id", "period_end", "statement_type", "metric_key", "industry_schema"),
        f"{exchange} 財報",
    )


def _preserve_first_seen(con, table: str, rows: list[dict[str, Any]], key_names: tuple[str, ...]) -> None:
    if not rows:
        return
    key_sql = ", ".join(key_names)
    existing = con.execute(f"SELECT {key_sql}, first_seen_at FROM {table}").fetchall()
    existing_map = {tuple(row[:-1]): row[-1] for row in existing}
    for row in rows:
        key = tuple(row[name] for name in key_names)
        if key in existing_map:
            row["first_seen_at"] = existing_map[key]


def _upsert_monthly_revenue(con, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    rows = _dedupe_rows(rows, ("stock_id", "revenue_month"), "月營收")
    _preserve_first_seen(con, "monthly_revenue", rows, ("stock_id", "revenue_month"))
    existing_report_dates = {
        (row[0], row[1]): row[2]
        for row in con.execute(
            "SELECT stock_id, revenue_month, report_date FROM monthly_revenue WHERE report_date IS NOT NULL"
        ).fetchall()
    }
    for row in rows:
        key = (row["stock_id"], row["revenue_month"])
        if row.get("report_date") is None and key in existing_report_dates:
            row["report_date"] = existing_report_dates[key]
    con.register("monthly_revenue_df", pd.DataFrame(rows))
    con.execute("""
        DELETE FROM monthly_revenue
        WHERE (stock_id, revenue_month) IN (
            SELECT stock_id, revenue_month FROM monthly_revenue_df
        )
    """)
    con.execute("""
        INSERT INTO monthly_revenue
        SELECT stock_id, stock_name, exchange, industry, revenue_month,
               revenue, previous_month_revenue, previous_year_revenue,
               reported_mom_pct, reported_yoy_pct, ytd_revenue,
               previous_ytd_revenue, reported_ytd_yoy_pct, note,
               report_date, first_seen_at, fetched_at, source
        FROM monthly_revenue_df
    """)
    return len(rows)


def _upsert_financial_facts(con, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    keys = ("stock_id", "period_end", "statement_type", "metric_key", "industry_schema")
    rows = _dedupe_rows(rows, keys, "財報 fact")
    _preserve_first_seen(con, "financial_facts", rows, keys)
    con.register("financial_facts_df", pd.DataFrame(rows))
    con.execute("""
        DELETE FROM financial_facts
        WHERE (stock_id, period_end, statement_type, metric_key, industry_schema) IN (
            SELECT stock_id, period_end, statement_type, metric_key, industry_schema
            FROM financial_facts_df
        )
    """)
    con.execute("""
        INSERT INTO financial_facts
        SELECT stock_id, stock_name, exchange, period_end, fiscal_year, quarter,
               statement_type, industry_schema, metric_key, raw_name, value,
               unit, is_ytd, report_date, first_seen_at, fetched_at, source
        FROM financial_facts_df
    """)
    return len(rows)


def _transactional_upsert(
    monthly_rows: list[dict[str, Any]], fact_rows: list[dict[str, Any]], db_path: str,
) -> tuple[int, int]:
    con = duckdb.connect(db_path)
    transaction_started = False
    try:
        con.execute("BEGIN")
        transaction_started = True
        monthly_count = _upsert_monthly_revenue(con, monthly_rows)
        fact_count = _upsert_financial_facts(con, fact_rows)
        con.execute("COMMIT")
        transaction_started = False
        return monthly_count, fact_count
    except Exception:
        if transaction_started:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def save_monthly_revenue(rows: list[dict[str, Any]], db_path: str = _DB_PATH) -> int:
    """單獨 upsert 月營收；CLI 更新兩張表時應改用 save_official_fundamentals。"""
    return _transactional_upsert(rows, [], db_path)[0]


def save_financial_facts(rows: list[dict[str, Any]], db_path: str = _DB_PATH) -> int:
    """單獨 upsert 財報 facts；CLI 更新兩張表時應改用 save_official_fundamentals。"""
    return _transactional_upsert([], rows, db_path)[1]


def save_official_fundamentals(
    monthly_rows: list[dict[str, Any]], fact_rows: list[dict[str, Any]], db_path: str = _DB_PATH,
) -> tuple[int, int]:
    """同一市場的月營收與財報在同一 transaction 原子寫入。"""
    return _transactional_upsert(monthly_rows, fact_rows, db_path)
