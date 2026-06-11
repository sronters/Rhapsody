from __future__ import annotations

from app.core.middleware import client_rate_limit_key


class _URL:
    path = "/api/v1/health"


class _Client:
    host = "127.0.0.1"


class _Request:
    headers = {"X-Forwarded-For": "10.0.0.1, 10.0.0.2"}
    client = _Client()
    url = _URL()


def test_client_rate_limit_key_prefers_forwarded_for() -> None:
    assert client_rate_limit_key(_Request()) == "10.0.0.1"