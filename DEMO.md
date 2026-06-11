# TeamMind local demo

This demo can run through FastAPI or through the Telegram bot. The Telegram product flow uses
the selected LLM provider from `AI_MODE`; it does not silently fall back to deterministic extraction.
For free local usage, run Ollama and set `AI_MODE=ollama`.

## Telegram bot setup

Create a bot with BotFather and set:

```env
TELEGRAM_BOT_TOKEN=your-bot-token
```

Choose one AI provider:

```env
AI_MODE=openai
OPENAI_API_KEY=...
```

```env
AI_MODE=openrouter
OPENROUTER_API_KEY=...
```

```env
AI_MODE=gemini
GEMINI_API_KEY=...
```

For local Ollama:

```powershell
ollama pull qwen2.5:7b
ollama serve
```

Then set:

```env
AI_MODE=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=qwen2.5:7b
```

If the selected provider is missing or unavailable, the bot returns a clear error.

## 1. Local venv test run

```bash
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -e ".[dev]"
python -m pytest
python -m ruff check . --no-cache
python -c "from app.main import create_app; app=create_app(); print(app.title, len(app.routes))"
```

## 2. Start Docker Compose services

```bash
cp .env.example .env
docker compose up --build
```

The stack starts:

- FastAPI API on `http://localhost:8000`
- Telegram bot process when `TELEGRAM_BOT_TOKEN` is configured
- Postgres + pgvector on `localhost:5432`
- Redis on `localhost:6379`
- MinIO on `localhost:9000`
- Celery worker process

The API container runs `alembic upgrade head` before starting Uvicorn. The MinIO init
container creates the `teammind` bucket idempotently.

## Telegram demo flow

Open the bot in Telegram and run:

```text
/start
/setup
/meeting
```

Paste meeting notes/transcript. The bot asks the configured LLM for JSON extraction, persists the
meeting summary, tasks, decisions, risks, memory chunks, and audit log, then returns the summary.

Then run:

```text
/document
```

Paste document text.

Then run:

```text
/ask
```

Ask a question. The bot retrieves memory sources, calls the configured LLM, and returns an answer
with sources.

You can also run:

```text
/tasks
/decisions
/audit
```

Live Zoom, Google Meet, and Microsoft Teams joining is not implemented in this version. Use pasted
transcripts, meeting notes, or Telegram text input.

## 3. Run migrations manually, if needed

Docker Compose runs migrations for the API automatically. If you are running the API outside
Compose against a local Postgres + pgvector database, run:

```bash
alembic upgrade head
```

## 4. Run integration tests against Docker Postgres

After Postgres is available on `localhost:5432`:

```bash
$env:TEAMMIND_INTEGRATION_DATABASE_URL="postgresql+asyncpg://teammind:teammind@localhost:5432/teammind"
python -m pytest tests/integration -m integration -v
```

Integration tests are skipped when `TEAMMIND_INTEGRATION_DATABASE_URL` is not set.

## 5. Open API docs

```text
http://localhost:8000/docs
```

Use this header for protected API calls:

```text
X-API-Key: local-dev-key
```

## 6. Minimal curl flow

Set variables manually from each response.

### Create organization

```bash
curl -s -X POST http://localhost:8000/api/v1/workspaces/organizations \
  -H "X-API-Key: local-dev-key" \
  -H "Content-Type: application/json" \
  -d '{"name":"Demo Org","deployment_mode":"cloud","retention_mode":"standard"}'
```

### Create workspace

```bash
curl -s -X POST http://localhost:8000/api/v1/workspaces \
  -H "X-API-Key: local-dev-key" \
  -H "Content-Type: application/json" \
  -d '{"organization_id":"ORG_ID","name":"Demo Workspace"}'
```

### Create user

```bash
curl -s -X POST http://localhost:8000/api/v1/workspaces/users \
  -H "X-API-Key: local-dev-key" \
  -H "Content-Type: application/json" \
  -d '{"display_name":"Demo Admin","email":"admin@example.com"}'
```

### Add user as admin

```bash
curl -s -X POST http://localhost:8000/api/v1/workspaces/WORKSPACE_ID/members \
  -H "X-API-Key: local-dev-key" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"USER_ID","role":"admin"}'
```

### Ingest meeting transcript

```bash
curl -s -X POST http://localhost:8000/api/v1/meetings/ingest \
  -H "X-API-Key: local-dev-key" \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id":"WORKSPACE_ID",
    "title":"Launch planning",
    "source":"upload",
    "transcript_text":"We decided to launch the beta next Friday. I will prepare the launch checklist. The main risk is blocked vendor approval. We agreed to choose Supplier X."
  }'
```

This deterministically persists:

- meeting record
- meeting summary
- extracted tasks
- extracted decisions
- extracted risks
- memory chunks

### Ingest document text

```bash
curl -s -X POST "http://localhost:8000/api/v1/documents/ingest?actor_user_id=USER_ID" \
  -H "X-API-Key: local-dev-key" \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id":"WORKSPACE_ID",
    "name":"Supplier Notes",
    "content_type":"text/plain",
    "storage_key":"workspaces/WORKSPACE_ID/documents/supplier-notes.txt",
    "extracted_text":"Supplier X was selected because it met compliance and delivery needs."
  }'
```

### Ask memory

```bash
curl -s -X POST "http://localhost:8000/api/v1/memory/ask?actor_user_id=USER_ID" \
  -H "X-API-Key: local-dev-key" \
  -H "Content-Type: application/json" \
  -d '{"workspace_id":"WORKSPACE_ID","question":"Why did we choose Supplier X?","top_k":5}'
```

The answer is deterministic when no LLM provider is configured and includes source metadata.

### List tasks

```bash
curl -s "http://localhost:8000/api/v1/tasks?workspace_id=WORKSPACE_ID&actor_user_id=USER_ID" \
  -H "X-API-Key: local-dev-key"
```

### List decisions

```bash
curl -s "http://localhost:8000/api/v1/decisions?workspace_id=WORKSPACE_ID&actor_user_id=USER_ID" \
  -H "X-API-Key: local-dev-key"
```

### List audit logs

```bash
curl -s "http://localhost:8000/api/v1/audit?workspace_id=WORKSPACE_ID&actor_user_id=USER_ID" \
  -H "X-API-Key: local-dev-key"
```

## What is deterministic/local today

- Meeting extraction is rule-based.
- Memory embeddings are deterministic local vectors.
- Memory answers use a deterministic local provider if no AI key is configured.
- Workers are contracts/planning boundaries unless external providers are configured.

## What is not complete yet

- Full STT processing for uploaded audio.
- DB-native pgvector nearest-neighbor query path in memory Q&A.
- Full frontend admin workflows.
- Production Helm dependencies and secrets.