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
MODEL = "anthropic/claude-opus-5"
