from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from talking_bot.db.models import Counterparty, Dialog, Message, MessageDirection


async def _dialog_for_counterparty(
    session: AsyncSession, counterparty: Counterparty, title: str
) -> Dialog:
    result = await session.execute(
        select(Dialog).where(Dialog.counterparty_id == counterparty.id)
    )
    dialog = result.scalars().first()
    if dialog is None:
        dialog = Dialog(counterparty_id=counterparty.id, title=title)
        session.add(dialog)
        await session.flush()
    return dialog


async def get_or_create_dialog(
    session: AsyncSession, tg_user_id: int | None = None, name: str = ""
) -> Dialog:
    """
    Один контрагент = один диалог (для стадии 1 этого достаточно —
    несколько параллельных диалогов с одним контрагентом добавим,
    если понадобится, без переделки остального).

    tg_user_id — Telegram-id заказчика (форвард с открытым отправителем).
    None — заказчик без Telegram (Авито, скрытый origin): ищем/создаём
    по имени без учёта регистра среди строк с пустым tg_user_id.
    """
    name = name.strip() or "Без имени"

    if tg_user_id is not None:
        result = await session.execute(
            select(Counterparty).where(Counterparty.tg_user_id == tg_user_id)
        )
        counterparty = result.scalar_one_or_none()
    else:
        result = await session.execute(
            select(Counterparty).where(
                Counterparty.tg_user_id.is_(None),
                func.lower(Counterparty.name) == name.lower(),
            )
        )
        counterparty = result.scalars().first()

    if counterparty is None:
        counterparty = Counterparty(tg_user_id=tg_user_id, name=name)
        session.add(counterparty)
        await session.flush()  # чтобы получить counterparty.id до создания диалога

        dialog = Dialog(counterparty_id=counterparty.id, title=name)
        session.add(dialog)
        await session.flush()
        return dialog

    return await _dialog_for_counterparty(session, counterparty, name)


async def find_counterparty_by_name(
    session: AsyncSession, name: str
) -> Counterparty | None:
    """Первый контрагент с таким именем без учёта регистра (любой tg_user_id)."""
    result = await session.execute(
        select(Counterparty)
        .where(func.lower(Counterparty.name) == name.lower())
        .order_by(Counterparty.id)
    )
    return result.scalars().first()


async def switch_or_create_dialog_by_name(
    session: AsyncSession, name: str
) -> tuple[Dialog, bool]:
    """
    Переключиться на существующий диалог по имени или завести нового
    контрагента без Telegram-id. Возвращает (dialog, created).
    """
    name = name.strip()
    existing = await find_counterparty_by_name(session, name)
    if existing is not None:
        dialog = await _dialog_for_counterparty(session, existing, existing.name)
        return dialog, False
    dialog = await get_or_create_dialog(session, tg_user_id=None, name=name)
    return dialog, True


async def get_dialog_by_topic_id(
    session: AsyncSession, topic_id: int
) -> Dialog | None:
    result = await session.execute(select(Dialog).where(Dialog.topic_id == topic_id))
    return result.scalar_one_or_none()


async def list_dialogs(session: AsyncSession) -> list[tuple[Dialog, Counterparty]]:
    result = await session.execute(
        select(Dialog, Counterparty)
        .join(Counterparty, Dialog.counterparty_id == Counterparty.id)
        .order_by(func.lower(Counterparty.name), Dialog.id)
    )
    return list(result.all())


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
