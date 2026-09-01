import hashlib
from datetime import date, datetime

import duckdb
import pytest

from scrapers.fundamentals import normalize_monthly_revenue, save_monthly_revenue
from scrapers.mops_monthly_revenue import (
    DownloadedMonthlyPage,
    MopsMonthlyRevenueError,
    _month_urls,
    parse_monthly_revenue_html,
    save_monthly_revenue_page,
)


def _page(exchange_title="上市公司", roc_year=113, month=1, revenue="1,000") -> bytes:
    cells = [
        "2330", "台積電", revenue, "900", "800", "11.11", "25.00",
        revenue, "800", "25.00", "-",
    ]
    headers = [
        "公司代號", "公司名稱", "當月營收", "上月營收", "去年當月營收",
        "上月比較增減(%)", "去年同月增減(%)", "當月累計營收", "去年累計營收",
        "前期比較增減(%)", "備註",
    ]
    html = f"""<html><head><meta http-equiv="Content-Type" content="text/html;charset=big5"></head>
    <body><h2>{exchange_title}{roc_year}年{month}月份營業收入統計表</h2>
      <table><tr><td>產業別：半導體業</td><td>單位：千元</td></tr>
        <tr>{''.join(f'<th>{value}</th>' for value in headers)}</tr>
        <tr>{''.join(f'<td>{value}</td>' for value in cells)}</tr>
        <tr><td>合計</td>{''.join('<td>0</td>' for _ in range(10))}</tr>
      </table>
    </body></html>"""
    return html.encode("big5")


def _downloaded_page(tmp_path, content, rows, when):
    digest = hashlib.sha256(content).hexdigest()
    path = tmp_path / f"{digest}.html"
    path.write_bytes(content)
    return DownloadedMonthlyPage(
        page_sha256=digest,
        exchange="TWSE",
        revenue_month=date(2024, 1, 1),
        source_url="https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_113_1_0.html",
        path=path,
        byte_size=len(content),
        retrieved_at=when,
        rows=rows,
    )


def test_parse_big5_page_maps_11_columns_and_skips_total():
    rows = parse_monthly_revenue_html(
        _page(), "TWSE", 2024, 1, fetched_at=datetime(2024, 2, 15),
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["stock_id"] == "2330"
    assert row["stock_name"] == "台積電"
    assert row["exchange"] == "TWSE"
    assert row["industry"] == "半導體業"
    assert row["revenue_month"] == date(2024, 1, 1)
    assert row["revenue"] == 1000
    assert row["previous_month_revenue"] == 900
    assert row["reported_yoy_pct"] == 25.0
    assert row["note"] is None
    assert row["report_date"] is None
    assert row["source"] == "mops_monthly_history"


def test_parse_real_page_header_with_10_cells_and_spaced_label():
    """2026-09-02 debug 複驗 Big5 修復時真實打 TWSE 2025-06 頁面才暴露的獨立bug：
    真實表頭列只有10格（不是資料列的11格），且第一格文字是「公司 代號」（中間多一個
    空格），原本的 len(texts)>=11 and texts[0]=="公司代號" 兩個條件都對不上，
    header_seen 永遠False，990列合法資料全被判定失敗。"""
    cells = [
        "2330", "台積電", "1,000", "900", "800", "11.11", "25.00",
        "1,000", "800", "25.00", "-",
    ]
    html = f"""<html><head><meta http-equiv="Content-Type" content="text/html;charset=big5"></head>
    <body><h2>上市公司113年1月份營業收入統計表</h2>
      <table><tr><td>產業別：半導體業</td><td>單位：千元</td></tr>
        <tr><th>公司 代號</th><th>公司名稱</th><th>當月營收</th><th>上月營收</th>
          <th>去年當月營收</th><th>上月比較增減(%)</th><th>去年同月增減(%)</th>
          <th>當月累計營收</th><th>去年累計營收</th><th>前期比較增減(%)</th></tr>
        <tr>{''.join(f'<td>{value}</td>' for value in cells)}</tr>
        <tr><td>合計</td>{''.join('<td>0</td>' for _ in range(10))}</tr>
      </table>
    </body></html>""".encode("big5")

    rows = parse_monthly_revenue_html(html, "TWSE", 2024, 1)
    assert len(rows) == 1
    assert rows[0]["stock_id"] == "2330"


def test_tpex_title_sets_tpex_exchange():
    rows = parse_monthly_revenue_html(
        _page(exchange_title="上櫃公司"), "TPEx", 2024, 1,
    )
    assert rows[0]["exchange"] == "TPEx"


def test_200_error_page_and_invalid_big5_are_rejected():
    with pytest.raises(MopsMonthlyRevenueError, match="標題不符"):
        parse_monthly_revenue_html("因為安全性考量，頁面無法呈現".encode("big5"), "TWSE", 2024, 1)
    with pytest.raises(MopsMonthlyRevenueError, match="有效 Big5"):
        parse_monthly_revenue_html(b"\x81", "TWSE", 2024, 1)


def test_single_digit_month_has_unpadded_and_padded_candidates():
    urls = _month_urls("TWSE", 2024, 1)
    assert urls == [
        "https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_113_1_0.html",
        "https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_113_01_0.html",
    ]


def test_page_versions_are_append_only_and_preserve_openapi_report_date(tmp_path, monkeypatch):
    from screener import database

    db_path = tmp_path / "monthly.duckdb"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    database.init_db()
    openapi = normalize_monthly_revenue([{
        "出表日期": "1130215",
        "資料年月": "11301",
        "產業別": "半導體業",
        "公司代號": "2330",
        "公司名稱": "台積電",
        "營業收入-當月營收": "1,000",
    }], "TWSE", fetched_at=datetime(2024, 2, 15))
    save_monthly_revenue(openapi, str(db_path))

    content1 = _page(revenue="1,000")
    rows1 = parse_monthly_revenue_html(content1, "TWSE", 2024, 1, datetime(2024, 3, 1))
    content2 = _page(revenue="1,100")
    rows2 = parse_monthly_revenue_html(content2, "TWSE", 2024, 1, datetime(2024, 3, 2))
    page1 = _downloaded_page(tmp_path, content1, rows1, datetime(2024, 3, 1))
    page2 = _downloaded_page(tmp_path, content2, rows2, datetime(2024, 3, 2))

    first = save_monthly_revenue_page(page1, str(db_path))
    repeated = save_monthly_revenue_page(page1, str(db_path))
    second = save_monthly_revenue_page(page2, str(db_path))

    assert first == {"pages": 1, "versions": 1, "current_rows": 1}
    assert repeated == {"pages": 0, "versions": 0, "current_rows": 1}
    assert second == {"pages": 1, "versions": 1, "current_rows": 1}
    con = duckdb.connect(str(db_path))
    assert con.execute("SELECT COUNT(*) FROM monthly_revenue_pages").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM monthly_revenue_versions").fetchone()[0] == 2
    revenue, report_date, source = con.execute("""
        SELECT revenue, report_date, source FROM monthly_revenue
        WHERE stock_id = '2330' AND revenue_month = DATE '2024-01-01'
    """).fetchone()
    con.close()
    assert revenue == 1100
    assert report_date == date(2024, 2, 15)
    assert source == "mops_monthly_history"
