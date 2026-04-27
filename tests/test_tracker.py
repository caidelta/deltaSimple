"""Tests for tracker.py — main polling loop.

Strategy:
- `sync_to_thread` (autouse) replaces asyncio.to_thread with a shim that calls
  functions synchronously, so in-memory SQLite connections stay on one thread.
- `mock_discord` patches notifier.send_discord with an AsyncMock.
- SnapTrade and yfinance are monkeypatched per-test via simple lambdas.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

import database
import tracker
from database import Position


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _pos(
    pos_id: str = "pos-1",
    ticker: str = "AAPL",
    option_type: str = "call",
    strike: float = 180.0,
    expiry: str = "2026-12-19",
    quantity: int = 1,
    avg_cost: float = 3.20,
    opened_at: str = "2026-04-26T10:00:00+00:00",
    status: str = "open",
) -> Position:
    return Position(
        id=pos_id,
        ticker=ticker,
        option_type=option_type,
        strike=strike,
        expiry=expiry,
        quantity=quantity,
        avg_cost=avg_cost,
        opened_at=opened_at,
        status=status,
    )


@pytest.fixture
def conn():
    """In-memory SQLite connection with schema pre-initialised."""
    c = database.connect(":memory:")
    database.init_db(c)
    return c


@pytest.fixture(autouse=True)
def sync_to_thread(monkeypatch):
    """Replace asyncio.to_thread with a shim so all DB calls stay on the test thread."""
    async def _fake(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr("tracker.asyncio.to_thread", _fake)


@pytest.fixture
def mock_discord(monkeypatch):
    """Patch notifier.send_discord as an AsyncMock and return it for assertions."""
    m = AsyncMock()
    monkeypatch.setattr("tracker.notifier.send_discord", m)
    return m


def _titles(mock_discord):
    """Extract embed titles from all send_discord calls."""
    return [c.args[0]["embeds"][0]["title"] for c in mock_discord.call_args_list]


# ---------------------------------------------------------------------------
# _handle_new
# ---------------------------------------------------------------------------

class TestHandleNew:
    async def test_sends_open_alert(self, conn, mock_discord, monkeypatch):
        monkeypatch.setattr("tracker.price_tracker.get_underlying_price", lambda t: 178.0)
        config = MagicMock(discord_webhook_url="http://hook")

        await tracker._handle_new(_pos(), conn, config)

        mock_discord.assert_called_once()
        assert "New Option Opened" in _titles(mock_discord)[0]

    async def test_saves_position_to_db(self, conn, mock_discord, monkeypatch):
        monkeypatch.setattr("tracker.price_tracker.get_underlying_price", lambda t: 178.0)
        config = MagicMock(discord_webhook_url="http://hook")

        pos = _pos()
        await tracker._handle_new(pos, conn, config)

        assert any(p.id == pos.id for p in database.get_open_positions(conn))

    async def test_saves_price_snapshot(self, conn, mock_discord, monkeypatch):
        monkeypatch.setattr("tracker.price_tracker.get_underlying_price", lambda t: 178.0)
        config = MagicMock(discord_webhook_url="http://hook")

        pos = _pos()
        await tracker._handle_new(pos, conn, config)

        assert database.get_last_price(conn, pos.id) == 178.0


# ---------------------------------------------------------------------------
# _handle_update
# ---------------------------------------------------------------------------

class TestHandleUpdate:
    async def test_alert_when_threshold_exceeded(self, conn, mock_discord, monkeypatch):
        pos = _pos()
        database.upsert_position(conn, pos)
        database.upsert_price_snapshot(conn, pos.id, 100.0)
        monkeypatch.setattr("tracker.price_tracker.get_underlying_price", lambda t: 110.0)
        config = MagicMock(discord_webhook_url="http://hook", price_alert_threshold_pct=5.0)

        await tracker._handle_update(pos, conn, config)

        mock_discord.assert_called_once()
        assert "Position Update" in _titles(mock_discord)[0]

    async def test_no_alert_below_threshold(self, conn, mock_discord, monkeypatch):
        pos = _pos()
        database.upsert_position(conn, pos)
        database.upsert_price_snapshot(conn, pos.id, 100.0)
        monkeypatch.setattr("tracker.price_tracker.get_underlying_price", lambda t: 102.0)
        config = MagicMock(discord_webhook_url="http://hook", price_alert_threshold_pct=5.0)

        await tracker._handle_update(pos, conn, config)

        mock_discord.assert_not_called()

    async def test_snapshot_refreshed_after_alert(self, conn, mock_discord, monkeypatch):
        pos = _pos()
        database.upsert_position(conn, pos)
        database.upsert_price_snapshot(conn, pos.id, 100.0)
        monkeypatch.setattr("tracker.price_tracker.get_underlying_price", lambda t: 110.0)
        config = MagicMock(discord_webhook_url="http://hook", price_alert_threshold_pct=5.0)

        await tracker._handle_update(pos, conn, config)

        assert database.get_last_price(conn, pos.id) == 110.0

    async def test_snapshot_not_refreshed_when_no_alert(self, conn, mock_discord, monkeypatch):
        pos = _pos()
        database.upsert_position(conn, pos)
        database.upsert_price_snapshot(conn, pos.id, 100.0)
        monkeypatch.setattr("tracker.price_tracker.get_underlying_price", lambda t: 102.0)
        config = MagicMock(discord_webhook_url="http://hook", price_alert_threshold_pct=5.0)

        await tracker._handle_update(pos, conn, config)

        assert database.get_last_price(conn, pos.id) == 100.0

    async def test_no_snapshot_seeds_price_without_alert(self, conn, mock_discord, monkeypatch):
        """Position in DB but no snapshot yet — seeds the price without alerting."""
        pos = _pos()
        database.upsert_position(conn, pos)
        monkeypatch.setattr("tracker.price_tracker.get_underlying_price", lambda t: 178.0)
        config = MagicMock(discord_webhook_url="http://hook", price_alert_threshold_pct=5.0)

        await tracker._handle_update(pos, conn, config)

        mock_discord.assert_not_called()
        assert database.get_last_price(conn, pos.id) == 178.0


# ---------------------------------------------------------------------------
# _handle_closed
# ---------------------------------------------------------------------------

class TestHandleClosed:
    async def test_sends_close_alert(self, conn, mock_discord, monkeypatch):
        pos = _pos()
        database.upsert_position(conn, pos)
        monkeypatch.setattr("tracker.price_tracker.get_underlying_price", lambda t: 170.0)
        config = MagicMock(discord_webhook_url="http://hook")

        await tracker._handle_closed(pos, conn, config)

        mock_discord.assert_called_once()
        assert "Option Closed" in _titles(mock_discord)[0]

    async def test_marks_position_closed_in_db(self, conn, mock_discord, monkeypatch):
        pos = _pos()
        database.upsert_position(conn, pos)
        monkeypatch.setattr("tracker.price_tracker.get_underlying_price", lambda t: 170.0)
        config = MagicMock(discord_webhook_url="http://hook")

        await tracker._handle_closed(pos, conn, config)

        assert not any(p.id == pos.id for p in database.get_open_positions(conn))

    async def test_falls_back_to_avg_cost_when_price_fetch_fails(
        self, conn, mock_discord, monkeypatch
    ):
        pos = _pos(avg_cost=3.20)
        database.upsert_position(conn, pos)

        def _fail(_):
            raise RuntimeError("yfinance down")

        monkeypatch.setattr("tracker.price_tracker.get_underlying_price", _fail)
        config = MagicMock(discord_webhook_url="http://hook")

        await tracker._handle_closed(pos, conn, config)

        mock_discord.assert_called_once()
        desc = mock_discord.call_args[0][0]["embeds"][0]["description"]
        assert "$3.20" in desc


# ---------------------------------------------------------------------------
# _process_tick — integration-level
# ---------------------------------------------------------------------------

class TestProcessTick:
    async def test_new_position_fires_open_alert(self, conn, mock_discord, monkeypatch):
        pos = _pos()
        monkeypatch.setattr("tracker.snaptrade_client.get_options_positions", lambda c: [pos])
        monkeypatch.setattr("tracker.price_tracker.get_underlying_price", lambda t: 178.0)
        config = MagicMock(discord_webhook_url="http://hook", price_alert_threshold_pct=5.0)

        await tracker._process_tick(conn, config)

        assert any("New Option Opened" in t for t in _titles(mock_discord))

    async def test_existing_position_does_not_refire_open_alert(
        self, conn, mock_discord, monkeypatch
    ):
        """Duplicate prevention: position already in DB goes to update path, not open."""
        pos = _pos()
        database.upsert_position(conn, pos)
        database.upsert_price_snapshot(conn, pos.id, 178.0)
        monkeypatch.setattr("tracker.snaptrade_client.get_options_positions", lambda c: [pos])
        monkeypatch.setattr("tracker.price_tracker.get_underlying_price", lambda t: 179.0)
        config = MagicMock(discord_webhook_url="http://hook", price_alert_threshold_pct=5.0)

        await tracker._process_tick(conn, config)

        assert not any("New Option Opened" in t for t in _titles(mock_discord))

    async def test_threshold_crossed_fires_update_alert(self, conn, mock_discord, monkeypatch):
        pos = _pos()
        database.upsert_position(conn, pos)
        database.upsert_price_snapshot(conn, pos.id, 100.0)
        monkeypatch.setattr("tracker.snaptrade_client.get_options_positions", lambda c: [pos])
        monkeypatch.setattr("tracker.price_tracker.get_underlying_price", lambda t: 110.0)
        config = MagicMock(discord_webhook_url="http://hook", price_alert_threshold_pct=5.0)

        await tracker._process_tick(conn, config)

        assert any("Position Update" in t for t in _titles(mock_discord))

    async def test_below_threshold_no_alert(self, conn, mock_discord, monkeypatch):
        pos = _pos()
        database.upsert_position(conn, pos)
        database.upsert_price_snapshot(conn, pos.id, 100.0)
        monkeypatch.setattr("tracker.snaptrade_client.get_options_positions", lambda c: [pos])
        monkeypatch.setattr("tracker.price_tracker.get_underlying_price", lambda t: 102.0)
        config = MagicMock(discord_webhook_url="http://hook", price_alert_threshold_pct=5.0)

        await tracker._process_tick(conn, config)

        mock_discord.assert_not_called()

    async def test_gone_position_fires_close_alert(self, conn, mock_discord, monkeypatch):
        pos = _pos()
        database.upsert_position(conn, pos)
        monkeypatch.setattr("tracker.snaptrade_client.get_options_positions", lambda c: [])
        monkeypatch.setattr("tracker.price_tracker.get_underlying_price", lambda t: 170.0)
        config = MagicMock(discord_webhook_url="http://hook")

        await tracker._process_tick(conn, config)

        assert any("Option Closed" in t for t in _titles(mock_discord))

    async def test_no_positions_anywhere_no_alerts(self, conn, mock_discord, monkeypatch):
        monkeypatch.setattr("tracker.snaptrade_client.get_options_positions", lambda c: [])
        config = MagicMock(discord_webhook_url="http://hook", price_alert_threshold_pct=5.0)

        await tracker._process_tick(conn, config)

        mock_discord.assert_not_called()

    async def test_multiple_positions_handled_independently(
        self, conn, mock_discord, monkeypatch
    ):
        pos_new = _pos(pos_id="new-1", ticker="AAPL")
        pos_existing = _pos(pos_id="exist-1", ticker="TSLA")
        pos_closed = _pos(pos_id="closed-1", ticker="NVDA")

        database.upsert_position(conn, pos_existing)
        database.upsert_price_snapshot(conn, pos_existing.id, 100.0)
        database.upsert_position(conn, pos_closed)

        monkeypatch.setattr(
            "tracker.snaptrade_client.get_options_positions",
            lambda c: [pos_new, pos_existing],
        )
        monkeypatch.setattr("tracker.price_tracker.get_underlying_price", lambda t: 102.0)
        config = MagicMock(discord_webhook_url="http://hook", price_alert_threshold_pct=5.0)

        await tracker._process_tick(conn, config)

        titles = _titles(mock_discord)
        assert any("New Option Opened" in t for t in titles)
        assert any("Option Closed" in t for t in titles)
        assert not any("Position Update" in t for t in titles)
