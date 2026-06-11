# Rhapsody Architecture and Current State

Last reviewed: 2026-06-10

## 1. Executive Summary

Rhapsody is a production-oriented FastAPI backend for a Telegram-native AI operating system for teams. Its purpose is to turn meetings, Telegram chats, documents, decisions, tasks, risks, and follow-ups into a tenant-isolated company memory that can answer questions with citations.

The repository is best described as a strong backend foundation and local/private deployment scaffold, not a complete end-user product yet. It already contains modular domain boundaries, async SQLAlchemy persistence, Alembic migrations, pgvector-ready memory chunks, AI provider routing, BYOK key encryption, RBAC helpers, audit logs, deterministic local AI fallbacks, Docker Compose infrastructure, a thin Celery worker boundary, a placeholder Next.js admin console, Helm skeletons, and a meaningful unit/integration test suite.

The biggest remaining gaps are production worker implementations, real Telegram webhook normalization and file-processing pipelines, full frontend workflows, production auth/SSO/session lifecycle, distributed rate limiting, production-grade vector retrieval, production observability, and enterprise deployment hardening.

## 2. What Is Done

### Backend foundation

- Modular FastAPI application factory in `app/main.py`.
- API v1 router in `app/api/router.py`.
- Route modules for health, workspaces, meetings, documents, files, memory, provider keys, tasks, decisions, audit, and Telegram ingestion.
- Async SQLAlchemy 2 session setup and model layer.
- PostgreSQL schema managed by Alembic.
- pgvector integration with `memory_chunks.embedding` as `Vector(256)`.
- Prometheus metrics mounted at `/metrics`.
- Optional Sentry initialization when `SENTRY_DSN` is configured.
- CORS, request ID middleware, and in-memory rate limiting middleware.

### Tenant and access model

- Organization and workspace records.
- User records with optional Telegram user mapping.
- Workspace membership with role assignments.
- Role/permission model for workspace-level access checks.
- Service API key authentication via `X-API-Key`.
- JWT creation and verification primitives for future user-facing auth.
- Route-level permission checks for sensitive workspace operations.

### Domain capabilities

- Telegram event ingestion for normalized event payloads.
- Telegram message importance classification into normal, decision, task, risk, and explicit query categories.
- Telegram webhook secret verification helper.
- Telegram file download URL helper.
- Meeting ingestion from transcript or queued media reference.
- Deterministic/rule-based meeting intelligence extraction for summaries, decisions, tasks, risks, and follow-up text.
- Document ingestion with text chunking into memory.
- Dependency-free document parsers for TXT, Markdown, CSV, DOCX, XLSX, and simple text-heavy PDFs.
- Task creation, listing, and status updates.
- Decision creation/listing and automatic memory indexing.
- Grounded memory Q&A with source citations.
- Deterministic local embeddings and deterministic local LLM fallback for offline development/testing.
- File upload/download presigned URL service for S3-compatible storage.
- Audit log recording for sensitive operations.
- BYOK provider key storage with Fernet encryption.

### AI/provider layer

- Provider abstraction via `LLMProvider`.
- Deterministic local provider for development and tests.
- OpenAI-compatible provider support.
- OpenRouter-compatible routing via OpenAI-compatible base URL configuration.
- Anthropic provider support.
- Gemini provider support.
- Azure OpenAI provider support.
- BYOK provider key lookup and provider construction.
- AI request metadata tracking boundaries including provider, model, purpose, prompt hash, tokens, and latency fields.
- Prompt-context redaction helper for common sensitive values.

### Workers and scheduling boundaries

- Celery app configuration.
- Worker task contracts for:
  - `meetings.process_recording`
  - `documents.index_document`
  - `tasks.dispatch_due_reminders`
  - `retention.sweep_workspace`
- Worker pipeline planning helpers for Telegram file transfer and document indexing.
- Deterministic placeholders for transcription, weekly summaries, and meeting extraction.
- Scheduling helpers for task reminder candidates and workspace retention sweeps.

### Deployment and operations

- Dockerfile for backend runtime.
- Docker Compose stack with API, worker, Postgres + pgvector, Redis, MinIO, and MinIO bucket initialization.
- `.env.example` for local configuration.
- Alembic migrations:
  - `0001_initial.py` creates the core schema and vector index.
  - `0002_memory_embedding_vector.py` ensures pgvector extension and documents the no-op migration context.
