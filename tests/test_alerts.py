"""Tests for alerts.py — embed structure, content, formatting, and colors."""

from datetime import datetime, timezone, timedelta

import pytest

from database import Position
import alerts


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _pos(**overrides) -> Position:
    """Build a Position with sensible defaults."""
    defaults = dict(
        id="pos-1",
        ticker="AAPL",
        option_type="call",
        strike=180.0,
        expiry="2026-05-16",
        quantity=1,
        avg_cost=3.20,
        opened_at="2026-04-01T10:00:00+00:00",
        status="open",
    )
    defaults.update(overrides)
    return Position(**defaults)


def _desc(payload: dict) -> str:
    """Extract the embed description from a webhook payload."""
    return payload["embeds"][0]["description"]


def _title(payload: dict) -> str:
    return payload["embeds"][0]["title"]


def _color(payload: dict) -> int:
    return payload["embeds"][0]["color"]


# ---------------------------------------------------------------------------
# build_open_alert
# ---------------------------------------------------------------------------

class TestBuildOpenAlert:
    def test_returns_dict_with_embeds_key(self):
        payload = alerts.build_open_alert(_pos(), 178.45)
        assert "embeds" in payload
        assert isinstance(payload["embeds"], list)
        assert len(payload["embeds"]) == 1

    def test_title_contains_new_option_opened(self):
        assert "New Option Opened" in _title(alerts.build_open_alert(_pos(), 178.45))

    def test_color_is_green(self):
        assert _color(alerts.build_open_alert(_pos(), 178.45)) == 0x00FF00

    def test_description_contains_ticker(self):
        assert "AAPL" in _desc(alerts.build_open_alert(_pos(), 178.45))

    def test_description_contains_strike(self):
        assert "180" in _desc(alerts.build_open_alert(_pos(strike=180.0), 178.45))

    def test_description_contains_option_type_call(self):
        desc = _desc(alerts.build_open_alert(_pos(option_type="call"), 178.45))
        assert "Call" in desc

    def test_description_contains_option_type_put(self):
        desc = _desc(alerts.build_open_alert(_pos(option_type="put"), 178.45))
        assert "Put" in desc

    def test_description_contains_avg_cost_formatted(self):
        """Avg cost is formatted as $3.20, not $3.2 or $3.2000."""
        assert "$3.20" in _desc(alerts.build_open_alert(_pos(avg_cost=3.20), 178.45))

    def test_description_contains_total_cost(self):
        """1 contract × avg_cost $3.20 × 100 = $320.00 total."""
        assert "$320.00" in _desc(alerts.build_open_alert(_pos(), 178.45))

    def test_total_cost_scales_with_quantity(self):
        """2 contracts × $3.20 × 100 = $640.00."""
        assert "$640.00" in _desc(alerts.build_open_alert(_pos(quantity=2), 178.45))

    def test_description_contains_underlying_price(self):
        assert "$178.45" in _desc(alerts.build_open_alert(_pos(), 178.45))

    def test_dollar_format_two_decimals_not_four(self):
        """$3.20 must appear, not $3.2000."""
        desc = _desc(alerts.build_open_alert(_pos(avg_cost=3.20), 178.45))
        assert "$3.2000" not in desc
        assert "$3.20" in desc

    def test_contract_label_call(self):
        """Contract label uses 'C' for call, e.g. 'AAPL 180C 2026-05-16'."""
        assert "180C" in _desc(alerts.build_open_alert(_pos(option_type="call"), 178.0))

    def test_contract_label_put(self):
        """Contract label uses 'P' for put."""
        assert "180P" in _desc(alerts.build_open_alert(_pos(option_type="put"), 178.0))

    def test_expiry_human_readable(self):
        """Expiry is displayed as 'May 16, 2026', not raw '2026-05-16'."""
        desc = _desc(alerts.build_open_alert(_pos(expiry="2026-05-16"), 178.45))
        assert "May 16, 2026" in desc

    def test_fractional_strike_no_trailing_zeros(self):
        """Strike 182.5 appears as '182.5', not '182.50'."""
        desc = _desc(alerts.build_open_alert(_pos(strike=182.5), 178.45))
        assert "182.5C" in desc


