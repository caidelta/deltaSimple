"""Main polling loop for deltaSimple.

Integrates config, database, snaptrade_client, price_tracker, alerts, and
notifier.  Runs as a long-lived async worker; shuts down cleanly on SIGINT or
SIGTERM.
"""

import asyncio
import signal
import sqlite3

from loguru import logger

import alerts
import database
import notifier
import price_tracker
import snaptrade_client
from config import Config, load_config


async def _handle_new(
    position: database.Position,
    conn: sqlite3.Connection,
    config: Config,
) -> None:
    """Open alert + DB upsert + price snapshot for a newly detected position."""
    underlying = await asyncio.to_thread(price_tracker.get_underlying_price, position.ticker)
    embed = alerts.build_open_alert(position, underlying)
    await notifier.send_discord(embed, config.discord_webhook_url)
    await asyncio.to_thread(database.upsert_position, conn, position)
    await asyncio.to_thread(database.upsert_price_snapshot, conn, position.id, underlying)
    logger.info(
        "Opened: {} {} strike={} expiry={}",
        position.ticker, position.option_type.upper(), position.strike, position.expiry,
    )


async def _handle_update(
    position: database.Position,
    conn: sqlite3.Connection,
    config: Config,
) -> None:
    """Fire update alert if underlying moved past threshold; refresh snapshot."""
    last_price = await asyncio.to_thread(database.get_last_price, conn, position.id)
    current = await asyncio.to_thread(price_tracker.get_underlying_price, position.ticker)

    if last_price is None:
        await asyncio.to_thread(database.upsert_price_snapshot, conn, position.id, current)
        return

    pct = abs(price_tracker.compute_pct_change(last_price, current))
    if pct >= config.price_alert_threshold_pct:
        old_val = position.avg_cost
        new_val = price_tracker.estimate_option_value(position, last_price, current)
        embed = alerts.build_update_alert(
            position, last_price, current, old_val, new_val,
            config.price_alert_threshold_pct,
        )
        await notifier.send_discord(embed, config.discord_webhook_url)
        await asyncio.to_thread(database.upsert_price_snapshot, conn, position.id, current)
        logger.info(
            "Update alert: {} moved {:.2f}% (threshold: {}%)",
            position.ticker, pct, config.price_alert_threshold_pct,
        )
    else:
        logger.debug(
            "No alert for {} — {:.2f}% < {}%",
            position.ticker, pct, config.price_alert_threshold_pct,
        )


async def _handle_closed(
    position: database.Position,
    conn: sqlite3.Connection,
    config: Config,
) -> None:
    """Close alert + mark position closed for a position gone from SnapTrade."""
    try:
        close_price = await asyncio.to_thread(price_tracker.get_underlying_price, position.ticker)
    except Exception as exc:
        logger.warning(
            "Could not fetch close price for {} ({}), falling back to avg_cost",
            position.ticker, exc,
        )
        close_price = position.avg_cost

    embed = alerts.build_close_alert(position, close_price)
    await notifier.send_discord(embed, config.discord_webhook_url)
    await asyncio.to_thread(database.mark_position_closed, conn, position.id)
    logger.info(
        "Closed: {} {} strike={} expiry={}",
        position.ticker, position.option_type.upper(), position.strike, position.expiry,
    )


async def _process_tick(conn: sqlite3.Connection, config: Config) -> None:
    """One poll cycle: diff SnapTrade snapshot vs DB, dispatch handlers."""
    snap_positions = await asyncio.to_thread(snaptrade_client.get_options_positions, config)
    db_positions = await asyncio.to_thread(database.get_open_positions, conn)

    snap_map = {p.id: p for p in snap_positions}
    db_map = {p.id: p for p in db_positions}

    for pos_id in snap_map.keys() - db_map.keys():
        await _handle_new(snap_map[pos_id], conn, config)

    for pos_id in snap_map.keys() & db_map.keys():
        await _handle_update(snap_map[pos_id], conn, config)

    for pos_id in db_map.keys() - snap_map.keys():
        await _handle_closed(db_map[pos_id], conn, config)


async def run() -> None:
    """Bootstrap and run the polling loop until SIGINT/SIGTERM."""
    config = load_config()
    logger.info("Starting deltaSimple ({})", config.env)

    conn = database.connect()
    await asyncio.to_thread(database.init_db, conn)

    user_secret = await asyncio.to_thread(snaptrade_client.register_user, config)
    config.snaptrade_user_secret = user_secret

    await notifier.send_startup_message(
        config.discord_webhook_url,
        config.poll_interval_seconds,
        config.price_alert_threshold_pct,
        config.env,
        config.snaptrade_user_id,
    )

    stop_event = asyncio.Event()

    def _on_signal() -> None:
        logger.info("Shutdown signal received — stopping after current tick")
        stop_event.set()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, _on_signal)
    loop.add_signal_handler(signal.SIGTERM, _on_signal)

    logger.info(
        "Polling every {}s — threshold: {}%",
        config.poll_interval_seconds,
        config.price_alert_threshold_pct,
    )

    while not stop_event.is_set():
        try:
            await _process_tick(conn, config)
        except Exception as exc:
            logger.error("Tick error: {}", exc)

        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=float(config.poll_interval_seconds)
            )
        except asyncio.TimeoutError:
            pass

    conn.close()
    logger.info("deltaSimple stopped cleanly")


if __name__ == "__main__":
    asyncio.run(run())
