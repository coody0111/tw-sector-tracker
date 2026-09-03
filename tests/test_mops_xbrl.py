import hashlib
import io
import logging
import zipfile
from datetime import datetime

import duckdb
import pytest
import scrapers.mops_xbrl as mops_xbrl

from scrapers.mops_xbrl import (
    ArchiveLink,
    DownloadedArchive,
    MopsXbrlError,
    parse_archive_links,
    parse_xbrl_instance,
    save_downloaded_archive,
)


def _xml_instance(revenue="1000000", extra_context="") -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl
  xmlns:xbrli="http://www.xbrl.org/2003/instance"
  xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
  xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
  xmlns:link="http://www.xbrl.org/2003/linkbase"
  xmlns:xlink="http://www.w3.org/1999/xlink"
  xmlns:tifrs-ci="https://example.tw/taxonomy/ifrs/ci/2020-06-30">
  <link:schemaRef xlink:type="simple" xlink:href="tifrs-ci.xsd"/>
  <xbrli:context id="YTD">
    <xbrli:entity><xbrli:identifier scheme="twse">2330</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-06-30</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="INSTANT">
    <xbrli:entity><xbrli:identifier scheme="twse">2330</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2024-06-30</xbrli:instant></xbrli:period>
  </xbrli:context>
  {extra_context}
  <xbrli:unit id="TWD"><xbrli:measure>iso4217:TWD</xbrli:measure></xbrli:unit>
  <xbrli:unit id="TWDPerShare"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:TWD</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>
  <tifrs-ci:NameOfReportingEntityOrOtherMeansOfIdentification contextRef="YTD">台積電</tifrs-ci:NameOfReportingEntityOrOtherMeansOfIdentification>
  <tifrs-ci:Revenue contextRef="YTD" unitRef="TWD" decimals="-3">{revenue}</tifrs-ci:Revenue>
  <tifrs-ci:ProfitLossAttributableToOwnersOfParent contextRef="YTD" unitRef="TWD" decimals="-3">250000</tifrs-ci:ProfitLossAttributableToOwnersOfParent>
  <tifrs-ci:BasicEarningsLossPerShare contextRef="YTD" unitRef="TWDPerShare" decimals="2">12.5</tifrs-ci:BasicEarningsLossPerShare>
  <tifrs-ci:Assets contextRef="INSTANT" unitRef="TWD" decimals="-3">5000000</tifrs-ci:Assets>
  <tifrs-ci:NetCashFlowsFromUsedInOperatingActivities contextRef="YTD" unitRef="TWD" decimals="-3">300000</tifrs-ci:NetCashFlowsFromUsedInOperatingActivities>