# ---------------------------------------------------------------------------
# build_update_alert
# ---------------------------------------------------------------------------

class TestBuildUpdateAlert:
    def _call_update(self, **overrides):
        pos_kw = {k: v for k, v in overrides.items() if k in Position.__dataclass_fields__}
        extra = {k: v for k, v in overrides.items() if k not in Position.__dataclass_fields__}
        return alerts.build_update_alert(
            _pos(**pos_kw),
            old_underlying=extra.get("old_underlying", 178.45),
            new_underlying=extra.get("new_underlying", 187.20),
            old_option_value=extra.get("old_option_value", 3.20),
            new_option_value=extra.get("new_option_value", 4.85),
            threshold_pct=extra.get("threshold_pct", 5.0),
        )

    def test_color_is_yellow(self):
        assert _color(self._call_update()) == 0xFFFF00

    def test_title_contains_position_update(self):
        assert "Position Update" in _title(self._call_update())

    def test_title_contains_contract_label(self):
        assert "AAPL" in _title(self._call_update())

    def test_description_contains_old_underlying(self):
        assert "$178.45" in _desc(self._call_update(old_underlying=178.45))

    def test_description_contains_new_underlying(self):
        assert "$187.20" in _desc(self._call_update(new_underlying=187.20))

    def test_description_contains_pct_change_with_sign(self):
        """(187.20 - 178.45) / 178.45 ≈ +4.90% — sign must be present."""
        desc = _desc(self._call_update(old_underlying=178.45, new_underlying=187.20))
        assert "+" in desc  # positive move has explicit plus sign

    def test_description_contains_old_option_value(self):
        assert "$3.20" in _desc(self._call_update(old_option_value=3.20))

    def test_description_contains_new_option_value(self):
        assert "$4.85" in _desc(self._call_update(new_option_value=4.85))

    def test_description_contains_pnl_dollar(self):
        """P&L = (4.85 - 3.20) × 1 × 100 = $165.00."""
        assert "$165.00" in _desc(self._call_update(
            avg_cost=3.20, new_option_value=4.85, quantity=1
        ))

    def test_description_contains_pnl_pct(self):
        """P&L% = (4.85 - 3.20) / 3.20 × 100 ≈ 51.6%."""
        assert "51.6%" in _desc(self._call_update(
            avg_cost=3.20, new_option_value=4.85
        ))

    def test_description_contains_threshold(self):
        desc = _desc(self._call_update(threshold_pct=5.0))
        assert "5%" in desc or "5.0%" in desc

    def test_negative_pnl_shows_minus_sign(self):
        """A losing trade shows a '-' prefix."""
        desc = _desc(self._call_update(avg_cost=5.00, new_option_value=3.00))
        assert "-$" in desc

    def test_underlying_pct_two_decimal_places(self):
        """Underlying pct change is formatted to 2 decimal places."""
        desc = _desc(self._call_update(old_underlying=100.0, new_underlying=105.0))
        assert "+5.00%" in desc

    def test_pnl_pct_one_decimal_place(self):
        """P&L pct is formatted to 1 decimal place."""
        desc = _desc(self._call_update(avg_cost=4.00, new_option_value=4.20))
        assert "+5.0%" in desc


# ---------------------------------------------------------------------------
# build_close_alert
# ---------------------------------------------------------------------------

