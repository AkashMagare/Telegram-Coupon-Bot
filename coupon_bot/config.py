"""Environment-backed application settings."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigurationError(ValueError):
    """Raised when required bot configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration for the bot."""

    bot_token: str
    database_path: str
    admin_ids: frozenset[int]
    page_size: int
    rate_limit_seconds: float
    log_level: str


def _parse_admin_ids(raw_value: str) -> frozenset[int]:
    if not raw_value.strip():
        return frozenset()

    values: set[int] = set()
    for raw_id in raw_value.replace(",", " ").split():
        try:
            user_id = int(raw_id)
        except ValueError as exc:
            raise ConfigurationError(
                "ADMIN_IDS must contain only numeric Telegram user IDs"
            ) from exc
        if user_id <= 0:
            raise ConfigurationError("ADMIN_IDS must contain positive user IDs")
        values.add(user_id)
    return frozenset(values)


def _parse_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ConfigurationError(f"{name} must be between {minimum} and {maximum}")
    return value


def _parse_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc
    if not minimum <= value <= maximum:
        raise ConfigurationError(f"{name} must be between {minimum} and {maximum}")
    return value


def load_settings() -> Settings:
    """Load and validate settings from the environment and an optional .env file."""

    load_dotenv()

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token or bot_token == "replace_with_token_from_botfather":
        raise ConfigurationError("BOT_TOKEN is required")

    database_path = os.getenv("DATABASE_PATH", "coupons.db").strip()
    if not database_path:
        raise ConfigurationError("DATABASE_PATH cannot be empty")

    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigurationError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")

    return Settings(
        bot_token=bot_token,
        database_path=database_path,
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS", "")),
        page_size=_parse_int("PAGE_SIZE", 5, 1, 10),
        rate_limit_seconds=_parse_float("RATE_LIMIT_SECONDS", 1.0, 0.0, 60.0),
        log_level=log_level,
    )
