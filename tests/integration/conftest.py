from __future__ import annotations

import os

import pytest

from app.core.config import get_settings


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: requires Docker Postgres + pgvector")
    for key in [
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "AZURE_OPENAI_API_KEY",
    ]:
        os.environ.pop(key, None)
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def integration_database_url() -> str:
    url = os.getenv("RHAPSODY_INTEGRATION_DATABASE_URL")
    if not url:
        pytest.skip(
            "Set RHAPSODY_INTEGRATION_DATABASE_URL to run Docker Postgres + pgvector "
            "integration tests."
        )
    if "postgresql" not in url:
        pytest.fail("Integration tests must use Postgres/pgvector, not SQLite.")
    return url