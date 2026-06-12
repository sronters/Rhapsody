# Architecture

Rhapsody is built around a Telegram bot, a FastAPI backend, and a project-scoped
memory store. The local stack runs with Docker Compose.

## Main Components

### Telegram Bot Layer

The bot is the main product interface. It handles commands such as `/setup`,
`/new_project`, `/meeting`, `/document`, `/ask`, `/tasks`, `/decisions`, and
`/audit`.

The bot does not own the data model directly. It opens database sessions and
calls service methods that create workspaces, store memory, and enforce project
scope.

### FastAPI Backend

The API provides health/readiness endpoints and backend routes for workspaces,
documents, memory, tasks, decisions, audit logs, files, provider keys, and
Telegram ingestion helpers.

In the current review scope, the Telegram bot flow is the primary interface.

### PostgreSQL + pgvector

PostgreSQL stores organizations, users, workspaces, Telegram chat mappings,
meetings, documents, tasks, decisions, risks, memory chunks, and audit logs.

`pgvector` is available for vector-backed memory retrieval. Memory chunks are
always associated with a workspace id, and retrieval for `/ask` is filtered by
the selected workspace.

### Redis and Worker

Redis is used by the worker process. The worker exists for heavier background
jobs and local stack parity. The core Telegram command flow used in current
verification runs through the bot and database services.

### MinIO

MinIO provides local S3-compatible object storage. Document metadata is stored in
Postgres, while object-storage settings are configured through `S3_*`
environment variables.

### AI Provider Layer

The product AI client routes meeting extraction and question answering through
the configured provider. Current modes include providers such as Gemini, OpenAI,
OpenRouter, Anthropic, Ollama, and local-compatible endpoints depending on
configuration.

The bot should return a clean error if the configured provider fails or is
missing required credentials.

### STT Layer

Speech-to-text is separate from the LLM provider. Supported modes include
OpenAI STT and `local_whisper`.

For `STT_MODE=local_whisper`, the runtime uses `faster-whisper` and ffmpeg.
Telegram `.ogg`/`.oga` voice messages are converted before transcription. If STT
is not configured, audio/voice/video meeting inputs return a clean error.

## Project and Workspace Isolation

The central isolation boundary is the workspace.

- A project is represented as a workspace.
- Telegram private chat selection is scoped by Telegram user.
- Telegram group selection is scoped by the group chat.
- Memory, meetings, documents, tasks, decisions, risks, and audit logs are
  stored with `workspace_id`.
- `/ask`, `/tasks`, `/decisions`, and `/audit` query only the active workspace.
- A non-manager cannot rebind an already-bound group to a different project.

Current group member policy: Telegram group membership alone is not enough. A
user must also be a project member to access bound project memory.

## Repository Structure

```text
app/
  api/              FastAPI routes
  bot/              Telegram bot handlers, states, and product service
  db/               SQLAlchemy models and session setup
  listener/         Separate live-call listener code
  schemas/          Pydantic request/response models
  services/         Domain services for AI, documents, memory, STT, files
  worker/           Background worker entrypoint and tasks
migrations/         Alembic migrations
tests/              Unit and integration-style tests
docs/               Human-readable project documentation
```

## Audit Logs

Audit logs record important project actions such as workspace creation,
workspace activation, meeting ingestion, document ingestion, and task status
updates. Audit entries include organization, workspace, actor, action, resource,
and metadata.

Audit listing in Telegram is scoped to the active project.

## Local Docker Compose Stack

The local stack includes:

- `api` - FastAPI app and Alembic migration startup.
- `bot` - Telegram Bot API process.
- `worker` - background worker process.
- `postgres` - PostgreSQL with pgvector.
- `redis` - Redis for worker support.
- `minio` - local S3-compatible storage.
- `listener` - optional separate MTProto listener profile/service.

The live listener is separate from the current accepted core Telegram flow and
should not be enabled unless its credentials and consent requirements are clear.