- Backup/restore script primitives for Postgres and MinIO.
- PowerShell integration test runner for Docker Postgres/pgvector path.
- Helm chart skeleton for API and worker deployments with private-mode defaults and monitoring/Vault placeholders.

### Frontend

- Next.js + Tailwind project shell under `frontend/`.
- Admin landing page with placeholder modules for organizations, workspaces, members, tasks, decisions, memory search, provider keys, audit logs, and deployment settings.

### Tests

Current test coverage includes:

- AI provider routing and BYOK behavior.
- AI provider helper behavior.
- Document parsing.
- Document ingestion/chunking.
- File storage key and presigned URL helpers.
- Meeting intelligence extraction.
- Memory prompt grounding and deterministic ranking.
- Provider key encryption behavior.
- Rate limit key extraction.
- RBAC rules.
- Redaction helpers.
- API route contracts.
- Scheduling helpers.
- JWT security primitives.
- Telegram importance/webhook/file helper behavior.
- Worker pipeline planning helpers.
- Integration tests for demo flow and pgvector contract, gated by an integration database URL.

## 3. What Is Left To Do

### Product and API completeness

- Implement full Telegram Bot API webhook payload normalization instead of requiring already-normalized Telegram events.
- Add user-facing authentication endpoints, refresh/session lifecycle, passwordless login or OAuth, and SSO hooks.
- Add end-user APIs for richer memory search/browse, document management, meeting review, and notifications.
- Add richer route coverage for all operational workflows and negative/authorization cases.
- Add idempotency keys for ingestion endpoints that may receive retries.

### AI and intelligence

- Replace deterministic meeting extraction with structured LLM extraction guarded by validation and tests.
- Add production embedding providers and configurable embedding dimensions per deployment/model.
- Use pgvector-native nearest-neighbor query paths in `MemoryService` rather than application-side ranking over recent candidates.
- Add provider-specific retry, timeout, circuit breaker, and rate-limit policies.
- Expand token/cost accounting by provider and model.
- Add configurable prompt/response redaction policies and per-tenant AI data handling controls.
- Add evaluation datasets and regression tests for retrieval and meeting/task extraction quality.

### Workers and integrations

- Implement real STT for audio/video recordings, likely through Whisper/local Whisper/cloud STT depending on deployment mode.
- Implement Telegram file download to object storage.
- Implement production document parsing/OCR pipeline for large PDFs, images, scans, and mixed documents.
- Implement asynchronous embedding generation for documents, meetings, Telegram messages, and decisions.
- Implement reminder dispatch through Telegram/email/other configured channels.
- Implement weekly summaries and automated status collection.
- Implement retention sweep jobs and per-organization retention policies.

### Frontend/operator console

- Replace placeholder admin cards with real workflows.
- Add organization/workspace/member management screens.
- Add task dashboard.
- Add decision journal.
- Add audit log viewer.
- Add memory search and citation viewer.
- Add provider key management UI.
- Add integration setup screens for Telegram and storage/AI providers.
- Add authentication and authorization to the console.

### Security and enterprise readiness

- Add SSO/SAML/OIDC and SCIM provisioning.
- Add distributed Redis-backed rate limiting for multi-instance deployments.
- Decide and implement Postgres row-level security strategy or equivalent defense-in-depth controls.
- Add customer-managed encryption key support.
- Add secrets management integration for production and private deployments.
- Add security review checklist and threat model.
- Add audit/event export for SIEM.

### Deployment and operations

- Expand Helm chart with dependencies or documented external requirements for Postgres, Redis, MinIO/S3, Vault/secrets, ingress, TLS, and monitoring.
- Add Kubernetes probes, resource requests/limits, autoscaling, network policies, and secret templates.
- Automate backup/restore via CronJobs or managed backup tooling.
- Add disaster recovery runbooks and restore tests.
- Add OpenTelemetry tracing and richer structured logs.
- Add production dashboards and alert rules for API, worker, database, Redis, object storage, AI providers, and job queues.

## 4. Architecture Overview

