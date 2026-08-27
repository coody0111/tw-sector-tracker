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
