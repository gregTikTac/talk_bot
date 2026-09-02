import json

from pydantic import BaseModel

from talking_bot.db.models import Dialog, Message, PlanItem
from talking_bot.llm.client import complete_json

_SYSTEM_PROMPT = """\
Ты помогаешь вести переговоры с заказчиком в Telegram. Твоя задача — \
составить черновик ответа на последнее сообщение заказчика.

Правила:
- Пиши в том же тоне, что и предыдущие сообщения в переписке: если там \
короткие фразы без формальностей — не пиши длинный официальный текст, \
и наоборот.
- Отвечай по существу последнего сообщения заказчика, не игнорируй его \
вопросы.
- Не делай уступок, которых нет в плане — но это не единственная твоя \
задача, за это отдельно отвечает другой модуль. Твоя задача — предложить \
хороший ответ, который потом проверят.
- Если заказчик просит что-то, чего нет в плане и не покрыто fallback-ом \
ни одного пункта — можно прямо предложить обсудить это отдельно, а не \
соглашаться и не игнорировать просьбу.
- Не выдумывай факты о проекте, которых нет в переписке или плане.
"""


class Draft(BaseModel):
    text: str
    addresses: list[str]
    concessions: list[str]
    open_questions: list[str]


def _format_plan_items(items: list[PlanItem]) -> str:
    if not items:
        return "(план пуст — пунктов нет)"
    lines = []
    for item in items:
        lines.append(
            f"- [{item.kind.value}] {item.code}: {item.title} "
            f"(значение: {item.value or '—'}, fallback: {item.fallback or '—'})"
        )
    return "\n".join(lines)


def _format_history(messages: list[Message], summary: str | None) -> str:
    parts = []
    if summary:
        parts.append(f"Сжатый пересказ более ранней части переписки:\n{summary}")
    if messages:
        history_lines = [
            f"[{m.direction.value}] {m.text}" for m in messages
        ]
        parts.append("Последние сообщения (старые сначала):\n" + "\n".join(history_lines))
    return "\n\n".join(parts) if parts else "(истории пока нет)"


def compose_draft(
    dialog: Dialog,
    plan_items: list[PlanItem],
    recent_messages: list[Message],
) -> Draft:
    """
    В отличие от guard, этот вызов ВИДИТ историю переписки и план вместе —
    он должен звучать в тон разговора, а не только формально соответствовать
    плану. Соответствие плану проверяет guard отдельным вызовом ПОСЛЕ этого.
    """
    plan_block = _format_plan_items(plan_items)
    history_block = _format_history(recent_messages, dialog.summary)
    style_block = json.dumps(dialog.style_card, ensure_ascii=False) if dialog.style_card else "(ещё не составлена)"

    user_content = (
        f"ПЛАН ПЕРЕГОВОРОВ:\n{plan_block}\n\n"
        f"КАРТОЧКА СТИЛЯ ОБЩЕНИЯ:\n{style_block}\n\n"
        f"ИСТОРИЯ ПЕРЕПИСКИ:\n{history_block}\n\n"
        "Составь черновик ответа на последнее сообщение заказчика. "
        "Ответь строго JSON-объектом вида "
        '{"text": str, "addresses": [str], "concessions": [str], '
        '"open_questions": [str]}, где addresses — какие тезисы заказчика '
        "закрыты, concessions — что ты сам считаешь уступкой в этом черновике "
        "(даже если план не нарушен явно), open_questions — что осталось "
        "без ответа. Без пояснений вокруг, только JSON."
    )

    parsed = complete_json(
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
    )
    return Draft.model_validate(parsed)
