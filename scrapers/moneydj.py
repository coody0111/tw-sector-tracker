import re
import requests
import time
import random
import logging
from bs4 import BeautifulSoup
from dataclasses import dataclass
from typing import List

logger = logging.getLogger(__name__)

BASE_URL = "https://www.moneydj.com"
INDUSTRY_INDEX_URL = f"{BASE_URL}/Z/ZH/ZHA/ZHA.djhtm"
CONCEPT_INDEX_URL = f"{BASE_URL}/Z/ZG/ZGE/ZGE.djhtm?a=E&b=E"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


@dataclass
class SectorStock:
    sector_type: str   # "industry" or "concept"
    sector_name: str
    sector_code: str   # e.g. "C023100" for industry; "" for concept
    stock_id: str
    stock_name: str


def _get(url: str, retries: int = 3) -> BeautifulSoup:
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return BeautifulSoup(resp.content, "lxml", from_encoding="cp950")
        except Exception as exc:
            logger.warning("GET %s attempt %d failed: %s", url, attempt + 1, exc)
            if attempt == retries - 1:
                raise
            time.sleep(5)


def _delay():
    time.sleep(random.uniform(1, 3))


def _parse_stock_table(soup: BeautifulSoup) -> List[tuple]:
    stocks = []
    for row in soup.select("table tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        first = cells[0].get_text(strip=True)
        # 一般股票代號 4 碼；TDR（台灣存託憑證）代號 6 碼、固定以 91 開頭
        m = re.match(r'^(91\d{4}|\d{4})(.*)$', first)
        if not m:
            continue
        stock_id = m.group(1)
        stock_name = m.group(2).strip()
        if not stock_name and len(cells) >= 2:
            stock_name = cells[1].get_text(strip=True)
        stocks.append((stock_id, stock_name))
    return stocks


def scrape_industry_sectors(limit: int = None) -> List[SectorStock]:
    results = []
    soup = _get(INDUSTRY_INDEX_URL)

    sector_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/zha/zh00.djhtm" in href.lower() and "?a=C" in href:
            sector_name = a.get_text(strip=True)
            sector_code = href.split("a=")[-1].split("&")[0]
            full_url = BASE_URL + href if href.startswith("/") else href
            if sector_name:
                sector_links.append((sector_name, sector_code, full_url))

    from config import should_include_sector
    sector_links = [s for s in sector_links if should_include_sector(s[1])]

    if limit is not None:
        sector_links = sector_links[:limit]

    for sector_name, sector_code, url in sector_links:
        _delay()
        try:
            page = _get(url)
            for stock_id, stock_name in _parse_stock_table(page):
                results.append(SectorStock(
                    sector_type="industry",
                    sector_name=sector_name,
                    sector_code=sector_code,
                    stock_id=stock_id,
                    stock_name=stock_name,
                ))
        except Exception as exc:
            logger.error("Failed to scrape industry sector %s: %s", sector_name, exc)

    return results


def scrape_concept_sectors(limit: int = None) -> List[SectorStock]:
    results = []
    soup = _get(CONCEPT_INDEX_URL)

    concept_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "ZGE.djhtm" in href and "?a=" in href:
            concept_name = a.get_text(strip=True)
            full_url = BASE_URL + href if href.startswith("/") else href
            if concept_name and concept_name not in ("E", ""):
                concept_links.append((concept_name, full_url))

    if limit is not None:
        concept_links = concept_links[:limit]

    for concept_name, url in concept_links:
        _delay()
        try:
            page = _get(url)
            for stock_id, stock_name in _parse_stock_table(page):
                results.append(SectorStock(
                    sector_type="concept",
                    sector_name=concept_name,
                    sector_code="",
                    stock_id=stock_id,
                    stock_name=stock_name,
                ))
        except Exception as exc:
            logger.error("Failed to scrape concept sector %s: %s", concept_name, exc)

    return results
