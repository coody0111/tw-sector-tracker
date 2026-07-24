import pandas as pd
import pytest

import scripts.build_universe as bu
from scripts.build_universe import load_overrides, apply_overrides, load_existing_exchange


def test_load_overrides_missing_file_returns_empty(tmp_path):
    assert load_overrides(tmp_path / "nope.csv") == {}


def test_load_overrides_reads_rows(tmp_path):
    p = tmp_path / "ov.csv"
    p.write_text(
        "stock_id,meta_sector,sub_sector,source_note\n"
        "3081,光通訊,光通訊,財報狗題材:光通訊\n",
        encoding="utf-8-sig",
    )
    ov = load_overrides(p)
    assert ov["3081"]["meta_sector"] == "光通訊"
    assert ov["3081"]["sub_sector"] == "光通訊"
    assert ov["3081"]["source_note"] == "財報狗題材:光通訊"


def test_apply_overrides_replaces_meta_sub_and_clears_warning():
    rows = [{"stock_id": "3081", "stock_name": "聯亞",
             "meta_sector": "晶圓代工", "sub_sector": "IC製造",
             "note": "⚠️ 也在 光通訊"}]
    overrides = {"3081": {"meta_sector": "光通訊", "sub_sector": "光通訊",
                          "source_note": "財報狗題材:光通訊"}}
    unmatched = apply_overrides(rows, overrides)
    assert rows[0]["meta_sector"] == "光通訊"
    assert rows[0]["sub_sector"] == "光通訊"
    assert rows[0]["note"] == "手動校正:財報狗題材:光通訊"
    assert unmatched == []


def test_apply_overrides_empty_sub_keeps_auto_sub():
    rows = [{"stock_id": "1234", "stock_name": "X",
             "meta_sector": "其他電子", "sub_sector": "自動子族",
             "note": ""}]
    overrides = {"1234": {"meta_sector": "光通訊", "sub_sector": "",
                          "source_note": "手動"}}
    apply_overrides(rows, overrides)
    assert rows[0]["meta_sector"] == "光通訊"
    assert rows[0]["sub_sector"] == "自動子族"  # override sub 留空 → 保留自動值


def test_apply_overrides_unmatched_id_returns_warning():
    rows = [{"stock_id": "3081", "stock_name": "聯亞",
             "meta_sector": "晶圓代工", "sub_sector": "IC製造", "note": ""}]
    overrides = {"9999": {"meta_sector": "光通訊", "sub_sector": "光通訊",
                          "source_note": "x"}}
    unmatched = apply_overrides(rows, overrides)
    assert unmatched == ["9999"]
    assert rows[0]["meta_sector"] == "晶圓代工"  # 未命中不動其他股


def test_apply_overrides_empty_meta_keeps_auto_meta():
    rows = [{"stock_id": "3081", "stock_name": "聯亞",
             "meta_sector": "晶圓代工", "sub_sector": "IC製造", "note": ""}]
    overrides = {"3081": {"meta_sector": "", "sub_sector": "光通訊",
                          "source_note": "手動"}}
    apply_overrides(rows, overrides)
    assert rows[0]["meta_sector"] == "晶圓代工"  # override meta 留空 → 保留自動值
    assert rows[0]["sub_sector"] == "光通訊"


def test_apply_overrides_no_overrides_leaves_unchanged():
    rows = [{"stock_id": "3081", "stock_name": "聯亞",
             "meta_sector": "晶圓代工", "sub_sector": "IC製造", "note": ""}]
    unmatched = apply_overrides(rows, {})
    assert unmatched == []
    assert rows[0]["meta_sector"] == "晶圓代工"


def test_load_existing_exchange_missing_file(tmp_path):
    assert load_existing_exchange(tmp_path / "nope.csv") == {}


def test_load_existing_exchange_no_column(tmp_path):
    p = tmp_path / "u.csv"
    p.write_text("stock_id,stock_name,meta_sector,sub_sector,note\n"
                 "2330,台積電,晶圓代工,晶圓代工,\n", encoding="utf-8-sig")
    assert load_existing_exchange(p) == {}


def test_load_existing_exchange_reads_map(tmp_path):
    p = tmp_path / "u.csv"
    p.write_text("stock_id,stock_name,exchange,meta_sector,sub_sector,note\n"
                 "2330,台積電,TWSE,晶圓代工,晶圓代工,\n"
                 "3081,聯亞,TPEx,光通訊,光通訊,\n", encoding="utf-8-sig")
    assert load_existing_exchange(p) == {"2330": "TWSE", "3081": "TPEx"}


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8-sig")


def test_build_preserves_existing_exchange_column(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "data" / "sectors" / "industry_sectors.csv",
           "stock_id,stock_name,sector_name\n"
           "2330,台積電,晶圓代工\n"
           "3081,聯亞,光通訊\n")
    # 既有 universe 已帶 exchange 欄
    _write(tmp_path / "data" / "stock_universe.csv",
           "stock_id,stock_name,exchange,meta_sector,sub_sector,note\n"
           "2330,台積電,TWSE,晶圓代工,晶圓代工,\n"
           "3081,聯亞,TPEx,晶圓代工,IC製造,\n")

    bu.build()

    out = pd.read_csv(tmp_path / "data" / "stock_universe.csv",
                      dtype=str, encoding="utf-8-sig").fillna("")
    # 欄序含 exchange 且位置正確
    assert list(out.columns) == ["stock_id", "stock_name", "exchange",
                                 "meta_sector", "sub_sector", "note"]
    # 重建後 exchange 未遺失
    assert out[out["stock_id"] == "2330"].iloc[0]["exchange"] == "TWSE"
    assert out[out["stock_id"] == "3081"].iloc[0]["exchange"] == "TPEx"


def test_build_missing_input_raises_systemexit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        bu.build()


def test_build_override_removes_stock_from_ambiguous_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "data" / "sectors" / "industry_sectors.csv",
           "stock_id,stock_name,sector_name\n"
           "3081,聯亞,光通訊\n"
           "3081,聯亞,晶圓代工\n")
    _write(tmp_path / "data" / "sector_overrides.csv",
           "stock_id,meta_sector,sub_sector,source_note\n"
           "3081,光通訊,光通訊,財報狗題材:光通訊\n")

    bu.build()

    universe = pd.read_csv(tmp_path / "data" / "stock_universe.csv",
                           dtype=str, encoding="utf-8-sig")
    row = universe[universe["stock_id"] == "3081"].iloc[0]
    assert row["meta_sector"] == "光通訊"
    assert row["note"] == "手動校正:財報狗題材:光通訊"

    report = (tmp_path / "data" / "universe_build_report.txt").read_text(encoding="utf-8")
    assert "無爭議股票" in report  # 3081 被 override 後應從爭議清單移除 → 清單空
