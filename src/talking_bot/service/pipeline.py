from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from talking_bot.db.models import Dialog, DraftOrigin, DraftStatus, MessageDirection
from talking_bot.domain.dialog import add_message, get_recent_messages
from talking_bot.domain.plan import get_active_plan, get_plan_items
from talking_bot.llm.compose import compose_draft
from talking_bot.llm.guard import Verdict, check_draft


@dataclass
class PipelineResult:
    draft_id: int
    draft_text: str
    verdict: Verdict


async def run_pipeline(
    session: AsyncSession, dialog: Dialog, incoming_text: str, source: str = "forward"
) -> PipelineResult:
    """
    Единственный путь из входящего сообщения в готовую карточку для
    оператора: записать сообщение → составить черновик → проверить его.
    Ни один шаг не пропускается — в частности, guard вызывается всегда,
    даже если это первый черновик без правок.
    source: "forward" (переслали из Telegram) или "paste" (вставили текст,
    например с Авито).
    """
    await add_message(session, dialog.id, incoming_text, MessageDirection.IN, source=source)

    plan = await get_active_plan(session, dialog.id)
    plan_items = await get_plan_items(session, plan.id) if plan else []
    recent_messages = await get_recent_messages(session, dialog.id)

    draft = compose_draft(dialog, plan_items, recent_messages)
    verdict = check_draft(plan_items, draft.text)

    from talking_bot.db.models import Draft as DraftRow

    draft_row = DraftRow(
        dialog_id=dialog.id,
        text=draft.text,
        origin=DraftOrigin.MODEL,
        status=DraftStatus.PENDING,
    )
    session.add(draft_row)
    await session.flush()

    from talking_bot.db.models import Verdict as VerdictRow, VerdictSubject, VerdictStatus

    verdict_row = VerdictRow(
        draft_id=draft_row.id,
        subject=VerdictSubject.MODEL_DRAFT,
        status=VerdictStatus(verdict.status),
        items=[v.model_dump() for v in verdict.violations],
        rationale=verdict.rationale,
    )
    session.add(verdict_row)
    await session.flush()

    return PipelineResult(draft_id=draft_row.id, draft_text=draft.text, verdict=verdict)


async def recheck_edited_text(
    session: AsyncSession, dialog_id: int, draft_id: int, edited_text: str
) -> Verdict:
    """
    Проверка твоей собственной правки или твоего текста, написанного с
    нуля. Тот самый механизм, ради которого guard вообще существует:
    кнопка "Изменить" не должна быть каналом обхода проверки.
    """
    plan = await get_active_plan(session, dialog_id)
    plan_items = await get_plan_items(session, plan.id) if plan else []

    verdict = check_draft(plan_items, edited_text)

    from talking_bot.db.models import Verdict as VerdictRow, VerdictSubject, VerdictStatus

    verdict_row = VerdictRow(
        draft_id=draft_id,
        subject=VerdictSubject.USER_EDIT,
        status=VerdictStatus(verdict.status),
        items=[v.model_dump() for v in verdict.violations],
        rationale=verdict.rationale,
    )
    session.add(verdict_row)
    await session.flush()

    return verdict