</xbrli:xbrl>""".encode()


def _downloaded(tmp_path, content, archive_sha, when):
    archive_path = tmp_path / f"{archive_sha}.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("reports/2330.xml", content)
    actual_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    return DownloadedArchive(
        link=ArchiveLink(
            year=2024,
            quarter=2,
            filename="tifrs-2024Q2.zip",
            url="https://mopsov.twse.com.tw/server-java/FileDownLoad?fileName=tifrs-2024Q2.zip",
        ),
        sha256=actual_sha,
        path=archive_path,
        byte_size=archive_path.stat().st_size,
        retrieved_at=when,
    )


def test_parse_archive_links_only_accepts_official_ifrs_zip():
    page = """
      <a href="/server-java/FileDownLoad?step=9&amp;fileName=tifrs-2024Q2.zip&amp;filePath=/ifrs/2024/">IFRS</a>
      <a href="/server-java/FileDownLoad?step=9&amp;fileName=tw-gaap-2012Q4.zip&amp;filePath=/xbrl/2012/">GAAP</a>
      <a href="https://evil.example/server-java/FileDownLoad?fileName=tifrs-2024Q3.zip">external</a>
    """
    links = parse_archive_links(page)
    assert [(link.year, link.quarter, link.filename) for link in links] == [
        (2024, 2, "tifrs-2024Q2.zip"),
    ]
    assert links[0].url.startswith("https://mopsov.twse.com.tw/")


def test_download_archive_retries_truncated_zip_before_caching(monkeypatch):
    valid_buffer = io.BytesIO()
    with zipfile.ZipFile(valid_buffer, "w") as archive:
        archive.writestr("reports/2330.xml", _xml_instance())
    responses = [b"PK-truncated", valid_buffer.getvalue()]

    class Response:
        def __init__(self, content):
            self.content = content
            self.headers = {
                "Content-Type": "application/zip",
                "Content-Length": str(len(content)),
            }

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=None):
            size = chunk_size or len(self.content) or 1
            for start in range(0, len(self.content), size):
                yield self.content[start:start + size]

    class Session:
        def __init__(self):
            self.calls = 0
            self.request_headers = []

        def get(self, *args, **kwargs):
            self.request_headers.append(kwargs["headers"])
            content = responses[self.calls]
            self.calls += 1
            return Response(content)

    session = Session()
    monkeypatch.setattr(mops_xbrl.time, "sleep", lambda seconds: None)
    link = ArchiveLink(
        2020, 3, "tifrs-2020Q3.zip",
        "https://mopsov.twse.com.tw/server-java/FileDownLoad?fileName=tifrs-2020Q3.zip",
    )

    content, _response = mops_xbrl._download_validated_zip(link, session=session)

    assert session.calls == 2
    assert content == valid_buffer.getvalue()
    assert "Cache-Control" not in session.request_headers[0]
    assert session.request_headers[1]["Cache-Control"] == "no-cache"
    assert session.request_headers[1]["Connection"] == "close"


def test_parse_xml_preserves_raw_facts_and_normalizes_units():
    parsed = parse_xbrl_instance(
        _xml_instance(), "reports/2330.xml", 2024, 2, "archive-sha", datetime(2024, 8, 14),
    )
    assert parsed is not None
    assert parsed.filing["stock_id"] == "2330"
    assert parsed.filing["stock_name"] == "台積電"
    by_metric = {row["metric_key"]: row for row in parsed.canonical_facts}
    assert by_metric["revenue"]["value"] == 1000
    assert by_metric["revenue"]["unit"] == "TWD_thousand"
    assert by_metric["eps"]["value"] == 12.5
    assert by_metric["eps"]["unit"] == "TWD/share"
    assert by_metric["total_assets"]["value"] == 5000
    assert by_metric["operating_cash_flow"]["value"] == 300
    revenue_raw = next(row for row in parsed.facts if row["local_name"] == "Revenue")
    assert revenue_raw["numeric_value"] == 1000000
    assert revenue_raw["decimals"] == "-3"  # decimals 是精度，不可當 10^-3 倍率


def test_inline_xbrl_applies_scale_and_sign():
    inline = b"""<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:tifrs-ci="https://example.tw/taxonomy/ifrs/ci/2020-06-30">
      <body>
        <xbrli:context id="YTD"><xbrli:entity><xbrli:identifier scheme="twse">2330</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-06-30</xbrli:endDate></xbrli:period></xbrli:context>
        <xbrli:unit id="TWD"><xbrli:measure>iso4217:TWD</xbrli:measure></xbrli:unit>
        <ix:nonFraction name="tifrs-ci:Revenue" contextRef="YTD" unitRef="TWD" decimals="-3" scale="3" sign="-">1,250</ix:nonFraction>
      </body>
    </html>"""
    parsed = parse_xbrl_instance(
        inline, "2330.xhtml", 2024, 2, "archive-sha", datetime(2024, 8, 14),
    )
    assert parsed is not None
    assert parsed.filing["content_format"] == "inline_xbrl"
    assert parsed.canonical_facts[0]["value"] == -1250


def test_inline_xbrl_accepts_html4_public_doctype_without_system_identifier():
    """MOPS 2021 Q2 includes an IE-saved HTML4 document that is not strict XML."""
    inline = b'''\xef\xbb\xbf<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">
    <HTML xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:tifrs-ci="https://example.tw/taxonomy/ifrs/ci/2020-06-30">
      <BODY>
        <xbrli:context id="YTD"><xbrli:entity><xbrli:identifier scheme="twse">1519</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startdate>2021-01-01</xbrli:startdate><xbrli:enddate>2021-06-30</xbrli:enddate></xbrli:period></xbrli:context>
        <xbrli:unit id="TWD"><xbrli:measure>iso4217:TWD</xbrli:measure></xbrli:unit>
        <ix:nonfraction name="tifrs-ci:Revenue" contextref="YTD" unitref="TWD" decimals="-3">1250000</ix:nonfraction>
      </BODY>
    </HTML>'''

    parsed = parse_xbrl_instance(
        inline, "tifrs-fr1-m1-ci-cr-1519-2021Q2.html", 2021, 2,
        "archive-sha", datetime(2021, 8, 14),
    )

    assert parsed is not None
    assert parsed.filing["stock_id"] == "1519"
    assert parsed.filing["content_format"] == "inline_xbrl"
    assert parsed.canonical_facts[0]["metric_key"] == "revenue"
    assert parsed.canonical_facts[0]["value"] == 1250


def test_inline_xbrl_recovers_ie_saved_unclosed_meta_tag():
    inline = b'''<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">
    <HTML xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:tifrs-ci="https://example.tw/taxonomy/ifrs/ci/2020-06-30">
      <HEAD><META http-equiv="Content-Type" content="text/html"></HEAD>
      <BODY>
        <xbrli:context id="YTD"><xbrli:entity><xbrli:identifier scheme="twse">1519</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startdate>2021-01-01</xbrli:startdate><xbrli:enddate>2021-06-30</xbrli:enddate></xbrli:period></xbrli:context>
        <xbrli:unit id="TWD"><xbrli:measure>iso4217:TWD</xbrli:measure></xbrli:unit>
        <ix:nonfraction name="tifrs-ci:Revenue" contextref="YTD" unitref="TWD" decimals="-3">1250000</ix:nonfraction>
      </BODY>
    </HTML>'''

    parsed = parse_xbrl_instance(
        inline, "tifrs-fr1-m1-ci-cr-1519-2021Q2.html", 2021, 2,
        "archive-sha", datetime(2021, 8, 14),
    )

    assert parsed is not None
    assert parsed.canonical_facts[0]["value"] == 1250


def test_wrong_duration_context_is_saved_raw_but_not_canonical():
    xml = _xml_instance().replace(b"2024-01-01", b"2024-04-01")
    parsed = parse_xbrl_instance(
        xml, "2330.xml", 2024, 2, "archive-sha", datetime(2024, 8, 14),
    )
    assert parsed is not None
    assert any(row["local_name"] == "Revenue" for row in parsed.facts)
    assert "revenue" not in {row["metric_key"] for row in parsed.canonical_facts}
    assert "eps" not in {row["metric_key"] for row in parsed.canonical_facts}


def test_cash_flow_reconciliation_concept_does_not_conflict_with_income_statement():
    xml = _xml_instance().replace(
        b'xmlns:tifrs-ci="https://example.tw/taxonomy/ifrs/ci/2020-06-30">',
        b'xmlns:tifrs-ci="https://example.tw/taxonomy/ifrs/ci/2020-06-30" '
        b'xmlns:ifrs="http://xbrl.iasb.org/taxonomy/2010-04-30/ifrs" '
        b'xmlns:scf="http://www.xbrl.org/tifrs/scf/2013-03-31">',
    ).replace(
        b"</xbrli:xbrl>",
        b'<ifrs:ProfitLossBeforeTax contextRef="YTD" unitRef="TWD" decimals="-3">-514600000</ifrs:ProfitLossBeforeTax>'
        b'<scf:ProfitLossBeforeTax contextRef="YTD" unitRef="TWD" decimals="-3">-515173000</scf:ProfitLossBeforeTax>'
        b"</xbrli:xbrl>",
    )
    parsed = parse_xbrl_instance(
        xml, "4712.xml", 2024, 2, "archive-sha", datetime(2024, 8, 14),
    )
    assert parsed is not None
    pretax = [row for row in parsed.canonical_facts if row["metric_key"] == "pretax_income"]
    assert len(pretax) == 1
    assert pretax[0]["value"] == -514600
    assert sum(row["local_name"] == "ProfitLossBeforeTax" for row in parsed.facts) == 2


def test_note_disclosure_concept_does_not_override_primary_statement():
    xml = _xml_instance().replace(
        b'xmlns:tifrs-ci="https://example.tw/taxonomy/ifrs/ci/2020-06-30">',
        b'xmlns:tifrs-ci="https://example.tw/taxonomy/ifrs/ci/2020-06-30" '
        b'xmlns:ifrs="http://xbrl.iasb.org/taxonomy/2010-04-30/ifrs" '
        b'xmlns:notes="http://www.xbrl.org/tifrs/notes/2013-03-31">',
    ).replace(
        b"</xbrli:xbrl>",
        b'<ifrs:RetainedEarnings contextRef="INSTANT" unitRef="TWD" decimals="-3">45665347000</ifrs:RetainedEarnings>'
        b'<notes:RetainedEarnings contextRef="INSTANT" unitRef="TWD" decimals="-3">20031074000</notes:RetainedEarnings>'
        b"</xbrli:xbrl>",
    )
    parsed = parse_xbrl_instance(
        xml, "2882.xml", 2024, 2, "archive-sha", datetime(2024, 8, 14),
    )
    assert parsed is not None
    retained = [row for row in parsed.canonical_facts if row["metric_key"] == "retained_earnings"]
    assert len(retained) == 1
    assert retained[0]["value"] == 45665347
    assert sum(row["local_name"] == "RetainedEarnings" for row in parsed.facts) == 2


def test_inconsistent_duplicate_fact_is_kept_raw_but_omitted_from_canonical():
    xml = _xml_instance().replace(
        b"</xbrli:xbrl>",
        b'<tifrs-ci:CashAndCashEquivalents contextRef="INSTANT" unitRef="TWD" decimals="-3">1064951000</tifrs-ci:CashAndCashEquivalents>'
        b'<tifrs-ci:CashAndCashEquivalents contextRef="INSTANT" unitRef="TWD" decimals="-3">0</tifrs-ci:CashAndCashEquivalents>'
        b"</xbrli:xbrl>",
    )
    parsed = parse_xbrl_instance(
        xml, "3356.xml", 2024, 2, "archive-sha", datetime(2024, 8, 14),
    )
    assert parsed is not None
    assert sum(row["local_name"] == "CashAndCashEquivalents" for row in parsed.facts) == 2
    assert "cash_and_equivalents" not in {
        row["metric_key"] for row in parsed.canonical_facts
    }


def test_backfill_skips_period_with_committed_archive(tmp_path, monkeypatch):
    db_path = tmp_path / "resume.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE xbrl_archives (
            accounting_standard VARCHAR,
            fiscal_year INTEGER,
            quarter INTEGER
        )
    """)
    con.execute("INSERT INTO xbrl_archives VALUES ('IFRS', 2013, 1)")
    con.close()
    links = [
        ArchiveLink(2013, quarter, f"tifrs-2013Q{quarter}.zip", f"https://mopsov.twse.com.tw/q{quarter}")
        for quarter in (1, 2)
    ]
    downloaded = []
    monkeypatch.setattr(mops_xbrl, "discover_ifrs_archives", lambda session: links)
    monkeypatch.setattr(
        mops_xbrl, "download_archive",
        lambda link, cache_root, session: downloaded.append(link) or link,
    )
    monkeypatch.setattr(
        mops_xbrl, "save_downloaded_archive",
        lambda archive, db_path: {
            "archives": 1, "filings": 1, "raw_facts": 1, "canonical_facts": 1,
        },
    )

    counts = mops_xbrl.backfill_mops_xbrl(
        start_year=2013,
        end_year=2013,
        db_path=str(db_path),
        cache_root=tmp_path,
        delay_seconds=0,
    )

    assert [(link.year, link.quarter) for link in downloaded] == [(2013, 2)]
    assert counts == {"archives": 1, "filings": 1, "raw_facts": 1, "canonical_facts": 1}


