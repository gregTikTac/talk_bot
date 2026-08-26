from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from talking_bot.db.models import Counterparty, Dialog, Message, MessageDirection


async def get_or_create_dialog(session: AsyncSession, tg_user_id: int, name: str) -> Dialog:
    """
    Один контрагент = один диалог (для стадии 1 этого достаточно —
    несколько параллельных диалогов с одним контрагентом добавим,
    если понадобится, без переделки остального).
    """
    result = await session.execute(
        select(Counterparty).where(Counterparty.tg_user_id == tg_user_id)
    )
    counterparty = result.scalar_one_or_none()

    if counterparty is None:
        counterparty = Counterparty(tg_user_id=tg_user_id, name=name)
        session.add(counterparty)
        await session.flush()  # чтобы получить counterparty.id до создания диалога

        dialog = Dialog(counterparty_id=counterparty.id, title=name)
        session.add(dialog)
        await session.flush()
        return dialog

    result = await session.execute(
        select(Dialog).where(Dialog.counterparty_id == counterparty.id)
    )
    dialog = result.scalars().first()
    if dialog is None:
        dialog = Dialog(counterparty_id=counterparty.id, title=name)
        session.add(dialog)
        await session.flush()
    return dialog


async def add_message(
    session: AsyncSession,
    dialog_id: int,
    text: str,
    direction: MessageDirection,
    source: str,
    tg_message_id: int | None = None,
    sent_at: datetime | None = None,
) -> Message:
    """
    sent_at по умолчанию — момент вызова (обычный случай: сообщение
    только что пришло в бота). При импорте истории (source="import")
    передавайте настоящее время сообщения явно — иначе вся история
    ляжет с одной и той же меткой времени и порядок сообщений будет
    держаться только на случайном совпадении id с порядком вставки.
    """
    message = Message(
        dialog_id=dialog_id,
        direction=direction,
        text=text,
        source=source,
        tg_message_id=tg_message_id,
        sent_at=sent_at or datetime.now(timezone.utc),
    )
    session.add(message)
    await session.flush()
    return message


async def get_recent_messages(
    session: AsyncSession, dialog_id: int, limit: int = 30
) -> list[Message]:
    """
    Последние N сообщений в хронологическом порядке (старые сначала).
    Сортируем по sent_at, а не по id — после импорта истории (см.
    ingest/telegram_export.py) реальное время сообщения и порядок его
    вставки в базу это разные вещи.
    """
    result = await session.execute(
        select(Message)
        .where(Message.dialog_id == dialog_id)
        .order_by(Message.sent_at.desc())
        .limit(limit)
    )
    messages = list(result.scalars().all())
    messages.reverse()
    return messages
