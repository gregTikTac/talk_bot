from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from talking_bot.control.keyboards import draft_keyboard
from talking_bot.control.states import EditDraft
from talking_bot.db.models import Draft, DraftStatus, MessageDirection
from talking_bot.db.session import get_session
from talking_bot.domain.dialog import add_message, get_or_create_dialog
from talking_bot.service.pipeline import recheck_edited_text, run_pipeline

router = Router()

_VERDICT_LABELS = {
    "in_plan": "✅ В рамках плана",
    "concession": "⚠️ Уступка",
    "red_line": "🔴 Нарушение красной линии",
}


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


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Перешлите мне сообщение заказчика — подготовлю черновик ответа "
        "и проверю его на соответствие плану переговоров."
    )


@router.message(F.forward_date | F.forward_origin)
async def handle_forwarded(message: Message) -> None:
    """
    Стадия 1 (без userbot): ты форвардишь сюда сообщение заказчика вручную.
    Каждый форвард считается новым входящим сообщением в диалоге с этим
    отправителем (Telegram-аккаунт, с которого ты пишешь боту, а не сам
    заказчик — контрагент в базе привязан к тебе, потому что userbot ещё
    не подключен).
    """
    incoming_text = message.text or message.caption
    if not incoming_text:
        await message.answer("В пересланном сообщении нет текста — не могу обработать.")
        return

    async with get_session() as session:
        dialog = await get_or_create_dialog(
            session, tg_user_id=message.from_user.id, name=message.from_user.full_name
        )
        result = await run_pipeline(session, dialog, incoming_text)

    card_text = _format_card(
        result.draft_text, result.verdict.status, _format_violations(result.verdict)
    )
    await message.answer(card_text, reply_markup=draft_keyboard(result.draft_id, result.verdict.status))


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
    """
    data = await state.get_data()
    draft_id = data["draft_id"]
    edited_text = message.text

    async with get_session() as session:
        draft = await session.get(Draft, draft_id)
        if draft is None:
            await message.answer("Черновик не найден.")
            await state.clear()
            return

        draft.text = edited_text
        verdict = await recheck_edited_text(session, draft.dialog_id, draft_id, edited_text)

    await state.clear()
    card_text = _format_card(edited_text, verdict.status, _format_violations(verdict))
    await message.answer(card_text, reply_markup=draft_keyboard(draft_id, verdict.status))
