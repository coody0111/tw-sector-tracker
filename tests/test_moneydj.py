from unittest.mock import patch, MagicMock
from scrapers.moneydj import scrape_industry_sectors, scrape_concept_sectors, SectorStock

MOCK_INDUSTRY_INDEX_HTML = """
<html><body>
<a href="/z/zh/zha/zh00.djhtm?a=C023100">半導體</a>
<a href="/z/zh/zha/zh00.djhtm?a=C023200">IC設計</a>
<a href="/unrelated">其他連結</a>
</body></html>
"""

MOCK_SECTOR_PAGE_HTML = """
<html><body>
<table>
<tr><th>代號</th><th>名稱</th><th>現價</th></tr>
<tr><td>2330</td><td>台積電</td><td>905.00</td></tr>
<tr><td>2454</td><td>聯發科</td><td>1200.00</td></tr>
</table>
</body></html>
"""

MOCK_CONCEPT_INDEX_HTML = """
<html><body>
<a href="/Z/ZG/ZGE/ZGE.djhtm?a=AI">AI</a>
<a href="/Z/ZG/ZGE/ZGE.djhtm?a=EV">電動車</a>
</body></html>
"""

def _make_mock_response(html: str):
    mock = MagicMock()
    mock.content = html.encode("cp950", errors="replace")
    mock.raise_for_status.return_value = None
    return mock

def test_scrape_industry_sectors_returns_list():
    responses = [
        _make_mock_response(MOCK_INDUSTRY_INDEX_HTML),
        _make_mock_response(MOCK_SECTOR_PAGE_HTML),
        _make_mock_response(MOCK_SECTOR_PAGE_HTML),
    ]
    with patch("scrapers.moneydj.requests.get", side_effect=responses), \
         patch("scrapers.moneydj.time.sleep"):
        result = scrape_industry_sectors()

    assert isinstance(result, list)
    assert all(isinstance(s, SectorStock) for s in result)

def test_scrape_industry_sectors_parses_stocks():
    responses = [
        _make_mock_response(MOCK_INDUSTRY_INDEX_HTML),
        _make_mock_response(MOCK_SECTOR_PAGE_HTML),
        _make_mock_response(MOCK_SECTOR_PAGE_HTML),
    ]
    with patch("scrapers.moneydj.requests.get", side_effect=responses), \
         patch("scrapers.moneydj.time.sleep"):
        result = scrape_industry_sectors()

    stock_ids = [s.stock_id for s in result]
    assert "2330" in stock_ids

def test_scrape_industry_sectors_sets_sector_name():
    responses = [
        _make_mock_response(MOCK_INDUSTRY_INDEX_HTML),
        _make_mock_response(MOCK_SECTOR_PAGE_HTML),
        _make_mock_response(MOCK_SECTOR_PAGE_HTML),
    ]
    with patch("scrapers.moneydj.requests.get", side_effect=responses), \
         patch("scrapers.moneydj.time.sleep"):
        result = scrape_industry_sectors()

    sector_names = {s.sector_name for s in result}
    assert "半導體" in sector_names

def test_scrape_concept_sectors_sets_type():
    responses = [
        _make_mock_response(MOCK_CONCEPT_INDEX_HTML),
        _make_mock_response(MOCK_SECTOR_PAGE_HTML),
        _make_mock_response(MOCK_SECTOR_PAGE_HTML),
    ]
    with patch("scrapers.moneydj.requests.get", side_effect=responses), \
         patch("scrapers.moneydj.time.sleep"):
        result = scrape_concept_sectors()

    assert all(s.sector_type == "concept" for s in result)
