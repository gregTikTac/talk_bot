from aiogram import F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    Message,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginHiddenUser,
    MessageOriginUser,
)

from talking_bot.control.keyboards import (
    BTN_DIALOGS,
    BTN_FIND,
    BTN_HELP,
    BTN_NEW_DIALOG,
    draft_keyboard,
    main_keyboard,
)
from talking_bot.control.states import (
    EditDraft,
    FindQuery,
    NewDialog,
    NO_ACTIVE_DIALOG_TEXT,
    get_active_dialog_id,
    set_active_dialog_id,
)
from talking_bot.control.topics import (
    GENERAL_TOPIC_HINT,
    ensure_dialog_topic,
    ensure_forum_topic,
    is_control_chat,
    is_general_topic,
    operator_dialog_id,
    send_draft_card,
)
from talking_bot.db.models import Dialog, Draft, DraftStatus, MessageDirection
from talking_bot.db.session import get_session
from talking_bot.domain.dialog import (
    add_message,
    get_or_create_dialog,
    list_dialogs,
    switch_or_create_dialog_by_name,
)
from talking_bot.service.pipeline import recheck_edited_text, run_pipeline

# Команды /dialog и /dialogs — отдельный роутер, подключается в app.py
# раньше основного, чтобы F.text-ловушка для вставок их не перехватила.
dialog_router = Router()
router = Router()

_NOT_FORWARD = ~(F.forward_date | F.forward_origin)
_NOT_EDITING = ~StateFilter(EditDraft.waiting_for_text)

_VERDICT_LABELS = {
    "in_plan": "✅ В рамках плана",
    "concession": "⚠️ Уступка",
    "red_line": "🔴 Нарушение красной линии",
}

START_TEXT = (
    "Пришлите сообщение заказчика — подготовлю черновик ответа "
    "и проверю его на соответствие плану переговоров.\n\n"
    "Пересланное из Telegram само привяжется к отправителю.\n"
    "Текст с Авито вставьте в топик заказчика или после выбора диалога.\n\n"
    "Кнопки внизу:\n"
    "• «Диалоги» — список\n"
    "• «Новый диалог» — создать или переключить по имени\n"
    "• «Поиск» — найти фразу в истории\n"
    "• «Справка» — этот текст\n"
    "Слева от поля ввода — меню тех же команд (/start, /dialogs, /dialog, /find, /import).\n\n"
    "Как получить окно со списком тем, как в Telegram Desktop\n"
    "Личка с ботом такое окно не рисует. Это супергруппа с темами (Topics / Forum):\n"
    "1. Создайте группу (или возьмите существующую) и сделайте её супергруппой.\n"
    "2. Настройки группы → Темы / Forum → включить.\n"
    "3. Добавьте этого бота администратором, включите «Управление темами» и отправку сообщений.\n"
    "4. Скопируйте id группы (обычно −100…; можно переслать сообщение из группы "
    "боту вроде @userinfobot) и пропишите CONTROL_CHAT_ID в .env.\n"
    "5. Перезапустите бота.\n\n"
    "После этого на каждого заказчика появится отдельная тема. Пишите в теме "
    "заказчика — вставки и черновики пойдут туда. Тема General — не заказчик.\n\n"
    "Карточки: если группа настроена и у диалога есть топик — черновик уходит "
    "в эту тему (из лички придёт короткое уведомление). Без CONTROL_CHAT_ID "
    "всё как раньше: /dialog, кнопки и карточки в личке."
)


def _format_card(draft_text: str, verdict_status: str, violations_text: str) -> str:
    label = _VERDICT_LABELS[verdict_status]
    body = f"{label}\n\n{draft_text}"
    if violations_text:
        body += f"\n\n{violations_text}"
    return body


def _format_violations(verdict) -> str:
    if not verdict.violations:
        return ""
    lines = [f"— {v.plan_item_code}: «{v.quote}» — {v.why}" for v in verdict.violations]
    return "\n".join(lines)


