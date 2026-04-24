"""Tests for database.py — all use in-memory SQLite, no file is created."""

import sqlite3

import pytest

from database import (
    Position,
    connect,
    get_last_price,
    get_open_positions,
    init_db,
    mark_position_closed,
    upsert_position,
    upsert_price_snapshot,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn():
    """In-memory SQLite connection with both tables initialised."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pos(**overrides) -> Position:
    """Build a Position with sensible defaults; override any field via kwargs."""
    defaults = dict(
        id="pos-1",
        ticker="AAPL",
        option_type="call",
        strike=180.0,
        expiry="2026-05-16",
        quantity=1,
        avg_cost=3.20,
        opened_at="2026-04-24T10:00:00",
        status="open",
    )
    defaults.update(overrides)
    return Position(**defaults)


def _table_names(conn: sqlite3.Connection) -> set[str]:
    """Return the set of user-created table names in the database."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {row[0] for row in rows}


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

class TestInitDb:
    def test_creates_positions_table(self, conn):
        assert "positions" in _table_names(conn)

    def test_creates_price_snapshots_table(self, conn):
        assert "price_snapshots" in _table_names(conn)

    def test_idempotent_when_called_twice(self, conn):
        """Calling init_db on an already-initialised DB must not raise."""
        init_db(conn)
        assert _table_names(conn) == {"positions", "price_snapshots"}


# ---------------------------------------------------------------------------
# upsert_position
# ---------------------------------------------------------------------------

class TestUpsertPosition:
    def test_inserts_new_position(self, conn):
        upsert_position(conn, _pos())
        rows = conn.execute("SELECT * FROM positions").fetchall()
        assert len(rows) == 1

    def test_inserted_fields_match(self, conn):
        p = _pos()
        upsert_position(conn, p)
        row = conn.execute("SELECT * FROM positions WHERE id = ?", (p.id,)).fetchone()
        assert row["ticker"] == "AAPL"
        assert row["option_type"] == "call"
        assert row["strike"] == 180.0
        assert row["expiry"] == "2026-05-16"
        assert row["quantity"] == 1
        assert row["avg_cost"] == pytest.approx(3.20)
        assert row["opened_at"] == "2026-04-24T10:00:00"
        assert row["status"] == "open"

    def test_no_duplicate_on_same_id(self, conn):
        upsert_position(conn, _pos())
        upsert_position(conn, _pos())
        count = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
        assert count == 1

    def test_updates_existing_row_fields(self, conn):
        upsert_position(conn, _pos(quantity=1, avg_cost=3.20))
        upsert_position(conn, _pos(quantity=2, avg_cost=2.80))
        row = conn.execute("SELECT * FROM positions WHERE id = 'pos-1'").fetchone()
        assert row["quantity"] == 2
        assert row["avg_cost"] == pytest.approx(2.80)

    def test_multiple_distinct_positions(self, conn):
        upsert_position(conn, _pos(id="pos-1", ticker="AAPL"))
        upsert_position(conn, _pos(id="pos-2", ticker="TSLA"))
        count = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
        assert count == 2

    def test_default_status_is_open(self, conn):
        upsert_position(conn, _pos())
        row = conn.execute("SELECT status FROM positions WHERE id = 'pos-1'").fetchone()
        assert row["status"] == "open"


# ---------------------------------------------------------------------------
# get_open_positions
# ---------------------------------------------------------------------------

class TestGetOpenPositions:
    def test_returns_empty_list_when_no_positions(self, conn):
        assert get_open_positions(conn) == []

    def test_returns_open_positions(self, conn):
        upsert_position(conn, _pos(id="pos-1", status="open"))
        upsert_position(conn, _pos(id="pos-2", status="open"))
        result = get_open_positions(conn)
        assert len(result) == 2

    def test_excludes_closed_positions(self, conn):
        upsert_position(conn, _pos(id="pos-open", status="open"))
        upsert_position(conn, _pos(id="pos-closed", status="closed"))
        result = get_open_positions(conn)
        assert len(result) == 1
        assert result[0].id == "pos-open"

    def test_returns_position_dataclass_instances(self, conn):
        upsert_position(conn, _pos())
        result = get_open_positions(conn)
        assert isinstance(result[0], Position)

    def test_returned_fields_match_inserted(self, conn):
        p = _pos(ticker="NVDA", strike=900.0, quantity=3)
        upsert_position(conn, p)
        result = get_open_positions(conn)
        r = result[0]
        assert r.ticker == "NVDA"
        assert r.strike == 900.0
        assert r.quantity == 3

    def test_all_closed_returns_empty(self, conn):
        upsert_position(conn, _pos(id="pos-1", status="closed"))
        upsert_position(conn, _pos(id="pos-2", status="closed"))
        assert get_open_positions(conn) == []


# ---------------------------------------------------------------------------
# mark_position_closed
# ---------------------------------------------------------------------------

class TestMarkPositionClosed:
    def test_changes_status_to_closed(self, conn):
        upsert_position(conn, _pos())
        mark_position_closed(conn, "pos-1")
        row = conn.execute("SELECT status FROM positions WHERE id = 'pos-1'").fetchone()
        assert row["status"] == "closed"

    def test_closed_position_absent_from_get_open(self, conn):
        upsert_position(conn, _pos())
        mark_position_closed(conn, "pos-1")
        assert get_open_positions(conn) == []

    def test_only_targeted_position_is_closed(self, conn):
        upsert_position(conn, _pos(id="pos-1"))
        upsert_position(conn, _pos(id="pos-2"))
        mark_position_closed(conn, "pos-1")
        open_ids = {p.id for p in get_open_positions(conn)}
        assert open_ids == {"pos-2"}

    def test_nonexistent_id_does_not_raise(self, conn):
        """mark_position_closed on an unknown id should be a silent no-op."""
        mark_position_closed(conn, "does-not-exist")

    def test_idempotent_double_close(self, conn):
        upsert_position(conn, _pos())
        mark_position_closed(conn, "pos-1")
        mark_position_closed(conn, "pos-1")
        row = conn.execute("SELECT status FROM positions WHERE id = 'pos-1'").fetchone()
        assert row["status"] == "closed"


# ---------------------------------------------------------------------------
# upsert_price_snapshot
# ---------------------------------------------------------------------------

class TestUpsertPriceSnapshot:
    def test_inserts_snapshot(self, conn):
        upsert_price_snapshot(conn, "pos-1", 178.45)
        row = conn.execute(
            "SELECT last_price FROM price_snapshots WHERE position_id = 'pos-1'"
        ).fetchone()
        assert row is not None

    def test_stored_price_matches(self, conn):
        upsert_price_snapshot(conn, "pos-1", 178.45)
        row = conn.execute(
            "SELECT last_price FROM price_snapshots WHERE position_id = 'pos-1'"
        ).fetchone()
        assert row["last_price"] == pytest.approx(178.45)

    def test_overwrites_existing_snapshot(self, conn):
        upsert_price_snapshot(conn, "pos-1", 100.0)
        upsert_price_snapshot(conn, "pos-1", 200.0)
        count = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
        assert count == 1
        row = conn.execute(
            "SELECT last_price FROM price_snapshots WHERE position_id = 'pos-1'"
        ).fetchone()
        assert row["last_price"] == pytest.approx(200.0)

    def test_updated_at_is_populated(self, conn):
        upsert_price_snapshot(conn, "pos-1", 178.45)
        row = conn.execute(
            "SELECT updated_at FROM price_snapshots WHERE position_id = 'pos-1'"
        ).fetchone()
        assert row["updated_at"] is not None
        assert len(row["updated_at"]) > 0

    def test_multiple_positions_stored_independently(self, conn):
        upsert_price_snapshot(conn, "pos-1", 100.0)
        upsert_price_snapshot(conn, "pos-2", 200.0)
        count = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
        assert count == 2


# ---------------------------------------------------------------------------
# get_last_price
# ---------------------------------------------------------------------------

class TestGetLastPrice:
    def test_returns_none_for_unknown_position(self, conn):
        assert get_last_price(conn, "does-not-exist") is None

    def test_returns_correct_price_after_insert(self, conn):
        upsert_price_snapshot(conn, "pos-1", 178.45)
        assert get_last_price(conn, "pos-1") == pytest.approx(178.45)

    def test_returns_latest_price_after_overwrite(self, conn):
        upsert_price_snapshot(conn, "pos-1", 100.0)
        upsert_price_snapshot(conn, "pos-1", 155.75)
        assert get_last_price(conn, "pos-1") == pytest.approx(155.75)

    def test_returns_float(self, conn):
        upsert_price_snapshot(conn, "pos-1", 50.0)
        result = get_last_price(conn, "pos-1")
        assert isinstance(result, float)

    def test_does_not_cross_contaminate_positions(self, conn):
        upsert_price_snapshot(conn, "pos-1", 100.0)
        upsert_price_snapshot(conn, "pos-2", 200.0)
        assert get_last_price(conn, "pos-1") == pytest.approx(100.0)
        assert get_last_price(conn, "pos-2") == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# connect() — in-memory path only
# ---------------------------------------------------------------------------

class TestConnect:
    def test_returns_sqlite_connection(self):
        c = connect(":memory:")
        assert isinstance(c, sqlite3.Connection)
        c.close()

    def test_row_factory_is_set(self):
        c = connect(":memory:")
        assert c.row_factory is sqlite3.Row
        c.close()
