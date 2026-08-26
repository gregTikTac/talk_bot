from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from talking_bot.config import settings

engine = create_async_engine(settings.database_url, echo=False)

_session_factory = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """
    Одна сессия = одна единица работы с базой (обычно один обработчик
    сообщения в боте). Коммитит при успехе, откатывает при ошибке —
    так наполовину сделанные изменения никогда не осядут в базе.
    """
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
