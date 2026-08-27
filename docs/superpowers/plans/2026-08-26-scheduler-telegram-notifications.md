# 排程通知系統（Telegram）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 `main.py` 能被排程（Windows Task Scheduler）定期執行，並把融資警示（🟢已驗證）跟收盤時的
「今日籌碼動向」（🟡純觀察）透過 Telegram Bot 推播到手機，全部依證據等級分流、不把未經證實的訊號
當成推薦。

**Architecture:** 新增 `processors/flow_watch.py` 算「今日籌碼動向」原始事實（不評分不排名）；
新增 `notifications/telegram.py` 負責實際發送 Telegram 訊息（timeout/錯誤處理/訊息分割/token 不外洩）；
`main.py` 新增 `--no-push`/`--summary-json` 參數，把執行摘要（含融資警示+今日籌碼動向）寫成 JSON；
新增 `scripts/run_scheduled.py` 當排程總控制器（交易日/時間窗判斷、執行鎖、通知去重、組訊息、呼叫
telegram 模組），`scripts/install_scheduler.ps1` 建立 Windows 排程工作。

**Tech Stack:** Python 3.11、`requests`（已是既有依賴）、`python-dotenv`（已是既有依賴）、DuckDB、
pytest、PowerShell（Windows Task Scheduler 安裝腳本）。

**Spec:** `docs/scheduler.md`（2026-08-26 更新版）

## Global Constraints

- **推播內容依證據等級分流**：融資警示（`margin_alerts`）是唯一回測驗證過的內容，文案一律稱
  「警示」不稱「訊號」或「推薦」；「今日籌碼動向」（`flow_watch`）純觀察、不做任何評分/排名邏輯，
  只陳述已發生的事實（買超金額/與近20日均量相比的異常倍數/成交值）
- **進貨分（`accumulation_score`）第一版不進入這個系統**——不要在任何地方接它
- **盤中（intraday）只監控融資警示 + 系統健康**，不监控 `flow_watch`；`flow_watch` 只在收盤（close）
  摘要出現
- **Token 安全規則**（`docs/scheduler.md` §9）：`.env` 不得加入 Git；Token 不得寫入 log；Telegram
  錯誤訊息不得包含完整 Token；發送失敗時的例外/log 只印錯誤類型或 HTTP 狀態碼，不印回應內文
- **`.env` 是機敏檔案，不要用 Edit/Write 直接改內容**——`.env.example` 可以改（沒有真實密鑰）
- 訊息內容數量上限：每則通知列 **Top 10** 檔（融資警示、今日籌碼動向皆同）
- Telegram 單則訊息長度上限 4096 字元（官方限制），超過需分割

---

## File Structure

- Create: `processors/flow_watch.py` — `get_flow_watch()`，今日籌碼動向純觀察查詢（獨立檔案，
  跟 `processors/performance.py` 裡其他「排名/評分」函式性質不同，特意分開避免未來被誤用成
  評分邏輯的一部分）
- Create: `notifications/__init__.py`（空檔，package marker）
- Create: `notifications/telegram.py` — `send_telegram_message()`
- Modify: `main.py` — 新增 `--no-push`/`--summary-json` CLI 參數；`run()` 新增 `push`/`summary_path`
  參數；新增 `_build_run_summary()` 純函式
- Create: `scripts/run_scheduled.py` — 排程總控制器（`intraday`/`close`/`test-notify` 三種模式）
- Create: `scripts/install_scheduler.ps1` — 建立 Windows 排程工作
- Modify: `.env.example` — 新增 `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`/`SITE_URL`
- Test: `tests/test_flow_watch.py`
- Test: `tests/test_telegram_notifier.py`
- Test: `tests/test_scheduled_runner.py`
- Test: `tests/test_main.py`（新增 `_build_run_summary()` 的測試）

---

### Task 1: `processors/flow_watch.py::get_flow_watch()` — 今日籌碼動向純觀察查詢

**Files:**
- Create: `processors/flow_watch.py`
- Test: `tests/test_flow_watch.py`

**Interfaces:**
- Produces: `get_flow_watch(universe_df: pd.DataFrame | None, db_path: str = "data/screener.db", trade_date: str | None = None, top_n: int = 10, avg_window: int = 20) -> list[dict]`，
  每筆 `{stock_id: str, stock_name: str, meta_sector: str, net_buy_lots: int, vs_avg20_ratio: float | None, turnover: int | None}`
  （欄位名稱對應 `docs/scheduler.md` §6 `flow_watch` JSON 範例）

- [ ] **Step 1: 寫失敗測試**

```python
import duckdb
import pandas as pd
from processors.flow_watch import get_flow_watch


def _make_flow_db(tmp_path, name, institutional_rows, price_rows):
    """institutional_rows: list of (stock_id,'YYYY-MM-DD',total_net)
    price_rows: list of (stock_id,'YYYY-MM-DD',close,volume)"""
    db = str(tmp_path / name)
    con = duckdb.connect(db)
    con.execute("CREATE TABLE institutional (stock_id VARCHAR, date DATE, total_net BIGINT)")
    con.executemany(
        "INSERT INTO institutional VALUES (?, ?, ?)",
        [(s, pd.to_datetime(d).date(), n) for (s, d, n) in institutional_rows],
    )
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, close DOUBLE, volume BIGINT)")
    con.executemany(
        "INSERT INTO daily_prices VALUES (?, ?, ?, ?)",
        [(s, pd.to_datetime(d).date(), c, v) for (s, d, c, v) in price_rows],
    )
    con.close()
    return db


def test_get_flow_watch_ranks_by_today_net_buy_and_computes_ratio_and_turnover(tmp_path):
    institutional_rows = [
        ("2330", "2026-07-01", 5000000), ("2330", "2026-06-30", 1000000),
        ("2317", "2026-07-01", 3000000), ("2317", "2026-06-30", 3000000),
    ]
    price_rows = [
        ("2330", "2026-07-01", 600.0, 20000000),
        ("2317", "2026-07-01", 100.0, 50000000),
    ]
    db = _make_flow_db(tmp_path, "flow.db", institutional_rows, price_rows)
    universe_df = pd.DataFrame([
        {"stock_id": "2330", "stock_name": "台積電", "meta_sector": "晶圓代工"},
        {"stock_id": "2317", "stock_name": "鴻海", "meta_sector": "電子代工"},
    ])

    result = get_flow_watch(universe_df, db_path=db, trade_date="2026-07-01", top_n=10, avg_window=20)

    assert [r["stock_id"] for r in result] == ["2330", "2317"]  # 2330買超較多排第一
    assert result[0]["stock_name"] == "台積電"
    assert result[0]["net_buy_lots"] == 5000  # 5,000,000股/1000
    assert result[0]["vs_avg20_ratio"] == 5.0  # 今日500萬 / 過去一筆(6/30)100萬均值 = 5.0
    assert result[0]["turnover"] == round(600.0 * 20000000)


def test_get_flow_watch_returns_empty_list_when_no_institutional_data_for_date(tmp_path):
    db = _make_flow_db(tmp_path, "empty.db", [], [])
    result = get_flow_watch(pd.DataFrame(columns=["stock_id", "stock_name", "meta_sector"]),
                             db_path=db, trade_date="2026-07-01")
    assert result == []


def test_get_flow_watch_handles_zero_history_average_as_none_ratio(tmp_path):
    """歷史均值查不到（新股或資料不足）時，vs_avg20_ratio 該是 None，不能除以零。"""
    institutional_rows = [("9999", "2026-07-01", 1000000)]  # 只有今天一筆，沒有歷史
    price_rows = [("9999", "2026-07-01", 50.0, 1000000)]
    db = _make_flow_db(tmp_path, "nohist.db", institutional_rows, price_rows)
    universe_df = pd.DataFrame([{"stock_id": "9999", "stock_name": "測試股", "meta_sector": "測試"}])

    result = get_flow_watch(universe_df, db_path=db, trade_date="2026-07-01")

    assert result[0]["vs_avg20_ratio"] is None
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_flow_watch.py -v`
Expected: FAIL（`processors/flow_watch.py` 還不存在，ModuleNotFoundError）