def _counterparty_from_forward(message: Message) -> tuple[int | None, str]:
    """Заказчик из origin форварда, не оператор, который пишет боту."""
    origin = message.forward_origin
    if isinstance(origin, MessageOriginUser):
        user = origin.sender_user
        return user.id, user.full_name or user.username or str(user.id)
    if isinstance(origin, MessageOriginHiddenUser):
        return None, origin.sender_user_name or "Скрытый отправитель"
    if isinstance(origin, MessageOriginChat):
        chat = origin.sender_chat
        return None, chat.title or origin.author_signature or "Чат"
    if isinstance(origin, MessageOriginChannel):
        chat = origin.chat
        return None, chat.title or origin.author_signature or "Канал"
    if message.forward_from is not None:
        user = message.forward_from
        return user.id, user.full_name or user.username or str(user.id)
    if message.forward_sender_name:
        return None, message.forward_sender_name
    return None, "Неизвестный отправитель"


async def _activate_dialog(
    message: Message, state: FSMContext, name: str
) -> None:
    name = name.strip()
    if not name:
        await message.answer(
            "Напишите имя заказчика, например: Иван",
            reply_markup=main_keyboard(),
        )
        return

    async with get_session() as session:
        dialog, created = await switch_or_create_dialog_by_name(session, name)
        title = dialog.title
        dialog_id = dialog.id
        topic_error = await ensure_forum_topic(message.bot, session, dialog)
        topic_id = dialog.topic_id

    await set_active_dialog_id(state, dialog_id)
    await state.set_state(None)

    if created:
        text = f"Создал диалог «{title}». Дальнейшие вставки с Авито пойдут сюда."
    else:
        text = f"Диалог: {title}. Дальнейшие вставки с Авито пойдут сюда."
    if topic_id is not None:
        text += f"\nТопик в группе: «{title}»."
    if topic_error:
        text += f"\n\n{topic_error}"
    await message.answer(text, reply_markup=main_keyboard())


async def _process_incoming(
    message: Message,
    incoming_text: str,
    source: str,
    *,
    dialog_id: int | None = None,
    tg_user_id: int | None = None,
    name: str | None = None,
) -> int | None:
    """
    Прогоняет пайплайн в указанном диалоге.
    Возвращает dialog.id при успехе, None если уже ответили об ошибке.
    """
    try:
        async with get_session() as session:
            if dialog_id is not None:
                dialog = await session.get(Dialog, dialog_id)
                if dialog is None:
                    await message.answer(NO_ACTIVE_DIALOG_TEXT, reply_markup=main_keyboard())
                    return None
            elif name is not None and tg_user_id is None:
                dialog, _created = await switch_or_create_dialog_by_name(session, name)
            else:
                dialog = await get_or_create_dialog(
                    session, tg_user_id=tg_user_id, name=name or "Без имени"
                )
            resolved_id = dialog.id

        topic_error = await ensure_dialog_topic(message.bot, resolved_id)
        if topic_error:
            await message.answer(topic_error, reply_markup=main_keyboard())

        async with get_session() as session:
            dialog = await session.get(Dialog, resolved_id)
            if dialog is None:
                await message.answer(NO_ACTIVE_DIALOG_TEXT, reply_markup=main_keyboard())
                return None
            result = await run_pipeline(session, dialog, incoming_text, source=source)
    except Exception:
        await message.answer(
            "Не удалось составить черновик: модель вернула пустой или битый ответ. "
            "Попробуйте ещё раз.",
            reply_markup=main_keyboard(),
        )
        return None

    card_text = _format_card(
        result.draft_text, result.verdict.status, _format_violations(result.verdict)
    )
    await send_draft_card(
        message, dialog, card_text, result.verdict.status, result.draft_id
    )
    return resolved_id


@dialog_router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.set_state(None)
    await message.answer(START_TEXT, reply_markup=main_keyboard())


