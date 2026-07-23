from pathlib import Path

from scripts.build_universe import load_overrides, apply_overrides


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


def test_apply_overrides_no_overrides_leaves_unchanged():
    rows = [{"stock_id": "3081", "stock_name": "聯亞",
             "meta_sector": "晶圓代工", "sub_sector": "IC製造", "note": ""}]
    unmatched = apply_overrides(rows, {})
    assert unmatched == []
    assert rows[0]["meta_sector"] == "晶圓代工"
