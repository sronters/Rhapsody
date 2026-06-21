<div align="center">
<img src="https://readme-typing-svg.demolab.com?font=Space+Mono&size=42&duration=2600&pause=900&color=0F766E&center=true&vCenter=true&width=900&lines=Rhapsody;Telegram-native+team+memory;Chats+%E2%86%92+Meetings+%E2%86%92+Tasks;Ask+your+team+history" />

**Telegram-first team memory for meetings, documents, tasks, decisions, and live-call notes.**

[English](README.md) · [Русский](README.ru.md)
</div>

Rhapsody is a project-scoped memory layer for teams that work in Telegram. It turns meeting notes, files, voice messages, and group chat context into searchable memory with tasks, decisions, risks, summaries, sources, and audit history.

## What Works

- Telegram bot project setup, project switching, meeting ingestion, document ingestion, `/ask`, `/tasks`, `/decisions`, `/audit`, and live-listener commands.
- FastAPI backend with PostgreSQL + pgvector, Redis, MinIO, worker pipelines, provider-key storage, RBAC, and service API-key auth.
- Local Docker Compose stack for API, bot, worker, listener, PostgreSQL, Redis, MinIO, and local Whisper mode.
- Bilingual product foundation: backend catalogs, Telegram language selection, stored user/chat locale, AI prompt language instruction, docs, README, and admin frontend routes `/en` and `/ru`.

## Local Run

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/ready
```

For a public HTTPS development endpoint without a public IP:

```bash
tailscale funnel 8000
```

Then set:

```env
API_BASE_URL=https://your-machine.your-tailnet.ts.net
RHAPSODY_DOMAIN=your-machine.your-tailnet.ts.net
```

## Languages

The default product locale is English:

```env
DEFAULT_LOCALE=en
SUPPORTED_LOCALES=en,ru
```

Telegram users can run `/language` or `/lang`. Private chats store the choice on `users.locale`; groups store it on `telegram_chats.locale`, and only project owners/admins can change the group language.

## Documentation

```bash
cd docs-site
npm install
npm run sync:en-ru
npm run check
npm run dev
```

The documentation site is the canonical product/operator docs. The short
maintainer architecture note is in `docs/ARCHITECTURE.md`.

Refresh the generated FastAPI OpenAPI file after changing routes:

```bash
python scripts/export_openapi.py
```

## Checks

```bash
python scripts/check_translations.py
python -m ruff check app tests migrations scripts
python -m pytest
cd frontend && npm install && npm run build
cd docs-site && npm install && npm run check
```

## Status

Rhapsody is ready for local development and Telegram testing. It is not yet a guaranteed 24/7 production deployment unless hosted on a reliable always-on machine or VPS.
