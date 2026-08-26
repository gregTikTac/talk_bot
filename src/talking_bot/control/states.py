from aiogram.fsm.state import State, StatesGroup


class EditDraft(StatesGroup):
    """
    Пока это состояние активно, бот ждёт от тебя текст правки для
    конкретного draft_id (хранится в FSM-данных). Любое другое сообщение
    в этот момент — это и есть правка, не новый форвард.
    """
    waiting_for_text = State()