def test_missing_context_reference_fails_the_instance():
    xml = _xml_instance().replace(b'contextRef="YTD"', b'contextRef="MISSING"', 1)
    with pytest.raises(MopsXbrlError, match="不存在的 context"):
        parse_xbrl_instance(
            xml, "2330.xml", 2024, 2, "archive-sha", datetime(2024, 8, 14),
        )


def test_contextless_notes_fact_is_ignored_but_main_fact_still_parses():
    xml = _xml_instance().replace(
        b'xmlns:tifrs-ci="https://example.tw/taxonomy/ifrs/ci/2020-06-30">',
        b'xmlns:tifrs-ci="https://example.tw/taxonomy/ifrs/ci/2020-06-30" '
        b'xmlns:notes="http://www.xbrl.org/tifrs/notes/2020-06-30">',
    ).replace(
            b'</xbrli:unit>',
            b'</xbrli:unit><notes:Ratio contextRef="MISSING" unitRef="Pure">1</notes:Ratio>',
    )
    parsed = parse_xbrl_instance(
        xml, "2855.xml", 2021, 3, "archive-sha", datetime(2021, 11, 14),
    )
    assert parsed is not None
    assert parsed.filing["stock_id"] == "2330"
    assert len(parsed.facts) == 6


def test_one_broken_instance_does_not_fail_the_whole_archive(tmp_path, monkeypatch, caplog):
    """真實案例（MOPS 2855 2021Q3）：單一公司申報缺 context 定義，
    不該讓同一季 ZIP 裡其他上百家公司的資料連坐失敗。"""
    from screener import database

    db_path = tmp_path / "fundamentals.duckdb"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    database.init_db()

    good_xml = _xml_instance()
    broken_xml = _xml_instance().replace(b'contextRef="YTD"', b'contextRef="MISSING"', 1)
    archive_path = tmp_path / "mixed.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("reports/2330.xml", good_xml)
        archive.writestr("reports/9999.xml", broken_xml)
    downloaded = DownloadedArchive(
        link=ArchiveLink(
            year=2021, quarter=3, filename="tifrs-2021Q3.zip",
            url="https://mopsov.twse.com.tw/server-java/FileDownLoad?fileName=tifrs-2021Q3.zip",
        ),
        sha256=hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        path=archive_path,
        byte_size=archive_path.stat().st_size,
        retrieved_at=datetime(2024, 8, 14),
    )

    with caplog.at_level("WARNING"):
        counts = save_downloaded_archive(downloaded, db_path=str(db_path))

    assert counts["archives"] == 1
    assert counts["filings"] == 1
    assert any("9999.xml" in record.message for record in caplog.records)
    con = duckdb.connect(str(db_path))
    assert con.execute("SELECT COUNT(*) FROM xbrl_filings").fetchone()[0] == 1
    con.close()


