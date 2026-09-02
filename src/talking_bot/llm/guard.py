from typing import Literal

from pydantic import BaseModel, Field

from talking_bot.db.models import PlanItem
from talking_bot.llm.client import complete_json

_SYSTEM_PROMPT = """\
Ты — проверяющий модуль переговорной системы. Твоя единственная задача: \
сравнить текст-кандидат с планом переговоров и определить, нарушает ли он \
план.

Правила:
- Ты НЕ видишь историю переписки и не должен её домысливать. Оценивай \
только сам текст против плана.
- red_line — пункт плана, который не обсуждается. Если текст-кандидат \
содержит уступку по red_line-пункту (совпадает с его breach_signal по \
смыслу, не обязательно дословно) — статус red_line.
- concession — текст даёт что-то сверх плана по flexible/target-пункту, \
но не нарушает ни одной red_line. Например: скидка, о которой план \
молчит, перенос срока не в рамках оговорённого fallback.
- in_plan — текст не даёт ничего, чего нет в плане, либо явно использует \
предусмotренный fallback.
- Если пунктов плана нет вообще — статус concession с пояснением "план \
пуст, проверить не по чему", а не in_plan по умолчанию.
- Для каждого нарушения указывай code пункта плана, дословную цитату из \
текста-кандидата и краткое объяснение почему.
"""


class Violation(BaseModel):
    plan_item_code: str
    kind: Literal["concession", "red_line"]
    quote: str = Field(description="Дословная цитата из текста-кандидата")
    why: str


class Verdict(BaseModel):
    status: Literal["in_plan", "concession", "red_line"]
    violations: list[Violation]
    rationale: str


def _format_plan_items(items: list[PlanItem]) -> str:
    if not items:
        return "(план пуст — пунктов нет)"

    lines = []
    for item in items:
        lines.append(
            f"- [{item.kind.value}] {item.code}: {item.title}\n"
            f"  значение: {item.value or '—'}\n"
            f"  fallback: {item.fallback or '—'}\n"
            f"  breach_signal: {item.breach_signal or '—'}"
        )
    return "\n".join(lines)


def check_draft(plan_items: list[PlanItem], candidate_text: str) -> Verdict:
    """
    Отдельный вызов Claude, БЕЗ истории переписки — только план и
    текст-кандидат. Модель, которая видит, как заказчик третий раз
    подряд давит на сроки, начинает "входить в положение" — это её
    нормальное поведение и здесь оно вредно. Прокурор без контекста
    не сочувствует.

    Вызывается на любой исходящий текст: черновик модели, твою правку,
    твой собственный текст. Обход этой функции не предусмотрен —
    если текст ушёл в Telegram, минуя check_draft, это баг, не фича.
    """
    plan_block = _format_plan_items(plan_items)

    # OpenRouter (OpenAI-совместимый API) не умеет messages.parse() с
    # Pydantic-схемой, как родной Anthropic SDK. Просим строгий JSON через
    # response_format и парсим сами — Pydantic всё равно проверит форму
    # ответа и упадёт с понятной ошибкой, если модель прислала не то.
    parsed = complete_json(
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"ПЛАН:\n{plan_block}\n\nТЕКСТ-КАНДИДАТ:\n{candidate_text}\n\n"
                    "Ответь строго JSON-объектом вида "
                    '{"status": "in_plan|concession|red_line", '
                    '"violations": [{"plan_item_code": str, '
                    '"kind": "concession|red_line", "quote": str, "why": str}], '
                    '"rationale": str}. Без пояснений вокруг, только JSON.'
                ),
            },
        ]
    )
    return Verdict.model_validate(parsed)
