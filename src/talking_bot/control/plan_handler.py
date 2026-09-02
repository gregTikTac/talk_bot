from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from talking_bot.control.keyboards import main_keyboard
from talking_bot.control.states import PlanEdit
from talking_bot.control.topics import operator_dialog_id
from talking_bot.db.models import Dialog
from talking_bot.db.session import get_session
from talking_bot.domain.plan import (
    extract_changelog,
    format_plan,
    get_active_plan,
    get_plan_items,
    parse_plan_text,
    replace_active_plan,
)

router = Router()

PLAN_HELP = (
    "Это не история переписки, а правила для guard: цена, объём, что нельзя обещать.\n\n"
    "Формат — одна строка на пункт, поля через | :\n"
    "код | вид | заголовок | значение | fallback | сигнал нарушения\n\n"
    "вид: красная / цель / гибко\n"
    "У красной линии fallback и сигнал обязательны. «—» = пусто.\n"
    "Первая строка может быть: changelog: зачем меняем\n\n"
    "Пример для Умиды (можно скопировать и поправить):\n\n"
    "PRICE | красная | Цена варианта 2 | 30 000 ₽ за весь курс | не снижать в чате, вынести в отдельное обсуждение | скидка, дешевле, 20 000 за тот же вариант 2\n"
    "HOURS | красная | Объём 15 часов с июля | 15 часов в текущем этапе | сверх объёма — отдельный этап | бесплатно ещё уроки, в ту же сумму\n"
    "PILOT | цель | Пилот доделываем как обещали | пилотный урок в любом случае | — | —\n"
    "PAY | гибко | Оплата | 15 000 сейчас, остальное после пилота | предоплата 15к уже ок | требую всю сумму до пилота"
)


async def show_plan(message: Message, dialog_id: int) -> None:
    async with get_session() as session:
        plan = await get_active_plan(session, dialog_id)
        items = await get_plan_items(session, plan.id) if plan else []
        body = format_plan(plan, items)
    await message.answer(body, reply_markup=main_keyboard())


async def prompt_plan(message: Message, state: FSMContext) -> None:
    dialog_id, err = await operator_dialog_id(message, state)
    if err:
        await message.answer(err, reply_markup=main_keyboard())
        return
    await show_plan(message, dialog_id)
    await state.set_state(PlanEdit.waiting_for_text)
    await message.answer(
        "Пришлите новый план одним сообщением — станет новой версией "
        "(старая останется в базе).\n\n" + PLAN_HELP,
        reply_markup=main_keyboard(),
    )


async def save_plan_text(message: Message, raw: str, dialog_id: int) -> bool:
    try:
        items = parse_plan_text(raw)
    except ValueError as exc:
        await message.answer(
            f"Не разобрал план:\n{exc}\n\nПоправьте и пришлите ещё раз.",
            reply_markup=main_keyboard(),
        )
        return False

    changelog = extract_changelog(raw)
    async with get_session() as session:
        dialog = await session.get(Dialog, dialog_id)
        if dialog is None:
            from talking_bot.control.states import NO_ACTIVE_DIALOG_TEXT

            await message.answer(NO_ACTIVE_DIALOG_TEXT, reply_markup=main_keyboard())
            return False
        plan = await replace_active_plan(session, dialog_id, items, changelog)
        stored = await get_plan_items(session, plan.id)
        body = format_plan(plan, stored)
    await message.answer("Сохранил.\n\n" + body, reply_markup=main_keyboard())
    return True


@router.message(Command("plan"))
async def cmd_plan(message: Message, command: CommandObject, state: FSMContext) -> None:
    args = (command.args or "").strip()
    dialog_id, err = await operator_dialog_id(message, state)
    if err:
        await message.answer(err, reply_markup=main_keyboard())
        return

    if not args:
        await prompt_plan(message, state)
        return

    await state.set_state(None)
    await save_plan_text(message, args, dialog_id)
