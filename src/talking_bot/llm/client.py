import json

from openai import OpenAI

from talking_bot.config import settings

# OpenRouter даёт доступ к Claude через OpenAI-совместимый API — один ключ,
# один способ считать баланс, вместо отдельного счёта в Anthropic напрямую.
# Плата за это: нет helper-ов вроде messages.parse() с Pydantic-схемой,
# structured output просим через response_format и разбираем JSON сами
# (см. llm/guard.py).
client = OpenAI(
    api_key=settings.anthropic_api_key,
    base_url="https://openrouter.ai/api/v1",
)

# Имя модели в формате OpenRouter: "провайдер/модель".
# Берётся из LLM_MODEL в .env, по умолчанию Sonnet 4.6 — не Opus.
MODEL = settings.llm_model


def _loads_json(raw: str | None) -> dict:
    if not raw or not str(raw).strip():
        raise ValueError("Модель вернула пустой ответ вместо JSON")
    text = str(raw).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        fence = text.rfind("```")
        if fence != -1:
            text = text[:fence]
        text = text.strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    return json.loads(text)


def complete_json(messages: list[dict], *, max_tokens: int = 4096) -> dict:
    """
    Один вызов OpenRouter с JSON-ответом. Reasoning выключен: у Sonnet 4.6
    thinking по умолчанию забирает весь max_tokens, и content приходит пустым.
    Ответ иногда обёрнут в ```json — снимаем ограду до разбора.
    """
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=messages,
        response_format={"type": "json_object"},
        extra_body={"reasoning": {"enabled": False, "effort": "none"}},
    )
    return _loads_json(response.choices[0].message.content)
