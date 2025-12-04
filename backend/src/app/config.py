"""Application configuration using Pydantic settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration pulled from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        populate_by_name=True,
    )

    environment: str = Field(default="local", alias="ENVIRONMENT")
    enable_hot_reload: bool = Field(default=False, alias="ENABLE_HOT_RELOAD")
    enable_frontend_watch: bool = Field(default=False, alias="ENABLE_FRONTEND_WATCH")
    default_provider_strategy: str = Field(default="auto", alias="PROVIDER_STRATEGY")


@lru_cache()
def get_settings() -> Settings:
    """Return cached settings instance."""

    return Settings()

