from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.services import (
    SUPPORTED_DOCUMENT_TYPES,
    TelegramProductService,
    extract_supported_document_text,
    provider_error_message,
)
from app.bot.states import AskStates, DocumentStates, MeetingStates, TaskStates
from app.db.session import AsyncSessionFactory
from app.i18n import t
from app.listener.adapters import ListenerError
from app.listener.service import LiveMeetingListenerService

router = Router()

HELP_TEXT = """Commands:
/setup - create or connect this chat to a workspace
/menu - show the main product menu
/project - show the active project
/projects - list projects connected to this chat
/project_new - create a new project
/project_use - switch this chat to a project
/members - show project members
/role - set a member role by replying to their message
/meeting - analyze meeting notes or a transcript file
/document - save and index document text or a supported file
/ask - ask a question from team memory
/tasks - show persisted tasks
/task_done - mark a task as done
/task_status - update a task status
/decisions - show persisted decisions
/digest_today - show today's project digest
/digest_week - show this week's project digest
/attention - show blockers, overdue tasks, and risks
/topics - show memory topics
/topic - show memory for one topic
/people - show project members
/person - show a person profile
/audit - show recent audit events
/reminders - show upcoming task reminders
/status - show task status summary
/connect_calls - connect call recording for this group
/call_setup - show recorder setup instructions
/recorder_status - show Rhapsody Recorder pool status
/listen - start live group call listening
/stop_listen - stop live listening and generate a report
/live_status - show live listener status"""

SETUP_REQUIRED = "Сначала выберите проект: /projects или создайте новый: /new_project Название"


@router.message(Command("start"))
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    locale = await _message_locale(message)
    await message.answer(t("telegram.start", locale), reply_markup=_language_keyboard())


@router.message(Command("language", "lang"))
async def language(message: Message, state: FSMContext) -> None:
    await state.clear()
    locale = await _message_locale(message)
    await message.answer(t("telegram.language_prompt", locale), reply_markup=_language_keyboard())


@router.callback_query(F.data.startswith("locale:"))
async def language_callback(callback: CallbackQuery) -> None:
    message = callback.message
    if message is None:
        await callback.answer()
        return
    requested_locale = (callback.data or "locale:en").split(":", maxsplit=1)[1]
    current_locale = await _message_locale(message, callback.from_user.id)
    try:
        async with AsyncSessionFactory() as session:
            saved_locale = await TelegramProductService(session).set_locale_for_chat(
                callback.from_user.id,
                callback.from_user.full_name,
                message.chat.id,
                message.chat.type,
                requested_locale,
            )
    except ValueError:
        await callback.answer(
            t("telegram.language_group_requires_setup", current_locale),
            show_alert=True,
        )
        return
    except PermissionError:
        await callback.answer(
            t("telegram.language_group_requires_manager", current_locale),
            show_alert=True,
        )
        return
    key = "telegram.language_saved_ru" if saved_locale == "ru" else "telegram.language_saved"
    await callback.answer(t(key, saved_locale), show_alert=True)
    await message.answer(t(key, saved_locale))


@router.message(Command("help"))
async def help_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(HELP_TEXT)


@router.message(Command("menu"))
async def menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(t("telegram.menu", await _message_locale(message)))


@router.message(Command("setup"))
async def setup(message: Message, state: FSMContext) -> None:
    await state.clear()
    async with AsyncSessionFactory() as session:
        context = await TelegramProductService(session).setup(
            telegram_user_id=message.from_user.id,
            display_name=message.from_user.full_name,
            telegram_chat_id=message.chat.id,
            chat_title=message.chat.title or message.chat.full_name,
            chat_type=message.chat.type,
        )
    if context is None:
        await message.answer(t("telegram.setup_required", await _message_locale(message)))
        return
    await message.answer(
        t(
            "telegram.setup_success",
            await _message_locale(message),
            workspace_name=context.workspace_name,
            role=context.role,
        )
    )


