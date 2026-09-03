"""MOPS 官方 IFRS XBRL 歷史財報回填。

資料來源只使用 MOPS 官方整批下載頁。原始 ZIP、instance 與 facts 以內容雜湊
append-only 保存；`retrieved_at` 只是本系統抓取時間，不冒充公司申報日。
"""
from __future__ import annotations

import hashlib
import html
import io
import json
import logging
import os
import re
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import duckdb
import pandas as pd
import requests
from bs4 import BeautifulSoup
from lxml import etree

logger = logging.getLogger(__name__)

MOPS_BULK_LIST_URL = "https://mopsov.twse.com.tw/mops/web/t203sb02"
_MOPS_BASE_URL = "https://mopsov.twse.com.tw"
_DB_PATH = "data/screener.db"
_CACHE_ROOT = Path("data/fundamentals/xbrl")
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/125 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/zip,*/*;q=0.8",
    "Accept-Encoding": "identity",
    "Referer": MOPS_BULK_LIST_URL,
}
_XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"
_IFRS_ARCHIVE_RE = re.compile(r"^tifrs-(\d{4})Q([1-4])\.zip$", re.IGNORECASE)
_DOWNLOAD_RE = re.compile(
    r"(?:https?://[^\"'<>\s]+)?/?server-java/FileDownLoad\?[^\"'<>\s]+",
    re.IGNORECASE,
)
# recover 模式的健全性檢查用：直接數原始 bytes 裡的 contextRef，當作「應該有幾個 fact」的基準
_CONTEXT_REF_RE = re.compile(rb"contextRef\s*=", re.IGNORECASE)
_STOCK_ID_RE = re.compile(r"(?<!\d)(\d{4,6})(?!\d)")
_DOWNLOAD_RETRY_DELAYS = (5.0, 20.0, 60.0)
# 串流下載的上限。最大的官方 ZIP 約 124 MB，20 分鐘約當要求平均 100 KB/s；
# 低於這個速率的連線在實測中最後都是給出截斷檔（見 _read_streamed_body）。
_DOWNLOAD_MAX_SECONDS = 1200.0
_DOWNLOAD_STALL_SECONDS = 120.0
_DOWNLOAD_CHUNK_BYTES = 1 << 20
_HTML4_PUBLIC_DOCTYPE_RE = re.compile(
    rb'(?i)(<!DOCTYPE\s+HTML\s+PUBLIC\s+"[^"]+")(\s*>)'
)


class MopsXbrlError(RuntimeError):
    """MOPS XBRL 資料無法安全解析或保存。"""


@dataclass(frozen=True)
class ArchiveLink:
    year: int
    quarter: int
    filename: str
    url: str

    @property
    def period_end(self) -> date:
        return _period_end(self.year, self.quarter)


@dataclass(frozen=True)
class DownloadedArchive:
    link: ArchiveLink
    sha256: str
    path: Path
    byte_size: int
    retrieved_at: datetime
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True)
class MetricDefinition:
    metric_key: str
    statement_type: str
    unit_kind: str
    alias_priority: int


@dataclass
class ParsedInstance:
    filing: dict[str, Any]
    facts: list[dict[str, Any]]
    canonical_facts: list[dict[str, Any]]


def _xml_parse_content(content: bytes, entry_path: str) -> etree._Element:
    """Parse XML/XHTML, tolerating MOPS' malformed HTML4 PUBLIC doctype."""
    # IE-saved inline filings sometimes omit the required system literal from
    # a PUBLIC doctype.  Normalize only that declaration; the original bytes
    # remain the source of filing_sha256 and raw-fact preservation.
    parse_content = _HTML4_PUBLIC_DOCTYPE_RE.sub(rb'\1 ""\2', content, count=1)
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False, huge_tree=True)
    try:
        return etree.fromstring(parse_content, parser=parser)
    except etree.XMLSyntaxError:
        if PurePosixPath(entry_path).suffix.lower() not in {".html", ".htm", ".xhtml"}:
            raise
        # Some IE-saved MOPS inline filings contain HTML-only constructs such
        # as unclosed META tags.  lxml's recovery mode keeps the XBRL
        # namespaces and facts, unlike the HTML parser, which discards them.
        recovery_parser = etree.XMLParser(
            resolve_entities=False, no_network=True, recover=True, huge_tree=True,
        )
        root = etree.fromstring(parse_content, parser=recovery_parser)
        # recover 模式會安靜地丟掉修不好的節點。全庫 34,318 份文件實測只有
        # 2021Q2 的 1519 觸發過（1,120 個 contextRef 全數保留、零丟失），但沒有
        # 紀錄就無從得知下次是不是同樣安全，所以把觸發檔案與 lxml 的實際錯誤
        # 一併寫進 log：錯誤若只落在 HTML 排版標籤（META/BR/SPAN）代表 XBRL
        # 內容未受影響，若出現 contextRef／facts 相關訊息就要人工複核。
        recovered_facts = sum(1 for element in root.iter() if _attribute(element, "contextRef"))
        source_refs = len(_CONTEXT_REF_RE.findall(parse_content))
        logger.warning(
            "MOPS XBRL %s 以 recover 模式解析：contextRef 原始 %d 個、解析後保留 %d 個%s；"
            "lxml 回報 %d 個錯誤",
            entry_path, source_refs, recovered_facts,
            "" if recovered_facts >= source_refs else f"（少 {source_refs - recovered_facts} 個，需人工複核）",
            len(recovery_parser.error_log),
        )
        for entry in list(recovery_parser.error_log)[:5]:
            logger.warning("  recover 錯誤 %s:%s %s", entry_path, entry.line, entry.message)
        return root


def _period_end(year: int, quarter: int) -> date:
    if quarter not in (1, 2, 3, 4):
        raise ValueError(f"quarter 必須為 1~4：{quarter}")
    return date(year, quarter * 3, (31, 30, 30, 31)[quarter - 1])


def _archive_link_from_url(raw_url: str) -> ArchiveLink | None:
    """只接受 MOPS FileDownLoad 中明確的 IFRS 季度 ZIP。"""
    decoded = html.unescape(unquote(raw_url.strip().strip("\"'")))
    if "FileDownLoad?" not in decoded:
        return None
    absolute = urljoin(_MOPS_BASE_URL, decoded.lstrip("./"))
    parsed = urlparse(absolute)
    if parsed.netloc.lower() != "mopsov.twse.com.tw":
        return None
    filename = parse_qs(parsed.query).get("fileName", [""])[0]
    match = _IFRS_ARCHIVE_RE.fullmatch(filename)
    if not match:
        return None
    return ArchiveLink(
        year=int(match.group(1)),
        quarter=int(match.group(2)),
        filename=filename,
        url=absolute,
    )


def parse_archive_links(page_html: str) -> list[ArchiveLink]:
    """解析官方整批下載頁；不自行拼出頁面尚未公布的季度。"""
    candidates: list[str] = []
    soup = BeautifulSoup(page_html, "html.parser")
    for tag in soup.find_all(href=True):
        candidates.append(str(tag["href"]))
    candidates.extend(_DOWNLOAD_RE.findall(html.unescape(page_html)))

    by_period: dict[tuple[int, int], ArchiveLink] = {}
    for candidate in candidates:
        link = _archive_link_from_url(candidate)
        if link is None:
            continue
        key = (link.year, link.quarter)
        previous = by_period.get(key)
        if previous is not None and previous.url != link.url:
            raise MopsXbrlError(f"MOPS 同一季度出現不同 IFRS 下載網址：{key}")
        by_period[key] = link
    return [by_period[key] for key in sorted(by_period)]


def discover_ifrs_archives(timeout: int = 30, session=requests) -> list[ArchiveLink]:
    response = session.get(MOPS_BULK_LIST_URL, headers=_HEADERS, timeout=timeout)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    links = parse_archive_links(response.text)
    if not links:
        raise MopsXbrlError("MOPS 整批下載頁沒有可辨識的 IFRS ZIP 連結")
    return links


def _validate_zip(content: bytes, filename: str) -> None:
    if not content.startswith(b"PK"):
        raise MopsXbrlError(f"MOPS 回應不是 ZIP：{filename}")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            bad_entry = archive.testzip()
    except zipfile.BadZipFile as exc:
        raise MopsXbrlError(f"MOPS ZIP 損壞：{filename}") from exc
    if bad_entry is not None:
        raise MopsXbrlError(f"MOPS ZIP entry CRC 錯誤：{filename}/{bad_entry}")


def _read_streamed_body(response: Any, filename: str) -> bytes:
    """分塊讀取回應本體，套用總時長與停滯上限，並比對 Content-Length。

    背景（2026-09-02 tifrs-2022Q2.zip）：官方伺服器會以極慢的速率持續吐資料，
    最後給出截斷的 ZIP。requests 的 `timeout` 只管「兩次 socket 讀取之間的間隔」，
    伺服器每 119 秒吐一點就永遠不會觸發，於是單次下載耗掉 3～8 小時，讀完才在
    `_validate_zip()` 發現是壞的——那一季前後花了 14 小時才成功。

    這裡改成串流讀取，讓失敗在分鐘級就浮現：
      * 總時長超過 _DOWNLOAD_MAX_SECONDS 就放棄（對最大的 124 MB 檔約當要求 100 KB/s）
      * 連續 _DOWNLOAD_STALL_SECONDS 沒有新資料就放棄
      * 官方有給 Content-Length 時，收完立刻比對，短傳直接判定失敗
    這三種都拋 MopsXbrlError，沿用既有的退避重試路徑。
    """
    header_length = str(response.headers.get("Content-Length", "")).strip()
    expected_bytes = int(header_length) if header_length.isdigit() else None

    chunks: list[bytes] = []
    total = 0
    started = last_progress = time.monotonic()
    for chunk in response.iter_content(chunk_size=_DOWNLOAD_CHUNK_BYTES):
        now = time.monotonic()
        if chunk:
            chunks.append(chunk)
            total += len(chunk)
            last_progress = now
        elif now - last_progress > _DOWNLOAD_STALL_SECONDS:
            raise MopsXbrlError(
                f"MOPS ZIP 下載停滯超過 {_DOWNLOAD_STALL_SECONDS:.0f} 秒："
                f"{filename}；已收 {total} bytes"
            )
        if now - started > _DOWNLOAD_MAX_SECONDS:
            raise MopsXbrlError(
                f"MOPS ZIP 下載超過 {_DOWNLOAD_MAX_SECONDS:.0f} 秒上限："
                f"{filename}；已收 {total} bytes"
                + (f" / 預期 {expected_bytes} bytes" if expected_bytes is not None else "")
            )

    content = b"".join(chunks)
    if expected_bytes is not None and len(content) != expected_bytes:
        raise MopsXbrlError(
            f"MOPS ZIP 短傳：{filename}；Content-Length={expected_bytes}、實收 {len(content)} bytes"
        )
    return content


def _download_validated_zip(
    link: ArchiveLink,
    timeout: int = 120,
    session=requests,
    retry_delays: tuple[float, ...] = _DOWNLOAD_RETRY_DELAYS,
) -> tuple[bytes, Any]:
    """下載並驗證 ZIP；短傳、擋頁與暫時性 HTTP 錯誤會退避重試。"""
    response = None
    content = b""
    for attempt in range(len(retry_delays) + 1):
        try:
            request_headers = dict(_HEADERS)
            if attempt > 0:
                request_headers.update({
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                    "Connection": "close",
                })
            response = session.get(
                link.url, headers=request_headers, timeout=timeout, stream=True,
            )
            response.raise_for_status()
            content = _read_streamed_body(response, link.filename)
            _validate_zip(content, link.filename)
            return content, response
        except (requests.exceptions.RequestException, MopsXbrlError) as exc:
            headers = getattr(response, "headers", {}) if response is not None else {}
            diagnostics = (
                f"收到 {len(content)} bytes、Content-Type={headers.get('Content-Type', 'unknown')}、"
                f"Content-Length={headers.get('Content-Length', 'unknown')}"
            )
            if attempt >= len(retry_delays):
                raise MopsXbrlError(
                    f"MOPS ZIP 下載驗證失敗（共 {attempt + 1} 次）："
                    f"{link.filename}；{diagnostics}；最後錯誤：{exc}"
                ) from exc
            delay = retry_delays[attempt]
            logger.warning(
                "MOPS XBRL %s 下載驗證失敗（第 %d/%d 次）：%s；%s；%.1f 秒後重試",
                link.filename, attempt + 1, len(retry_delays) + 1,
                exc, diagnostics, delay,
            )
            close = getattr(response, "close", None)
            if callable(close):
                close()
            time.sleep(delay)

    raise MopsXbrlError(f"MOPS ZIP 未取得有效回應：{link.filename}")  # pragma: no cover


def download_archive(
    link: ArchiveLink,
    cache_root: Path | str = _CACHE_ROOT,
    timeout: int = 120,
    session=requests,
    retrieved_at: datetime | None = None,
    retry_delays: tuple[float, ...] = _DOWNLOAD_RETRY_DELAYS,
) -> DownloadedArchive:
    """下載並版本化保存 ZIP；只有完整通過驗證的內容才會進 cache。"""
    content, response = _download_validated_zip(
        link, timeout=timeout, session=session, retry_delays=retry_delays,
    )
    digest = hashlib.sha256(content).hexdigest()
    target_dir = Path(cache_root) / str(link.year) / Path(link.filename).stem
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{digest}.zip"
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
    return DownloadedArchive(
        link=link,
        sha256=digest,
        path=target,
        byte_size=len(content),
        retrieved_at=retrieved_at or datetime.now(),
        etag=response.headers.get("ETag"),
        last_modified=response.headers.get("Last-Modified"),
    )


def _expanded_lexical_qname(value: str | None, element: etree._Element) -> str | None:
    if not value:
        return None
    if value.startswith("{"):
        return value
    if ":" in value:
        prefix, local_name = value.split(":", 1)
        namespace = element.nsmap.get(prefix)
        return f"{{{namespace}}}{local_name}" if namespace else value
    namespace = element.nsmap.get(None)
    return f"{{{namespace}}}{value}" if namespace else value


def _element_local_name(element: etree._Element) -> str:
    """Comments/processing instructions 沒有字串 tag，不可直接交給 QName。"""
    return etree.QName(element).localname if isinstance(element.tag, str) else ""


def _attribute(element: etree._Element, name: str) -> str | None:
    """讀取 XML／舊式 Inline HTML 屬性；後者會使用全小寫名稱。"""
    value = element.get(name)
    if value is not None:
        return value
    folded_name = name.casefold()
    for attribute_name, attribute_value in element.attrib.items():
        if attribute_name.casefold() == folded_name:
            return attribute_value
    return None


def _local_name(qname: str | None) -> str:
    if not qname:
        return ""
    return qname.rsplit("}", 1)[-1].split(":")[-1]


def _namespace_uri(qname: str | None) -> str:
    if qname and qname.startswith("{") and "}" in qname:
        return qname[1:].split("}", 1)[0]
    return ""


def _is_notes_namespace(namespace_uri: str) -> bool:
    return bool(re.search(r"(?:^|[/_-])notes?(?:$|[/_-])", namespace_uri.casefold()))


def _date_text(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _descendant(element: etree._Element, local_name: str) -> etree._Element | None:
    folded_name = local_name.casefold()
    for child in element.iterdescendants():
        if _element_local_name(child).casefold() == folded_name:
            return child
    return None


def _descendants(element: etree._Element, local_name: str) -> Iterator[etree._Element]:
    folded_name = local_name.casefold()
    for child in element.iterdescendants():
        if _element_local_name(child).casefold() == folded_name:
            yield child


def _parse_contexts(root: etree._Element) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for node in root.iter():
        context_id = _attribute(node, "id")
        if _element_local_name(node).casefold() != "context" or not context_id:
            continue
        identifier = _descendant(node, "identifier")
        instant = _descendant(node, "instant")
        start = _descendant(node, "startDate")
        end = _descendant(node, "endDate")
        dimensions: list[dict[str, str]] = []
        for member in node.iterdescendants():
            local = _element_local_name(member).casefold()
            if local not in ("explicitmember", "typedmember"):
                continue
            dimension = _expanded_lexical_qname(_attribute(member, "dimension"), member) or ""
            if local == "explicitmember":
                member_value = _expanded_lexical_qname("".join(member.itertext()).strip(), member) or ""
            else:
                member_value = " ".join(text.strip() for text in member.itertext() if text.strip())
            dimensions.append({"dimension": dimension, "member": member_value})
        dimensions.sort(key=lambda item: (item["dimension"], item["member"]))
        contexts[context_id] = {
            "entity_identifier": "".join(identifier.itertext()).strip() if identifier is not None else None,
            "instant": _date_text("".join(instant.itertext()) if instant is not None else None),
            "start_date": _date_text("".join(start.itertext()) if start is not None else None),
            "end_date": _date_text("".join(end.itertext()) if end is not None else None),
            "dimensions": dimensions,
            "dimensions_json": json.dumps(dimensions, ensure_ascii=False, sort_keys=True),
        }
    return contexts


def _parse_units(root: etree._Element) -> dict[str, str]:
    units: dict[str, str] = {}
    for node in root.iter():
        unit_id = _attribute(node, "id")
        if _element_local_name(node).casefold() != "unit" or not unit_id:
            continue
        numerators: list[str] = []
        denominators: list[str] = []
        divide = _descendant(node, "divide")
        if divide is None:
            numerators = [
                _local_name(_expanded_lexical_qname("".join(measure.itertext()).strip(), measure))
                for measure in _descendants(node, "measure")
            ]
        else:
            numerator_node = _descendant(divide, "unitNumerator")
            denominator_node = _descendant(divide, "unitDenominator")
            if numerator_node is not None:
                numerators = [
                    _local_name(_expanded_lexical_qname("".join(measure.itertext()).strip(), measure))
                    for measure in _descendants(numerator_node, "measure")
                ]
            if denominator_node is not None:
                denominators = [
                    _local_name(_expanded_lexical_qname("".join(measure.itertext()).strip(), measure))
                    for measure in _descendants(denominator_node, "measure")
                ]
        text = "*".join(filter(None, numerators)) or "unknown"
        if denominators:
            text += "/" + "*".join(filter(None, denominators))
        units[unit_id] = text
    return units


def _numeric_value(raw_value: str, scale: str | None = None, sign: str | None = None) -> float | None:
    text = re.sub(r"[\s,]", "", raw_value).replace("−", "-").replace("－", "-")
    if text in ("", "-", "--", "N/A"):
        return None
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        number = Decimal(text)
        if scale:
            number *= Decimal(10) ** int(scale)
        if sign == "-":
            number = -abs(number)
        return float(number) if number.is_finite() else None
    except (InvalidOperation, ValueError, OverflowError):
        return None


def _build_metric_map() -> dict[str, MetricDefinition]:
    groups: list[tuple[str, str, str, tuple[str, ...]]] = [
        ("revenue", "income", "amount", (
            "Revenue", "OperatingRevenue", "OperatingRevenueNet", "NetOperatingRevenue",
        )),
        ("cost_of_revenue", "income", "amount", (
            "OperatingCosts", "CostOfGoodsSold", "OperatingCost",
        )),
        ("gross_profit", "income", "amount", (
            "GrossProfitLossFromOperations", "GrossProfitLoss", "GrossProfit",
        )),
        ("operating_expenses", "income", "amount", (
            "OperatingExpenses", "TotalOperatingExpenses",
        )),
        ("operating_income", "income", "amount", (
            "NetOperatingIncomeLoss", "OperatingIncomeLoss", "OperatingProfitLoss",
        )),
        ("nonoperating_income", "income", "amount", (
            "NonoperatingIncomeAndExpenses", "NonOperatingIncomeAndExpenses",
        )),
        ("pretax_income", "income", "amount", (
            "ProfitLossFromContinuingOperationsBeforeTax", "ProfitLossBeforeTax", "IncomeLossBeforeTax",
        )),
        ("income_tax", "income", "amount", (
            "TaxExpenseIncome", "IncomeTaxExpenseBenefit", "IncomeTaxExpense",
        )),
        ("net_income", "income", "amount", (
            "ProfitLoss", "NetIncomeLoss", "NetIncome",
        )),
        ("net_income_parent", "income", "amount", (
            "ProfitLossAttributableToOwnersOfParent", "NetIncomeLossAttributableToOwnersOfParent",
        )),
        ("comprehensive_income", "income", "amount", (
            "OtherComprehensiveIncome", "OtherComprehensiveIncomeLossNetOfTax",
        )),
        ("eps", "income", "eps", (
            "BasicEarningsLossPerShare", "BasicEarningsPerShare",
        )),
        ("diluted_eps", "income", "eps", (
            "DilutedEarningsLossPerShare", "DilutedEarningsPerShare",
        )),
        ("cash_and_equivalents", "balance", "amount", ("CashAndCashEquivalents",)),
        ("accounts_receivable", "balance", "amount", (
            "AccountsReceivableNet", "NotesAndAccountsReceivableNet",
        )),
        ("inventories", "balance", "amount", ("Inventories",)),
        ("current_assets", "balance", "amount", ("CurrentAssets",)),
        ("noncurrent_assets", "balance", "amount", ("NoncurrentAssets", "NonCurrentAssets")),
        ("total_assets", "balance", "amount", ("Assets", "TotalAssets")),
        ("property_plant_equipment", "balance", "amount", (
            "PropertyPlantAndEquipment", "PropertyPlantAndEquipmentNet",
        )),
        ("current_liabilities", "balance", "amount", ("CurrentLiabilities",)),
        ("noncurrent_liabilities", "balance", "amount", (
            "NoncurrentLiabilities", "NonCurrentLiabilities",
        )),
        ("total_liabilities", "balance", "amount", ("Liabilities", "TotalLiabilities")),
        ("short_term_borrowings", "balance", "amount", ("ShorttermBorrowings", "ShortTermBorrowings")),
        ("long_term_debt", "balance", "amount", (
            "LongtermBorrowings", "LongTermBorrowings", "LongtermDebt",
        )),
        ("share_capital", "balance", "amount", (
            "CapitalStock", "ShareCapital", "CapitalStockTotal",
        )),
        ("retained_earnings", "balance", "amount", (
            "RetainedEarnings", "RetainedEarningsAccumulatedDeficit",
        )),
        ("equity_parent", "balance", "amount", (
            "EquityAttributableToOwnersOfParent", "EquityAttributableToOwnersOfParentCompany",
        )),
        ("total_equity", "balance", "amount", ("Equity", "TotalEquity")),
        ("noncontrolling_interests", "balance", "amount", ("NoncontrollingInterests",)),
        ("book_value_per_share", "balance", "eps", (
            "BookValuePerShare", "NetValuePerShare",
        )),
        ("operating_cash_flow", "cash_flow", "amount", (
            "NetCashFlowsFromUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivities",
        )),
        ("investing_cash_flow", "cash_flow", "amount", (
            "NetCashFlowsFromUsedInInvestingActivities",
            "NetCashProvidedByUsedInInvestingActivities",
        )),
        ("financing_cash_flow", "cash_flow", "amount", (
            "NetCashFlowsFromUsedInFinancingActivities",
            "NetCashProvidedByUsedInFinancingActivities",
        )),
        ("exchange_effect_on_cash", "cash_flow", "amount", (
            "EffectOfExchangeRateChangesOnCashAndCashEquivalents",
        )),
        ("cash_change", "cash_flow", "amount", (
            "NetIncreaseDecreaseInCashAndCashEquivalents",
            "IncreaseDecreaseInCashAndCashEquivalents",
        )),
        ("cash_beginning", "cash_flow", "amount", (
            "CashAndCashEquivalentsAtBeginningOfPeriod",
        )),
        ("cash_ending", "cash_flow", "amount", (
            "CashAndCashEquivalentsAtEndOfPeriod",
        )),
    ]
    mapping: dict[str, MetricDefinition] = {}
    for metric_key, statement_type, unit_kind, aliases in groups:
        for index, alias in enumerate(aliases):
            if alias in mapping:
                raise RuntimeError(f"重複的 XBRL local name mapping：{alias}")
            mapping[alias] = MetricDefinition(metric_key, statement_type, unit_kind, len(aliases) - index)
    return mapping


_METRIC_MAP = _build_metric_map()
_COMPANY_NAME_CONCEPTS = {
    "NameOfReportingEntityOrOtherMeansOfIdentification",
    "NameOfReportingEntity",
}


def _iter_fact_elements(root: etree._Element, content_format: str) -> Iterator[tuple[etree._Element, str]]:
    if content_format == "inline_xbrl":
        for element in root.iter():
            if _element_local_name(element).casefold() in ("nonfraction", "nonnumeric"):
                qname = _expanded_lexical_qname(element.get("name"), element)
                if qname:
                    yield element, qname
        return
    for element in root.iter():
        if _attribute(element, "contextRef"):
            yield element, element.tag


def _content_format(root: etree._Element) -> str:
    if any(
        _element_local_name(element).casefold() in ("nonfraction", "nonnumeric")
        for element in root.iter()
    ):
        return "inline_xbrl"
    return "xbrl_xml"


def _stock_id(contexts: dict[str, dict[str, Any]], entry_path: str) -> str:
    identifiers = {
        context["entity_identifier"]
        for context in contexts.values()
        if context.get("entity_identifier")
    }
    candidates: set[str] = set()
    for identifier in identifiers:
        match = _STOCK_ID_RE.search(str(identifier))
        if match:
            candidates.add(match.group(1))
    if not candidates:
        match = _STOCK_ID_RE.search(PurePosixPath(entry_path).name)
        if match:
            candidates.add(match.group(1))
    if len(candidates) != 1:
        raise MopsXbrlError(f"XBRL 無法唯一辨識公司代號：{entry_path} -> {sorted(candidates)}")
    return candidates.pop()


def _industry_schema(namespace_uri: str) -> str:
    for schema in ("basi", "bd", "ci", "fh", "ins", "mim"):
        if re.search(rf"(?:/|-){schema}(?:/|-|$)", namespace_uri, re.IGNORECASE):
            return schema
    return "xbrl"


def _dimension_priority(dimensions: list[dict[str, str]]) -> int:
    if not dimensions:
        return 20
    joined = " ".join(
        f"{item.get('dimension', '')} {item.get('member', '')}" for item in dimensions
    ).lower()
    if "consolidatedfinancialstatementsmember" in joined or "consolidated" in joined:
        return 30
    return -1


def _context_matches(
    context: dict[str, Any], definition: MetricDefinition, year: int, quarter: int,
) -> bool:
    period_end = _period_end(year, quarter)
    if definition.statement_type == "balance":
        return context.get("instant") == period_end
    return (
        context.get("start_date") == date(year, 1, 1)
        and context.get("end_date") == period_end
    )


def _normalize_canonical_value(
    value: float, raw_unit: str | None, definition: MetricDefinition,
) -> tuple[float, str] | None:
    unit = (raw_unit or "").lower()
    if definition.unit_kind == "amount":
        if "twd" not in unit:
            return None
        return value / 1000.0, "TWD_thousand"
    if definition.unit_kind == "eps":
        # 早期申報（實測 2013Q1，2330/1101 等 300/300 中）常見用純 TWD 當
        # unitRef，不透過 divide/unitDenominator=shares 表示「每股」；concept 本身
        # 已經是 BasicEarningsLossPerShare/DilutedEarningsLossPerShare，語意不需要
        # unit 字串裡也含 "share" 才能確認，硬性要求會把值正確、只是單位標示不規範
        # 的早期資料整批濾成 None（2026-09-02 debug 驗證抓到）。
        if "twd" not in unit:
            return None
        return value, "TWD/share"
    if definition.unit_kind == "shares":
        return (value, "shares") if "share" in unit else None
    return value, raw_unit or "pure"


def _supported_metric_namespace(namespace_uri: str) -> bool:
    """Canonical mapping 只套在 IFRS／TWSE taxonomy family；其他 QName 仍保存 raw。"""
    namespace = namespace_uri.lower()
    return "ifrs" in namespace or "twse" in namespace or "mops" in namespace


def _statement_namespace_priority(namespace_uri: str, statement_type: str) -> int:
    """避免把現金流調節項的同名 concept 投影成損益表指標。

    早期 TIFRS taxonomy 會在 `sci`/`sfp`/`scf`/`sce` statement namespace
    重複使用相同 local name。若 namespace 已明示報表，只能投影到對應報表；
    IASB／公司 extension 等未明示 statement 的 namespace 維持一般候選。
    """
    namespace = namespace_uri.lower()
    if re.search(r"(?:^|[/_-])notes?(?:$|[/_-])", namespace):
        return -1
    match = re.search(r"(?:^|[/_-])(sci|sfp|scf|sce)(?:$|[/_-])", namespace)
    if match is None:
        return 10
    expected = {
        "income": "sci",
        "balance": "sfp",
        "cash_flow": "scf",
        "equity": "sce",
    }.get(statement_type)
    return 20 if match.group(1) == expected else -1


def _canonical_facts(
    raw_facts: list[dict[str, Any]], year: int, quarter: int,
) -> list[dict[str, Any]]:
    candidates: dict[tuple[str, str], list[tuple[tuple[int, int, int], dict[str, Any]]]] = {}
    for fact in raw_facts:
        definition = _METRIC_MAP.get(fact["local_name"])
        context = fact["_context"]
        if (
            definition is None
            or not _supported_metric_namespace(fact["namespace_uri"])
            or fact["numeric_value"] is None
            or not _context_matches(
            context, definition, year, quarter,
            )
        ):
            continue
        dimension_priority = _dimension_priority(context["dimensions"])
        namespace_priority = _statement_namespace_priority(
            fact["namespace_uri"], definition.statement_type,
        )
        if dimension_priority < 0 or namespace_priority < 0:
            continue
        normalized = _normalize_canonical_value(fact["numeric_value"], fact["unit"], definition)
        if normalized is None:
            continue
        value, unit = normalized
        row = {
            "stock_id": fact["stock_id"],
            "period_end": _period_end(year, quarter),
            "fiscal_year": year,
            "quarter": quarter,
            "statement_type": definition.statement_type,
            "industry_schema": _industry_schema(fact["namespace_uri"]),
            "metric_key": definition.metric_key,
            "qname": fact["qname"],
            "context_id": fact["context_id"],
            "value": value,
            "unit": unit,
            "is_ytd": definition.statement_type != "balance",
        }
        key = (definition.statement_type, definition.metric_key)
        rank = (dimension_priority, namespace_priority, definition.alias_priority)
        candidates.setdefault(key, []).append((rank, row))

    result: list[dict[str, Any]] = []
    for key, rows in candidates.items():
        best_rank = max(rank for rank, _ in rows)
        best = [row for rank, row in rows if rank == best_rank]
        distinct_values = {row["value"] for row in best}
        if len(distinct_values) > 1:
            logger.warning(
                "MOPS XBRL %s %d Q%d 同優先序 fact 數值衝突，略過 canonical fact %s/%s：%s",
                best[0]["stock_id"], year, quarter, key[0], key[1],
                sorted(distinct_values),
            )
            continue
        result.append(best[0])
    return sorted(result, key=lambda row: (row["statement_type"], row["metric_key"]))


def parse_xbrl_instance(
    content: bytes,
    entry_path: str,
    year: int,
    quarter: int,
    archive_sha256: str,
    retrieved_at: datetime,
) -> ParsedInstance | None:
    """解析單一案例文件；taxonomy/linkbase 等無 context XML 回 None。"""
    try:
            root = _xml_parse_content(content, entry_path)
    except etree.XMLSyntaxError as exc:
        raise MopsXbrlError(f"XBRL XML 解析失敗：{entry_path}") from exc
    contexts = _parse_contexts(root)
    if not contexts:
        return None
    units = _parse_units(root)
    stock_id = _stock_id(contexts, entry_path)
    content_format = _content_format(root)
    filing_sha256 = hashlib.sha256(content).hexdigest()
    schema_refs = sorted({
        element.get("{http://www.w3.org/1999/xlink}href")
        for element in root.iter()
        if _element_local_name(element) == "schemaRef"
        and element.get("{http://www.w3.org/1999/xlink}href")
    })
    raw_facts: list[dict[str, Any]] = []
    company_name: str | None = None
    for fact_index, (element, qname) in enumerate(_iter_fact_elements(root, content_format)):
        context_id = _attribute(element, "contextRef")
        context = contexts.get(context_id or "")
        if context is None:
            if _is_notes_namespace(_namespace_uri(qname)):
                logger.warning(
                    "MOPS XBRL %s context 不存在，略過附註 fact：%s/%s",
                    entry_path, qname, context_id,
                )
                continue
            raise MopsXbrlError(f"fact 引用不存在的 context：{entry_path}/{context_id}")
        raw_value = " ".join(text.strip() for text in element.itertext() if text.strip())
        is_nil = str(element.get(_XSI_NIL, "false")).lower() in ("true", "1")
        unit_id = _attribute(element, "unitRef")
        numeric = None if is_nil else _numeric_value(
            raw_value,
            scale=_attribute(element, "scale") if content_format == "inline_xbrl" else None,
            sign=_attribute(element, "sign") if content_format == "inline_xbrl" else None,
        )
        local_name = _local_name(qname)
        if local_name in _COMPANY_NAME_CONCEPTS and raw_value:
            company_name = raw_value
        raw_facts.append({
            "filing_sha256": filing_sha256,
            "fact_index": fact_index,
            "stock_id": stock_id,
            "qname": qname,
            "namespace_uri": _namespace_uri(qname),
            "local_name": local_name,
            "context_id": context_id,
            "period_start": context["start_date"],
            "period_end": context["end_date"],
            "instant": context["instant"],
            "unit_id": unit_id,
            "unit": units.get(unit_id or ""),
            "decimals": _attribute(element, "decimals"),
            "dimensions_json": context["dimensions_json"],
            "raw_value": raw_value,
            "numeric_value": numeric,
            "is_nil": is_nil,
            "_context": context,
        })
    if not raw_facts:
        raise MopsXbrlError(f"案例文件沒有 facts：{entry_path}")
    canonical = _canonical_facts(raw_facts, year, quarter)
    for row in raw_facts:
        row.pop("_context")
    for row in canonical:
        row.update({
            "filing_sha256": filing_sha256,
            "first_seen_at": retrieved_at,
            "reported_at": None,
        })
    filing = {
        "filing_sha256": filing_sha256,
        "archive_sha256": archive_sha256,
        "entry_path": entry_path,
        "stock_id": stock_id,
        "stock_name": company_name,
        "period_end": _period_end(year, quarter),
        "fiscal_year": year,
        "quarter": quarter,
        "content_format": content_format,
        "taxonomy_refs_json": json.dumps(schema_refs, ensure_ascii=False),
        "reported_at": None,
        "first_seen_at": retrieved_at,
    }
    return ParsedInstance(filing=filing, facts=raw_facts, canonical_facts=canonical)


def _iter_zip_documents(
    archive: zipfile.ZipFile, prefix: str = "", depth: int = 0,
) -> Iterator[tuple[str, bytes]]:
    """支援官方外包 ZIP 裡再包公司 ZIP；最多兩層且永不 extract。"""
    if depth > 2:
        raise MopsXbrlError(f"XBRL ZIP 巢狀超過安全上限：{prefix}")
    bad_entry = archive.testzip()
    if bad_entry is not None:
        raise MopsXbrlError(f"ZIP entry CRC 錯誤：{prefix}{bad_entry}")
    supported = {".xml", ".xbrl", ".xhtml", ".html", ".htm"}
    for info in archive.infolist():
        if info.is_dir():
            continue
        content = archive.read(info)
        entry_path = f"{prefix}{info.filename}"
        suffix = PurePosixPath(info.filename).suffix.lower()
        if suffix == ".zip":
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as nested:
                    yield from _iter_zip_documents(nested, prefix=f"{entry_path}!/", depth=depth + 1)
            except zipfile.BadZipFile as exc:
                raise MopsXbrlError(f"巢狀 ZIP 損壞：{entry_path}") from exc
        elif suffix in supported:
            yield entry_path, content


def iter_archive_instances(downloaded: DownloadedArchive) -> Iterator[ParsedInstance]:
    """安全地從 ZIP 記憶體讀 entry；不將不可信路徑解壓到磁碟。"""
    try:
        with zipfile.ZipFile(downloaded.path) as archive:
            for entry_path, content in _iter_zip_documents(archive):
                instance = parse_xbrl_instance(
                    content=content,
                    entry_path=entry_path,
                    year=downloaded.link.year,
                    quarter=downloaded.link.quarter,
                    archive_sha256=downloaded.sha256,
                    retrieved_at=downloaded.retrieved_at,
                )
                if instance is not None:
                    yield instance
    except zipfile.BadZipFile as exc:
        raise MopsXbrlError(f"ZIP 損壞：{downloaded.path}") from exc


def _insert_dicts(con, table: str, registration: str, rows: list[dict[str, Any]], columns: list[str]) -> None:
    if not rows:
        return
    frame = pd.DataFrame([{column: row.get(column) for column in columns} for row in rows])
    con.register(registration, frame)
    con.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"SELECT {', '.join(columns)} FROM {registration}"
    )
    con.unregister(registration)


def _current_financial_rows(con, affected_periods: set[tuple[str, date]]) -> list[dict[str, Any]]:
    if not affected_periods:
        return []
    key_rows = [{"stock_id": stock_id, "period_end": period_end} for stock_id, period_end in affected_periods]
    con.register("affected_xbrl_periods_df", pd.DataFrame(key_rows))
    rows = con.execute("""
        WITH latest_market AS (
            SELECT stock_id,
                   arg_max(stock_name, revenue_month) AS stock_name,
                   arg_max(exchange, revenue_month) AS exchange
            FROM monthly_revenue
            GROUP BY stock_id
        )
        SELECT current.stock_id,
               COALESCE(current.stock_name, market.stock_name) AS stock_name,
               COALESCE(market.exchange, 'UNKNOWN') AS exchange,
               current.period_end, current.fiscal_year, current.quarter,
               current.statement_type, current.industry_schema, current.metric_key,
               current.qname AS raw_name, current.value, current.unit, current.is_ytd,
               current.reported_at AS report_date,
               current.first_seen_at, current.first_seen_at AS fetched_at,
               'mops_xbrl' AS source
        FROM xbrl_current_facts current
        JOIN affected_xbrl_periods_df affected
          ON affected.stock_id = current.stock_id
         AND affected.period_end = current.period_end
        LEFT JOIN latest_market market ON market.stock_id = current.stock_id
    """).fetchdf()
    con.unregister("affected_xbrl_periods_df")
    return rows.to_dict("records")


def save_downloaded_archive(
    downloaded: DownloadedArchive, db_path: str = _DB_PATH,
) -> dict[str, int]:
    """以單一 transaction 保存整個 archive；同 SHA 重跑不新增資料。"""
    from scrapers.fundamentals import _upsert_financial_facts

    con = duckdb.connect(db_path)
    transaction_started = False
    counts = {"archives": 0, "filings": 0, "raw_facts": 0, "canonical_facts": 0}
    try:
        existing = con.execute(
            "SELECT 1 FROM xbrl_archives WHERE archive_sha256 = ?", [downloaded.sha256],
        ).fetchone()
        if existing:
            return counts
        con.execute("BEGIN")
        transaction_started = True
        con.execute("""
            INSERT INTO xbrl_archives (
                archive_sha256, accounting_standard, fiscal_year, quarter, period_end,
                source_url, source_filename, local_path, byte_size, etag, last_modified,
                first_seen_at, retrieved_at
            ) VALUES (?, 'IFRS', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            downloaded.sha256,
            downloaded.link.year,
            downloaded.link.quarter,
            downloaded.link.period_end,
            downloaded.link.url,
            downloaded.link.filename,
            str(downloaded.path),
            downloaded.byte_size,
            downloaded.etag,
            downloaded.last_modified,
            downloaded.retrieved_at,
            downloaded.retrieved_at,
        ])
        counts["archives"] = 1
        affected_periods: set[tuple[str, date]] = set()
        instance_count = 0
        for instance in iter_archive_instances(downloaded):
            instance_count += 1
            filing_sha = instance.filing["filing_sha256"]
            already_saved = con.execute(
                "SELECT 1 FROM xbrl_filings WHERE filing_sha256 = ?", [filing_sha],
            ).fetchone()
            if not already_saved:
                filing_columns = [
                    "filing_sha256", "archive_sha256", "entry_path", "stock_id", "stock_name",
                    "period_end", "fiscal_year", "quarter", "content_format", "taxonomy_refs_json",
                    "reported_at", "first_seen_at",
                ]
                _insert_dicts(con, "xbrl_filings", "xbrl_filing_df", [instance.filing], filing_columns)
                fact_columns = [
                    "filing_sha256", "fact_index", "stock_id", "qname", "namespace_uri", "local_name",
                    "context_id", "period_start", "period_end", "instant", "unit_id", "unit", "decimals",
                    "dimensions_json", "raw_value", "numeric_value", "is_nil",
                ]
                _insert_dicts(con, "xbrl_facts", "xbrl_facts_df", instance.facts, fact_columns)
                canonical_columns = [
                    "filing_sha256", "stock_id", "period_end", "fiscal_year", "quarter",
                    "statement_type", "industry_schema", "metric_key", "qname", "context_id",
                    "value", "unit", "is_ytd", "first_seen_at", "reported_at",
                ]
                _insert_dicts(
                    con, "xbrl_canonical_facts", "xbrl_canonical_df",
                    instance.canonical_facts, canonical_columns,
                )
                counts["filings"] += 1
                counts["raw_facts"] += len(instance.facts)
                counts["canonical_facts"] += len(instance.canonical_facts)
                affected_periods.add((instance.filing["stock_id"], instance.filing["period_end"]))
            con.execute("""
                INSERT INTO xbrl_archive_entries (archive_sha256, entry_path, filing_sha256)
                VALUES (?, ?, ?)
            """, [downloaded.sha256, instance.filing["entry_path"], filing_sha])
        if instance_count == 0:
            raise MopsXbrlError(f"archive 沒有可辨識的 XBRL 案例文件：{downloaded.link.filename}")

        affected_periods.update(
            (str(stock_id), period_end)
            for stock_id, period_end in con.execute("""
                SELECT DISTINCT stock_id, period_end
                FROM financial_facts
                WHERE source = 'mops_xbrl' AND period_end = ?
            """, [downloaded.link.period_end]).fetchall()
        )
        current_rows = _current_financial_rows(con, affected_periods)
        if current_rows:
            existing_first_seen = {
                (row[0], str(row[1])[:10], row[2], row[3]): row[4]
                for row in con.execute("""
                    SELECT stock_id, period_end, statement_type, metric_key, MIN(first_seen_at)
                    FROM financial_facts
                    GROUP BY stock_id, period_end, statement_type, metric_key
                """).fetchall()
            }
            for row in current_rows:
                key = (
                    row["stock_id"], str(row["period_end"])[:10],
                    row["statement_type"], row["metric_key"],
                )
                if key in existing_first_seen:
                    row["first_seen_at"] = existing_first_seen[key]
        if affected_periods:
            affected_rows = [
                {"stock_id": stock_id, "period_end": period_end}
                for stock_id, period_end in affected_periods
            ]
            con.register("affected_xbrl_projection_df", pd.DataFrame(affected_rows))
            con.execute("""
                DELETE FROM financial_facts AS fact
                USING affected_xbrl_projection_df AS affected
                WHERE fact.source = 'mops_xbrl'
                  AND fact.stock_id = affected.stock_id
                  AND fact.period_end = affected.period_end
            """)
            con.unregister("affected_xbrl_projection_df")
        if current_rows:
            _upsert_financial_facts(con, current_rows)
        con.execute("COMMIT")
        transaction_started = False
        return counts
    except Exception:
        if transaction_started:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def _completed_archive_periods(db_path: str) -> set[tuple[int, int]]:
    """已提交 archive 才算完成；失敗季度因 transaction rollback 不會被略過。"""
    if not Path(db_path).is_file():
        return set()
    con = duckdb.connect(db_path, read_only=True)
    try:
        table_exists = con.execute("""
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_name = 'xbrl_archives'
        """).fetchone()[0]
        if not table_exists:
            return set()
        return {
            (int(year), int(quarter))
            for year, quarter in con.execute("""
                SELECT DISTINCT fiscal_year, quarter
                FROM xbrl_archives
                WHERE accounting_standard = 'IFRS'
            """).fetchall()
        }
    finally:
        con.close()


def backfill_mops_xbrl(
    start_year: int = 2013,
    end_year: int | None = None,
    db_path: str = _DB_PATH,
    cache_root: Path | str = _CACHE_ROOT,
    delay_seconds: float = 0.8,
    session=requests,
    refresh_existing: bool = False,
) -> dict[str, int]:
    """從官方清單依序回填 IFRS 季報；預設略過已完整提交的季度。"""
    if start_year < 2013:
        raise ValueError("Phase 2 只支援 IFRS 2013 Q1 起；TW-GAAP 不在本階段")
    end_year = end_year or date.today().year
    if end_year < start_year:
        raise ValueError("end_year 不可早於 start_year")
    links = [
        link for link in discover_ifrs_archives(session=session)
        if start_year <= link.year <= end_year
    ]
    if not links:
        raise MopsXbrlError(f"MOPS 清單沒有 {start_year}~{end_year} 的 IFRS ZIP")
    if not refresh_existing:
        completed = _completed_archive_periods(db_path)
        pending = []
        for link in links:
            if (link.year, link.quarter) in completed:
                logger.info("MOPS XBRL %d Q%d：已完成，跳過", link.year, link.quarter)
            else:
                pending.append(link)
        links = pending
    totals = {"archives": 0, "filings": 0, "raw_facts": 0, "canonical_facts": 0}
    for index, link in enumerate(links):
        logger.info("MOPS XBRL 回填 %d Q%d：下載 %s", link.year, link.quarter, link.filename)
        downloaded = download_archive(link, cache_root=cache_root, session=session)
        counts = save_downloaded_archive(downloaded, db_path=db_path)
        for name, count in counts.items():
            totals[name] += count
        logger.info(
            "MOPS XBRL %d Q%d：archive +%d、filings +%d、raw facts +%d、canonical +%d",
            link.year, link.quarter, counts["archives"], counts["filings"],
            counts["raw_facts"], counts["canonical_facts"],
        )
        if delay_seconds > 0 and index < len(links) - 1:
            time.sleep(delay_seconds)
    return totals
