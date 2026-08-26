from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from talking_bot.db.models import Plan, PlanItem


async def get_active_plan(session: AsyncSession, dialog_id: int) -> Plan | None:
    """
    Активный план — тот, у которого active=True. Пунктов может не быть
    вообще (план ещё не написан) — это нормальное состояние на старте,
    guard в этом случае должен явно сказать "план пуст", а не молчать.
    """
    result = await session.execute(
        select(Plan)
        .where(Plan.dialog_id == dialog_id, Plan.active.is_(True))
        .order_by(Plan.version.desc())
    )
    return result.scalars().first()


async def get_plan_items(session: AsyncSession, plan_id: int) -> list[PlanItem]:
    result = await session.execute(
        select(PlanItem).where(PlanItem.plan_id == plan_id)
    )
    return list(result.scalars().all())


async def create_new_plan_version(
    session: AsyncSession, dialog_id: int, changelog: str
) -> Plan:
    """
    Новая версия плана. Предыдущая активная версия деактивируется,
    но не удаляется — история версий остаётся в базе навсегда.
    changelog обязателен: без него непонятно, "передумали" или "прогнулись".
    """
    current = await get_active_plan(session, dialog_id)
    next_version = 1 if current is None else current.version + 1

    if current is not None:
        current.active = False

    plan = Plan(
        dialog_id=dialog_id,
        version=next_version,
        active=True,
        changelog=changelog,
    )
    session.add(plan)
    await session.flush()
    return plan
