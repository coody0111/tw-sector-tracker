"""MOPS 官方上市／上櫃月營收整批歷史頁。

官方 `nas/t21` 靜態頁是 Big5、按產業分段的 11 欄 HTML。這個模組只負責
歷史回填；最新一期仍由 `scrapers.fundamentals` 的 TWSE／TPEx OpenAPI 取得。
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import requests
from bs4 import BeautifulSoup

from scrapers.fundamentals import (
    _upsert_monthly_revenue,
    fetch_monthly_revenue,
    normalize_monthly_revenue,
    save_monthly_revenue,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://mopsov.twse.com.tw/nas/t21"
_DB_PATH = "data/screener.db"
_CACHE_ROOT = Path("data/fundamentals/monthly_revenue")
_MARKET_PATH = {"TWSE": "sii", "TPEx": "otc"}
_MARKET_TITLE = {"TWSE": "上市公司", "TPEx": "上櫃公司"}
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/125 Safari/537.36"
    ),
    "Accept": "text/html,*/*;q=0.8",
}
_STOCK_ID_RE = re.compile(r"\d{4,6}")


class MopsMonthlyRevenueError(RuntimeError):
    """MOPS 月營收歷史頁無法安全使用。"""


@dataclass(frozen=True)
class DownloadedMonthlyPage:
    page_sha256: str
    exchange: str
    revenue_month: date
    source_url: str
    path: Path
    byte_size: int
    retrieved_at: datetime
    rows: list[dict[str, Any]]


def _month_start(year: int, month: int) -> date:
    if year < 1912 or month not in range(1, 13):
        raise ValueError(f"年月不合法：{year}-{month}")
    return date(year, month, 1)


def _month_urls(exchange: str, year: int, month: int) -> list[str]:
    if exchange not in _MARKET_PATH:
        raise ValueError(f"不支援的市場：{exchange}")
    roc_year = year - 1911
    market_path = _MARKET_PATH[exchange]
    month_tokens = [str(month), f"{month:02d}"]
    return list(dict.fromkeys(
        f"{_BASE_URL}/{market_path}/t21sc03_{roc_year}_{token}_0.html"
        for token in month_tokens
    ))


def _cell_text(cell) -> str:
    return re.sub(r"\s+", " ", cell.get_text(" ", strip=True).replace("\xa0", " ")).strip()


def _get_with_retries(session, url: str, timeout: int, retries: int = 3):
    last_error: requests.RequestException | None = None
    for attempt in range(retries):
        try:
            response = session.get(url, headers=_HEADERS, timeout=timeout)
            if response.status_code < 500 or attempt == retries - 1:
                return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt == retries - 1:
                raise
        time.sleep(2 ** attempt)
    if last_error is not None:
        raise last_error
    raise MopsMonthlyRevenueError(f"MOPS 月營收請求沒有回應：{url}")


def _industry_name(row_text: str) -> str | None:
    match = re.search(r"產業別\s*[:：]\s*([^|]+)", row_text)
    if not match:
        return None
    industry = re.split(r"單位\s*[:：]", match.group(1), maxsplit=1)[0].strip(" ：:|- ")
    return industry or None


def parse_monthly_revenue_html(
    content: bytes,
    exchange: str,
    year: int,
    month: int,
    fetched_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """解析 Big5 官方頁；200 擋頁、錯誤年月與空表都會被拒絕。"""
    if exchange not in _MARKET_PATH:
        raise ValueError(f"不支援的市場：{exchange}")
    try:
        # 用 cp950（big5 的相容超集）而非嚴格 big5：實測 TWSE 2025-06 那頁在股票代號
        # 2353 公司名遇到 Big5 擴充字元（0xf9 開頭）就整月直接 UnicodeDecodeError，
        # 不是舊資料才有的邊界案例（2026-09-02 debug 驗證抓到）。cp950/big5hkscs 都
        # 驗證過能完整解碼同一頁，且對本來就是標準 big5 的頁面不影響解析結果。
        page = content.decode("cp950")
    except UnicodeDecodeError as exc:
        raise MopsMonthlyRevenueError(f"MOPS 月營收頁不是有效 Big5：{exchange} {year}-{month:02d}") from exc
    compact_page = re.sub(r"\s+", "", BeautifulSoup(page, "html.parser").get_text())
    expected_titles = {
        f"{_MARKET_TITLE[exchange]}{year - 1911}年{month}月",
        f"{_MARKET_TITLE[exchange]}{year - 1911}年{month:02d}月",
    }
    if not any(title in compact_page for title in expected_titles):
        raise MopsMonthlyRevenueError(
            f"MOPS 月營收頁標題不符（預期 {sorted(expected_titles)}）：{exchange} {year}-{month:02d}"
        )

    soup = BeautifulSoup(page, "html.parser")
    industry: str | None = None
    header_seen = False
    raw_rows: list[dict[str, Any]] = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        if not cells:
            continue
        texts = [_cell_text(cell) for cell in cells]
        joined = "|".join(texts)
        found_industry = _industry_name(joined)
        if found_industry:
            industry = found_industry
        # 表頭列不能綁死儲存格數／精確字串比對：實測真實 TWSE 2025-06 頁面表頭列只有
        # 10 格（不是資料列的11格），且第一格文字是「公司 代號」（中間多一個空格），跟
        # 原本要求的 len(texts)>=11 and texts[0]=="公司代號" 兩個條件都對不上，導致
        # header_seen 永遠 False、990列合法資料全被判定失敗（2026-09-02 debug 複驗
        # Big5 修復時才第一次真的跑到這一步、才暴露出來的獨立bug）。改成只看去空白後的
        # 第一格文字，不再要求儲存格數——資料列已經有 _STOCK_ID_RE 獨立驗證，不會誤判。
        if texts[0].replace(" ", "") == "公司代號":
            header_seen = True
            continue
        if len(texts) != 11 or _STOCK_ID_RE.fullmatch(texts[0]) is None:
            continue
        if not industry:
            raise MopsMonthlyRevenueError(f"公司列缺少產業別：{exchange} {year}-{month:02d}/{texts[0]}")
        raw_rows.append({
            "資料年月": f"{year - 1911:03d}{month:02d}",
            "產業別": industry,
            "公司代號": texts[0],
            "公司名稱": texts[1],
            "營業收入-當月營收": texts[2],
            "營業收入-上月營收": texts[3],
            "營業收入-去年當月營收": texts[4],
            "營業收入-上月比較增減(%)": texts[5],
            "營業收入-去年同月增減(%)": texts[6],
            "累計營業收入-當月累計營收": texts[7],
            "累計營業收入-去年累計營收": texts[8],
            "累計營業收入-前期比較增減(%)": texts[9],
            "備註": texts[10],
        })
    if not header_seen or not raw_rows:
        raise MopsMonthlyRevenueError(f"MOPS 月營收頁缺少 11 欄公司資料：{exchange} {year}-{month:02d}")
    return normalize_monthly_revenue(
        raw_rows,
        exchange,
        fetched_at=fetched_at or datetime.now(),
        source="mops_monthly_history",
    )


def fetch_monthly_revenue_page(
    exchange: str,
    year: int,
    month: int,
    cache_root: Path | str = _CACHE_ROOT,
    timeout: int = 60,
    session=requests,
    retrieved_at: datetime | None = None,
) -> DownloadedMonthlyPage:
    """依序嘗試月份不補零／補零 URL，以內容而非 status 單獨判定成功。"""
    revenue_month = _month_start(year, month)
    retrieved_at = retrieved_at or datetime.now()
    failures: list[str] = []
    for url in _month_urls(exchange, year, month):
        try:
            response = _get_with_retries(session, url, timeout)
            if response.status_code == 404:
                failures.append(f"{url}: HTTP 404")
                continue
            response.raise_for_status()
            rows = parse_monthly_revenue_html(
                response.content, exchange, year, month, fetched_at=retrieved_at,
            )
        except (requests.RequestException, MopsMonthlyRevenueError) as exc:
            failures.append(f"{url}: {exc}")
            continue
        content = response.content
        digest = hashlib.sha256(content).hexdigest()
        target_dir = Path(cache_root) / exchange / str(year) / f"{month:02d}"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{digest}.html"
        if not target.exists():
            temp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(dir=target_dir, delete=False, suffix=".tmp") as handle:
                    handle.write(content)
                    temp_path = Path(handle.name)
                os.replace(temp_path, target)
            finally:
                if temp_path is not None and temp_path.exists():
                    temp_path.unlink()
        return DownloadedMonthlyPage(
            page_sha256=digest,
            exchange=exchange,
            revenue_month=revenue_month,
            source_url=url,
            path=target,
            byte_size=len(content),
            retrieved_at=retrieved_at,
            rows=rows,
        )
    raise MopsMonthlyRevenueError(
        f"MOPS 月營收頁所有候選網址都失敗：{exchange} {year}-{month:02d}\n" + "\n".join(failures)
    )


def save_monthly_revenue_page(
    page: DownloadedMonthlyPage, db_path: str = _DB_PATH,
) -> dict[str, int]:
    """同一 transaction 保存 page/version 並更新 monthly_revenue current projection。"""
    con = duckdb.connect(db_path)
    transaction_started = False
    counts = {"pages": 0, "versions": 0, "current_rows": 0}
    try:
        existing = con.execute(
            "SELECT 1 FROM monthly_revenue_pages WHERE page_sha256 = ?", [page.page_sha256],
        ).fetchone()
        if existing:
            con.execute("BEGIN")
            transaction_started = True
            con.execute("""
                UPDATE monthly_revenue_pages
                SET retrieved_at = ?, source_url = ?, local_path = ?
                WHERE page_sha256 = ?
            """, [page.retrieved_at, page.source_url, str(page.path), page.page_sha256])
            counts["current_rows"] = _upsert_monthly_revenue(con, page.rows)
            con.execute("COMMIT")
            transaction_started = False
            return counts
        con.execute("BEGIN")
        transaction_started = True
        con.execute("""
            INSERT INTO monthly_revenue_pages (
                page_sha256, exchange, revenue_month, source_url, local_path,
                byte_size, first_seen_at, retrieved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            page.page_sha256, page.exchange, page.revenue_month, page.source_url,
            str(page.path), page.byte_size, page.retrieved_at, page.retrieved_at,
        ])
        version_columns = [
            "page_sha256", "stock_id", "stock_name", "exchange", "industry", "revenue_month",
            "revenue", "previous_month_revenue", "previous_year_revenue", "reported_mom_pct",
            "reported_yoy_pct", "ytd_revenue", "previous_ytd_revenue", "reported_ytd_yoy_pct",
            "note", "report_date", "first_seen_at", "source",
        ]
        version_rows = [dict(row, page_sha256=page.page_sha256) for row in page.rows]
        frame = pd.DataFrame([
            {column: row.get(column) for column in version_columns} for row in version_rows
        ])
        con.register("monthly_revenue_versions_df", frame)
        con.execute(f"""
            INSERT INTO monthly_revenue_versions ({', '.join(version_columns)})
            SELECT {', '.join(version_columns)} FROM monthly_revenue_versions_df
        """)
        con.unregister("monthly_revenue_versions_df")
        counts["pages"] = 1
        counts["versions"] = len(page.rows)
        counts["current_rows"] = _upsert_monthly_revenue(con, page.rows)
        con.execute("COMMIT")
        transaction_started = False
        return counts
    except Exception:
        if transaction_started:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def _iter_months(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)