def test_save_is_idempotent_and_new_sha_updates_current_projection(tmp_path, monkeypatch):
    from screener import database

    db_path = tmp_path / "fundamentals.duckdb"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    database.init_db()
    first = _downloaded(tmp_path, _xml_instance("1000000"), "first", datetime(2024, 8, 14))
    second = _downloaded(tmp_path, _xml_instance("2000000"), "second", datetime(2024, 8, 20))

    first_counts = save_downloaded_archive(first, db_path=str(db_path))
    repeat_counts = save_downloaded_archive(first, db_path=str(db_path))
    second_counts = save_downloaded_archive(second, db_path=str(db_path))

    assert first_counts["archives"] == 1
    assert repeat_counts == {"archives": 0, "filings": 0, "raw_facts": 0, "canonical_facts": 0}
    assert second_counts["archives"] == 1
    con = duckdb.connect(str(db_path))
    assert con.execute("SELECT COUNT(*) FROM xbrl_archives").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM xbrl_filings").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM xbrl_archive_entries").fetchone()[0] == 2
    current_revenue = con.execute("""
        SELECT value FROM xbrl_current_facts
        WHERE stock_id = '2330' AND metric_key = 'revenue'
    """).fetchone()[0]
    projected_revenue, report_date = con.execute("""
        SELECT value, report_date FROM financial_facts
        WHERE stock_id = '2330' AND metric_key = 'revenue'
    """).fetchone()
    con.close()
    assert current_revenue == 2000
    assert projected_revenue == 2000
    assert report_date is None  # 不可把 retrieved_at 冒充官方申報日