class TestBuildCloseAlert:
    def test_color_is_red(self):
        assert _color(alerts.build_close_alert(_pos(), 5.10)) == 0xFF0000

    def test_title_contains_option_closed(self):
        assert "Option Closed" in _title(alerts.build_close_alert(_pos(), 5.10))

    def test_title_contains_contract_label(self):
        assert "AAPL" in _title(alerts.build_close_alert(_pos(), 5.10))

    def test_description_contains_avg_cost(self):
        assert "$3.20" in _desc(alerts.build_close_alert(_pos(avg_cost=3.20), 5.10))

    def test_description_contains_close_price(self):
        assert "$5.10" in _desc(alerts.build_close_alert(_pos(), 5.10))

    def test_description_contains_pnl_dollar(self):
        """P&L = (5.10 - 3.20) × 1 × 100 = $190.00."""
        assert "$190.00" in _desc(alerts.build_close_alert(_pos(avg_cost=3.20), 5.10))

    def test_description_contains_pnl_pct(self):
        """P&L% = (5.10 - 3.20) / 3.20 × 100 = 59.375% ≈ 59.4%."""
        assert "59.4%" in _desc(alerts.build_close_alert(_pos(avg_cost=3.20), 5.10))

    def test_pnl_pct_one_decimal(self):
        """P&L pct uses 1 decimal place."""
        desc = _desc(alerts.build_close_alert(_pos(avg_cost=4.00), 5.00))
        assert "+25.0%" in desc

    def test_negative_pnl_has_minus_sign(self):
        """A losing close shows '-$'."""
        desc = _desc(alerts.build_close_alert(_pos(avg_cost=5.00), 3.00))
        assert "-$" in desc

    def test_description_contains_held_days(self):
        """Hold duration appears in the description."""
        desc = _desc(alerts.build_close_alert(_pos(), 5.10))
        assert "day" in desc

    def test_held_duration_reflects_opened_at(self):
        """A position opened 3 days ago shows '3 days'."""
        three_days_ago = (
            datetime.now(timezone.utc) - timedelta(days=3)
        ).isoformat()
        pos = _pos(opened_at=three_days_ago)
        assert "3 days" in _desc(alerts.build_close_alert(pos, 5.10))

    def test_held_one_day_singular(self):
        """'1 day', not '1 days'."""
        one_day_ago = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).isoformat()
        pos = _pos(opened_at=one_day_ago)
        desc = _desc(alerts.build_close_alert(pos, 5.10))
        assert "1 day" in desc
        assert "1 days" not in desc

    def test_dollar_format_two_decimals(self):
        """$5.10 must appear, not $5.1 or $5.1000."""
        desc = _desc(alerts.build_close_alert(_pos(), 5.10))
        assert "$5.10" in desc
        assert "$5.1000" not in desc

    def test_pnl_positive_has_plus_sign(self):
        """Profitable close shows '+$' prefix."""
        desc = _desc(alerts.build_close_alert(_pos(avg_cost=3.20), 5.10))
        assert "+$" in desc


# ---------------------------------------------------------------------------
# Shared embed structure tests
# ---------------------------------------------------------------------------

class TestEmbedStructure:
    def test_all_payloads_have_embeds_list(self):
        for payload in [
            alerts.build_open_alert(_pos(), 178.0),
            alerts.build_update_alert(_pos(), 178.0, 187.0, 3.20, 4.85, 5.0),
            alerts.build_close_alert(_pos(), 5.10),
        ]:
            assert "embeds" in payload
            assert isinstance(payload["embeds"], list)

    def test_all_embeds_have_color(self):
        for payload in [
            alerts.build_open_alert(_pos(), 178.0),
            alerts.build_update_alert(_pos(), 178.0, 187.0, 3.20, 4.85, 5.0),
            alerts.build_close_alert(_pos(), 5.10),
        ]:
            assert "color" in payload["embeds"][0]

    def test_colors_are_distinct(self):
        open_color   = _color(alerts.build_open_alert(_pos(), 178.0))
        update_color = _color(alerts.build_update_alert(_pos(), 178.0, 187.0, 3.20, 4.85, 5.0))
        close_color  = _color(alerts.build_close_alert(_pos(), 5.10))
        assert len({open_color, update_color, close_color}) == 3
