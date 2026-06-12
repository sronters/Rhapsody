# Rhapsody

Rhapsody is a Telegram-first team memory assistant.

Teams often lose decisions, tasks, context, and documents inside chat threads.
Rhapsody keeps that working context by project, then lets people ask questions
later with sources. The current core flow is centered on Telegram because that is
where many teams already discuss meetings, documents, follow-ups, and decisions.

Rhapsody is not a generic chatbot. It is a project-scoped memory layer for team
work: meetings become summaries, tasks, decisions, risks, and memory chunks;
documents become searchable project memory; questions are answered only from the
selected project.

## Current Status

Currently working:

- Telegram bot startup with a valid `TELEGRAM_BOT_TOKEN`.
- Private-chat project creation and switching with `/new_project` and
  `/use_project`.
- Meeting ingestion from pasted text and supported note files.
- Document ingestion from pasted text and supported files.
- `/ask` over stored meetings, documents, and chat memory with sources.
- `/tasks`, `/task_done`, `/task_status`, `/decisions`, and `/audit` over
  persisted project data.
- Local Whisper mode for Telegram voice/audio when configured.
- Project isolation for one-user multi-project flows.
- Group project binding and automated group hijack regression coverage.
- Docker Compose local stack with API, bot, worker, Postgres + pgvector, Redis,
  and MinIO.

Still pending:

- Real second Telegram user cross-access manual test.
- Real second Telegram user group hijack manual test.
- Live-call listener verification is separate from the accepted core Telegram
  flow and is not part of the current accepted scope.

Do not treat this repository as ready for production use. It is suitable for
preliminary technical review of the core Telegram product flow.

## How It Works

1. A Telegram user creates or selects a project.
2. Rhapsody maps the Telegram chat to the selected project/workspace.
3. Meeting notes, documents, and important chat content are stored in that
   workspace.
4. The AI provider extracts summaries, tasks, decisions, risks, and answer text.
5. `/ask` retrieves memory only from the selected workspace and returns sources.
6. Tasks, decisions, documents, memory chunks, and audit logs remain scoped to
   the project.

## Local Run

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/ready
```

The API is available at `http://localhost:8000`.

For local Python development:

```bash
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -e ".[dev]"
python -m pytest
python -m ruff check . --no-cache
```

## Required Environment

Minimum local Docker settings:

```env
DATABASE_URL=postgresql+asyncpg://rhapsody:rhapsody@postgres:5432/rhapsody
REDIS_URL=redis://redis:6379/0
S3_ENDPOINT_URL=http://minio:9000
S3_ACCESS_KEY_ID=minioadmin
S3_SECRET_ACCESS_KEY=minioadmin
S3_BUCKET=rhapsody
TELEGRAM_BOT_TOKEN=
AI_MODE=gemini
GEMINI_API_KEY=
VISION_MODE=gemini
STT_MODE=local_whisper
LOCAL_WHISPER_MODEL=small
LOCAL_WHISPER_LANGUAGE=ru
LISTENER_ENABLED=false
```

Use `OPENAI_API_KEY` instead if `AI_MODE=openai`, `VISION_MODE=openai`, or
`STT_MODE=openai`.

Local Whisper uses `faster-whisper` and ffmpeg inside the Docker image. Telegram
`.ogg`/`.oga` voice messages are converted before transcription. If STT is not
configured, audio inputs return a clean Telegram error instead of a fake
transcript.

## Telegram Commands

Project setup:

- `/start` - show basic help.
- `/setup` - connect a private chat or start group setup.
- `/new_project Alpha` - create and select a project.
- `/projects` - list projects visible to the current user.
- `/use_project Alpha` - switch the selected project.
- `/project` or `/current_project` - show the active project.

Memory and work:

- `/meeting` - send meeting text, a supported note file, or configured audio.
- `/document` - save pasted document text or a supported file.
- `/ask What did we decide?` - answer from selected project memory.
- `/tasks` - list persisted tasks.
- `/task_done 1` - mark a task done.
- `/task_status 1 blocked` - set task status.
- `/decisions` - list persisted decisions.
- `/audit` - list recent project audit events.

Some commands exist for broader product experiments, but the current accepted
core flow is the project-scoped Telegram memory flow above.

## Project Isolation

Private chats:

- Each Telegram user has their own selected project mapping.
- One user can create `Alpha` and `Beta` and switch between them.
- `/ask`, `/tasks`, `/decisions`, `/document`, and `/audit` use only the selected
  workspace.

Group chats:

- A group is bound to one active project mapping at a time.
- Group memory is saved only to the bound project.
- A random non-manager cannot create or select a project to rebind an already
  bound group.
- Current policy: a Telegram group member must also be a project member to use
  bound project memory.

Known manual gap: second-user Telegram isolation still needs verification with a
real second Telegram identity.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Telegram flow](docs/TELEGRAM_FLOW.md)
- [Project isolation](docs/PROJECT_ISOLATION.md)
- [Demo checklist](docs/DEMO_CHECKLIST.md)
- [Verification](docs/VERIFICATION.md)
- [Project reference](docs/PROJECT.md)

## Known Limitations

- Second-user manual Telegram testing is still pending.
- Live-call listening is a separate MTProto/user-session service and is not part
  of the accepted core flow.
- The frontend is not the main reviewed interface for the current scope.
- Provider quality depends on the configured LLM/STT/Vision provider.
- Local development secrets in `.env` must be supplied by the operator; no real
  secrets belong in `.env.example`.