def test_new_archive_conflict_does_not_leave_previous_canonical_projection(tmp_path, monkeypatch):
    from screener import database

    db_path = tmp_path / "conflict-version.duckdb"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    database.init_db()
    first_xml = _xml_instance().replace(
        b"</xbrli:xbrl>",
        b'<tifrs-ci:CashAndCashEquivalents contextRef="INSTANT" unitRef="TWD" decimals="-3">1000000</tifrs-ci:CashAndCashEquivalents>'
        b"</xbrli:xbrl>",
    )
    conflicted_xml = _xml_instance().replace(
        b"</xbrli:xbrl>",
        b'<tifrs-ci:CashAndCashEquivalents contextRef="INSTANT" unitRef="TWD" decimals="-3">1000000</tifrs-ci:CashAndCashEquivalents>'
        b'<tifrs-ci:CashAndCashEquivalents contextRef="INSTANT" unitRef="TWD" decimals="-3">0</tifrs-ci:CashAndCashEquivalents>'
        b"</xbrli:xbrl>",
    )
    save_downloaded_archive(
        _downloaded(tmp_path, first_xml, "first", datetime(2024, 8, 14)),
        db_path=str(db_path),
    )
    save_downloaded_archive(
        _downloaded(tmp_path, conflicted_xml, "conflicted", datetime(2024, 8, 20)),
        db_path=str(db_path),
    )

    con = duckdb.connect(str(db_path))
    current_count = con.execute("""
        SELECT COUNT(*) FROM xbrl_current_facts
        WHERE stock_id = '2330' AND metric_key = 'cash_and_equivalents'
    """).fetchone()[0]
    projected_count = con.execute("""
        SELECT COUNT(*) FROM financial_facts
        WHERE stock_id = '2330' AND metric_key = 'cash_and_equivalents'
          AND source = 'mops_xbrl'
    """).fetchone()[0]
    con.close()
    assert current_count == 0
    assert projected_count == 0


