from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select

from talking_bot.control.keyboards import main_keyboard
from talking_bot.control.states import FindQuery
from talking_bot.control.topics import operator_dialog_id
from talking_bot.db.models import Dialog, Message as MessageRow
from talking_bot.db.session import get_session

router = Router()

_MAX_RESULTS = 10
_SNIPPET_RADIUS = 80  # символов вокруг найденного слова, чтобы показать контекст


def _make_snippet(text: str, query: str) -> str:
    lower_text = text.lower()
    idx = lower_text.find(query.lower())
    if idx == -1:
        return text[:160]

    start = max(0, idx - _SNIPPET_RADIUS)
    end = min(len(text), idx + len(query) + _SNIPPET_RADIUS)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + text[start:end] + suffix


async def prompt_find(message: Message, state: FSMContext) -> None:
    _dialog_id, err = await operator_dialog_id(message, state)
    if err:
        await message.answer(err, reply_markup=main_keyboard())
        return
    await state.set_state(FindQuery.waiting_for_query)
    await message.answer(
        "Что искать в истории диалога? Напишите фразу.",
        reply_markup=main_keyboard(),
    )


async def run_find(message: Message, query: str, dialog_id: int) -> None:
    """
    Обычный поиск по подстроке (ILIKE), не векторный/семантический —
    так и договорились для старта: команда с ключевыми словами, бот
    отдаёт цитаты с датой. Ищет в указанном диалоге, не во всей базе.
    """
    async with get_session() as session:
        dialog = await session.get(Dialog, dialog_id)
        if dialog is None:
            from talking_bot.control.states import NO_ACTIVE_DIALOG_TEXT

            await message.answer(NO_ACTIVE_DIALOG_TEXT, reply_markup=main_keyboard())
            return
        result = await session.execute(
            select(MessageRow)
            .where(MessageRow.dialog_id == dialog.id, MessageRow.text.ilike(f"%{query}%"))
            .order_by(MessageRow.sent_at.desc())
            .limit(_MAX_RESULTS)
        )
        matches = list(result.scalars().all())

    if not matches:
        await message.answer(
            f"По запросу «{query}» ничего не нашлось в истории этого диалога.",
            reply_markup=main_keyboard(),
        )
        return

    lines = [f"Найдено {len(matches)} (показаны последние по времени):\n"]
    for m in matches:
        arrow = "→" if m.direction.value == "out" else "←"
        date_str = m.sent_at.strftime("%d.%m.%Y")
        snippet = _make_snippet(m.text, query)
        lines.append(f"{arrow} {date_str}: {snippet}")

    await message.answer("\n\n".join(lines), reply_markup=main_keyboard())


@router.message(Command("find"))
async def cmd_find(message: Message, command: CommandObject, state: FSMContext) -> None:
    query = command.args
    if not query or not query.strip():
        await prompt_find(message, state)
        return
    query = query.strip()
    await state.set_state(None)

    dialog_id, err = await operator_dialog_id(message, state)
    if err:
        await message.answer(err, reply_markup=main_keyboard())
        return
    await run_find(message, query, dialog_id)
