from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# callback_data формата "действие:draft_id" — aiogram ограничивает длину
# callback_data 64 байтами, поэтому в кнопке только id, а не весь текст.


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
