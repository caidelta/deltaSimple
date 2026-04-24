"""Config loader for deltaSimple.

Loads and validates all environment variables, exposes a typed Config object,
and initialises the loguru logger. Import `config` and `logger` from this module.
"""

import os
import sys
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from loguru import logger


_REQUIRED_VARS = (
    "SNAPTRADE_CLIENT_ID",
    "SNAPTRADE_CONSUMER_KEY",
    "SNAPTRADE_USER_ID",
    "DISCORD_WEBHOOK_URL",
    "POLL_INTERVAL_SECONDS",
    "PRICE_ALERT_THRESHOLD_PCT",
)

_SECRET_FIELDS = {
    "snaptrade_client_id",
    "snaptrade_consumer_key",
    "snaptrade_user_secret",
    "discord_webhook_url",
    "telegram_bot_token",
}


def _mask(value: Optional[str]) -> str:
    """Return a masked version of a secret string, showing only the last 4 characters."""
    if not value:
        return "None"
    return f"****{value[-4:]}" if len(value) > 4 else "****"


@dataclass
class Config:
    """Typed, validated configuration loaded from environment variables."""

    snaptrade_client_id: str
    snaptrade_consumer_key: str
    snaptrade_user_id: str
    snaptrade_user_secret: Optional[str]
    discord_webhook_url: str
    telegram_bot_token: Optional[str]
    telegram_chat_id: Optional[str]
    poll_interval_seconds: int
    price_alert_threshold_pct: float
    env: str

    def __str__(self) -> str:
        """Return a human-readable config summary with secrets masked."""
        lines = ["Config("]
        for field_name, value in self.__dict__.items():
            display = _mask(value) if field_name in _SECRET_FIELDS else value
            lines.append(f"  {field_name}={display}")
        lines.append(")")
        return "\n".join(lines)


def _setup_logger(env: str) -> None:
    """Configure loguru based on the current environment."""
    logger.remove()
    level = "DEBUG" if env == "development" else "INFO"
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )


def load_config() -> "Config":
    """Load environment variables, validate required fields, and return a Config.

    Raises:
        ValueError: If any required environment variable is missing or blank.
        ValueError: If POLL_INTERVAL_SECONDS is not a valid integer.
        ValueError: If PRICE_ALERT_THRESHOLD_PCT is not a valid float.
    """
    load_dotenv()

    missing = [key for key in _REQUIRED_VARS if not os.getenv(key)]
    if missing:
        raise ValueError(
            f"Missing required environment variable(s): {', '.join(missing)}"
        )

    try:
        poll_interval = int(os.environ["POLL_INTERVAL_SECONDS"])
    except ValueError:
        raise ValueError(
            f"POLL_INTERVAL_SECONDS must be a valid integer, "
            f"got: {os.environ['POLL_INTERVAL_SECONDS']!r}"
        )

    try:
        threshold_pct = float(os.environ["PRICE_ALERT_THRESHOLD_PCT"])
    except ValueError:
        raise ValueError(
            f"PRICE_ALERT_THRESHOLD_PCT must be a valid float, "
            f"got: {os.environ['PRICE_ALERT_THRESHOLD_PCT']!r}"
        )

    env = os.getenv("ENV", "production")
    _setup_logger(env)

    return Config(
        snaptrade_client_id=os.environ["SNAPTRADE_CLIENT_ID"],
        snaptrade_consumer_key=os.environ["SNAPTRADE_CONSUMER_KEY"],
        snaptrade_user_id=os.environ["SNAPTRADE_USER_ID"],
        snaptrade_user_secret=os.getenv("SNAPTRADE_USER_SECRET") or None,
        discord_webhook_url=os.environ["DISCORD_WEBHOOK_URL"],
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
        poll_interval_seconds=poll_interval,
        price_alert_threshold_pct=threshold_pct,
        env=env,
    )


if __name__ == "__main__":
    cfg = load_config()
    logger.info("Config loaded successfully")
    print(cfg)
