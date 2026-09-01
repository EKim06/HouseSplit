from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "HouseSplit"
    secret_key: str = "development-only-change-me"
    database_url: str = "sqlite:///./housesplit.db"
    secure_cookies: bool = False
    auto_create_db: bool = True

    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="HOUSE_SPLIT_", extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

