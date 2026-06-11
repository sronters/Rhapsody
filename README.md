# Rhapsody

Rhapsody — бот для команд в Telegram.

Он помогает сохранять рабочий контекст из чатов, встреч, документов и голосовых сообщений. После этого у бота можно спросить, что обсуждали, какие решения приняли, кто что должен сделать и где это было сказано.

## Что умеет

* подключается к Telegram-группе;
* сохраняет полезные сообщения из чата;
* принимает документы, изображения, voice/audio/video;
* разбирает встречи по тексту или записи;
* выделяет summary, задачи, дедлайны, решения и риски;
* отвечает на вопросы по памяти команды;
* показывает задачи, решения, аудит и статус системы.

Основной интерфейс — Telegram-команды:

```text
/start
/help
/setup
/meeting
/document
/ask
/tasks
/task_done
/task_status
/decisions
/audit
/reminders
/status
```

Есть отдельный режим для live-звонков:

```text
/listen
/live_status
/stop_listen
```

Он работает через отдельный listener на MTProto/user session. Это не обычный Telegram Bot API, поэтому live-call режим нужно проверять отдельно в реальном групповом звонке.

## Стек

* FastAPI
* PostgreSQL + pgvector
* Redis
* Celery
* MinIO
* SQLAlchemy 2.0
* Alembic
* aiogram 3
* Gemini / OpenAI / OpenRouter / Ollama
* faster-whisper
* Docker Compose

## Быстрый запуск

```bash
cp .env.example .env
docker compose up --build -d
```

API docs:

```text
http://localhost:8000/docs
```

Проверка:

```bash
docker compose ps
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/ready
```

## Минимальная настройка для Telegram

В `.env` нужно указать токен бота и AI provider.

Пример через Gemini:

```env
TELEGRAM_BOT_TOKEN=

AI_MODE=gemini
GEMINI_API_KEY=

VISION_MODE=gemini
```

После этого:

```bash
docker compose up --build -d
docker compose logs bot --tail=100
```

## Голосовые сообщения и аудио

Если OpenAI STT недоступен или возвращает `429`, можно использовать локальный Whisper:

```env
STT_MODE=local_whisper
LOCAL_WHISPER_MODEL=small
LOCAL_WHISPER_DEVICE=cpu
LOCAL_WHISPER_COMPUTE_TYPE=int8
LOCAL_WHISPER_LANGUAGE=ru
```

Для лучшего качества русского языка можно поставить:

```env
LOCAL_WHISPER_MODEL=medium
```

Если речь смешанная — русский, казахский, английский — можно оставить язык пустым:

```env
LOCAL_WHISPER_LANGUAGE=
```

## Документы и медиа

Rhapsody принимает:

* `.txt`
* `.md`
* `.csv`
* `.docx`
* `.xlsx`
* `.pdf`
* изображения
* voice messages
* audio files
* video/meeting recordings

Audio/video при необходимости прогоняются через `ffmpeg`.

## Live calls

Обычный Telegram bot не может сам зайти в групповой звонок и слушать его как участник. Для этого нужен отдельный listener через MTProto и обычный Telegram user account.

Настройка:

```env
LISTENER_ENABLED=true
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_USER_SESSION=
STT_MODE=local_whisper
```

Запуск:

```bash
docker compose --profile listener up --build -d
```

Команды в группе:

```text
/listen
/live_status
/stop_listen
```

Live-call режим считается рабочим только после ручной проверки: listener account вошёл в звонок, аудио записалось, transcript появился, бот отправил отчёт, а `/ask` смог ответить по этой встрече.

## Разработка

```bash
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -e ".[dev]"
python -m pytest
uvicorn app.main:create_app --factory --reload
```

## Проверки

```bash
python -m pytest
python -m ruff check . --no-cache
python -c "from app.main import create_app; app=create_app(); print(app.title, len(app.routes))"
docker compose config
docker compose up --build -d
docker compose ps
```

Для listener:

```bash
docker compose --profile listener build
docker compose --profile listener up -d
docker compose logs listener --tail=200
```

## Режимы запуска

* `cloud` — ключи AI provider задаются на стороне продукта;
* `byok` — организация использует свои ключи;
* `private` — self-hosted запуск с локальными моделями, MinIO и собственной базой.

## Текущий статус

Основной Telegram flow работает через бота при корректной настройке `.env`.

Live-call режим вынесен отдельно. Его нельзя считать готовым, пока он не пройдёт ручной тест в реальном Telegram group call.
