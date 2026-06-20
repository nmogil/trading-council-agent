"""Centralized runtime configuration.

Safe defaults: the service runs in paper mode with live trading disabled unless
the operator explicitly opts in via environment variables. Live mode is rejected
at load time unless ``TRADING_COUNCIL_LIVE_ENABLED=true`` is also set.
"""

from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

VALID_MODES = {"paper", "live"}


class Settings(BaseSettings):
    """Application settings loaded from the environment and ``.env``."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Runtime
    mode: str = Field(default="paper", alias="TRADING_COUNCIL_MODE")
    live_enabled: bool = Field(default=False, alias="TRADING_COUNCIL_LIVE_ENABLED")
    kill_switch: bool = Field(default=False, alias="TRADING_COUNCIL_KILL_SWITCH")
    database_url: str = Field(
        default="sqlite:///./data/trading_council.db",
        alias="TRADING_COUNCIL_DATABASE_URL",
    )
    timezone: str = Field(default="Europe/London", alias="TRADING_COUNCIL_TIMEZONE")

    # Alpaca paper
    alpaca_paper_api_key: str | None = Field(default=None, alias="ALPACA_PAPER_API_KEY")
    alpaca_paper_secret_key: str | None = Field(default=None, alias="ALPACA_PAPER_SECRET_KEY")
    alpaca_paper_base_url: str = Field(
        default="https://paper-api.alpaca.markets",
        alias="ALPACA_PAPER_BASE_URL",
    )

    # Alpaca live — leave unset until a later phase enables live trading.
    alpaca_live_api_key: str | None = Field(default=None, alias="ALPACA_LIVE_API_KEY")
    alpaca_live_secret_key: str | None = Field(default=None, alias="ALPACA_LIVE_SECRET_KEY")
    alpaca_live_base_url: str = Field(
        default="https://api.alpaca.markets",
        alias="ALPACA_LIVE_BASE_URL",
    )

    @model_validator(mode="after")
    def validate_mode(self) -> Settings:
        """Enforce a valid mode and keep live trading blocked by default."""
        if self.mode not in VALID_MODES:
            raise ValueError("TRADING_COUNCIL_MODE must be paper or live")
        if self.mode == "live" and not self.live_enabled:
            raise ValueError("live mode requires TRADING_COUNCIL_LIVE_ENABLED=true")
        return self