- [ ] **Step 3: 實作 `processors/flow_watch.py`**

```python
"""
今日籌碼動向 — 純觀察查詢，不做任何評分/排名邏輯以外的加權。
只回傳「今天發生了什麼」的事實（買超金額/與近期均量相比的異常倍數/成交值），
不宣稱任何預測力，跟籌碼頁🟡觀察用分頁、docs/scheduler.md §7.6 的定位一致。
2026-08-26 跟 Cody 用 grilling 確認：這個檔案刻意獨立於 processors/performance.py
之外，避免未來被誤接進任何評分/排名邏輯裡（那正是這個 session 花很多力氣在修正的問題）。
"""
import duckdb
import pandas as pd


def get_flow_watch(
    universe_df: pd.DataFrame | None,
    db_path: str = "data/screener.db",
    trade_date: str | None = None,
    top_n: int = 10,
    avg_window: int = 20,
) -> list[dict]:
    """
    今日籌碼動向：依 trade_date 當日 institutional.total_net（三大法人合計買超）由大到小
    排序取前 top_n（只看買超 > 0，不含賣超），每檔附上：
    - net_buy_lots：今日買超張數（total_net 股數 / 1000）
    - vs_avg20_ratio：今日 total_net 相對「過去 avg_window 個交易日 |total_net| 平均值」
      的倍數，四捨五入到小數 2 位；沒有足夠歷史資料時為 None（不做除以零）
    - turnover：今日成交值（close × volume，四捨五入到整數），查不到價格資料時為 None

    trade_date 為 None 時使用 institutional 表最新日期。回傳 [] 代表當天沒有買超資料。
    """
    con = duckdb.connect(db_path, read_only=True)
    if trade_date is None:
        row = con.execute("SELECT MAX(date) FROM institutional").fetchone()
        trade_date = str(row[0])[:10] if row and row[0] else None
    if not trade_date:
        con.close()
        return []

    today_df = con.execute(
        "SELECT stock_id, total_net FROM institutional "
        "WHERE date = ? AND total_net > 0 ORDER BY total_net DESC LIMIT ?",
        [trade_date, top_n],
    ).df()
    if today_df.empty:
        con.close()
        return []

    stock_ids = today_df["stock_id"].astype(str).tolist()
    placeholders = ",".join("?" for _ in stock_ids)

    hist_df = con.execute(
        f"""
        SELECT stock_id, AVG(ABS(total_net)) AS avg_abs_net
        FROM (
            SELECT stock_id, date, total_net
            FROM institutional
            WHERE stock_id IN ({placeholders}) AND date < ?
            QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) <= ?
        )
        GROUP BY stock_id
        """,
        [*stock_ids, trade_date, avg_window],
    ).df()

    price_df = con.execute(
        f"SELECT stock_id, close, volume FROM daily_prices WHERE date = ? AND stock_id IN ({placeholders})",
        [trade_date, *stock_ids],
    ).df()
    con.close()

    avg_map = dict(zip(hist_df["stock_id"].astype(str), hist_df["avg_abs_net"]))
    price_map = {
        str(row.stock_id): (row.close, row.volume) for row in price_df.itertuples()
    }
    name_map = {}
    if universe_df is not None and not universe_df.empty:
        name_map = universe_df.set_index(universe_df["stock_id"].astype(str))[
            ["stock_name", "meta_sector"]
        ].to_dict("index")

    results = []
    for row in today_df.itertuples():
        sid = str(row.stock_id)
        avg_abs = avg_map.get(sid)
        ratio = round(row.total_net / avg_abs, 2) if avg_abs and avg_abs > 0 else None
        close, volume = price_map.get(sid, (None, None))
        turnover = round(close * volume) if close is not None and volume is not None else None
        info = name_map.get(sid, {})
        results.append({
            "stock_id": sid,
            "stock_name": info.get("stock_name", ""),
            "meta_sector": info.get("meta_sector", ""),
            "net_buy_lots": round(row.total_net / 1000),
            "vs_avg20_ratio": ratio,
            "turnover": turnover,
        })
    return results
```

- [ ] **Step 4: 執行測試確認通過**

Run: `pytest tests/test_flow_watch.py -v`
Expected: PASS（3/3）

- [ ] **Step 5: Commit**

```bash
git add processors/flow_watch.py tests/test_flow_watch.py
git commit -m "feat(flow-watch): 新增今日籌碼動向純觀察查詢(不評分不排名)"
```

---

### Task 2: `notifications/telegram.py::send_telegram_message()` — Telegram 發送

**Files:**
- Create: `notifications/__init__.py`（空檔）
- Create: `notifications/telegram.py`
- Test: `tests/test_telegram_notifier.py`

**Interfaces:**
- Produces:
  - `class TelegramConfigError(Exception)`
  - `send_telegram_message(text: str, token: str | None = None, chat_id: str | None = None) -> bool`
    （`token`/`chat_id` 未傳入時讀環境變數 `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`；
    兩者皆未設定時拋 `TelegramConfigError`；回傳是否所有訊息片段都成功送達）

- [ ] **Step 1: 寫失敗測試**

```python
import logging
import pytest
import requests
from notifications.telegram import send_telegram_message, TelegramConfigError, _split_message


def test_send_telegram_message_raises_when_token_missing(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(TelegramConfigError):
        send_telegram_message("測試")


def test_send_telegram_message_posts_to_correct_url_and_returns_true_on_success(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200
        text = "ok"

    def fake_post(url, data, timeout):
        captured["url"] = url
        captured["data"] = data
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    result = send_telegram_message("台股收盤摘要", token="fake-token-123", chat_id="99999")

    assert result is True
    assert captured["url"] == "https://api.telegram.org/botfake-token-123/sendMessage"
    assert captured["data"] == {"chat_id": "99999", "text": "台股收盤摘要"}
    assert captured["timeout"] == 15


def test_send_telegram_message_returns_false_on_http_error_without_leaking_response_body(monkeypatch, caplog):
    class FakeResponse:
        status_code = 401
        text = "unauthorized: bot-token-abc-should-not-leak"

    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse())
    with caplog.at_level(logging.ERROR):
        result = send_telegram_message("測試", token="bot-token-abc", chat_id="1")

    assert result is False
    assert "bot-token-abc" not in caplog.text  # token 不外洩到 log
    assert "should-not-leak" not in caplog.text  # 回應內文也不外洩


def test_send_telegram_message_returns_false_on_timeout(monkeypatch, caplog):
    def raise_timeout(*a, **k):
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(requests, "post", raise_timeout)
    with caplog.at_level(logging.ERROR):
        result = send_telegram_message("測試", token="tok", chat_id="1")

    assert result is False
    assert "逾時" in caplog.text


def test_split_message_keeps_short_message_as_single_chunk():
    assert _split_message("短訊息") == ["短訊息"]


def test_split_message_splits_long_message_on_blank_lines():
    long_para = "A" * 3000
    text = f"{long_para}\n\n{long_para}\n\n{long_para}"
    chunks = _split_message(text, max_length=4000)
    assert len(chunks) >= 2
    assert all(len(c) <= 4000 for c in chunks)
    assert "".join(chunks).replace("\n\n", "") == text.replace("\n\n", "")
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_telegram_notifier.py -v`
Expected: FAIL（`notifications` 模組還不存在）

