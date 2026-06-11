# TeamMind

TeamMind — это production-ready FastAPI бэкэнд для Telegram-native AI операционной системы команд. Превращает совещания, чаты, документы, задачи, решения и риски в изолированную корпоративную память компании с цитируемыми ответами.

## Содержимое

- Модульное FastAPI приложение с асинхронной SQLAlchemy 2.0
- PostgreSQL схема с поддержкой pgvector для векторного хранилища памяти
- Redis/Celery контракты воркеров для тяжёлой обработки
- Маршрутизатор AI провайдеров для Cloud, BYOK и Private режимов развёртывания
- Изоляция тенантов, аутентификация по API-ключам, RBAC помощники, логи аудита и санитизированное логирование AI запросов
- Доменные модели для совещаний, задач, решений, документов и памяти
- Docker Compose стек с API, воркером, Postgres + pgvector, Redis и MinIO
- Migrации Alembic и unit тесты для базового поведения интеллектуальной системы

Полный справочник проекта смотрите в [docs/PROJECT.md](docs/PROJECT.md): архитектура, технологический стек, API поверхность, функции, модель данных, режимы развёртывания, модель безопасности и дорожная карта.

## Быстрый старт

```bash
cp .env.example .env
docker compose up --build
```

Документация API доступна по адресу `http://localhost:8000/docs`.

Для работы с Telegram ботом установите `TELEGRAM_BOT_TOKEN` и один из AI провайдеров в `.env`.
Обработка загруженных voice/audio/video совещаний требует `STT_MODE=openai` с `OPENAI_API_KEY` или `STT_MODE=local_whisper` с локально установленным Whisper.
Распознавание изображений требует `VISION_MODE=openai` с `OPENAI_API_KEY` или `VISION_MODE=gemini` с `GEMINI_API_KEY`.

Прослушивание Telegram групповых звонков — это отдельный MTProto/user-session сервис, не процесс Bot API. Включайте только с явного согласия группы и реальными учётными данными:

```bash
LISTENER_ENABLED=true
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
TELEGRAM_USER_SESSION=...
STT_MODE=openai
docker compose --profile listener up --build
```

Затем используйте команды `/listen`, `/stop_listen` и `/live_status` в настроенной Telegram группе.
Слушатель вернёт ясную ошибку, если отсутствуют MTProto учётные данные, конфигурация STT или требуемые зависимости.

## Локальная разработка

```bash
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -e ".[dev]"
pytest
uvicorn app.main:create_app --factory --reload
```

## Режимы развёртывания

- `cloud`: AI ключи TeamMind и управляемая инфраструктура
- `byok`: зашифрованные ключи провайдеров заказчика с маршрутизацией по организациям
- `private`: on-prem стек с локальным vLLM/Ollama, локальными эмбеддингами, MinIO и приватной Postgres

Эти режимы управляются конфигурацией. Основная бизнес-логика не зависит от конкретного LLM провайдера.
