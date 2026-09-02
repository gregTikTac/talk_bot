from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# callback_data формата "действие:draft_id" — aiogram ограничивает длину
# callback_data 64 байтами, поэтому в кнопке только id, а не весь текст.

BTN_DIALOGS = "Диалоги"
BTN_NEW_DIALOG = "Новый диалог"
BTN_PLAN = "План"
BTN_FIND = "Поиск"
BTN_HELP = "Справка"

BOT_COMMANDS = [
    BotCommand(command="start", description="Справка и настройка группы с темами"),
    BotCommand(command="dialogs", description="Список диалогов"),
    BotCommand(command="dialog", description="Создать или переключить диалог"),
    BotCommand(command="plan", description="План переговоров активного диалога"),
    BotCommand(command="find", description="Поиск по истории диалога"),
    BotCommand(command="import", description="Как загрузить историю чата"),
    BotCommand(command="import_file", description="Импорт JSON-экспорта (нужен файл)"),
]


def draft_keyboard(draft_id: int, verdict_status: str) -> InlineKeyboardMarkup:
    """
    На red_line кнопка "Отправить" намеренно отсутствует — единственный
    способ отправить нарушение красной линии - explicitly набрать кодовую
    фразу через /override (см. control/handlers.py). Одна кнопка это делать
    не должна: трение здесь предусмотрено архитектурой, не забыто.
    """
    buttons: list[list[InlineKeyboardButton]] = []

    if verdict_status != "red_line":
        buttons.append([
            InlineKeyboardButton(text="✅ Отправить", callback_data=f"send:{draft_id}"),
        ])

    buttons.append([
        InlineKeyboardButton(text="✏️ Изменить", callback_data=f"edit:{draft_id}"),
        InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"skip:{draft_id}"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def main_keyboard() -> ReplyKeyboardMarkup:
    """
    Постоянные кнопки внизу экрана. Не перехватывают форварды и произвольный
    текст заказчика — в handlers стоят как точное совпадение строки.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_DIALOGS), KeyboardButton(text=BTN_NEW_DIALOG)],
            [KeyboardButton(text=BTN_PLAN), KeyboardButton(text=BTN_FIND)],
            [KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Вставка заказчика или команда",
    )
