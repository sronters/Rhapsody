from __future__ import annotations

from app.services.redaction import redact_text


def test_redact_text_masks_common_sensitive_values() -> None:
    text = "Email a@example.com token=abc123 phone +1 555 123 4567"

    redacted = redact_text(text)

    assert "a@example.com" not in redacted
    assert "abc123" not in redacted
    assert "+1 555 123 4567" not in redacted