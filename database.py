"""SQLite database layer for deltaSimple.

All public functions accept an open sqlite3.Connection so callers control
connection lifecycle and tests can pass an in-memory connection.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Position:
    """Represents a single options position tracked by the bot."""

    id: str
    ticker: str
    option_type: str   # "call" or "put"
    strike: float
    expiry: str        # "YYYY-MM-DD"
    quantity: int
    avg_cost: float    # per contract
    opened_at: str     # ISO timestamp
    status: str = "open"


def connect(db_path: str = "tracker.db") -> sqlite3.Connection:
    """Open a connection to the SQLite database at db_path.

    Pass ':memory:' for an in-memory database (tests only).
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create positions and price_snapshots tables if they do not already exist."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS positions (
            id          TEXT PRIMARY KEY,
            ticker      TEXT    NOT NULL,
            option_type TEXT    NOT NULL,
            strike      REAL    NOT NULL,
            expiry      TEXT    NOT NULL,
            quantity    INTEGER NOT NULL,
            avg_cost    REAL    NOT NULL,
            opened_at   TEXT    NOT NULL,
            status      TEXT    NOT NULL DEFAULT 'open'
        );

        CREATE TABLE IF NOT EXISTS price_snapshots (
            position_id TEXT PRIMARY KEY,
            last_price  REAL NOT NULL,
            updated_at  TEXT NOT NULL
        );
        """
    )
    conn.commit()


def upsert_position(conn: sqlite3.Connection, position: Position) -> None:
    """Insert a new position or replace an existing one with the same id."""
    conn.execute(
        """
        INSERT OR REPLACE INTO positions
            (id, ticker, option_type, strike, expiry, quantity, avg_cost, opened_at, status)
        VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            position.id,
            position.ticker,
            position.option_type,
            position.strike,
            position.expiry,
            position.quantity,
            position.avg_cost,
            position.opened_at,
            position.status,
        ),
    )
    conn.commit()


def get_open_positions(conn: sqlite3.Connection) -> list[Position]:
    """Return all positions whose status is 'open'."""
    cursor = conn.execute(
        """
        SELECT id, ticker, option_type, strike, expiry, quantity, avg_cost, opened_at, status
        FROM positions
        WHERE status = 'open'
        """
    )
    return [Position(*tuple(row)) for row in cursor.fetchall()]


def mark_position_closed(conn: sqlite3.Connection, position_id: str) -> None:
    """Set status='closed' for the given position id.

    No-op if the position_id does not exist.
    """
    conn.execute(
        "UPDATE positions SET status = 'closed' WHERE id = ?",
        (position_id,),
    )
    conn.commit()


def upsert_price_snapshot(
    conn: sqlite3.Connection, position_id: str, price: float
) -> None:
    """Insert or overwrite the most recent price snapshot for a position."""
    conn.execute(
        """
        INSERT OR REPLACE INTO price_snapshots (position_id, last_price, updated_at)
        VALUES (?, ?, ?)
        """,
        (position_id, price, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def get_last_price(conn: sqlite3.Connection, position_id: str) -> Optional[float]:
    """Return the last recorded underlying price for a position, or None if unknown."""
    cursor = conn.execute(
        "SELECT last_price FROM price_snapshots WHERE position_id = ?",
        (position_id,),
    )
    row = cursor.fetchone()
    return float(row[0]) if row else None