def test_growth_view_keeps_eps_cumulative_and_uses_exact_quarter_end(tmp_path, monkeypatch):
    from screener import database

    db_path = tmp_path / "growth.duckdb"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    database.init_db()
    con = duckdb.connect(str(db_path))
    rows = [
        ("2330", "2023-06-30", 2023, 2, "eps", 10.0),
        ("2330", "2024-03-31", 2024, 1, "eps", 6.0),
        ("2330", "2024-06-30", 2024, 2, "eps", 12.5),
        ("2330", "2024-03-31", 2024, 1, "revenue", 100.0),
        ("2330", "2024-06-30", 2024, 2, "revenue", 250.0),
    ]
    con.executemany("""
        INSERT INTO financial_facts (
            stock_id, stock_name, exchange, period_end, fiscal_year, quarter,
            statement_type, industry_schema, metric_key, raw_name, value, unit,
            is_ytd, report_date, first_seen_at, fetched_at, source
        ) VALUES (?, '台積電', 'TWSE', ?, ?, ?, 'income', 'ci', ?, ?, ?,
                  CASE WHEN ? = 'eps' THEN 'TWD/share' ELSE 'TWD_thousand' END,
                  true, NULL, TIMESTAMP '2024-08-14', TIMESTAMP '2024-08-14', 'mops_xbrl')
    """, [(sid, period, year, quarter, metric, metric, value, metric) for sid, period, year, quarter, metric, value in rows])
    eps = con.execute("""
        SELECT single_quarter_value, calculated_qoq_pct, calculated_quarter_yoy_pct,
               calculated_ytd_yoy_pct
        FROM financial_fact_growth
        WHERE stock_id = '2330' AND period_end = DATE '2024-06-30' AND metric_key = 'eps'
    """).fetchone()
    revenue_single = con.execute("""
        SELECT single_quarter_value FROM financial_fact_growth
        WHERE stock_id = '2330' AND period_end = DATE '2024-06-30' AND metric_key = 'revenue'
    """).fetchone()[0]
    con.close()
    assert eps == (None, None, None, 25.0)
    assert revenue_single == 150.0  # 6/30 必須精確找到 3/31，不可誤算成 3/30


def _zip_bytes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("reports/2330.xml", _xml_instance())
    return buffer.getvalue()


class _StreamResponse:
    """可控的串流回應：headers 可自訂，內容分塊吐出。"""

    def __init__(self, content, content_length=None, chunks=None):
        self.content = content
        self._chunks = chunks
        self.headers = {"Content-Type": "application/zip"}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=None):
        if self._chunks is not None:
            yield from self._chunks
            return
        size = chunk_size or len(self.content) or 1
        for start in range(0, len(self.content), size):
            yield self.content[start:start + size]


def _link():
    return ArchiveLink(
        2022, 2, "tifrs-2022Q2.zip",
        "https://mopsov.twse.com.tw/server-java/FileDownLoad?fileName=tifrs-2022Q2.zip",
    )


