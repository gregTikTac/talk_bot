import tempfile
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from talking_bot.control.keyboards import main_keyboard
from talking_bot.control.states import NO_ACTIVE_DIALOG_TEXT
from talking_bot.control.topics import operator_dialog_id
from talking_bot.db.models import Dialog, MessageDirection
from talking_bot.db.session import get_session
from talking_bot.domain.dialog import add_message
from talking_bot.ingest.telegram_export import parse_export

router = Router()


@router.message(Command("import"))
async def cmd_import_help(message: Message) -> None:
    await message.answer(
        "Чтобы загрузить историю переписки:\n"
        "1. В Telegram Desktop → чат с заказчиком → ⋮ → Экспорт истории чата "
        "→ формат JSON, без медиафайлов.\n"
        "2. Выберите диалог: «Новый диалог» / /dialog Имя "
        "(или откройте топик заказчика в группе).\n"
        "3. Пришлите мне получившийся result.json файлом, с подписью "
        "/import_file и вашим from_id из этого экспорта "
        "(например: /import_file user361963836). История попадёт в активный "
        "диалог (или в заказчика этой темы, если пишете из топика).",
        reply_markup=main_keyboard(),
    )


@router.message(Command("import_file"), F.document)
async def cmd_import_file(message: Message, state: FSMContext) -> None:
    """
    from_id (например "user361963836") — это твой собственный id в
    экспорте, нужен чтобы отличить исходящие сообщения от входящих.
    Без него направление сообщений не определить: в личном чате оба
    участника выглядят в JSON одинаково, кроме этого поля.
    """
    args = (message.text or message.caption or "").split()
    if len(args) < 2:
        await message.answer(
            "Укажите ваш from_id из экспорта вместе с командой, например:\n"
            "/import_file user361963836",
            reply_markup=main_keyboard(),
        )
        return
    my_from_id = args[1]

    dialog_id, err = await operator_dialog_id(message, state)
    if err:
        await message.answer(err, reply_markup=main_keyboard())
        return

    if not message.document.file_name.endswith(".json"):
        await message.answer(
            "Ожидаю файл result.json (экспорт Telegram Desktop).",
            reply_markup=main_keyboard(),
        )
        return

    with tempfile.TemporaryDirectory() as tmp_dir:
        file_path = Path(tmp_dir) / "result.json"
        file = await message.bot.get_file(message.document.file_id)
        await message.bot.download_file(file.file_path, destination=file_path)

        try:
            parsed = parse_export(file_path, my_from_id=my_from_id)
        except Exception as exc:
            await message.answer(f"Не смог разобрать файл: {exc}", reply_markup=main_keyboard())
            return

    if not parsed:
        await message.answer(
            "В файле не нашлось текстовых сообщений. Проверьте from_id — "
            "возможно, он неверный, и все сообщения определились как одно "
            "направление.",
            reply_markup=main_keyboard(),
        )
        return

    async with get_session() as session:
        dialog = await session.get(Dialog, dialog_id)
        if dialog is None:
            await message.answer(NO_ACTIVE_DIALOG_TEXT, reply_markup=main_keyboard())
            return
        for m in parsed:
            await add_message(
                session,
                dialog.id,
                m.text,
                m.direction,
                source="import",
                tg_message_id=m.tg_message_id,
                sent_at=m.sent_at,
            )

    out_count = sum(1 for m in parsed if m.direction == MessageDirection.OUT)
    in_count = len(parsed) - out_count
    await message.answer(
        f"Загружено {len(parsed)} сообщений (ваших: {out_count}, входящих: {in_count}).\n\n"
        "⚠️ Плана переговоров для этого диалога ещё нет — guard будет "
        "отвечать «план пуст», пока вы его не составите.",
        reply_markup=main_keyboard(),
    )
