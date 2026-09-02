"""
Топики супергруппы — настоящее «окно на заказчика», как список тем
в Telegram Desktop. Личка бота такое окно нарисовать не может.

Правило карточек: если задан CONTROL_CHAT_ID и у диалога есть topic_id,
карточка уходит в топик заказчика. Если оператор писал не из этого топика
(личка, General, чужая тема) — туда же короткое «черновик в топике».
Без группы или без топика карточка отвечает в текущий чат, как раньше.
"""

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from talking_bot.config import settings
from talking_bot.control.keyboards import draft_keyboard, main_keyboard
from talking_bot.control.states import NO_ACTIVE_DIALOG_TEXT, get_active_dialog_id
from talking_bot.db.models import Dialog
from talking_bot.db.session import get_session
from talking_bot.domain.dialog import get_dialog_by_topic_id

# Служебная тема «General» в форуме Telegram всегда имеет thread_id = 1.
GENERAL_TOPIC_ID = 1
_TOPIC_NAME_MAX = 128

GENERAL_TOPIC_HINT = (
    "Тема General — не заказчик.\n"
    "Откройте топик нужного человека или создайте диалог: "
    "«Новый диалог» / /dialog Имя"
)

UNMAPPED_TOPIC_HINT = (
    "Эта тема не привязана к заказчику.\n"
    "Откройте топик заказчика или создайте диалог: «Новый диалог» / /dialog Имя"
)


def is_control_chat(message: Message) -> bool:
    if settings.control_chat_id is None:
        return False
    if message.chat.type not in ("group", "supergroup"):
        return False
    return message.chat.id == settings.control_chat_id


def is_general_topic(message: Message) -> bool:
    if not is_control_chat(message):
        return False
    thread_id = message.message_thread_id
    return thread_id is None or thread_id == GENERAL_TOPIC_ID


def explain_topic_error(exc: BaseException) -> str:
    raw = str(exc).lower()
    if "chat not found" in raw:
        return (
            "Не нашёл группу CONTROL_CHAT_ID. Проверьте id "
            "(обычно начинается с −100) и что бот добавлен в эту супергруппу."
        )
    if (
        "not a forum" in raw
        or "topics are disabled" in raw
        or "topic_closed" in raw
        or "topics_not_supported" in raw
    ):
        return (
            "В этой группе не включены темы. Telegram Desktop: "
            "настройки группы → Темы / Forum → включить. "
            "Нужна супергруппа, не обычная группа."
        )
    if (
        "not enough rights" in raw
        or "manage topic" in raw
        or "can't manage" in raw
        or "forbidden" in raw
        or "not a member" in raw
    ):
        return (
            "Боту не хватает прав. Сделайте его администратором супергруппы "
            "и включите «Управление темами» и отправку сообщений."
        )
    return (
        "Не удалось создать или написать в топик. Проверьте: супергруппа, "
        "темы включены, бот — админ с правом «Управление темами», "
        f"CONTROL_CHAT_ID верный. Ответ Telegram: {exc}"
    )


def _topic_name(title: str) -> str:
    name = (title or "Без имени").strip() or "Без имени"
    if len(name) <= _TOPIC_NAME_MAX:
        return name
    return name[: _TOPIC_NAME_MAX - 1] + "…"


async def ensure_forum_topic(bot: Bot, session: AsyncSession, dialog: Dialog) -> str | None:
    """
    Создаёт топик, если CONTROL_CHAT_ID задан и у диалога ещё нет topic_id.
    Возвращает текст ошибки для оператора или None, если всё ок / топики выключены.
    """
    if settings.control_chat_id is None:
        return None
    if dialog.topic_id is not None:
        return None

    try:
        topic = await bot.create_forum_topic(
            chat_id=settings.control_chat_id,
            name=_topic_name(dialog.title),
        )
    except TelegramAPIError as exc:
        return explain_topic_error(exc)

    dialog.topic_id = topic.message_thread_id
    await session.flush()

    try:
        await bot.send_message(
            chat_id=settings.control_chat_id,
            text=(
                f"Диалог «{dialog.title}». Пишите сюда сообщения этого заказчика — "
                "черновики будут приходить в эту тему."
            ),
            message_thread_id=dialog.topic_id,
            reply_markup=main_keyboard(),
        )
    except TelegramAPIError:
        # Топик уже есть в базе; приветствие — необязательно.
        pass
    return None


async def ensure_dialog_topic(bot: Bot, dialog_id: int) -> str | None:
    if settings.control_chat_id is None:
        return None
    async with get_session() as session:
        dialog = await session.get(Dialog, dialog_id)
        if dialog is None:
            return None
        return await ensure_forum_topic(bot, session, dialog)


async def operator_dialog_id(
    message: Message, state: FSMContext
) -> tuple[int | None, str | None]:
    """
    Диалог оператора: топик группы важнее FSM.
    General не считается заказчиком (вставка там отсекается отдельно);
    команды вроде /find могут взять активный диалог из FSM.
    """
    if is_control_chat(message) and not is_general_topic(message):
        thread_id = message.message_thread_id
        if thread_id is not None:
            async with get_session() as session:
                dialog = await get_dialog_by_topic_id(session, thread_id)
            if dialog is None:
                return None, UNMAPPED_TOPIC_HINT
            return dialog.id, None

    dialog_id = await get_active_dialog_id(state)
    if dialog_id is None:
        return None, NO_ACTIVE_DIALOG_TEXT
    return dialog_id, None


def _in_dialog_topic(message: Message, dialog: Dialog) -> bool:
    if dialog.topic_id is None or not is_control_chat(message):
        return False
    return message.message_thread_id == dialog.topic_id


async def send_draft_card(
    message: Message,
    dialog: Dialog,
    card_text: str,
    verdict_status: str,
    draft_id: int,
) -> None:
    markup = draft_keyboard(draft_id, verdict_status)
    topic_id = dialog.topic_id
    control_id = settings.control_chat_id

    if control_id is not None and topic_id is not None and not _in_dialog_topic(message, dialog):
        try:
            await message.bot.send_message(
                chat_id=control_id,
                text=card_text,
                reply_markup=markup,
                message_thread_id=topic_id,
            )
        except TelegramAPIError as exc:
            await message.answer(
                f"{explain_topic_error(exc)}\n\nКарточка здесь:\n\n{card_text}",
                reply_markup=markup,
            )
            return
        await message.answer(
            f"Черновик отправил в топик «{dialog.title}».",
            reply_markup=main_keyboard(),
        )
        return

    await message.answer(card_text, reply_markup=markup)
