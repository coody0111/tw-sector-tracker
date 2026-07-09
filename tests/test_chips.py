# tests/test_chips.py
from scrapers.chips import _parse_num, _parse_num_opt


def test_parse_num_returns_zero_on_failure():
    """_parse_num 用於買賣超等『0 是合法值』欄位：解析失敗回 0。"""
    assert _parse_num("1,234") == 1234
    assert _parse_num("-500") == -500
    assert _parse_num("--") == 0
    assert _parse_num("") == 0
    assert _parse_num(None) == 0


def test_parse_num_opt_returns_none_on_failure():
    """回歸（#2）：融資/融券『餘額』欄位用嚴格版——解析失敗回 None（不是 0）。
    舊版 _parse_num 回 0 會讓 margin_change = 0 - prev_margin 變成假的巨額『融資大減』。"""
    assert _parse_num_opt("1,234,567") == 1234567
    assert _parse_num_opt("-500") == -500
    # 各種格式跳掉的情況：不能回 0（否則造假訊號），要回 None 讓上層跳列
    assert _parse_num_opt("--") is None
    assert _parse_num_opt("") is None
    assert _parse_num_opt("N/A") is None
    assert _parse_num_opt(None) is None
    assert _parse_num_opt("1,234 (註)") is None  # 帶 footnote 標記


def test_margin_balance_parse_failure_would_not_fake_a_drop():
    """驗證修法的意圖：餘額解析失敗時，若沿用舊的『回 0 再相減』會產生假的融資大減。
    用 _parse_num_opt + 『任一 None 就跳列』的組合，確認不會算出 margin_change = -prev。"""
    # 模擬 TWSE margin 那段的處理邏輯（餘額欄格式跳掉）
    margin_bal = _parse_num_opt("--")        # 今日餘額格式跳掉
    prev_margin = _parse_num_opt("1,000,000")  # 昨日正常
    short_bal = _parse_num_opt("0")
    prev_short = _parse_num_opt("0")

    skip = None in (margin_bal, prev_margin, short_bal, prev_short)
    assert skip is True, "餘額解析失敗應該跳過整列"

    # 反面：若沿用舊寫法（回 0），會算出假的 -1,000,000 融資大減
    old_margin_bal = _parse_num("--")  # 舊版回 0
    fake_change = old_margin_bal - 1_000_000
    assert fake_change == -1_000_000  # 這就是舊版會寫進 DB 的假訊號（本測試證明它存在、故需跳列）
