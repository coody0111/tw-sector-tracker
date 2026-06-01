import pandas as pd
from processors.changes import detect_changes

def _make_df(rows):
    return pd.DataFrame(rows, columns=["date", "sector_type", "sector_name",
                                        "sector_code", "stock_id", "stock_name"])

def test_detect_added_stock():
    yesterday = _make_df([
        ["2026-05-28", "concept", "AI", "", "2330", "台積電"],
    ])
    today = _make_df([
        ["2026-05-29", "concept", "AI", "", "2330", "台積電"],
        ["2026-05-29", "concept", "AI", "", "2317", "鴻海"],
    ])
    changes = detect_changes(today, yesterday, sector_type="concept", today_date="2026-05-29")
    added = [c for c in changes if c["action"] == "added"]
    assert len(added) == 1
    assert added[0]["stock_id"] == "2317"

def test_detect_removed_stock():
    yesterday = _make_df([
        ["2026-05-28", "concept", "AI", "", "2330", "台積電"],
        ["2026-05-28", "concept", "AI", "", "2317", "鴻海"],
    ])
    today = _make_df([
        ["2026-05-29", "concept", "AI", "", "2330", "台積電"],
    ])
    changes = detect_changes(today, yesterday, sector_type="concept", today_date="2026-05-29")
    removed = [c for c in changes if c["action"] == "removed"]
    assert len(removed) == 1
    assert removed[0]["stock_id"] == "2317"

def test_no_changes_when_same():
    yesterday = _make_df([["2026-05-28", "concept", "AI", "", "2330", "台積電"]])
    today = _make_df([["2026-05-29", "concept", "AI", "", "2330", "台積電"]])
    changes = detect_changes(today, yesterday, sector_type="concept", today_date="2026-05-29")
    assert changes == []

def test_empty_yesterday_returns_no_changes():
    yesterday = pd.DataFrame()
    today = _make_df([["2026-05-29", "concept", "AI", "", "2330", "台積電"]])
    changes = detect_changes(today, yesterday, sector_type="concept", today_date="2026-05-29")
    assert changes == []