@dialog_router.message(Command("dialogs"))
async def cmd_dialogs(message: Message, state: FSMContext) -> None:
    await state.set_state(None)
    resolved_id, err = await operator_dialog_id(message, state)
    active_id = resolved_id if err is None else await get_active_dialog_id(state)
    async with get_session() as session:
        rows = await list_dialogs(session)

    if not rows:
        await message.answer(
            "Пока нет ни одного диалога. Перешлите сообщение заказчика "
            "или создайте: «Новый диалог» / /dialog Имя",
            reply_markup=main_keyboard(),
        )
        return

    lines = ["Диалоги:\n"]
    for dialog, counterparty in rows:
        mark = "→ " if dialog.id == active_id else "   "
        topic = " · тема" if dialog.topic_id is not None else ""
        lines.append(f"{mark}{counterparty.name}{topic}")
    lines.append("\nАктивный помечен стрелкой. Переключение: «Новый диалог» или /dialog Имя")
    await message.answer("\n".join(lines), reply_markup=main_keyboard())


@dialog_router.message(Command("dialog"))
async def cmd_dialog(message: Message, command: CommandObject, state: FSMContext) -> None:
    name = (command.args or "").strip()
    if not name:
        await state.set_state(NewDialog.waiting_for_name)
        await message.answer(
            "Как зовут заказчика? Напишите имя — например, Иван.",
            reply_markup=main_keyboard(),
        )
        return
    await _activate_dialog(message, state, name)


@dialog_router.message(F.text == BTN_HELP, _NOT_EDITING, _NOT_FORWARD)
async def btn_help(message: Message, state: FSMContext) -> None:
    await cmd_start(message, state)


@dialog_router.message(F.text == BTN_DIALOGS, _NOT_EDITING, _NOT_FORWARD)
async def btn_dialogs(message: Message, state: FSMContext) -> None:
    await state.set_state(None)
    await cmd_dialogs(message, state)


@dialog_router.message(F.text == BTN_NEW_DIALOG, _NOT_EDITING, _NOT_FORWARD)
async def btn_new_dialog(message: Message, state: FSMContext) -> None:
    await state.set_state(NewDialog.waiting_for_name)
    await message.answer(
        "Как зовут заказчика? Напишите имя — например, Иван.",
        reply_markup=main_keyboard(),
    )


@dialog_router.message(F.text == BTN_FIND, _NOT_EDITING, _NOT_FORWARD)
async def btn_find(message: Message, state: FSMContext) -> None:
    from talking_bot.control.find_handler import prompt_find

    await prompt_find(message, state)


@dialog_router.message(NewDialog.waiting_for_name, F.text, _NOT_FORWARD)
async def handle_new_dialog_name(message: Message, state: FSMContext) -> None:
    await _activate_dialog(message, state, message.text or "")


@dialog_router.message(FindQuery.waiting_for_query, F.text, _NOT_FORWARD)
async def handle_find_query(message: Message, state: FSMContext) -> None:
    from talking_bot.control.find_handler import run_find

    query = (message.text or "").strip()
    await state.set_state(None)
    if not query:
        await message.answer("Пустой запрос. Напишите фразу для поиска.", reply_markup=main_keyboard())
        return

    dialog_id, err = await operator_dialog_id(message, state)
    if err:
        await message.answer(err, reply_markup=main_keyboard())
        return
    await run_find(message, query, dialog_id)


@router.message(F.forward_date | F.forward_origin)
async def handle_forwarded(message: Message, state: FSMContext) -> None:
    """
    Форвард считается входящим от исходного отправителя (forward_origin),
    не от оператора. После успешной обработки этот диалог становится
    активным — следующая вставка с Авито продолжит ту же нить.
    """
    incoming_text = message.text or message.caption
    if not incoming_text:
        await message.answer(
            "В пересланном сообщении нет текста — не могу обработать.",
            reply_markup=main_keyboard(),
        )
        return

    tg_user_id, name = _counterparty_from_forward(message)
    dialog_id = await _process_incoming(
        message, incoming_text, source="forward", tg_user_id=tg_user_id, name=name
    )
    if dialog_id is not None:
        await set_active_dialog_id(state, dialog_id)


