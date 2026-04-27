"""Discord and Telegram notification senders for deltaSimple.

send_discord  — async POST to Discord webhook; retries once on HTTP 5xx.
send_telegram — stub; logs and returns without sending anything.
"""

import httpx
from loguru import logger


async def send_discord(embed: dict, webhook_url: str) -> None:
    """POST an embed payload to the Discord webhook URL.

    Retries once on HTTP 5xx. Logs any failure and returns without raising.

    Args:
        embed:       Full Discord webhook payload dict (contains ``"embeds"`` key).
        webhook_url: The Discord webhook URL to POST to.
    """
    async with httpx.AsyncClient() as client:
        for attempt in range(2):
            try:
                resp = await client.post(webhook_url, json=embed)
            except httpx.HTTPError as exc:
                if attempt == 0:
                    logger.warning("Discord POST failed ({}), retrying...", exc)
                    continue
                logger.error("Discord webhook request failed after retry: {}", exc)
                return

            if resp.status_code >= 500:
                if attempt == 0:
                    logger.warning(
                        "Discord returned HTTP {}, retrying...", resp.status_code
                    )
                    continue
                logger.error(
                    "Discord webhook failed after retry: HTTP {}", resp.status_code
                )
                return

            if not resp.is_success:
                logger.error("Discord webhook returned HTTP {}", resp.status_code)
                return

            logger.debug("Discord alert sent (HTTP {})", resp.status_code)
            return


async def send_startup_message(
    webhook_url: str,
    poll_interval_seconds: int,
    threshold_pct: float,
    env: str,
    user_id: str,
) -> None:
    """Send the one-time startup notification to Discord.

    Called once on bot launch to confirm the webhook is reachable.

    Args:
        webhook_url:           Discord webhook URL.
        poll_interval_seconds: Poll cadence (shown in the message).
        threshold_pct:         Alert threshold (shown in the message).
        env:                   Runtime environment string.
        user_id:               SnapTrade user ID being monitored.
    """
    from alerts import build_startup_alert
    embed = build_startup_alert(poll_interval_seconds, threshold_pct, env, user_id)
    await send_discord(embed, webhook_url)


def send_telegram(message: str) -> None:
    """Stub. Telegram delivery is not yet implemented.

    Args:
        message: The message that would be sent (ignored).
    """
    logger.info("Telegram not yet implemented, skipping")


if __name__ == "__main__":
    import asyncio
    from config import load_config
    from alerts import build_open_alert
    from database import Position

    _cfg = load_config()

    _test_pos = Position(
        id="test-1",
        ticker="AAPL",
        option_type="call",
        strike=180.0,
        expiry="2026-05-16",
        quantity=1,
        avg_cost=3.20,
        opened_at="2026-04-26T10:00:00+00:00",
        status="open",
    )
    _embed = build_open_alert(_test_pos, underlying_price=178.45)
    asyncio.run(send_discord(_embed, _cfg.discord_webhook_url))
    logger.info("Test embed sent to Discord")
