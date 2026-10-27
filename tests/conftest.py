import pytest


@pytest.fixture(autouse=True)
def _isolate_fundamentals_stamp(tmp_path, monkeypatch):
    """main._update_fundamentals_db 的「今天抓過」戳記一律寫到 tmp，不能寫進真的 data/
    （2026-10-27 Debugger：舊測試沒 patch，在 master 跑 pytest 會讓當天收盤跳過月營收／季報）。"""
    import main
    import recommend.data
    monkeypatch.setattr(main, "FUNDAMENTALS_STAMP_PATH", tmp_path / "fundamentals_last_update.txt")
    # 還原價事件表：測試不能讀到真的 data/corporate_events.csv（要用的測試自己傳 events_path）
    monkeypatch.setattr(recommend.data, "EVENTS_PATH", str(tmp_path / "no_events.csv"))
