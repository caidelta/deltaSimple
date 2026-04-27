"""SnapTrade integration: user registration and option position fetching.

NOTE — naming collision: the installed SDK package is also called
`snaptrade_client`.  `build_client()` handles this by temporarily removing the
project root from sys.path so the SDK package can be imported cleanly.  In
tests the function is always mocked, so the collision is never triggered.
"""

import os
import sys
from datetime import datetime, timezone
from typing import Optional

from dotenv import set_key
from loguru import logger

from config import Config
from database import Position


def build_client(config: Config):
    """Construct a live SnapTrade SDK client from config credentials.

    Temporarily removes the project directory from sys.path and pops this
    module from sys.modules so that ``from snaptrade_client import SnapTrade``
    resolves to the installed SDK package, not this file.
    """
    project_dir = os.path.dirname(os.path.abspath(__file__))
    saved_path = sys.path[:]
    saved_mod = sys.modules.pop("snaptrade_client", None)

    sys.path[:] = [
        p for p in sys.path
        if p not in ("", ".")
        and os.path.abspath(p) != project_dir
    ]

    try:
        from snaptrade_client import SnapTrade
        from snaptrade_client.configuration import Configuration

        return SnapTrade(
            Configuration(
                consumer_key=config.snaptrade_consumer_key,
                client_id=config.snaptrade_client_id,
            )
        )
    finally:
        sys.path[:] = saved_path
        if saved_mod is not None:
            sys.modules["snaptrade_client"] = saved_mod


def register_user(config: Config, env_path: str = ".env") -> str:
    """Register the SnapTrade user if not already registered.

    Skips registration when SNAPTRADE_USER_SECRET is already populated.
    On first run, persists the returned secret to env_path.

    Returns:
        The user secret (existing or newly issued).

    Raises:
        Exception: Any error returned by the SnapTrade registration API.
    """
    if config.snaptrade_user_secret:
        logger.info("SnapTrade user already registered — skipping registration")
        return config.snaptrade_user_secret

    snaptrade = build_client(config)
    try:
        response = snaptrade.authentication.register_snap_trade_user(
            user_id=config.snaptrade_user_id
        )
        user_secret = response.body["userSecret"]
    except Exception as exc:
        logger.error(f"SnapTrade user registration failed: {exc}")
        raise

    set_key(env_path, "SNAPTRADE_USER_SECRET", user_secret)
    logger.info("SnapTrade user registered and secret persisted to {}", env_path)
    return user_secret


def get_options_positions(config: Config) -> list[Position]:
    """Return all open options positions across every SnapTrade account.

    Non-option holdings and malformed entries are logged and skipped rather
    than causing a crash.

    Raises:
        ValueError: When SNAPTRADE_USER_SECRET is not set.
        Exception:  When the accounts list cannot be fetched.
    """
    if not config.snaptrade_user_secret:
        raise ValueError(
            "SNAPTRADE_USER_SECRET is not set. Call register_user() first."
        )

    snaptrade = build_client(config)

    try:
        accounts_resp = snaptrade.account_information.list_user_accounts(
            user_id=config.snaptrade_user_id,
            user_secret=config.snaptrade_user_secret,
        )
        accounts = accounts_resp.body
    except Exception as exc:
        logger.error(f"Failed to fetch SnapTrade accounts: {exc}")
        raise

    positions: list[Position] = []

    for account in accounts:
        account_id = str(account["id"])
        try:
            holdings_resp = snaptrade.options.list_option_holdings(
                user_id=config.snaptrade_user_id,
                user_secret=config.snaptrade_user_secret,
                account_id=account_id,
            )
            raw_holdings = holdings_resp.body
        except Exception as exc:
            logger.warning(
                f"Failed to fetch option holdings for account {account_id}: {exc}"
            )
            continue

        for raw in raw_holdings:
            try:
                pos = _normalize_position(raw)
                if pos is not None:
                    positions.append(pos)
            except ValueError as exc:
                logger.warning(
                    "Skipping malformed holding ({}). Raw: {!r}", exc, raw
                )

    return positions


def _normalize_position(raw: dict) -> Optional[Position]:
    """Normalize a raw OptionsPosition dict into a Position dataclass.

    Returns:
        A ``Position`` for valid option holdings.
        ``None`` for non-option holdings (no ``option_symbol`` key), which are
        silently filtered.

    Raises:
        ValueError: When an option holding is present but required fields are
            missing or the structure is malformed.
    """
    try:
        symbol = raw["symbol"]
    except (KeyError, TypeError):
        raise ValueError(f"Position missing 'symbol' field: {raw!r}")

    if "option_symbol" not in symbol:
        return None

    try:
        opt = symbol["option_symbol"]
    except (KeyError, TypeError):
        raise ValueError(f"'symbol' missing 'option_symbol': {symbol!r}")

    _required = {"option_type", "strike_price", "expiration_date"}
    missing = _required - set(opt.keys())
    if missing:
        raise ValueError(
            f"option_symbol missing required fields {sorted(missing)}: {opt!r}"
        )

    try:
        underlying = opt["underlying_symbol"]
    except (KeyError, TypeError):
        raise ValueError(f"option_symbol missing 'underlying_symbol': {opt!r}")

    if "symbol" not in underlying:
        raise ValueError(
            f"underlying_symbol missing 'symbol' field: {underlying!r}"
        )

    position_id = str(symbol.get("id", ""))
    if not position_id:
        raise ValueError(f"'symbol' missing 'id' field: {symbol!r}")

    avg_cost_raw = raw.get("average_purchase_price")

    return Position(
        id=position_id,
        ticker=str(underlying["symbol"]),
        option_type=str(opt["option_type"]).lower(),
        strike=float(opt["strike_price"]),
        expiry=str(opt["expiration_date"]),
        quantity=int(raw.get("units", 0)),
        avg_cost=float(avg_cost_raw) if avg_cost_raw is not None else 0.0,
        opened_at=datetime.now(timezone.utc).isoformat(),
        status="open",
    )


if __name__ == "__main__":
    from config import load_config

    _cfg = load_config()
    _secret = register_user(_cfg)
    logger.info("Using user secret: ****{}", _secret[-4:])
    _positions = get_options_positions(_cfg)
    logger.info("Found {} open option position(s)", len(_positions))
    for _p in _positions:
        logger.info(
            "  {} {} strike={} expiry={} qty={}",
            _p.ticker,
            _p.option_type.upper(),
            _p.strike,
            _p.expiry,
            _p.quantity,
        )
