from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select

from talking_bot.db.models import Message as MessageRow
from talking_bot.db.session import get_session
from talking_bot.domain.dialog import get_or_create_dialog

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


@router.message(Command("find"))
async def cmd_find(message: Message, command: CommandObject) -> None:
    """
    Обычный поиск по подстроке (ILIKE), не векторный/семантический —
    так и договорились для старта: команда с ключевыми словами, бот
    отдаёт цитаты с датой. Простое и предсказуемое поведение важнее
    "умного" поиска, который может не найти то, что ищешь дословно.
    """
    query = command.args
    if not query or not query.strip():
        await message.answer("Использование: /find <фраза для поиска>\nНапример: /find видеоуроки")
        return
    query = query.strip()

    async with get_session() as session:
        dialog = await get_or_create_dialog(
            session, tg_user_id=message.from_user.id, name=message.from_user.full_name
        )
        result = await session.execute(
            select(MessageRow)
            .where(MessageRow.dialog_id == dialog.id, MessageRow.text.ilike(f"%{query}%"))
            .order_by(MessageRow.sent_at.desc())
            .limit(_MAX_RESULTS)
        )
        matches = list(result.scalars().all())

    if not matches:
        await message.answer(f"По запросу «{query}» ничего не нашлось в истории этого диалога.")
        return

    lines = [f"Найдено {len(matches)} (показаны последние по времени):\n"]
    for m in matches:
        arrow = "→" if m.direction.value == "out" else "←"
        date_str = m.sent_at.strftime("%d.%m.%Y")
        snippet = _make_snippet(m.text, query)
        lines.append(f"{arrow} {date_str}: {snippet}")

    await message.answer("\n\n".join(lines))
