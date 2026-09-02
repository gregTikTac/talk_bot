from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    bot_token: str
    anthropic_api_key: str
    database_url: str  # postgresql+asyncpg://user:pass@host/db
    # OpenRouter slug. По договорённости — Sonnet 4.6, не Opus.
    llm_model: str = "anthropic/claude-sonnet-4.6"

    # api.telegram.org может быть заблокирован у провайдера/страны, где
    # крутится бот. Если задано — весь трафик к Telegram идёт через этот
    # прокси (http://, socks5:// — что понимает aiohttp). Пусто — бот
    # стучится напрямую, как раньше.
    proxy_url: str | None = None

    # Супергруппа с включёнными темами (Topics/Forum). Обычно −100…
    # Пусто — работаем только в личке, /dialog и кнопки как раньше.
    control_chat_id: int | None = None

    @field_validator("control_chat_id", mode="before")
    @classmethod
    def _empty_control_chat_id(cls, value):
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value


settings = Settings()
