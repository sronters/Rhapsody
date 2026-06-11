from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.services import (
    SUPPORTED_DOCUMENT_TYPES,
    TelegramProductService,
    extract_supported_document_text,
    provider_error_message,
)
from app.bot.states import AskStates, DocumentStates, MeetingStates, TaskStates
from app.db.session import AsyncSessionFactory
from app.listener.adapters import ListenerError
from app.listener.service import LiveMeetingListenerService

router = Router()

HELP_TEXT = """Commands:
/setup - create or connect this chat to a workspace
/meeting - analyze meeting notes or a transcript file
/document - save and index document text or a supported file
/ask - ask a question from team memory
/tasks - show persisted tasks
/task_done - mark a task as done
/task_status - update a task status
/decisions - show persisted decisions
/audit - show recent audit events
/reminders - show upcoming task reminders
/status - show task status summary
/listen - start live group call listening
/stop_listen - stop live listening and generate a report
/live_status - show live listener status"""

SETUP_REQUIRED = "This chat is not connected yet. Run /setup first."


@router.message(Command("start"))
async def start(message: Message) -> None:
    await message.answer(
        "Welcome to Rhapsody. I turn team communication, meetings, and documents into "
        "searchable operating memory.\n\n"
        f"{HELP_TEXT}\n\nRun /setup first if this chat is not connected yet."
    )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("setup"))
async def setup(message: Message) -> None:
    async with AsyncSessionFactory() as session:
        await TelegramProductService(session).setup(
            telegram_user_id=message.from_user.id,
            display_name=message.from_user.full_name,
            telegram_chat_id=message.chat.id,
            chat_title=message.chat.title or message.chat.full_name,
        )
    await message.answer(
        "Workspace connected.\n"
        "You can now use /meeting, /document, /ask, /tasks, /task_done, "
        "/task_status, /decisions, /audit, /reminders, and /status."
    )


@router.message(Command("meeting"))
async def meeting(message: Message, state: FSMContext) -> None:
    await state.set_state(MeetingStates.waiting_for_transcript)
    await message.answer(
        f"Send the meeting transcript, notes, or a supported file ({SUPPORTED_DOCUMENT_TYPES})."
    )