- [ ] **Step 3: 建立 `notifications/__init__.py`（空檔）與實作 `notifications/telegram.py`**

`notifications/__init__.py`：空檔即可。

`notifications/telegram.py`：

```python
"""
Telegram Bot 訊息發送。
責任：呼叫 Telegram sendMessage、處理 timeout/HTTP 錯誤、分割超長訊息、
絕不把 Bot Token 或 API 回應內文輸出到 log（見 docs/scheduler.md §9 安全規則）。
"""
import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"
_MAX_MESSAGE_LENGTH = 4000  # Telegram 官方上限 4096，留緩衝給分割
_TIMEOUT_SECONDS = 15


class TelegramConfigError(Exception):
    """TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未設定。"""


def _split_message(text: str, max_length: int = _MAX_MESSAGE_LENGTH) -> list[str]:
    """依空行分段切割過長訊息，避免切在句子中間；單段仍過長時強制切斷。"""
    if len(text) <= max_length:
        return [text]
    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > max_length:
            if current:
                chunks.append(current)
            current = para[:max_length] if len(para) > max_length else para
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def send_telegram_message(
    text: str, token: str | None = None, chat_id: str | None = None
) -> bool:
    """
    傳送訊息到 Telegram。token/chat_id 未傳入時讀環境變數
    TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID。兩者任一未設定時拋 TelegramConfigError
    （安全失敗，不嘗試發送）。回傳是否所有訊息片段都成功送達。
    """
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        raise TelegramConfigError("TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未設定")

    url = _API_BASE.format(token=token)
    all_ok = True
    for chunk in _split_message(text):
        try:
            resp = requests.post(url, data={"chat_id": chat_id, "text": chunk}, timeout=_TIMEOUT_SECONDS)
            if resp.status_code != 200:
                logger.error("Telegram 發送失敗：HTTP %d", resp.status_code)
                all_ok = False
        except requests.exceptions.Timeout:
            logger.error("Telegram 發送逾時（%d秒）", _TIMEOUT_SECONDS)
            all_ok = False
        except requests.exceptions.RequestException as exc:
            logger.error("Telegram 發送發生錯誤：%s", type(exc).__name__)
            all_ok = False
    return all_ok
```

- [ ] **Step 4: 執行測試確認通過**

Run: `pytest tests/test_telegram_notifier.py -v`
Expected: PASS（6/6）

- [ ] **Step 5: Commit**

```bash
git add notifications/ tests/test_telegram_notifier.py
git commit -m "feat(notifications): 新增telegram.py，處理發送/timeout/訊息分割/token不外洩"
```

---

### Task 3: `main.py` — `--no-push`/`--summary-json` 參數 + 執行摘要

**Files:**
- Modify: `main.py:518`（`run()` 函式簽名）、`main.py:706` 附近（新增 `flow_watch` 計算）、
  `main.py:990`（`_push_html` 呼叫改成有條件）、`main.py:995` 起（argparse 區塊新增參數）、
  `main.py:1095` 附近（CLI 呼叫 `run()` 傳新參數）
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: Task 1 的 `processors.flow_watch.get_flow_watch()`
- Produces: `_build_run_summary(trade_date, realtime, market_regime, margin_div, flow_watch, html_updated, git_pushed, started_at, finished_at, warnings) -> dict`
  （純函式，後續 Task 5 的 `scripts/run_scheduled.py` 會讀這個函式寫出的 JSON 檔案，
  欄位名稱見 `docs/scheduler.md` §6）

- [ ] **Step 1: 寫 `_build_run_summary()` 的失敗測試**

```python
from datetime import date, datetime
from main import _build_run_summary


def test_build_run_summary_close_mode_includes_flow_watch():
    started = datetime(2026, 8, 26, 15, 0, 0)
    finished = datetime(2026, 8, 26, 15, 1, 32)
    summary = _build_run_summary(
        trade_date=date(2026, 8, 26),
        realtime=False,
        market_regime={"tier": "小漲"},
        margin_div={"bearish": [{"stock_id": "2330", "stock_name": "台積電", "margin_pct": 5.2, "price_pct": -3.1, "days": 10}]},
        flow_watch=[{"stock_id": "2317", "stock_name": "鴻海", "net_buy_lots": 3200, "vs_avg20_ratio": 3.2, "turnover": 890000000}],
        html_updated=True, git_pushed=True,
        started_at=started, finished_at=finished, warnings=[],
    )
    assert summary["status"] == "success"
    assert summary["mode"] == "close"
    assert summary["trade_date"] == "2026-08-26"
    assert summary["market_regime"] == "小漲"
    assert summary["market_regime_label"] == "小漲"
    assert summary["margin_alerts"] == [{"stock_id": "2330", "stock_name": "台積電", "margin_pct": 5.2, "price_pct": -3.1, "days": 10}]
    assert summary["flow_watch"] == [{"stock_id": "2317", "stock_name": "鴻海", "net_buy_lots": 3200, "vs_avg20_ratio": 3.2, "turnover": 890000000}]
    assert summary["html_updated"] is True
    assert summary["git_pushed"] is True
    assert summary["duration_seconds"] == 92


def test_build_run_summary_intraday_mode_excludes_flow_watch():
    """盤中模式不帶flow_watch欄位——避免run_scheduled.py誤把觀察用內容當盤中通知素材。"""
    started = datetime(2026, 8, 26, 10, 30, 0)
    finished = datetime(2026, 8, 26, 10, 31, 25)
    summary = _build_run_summary(
        trade_date=date(2026, 8, 26), realtime=True,
        market_regime=None, margin_div={}, flow_watch=[],
        html_updated=False, git_pushed=False,
        started_at=started, finished_at=finished, warnings=["TPEx逾時"],
    )
    assert summary["mode"] == "intraday"
    assert "flow_watch" not in summary
    assert summary["margin_alerts"] == []
    assert summary["market_regime"] is None
    assert summary["warnings"] == ["TPEx逾時"]
```

