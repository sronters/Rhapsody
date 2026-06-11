<div align="center">
<img src="https://capsule-render.vercel.app/api?type=waving&height=180&color=0:111827,45:4F46E5,100:7C3AED&text=Rhapsody&fontColor=FFFFFF&fontSize=52&fontAlignY=36&desc=Telegram-native%20team%20memory&descAlignY=58&descSize=18" />
<br />
<img src="https://readme-typing-svg.demolab.com?font=Space+Mono&size=22&duration=2600&pause=900&color=A78BFA&center=true&vCenter=true&width=850&lines=Chats+%E2%86%92+Meetings+%E2%86%92+Tasks+%E2%86%92+Decisions;Voice+notes+%E2%86%92+Transcripts+%E2%86%92+Team+memory;Ask+what+your+team+already+knows" />
<br />
<br />
<img src="https://img.shields.io/badge/FastAPI-111827?style=for-the-badge&logo=fastapi&logoColor=00E0B8" />
<img src="https://img.shields.io/badge/PostgreSQL_+_pgvector-1E293B?style=for-the-badge&logo=postgresql&logoColor=60A5FA" />
<img src="https://img.shields.io/badge/Telegram-075985?style=for-the-badge&logo=telegram&logoColor=FFFFFF" />
<img src="https://img.shields.io/badge/Docker-1D4ED8?style=for-the-badge&logo=docker&logoColor=FFFFFF" />
<img src="https://img.shields.io/badge/Whisper-4C1D95?style=for-the-badge&logo=openai&logoColor=C4B5FD" />
<img src="https://img.shields.io/badge/Gemini-312E81?style=for-the-badge&logo=googlegemini&logoColor=A5B4FC" />
<br />
<br />
<img src="https://capsule-render.vercel.app/api?type=rect&height=2&color=0:38BDF8,50:A78BFA,100:F472B6" />
</div>
<br />

Rhapsody

Rhapsody — бот для команд в Telegram.

Он помогает сохранять рабочий контекст из чатов, встреч, документов и голосовых сообщений. После этого у бота можно спросить, что обсуждали, какие решения приняли, кто что должен сделать и где это было сказано.

<div align="center">
Telegram group
   ↓
chats · meetings · docs · voice · images
   ↓
Rhapsody
   ↓
tasks · decisions · risks · cited answers
</div>

Что умеет

* подключается к Telegram-группе;
* сохраняет полезные сообщения из чата;
* принимает документы, изображения, voice/audio/video;
* разбирает встречи по тексту или записи;
* выделяет summary, задачи, дедлайны, решения и риски;
* отвечает на вопросы по памяти команды;
* показывает задачи, решения, аудит и статус системы.

⸻

Основной интерфейс

Основной интерфейс — Telegram-команды:

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

Есть отдельный режим для live-звонков:

/listen
/live_status
/stop_listen

Он работает через отдельный listener на MTProto/user session. Это не обычный Telegram Bot API, поэтому live-call режим нужно проверять отдельно в реальном групповом звонке.

⸻

Стек

<div align="center">

Backend	Data	Telegram	AI / STT	Runtime
FastAPI	PostgreSQL + pgvector	aiogram 3	Gemini	Docker Compose
SQLAlchemy 2.0	Redis	MTProto listener	OpenAI	MinIO
Alembic	Celery	Telethon / Pyrogram	OpenRouter / Ollama	faster-whisper

</div>

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

⸻

Быстрый запуск

cp .env.example .env
docker compose up --build -d

API docs:

http://localhost:8000/docs

Проверка:

docker compose ps
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/ready

⸻

Минимальная настройка для Telegram

В .env нужно указать токен бота и AI provider.

Пример через Gemini:

TELEGRAM_BOT_TOKEN=
AI_MODE=gemini
GEMINI_API_KEY=
VISION_MODE=gemini

После этого:

docker compose up --build -d
docker compose logs bot --tail=100

⸻

Голосовые сообщения и аудио

Если OpenAI STT недоступен или возвращает 429, можно использовать локальный Whisper:

STT_MODE=local_whisper
LOCAL_WHISPER_MODEL=small
LOCAL_WHISPER_DEVICE=cpu
LOCAL_WHISPER_COMPUTE_TYPE=int8
LOCAL_WHISPER_LANGUAGE=ru

Для лучшего качества русского языка можно поставить:

LOCAL_WHISPER_MODEL=medium

Если речь смешанная — русский, казахский, английский — можно оставить язык пустым:

LOCAL_WHISPER_LANGUAGE=

⸻

Документы и медиа

Rhapsody принимает:

* .txt
* .md
* .csv
* .docx
* .xlsx
* .pdf
* изображения
* voice messages
* audio files
* video/meeting recordings

Audio/video при необходимости прогоняются через ffmpeg.

<div align="center">
file / image / audio / video
        ↓
download
        ↓
parse / OCR / STT
        ↓
memory chunks
        ↓
/ask with sources
</div>

⸻

Live calls

Обычный Telegram bot не может сам зайти в групповой звонок и слушать его как участник. Для этого нужен отдельный listener через MTProto и обычный Telegram user account.

Настройка:

LISTENER_ENABLED=true
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_USER_SESSION=
STT_MODE=local_whisper

Запуск:

docker compose --profile listener up --build -d

Команды в группе:

/listen
/live_status
/stop_listen

Live-call режим считается рабочим только после ручной проверки: listener account вошёл в звонок, аудио записалось, transcript появился, бот отправил отчёт, а /ask смог ответить по этой встрече.

⸻

Разработка

python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -e ".[dev]"
python -m pytest
uvicorn app.main:create_app --factory --reload

⸻

Проверки

python -m pytest
python -m ruff check . --no-cache
python -c "from app.main import create_app; app=create_app(); print(app.title, len(app.routes))"
docker compose config
docker compose up --build -d
docker compose ps

Для listener:

docker compose --profile listener build
docker compose --profile listener up -d
docker compose logs listener --tail=200

⸻

Режимы запуска

* cloud — ключи AI provider задаются на стороне продукта;
* byok — организация использует свои ключи;
* private — self-hosted запуск с локальными моделями, MinIO и собственной базой.

⸻

Текущий статус

Основной Telegram flow работает через бота при корректной настройке .env.

Live-call режим вынесен отдельно. Его нельзя считать готовым, пока он не пройдёт ручной тест в реальном Telegram group call.

<br />
<div align="center">
<img src="https://capsule-render.vercel.app/api?type=waving&height=120&section=footer&color=0:7C3AED,50:2563EB,100:0F172A" />
   </div>