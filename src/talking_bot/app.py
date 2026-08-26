import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage

from talking_bot.config import settings
from talking_bot.control.find_handler import router as find_router
from talking_bot.control.handlers import router
from talking_bot.control.import_handler import router as import_router


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
    # import_router и find_router — раньше основного: /import_file и /find
    # должны сработать как команды, а не попасть в обработчик форвардов.
    dispatcher.include_router(import_router)
    dispatcher.include_router(find_router)
    dispatcher.include_router(router)

    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