```text
Telegram / Upload / Integrations
        |
        v
FastAPI API Layer
        |
        v
Domain Services
        |
        +--> Access / RBAC
        +--> Workspaces
        +--> Telegram Ingest
        +--> Meetings
        +--> Documents
        +--> Files
        +--> Tasks
        +--> Decisions
        +--> Memory
        +--> Provider Keys
        +--> Audit
        |
        v
Repositories / SQLAlchemy Async ORM
        |
        v
PostgreSQL + pgvector

Heavy jobs:
FastAPI -> Redis -> Celery workers -> STT / parsing / embeddings / LLM extraction / reminders / retention

Files:
FastAPI and workers -> S3-compatible object storage -> MinIO locally, R2/S3/private S3 in deployment

AI:
Domain services -> AI Router -> OpenAI / OpenRouter / Anthropic / Gemini / Azure OpenAI / local vLLM or Ollama / deterministic local fallback
```

The current backend is a modular monolith. This is an appropriate architecture for this stage because it keeps product iteration fast while preserving domain seams that can later be split into separate services if scaling or compliance requirements demand it.

## 5. Tech Stack

### Backend

- Python 3.10+
- FastAPI
- Pydantic v2
- SQLAlchemy 2 async
- Asyncpg
- Alembic
- PostgreSQL
- pgvector
- Redis
- Celery
- Boto3 for S3-compatible object storage
- Cryptography/Fernet for BYOK encryption
- Prometheus client
- Structlog and python-json-logger
- Optional Sentry SDK

### Frontend

- Next.js
- TypeScript
- Tailwind CSS

### Quality and testing

- Pytest
- Pytest-asyncio
- Pytest-cov
- Ruff
- Integration tests against Postgres + pgvector when configured

### Runtime and deployment

- Docker
- Docker Compose
- Kubernetes/Helm skeleton
- MinIO for local/private S3-compatible object storage

## 6. Source Layout

```text
app/
  main.py                  FastAPI application factory, middleware, routes, metrics
  api/
    deps.py                Shared FastAPI dependencies
    router.py              API v1 router composition
    routes/                HTTP route modules by domain
  core/
    config.py              Typed settings
    logging.py             Logging setup
    middleware.py          Request IDs and rate limiting
    rbac.py                Roles and permissions
    security.py            Service API key and JWT helpers
  db/
    base.py                SQLAlchemy declarative base
    models.py              Persistence models
    session.py             Async session factory/dependency
  repositories/
    workspace.py           Workspace/member data access helper
  schemas/
    *.py                   Pydantic request/response contracts
  services/
    *.py                   Domain services and AI/embedding/file helpers
  workers/
    celery_app.py          Celery app configuration
    tasks.py               Worker task contracts
docs/
  PROJECT.md               This architecture and status reference
frontend/
  app/                     Next.js app router shell
helm/
  rhapsody/                Kubernetes/Helm skeleton
migrations/
  versions/                Alembic migrations
scripts/                   Backup/restore and integration-test helper scripts
tests/                     Unit and integration tests
```

## 7. Runtime Flow By Use Case

### Workspace setup

1. API receives organization/workspace/user/member request.
2. `X-API-Key` service authentication is checked.
3. Workspace domain logic persists tenant records.
4. Sensitive operations are written to `audit_logs`.

### Telegram ingestion

1. API receives a normalized Telegram event.
2. Optional webhook secret verification can be used by the route/service boundary.
3. Telegram service creates or maps the sender user.
4. Message importance is classified.
5. Important messages are stored and indexed into memory chunks.

### Meeting ingestion

1. API receives transcript text or media reference.
2. Meeting record is created.
3. If transcript text exists, deterministic extraction produces summary, tasks, decisions, risks, and memory chunks.
4. If only media exists, the current behavior is to queue/store the record; full STT is still future work.

### Document ingestion

1. API receives document metadata and extracted text.
2. Document record is created.
3. Text is chunked with fixed-size overlapping chunks.
4. Chunks receive deterministic local embeddings and are stored as memory chunks.

### Memory Q&A

1. API receives a workspace-scoped question.
2. Access service checks `read_memory` permission for the actor.
3. Memory service retrieves recent candidate chunks.
4. Candidates are ranked using deterministic embedding similarity plus lexical overlap.
5. A grounded prompt is built with source snippets.
6. AI router chooses configured provider or deterministic local fallback.
7. Response returns answer text plus source metadata.

### BYOK provider routing

