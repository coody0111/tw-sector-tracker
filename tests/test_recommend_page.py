import inspect

from export.recommend_generator import BACKTEST_REF, generate, render


def _card(sid, name, **kw):
    c = {"stock_id": sid, "stock_name": name, "meta_sector": "銅箔基板", "strategy": "突破策略", "type": "整理",
         "routes": "法人,外資", "n_routes": 2, "signal_date": "2026-09-24", "signal_close": 337.5, "close": 337.5,
         "change_pct": 9.93, "since_signal_pct": 0.0, "bias10": 12.0, "below_ma60": False, "alerts": [],
         "vr": 3.0, "rng20": 18.0, "ret20_prev": 5.0, "status": "有效", "day_n": 1, "top21": False}
    return {**c, **kw}


def _payload(**kw):
    p = {
        "trade_date": "2026-09-24",
        "header": {"above_ma20_pct": 0.61, "limit_up": 18, "limit_down": 1, "fail_rate": 0.28, "fail_n": 39},
        "taiex_above_ma20": True, "taiex_ma20_gap": 0.028,
        "new": [{"sector": "銅箔基板", "count": 1, "cards": [_card("6672", "騰輝<電子>-KY", top21=True)]}],
        "active": [_card("2383", "台光電", signal_date="2026-09-22", day_n=3, close=1185.0, signal_close=1150.0,
                         since_signal_pct=3.04, alerts=["族群獨漲"])],
        "invalid": [_card("6274", "台燿", signal_date="2026-09-22", day_n=3, close=288.5, signal_close=310.0,
                          since_signal_pct=-6.94, status="失效")],
        "leaders": {"sectors": [{"rank": 1, "sector": "銅箔基板", "n": 5, "ret21": 38.2, "from_high": -1.0,
                                 "rng5": 4.1, "status": "整理中"}],
                    "stocks": [{"rank": 1, "stock_id": "6274", "stock_name": "台燿", "meta_sector": "銅箔基板",
                                "ret21": 82.4, "from_high": -12.6, "rng5": 5.6, "vr5_20": None, "status": "拉回中"}]},
        "scorecard": {"突破策略": {"n": 25, "mean_r": 0.5, "win_rate": 0.3, "payoff": 4.0, "pf": 1.5, "open_n": 3,
                                   "unfilled_n": 2,
                                   "by_type": [{"type": "整理", "n": 25, "mean_r": 0.5, "pf": 1.5}],
                                   "by_month": [{"month": "2026-09", "n": 25, "win_rate": 0.3, "mean_r": -0.4, "pf": 0.7}]}},
        "scorecard_rows": {"突破策略": [
            {"stock_id": "3017", "stock_name": "奇鋐", "signal_date": "2026-09-18", "type": "續攻", "entry_price": 1265.0,
             "exit_date": "2026-09-25", "exit_price": 1189.0, "exit_reason": "停損", "ret": -0.063,
             "r_multiple": -1.05, "mfe": 0.012, "hold_days": 5},
            {"stock_id": "6274", "stock_name": "台燿", "signal_date": "2026-09-10", "type": "整理", "entry_price": None,
             "exit_date": None, "exit_price": None, "exit_reason": "買不到", "ret": None, "r_multiple": None,
             "mfe": None, "hold_days": None}]},
    }
    return {**p, **kw}


def test_page_has_all_sections_and_precomputed_order():
    html = render(_payload())
    for text in ("今日新訊號", "前幾天的推薦，仍有效", "已失效 1 檔", "近 21 天最強", "推薦成績單",
                 "近 21 天前 20 名", "在 MA20 之上", "61%", "28%"):
        assert text in html, text
    assert 'data-price="337.5"' in html
    assert ">493<" in html                         # 100 萬 × 1% ÷ (337.5 × 6%) = 493 股
    assert ">317.25<" in html                      # 停損價 337.5 × 0.94
    assert '<span class="chip-cons">拉回中</span>' in html and "族群獨漲" in html
    assert 'href="recommend.html" aria-current="page"' in html


def test_page_escapes_names_and_marks_lagging_backtest():
    html = render(_payload())
    assert "騰輝&lt;電子&gt;-KY" in html and "騰輝<電子>" not in html
    assert "（低於回測）" in html                  # 已出場 25 筆、勝率 30% > 回測 25%，但 PF 1.5 < 回測
    assert f"回測 {BACKTEST_REF['pf']:.2f}" in html
    assert "買不到" in html and "停損" in html


def test_empty_payload_shows_empty_states():
    html = render({"trade_date": "2026-10-22", "header": {}, "new": [], "active": [], "invalid": [],
                   "leaders": {"stocks": [], "sectors": []}, "scorecard": {}, "scorecard_rows": {}})
    assert "今天沒有新訊號" in html and "資料不足 22 個交易日" in html and "還沒有推薦紀錄" in html
    assert "加權指數" in html and "—" in html


def test_generate_writes_file(tmp_path):
    out = tmp_path / "recommend.html"
    generate(_payload(), output_path=str(out))
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_main_generates_and_pushes_recommend_page():
    import main
    src = inspect.getsource(main.run)
    assert "generate_recommend_html(recommend_payload)" in src
    assert '"docs/recommend.html"' in inspect.getsource(main._push_html)


def test_mobile_single_column_can_shrink_below_table_width():
    """1fr 的最小寬度是內容（表格）寬，375px 會橫向捲動；要 minmax(0,1fr)（bug-reports 2026-10-26）。"""
    from export.recommend_generator import PAGE_CSS
    assert "grid-template-columns:1fr" not in PAGE_CSS


def test_withdrawn_block_shows_reason():
    html = render(_payload(withdrawn=[{"stock_id": "3537", "stock_name": "晶相光", "reason": "法人買超占股本排名前 12%（需前 10%）"}],
                           shareholder_date="2026-10-23"))
    assert "開盤前撤回 1 檔" in html and "集保 2026-10-23 更新後不再符合" in html and "排名前 12%" in html