def test_download_detects_short_transfer_against_content_length(monkeypatch):
    """回歸（2026-09-02 tifrs-2022Q2.zip）：官方宣告 Content-Length 但只吐一半就斷線。
    以前要整包讀完、等 _validate_zip 才發現；現在收完立刻比對長度就判定失敗。"""
    full = _zip_bytes()
    truncated = full[: len(full) // 2]

    class Session:
        def __init__(self):
            self.calls = 0

        def get(self, *args, **kwargs):
            assert kwargs["stream"] is True, "必須用串流下載，否則無法在讀取途中設限"
            self.calls += 1
            if self.calls == 1:
                return _StreamResponse(truncated, content_length=len(full))
            return _StreamResponse(full, content_length=len(full))

    monkeypatch.setattr(mops_xbrl.time, "sleep", lambda seconds: None)
    session = Session()
    content, _response = mops_xbrl._download_validated_zip(_link(), session=session)

    assert session.calls == 2, "短傳要觸發重試"
    assert content == full


def test_download_gives_up_when_exceeding_total_time_budget(monkeypatch):
    """回歸：伺服器以極慢速率持續吐資料時，requests 的 timeout 永遠不觸發
    （它只管兩次讀取之間的間隔），實際single次下載曾耗掉 3~8 小時。
    總時長上限要讓它在預算內就放棄，而不是讀完才發現是壞檔。"""
    clock = {"now": 0.0}
    monkeypatch.setattr(mops_xbrl.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(mops_xbrl.time, "sleep", lambda seconds: None)

    def slow_chunks():
        for _ in range(100):
            clock["now"] += 60.0        # 每塊耗一分鐘
            yield b"x" * 1024

    response = _StreamResponse(b"", content_length=None, chunks=slow_chunks())
    with pytest.raises(mops_xbrl.MopsXbrlError) as excinfo:
        mops_xbrl._read_streamed_body(response, "tifrs-2022Q2.zip")
    assert "秒上限" in str(excinfo.value)
    assert clock["now"] <= mops_xbrl._DOWNLOAD_MAX_SECONDS + 60.0


def test_download_gives_up_when_stalled(monkeypatch):
    """連線掛著但完全不吐資料時要放棄，不能無限等。"""
    clock = {"now": 0.0}
    monkeypatch.setattr(mops_xbrl.time, "monotonic", lambda: clock["now"])

    def stalled_chunks():
        yield b"x" * 1024
        for _ in range(10):
            clock["now"] += 30.0
            yield b""                   # keep-alive，沒有實際資料

    response = _StreamResponse(b"", content_length=None, chunks=stalled_chunks())
    with pytest.raises(mops_xbrl.MopsXbrlError) as excinfo:
        mops_xbrl._read_streamed_body(response, "tifrs-2022Q2.zip")
    assert "停滯" in str(excinfo.value)


def test_download_accepts_response_without_content_length():
    """官方有時不給 Content-Length，這時不能因為少了 header 就判定失敗。"""
    full = _zip_bytes()
    response = _StreamResponse(full, content_length=None)
    assert mops_xbrl._read_streamed_body(response, "tifrs-2022Q2.zip") == full


def test_recover_mode_logs_fact_counts_and_lxml_errors(caplog):
    """recover 模式必須留痕：記錄觸發檔案、contextRef 保留數與 lxml 錯誤，
    否則下次真的丟了 facts 也沒人知道（全庫 34,318 份只有 1 份會走到這裡）。"""
    malformed = (
        b'<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN">'
        b'<html xmlns:ifrs="http://www.ifrs.org/taxonomy">'
        b"<head><META charset=\"utf-8\"></head>"
        b"<body>"
        b'<ifrs:Revenue contextRef="c1" unitRef="u1">100</ifrs:Revenue>'
        b'<ifrs:ProfitLoss contextRef="c1" unitRef="u1">20</ifrs:ProfitLoss>'
        b"</body></html>"
    )
    with caplog.at_level(logging.WARNING, logger="scrapers.mops_xbrl"):
        root = mops_xbrl._xml_parse_content(malformed, "tifrs-fr1-m1-ci-cr-9999-2021Q2.html")

    kept = sum(1 for el in root.iter() if mops_xbrl._attribute(el, "contextRef"))
    assert kept == 2, "recover 後兩個 fact 都要留著"
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "recover 模式解析" in messages
    assert "9999" in messages, "log 要指出是哪份文件"
