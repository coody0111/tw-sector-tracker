# tests/test_insider_holdings.py
from scrapers.insider_holdings import _parse_response, fetch_insider_holdings_monthly

_SAMPLE_HTML = """
<table class='noBorder'><tr><td class='reportCont' style='text-align:right !important;'>資料年月:11505</td></tr></table>
<table class='hasBorder'>
<TR class='odd'><TD style='text-align:left !important;'>董事本人</td><TD align='left'>王小明</td><TD style='text-align:right !important;'>0</td><TD style='text-align:right !important;'>1,000,000</td><TD style='text-align:right !important;'>0</td><TD>0.00%</td><TD style='text-align:right !important;'>0</td><TD style='text-align:right !important;'>0</td><TD>0.00%</td></TR>
<TR class='even'><TD style='text-align:left !important;'>獨立董事本人</td><TD align='left'>陳小華</td><TD style='text-align:right !important;'>0</td><TD style='text-align:right !important;'>0</td><TD style='text-align:right !important;'>0</td><TD>0.00%</td><TD style='text-align:right !important;'>0</td><TD style='text-align:right !important;'>0</td><TD>0.00%</td></TR>
<TR class='odd'><TD style='text-align:left !important;'>總經理本人</td><TD align='left'>林大方</td><TD style='text-align:right !important;'>0</td><TD style='text-align:right !important;'>500,000</td><TD style='text-align:right !important;'>200,000</td><TD>40.00%</td><TD style='text-align:right !important;'>0</td><TD style='text-align:right !important;'>0</td><TD>0.00%</td></TR>
<TR class='even'><TD style='text-align:left !important;'>大股東本人</td><TD align='left'>某投資公司</td><TD style='text-align:right !important;'>0</td><TD style='text-align:right !important;'>3,000,000</td><TD style='text-align:right !important;'>0</td><TD>0.00%</td><TD style='text-align:right !important;'>0</td><TD style='text-align:right !important;'>0</td><TD>0.00%</td></TR>
</table>
"""

_NO_DATA_HTML = "<center> <font color='red'><B>查無此公司資料</B></font></center>"


def test_parse_response_classifies_company_vs_major_holder():
    """董事/獨董/總經理歸『公司派』加總；大股東歸『大股東』加總，
    數字要對得起來（含關係人欄一起加，這個範例都是 0 不影響）。"""
    result = _parse_response(_SAMPLE_HTML)
    assert result is not None
    assert result["report_date"] == "2026-05-01"
    assert result["company_shares"] == 1_000_000 + 0 + 500_000   # 董事+獨董+總經理
    assert result["company_pledge_shares"] == 200_000            # 只有總經理有設質
    assert result["major_holder_shares"] == 3_000_000
    assert result["major_holder_pledge_shares"] == 0


def test_parse_response_returns_none_when_no_data():
    """查無資料時回傳 None，不能拋例外或誤判成 0。"""
    assert _parse_response(_NO_DATA_HTML) is None


def test_save_to_db_computes_month_over_month_change(tmp_path):
    from scrapers.insider_holdings import save_to_db
    import duckdb

    db_path = str(tmp_path / "t.db")
    con = duckdb.connect(db_path)
    con.execute("""
        CREATE TABLE insider_holdings (
            stock_id VARCHAR NOT NULL, report_date DATE NOT NULL,
            company_shares BIGINT, company_chg BIGINT, company_pledge_pct DOUBLE,
            major_holder_shares BIGINT, major_holder_chg BIGINT, major_holder_pledge_pct DOUBLE,
            PRIMARY KEY (stock_id, report_date)
        )
    """)
    con.close()

    # 第一個月：無前值可比
    rows1 = [{
        "stock_id": "2330", "report_date": "2026-04-01",
        "company_shares": 1_000_000, "company_pledge_shares": 0,
        "major_holder_shares": 3_000_000, "major_holder_pledge_shares": 0,
    }]
    save_to_db(rows1, db_path=db_path)

    # 第二個月：公司派持股增加、大股東減少
    rows2 = [{
        "stock_id": "2330", "report_date": "2026-05-01",
        "company_shares": 1_100_000, "company_pledge_shares": 0,
        "major_holder_shares": 2_500_000, "major_holder_pledge_shares": 0,
    }]
    n = save_to_db(rows2, db_path=db_path)
    assert n == 1

    con = duckdb.connect(db_path)
    row = con.execute(
        "SELECT company_chg, major_holder_chg FROM insider_holdings WHERE stock_id='2330' AND report_date='2026-05-01'"
    ).fetchone()
    first_row = con.execute(
        "SELECT company_chg, major_holder_chg FROM insider_holdings WHERE stock_id='2330' AND report_date='2026-04-01'"
    ).fetchone()
    con.close()

    assert row[0] == 100_000     # 1,100,000 - 1,000,000
    assert row[1] == -500_000    # 2,500,000 - 3,000,000
    assert first_row[0] is None  # 第一個月無前值，chg 應為 NULL