1. Admin stores an organization provider key through provider-key routes.
2. Key is encrypted with Fernet before persistence.
3. API responses never return plaintext secrets.
4. AI router can load the encrypted key, decrypt it inside service boundaries, and construct the provider for the request.

## 8. Domain Modules

### Workspaces and tenants

Owns organizations, workspaces, users, and workspace members. This is the central tenant boundary. Every business object should be scoped to a workspace or organization.

### Access/RBAC

Provides permission checks based on workspace role membership. Sensitive operational routes require service authentication plus an actor with the required workspace permission.

### Telegram

Handles normalized Telegram events, sender mapping, message classification, important-message persistence, and helper logic for webhook secrets and file URLs.

### Meetings

Stores meetings and deterministic transcript-derived intelligence. This module is ready for a structured LLM extraction implementation but does not yet contain production AI extraction or STT.

### Documents

Stores document metadata, parses supported document content where helpers are used, chunks extracted text, embeds chunks deterministically, and inserts memory chunks.

### Files

Generates S3-compatible presigned upload/download URLs and enforces workspace-scoped object key conventions.

### Tasks

Creates, lists, and updates tasks. Task mutations write audit logs.

### Decisions

Creates and lists decisions. New decisions are also indexed into memory so future answers can cite them.

### Memory

Builds grounded prompts from workspace memory chunks and routes generation through the AI router. Retrieval is currently application-side over recent candidates rather than fully pgvector-native.

### Provider Keys

Stores encrypted organization-level AI provider keys for BYOK mode. Plaintext keys are not exposed in API responses.

### Audit

Stores sensitive enterprise traceability events such as workspace changes, meeting/document ingestion, task changes, decision creation, and provider key changes.

## 9. API Surface

Base path: `/api/v1`

| Area | Endpoint | Status |
| --- | --- | --- |
| Health | `GET /health` | Implemented |
| Health | `GET /ready` | Implemented |
| Workspaces | `POST /workspaces/organizations` | Implemented |
| Workspaces | `POST /workspaces` | Implemented |
| Workspaces | `GET /workspaces/{workspace_id}` | Implemented |
| Workspaces | `POST /workspaces/users` | Implemented |
| Workspaces | `POST /workspaces/{workspace_id}/members` | Implemented |
| Workspaces | `GET /workspaces/{workspace_id}/members` | Implemented |
| Telegram | `POST /telegram/events` | Implemented for normalized events |
| Meetings | `POST /meetings/ingest` | Implemented with deterministic transcript processing |
| Documents | `POST /documents/ingest?actor_user_id=...` | Implemented |
| Files | `POST /files/upload-url?actor_user_id=...` | Implemented |
| Files | `POST /files/download-url?actor_user_id=...` | Implemented |
| Memory | `POST /memory/ask?actor_user_id=...` | Implemented with app-side ranking |
| Tasks | `POST /tasks?actor_user_id=...` | Implemented |
| Tasks | `GET /tasks?workspace_id=...&actor_user_id=...` | Implemented |
| Tasks | `PATCH /tasks/{task_id}/status?actor_user_id=...` | Implemented |
| Decisions | `POST /decisions?actor_user_id=...` | Implemented |
| Decisions | `GET /decisions?workspace_id=...&actor_user_id=...` | Implemented |
| Audit | `GET /audit?workspace_id=...&actor_user_id=...` | Implemented |
| Provider Keys | `PUT /provider-keys?actor_user_id=...` | Implemented |
| Provider Keys | `GET /provider-keys?organization_id=...&workspace_id=...&actor_user_id=...` | Implemented |
| Provider Keys | `DELETE /provider-keys?actor_user_id=...` | Implemented |
| Metrics | `GET /metrics` | Implemented |

## 10. Data Model

Main tables from `app/db/models.py`:

- `organizations`
- `workspaces`
- `users`
- `workspace_members`
- `telegram_chats`
- `meetings`
- `meeting_summaries`
- `messages`
- `documents`
- `memory_chunks`
- `tasks`
- `decisions`
- `risks`
- `ai_requests`
- `encrypted_api_keys`
- `audit_logs`

Important data rules:

- Workspace-scoped data must always be filtered by `workspace_id`.
- Organization-level secrets are scoped by `organization_id`.
- Provider keys are encrypted and never returned in plaintext.
- AI prompts/responses should not be stored raw in audit logs.
- `memory_chunks.embedding` is currently `Vector(256)`.
- Embedding dimensions are abstracted in `EmbeddingService` for future provider/model changes.

