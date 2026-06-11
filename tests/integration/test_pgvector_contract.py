from __future__ import annotations

import pytest


@pytest.mark.integration
def test_integration_database_must_be_postgres_pgvector(integration_database_url: str) -> None:
    assert integration_database_url.startswith("postgresql")