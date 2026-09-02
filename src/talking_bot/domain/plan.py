from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from talking_bot.db.models import Plan, PlanItem, PlanItemKind


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


@dataclass
class ParsedPlanItem:
    code: str
    kind: PlanItemKind
    title: str
    value: str | None
    fallback: str | None
    breach_signal: str | None


_KIND_ALIASES = {
    "red_line": PlanItemKind.RED_LINE,
    "red": PlanItemKind.RED_LINE,
    "redline": PlanItemKind.RED_LINE,
    "красная": PlanItemKind.RED_LINE,
    "красный": PlanItemKind.RED_LINE,
    "к": PlanItemKind.RED_LINE,
    "target": PlanItemKind.TARGET,
    "цель": PlanItemKind.TARGET,
    "целевой": PlanItemKind.TARGET,
    "flexible": PlanItemKind.FLEXIBLE,
    "гибко": PlanItemKind.FLEXIBLE,
    "гибкий": PlanItemKind.FLEXIBLE,
    "flex": PlanItemKind.FLEXIBLE,
}

_KIND_LABELS = {
    PlanItemKind.RED_LINE: "🔴 красная линия",
    PlanItemKind.TARGET: "🎯 цель",
    PlanItemKind.FLEXIBLE: "〰️ гибко",
}


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text or text in {"—", "-", "–", "нет"}:
        return None
    return text


def parse_plan_text(raw: str) -> list[ParsedPlanItem]:
    """
    Строка: код | вид | заголовок | значение | fallback | сигнал
    Вид: красная / цель / гибко (или red_line / target / flexible).
    Для красной линии fallback и сигнал обязательны.
    """
    items: list[ParsedPlanItem] = []
    errors: list[str] = []
    seen_codes: set[str] = set()

    for index, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.lower().startswith("changelog:"):
            continue
        parts = [p.strip() for p in stripped.split("|")]
        if len(parts) < 4:
            errors.append(
                f"строка {index}: нужно минимум 4 поля через | "
                "(код | вид | заголовок | значение)"
            )
            continue
        code, kind_raw, title, value, *rest = parts
        code = code.upper().replace(" ", "_")
        if not code or len(code) > 64:
            errors.append(f"строка {index}: пустой или слишком длинный код")
            continue
        if code in seen_codes:
            errors.append(f"строка {index}: код {code} уже был")
            continue
        kind = _KIND_ALIASES.get(kind_raw.lower())
        if kind is None:
            errors.append(
                f"строка {index}: вид «{kind_raw}» — укажите красная, цель или гибко"
            )
            continue
        if not title:
            errors.append(f"строка {index}: пустой заголовок")
            continue
        fallback = _blank(rest[0]) if len(rest) > 0 else None
        breach = _blank(rest[1]) if len(rest) > 1 else None
        if kind == PlanItemKind.RED_LINE and (not fallback or not breach):
            errors.append(
                f"строка {index} ({code}): у красной линии нужны fallback и сигнал нарушения"
            )
            continue
        seen_codes.add(code)
        items.append(
            ParsedPlanItem(
                code=code,
                kind=kind,
                title=title[:255],
                value=_blank(value),
                fallback=fallback,
                breach_signal=breach,
            )
        )

    if errors:
        raise ValueError("\n".join(errors))
    if not items:
        raise ValueError("Не нашёл ни одного пункта. Пришлите строки через |")
    return items


def extract_changelog(raw: str) -> str:
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("changelog:"):
            note = stripped.split(":", 1)[1].strip()
            if note:
                return note
    return "замена через /plan"


async def replace_active_plan(
    session: AsyncSession,
    dialog_id: int,
    items: list[ParsedPlanItem],
    changelog: str,
) -> Plan:
    plan = await create_new_plan_version(session, dialog_id, changelog)
    for item in items:
        session.add(
            PlanItem(
                plan_id=plan.id,
                code=item.code,
                title=item.title,
                value=item.value,
                kind=item.kind,
                fallback=item.fallback,
                breach_signal=item.breach_signal,
            )
        )
    await session.flush()
    return plan


def format_plan(plan: Plan | None, items: list[PlanItem]) -> str:
    if plan is None or not items:
        return "Плана ещё нет — guard будет писать «план пуст»."
    lines = [f"План, версия {plan.version}"]
    if plan.changelog:
        lines.append(f"changelog: {plan.changelog}")
    lines.append("")
    for item in items:
        lines.append(f"{_KIND_LABELS[item.kind]}  {item.code} — {item.title}")
        if item.value:
            lines.append(f"   значение: {item.value}")
        if item.fallback:
            lines.append(f"   fallback: {item.fallback}")
        if item.breach_signal:
            lines.append(f"   сигнал: {item.breach_signal}")
        lines.append("")
    return "\n".join(lines).rstrip()
