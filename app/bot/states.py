from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class MeetingStates(StatesGroup):
    waiting_for_transcript = State()


class DocumentStates(StatesGroup):
    waiting_for_document = State()


class AskStates(StatesGroup):
    waiting_for_question = State()


class TaskStates(StatesGroup):
    waiting_for_done_task = State()
    waiting_for_status_update = State()