"""Discord embed builders for all three alert types.

Each builder returns a complete Discord webhook payload dict ready to POST.
No network calls happen here — that is notifier.py's job.
"""

from datetime import datetime, timezone

from database import Position
from price_tracker import compute_pct_change

_COLOR_OPEN    = 0x00FF00  # green
_COLOR_UPDATE  = 0xFFFF00  # yellow
_COLOR_CLOSE   = 0xFF0000  # red
_COLOR_STARTUP = 0x5865F2  # Discord blurple — distinct from alert colours


# ---------------------------------------------------------------------------
# Internal formatting helpers
# ---------------------------------------------------------------------------

def _contract_label(position: Position) -> str:
    """Return a short option label, e.g. 'AAPL 180C 2026-05-16'."""
    type_char = "C" if position.option_type == "call" else "P"
    strike = f"{position.strike:g}"
    return f"{position.ticker} {strike}{type_char} {position.expiry}"


def _fmt_expiry(expiry: str) -> str:
    """Convert 'YYYY-MM-DD' to human-readable 'Month D, YYYY'."""
    dt = datetime.strptime(expiry, "%Y-%m-%d")
    return f"{dt.strftime('%B')} {dt.day}, {dt.year}"


def _fmt_dollar(amount: float) -> str:
    """Format a dollar amount with exactly 2 decimal places."""
    return f"${amount:.2f}"


def _fmt_pnl(pnl: float) -> str:
    """Format a P&L value with an explicit sign, e.g. '+$165.00' or '-$40.00'."""
    sign = "+" if pnl >= 0 else "-"
    return f"{sign}${abs(pnl):.2f}"


def _fmt_pct(pct: float, decimals: int = 2) -> str:
    """Format a percentage with an explicit '+' sign for non-negative values."""
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.{decimals}f}%"


def _held_days(opened_at: str) -> str:
    """Return a human-readable hold duration from an ISO timestamp to now."""
    try:
        opened = datetime.fromisoformat(opened_at)
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - opened).days
    except (ValueError, TypeError):
        return "unknown"
    return f"{days} day{'s' if days != 1 else ''}"


def _build_embed(title: str, description: str, color: int) -> dict:
    """Wrap title, description, and color into a Discord webhook payload."""
    return {"embeds": [{"title": title, "description": description, "color": color}]}


# ---------------------------------------------------------------------------
# Public alert builders
# ---------------------------------------------------------------------------

def build_open_alert(position: Position, underlying_price: float) -> dict:
    """Build a green embed for a newly opened option position.

    Args:
        position:         The newly opened position.
        underlying_price: Underlying spot price at the time of detection.
    """
    contract  = _contract_label(position)
    type_str  = position.option_type.capitalize()
    total     = position.avg_cost * position.quantity * 100

    description = (
        f"**Contract:** {contract}\n"
        f"**Type:** {type_str} | **Strike:** {_fmt_dollar(position.strike)} | "
        f"**Expiry:** {_fmt_expiry(position.expiry)}\n"
        f"**Qty:** {position.quantity} contract(s) | "
        f"**Avg Cost:** {_fmt_dollar(position.avg_cost)} ({_fmt_dollar(total)} total)\n"
        f"**Underlying at open:** {_fmt_dollar(underlying_price)}"
    )
    return _build_embed("🟢 New Option Opened", description, _COLOR_OPEN)


def build_update_alert(
    position: Position,
    old_underlying: float,
    new_underlying: float,
    old_option_value: float,
    new_option_value: float,
    threshold_pct: float,
) -> dict:
    """Build a yellow embed for an underlying price update that crossed the threshold.

    Args:
        position:          The open position being tracked.
        old_underlying:    Underlying price at the previous snapshot.
        new_underlying:    Current underlying price.
        old_option_value:  Estimated option value at previous snapshot.
        new_option_value:  Estimated option value now.
        threshold_pct:     The configured alert threshold that was breached.
    """
    contract        = _contract_label(position)
    underlying_pct  = compute_pct_change(old_underlying, new_underlying)
    pnl             = (new_option_value - position.avg_cost) * position.quantity * 100
    pnl_pct         = (new_option_value - position.avg_cost) / position.avg_cost * 100

    description = (
        f"**Underlying:** {_fmt_dollar(old_underlying)} → {_fmt_dollar(new_underlying)} "
        f"({_fmt_pct(underlying_pct)})\n"
        f"**Est. Option Value:** {_fmt_dollar(old_option_value)} → {_fmt_dollar(new_option_value)}\n"
        f"**Est. P&L:** {_fmt_pnl(pnl)} ({_fmt_pct(pnl_pct, decimals=1)})\n"
        f"Delta trigger: underlying moved past {threshold_pct:g}% threshold"
    )
    return _build_embed(f"📊 Position Update — {contract}", description, _COLOR_UPDATE)


def build_startup_alert(
    poll_interval_seconds: int,
    threshold_pct: float,
    env: str,
    user_id: str,
) -> dict:
    """Build a blurple embed sent once when the bot connects successfully.

    Args:
        poll_interval_seconds: Configured poll cadence.
        threshold_pct:         Price-move alert threshold.
        env:                   Runtime environment string.
        user_id:               SnapTrade user ID being monitored.
    """
    description = (
        "Bot is now live and monitoring your Wealthsimple options portfolio.\n\n"
        f"**Poll interval:** {poll_interval_seconds}s | "
        f"**Alert threshold:** {threshold_pct:g}%\n"
        f"**Environment:** {env} | **User:** {user_id}"
    )
    return _build_embed("✅ deltaSimple Connected", description, _COLOR_STARTUP)


def build_close_alert(position: Position, close_price: float) -> dict:
    """Build a red embed for a position that has been closed.

    Args:
        position:    The closed position (avg_cost used as cost basis).
        close_price: The underlying price at the time of close detection.
    """
    contract = _contract_label(position)
    pnl      = (close_price - position.avg_cost) * position.quantity * 100
    pnl_pct  = (close_price - position.avg_cost) / position.avg_cost * 100
    held     = _held_days(position.opened_at)

    description = (
        f"**Closed avg cost:** {_fmt_dollar(position.avg_cost)} | "
        f"**Close price:** {_fmt_dollar(close_price)}\n"
        f"**Est. P&L:** {_fmt_pnl(pnl)} ({_fmt_pct(pnl_pct, decimals=1)})\n"
        f"**Held:** {held}"
    )
    return _build_embed(f"🔴 Option Closed — {contract}", description, _COLOR_CLOSE)
