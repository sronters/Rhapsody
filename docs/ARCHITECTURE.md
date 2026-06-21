# Rhapsody Architecture

Last reviewed: 2026-06-21

This is the only long-form Markdown note kept under `docs/`. Product and
operator documentation lives in `docs-site/`.

## Purpose

Rhapsody is a Telegram-first team memory system. It stores meetings, documents,
tasks, decisions, risks, live-call notes, and important chat context inside a
selected workspace, then answers questions from that workspace with sources.

The repository is a production-oriented backend and deployment scaffold. It is
ready for local development and Telegram testing, while full production rollout
still depends on real recorder-account validation, operator hardening, and a
complete admin console.

## Runtime Shape

```text
Telegram users
  |
  v
Telegram bot commands
  |
  v
FastAPI / domain services
  |
  +--> workspace and RBAC checks
  +--> meetings, documents, memory, tasks, decisions, audit
  +--> live-call orchestration
  +--> AI provider routing and STT
  |
  v
PostgreSQL + pgvector

Background jobs:
FastAPI/bot -> Redis -> Celery workers -> storage, STT, indexing, finalization

Files:
API/workers -> S3-compatible object storage -> MinIO locally

Live calls:
Bot command -> call_sessions -> listener service -> call_audio_chunks -> workers
```

## Main Components

- `app/api/` exposes FastAPI routes under `/api/v1`.
- `app/bot/` contains Telegram command handlers and product service logic.
- `app/calls/` owns durable live-call state and repositories.
- `app/db/` contains SQLAlchemy models and session setup.
- `app/i18n/` contains backend translation catalogs and locale helpers.
- `app/listener/` runs the MTProto/PyTgCalls listener outside the Bot API process.
- `app/services/` contains AI, memory, file, document, STT, and audio helpers.
- `app/workers/` contains Celery app setup and background task contracts.
- `migrations/` contains Alembic migrations.
- `frontend/` contains the Next.js admin shell.
- `docs-site/` contains the Mintlify documentation site.

## Implemented Product Surface

- Telegram setup and project selection in private chats and groups.
- Meeting and document ingestion into workspace-scoped memory.
- `/ask`, `/tasks`, `/decisions`, `/audit`, digest, attention, topics, and people commands.
- Language selection through `/language` and `/lang` for English and Russian.
- Service API-key auth with `X-API-Key`.
- PostgreSQL persistence with pgvector-ready memory chunks.
- AI routing for local deterministic mode, Ollama/local-compatible endpoints,
  OpenAI-compatible providers, OpenRouter, Anthropic, Gemini, Azure OpenAI, and
  encrypted BYOK provider keys.
- STT boundary with OpenAI STT and local Whisper support.
- Docker Compose stack for API, bot, worker, listener, Postgres, Redis, and MinIO.
- Oracle Always Free deployment scaffold with Caddy and dedicated Compose file.
- Live-call session, listener-account, audio-chunk, readiness, ops-status, and
  metrics foundations.

## Live Calls

Live-call recording is intentionally split from the Telegram Bot API process.
The bot creates and controls durable call sessions. The listener service joins
calls through configured recorder accounts, writes audio chunks to local spool
storage, and workers upload/transcribe/finalize those chunks.

Important tables:

- `call_sessions`
- `listener_accounts`
- `call_audio_chunks`
- `live_meeting_sessions` for compatibility with the Telegram command flow

Important endpoints:

- `GET /api/v1/calls/ready`
- `GET /api/v1/calls/ops-status`

Important tasks:

- `calls.upload_pending_chunks`
- `calls.transcribe_pending_chunks`
- `calls.finalize_meeting`
- `calls.recover_stale`

Real Telegram group-call validation with recorder accounts is still required
before treating live recording as production-ready.

## Verification

Use these checks after touching backend or docs:

```bash
python scripts/check_translations.py
python -m ruff check app tests migrations scripts
$env:PYTHONPATH=(Get-Location).Path; python -m pytest
cd frontend && npm install && npm run build
cd docs-site && npm install && npm run check
```

The explicit `PYTHONPATH` protects local test runs on this workstation from
importing a neighboring package named `app`.

## Documentation Layout

- `README.md` is the short English project entry point.
- `README.ru.md` is the short Russian project entry point.
- `DEMO.md` is the runnable local demo flow.
- `docs/ARCHITECTURE.md` is this maintainer architecture note.
- `docs-site/` is the full docs site and should not commit `node_modules/`.
