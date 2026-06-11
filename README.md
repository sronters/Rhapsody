# Rhapsody

Rhapsody is a production-oriented FastAPI backend for a Telegram-native AI operating system for teams. It turns meetings, chats, documents, tasks, decisions, and risks into a tenant-isolated company memory with cited answers.

## What is included

- Modular FastAPI app with async SQLAlchemy 2.0.
- PostgreSQL schema with pgvector-ready memory chunks.
- Redis/Celery worker contracts for heavy processing.
- AI provider router for Cloud, BYOK, and Private deployment modes.
- Tenant isolation, API-key auth, RBAC helpers, audit logs, and sanitized AI request logging.
- Meeting, task, decision, document, and memory domain models.
- Docker Compose stack with API, worker, Postgres + pgvector, Redis, and MinIO.
- Alembic migrations and unit tests for core intelligence behavior.

See [docs/PROJECT.md](docs/PROJECT.md) for the full project reference: architecture,
tech stack, API surface, functions, data model, deployment modes, security model,
and roadmap.

## Quick Start

```bash
cp .env.example .env
docker compose up --build
```

API docs are available at `http://localhost:8000/docs`.

For the Telegram product flow, set `TELEGRAM_BOT_TOKEN` and one AI provider in `.env`.
Uploaded voice/audio/video meeting processing also needs `STT_MODE=openai` with
`OPENAI_API_KEY`, or `STT_MODE=local_whisper` with a local Whisper runtime installed.
Image/photo understanding needs `VISION_MODE=openai` with `OPENAI_API_KEY`, or
`VISION_MODE=gemini` with `GEMINI_API_KEY`.

Live Telegram group call listening is a separate MTProto/user-session service, not the
Bot API process. Enable it only with explicit group consent and real listener credentials:

```bash
LISTENER_ENABLED=true
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
TELEGRAM_USER_SESSION=...
STT_MODE=openai
docker compose --profile listener up --build
```

Then use `/listen`, `/stop_listen`, and `/live_status` in a configured Telegram group.
The listener will fail clearly if MTProto credentials, STT configuration, or runtime
dependencies are missing.

## Local Development

```bash
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -e ".[dev]"
pytest
uvicorn app.main:create_app --factory --reload
```

## Deployment Modes

- `cloud`: Rhapsody-owned AI keys and managed infrastructure.
- `byok`: customer-supplied encrypted provider keys routed per organization.
- `private`: on-prem stack using local vLLM/Ollama, local embeddings, MinIO, and private Postgres.

These modes are configuration-driven. Core business logic does not depend on a specific LLM provider.
