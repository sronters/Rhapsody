$ErrorActionPreference = "Stop"

if (-not $env:TEAMMIND_INTEGRATION_DATABASE_URL) {
  $env:TEAMMIND_INTEGRATION_DATABASE_URL = "postgresql+asyncpg://teammind:teammind@localhost:5432/teammind"
}

docker compose up -d postgres
python -m pytest tests/integration -m integration