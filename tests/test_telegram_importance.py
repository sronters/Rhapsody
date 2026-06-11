from __future__ import annotations

import pytest

from app.services.telegram import (
    TelegramWebhookVerificationError,
    build_telegram_file_download_url,
    classify_message_importance,
    verify_telegram_webhook_secret,
)


def test_classify_message_importance() -> None:
    assert classify_message_importance("We decided to choose option B") == "decision"
    assert classify_message_importance("I will finish the deck by Friday") == "task"
    assert classify_message_importance("This is blocked by the vendor") == "risk"
    assert classify_message_importance("hello team") == "normal"


def test_verify_telegram_webhook_secret_allows_matching_secret() -> None:
    verify_telegram_webhook_secret("expected", "expected")


def test_verify_telegram_webhook_secret_rejects_mismatch() -> None:
    with pytest.raises(TelegramWebhookVerificationError):
        verify_telegram_webhook_secret("expected", "wrong")


def test_verify_telegram_webhook_secret_is_noop_when_unconfigured() -> None:
    verify_telegram_webhook_secret(None, None)


def test_build_telegram_file_download_url() -> None:
    assert (
        build_telegram_file_download_url("token", "/documents/file.pdf")
        == "https://api.telegram.org/file/bottoken/documents/file.pdf"
    )
