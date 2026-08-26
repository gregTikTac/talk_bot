from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    bot_token: str
    anthropic_api_key: str
    database_url: str  # postgresql+asyncpg://user:pass@host/db

    # api.telegram.org может быть заблокирован у провайдера/страны, где
    # крутится бот. Если задано — весь трафик к Telegram идёт через этот
    # прокси (http://, socks5:// — что понимает aiohttp). Пусто — бот
    # стучится напрямую, как раньше.
    proxy_url: str | None = None


settings = Settings()