@router.message(MeetingStates.waiting_for_transcript, F.text)
async def receive_meeting(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _ingest_meeting_text(message, message.text or "")


@router.message(MeetingStates.waiting_for_transcript, F.document)
async def receive_meeting_file(message: Message, state: FSMContext) -> None:
    await state.clear()
    progress = await message.answer("Downloading meeting file...")
    try:
        downloaded = await message.bot.download(message.document)
        if downloaded is None:
            await progress.edit_text("I could not download this file from Telegram.")
            return
        transcript = extract_supported_document_text(
            downloaded.read(),
            message.document.file_name or "meeting-notes",
            message.document.mime_type,
        )
    except Exception as exc:
        await progress.edit_text(provider_error_message(exc))
        return
    await progress.delete()
    await _ingest_meeting_text(message, transcript)


@router.message(MeetingStates.waiting_for_transcript, F.voice | F.audio | F.video)
async def receive_meeting_recording(message: Message, state: FSMContext) -> None:
    await state.clear()
    media, filename, content_type = _message_media(message)
    progress = await message.answer("Transcribing recording...")
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        context = await service.context_for_chat(message.from_user.id, message.chat.id)
        if context is None:
            await progress.edit_text(SETUP_REQUIRED)
            return
        try:
            downloaded = await message.bot.download(media)
            if downloaded is None:
                await progress.edit_text("I could not download this recording from Telegram.")
                return
            result = await service.ingest_meeting_media(
                context,
                downloaded.read(),
                filename,
                content_type,
            )
        except Exception as exc:
            await progress.edit_text(provider_error_message(exc))
            return
    await progress.edit_text(result)


async def _ingest_meeting_text(message: Message, transcript: str) -> None:
    progress = await message.answer("Analyzing meeting...")
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        context = await service.context_for_chat(message.from_user.id, message.chat.id)
        if context is None:
            await progress.edit_text(SETUP_REQUIRED)
            return
        try:
            result = await service.ingest_meeting(context, transcript)
        except Exception as exc:
            await progress.edit_text(provider_error_message(exc))
            return
    await progress.edit_text(result)


@router.message(Command("document"))
async def document(message: Message, state: FSMContext) -> None:
    await state.set_state(DocumentStates.waiting_for_document)
    await message.answer(f"Send document text or upload a file ({SUPPORTED_DOCUMENT_TYPES}).")


@router.message(DocumentStates.waiting_for_document, F.text)
async def receive_document_text(message: Message, state: FSMContext) -> None:
    await state.clear()
    progress = await message.answer("Indexing document...")
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        context = await service.context_for_chat(message.from_user.id, message.chat.id)
        if context is None:
            await progress.edit_text(SETUP_REQUIRED)
            return
        result = await service.ingest_document_text(context, message.text or "")
    await progress.edit_text(result)


@router.message(DocumentStates.waiting_for_document, F.document)
async def receive_document_file(message: Message, state: FSMContext) -> None:
    await state.clear()
    progress = await message.answer("Indexing document...")
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        context = await service.context_for_chat(message.from_user.id, message.chat.id)
        if context is None:
            await progress.edit_text(SETUP_REQUIRED)
            return
        try:
            downloaded = await message.bot.download(message.document)
            if downloaded is None:
                await progress.edit_text("I could not download this file from Telegram.")
                return
            result = await service.ingest_document_file(
                context,
                downloaded.read(),
                message.document.file_name or "telegram-document",
                message.document.mime_type,
            )
        except Exception as exc:
            await progress.edit_text(provider_error_message(exc))
            return
    await progress.edit_text(result)


@router.message(DocumentStates.waiting_for_document, F.photo)
async def receive_document_photo(message: Message, state: FSMContext) -> None:
    await state.clear()
    progress = await message.answer("Reading image...")
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        context = await service.context_for_chat(message.from_user.id, message.chat.id)
        if context is None:
            await progress.edit_text(SETUP_REQUIRED)
            return
        try:
            photo = message.photo[-1]
            downloaded = await message.bot.download(photo.file_id)
            if downloaded is None:
                await progress.edit_text("I could not download this image from Telegram.")
                return
            result = await service.ingest_image(
                context,
                downloaded.read(),
                f"telegram-photo-{message.message_id}.jpg",
                "image/jpeg",
            )
        except Exception as exc:
            await progress.edit_text(provider_error_message(exc))
            return
    await progress.edit_text(result)


@router.message(DocumentStates.waiting_for_document, F.voice | F.audio)
async def receive_audio_document(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Recordings are processed as meetings. Use /meeting and send the recording there."
    )


@router.message(Command("ask"))
async def ask(message: Message, state: FSMContext) -> None:
    question = " ".join(_command_args(message.text))
    if question:
        await _answer_question(message, question)
        return
    await state.set_state(AskStates.waiting_for_question)
    await message.answer("What do you want to know?")


@router.message(AskStates.waiting_for_question, F.text)
async def receive_question(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _answer_question(message, message.text or "")


async def _answer_question(message: Message, question: str) -> None:
    progress = await message.answer("Searching team memory...")
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        context = await service.context_for_chat(message.from_user.id, message.chat.id)
        if context is None:
            await progress.edit_text(SETUP_REQUIRED)
            return
        try:
            result = await service.ask(context, question)
        except Exception as exc:
            await progress.edit_text(provider_error_message(exc))
            return
    await progress.edit_text(result)


@router.message(Command("tasks"))
async def tasks(message: Message) -> None:
    await _send_context_result(message, "list_tasks")


@router.message(Command("task_done"))
async def task_done(message: Message, state: FSMContext) -> None:
    args = _command_args(message.text)
    if args and args[0].isdigit():
        await _update_task_status(message, int(args[0]), "done")
        return
    await state.set_state(TaskStates.waiting_for_done_task)
    await message.answer("Send the task number to mark as done. Use /tasks if you need the list.")


@router.message(TaskStates.waiting_for_done_task, F.text)
async def receive_done_task(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not (message.text or "").strip().isdigit():
        await message.answer("Please send a task number. Use /tasks to see the current list.")
        return
    await _update_task_status(message, int((message.text or "").strip()), "done")


@router.message(Command("task_status"))
async def task_status(message: Message, state: FSMContext) -> None:
    args = _command_args(message.text)
    if len(args) >= 2 and args[0].isdigit():
        await _update_task_status(message, int(args[0]), args[1])
        return
    await state.set_state(TaskStates.waiting_for_status_update)
    await message.answer(
        "Send task number and status, for example: 2 in_progress.\n"
        "Allowed statuses: open, in_progress, blocked, done, cancelled."
    )


@router.message(TaskStates.waiting_for_status_update, F.text)
async def receive_task_status(message: Message, state: FSMContext) -> None:
    await state.clear()
    args = (message.text or "").strip().split()
    if len(args) < 2 or not args[0].isdigit():
        await message.answer("Please send a task number and status, for example: 2 blocked.")
        return
    await _update_task_status(message, int(args[0]), args[1])


@router.message(Command("decisions"))
async def decisions(message: Message) -> None:
    await _send_context_result(message, "list_decisions")


@router.message(Command("audit"))
async def audit(message: Message) -> None:
    await _send_context_result(message, "list_audit")


@router.message(Command("reminders"))
async def reminders(message: Message) -> None:
    await _send_context_result(message, "list_reminders")


@router.message(Command("status"))
async def status(message: Message) -> None:
    await _send_context_result(message, "task_status_summary")


@router.message(Command("listen"))
async def listen(message: Message) -> None:
    if not is_live_listening_chat_type(message.chat.type):
        await message.answer("Live call listening can only be started in a Telegram group.")
        return
    async with AsyncSessionFactory() as session:
        product_service = TelegramProductService(session)
        context = await product_service.context_for_chat(message.from_user.id, message.chat.id)
        if context is None:
            await message.answer(SETUP_REQUIRED)
            return
        try:
            result = await LiveMeetingListenerService(session).start_listening(
                context,
                message.chat.id,
            )
        except ListenerError as exc:
            await message.answer(str(exc))
            return
    await message.answer(result.message)


@router.message(Command("stop_listen"))
async def stop_listen(message: Message) -> None:
    if not is_live_listening_chat_type(message.chat.type):
        await message.answer("Live call listening is only available in Telegram groups.")
        return
    async with AsyncSessionFactory() as session:
        product_service = TelegramProductService(session)
        context = await product_service.context_for_chat(message.from_user.id, message.chat.id)
        if context is None:
            await message.answer(SETUP_REQUIRED)
            return
        try:
            await message.answer("Rhapsody stopped listening and is generating the meeting report.")
            result = await LiveMeetingListenerService(session).stop_listening(
                context,
                message.chat.id,
            )
        except Exception as exc:
            await message.answer(str(exc))
            return
    await message.answer(result.report)


@router.message(Command("live_status"))
async def live_status(message: Message) -> None:
    if not is_live_listening_chat_type(message.chat.type):
        await message.answer("Live call listening status is only available in Telegram groups.")
        return
    async with AsyncSessionFactory() as session:
        product_service = TelegramProductService(session)
        context = await product_service.context_for_chat(message.from_user.id, message.chat.id)
        if context is None:
            await message.answer(SETUP_REQUIRED)
            return
        result = await LiveMeetingListenerService(session).live_status(context, message.chat.id)
    await message.answer(result.message)


@router.message(F.text & ~F.text.startswith("/"))
async def remember_group_message(message: Message) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        return
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        context = await service.context_for_chat(message.from_user.id, message.chat.id)
        if context is None:
            return
        await service.ingest_chat_message(context, message.message_id, message.text or "")


@router.message(F.document)
async def remember_group_document(message: Message) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        return
    progress = await message.answer("Indexing file...")
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        context = await service.context_for_chat(message.from_user.id, message.chat.id)
        if context is None:
            await progress.delete()
            return
        try:
            downloaded = await message.bot.download(message.document)
            if downloaded is None:
                await progress.edit_text("I could not download this file from Telegram.")
                return
            result = await service.ingest_document_file(
                context,
                downloaded.read(),
                message.document.file_name or "telegram-document",
                message.document.mime_type,
            )
        except Exception as exc:
            await progress.edit_text(provider_error_message(exc))
            return
    await progress.edit_text(result)


@router.message(F.photo)
async def remember_group_photo(message: Message) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        return
    progress = await message.answer("Reading image...")
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        context = await service.context_for_chat(message.from_user.id, message.chat.id)
        if context is None:
            await progress.delete()
            return
        try:
            photo = message.photo[-1]
            downloaded = await message.bot.download(photo.file_id)
            if downloaded is None:
                await progress.edit_text("I could not download this image from Telegram.")
                return
            result = await service.ingest_image(
                context,
                downloaded.read(),
                f"telegram-photo-{message.message_id}.jpg",
                "image/jpeg",
            )
        except Exception as exc:
            await progress.edit_text(provider_error_message(exc))
            return
    await progress.edit_text(result)


@router.message(F.voice | F.audio | F.video)
async def remember_group_recording(message: Message) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        return
    media, filename, content_type = _message_media(message)
    progress = await message.answer("Transcribing recording...")
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        context = await service.context_for_chat(message.from_user.id, message.chat.id)
        if context is None:
            await progress.delete()
            return
        try:
            downloaded = await message.bot.download(media)
            if downloaded is None:
                await progress.edit_text("I could not download this recording from Telegram.")
                return
            result = await service.ingest_media_message(
                context,
                message.message_id,
                downloaded.read(),
                filename,
                content_type,
            )
        except Exception as exc:
            await progress.edit_text(provider_error_message(exc))
            return
    await progress.edit_text(result)


async def _send_context_result(message: Message, method_name: str) -> None:
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        context = await service.context_for_chat(message.from_user.id, message.chat.id)
        if context is None:
            await message.answer(SETUP_REQUIRED)
            return
        result = await getattr(service, method_name)(context)
    await message.answer(result)


async def _update_task_status(message: Message, task_number: int, status: str) -> None:
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        context = await service.context_for_chat(message.from_user.id, message.chat.id)
        if context is None:
            await message.answer(SETUP_REQUIRED)
            return
        result = await service.update_task_status(context, task_number, status)
    await message.answer(result)


def _command_args(text: str | None) -> list[str]:
    if not text:
        return []
    parts = text.strip().split()
    return parts[1:]


def _message_media(message: Message):
    if message.voice is not None:
        return message.voice, f"voice-{message.message_id}.ogg", message.voice.mime_type
    if message.audio is not None:
        return (
            message.audio,
            message.audio.file_name or f"audio-{message.message_id}.mp3",
            message.audio.mime_type,
        )
    if message.video is not None:
        return message.video, f"video-{message.message_id}.mp4", message.video.mime_type
    raise ValueError("No supported media found.")


def is_live_listening_chat_type(chat_type: str) -> bool:
    return chat_type in {"group", "supergroup"}
