<div align="center">
<img src="https://readme-typing-svg.demolab.com?font=Space+Mono&size=42&duration=2600&pause=900&color=0F766E&center=true&vCenter=true&width=900&lines=Rhapsody;Telegram-native+team+memory;Chats+%E2%86%92+Meetings+%E2%86%92+Tasks;Ask+your+team+history" />

**Telegram-first память команды для встреч, документов, задач, решений и live-звонков.**

[English](README.md) · [Русский](README.ru.md)
</div>

Rhapsody — это project-scoped слой памяти для команд, которые работают в Telegram. Он превращает заметки встреч, файлы, голосовые сообщения и контекст групповых чатов в searchable memory с задачами, решениями, рисками, summary, источниками и audit history.

## Что Уже Работает

- Telegram bot: setup проекта, переключение проектов, ingest встреч и документов, `/ask`, `/tasks`, `/decisions`, `/audit`, команды live-listener.
- FastAPI backend с PostgreSQL + pgvector, Redis, MinIO, worker pipelines, provider-key storage, RBAC и service API-key auth.
- Local Docker Compose stack: API, bot, worker, listener, PostgreSQL, Redis, MinIO и local Whisper mode.
- Двуязычная основа продукта: backend catalogs, выбор языка в Telegram, сохранение locale у пользователя/чата, language instruction для AI prompts, docs, README и admin frontend routes `/en` и `/ru`.

## Локальный Запуск

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/ready
```

Чтобы открыть публичный HTTPS endpoint без белого IP:

```bash
tailscale funnel 8000
```

Затем укажи:

```env
API_BASE_URL=https://your-machine.your-tailnet.ts.net
RHAPSODY_DOMAIN=your-machine.your-tailnet.ts.net
```

## Языки

Дефолтный язык продукта — английский:

```env
DEFAULT_LOCALE=en
SUPPORTED_LOCALES=en,ru
```

В Telegram можно использовать `/language` или `/lang`. В личных чатах выбор хранится в `users.locale`; в группах — в `telegram_chats.locale`, и менять язык группы могут только owner/admin проекта.

## Документация

```bash
cd docs-site
npm install
npm run sync:en-ru
npm run check
npm run dev
```

`docs-site/` — основная продуктовая и операторская документация. Короткая
maintainer-заметка по архитектуре находится в `docs/ARCHITECTURE.md`.

После изменения API обновите OpenAPI файл:

```bash
python scripts/export_openapi.py
```

## Проверки

```bash
python scripts/check_translations.py
python -m ruff check app tests migrations scripts
python -m pytest
cd frontend && npm install && npm run build
cd docs-site && npm install && npm run check
```

## Статус

Rhapsody подходит для локальной разработки и Telegram-тестов. Для настоящего 24/7 production нужен постоянно включенный компьютер, Oracle A1 при доступности или VPS.
