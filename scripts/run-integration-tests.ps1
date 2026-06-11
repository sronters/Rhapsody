$ErrorActionPreference = "Stop"

if (-not $env:RHAPSODY_INTEGRATION_DATABASE_URL) {
  $env:RHAPSODY_INTEGRATION_DATABASE_URL = "postgresql+asyncpg://rhapsody:rhapsody@localhost:5432/rhapsody"
}

docker compose up -d postgres
python -m pytest tests/integration -m integration