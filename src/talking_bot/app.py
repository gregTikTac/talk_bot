import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage

from talking_bot.config import settings
from talking_bot.control.find_handler import router as find_router
from talking_bot.control.handlers import dialog_router, router
from talking_bot.control.import_handler import router as import_router
from talking_bot.control.keyboards import BOT_COMMANDS
from talking_bot.control.plan_handler import router as plan_router


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    # Если api.telegram.org заблокирован у провайдера — задай PROXY_URL
    # в .env (http://host:port или socks5://host:port). Без него сессия
    # работает как обычно, напрямую.
    session = AiohttpSession(proxy=settings.proxy_url) if settings.proxy_url else None
    bot = Bot(token=settings.bot_token, session=session)
    # MemoryStorage для FSM ("жду правку от тебя") хватает для стадии 1 —
    # состояние живёт, пока процесс не перезапущен. Если это станет
    # проблемой, меняется на RedisStorage без переделки handlers.py.
    dispatcher = Dispatcher(storage=MemoryStorage())
    # Команды раньше основного роутера: /import_file, /find, /dialog, /dialogs
    # не должны попасть в обработчик форвардов или F.text-вставку с Авито.
    dispatcher.include_router(import_router)
    dispatcher.include_router(find_router)
    dispatcher.include_router(plan_router)
    dispatcher.include_router(dialog_router)
    dispatcher.include_router(router)

    # Меню слева от поля ввода (гамбургер / Menu). Не падаем, если Telegram
    # временно недоступен — polling всё равно попробует подключиться.
    try:
        await bot.set_my_commands(BOT_COMMANDS)
    except TelegramAPIError:
        logging.exception("Не удалось установить меню команд бота")

    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
