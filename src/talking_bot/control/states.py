from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Активный диалог живёт в FSM-данных, не в отдельном состоянии —
# иначе переключение заказчика сбивало бы «жду правку черновика».
ACTIVE_DIALOG_ID_KEY = "active_dialog_id"

NO_ACTIVE_DIALOG_TEXT = (
    "Сначала выберите диалог: кнопка «Новый диалог» или /dialog Имя\n"
    "Например: /dialog Иван. Список: «Диалоги» или /dialogs"
)


class EditDraft(StatesGroup):
    """
    Пока это состояние активно, бот ждёт от тебя текст правки для
    конкретного draft_id (хранится в FSM-данных). Любое другое сообщение
    в этот момент — это и есть правка, не новый форвард.
    """

    waiting_for_text = State()


class NewDialog(StatesGroup):
    """Ждём имя заказчика после кнопки «Новый диалог» или голого /dialog."""

    waiting_for_name = State()


class FindQuery(StatesGroup):
    """Ждём фразу поиска после кнопки «Поиск» или голого /find."""

    waiting_for_query = State()


class PlanEdit(StatesGroup):
    """Ждём текст плана после /plan или кнопки «План»."""

    waiting_for_text = State()


async def get_active_dialog_id(state: FSMContext) -> int | None:
    data = await state.get_data()
    raw = data.get(ACTIVE_DIALOG_ID_KEY)
    if raw is None:
        return None
    return int(raw)


async def set_active_dialog_id(state: FSMContext, dialog_id: int) -> None:
    await state.update_data({ACTIVE_DIALOG_ID_KEY: dialog_id})