@router.message(Command("project", "current_project"))
async def project(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _send_context_result(message, "current_project")


@router.message(Command("projects"))
async def projects(message: Message, state: FSMContext) -> None:
    await state.clear()
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        result = await service.list_available_projects(
            message.from_user.id,
            message.from_user.full_name,
            message.chat.id,
            message.chat.type,
        )
    await message.answer(result)


@router.message(Command("project_new", "new_project"))
async def project_new(message: Message, state: FSMContext) -> None:
    await state.clear()
    name = " ".join(_command_args(message.text))
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        try:
            result = await service.create_project_for_telegram_user(
                message.from_user.id,
                message.from_user.full_name,
                message.chat.id,
                message.chat.type,
                name,
                message.chat.title or message.chat.full_name,
            )
        except Exception as exc:
            await message.answer(provider_error_message(exc))
            return
    await message.answer(result)


@router.message(Command("project_use", "use_project"))
async def project_use(message: Message, state: FSMContext) -> None:
    await state.clear()
    selector = " ".join(_command_args(message.text))
    if not selector:
        await message.answer("Напиши номер или название проекта: /project_use 2")
        return
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        try:
            result = await service.use_project_for_telegram_user(
                message.from_user.id,
                message.from_user.full_name,
                message.chat.id,
                message.chat.type,
                selector,
                message.chat.title or message.chat.full_name,
            )
        except Exception as exc:
            await message.answer(provider_error_message(exc))
            return
    await message.answer(result)


@router.message(Command("project_info"))
async def project_info(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _send_context_result(message, "project_info")


@router.message(Command("invite_user"))
async def invite_user(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _send_context_result(message, "invite_user_placeholder")


@router.message(Command("members"))
async def members(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _send_context_result(message, "list_members")


@router.message(Command("role"))
async def role(message: Message, state: FSMContext) -> None:
    await state.clear()
    args = _command_args(message.text)
    if not message.reply_to_message or not message.reply_to_message.from_user or not args:
        await message.answer(
            "Ответь на сообщение участника командой /role admin, /role member или /role viewer."
        )
        return
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        context = await service.context_for_chat(
            message.from_user.id,
            message.chat.id,
            message.chat.type,
        )
        if context is None:
            await message.answer(SETUP_REQUIRED)
            return
        try:
            result = await service.set_member_role(
                context,
                message.reply_to_message.from_user.id,
                args[0],
            )
        except Exception as exc:
            await message.answer(provider_error_message(exc))
            return
    await message.answer(result)


@router.message(Command("meeting"))
async def meeting(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not await _has_selected_project(message):
        await message.answer(t("telegram.setup_required", await _message_locale(message)))
        return
    await state.set_state(MeetingStates.waiting_for_transcript)
    await message.answer(
        t("telegram.meeting_prompt", await _message_locale(message), types=SUPPORTED_DOCUMENT_TYPES)
    )


@router.message(MeetingStates.waiting_for_transcript, F.text & ~F.text.startswith("/"))
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
    progress = await message.answer("Голосовое получено. Расшифровываю.")
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        context = await service.context_for_chat(
            message.from_user.id,
            message.chat.id,
            message.chat.type,
        )
        if context is None:
            await progress.edit_text(SETUP_REQUIRED)
            return
        try:
            downloaded = await message.bot.download(media)
            if downloaded is None:
                await progress.edit_text("I could not download this recording from Telegram.")
                return
            await progress.edit_text("Запись скачана. Расшифровываю и анализирую встречу.")
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
    progress = await message.answer("Анализирую встречу.")
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        context = await service.context_for_chat(
            message.from_user.id,
            message.chat.id,
            message.chat.type,
        )
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
    await state.clear()
    if not await _has_selected_project(message):
        await message.answer(t("telegram.setup_required", await _message_locale(message)))
        return
    await state.set_state(DocumentStates.waiting_for_document)
    await message.answer(
        t(
            "telegram.document_prompt",
            await _message_locale(message),
            types=SUPPORTED_DOCUMENT_TYPES,
        )
    )


@router.message(DocumentStates.waiting_for_document, F.text & ~F.text.startswith("/"))
async def receive_document_text(message: Message, state: FSMContext) -> None:
    await state.clear()
    progress = await message.answer("Indexing document...")
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        context = await service.context_for_chat(
            message.from_user.id,
            message.chat.id,
            message.chat.type,
        )
        if context is None:
            await progress.edit_text(SETUP_REQUIRED)
            return
        result = await service.ingest_document_text(
            context,
            message.text or "",
            telegram_message_id=message.message_id,
        )
    await progress.edit_text(result)


@router.message(DocumentStates.waiting_for_document, F.document)
async def receive_document_file(message: Message, state: FSMContext) -> None:
    await state.clear()
    progress = await message.answer("Indexing document...")
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        context = await service.context_for_chat(
            message.from_user.id,
            message.chat.id,
            message.chat.type,
        )
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
                telegram_message_id=message.message_id,
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
        context = await service.context_for_chat(
            message.from_user.id,
            message.chat.id,
            message.chat.type,
        )
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
                telegram_message_id=message.message_id,
            )
        except Exception as exc:
            await progress.edit_text(provider_error_message(exc))
            return
    await progress.edit_text(result)


@router.message(DocumentStates.waiting_for_document, F.voice | F.audio)
async def receive_audio_document(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        t("telegram.recordings_are_meetings", await _message_locale(message))
    )


@router.message(Command("ask"))
async def ask(message: Message, state: FSMContext) -> None:
    await state.clear()
    question = " ".join(_command_args(message.text))
    if question:
        await _answer_question(message, question)
        return
    if not await _has_selected_project(message):
        await message.answer(t("telegram.setup_required", await _message_locale(message)))
        return
    await state.set_state(AskStates.waiting_for_question)
    await message.answer(t("telegram.ask_prompt", await _message_locale(message)))


@router.message(AskStates.waiting_for_question, F.text & ~F.text.startswith("/"))
async def receive_question(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _answer_question(message, message.text or "")


async def _answer_question(message: Message, question: str) -> None:
    progress = await message.answer("Searching team memory...")
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        context = await service.context_for_chat(
            message.from_user.id,
            message.chat.id,
            message.chat.type,
        )
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
async def tasks(message: Message, state: FSMContext) -> None:
    await state.clear()
    args = _command_args(message.text)
    if args and args[0].isdigit():
        await _send_context_result(message, "task_detail", int(args[0]))
        return
    await _send_context_result(message, "list_tasks")


@router.message(Command("task_done"))
async def task_done(message: Message, state: FSMContext) -> None:
    await state.clear()
    args = _command_args(message.text)
    if args and args[0].isdigit():
        await _update_task_status(message, int(args[0]), "done")
        return
    await state.set_state(TaskStates.waiting_for_done_task)
    await message.answer(t("telegram.task_number_prompt", await _message_locale(message)))


@router.message(TaskStates.waiting_for_done_task, F.text & ~F.text.startswith("/"))
async def receive_done_task(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not (message.text or "").strip().isdigit():
        await message.answer(t("telegram.task_number_prompt", await _message_locale(message)))
        return
    await _update_task_status(message, int((message.text or "").strip()), "done")


@router.message(Command("task_status"))
async def task_status(message: Message, state: FSMContext) -> None:
    await state.clear()
    args = _command_args(message.text)
    if len(args) >= 2 and args[0].isdigit():
        await _update_task_status(message, int(args[0]), args[1])
        return
    await state.set_state(TaskStates.waiting_for_status_update)
    await message.answer(
        t("telegram.task_status_prompt", await _message_locale(message))
    )


@router.message(TaskStates.waiting_for_status_update, F.text & ~F.text.startswith("/"))
async def receive_task_status(message: Message, state: FSMContext) -> None:
    await state.clear()
    args = (message.text or "").strip().split()
    if len(args) < 2 or not args[0].isdigit():
        await message.answer("Отправь номер задачи и статус, например: 2 blocked.")
        return
    await _update_task_status(message, int(args[0]), args[1])


@router.message(Command("decisions"))
async def decisions(message: Message, state: FSMContext) -> None:
    await state.clear()
    args = _command_args(message.text)
    if args and args[0].isdigit():
        await _send_context_result(message, "decision_detail", int(args[0]))
        return
    await _send_context_result(message, "list_decisions")


@router.message(Command("audit"))
async def audit(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _send_context_result(message, "list_audit")


@router.message(Command("reminders"))
async def reminders(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _send_context_result(message, "list_reminders")


@router.message(Command("status"))
async def status(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _send_context_result(message, "task_status_summary")


@router.message(Command("digest_today"))
async def digest_today(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _send_context_result(message, "digest", 1)


@router.message(Command("digest_week"))
async def digest_week(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _send_context_result(message, "digest", 7)


@router.message(Command("attention"))
async def attention(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _send_context_result(message, "attention")


@router.message(Command("topics"))
async def topics(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _send_context_result(message, "topics")


@router.message(Command("topic"))
async def topic(message: Message, state: FSMContext) -> None:
    await state.clear()
    query = " ".join(_command_args(message.text))
    await _send_context_result(message, "topic_detail", query)


@router.message(Command("people"))
async def people(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _send_context_result(message, "people")


@router.message(Command("person"))
async def person(message: Message, state: FSMContext) -> None:
    await state.clear()
    name = " ".join(_command_args(message.text))
    await _send_context_result(message, "person", name)


@router.message(Command("connect_calls", "call_setup"))
async def call_setup(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not is_live_listening_chat_type(message.chat.type):
        await message.answer(
            t("telegram.call_recording_group_only", await _message_locale(message))
        )
        return
    async with AsyncSessionFactory() as session:
        product_service = TelegramProductService(session)
        context = await product_service.context_for_chat(
            message.from_user.id,
            message.chat.id,
            message.chat.type,
        )
        if context is None:
            await message.answer(SETUP_REQUIRED)
            return
        result = await LiveMeetingListenerService(session).call_setup(context, message.chat.id)
    await message.answer(result.message, reply_markup=_call_setup_keyboard())


@router.message(Command("recorder_status"))
async def recorder_status(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not is_live_listening_chat_type(message.chat.type):
        await message.answer("Recorder status is only available in Telegram groups.")
        return
    async with AsyncSessionFactory() as session:
        product_service = TelegramProductService(session)
        context = await product_service.context_for_chat(
            message.from_user.id,
            message.chat.id,
            message.chat.type,
        )
        if context is None:
            await message.answer(SETUP_REQUIRED)
            return
        result = await LiveMeetingListenerService(session).recorder_status(
            context,
            message.chat.id,
        )
    await message.answer(result.message)


@router.callback_query(F.data == "recorder_status")
async def recorder_status_callback(callback: CallbackQuery) -> None:
    message = callback.message
    if message is None:
        await callback.answer("Open the group chat and use /recorder_status.")
        return
    async with AsyncSessionFactory() as session:
        product_service = TelegramProductService(session)
        context = await product_service.context_for_chat(
            callback.from_user.id,
            message.chat.id,
            message.chat.type,
        )
        if context is None:
            await callback.answer("Run /setup first.", show_alert=True)
            return
        result = await LiveMeetingListenerService(session).recorder_status(
            context,
            message.chat.id,
        )
    await callback.answer()
    await message.answer(result.message)


@router.callback_query(F.data == "start_listen")
async def start_listen_callback(callback: CallbackQuery) -> None:
    message = callback.message
    if message is None:
        await callback.answer("Open the group chat and use /listen.")
        return
    async with AsyncSessionFactory() as session:
        product_service = TelegramProductService(session)
        context = await product_service.context_for_chat(
            callback.from_user.id,
            message.chat.id,
            message.chat.type,
        )
        if context is None:
            await callback.answer("Run /setup first.", show_alert=True)
            return
        try:
            result = await LiveMeetingListenerService(session).start_listening(
                context,
                message.chat.id,
            )
        except ListenerError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
    await callback.answer()
    await message.answer(result.message)


@router.callback_query(F.data == "disable_call_recording")
async def disable_call_recording_callback(callback: CallbackQuery) -> None:
    message = callback.message
    if message is None:
        await callback.answer("Open the group chat and use /stop_listen.")
        return
    async with AsyncSessionFactory() as session:
        product_service = TelegramProductService(session)
        context = await product_service.context_for_chat(
            callback.from_user.id,
            message.chat.id,
            message.chat.type,
        )
        if context is None:
            await callback.answer("Run /setup first.", show_alert=True)
            return
        try:
            result = await LiveMeetingListenerService(session).stop_listening(
                context,
                message.chat.id,
            )
        except ListenerError:
            await callback.answer("No active listener is running.", show_alert=True)
            return
    await callback.answer()
    await message.answer(result.report)


@router.message(Command("listen"))
async def listen(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not is_live_listening_chat_type(message.chat.type):
        await message.answer(t("telegram.live_group_only", await _message_locale(message)))
        return
    async with AsyncSessionFactory() as session:
        product_service = TelegramProductService(session)
        context = await product_service.context_for_chat(
            message.from_user.id,
            message.chat.id,
            message.chat.type,
        )
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
async def stop_listen(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not is_live_listening_chat_type(message.chat.type):
        await message.answer(t("telegram.live_group_only", await _message_locale(message)))
        return
    async with AsyncSessionFactory() as session:
        product_service = TelegramProductService(session)
        context = await product_service.context_for_chat(
            message.from_user.id,
            message.chat.id,
            message.chat.type,
        )
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
async def live_status(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not is_live_listening_chat_type(message.chat.type):
        await message.answer(t("telegram.live_group_only", await _message_locale(message)))
        return
    async with AsyncSessionFactory() as session:
        product_service = TelegramProductService(session)
        context = await product_service.context_for_chat(
            message.from_user.id,
            message.chat.id,
            message.chat.type,
        )
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
        context = await service.context_for_chat(
            message.from_user.id,
            message.chat.id,
            message.chat.type,
        )
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
        context = await service.context_for_chat(
            message.from_user.id,
            message.chat.id,
            message.chat.type,
        )
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
                telegram_message_id=message.message_id,
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
        context = await service.context_for_chat(
            message.from_user.id,
            message.chat.id,
            message.chat.type,
        )
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
                telegram_message_id=message.message_id,
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
        context = await service.context_for_chat(
            message.from_user.id,
            message.chat.id,
            message.chat.type,
        )
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


async def _has_selected_project(message: Message) -> bool:
    async with AsyncSessionFactory() as session:
        context = await TelegramProductService(session).context_for_chat(
            message.from_user.id,
            message.chat.id,
            message.chat.type,
        )
    return context is not None


async def _send_context_result(message: Message, method_name: str, *args: object) -> None:
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        context = await service.context_for_chat(
            message.from_user.id,
            message.chat.id,
            message.chat.type,
        )
        if context is None:
            await message.answer(t("telegram.setup_required", await _message_locale(message)))
            return
        try:
            result = await getattr(service, method_name)(context, *args)
        except Exception as exc:
            await message.answer(provider_error_message(exc))
            return
    await message.answer(result)


async def _update_task_status(message: Message, task_number: int, status: str) -> None:
    async with AsyncSessionFactory() as session:
        service = TelegramProductService(session)
        context = await service.context_for_chat(
            message.from_user.id,
            message.chat.id,
            message.chat.type,
        )
        if context is None:
            await message.answer(t("telegram.setup_required", await _message_locale(message)))
            return
        try:
            result = await service.update_task_status(context, task_number, status)
        except Exception as exc:
            await message.answer(provider_error_message(exc))
            return
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


def _call_setup_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Check connection", callback_data="recorder_status"),
                InlineKeyboardButton(text="Start listening", callback_data="start_listen"),
            ],
            [
                InlineKeyboardButton(
                    text="Disable call recording",
                    callback_data="disable_call_recording",
                )
            ],
        ]
    )


async def _message_locale(message: Message, telegram_user_id: int | None = None) -> str:
    async with AsyncSessionFactory() as session:
        return await TelegramProductService(session).locale_for_chat(
            telegram_user_id or message.from_user.id,
            message.chat.id,
            message.chat.type,
        )


def _language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="English", callback_data="locale:en"),
                InlineKeyboardButton(text="Русский", callback_data="locale:ru"),
            ]
        ]
    )
