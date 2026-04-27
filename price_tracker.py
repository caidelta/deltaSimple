"""Underlying price fetching and option value estimation for deltaSimple.

Uses yfinance for live price data. Option value estimation is a simple
directional-proxy model: no Black-Scholes, no greeks, no options chain.
"""

import sys

import yfinance as yf

from database import Position


def get_underlying_price(ticker: str) -> float:
    """Return the current market price for the given ticker.

    Args:
        ticker: Equity symbol, e.g. ``"AAPL"``.

    Returns:
        Most recent price as a ``float``.

    Raises:
        RuntimeError: When yfinance raises any exception (wraps with ticker name).
        ValueError:   When yfinance returns ``None`` for last_price.
    """
    try:
        price = yf.Ticker(ticker).fast_info.last_price
    except Exception as exc:
        raise RuntimeError(
            f"yfinance failed to fetch price for {ticker!r}: {exc}"
        ) from exc

    if price is None:
        raise ValueError(
            f"yfinance returned no price for {ticker!r} — check the symbol is valid"
        )

    return float(price)


def compute_pct_change(old_price: float, new_price: float) -> float:
    """Return the signed percentage change from old_price to new_price.

    Args:
        old_price: Reference price (must be non-zero).
        new_price: Current price.

    Returns:
        Signed percentage, e.g. ``5.0`` for a 5 % gain, ``-5.0`` for a loss.

    Raises:
        ValueError: When ``old_price`` is zero.
    """
    if old_price == 0:
        raise ValueError("old_price must be non-zero to compute percentage change")
    return (new_price - old_price) / old_price * 100.0


def estimate_option_value(
    position: Position,
    old_underlying: float,
    new_underlying: float,
) -> float:
    """Estimate the current per-contract option value after an underlying move.

    Model: the option value scales by the same percentage as the underlying,
    with directional sign adjusted for option type:

    - **Call**: gains when underlying rises, loses when it falls.
    - **Put**: gains when underlying falls, loses when it rises.

    The result is clamped to ``0.0`` — option value cannot go negative.

    Args:
        position:       Open option position; ``avg_cost`` is the baseline value.
        old_underlying: Underlying price at the previous snapshot.
        new_underlying: Current underlying price.

    Returns:
        Estimated per-contract value in the same units as ``position.avg_cost``.

    Raises:
        ValueError: When ``old_underlying`` is zero.
    """
    pct = compute_pct_change(old_underlying, new_underlying)

    if position.option_type == "call":
        scale = 1.0 + pct / 100.0
    else:
        scale = 1.0 - pct / 100.0

    return max(0.0, position.avg_cost * scale)


if __name__ == "__main__":
    _ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    _price = get_underlying_price(_ticker)
    print(f"{_ticker}: ${_price:.2f}")