加在 `tests/test_main.py` 現有內容之後（現有測試是 `_retry_fetch` 相關，不用動）。

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_main.py -v`
Expected: FAIL（`_build_run_summary` 還不存在，ImportError）

- [ ] **Step 3: 在 `main.py` 新增 `import json` 跟 `_build_run_summary()`**

在 `main.py` 檔案頂部 import 區塊（第 1-22 行附近）確認/新增：

```python
import json
```

在 `def _push_html(trade_date: date) -> None:`（第 245 行）之前新增：

```python
def _build_run_summary(
    trade_date: date,
    realtime: bool,
    market_regime: dict | None,
    margin_div: dict,
    flow_watch: list,
    html_updated: bool,
    git_pushed: bool,
    started_at,
    finished_at,
    warnings: list,
) -> dict:
    """組出 --summary-json 要寫的執行摘要（見 docs/scheduler.md §6）。純函式、不寫檔，
    方便單元測試。盤中模式（realtime=True）不帶 flow_watch 欄位——那是收盤摘要專屬的
    純觀察內容，2026-08-26 跟 Cody 確認盤中不監控這類沒有過半勝率的內容（見 §7.1）。
    market_regime 目前只有中文 tier 字串（如「小漲」），沒有另外的英文 enum，
    market_regime/market_regime_label 兩個欄位暫時填相同值。"""
    tier = (market_regime or {}).get("tier")
    summary = {
        "status": "success",
        "mode": "intraday" if realtime else "close",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "trade_date": trade_date.isoformat(),
        "market_regime": tier,
        "market_regime_label": tier,
        "margin_alerts": margin_div.get("bearish", []),
        "warnings": warnings,
        "html_updated": html_updated,
        "git_pushed": git_pushed,
        "duration_seconds": round((finished_at - started_at).total_seconds()),
    }
    if not realtime:
        summary["flow_watch"] = flow_watch
    return summary
```

- [ ] **Step 4: 執行測試確認通過**

Run: `pytest tests/test_main.py -v`
Expected: PASS（含既有 `_retry_fetch` 測試全部通過）

- [ ] **Step 5: `run()` 簽名新增 `push`/`summary_path` 參數（第 518 行）**

把：

```python
def run(trade_date: date = None, realtime: bool = False) -> None:
```

改成：

```python
def run(trade_date: date = None, realtime: bool = False, push: bool = True, summary_path: str = None) -> None:
```

在函式最開頭（`"""每日執行..."""` docstring 之後）加：

```python
    from datetime import datetime as _datetime
    _started_at = _datetime.now()
    _run_warnings: list = []
    # 以下 4 個變數只有在「if perf or meta_perf:」區塊（函式中段）真的跑到時才會被賦值，
    # 資料源全部失敗、perf/meta_perf 都是空的那天，區塊完全不會執行——先在這裡給預設值，
    # 讓 _build_run_summary() 不管有沒有跑到那個區塊都能安全讀到值，不用在使用處用
    # locals()/dir() 這種內省技巧去猜變數存不存在。
    market_regime = None
    margin_div = {}
    flow_watch = []
    chips_html_written = False
```

**已確認**：`main.py` 現有程式碼裡 `generate_chips_html(...)` 的回傳值有存進
`chips_html_written`（`html_updated` 欄位可以直接引用這個變數），但
`generate_index_html(trade_date, meta_perf, universe_df, ...)`（第 781 行附近）是裸呼叫、
**沒有接回傳值**，目前沒有對應的 `index_html_written` 變數可用——這次不新增（YAGNI，超出
這個 Task 範圍，屬於 index.html generator 自己的事），`html_updated` 欄位第一版只反映
chips.html 有沒有更新，Step 7 直接用 `html_updated=bool(chips_html_written)` 即可，不用
`index_html_written`。

- [ ] **Step 6: 計算 `flow_watch`（只在收盤模式，緊接在 `margin_div = get_margin_divergence(universe_df)...` 那行之後，第 706 行附近）**

```python
        margin_div = get_margin_divergence(universe_df) if universe_df is not None else {}
        if not realtime and universe_df is not None:
            from processors.flow_watch import get_flow_watch
            flow_watch = get_flow_watch(universe_df, trade_date=trade_date.isoformat())
```

（`flow_watch` 已經在函式開頭初始化成 `[]`，這裡只在條件成立時覆寫，不用重新宣告）

- [ ] **Step 7: `_push_html` 呼叫改成有條件（第 990 行）+ 寫出 summary JSON**

把：

```python
        _push_html(trade_date)

    logger.info("=== Done ===")
```

改成：

```python
        if push:
            _push_html(trade_date)
        elif summary_path:
            _run_warnings.append("--no-push：本次未執行git commit/push")

    if summary_path:
        _finished_at = _datetime.now()
        summary = _build_run_summary(
            trade_date=trade_date, realtime=realtime,
            market_regime=market_regime, margin_div=margin_div, flow_watch=flow_watch,
            html_updated=bool(chips_html_written),
            git_pushed=push,
            started_at=_started_at, finished_at=_finished_at, warnings=_run_warnings,
        )
        Path(summary_path).parent.mkdir(parents=True, exist_ok=True)
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        logger.info("執行摘要已寫入 %s", summary_path)

    logger.info("=== Done ===")
```

**注意給實作者**：`market_regime`/`margin_div`/`flow_watch`/`chips_html_written`
這 4 個變數在 Step 5 已經於函式開頭初始化預設值，這裡可以直接引用不會 `NameError`（即使
`if perf or meta_perf:` 區塊完全沒跑到、或跑到但某段又被自己的 `try/except` 吃掉例外，也一定
有預設值可用）。實作完 Step 5-7 之後，務必先跑一次
`python -c "import main; main.run(push=False, summary_path='scratch_summary.json')"`
（在有真實 `data/screener.db` 的環境）確認不會 crash、`scratch_summary.json` 內容合理，
再進下一步（這步驟你自己確認即可，不用等 Debugger，因為只是驗證程式碼能不能跑通，
不涉及推送/機敏資料）。

- [ ] **Step 8: argparse 新增 `--no-push`/`--summary-json`（第 995 行起的 `if __name__ == "__main__":` 區塊）**

在既有 `parser.add_argument("--update-sectors", ...)` 之後、任何位置皆可（建議跟其他無依賴的旗標放一起）新增：

```python
    parser.add_argument("--no-push", action="store_true",
                        help="產生結果但不執行 Git commit/push（排程盤中模式用）")
    parser.add_argument("--summary-json", type=str, default=None, metavar="PATH",
                        help="將本次執行摘要輸出為 JSON（排程系統讀取用）")
```

- [ ] **Step 9: CLI 呼叫 `run()` 時傳入新參數（第 1095 行附近，原本 `run(realtime=args.realtime)`）**

把：

```python
        run(realtime=args.realtime)
```

改成：

```python
        run(realtime=args.realtime, push=not args.no_push, summary_path=args.summary_json)
```

- [ ] **Step 10: 跑全部既有測試，確認沒有破壞既有行為**

Run: `pytest tests/test_main.py -v`
Expected: PASS 全部（新增的 2 個 + 既有 5 個 `_retry_fetch` 測試）

- [ ] **Step 11: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat(main): 新增--no-push/--summary-json，run()輸出執行摘要JSON"
```

---

### Task 4: `scripts/run_scheduled.py` 骨架 — 交易日/時間窗判斷 + 執行鎖 + 呼叫 main.py

**Files:**
- Create: `scripts/run_scheduled.py`
- Test: `tests/test_scheduled_runner.py`

