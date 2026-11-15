"""Settings, loaded from environment variables or the .env file.

Usage anywhere in the code:
    from nerkhbot.config import get_settings
    settings = get_settings()
    settings.channels  # -> ["somechannel", ...]
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Read .env from the current folder. Field names map to env vars
    # case-insensitively: tg_api_id <- TG_API_ID. Unknown vars are ignored.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Required: no default, so startup fails loudly if they're missing.
    tg_api_id: int
    tg_api_hash: str

    tg_session: str = "data/nerkhbot"
    tg_channels: str = ""  # raw comma-separated string; use .channels

    backfill_days: int = 10
    catchup_minutes: int = 10

    database_url: str = "sqlite:///data/nerkhbot.db"
    log_level: str = "INFO"
    log_dir: str = "logs"

    @property
    def channels(self) -> list[str]:
        """TG_CHANNELS as a clean list: '@A, https://t.me/b/' -> ['a', 'b']."""
        result = []
        for item in self.tg_channels.split(","):
            name = item.strip()
            for prefix in ("https://t.me/", "http://t.me/", "t.me/", "@"):
                if name.lower().startswith(prefix):
                    name = name[len(prefix):]
            name = name.strip("/").lower()
            if name:
                result.append(name)
        return result


@lru_cache
def get_settings() -> Settings:
    """Build Settings once and reuse it (reading .env on every call is wasteful)."""
    return Settings()
