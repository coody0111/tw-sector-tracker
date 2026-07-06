# tests/test_insider_holdings.py
from scrapers.insider_holdings import (
    _check_mops_response,
    _parse_response,
    fetch_insider_holdings_monthly,
    MOPSBlockedError,
)


class _FakeResp:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


_BLOCK_HTML = """
<html><body>
因為安全性考量，您所執行的頁面無法呈現。<BR>
FOR SECURITY REASONS, THIS PAGE CAN NOT BE ACCESSED.<BR>
</body></html>
"""

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


def test_to_int_non_numeric_returns_zero():
    """非數字 cell（如 '-'／'－'／'N/A'）視為 0、不拋例外（避免整支股票靜默消失）。"""
    from scrapers.insider_holdings import _to_int
    assert _to_int("-") == 0
    assert _to_int("－") == 0
    assert _to_int("N/A") == 0
    assert _to_int("") == 0
    assert _to_int("1,234,567") == 1_234_567


def test_parse_response_survives_dash_cell():
    """某數字 cell 是 '-' 時，該股仍能解析（該值當 0），不會整支回 None。"""
    html = _SAMPLE_HTML.replace("1,000,000", "-")  # 董事本人目前持股變成 '-'
    result = _parse_response(html)
    assert result is not None
    assert result["company_shares"] == 500_000   # 董事 0 + 獨董 0 + 總經理 500,000


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


def test_check_mops_response_detects_real_block_page():
    """2026-07-06 實測擋頁：307 + 資安考量文字，不能被誤判成查無資料。"""
    import pytest
    with pytest.raises(MOPSBlockedError):
        _check_mops_response(_FakeResp(307, _BLOCK_HTML))


def test_check_mops_response_allows_normal_200():
    """合法回應（含查無資料在內）都是 200，不該被誤判成擋頁。"""
    _check_mops_response(_FakeResp(200, _SAMPLE_HTML))       # 有資料
    _check_mops_response(_FakeResp(200, _NO_DATA_HTML))      # 查無資料，仍是合法回應


def test_fetch_insider_holdings_monthly_separates_blocked_from_no_data(monkeypatch):
    """被 MOPS 擋掉的股票要進 blocked_ids、不能跟『真的查無資料』混在一起算成同一種失敗。"""
    import scrapers.insider_holdings as ih

    def fake_fetch(stock_id):
        if stock_id == "1101":
            return {"report_date": "2026-05-01", "company_shares": 100, "company_pledge_shares": 0,
                     "major_holder_shares": 200, "major_holder_pledge_shares": 0}
        if stock_id == "1102":
            return None  # 真的查無資料（合法回應，只是沒有揭露）
        raise MOPSBlockedError("被擋")  # 1103：三次重試全部被擋

    monkeypatch.setattr(ih, "_fetch_one_stock", fake_fetch)
    monkeypatch.setattr(ih.time, "sleep", lambda *a, **k: None)  # 測試不要真的等退避時間

    results, blocked_ids = fetch_insider_holdings_monthly(["1101", "1102", "1103"], delay=0)

    assert [r["stock_id"] for r in results] == ["1101"]
    assert blocked_ids == ["1103"]