**Interfaces:**
- Consumes: 無（這個 Task 先不接 Task 2 的 telegram 模組，先把骨架跟鎖定機制做對，Task 5 再接訊息）
- Produces:
  - `is_trading_day(d: "datetime.date") -> bool`（週一至週五為交易日；**不含國定假日行事曆**，
    這是刻意的 YAGNI 範圍限制，`docs/scheduler.md` 沒有要求行事曆功能，之後真的因為國定假日
    誤跑再補）
  - `is_market_hours(now: "datetime.datetime") -> bool`（週一至週五 09:00-13:30）
  - `class ExecutionLock`：`acquire() -> bool`（成功取得鎖回傳 True，鎖已被其他存活程序持有時
    回傳 False；鎖檔存的 PID 對應程序已不存在時視為過期鎖，自動接管）、
    `release() -> None`
  - `run_main_py(mode: str, summary_path: str) -> dict`（用 `subprocess.run` 呼叫
    `python main.py`，`mode="intraday"` 帶 `--realtime --no-push`，`mode="close"` 不帶這兩個旗標，
    兩種都帶 `--summary-json {summary_path}`；回傳
    `{"returncode": int, "stdout": str, "stderr": str}`）

- [ ] **Step 1: 寫失敗測試**

```python
import os
import sys
from datetime import date, datetime, time as dt_time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.run_scheduled import is_trading_day, is_market_hours, ExecutionLock, run_main_py


def test_is_trading_day_true_for_weekday():
    assert is_trading_day(date(2026, 8, 26)) is True  # 週三


def test_is_trading_day_false_for_weekend():
    assert is_trading_day(date(2026, 8, 29)) is False  # 週六
    assert is_trading_day(date(2026, 8, 30)) is False  # 週日


def test_is_market_hours_true_within_window():
    assert is_market_hours(datetime(2026, 8, 26, 10, 30)) is True
    assert is_market_hours(datetime(2026, 8, 26, 9, 0)) is True
    assert is_market_hours(datetime(2026, 8, 26, 13, 30)) is True


def test_is_market_hours_false_outside_window():
    assert is_market_hours(datetime(2026, 8, 26, 8, 59)) is False
    assert is_market_hours(datetime(2026, 8, 26, 13, 31)) is False
    assert is_market_hours(datetime(2026, 8, 29, 10, 30)) is False  # 週六


def test_execution_lock_acquire_and_release(tmp_path):
    lock_path = tmp_path / "scheduler.lock"
    lock = ExecutionLock(str(lock_path))
    assert lock.acquire() is True
    assert lock_path.exists()
    lock.release()
    assert not lock_path.exists()


def test_execution_lock_refuses_when_held_by_live_process(tmp_path):
    lock_path = tmp_path / "scheduler.lock"
    lock_path.write_text(str(os.getpid()))  # 用自己的PID模擬「還活著的持鎖程序」
    lock = ExecutionLock(str(lock_path))
    assert lock.acquire() is False


def test_execution_lock_auto_releases_stale_lock_from_dead_process(tmp_path):
    lock_path = tmp_path / "scheduler.lock"
    lock_path.write_text("999999999")  # 一個幾乎不可能存在的PID
    lock = ExecutionLock(str(lock_path))
    assert lock.acquire() is True


def test_run_main_py_intraday_mode_includes_realtime_and_no_push_flags(monkeypatch, tmp_path):
    captured = {}

    class FakeCompleted:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        return FakeCompleted()

    monkeypatch.setattr("subprocess.run", fake_run)
    summary_path = str(tmp_path / "summary.json")
    result = run_main_py("intraday", summary_path)

    assert "--realtime" in captured["cmd"]
    assert "--no-push" in captured["cmd"]
    assert "--summary-json" in captured["cmd"]
    assert summary_path in captured["cmd"]
    assert result["returncode"] == 0


def test_run_main_py_close_mode_excludes_realtime_and_no_push_flags(monkeypatch, tmp_path):
    captured = {}

    class FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda cmd, **k: captured.setdefault("cmd", cmd) or FakeCompleted())
    run_main_py("close", str(tmp_path / "summary.json"))

    assert "--realtime" not in captured["cmd"]
    assert "--no-push" not in captured["cmd"]
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_scheduled_runner.py -v`
Expected: FAIL（`scripts/run_scheduled.py` 還不存在）

- [ ] **Step 3: 實作 `scripts/run_scheduled.py`（骨架部分）**

```python
"""
排程總控制器。負責：判斷交易日/盤中時間窗、取得執行鎖、呼叫 main.py、
讀取執行摘要、決定要不要通知、寫 scheduler.log。
見 docs/scheduler.md 完整規格。

Usage:
    python scripts/run_scheduled.py intraday
    python scripts/run_scheduled.py close
    python scripts/run_scheduled.py test-notify
"""
import logging
import os
import subprocess
import sys
from datetime import date, datetime, time as dt_time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOCK_PATH = _PROJECT_ROOT / "logs" / "scheduler.lock"
_SUMMARY_PATH = _PROJECT_ROOT / "logs" / "latest_summary.json"
_LOG_PATH = _PROJECT_ROOT / "logs" / "scheduler.log"

logging.basicConfig(
    filename=str(_LOG_PATH), level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

_MARKET_OPEN = dt_time(9, 0)
_MARKET_CLOSE = dt_time(13, 30)


def is_trading_day(d: date) -> bool:
    """週一至週五為交易日。不含國定假日行事曆（YAGNI，docs/scheduler.md 沒有要求；
    國定假日誤跑的風險：main.py 抓不到當天資料會自然回退到最近交易日，不會產生錯誤資料，
    只是浪費一次排程，接受這個風險，不在第一版處理）。"""
    return d.weekday() < 5


def is_market_hours(now: datetime) -> bool:
    """週一至週五 09:00-13:30（含端點）。"""
    if not is_trading_day(now.date()):
        return False
    return _MARKET_OPEN <= now.time() <= _MARKET_CLOSE


class ExecutionLock:
    """檔案鎖：`logs/scheduler.lock` 存持鎖程序的 PID。程序異常結束後鎖必須能自動釋放——
    用 `os.kill(pid, 0)` 檢查該 PID 是否還活著，不活著就視為過期鎖，直接接管
    （見 docs/scheduler.md §8.1）。"""

    def __init__(self, lock_path: str = None):
        self.lock_path = Path(lock_path) if lock_path else _LOCK_PATH

    def _pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        except ValueError:
            return False
        return True

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        if self.lock_path.exists():
            try:
                held_pid = int(self.lock_path.read_text().strip())
            except (ValueError, OSError):
                held_pid = None
            if held_pid and self._pid_alive(held_pid):
                logger.warning("執行鎖被 PID %d 持有，本次直接結束", held_pid)
                return False
            logger.info("偵測到過期鎖（PID %s 已不存在），自動接管", held_pid)
        self.lock_path.write_text(str(os.getpid()))
        return True

    def release(self) -> None:
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass


def run_main_py(mode: str, summary_path: str, timeout: int = 900) -> dict:
    """呼叫 `python main.py`。intraday 模式帶 --realtime --no-push，close 模式不帶。
    兩種模式都帶 --summary-json。回傳 {returncode, stdout, stderr}。"""
    cmd = [sys.executable, str(_PROJECT_ROOT / "main.py")]
    if mode == "intraday":
        cmd += ["--realtime", "--no-push"]
    cmd += ["--summary-json", summary_path]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("intraday", "close", "test-notify"):
        print("Usage: python scripts/run_scheduled.py {intraday|close|test-notify}")
        sys.exit(1)
    # test-notify 模式跟鎖定/main.py 呼叫的接線在 Task 5 完成
    print(f"骨架階段：{sys.argv[1]} 模式的完整流程會在 Task 5 接上")
```

