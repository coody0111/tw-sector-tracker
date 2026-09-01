from datetime import date, datetime

import duckdb
import pytest

from scrapers.fundamentals import (
    FundamentalDataError,
    _fetch_json,
    normalize_financial_statement,
    normalize_monthly_revenue,
    save_financial_facts,
    save_monthly_revenue,
    save_official_fundamentals,
)


_TWSE_MONTHLY = [{
    "出表日期": "1150817",
    "資料年月": "11507",
    "公司代號": "1101",
    "公司名稱": "台泥",
    "產業別": "水泥工業",
    "營業收入-當月營收": "13,744,103",
    "營業收入-上月營收": "13,382,706",
    "營業收入-去年當月營收": "13,535,929",
    "營業收入-上月比較增減(%)": "2.7004",
    "營業收入-去年同月增減(%)": "1.5379",
    "累計營業收入-當月累計營收": "85,211,435",
    "累計營業收入-去年累計營收": "83,916,845",
    "累計營業收入-前期比較增減(%)": "1.5427",
    "備註": "-",
}]

_TPEX_MONTHLY = [{
    **_TWSE_MONTHLY[0],
    "公司代號": "1240",
    "公司名稱": "茂生農經",
    "產業別": "農業科技",
}]


def test_normalize_monthly_revenue_unifies_twse_and_tpex():
    seen = datetime(2026, 8, 31, 12, 0)
    twse = normalize_monthly_revenue(_TWSE_MONTHLY, "TWSE", fetched_at=seen)[0]
    tpex = normalize_monthly_revenue(_TPEX_MONTHLY, "TPEx", fetched_at=seen)[0]

    assert twse["stock_id"] == "1101"
    assert tpex["stock_id"] == "1240"
    assert twse["revenue_month"] == date(2026, 7, 1)
    assert twse["report_date"] == date(2026, 8, 17)
    assert twse["revenue"] == 13_744_103
    assert twse["reported_mom_pct"] == pytest.approx(2.7004)
    assert twse["note"] is None
    assert twse["source"] == "twse_openapi"
    assert tpex["source"] == "tpex_openapi"


def test_normalize_financial_statement_accepts_tpex_mixed_identifier_fields():
    rows = [{
        "Date": "1150831",
        "年度": "115",
        "季別": "2",
        "SecuritiesCompanyCode": "1240",
        "CompanyName": "茂生農經",
        "營業收入": "1,440,672.00",
        "本期淨利（淨損）": "(126,506.00)",
        "基本每股盈餘（元）": "2.85",
        "停業單位損益": "",
    }]

    facts = normalize_financial_statement(rows, "TPEx", "income", "ci")
    by_metric = {row["metric_key"]: row for row in facts}

    assert by_metric["revenue"]["period_end"] == date(2026, 6, 30)
    assert by_metric["revenue"]["value"] == 1_440_672
    assert by_metric["net_income"]["value"] == -126_506
    assert by_metric["eps"]["unit"] == "TWD/share"
    assert by_metric["eps"]["is_ytd"] is True
    assert len(facts) == 3


def test_normalize_balance_sheet_marks_snapshot_and_per_share_unit():
    rows = [{
        "出表日期": "1150831", "年度": "115", "季別": "2",
        "公司代號": "1101", "公司名稱": "台泥",
        "資產總計": "596016531.00", "每股參考淨值": "30.86",
        "待註銷股本股數（單位：股）": "1,000",
    }]
    facts = normalize_financial_statement(rows, "TWSE", "balance", "ci")
    by_metric = {row["metric_key"]: row for row in facts}

    assert by_metric["total_assets"]["is_ytd"] is False
    assert by_metric["book_value_per_share"]["unit"] == "TWD/share"
    assert by_metric["raw:待註銷股本股數（單位：股）"]["unit"] == "shares"


def test_fetch_json_rejects_html_like_json_list(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return ["<html>blocked</html>"]

    monkeypatch.setattr("scrapers.fundamentals.requests.get", lambda *a, **k: FakeResponse())
    with pytest.raises(FundamentalDataError):
        _fetch_json("https://example.invalid")


def _init_temp_db(tmp_path, monkeypatch):
    import screener.database as database

    db_path = str(tmp_path / "fundamentals.db")
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.init_db()
    return db_path


def test_monthly_revenue_upsert_is_idempotent_and_preserves_first_seen(tmp_path, monkeypatch):
    db_path = _init_temp_db(tmp_path, monkeypatch)
    first = datetime(2026, 8, 17, 18, 0)
    rows = normalize_monthly_revenue(_TWSE_MONTHLY, "TWSE", fetched_at=first)
    save_monthly_revenue(rows, db_path)

    second = datetime(2026, 8, 18, 18, 0)
    changed = normalize_monthly_revenue(_TWSE_MONTHLY, "TWSE", fetched_at=second)
    changed[0]["revenue"] = 13_744_104
    save_monthly_revenue(changed, db_path)

    con = duckdb.connect(db_path)
    row = con.execute(
        "SELECT COUNT(*), MIN(first_seen_at), MAX(fetched_at), MAX(revenue) FROM monthly_revenue"
    ).fetchone()
    con.close()
    assert row == (1, first, second, 13_744_104)


def test_monthly_growth_view_does_not_cross_missing_month(tmp_path, monkeypatch):
    db_path = _init_temp_db(tmp_path, monkeypatch)
    seen = datetime(2026, 8, 31, 12, 0)
    july = normalize_monthly_revenue(_TWSE_MONTHLY, "TWSE", fetched_at=seen)[0]
    may = {**july, "revenue_month": date(2026, 5, 1), "revenue": 10_000_000}
    save_monthly_revenue([may, july], db_path)

    con = duckdb.connect(db_path)
    mom = con.execute("""
        SELECT calculated_mom_pct FROM monthly_revenue_growth
        WHERE stock_id = '1101' AND revenue_month = DATE '2026-07-01'
    """).fetchone()[0]
    con.close()
    assert mom is None


def test_financial_growth_view_does_not_derive_q2_without_q1(tmp_path, monkeypatch):
    db_path = _init_temp_db(tmp_path, monkeypatch)
    q2 = normalize_financial_statement([{
        "出表日期": "1150831", "年度": "115", "季別": "2",
        "公司代號": "1101", "公司名稱": "台泥", "營業收入": "1000",
    }], "TWSE", "income", "ci")
    save_financial_facts(q2, db_path)

    con = duckdb.connect(db_path)
    single = con.execute("""
        SELECT single_quarter_value FROM financial_fact_growth
        WHERE stock_id = '1101' AND metric_key = 'revenue'
    """).fetchone()[0]
    con.close()
    assert single is None




def test_combined_save_rolls_back_monthly_when_financial_write_fails(tmp_path, monkeypatch):
    import scrapers.fundamentals as fundamentals

    db_path = _init_temp_db(tmp_path, monkeypatch)
    monthly = normalize_monthly_revenue(_TWSE_MONTHLY, "TWSE")

    def fail_financial_write(con, rows):
        raise RuntimeError("financial write failed")

    monkeypatch.setattr(fundamentals, "_upsert_financial_facts", fail_financial_write)
    with pytest.raises(RuntimeError, match="financial write failed"):
        save_official_fundamentals(monthly, [], db_path)

    con = duckdb.connect(db_path)
    count = con.execute("SELECT COUNT(*) FROM monthly_revenue").fetchone()[0]
    con.close()
    assert count == 0
