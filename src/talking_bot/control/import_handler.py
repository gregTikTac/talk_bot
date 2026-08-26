import tempfile
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from talking_bot.db.models import MessageDirection
from talking_bot.db.session import get_session
from talking_bot.domain.dialog import add_message, get_or_create_dialog
from talking_bot.ingest.telegram_export import parse_export

router = Router()


@router.message(Command("import"))
async def cmd_import_help(message: Message) -> None:
    await message.answer(
        "Чтобы загрузить историю переписки:\n"
        "1. В Telegram Desktop → чат с заказчиком → ⋮ → Экспорт истории чата "
        "→ формат JSON, без медиафайлов.\n"
        "2. Пришлите мне получившийся result.json файлом, с подписью "
        "/import_file и вашим from_id из этого экспорта "
        "(например: /import_file user361963836)."
    )


@router.message(Command("import_file"), F.document)
async def cmd_import_file(message: Message) -> None:
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
            "/import_file user361963836"
        )
        return
    my_from_id = args[1]

    if not message.document.file_name.endswith(".json"):
        await message.answer("Ожидаю файл result.json (экспорт Telegram Desktop).")
        return

    with tempfile.TemporaryDirectory() as tmp_dir:
        file_path = Path(tmp_dir) / "result.json"
        file = await message.bot.get_file(message.document.file_id)
        await message.bot.download_file(file.file_path, destination=file_path)

        try:
            parsed = parse_export(file_path, my_from_id=my_from_id)
        except Exception as exc:
            await message.answer(f"Не смог разобрать файл: {exc}")
            return

    if not parsed:
        await message.answer(
            "В файле не нашлось текстовых сообщений. Проверьте from_id — "
            "возможно, он неверный, и все сообщения определились как одно "
            "направление."
        )
        return

    async with get_session() as session:
        dialog = await get_or_create_dialog(
            session, tg_user_id=message.from_user.id, name=message.from_user.full_name
        )
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
        "отвечать «план пуст», пока вы его не составите."
    )