- [ ] **Step 4: 執行測試確認通過**

Run: `pytest tests/test_scheduled_runner.py -v`
Expected: PASS（8/8）

- [ ] **Step 5: Commit**

```bash
git add scripts/run_scheduled.py tests/test_scheduled_runner.py
git commit -m "feat(scheduler): run_scheduled.py骨架(交易日/時間窗判斷+執行鎖+呼叫main.py)"
```

---

### Task 5: `scripts/run_scheduled.py` 完整接線 — 通知去重 + 訊息組裝 + Telegram 發送

**Files:**
- Modify: `scripts/run_scheduled.py`
- Test: `tests/test_scheduled_runner.py`

**Interfaces:**
- Consumes: Task 1 `get_flow_watch()`（已經在 `main.py` 內部呼叫，這裡只讀 summary JSON 的
  `flow_watch` 欄位，不直接呼叫）、Task 2 `notifications.telegram.send_telegram_message()`、
  Task 3 `main.py` 寫出的 `latest_summary.json` 格式、Task 4 的 `is_trading_day`/`is_market_hours`/
  `ExecutionLock`/`run_main_py`
- Produces:
  - `load_summary(path: str) -> dict | None`
  - `compute_signal_hash(summary: dict) -> str`（只 hash 會影響通知內容的欄位：
    `margin_alerts` 的 stock_id 集合 + `market_regime`）
  - `load_notification_state(path: str) -> dict`、`save_notification_state(path: str, state: dict) -> None`
  - `should_notify_intraday(summary: dict, prev_state: dict) -> bool`
  - `compose_intraday_message(summary: dict) -> str`（格式對照 `docs/scheduler.md` §7.4）
  - `compose_close_message(summary: dict, site_url: str) -> str`（格式對照 §7.6）
  - `compose_failure_message(mode: str, error: str, duration_seconds: float) -> str`（格式對照 §7.5）
  - `main()`：完整流程（parse argv → 若非 test-notify 則檢查交易日/時間窗 → 取執行鎖 →
    呼叫 `run_main_py` → 讀 summary → 決定要不要通知 → 組訊息 → 呼叫
    `notifications.telegram.send_telegram_message()` → 更新 notification_state → 釋放鎖）

- [ ] **Step 1: 寫失敗測試**

```python
import json
from scripts.run_scheduled import (
    load_summary, compute_signal_hash, load_notification_state, save_notification_state,
    should_notify_intraday, compose_intraday_message, compose_close_message, compose_failure_message,
)


def test_load_summary_reads_json_file(tmp_path):
    p = tmp_path / "summary.json"
    p.write_text(json.dumps({"status": "success", "mode": "close"}), encoding="utf-8")
    assert load_summary(str(p)) == {"status": "success", "mode": "close"}


def test_load_summary_returns_none_when_file_missing(tmp_path):
    assert load_summary(str(tmp_path / "missing.json")) is None


def test_compute_signal_hash_stable_for_same_content():
    summary = {"margin_alerts": [{"stock_id": "2330"}], "market_regime": "小漲"}
    assert compute_signal_hash(summary) == compute_signal_hash(dict(summary))


def test_compute_signal_hash_changes_when_alerts_change():
    a = {"margin_alerts": [{"stock_id": "2330"}], "market_regime": "小漲"}
    b = {"margin_alerts": [{"stock_id": "2330"}, {"stock_id": "2317"}], "market_regime": "小漲"}
    assert compute_signal_hash(a) != compute_signal_hash(b)


def test_load_notification_state_returns_empty_dict_when_missing_or_corrupted(tmp_path):
    assert load_notification_state(str(tmp_path / "missing.json")) == {}
    corrupted = tmp_path / "bad.json"
    corrupted.write_text("{not valid json", encoding="utf-8")
    assert load_notification_state(str(corrupted)) == {}


def test_save_and_reload_notification_state_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    save_notification_state(str(p), {"last_signal_hash": "abc123"})
    assert load_notification_state(str(p)) == {"last_signal_hash": "abc123"}


def test_should_notify_intraday_true_when_hash_changed():
    summary = {"margin_alerts": [{"stock_id": "2330"}], "market_regime": "小漲"}
    prev_state = {"last_signal_hash": "different-hash"}
    assert should_notify_intraday(summary, prev_state) is True


def test_should_notify_intraday_false_when_hash_unchanged():
    summary = {"margin_alerts": [{"stock_id": "2330"}], "market_regime": "小漲"}
    prev_state = {"last_signal_hash": compute_signal_hash(summary)}
    assert should_notify_intraday(summary, prev_state) is False


def test_compose_intraday_message_lists_margin_alerts_only():
    summary = {
        "market_regime_label": "小漲",
        "margin_alerts": [
            {"stock_id": "2330", "stock_name": "台積電", "margin_pct": 5.2, "price_pct": -3.1, "days": 10},
        ],
        "warnings": [],
    }
    msg = compose_intraday_message(summary)
    assert "融資警示" in msg
    assert "2330 台積電" in msg
    assert "+5.2%" in msg
    assert "-3.1%" in msg
    assert "背離" in msg
    assert "進貨分" not in msg and "score" not in msg  # 盤中不該出現任何評分內容


def test_compose_close_message_includes_flow_watch_with_disclosure():
    summary = {
        "market_regime_label": "小漲",
        "margin_alerts": [],
        "flow_watch": [
            {"stock_id": "2317", "stock_name": "鴻海", "net_buy_lots": 3200, "vs_avg20_ratio": 3.2, "turnover": 890000000},
        ],
        "html_updated": True, "git_pushed": True,
    }
    msg = compose_close_message(summary, site_url="https://example.com/chips.html")
    assert "今日籌碼動向" in msg
    assert "純觀察" in msg or "非推薦" in msg  # 誠實揭露文字必須存在
    assert "2317 鴻海" in msg
    assert "3,200張" in msg or "3200張" in msg
    assert "3.2倍" in msg
    assert "https://example.com/chips.html" in msg


def test_compose_failure_message_includes_error_and_duration():
    msg = compose_failure_message("close", "TPEx API timeout", 130)
    assert "台股排程執行失敗" in msg
    assert "TPEx API timeout" in msg
    assert "2 分 10 秒" in msg or "130" in msg
```

加在 Task 4 已經寫好的測試檔案後面（同一個 `tests/test_scheduled_runner.py`）。

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_scheduled_runner.py -v`
Expected: FAIL（新函式都還不存在）

- [ ] **Step 3: 在 `scripts/run_scheduled.py` 補上剩餘實作，取代原本骨架階段的 `if __name__ == "__main__":`**

在既有 import 區塊補：

```python
import hashlib
import json
```

在 `run_main_py()` 之後、原本 `if __name__ == "__main__":` 之前加入：

```python
_STATE_PATH = _PROJECT_ROOT / "data" / "notification_state.json"