def backfill_mops_monthly_revenue(
    start_year: int = 2013,
    db_path: str = _DB_PATH,
    cache_root: Path | str = _CACHE_ROOT,
    end_months: dict[str, date] | None = None,
    delay_seconds: float = 0.3,
    session=requests,
) -> dict[str, int]:
    """回填兩市場月營收；預設由各市場最新官方 OpenAPI 決定結束月份。"""
    if start_year < 2013:
        raise ValueError("Phase 2B 預設只回填 2013 年起月營收")
    latest_openapi_rows: dict[str, list[dict[str, Any]]] = {}
    if end_months is None:
        end_months = {}
        for exchange in ("TWSE", "TPEx"):
            rows = fetch_monthly_revenue(exchange)
            if not rows:
                raise MopsMonthlyRevenueError(f"{exchange} 最新官方月營收 OpenAPI 是空資料")
            latest_openapi_rows[exchange] = rows
            end_months[exchange] = max(row["revenue_month"] for row in rows)
    totals = {"pages": 0, "versions": 0, "current_rows": 0}
    for exchange in ("TWSE", "TPEx"):
        end = end_months.get(exchange)
        if end is None:
            raise ValueError(f"缺少 {exchange} 回填結束月份")
        start = date(start_year, 1, 1)
        if end < start:
            raise ValueError(f"{exchange} 結束月份 {end} 早於回填起點 {start}")
        months = list(_iter_months(start, end))
        for index, revenue_month in enumerate(months):
            logger.info("MOPS 月營收回填 %s %s", exchange, revenue_month.strftime("%Y-%m"))
            page = fetch_monthly_revenue_page(
                exchange=exchange,
                year=revenue_month.year,
                month=revenue_month.month,
                cache_root=cache_root,
                session=session,
            )
            counts = save_monthly_revenue_page(page, db_path=db_path)
            for name, count in counts.items():
                totals[name] += count
            if delay_seconds > 0 and index < len(months) - 1:
                time.sleep(delay_seconds)
    # 歷史靜態頁沒有 report_date；最後讓已抓到的最新 OpenAPI row 回寫，保留官方出表日期。
    for rows in latest_openapi_rows.values():
        totals["current_rows"] += save_monthly_revenue(rows, db_path=db_path)
    return totals