@router.callback_query(F.data.startswith("send:"))
async def handle_send(callback: CallbackQuery) -> None:
    draft_id = int(callback.data.split(":", 1)[1])

    async with get_session() as session:
        draft = await session.get(Draft, draft_id)
        if draft is None:
            await callback.answer("Черновик не найден.", show_alert=True)
            return
        draft.status = DraftStatus.SENT
        await add_message(session, draft.dialog_id, draft.text, MessageDirection.OUT, source="forward")

    await callback.message.edit_text(
        callback.message.text + "\n\n📤 Отправлено (отметьте вручную в чате с заказчиком).",
        reply_markup=None,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("skip:"))
async def handle_skip(callback: CallbackQuery) -> None:
    draft_id = int(callback.data.split(":", 1)[1])

    async with get_session() as session:
        draft = await session.get(Draft, draft_id)
        if draft is not None:
            draft.status = DraftStatus.DISCARDED

    await callback.message.edit_text(callback.message.text + "\n\n⏭ Пропущено.", reply_markup=None)
    await callback.answer()


@router.callback_query(F.data.startswith("edit:"))
async def handle_edit_request(callback: CallbackQuery, state: FSMContext) -> None:
    draft_id = int(callback.data.split(":", 1)[1])
    await state.set_state(EditDraft.waiting_for_text)
    await state.update_data(draft_id=draft_id)
    await callback.message.answer("Пришлите новый текст ответа — проверю его так же, как черновик.")
    await callback.answer()


@router.message(EditDraft.waiting_for_text)
async def handle_edit_text(message: Message, state: FSMContext) -> None:
    """
    Ни один байт не уходит в Telegram, минуя guard — в том числе твоя
    собственная правка. Кнопка "Изменить" не должна быть каналом обхода.
    Состояние сбрасываем без clear(), чтобы не потерять активный диалог.
    """
    data = await state.get_data()
    draft_id = data["draft_id"]
    edited_text = message.text

    async with get_session() as session:
        draft = await session.get(Draft, draft_id)
        if draft is None:
            await message.answer("Черновик не найден.", reply_markup=main_keyboard())
            await state.set_state(None)
            return

        draft.text = edited_text
        dialog = await session.get(Dialog, draft.dialog_id)
        verdict = await recheck_edited_text(session, draft.dialog_id, draft_id, edited_text)

    await state.set_state(None)
    card_text = _format_card(edited_text, verdict.status, _format_violations(verdict))
    if dialog is not None:
        await send_draft_card(message, dialog, card_text, verdict.status, draft_id)
    else:
        await message.answer(card_text, reply_markup=draft_keyboard(draft_id, verdict.status))


@router.message(F.text, ~F.text.startswith("/"))
async def handle_pasted_text(message: Message, state: FSMContext) -> None:
    """
    Скопированный текст с Авито и других площадок, откуда нельзя сделать
    форвард. В топике заказчика активный /dialog не нужен — берём диалог
    по topic_id. Команды, кнопки меню и «жду правку черновика» раньше.
    """
    incoming_text = message.text.strip() if message.text else ""
    if not incoming_text:
        await message.answer(
            "Пустое сообщение — вставьте текст заказчика или перешлите его.",
            reply_markup=main_keyboard(),
        )
        return

    if is_control_chat(message) and is_general_topic(message):
        await message.answer(GENERAL_TOPIC_HINT, reply_markup=main_keyboard())
        return

    dialog_id, err = await operator_dialog_id(message, state)
    if err:
        await message.answer(err, reply_markup=main_keyboard())
        return

    await set_active_dialog_id(state, dialog_id)
    await _process_incoming(
        message, incoming_text, source="paste", dialog_id=dialog_id
    )