def load_summary(path: str) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.error("讀取 summary JSON 失敗：%s", path)
        return None


def compute_signal_hash(summary: dict) -> str:
    """只 hash 會影響通知內容的欄位（融資警示的股票清單 + 市場狀態），
    避免 duration_seconds/started_at 這類每次都不同的欄位讓 hash 永遠不一樣。"""
    alert_ids = sorted(a.get("stock_id", "") for a in summary.get("margin_alerts", []))
    payload = json.dumps(
        {"alert_ids": alert_ids, "market_regime": summary.get("market_regime")},
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_notification_state(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("notification_state.json 損毀，視為空狀態重建：%s", path)
        return {}


def save_notification_state(path: str, state: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def should_notify_intraday(summary: dict, prev_state: dict) -> bool:
    return compute_signal_hash(summary) != prev_state.get("last_signal_hash")


def _fmt_lots(n: int) -> str:
    return f"{n:,}張"


def compose_intraday_message(summary: dict) -> str:
    now_str = datetime.now().strftime("%H:%M")
    lines = [f"台股盤中更新｜{now_str}", "", f"市場狀態：{summary.get('market_regime_label', '未知')}"]
    alerts = summary.get("margin_alerts", [])
    lines.append(f"融資警示（新增）：{len(alerts)} 檔" if alerts else "融資警示：無")
    for a in alerts[:10]:
        lines.append("")
        lines.append(f"{a['stock_id']} {a['stock_name']}")
        lines.append(f"融資{a.get('days', '?')}日{a['margin_pct']:+.1f}%、股價{a['price_pct']:+.1f}%（背離）")
    lines.append("")
    warnings = summary.get("warnings", [])
    lines.append(f"資料異常：{'、'.join(warnings) if warnings else '無'}")
    return "\n".join(lines)


def compose_close_message(summary: dict, site_url: str) -> str:
    lines = [
        f"台股收盤摘要｜{summary.get('trade_date', '')}", "",
        f"市場狀態：{summary.get('market_regime_label', '未知')}",
    ]
    alerts = summary.get("margin_alerts", [])
    lines.append(f"融資警示：{len(alerts)} 檔" if alerts else "融資警示：無")
    for a in alerts[:10]:
        lines.append(f"  {a['stock_id']} {a['stock_name']} 融資{a.get('days', '?')}日{a['margin_pct']:+.1f}%")

    flow = summary.get("flow_watch", [])
    if flow:
        lines.append("")
        lines.append("── 今日籌碼動向（純觀察，非推薦）──")
        for f in flow[:10]:
            ratio_str = f"是近20日均量的{f['vs_avg20_ratio']}倍" if f.get("vs_avg20_ratio") is not None else "近期均量資料不足"
            turnover_str = f"成交值{f['turnover'] / 1e8:.1f}億" if f.get("turnover") else "成交值資料不足"
            lines.append("")
            lines.append(f"{f['stock_id']} {f['stock_name']}")
            lines.append(f"買超 {_fmt_lots(f['net_buy_lots'])}｜{ratio_str}｜{turnover_str}")
        lines.append("")
        lines.append("（僅陳述今日買超事實，不代表預測後續漲跌）")

    lines.append("")
    lines.append(f"資料完整性：{'正常' if not summary.get('warnings') else '、'.join(summary['warnings'])}")
    if summary.get("git_pushed"):
        lines.append(f"網站已更新：{site_url}")
    else:
        lines.append("網站未推送")
    return "\n".join(lines)


def compose_failure_message(mode: str, error: str, duration_seconds: float) -> str:
    mode_label = "盤中監控" if mode == "intraday" else "收盤更新"
    minutes, seconds = divmod(round(duration_seconds), 60)
    return "\n".join([
        f"台股排程執行失敗｜{datetime.now().strftime('%H:%M')}", "",
        f"模式：{mode_label}", f"錯誤：{error}", f"執行時間：{minutes} 分 {seconds} 秒", "",
        "已保留 logs/scheduler.log", "網站未推送",
    ])


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("intraday", "close", "test-notify"):
        print("Usage: python scripts/run_scheduled.py {intraday|close|test-notify}")
        return 1
    mode = sys.argv[1]

    from notifications.telegram import send_telegram_message, TelegramConfigError

    if mode == "test-notify":
        try:
            ok = send_telegram_message("台股排程通知測試 — 收到這則代表 Bot Token/Chat ID 設定正確。")
        except TelegramConfigError as exc:
            logger.error("test-notify 失敗：%s", exc)
            print(f"設定錯誤：{exc}")
            return 1
        print("已送出測試訊息" if ok else "發送失敗，詳見 logs/scheduler.log")
        return 0 if ok else 1

    now = datetime.now()
    if mode == "intraday" and not is_market_hours(now):
        logger.info("非盤中時間，%s 模式跳過", mode)
        return 0
    if mode == "close" and not is_trading_day(now.date()):
        logger.info("非交易日，close 模式跳過")
        return 0

    lock = ExecutionLock()
    if not lock.acquire():
        logger.info("執行鎖持有中，本次跳過")
        return 0

    try:
        started = datetime.now()
        result = run_main_py(mode, str(_SUMMARY_PATH))
        if result["returncode"] != 0:
            duration = (datetime.now() - started).total_seconds()
            error_msg = (result["stderr"] or "未知錯誤").strip().splitlines()[-1] if result["stderr"] else "main.py 執行失敗"
            try:
                send_telegram_message(compose_failure_message(mode, error_msg, duration))
            except TelegramConfigError:
                logger.error("main.py 執行失敗，且 Telegram 設定缺失，無法通知：%s", error_msg)
            logger.error("main.py 執行失敗（returncode=%d）：%s", result["returncode"], result["stderr"])
            return 1

        summary = load_summary(str(_SUMMARY_PATH))
        if summary is None:
            logger.error("讀不到 summary JSON，跳過通知")
            return 1

        if mode == "intraday":
            prev_state = load_notification_state(str(_STATE_PATH))
            if should_notify_intraday(summary, prev_state):
                try:
                    send_telegram_message(compose_intraday_message(summary))
                except TelegramConfigError as exc:
                    logger.error("Telegram 設定缺失，無法通知：%s", exc)
                save_notification_state(str(_STATE_PATH), {
                    "last_signal_hash": compute_signal_hash(summary),
                    "last_market_regime": summary.get("market_regime"),
                    "last_notified_at": datetime.now().isoformat(),
                })
            else:
                logger.info("盤中訊號與上次相同，不重複通知")
        else:  # close
            site_url = os.environ.get("SITE_URL", "https://coody0111.github.io/tw-sector-tracker/")
            try:
                send_telegram_message(compose_close_message(summary, site_url))
            except TelegramConfigError as exc:
                logger.error("Telegram 設定缺失，無法通知：%s", exc)

        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
```

**注意給實作者**：這一步是把 Task 4 骨架階段暫時放的 `print(...)` 佔位邏輯整段換掉，
`main()` 函式要放在檔案最後、`if __name__ == "__main__": sys.exit(main())` 之前，
取代 Task 4 Step 3 那段簡化版的 `if __name__ == "__main__":` 區塊。

- [ ] **Step 4: 執行測試確認通過**

Run: `pytest tests/test_scheduled_runner.py -v`
Expected: PASS（Task 4 的 8 個 + 這裡新增的 11 個，共 19 個）

- [ ] **Step 5: 跑全部相關測試**

Run: `pytest tests/test_flow_watch.py tests/test_telegram_notifier.py tests/test_scheduled_runner.py tests/test_main.py -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/run_scheduled.py tests/test_scheduled_runner.py
git commit -m "feat(scheduler): run_scheduled.py完整接線(通知去重+訊息組裝+telegram發送)"
```

---

### Task 6: `.env.example` 更新 + `scripts/install_scheduler.ps1`

**Files:**
- Modify: `.env.example`
- Create: `scripts/install_scheduler.ps1`

**Interfaces:**
- Consumes: 無（純設定檔+安裝腳本，不是 Python 程式碼，沒有函式介面）
- Produces: 無

- [ ] **Step 1: 更新 `.env.example`**

把現有：

```dotenv
FINMIND_TOKEN=your-finmind-api-token-here
```

改成：

```dotenv
FINMIND_TOKEN=your-finmind-api-token-here
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
TELEGRAM_CHAT_ID=your-telegram-chat-id
SITE_URL=https://coody0111.github.io/tw-sector-tracker/
```

- [ ] **Step 2: 建立 `scripts/install_scheduler.ps1`**

```powershell
<#
建立 Windows 工作排程器的兩個排程工作：TW-Sector-Intraday（盤中每15分鐘）、
TW-Sector-DailyClose（收盤 15:00）。見 docs/scheduler.md §10。

用法：以系統管理員權限開 PowerShell，執行：
    .\scripts\install_scheduler.ps1

只建立排程工作，不會立即執行 main.py，也不會動 Git。
#>

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonPath = (Get-Command python).Source
$RunnerPath = Join-Path $ProjectRoot "scripts\run_scheduled.py"

if (-not (Test-Path $RunnerPath)) {
    Write-Error "找不到 $RunnerPath，請確認在專案根目錄執行，且 scripts/run_scheduled.py 已存在"
    exit 1
}

# ── 盤中監控 ──────────────────────────────────────────────
$IntradayAction = New-ScheduledTaskAction -Execute $PythonPath `
    -Argument "`"$RunnerPath`" intraday" -WorkingDirectory $ProjectRoot

$IntradayTrigger = New-ScheduledTaskTrigger -Once -At "09:00" `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -RepetitionDuration (New-TimeSpan -Hours 4 -Minutes 45)

$IntradaySettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew -StartWhenAvailable

Register-ScheduledTask -TaskName "TW-Sector-Intraday" `
    -Action $IntradayAction -Trigger $IntradayTrigger -Settings $IntradaySettings `
    -Description "台股盤中籌碼監控，每15分鐘執行一次（09:00-13:45）" -Force

Write-Host "已建立 TW-Sector-Intraday"

# ── 收盤更新 ──────────────────────────────────────────────
$CloseAction = New-ScheduledTaskAction -Execute $PythonPath `
    -Argument "`"$RunnerPath`" close" -WorkingDirectory $ProjectRoot

$CloseTrigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "15:00"

$CloseSettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew -StartWhenAvailable

Register-ScheduledTask -TaskName "TW-Sector-DailyClose" `
    -Action $CloseAction -Trigger $CloseTrigger -Settings $CloseSettings `
    -Description "台股收盤每日更新，週一至週五 15:00 執行" -Force

Write-Host "已建立 TW-Sector-DailyClose"
Write-Host ""
Write-Host "驗收步驟（docs/scheduler.md §11.2）："
Write-Host "  1. python scripts/run_scheduled.py test-notify   （手機應收到測試訊息）"
Write-Host "  2. python scripts/run_scheduled.py intraday      （確認不產生 git commit）"
Write-Host "  3. Get-ScheduledTask -TaskName TW-Sector-* | Format-List"
```

- [ ] **Step 3: 手動驗收（不是自動化測試，`.ps1` 呼叫 `schtasks`/`Register-ScheduledTask` 需要真的
  在 Windows 上跑，不適合寫成 pytest；照 `docs/scheduler.md` §11.2 的驗收清單，由 Cody 自己執行）**

這步驟本身不是 code step，是給 Cody 的操作說明，留在這裡當作 Task 完成的判斷依據：

1. `.env` 填入真實的 `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`（跟 Task 1-5 一樣，這個檔案不會被
   Claude 動）
2. 以系統管理員權限執行 `.\scripts\install_scheduler.ps1`
3. `python scripts/run_scheduled.py test-notify` → 手機應收到測試訊息
4. `python scripts/run_scheduled.py intraday` → 確認 `git status` 沒有新的 commit
5. `Get-ScheduledTask -TaskName TW-Sector-*` → 確認兩個工作都已建立

- [ ] **Step 4: Commit**

```bash
git add .env.example scripts/install_scheduler.ps1
git commit -m "feat(scheduler): 新增install_scheduler.ps1 + .env.example補Telegram欄位"
```

---

## Self-Review 紀錄

- **Spec 覆蓋**：`docs/scheduler.md` §2(執行模式)→Task4/5、§5(main.py修改)→Task3、
  §6(執行摘要格式)→Task3、§7(通知規則，含2026-08-26調整的證據等級分流)→Task5、
  §8(防重複機制)→Task4/5、§9(環境變數)→Task6、§10(Windows排程)→Task6，全部對應到位。
  §11(測試要求)裡「Telegram成功發送/timeout/Token缺少安全失敗」→Task2測試涵蓋，
  「非交易日不執行/非盤中時間不執行/執行鎖生效」→Task4測試涵蓋，
  「訊號相同不重複通知/訊號改變才通知/--no-push不執行Git/main.py失敗時傳送錯誤通知/
  通知狀態檔損壞時能安全重建」→Task5測試涵蓋。§11.2人工驗收→Task6 Step3列出來給Cody。
- **Placeholder 掃描**：無 TBD/之後補——每個 Step 都有完整程式碼；Task 6 的手動驗收步驟
  刻意不是 code step（`.ps1` 需要真實 Windows 排程環境，不適合單元測試），已明確標注原因，
  不是遺漏。
- **型別一致性**：`get_flow_watch()` 回傳的欄位名稱（`net_buy_lots`/`vs_avg20_ratio`/`turnover`）
  在 Task 1 定義、Task 3 的 `_build_run_summary()` 直接透傳、Task 5 的 `compose_close_message()`
  讀取，三處欄位名稱一致；`margin_alerts` 欄位名稱（`stock_id`/`stock_name`/`margin_pct`/
  `price_pct`/`days`）沿用既有 `get_margin_divergence()` 回傳格式，三處一致；
  `send_telegram_message()`/`TelegramConfigError` 在 Task 2 定義、Task 5 直接 import 使用，
  簽名一致。

## 執行選項

Plan 已存到 `docs/superpowers/plans/2026-08-26-scheduler-telegram-notifications.md`。兩種執行方式：

1. **Subagent-Driven（建議）**——每個 Task 派一個全新 subagent 執行，Task 之間我 review，
   迭代快
2. **Inline Execution**——在這個 session 裡照 Task 順序批次執行，每個 Task 完成後停下來給你看

要用哪一種？