## 11. RBAC Model

Roles:

- `member`
- `team_lead`
- `manager`
- `admin`
- `enterprise_admin`

Permissions:

- `read_memory`
- `manage_tasks`
- `manage_decisions`
- `manage_workspace`
- `view_audit`

Operational routes generally require:

1. A valid service API key.
2. An `actor_user_id`.
3. Workspace membership with the required permission.

## 12. Deployment Modes

### Cloud mode

Rhapsody-operated infrastructure and Rhapsody-managed AI provider keys. Recommended stack includes managed Postgres with pgvector, Redis, S3/R2, and hosted API/worker runtime.

### BYOK mode

Same backend architecture as cloud mode, but customer AI provider keys are stored encrypted and routed per organization.

### Private/on-prem mode

Backend, Postgres + pgvector, Redis, MinIO/S3, worker processes, and AI/STT/embedding infrastructure run inside the customer environment. The current Helm chart defaults toward private mode but is still a skeleton.

## 13. Local Development

```bash
cp .env.example .env
docker compose up --build
```

API docs are available in non-production mode at:

```text
http://localhost:8000/docs
```

Python development path:

```bash
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -e ".[dev]"
pytest
uvicorn app.main:create_app --factory --reload
```

## 14. Testing and Quality

Recommended verification commands:

```bash
python -m pytest
python -m ruff check . --no-cache
python -c "from app.main import create_app; app=create_app(); print(app.title, len(app.routes))"
```

Integration tests are located under `tests/integration`. They require `RHAPSODY_INTEGRATION_DATABASE_URL` and are intended for a real Postgres + pgvector database. Use `scripts/run-integration-tests.ps1` for the Docker Postgres path.

## 15. Known Constraints and Risks

- The admin frontend is a placeholder shell, not a working console.
- Worker tasks mostly return queued/planning placeholders and do not perform production STT, parsing, embeddings, reminders, or retention work yet.
- Memory retrieval does not yet use DB-native pgvector nearest-neighbor search in the runtime Q&A path.
- Telegram ingestion expects normalized events; raw Telegram webhook update normalization is still needed.
- Rate limiting is in-memory and only safe for single-process/simple deployments.
- Helm is a starting point, not a complete production chart.
- Full user auth, SSO, SCIM, and production session lifecycle are not implemented.
- Production-grade observability and backup automation are not complete.

## 16. Recommended Next Milestones

1. Implement raw Telegram webhook normalization and file-to-storage worker path.
2. Implement production STT/document parsing/OCR worker pipelines.
3. Switch memory retrieval to pgvector-native nearest-neighbor querying with integration coverage.
4. Add structured LLM extraction for meetings with schema validation and deterministic fallback.
5. Build real admin console workflows for tenants, members, provider keys, audit, tasks, decisions, and memory search.
6. Add user auth/session lifecycle and SSO/OIDC foundations.
7. Replace in-memory rate limiting with Redis-backed distributed rate limiting.
8. Expand Helm chart and operational runbooks for production/private deployments.
9. Add OpenTelemetry tracing, dashboards, and alert rules.
10. Automate backups/restores and perform restore verification tests.

## 17. Completion Snapshot

| Area | Current State |
| --- | --- |
| Backend API foundation | Mostly complete for current domain scope |
| Database schema/migrations | Foundation complete; future migrations expected |
| Tenant/RBAC model | Implemented foundation |
| Telegram | Normalized ingestion implemented; raw webhook/file pipeline pending |
| Meetings | Transcript ingestion and deterministic extraction implemented; STT/LLM extraction pending |
| Documents | Ingestion/chunking/parsers implemented; production OCR/large-file pipeline pending |
| Memory Q&A | Grounded answers implemented; pgvector runtime query pending |
| AI routing | Multi-provider and BYOK foundation implemented |
| Workers | Contracts/placeholders implemented; production jobs pending |
| Security | Service auth/RBAC/encryption/audit foundation implemented; SSO/RLS/distributed limits pending |
| Frontend | Placeholder shell only |
| Docker Compose | Implemented for local stack |
| Helm | Skeleton only |
| Tests | Meaningful unit coverage plus gated integration tests |