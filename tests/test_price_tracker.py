"""Tests for price_tracker.py — yfinance is always mocked, no network calls."""

from unittest.mock import MagicMock, patch

import pytest

from database import Position
import price_tracker


# ---------------------------------------------------------------------------
# Helpers
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
        opened_at="2026-04-26T10:00:00",
        status="open",
    )
    defaults.update(overrides)
    return Position(**defaults)


def _mock_ticker(last_price):
    """Return a mock yf.Ticker whose fast_info.last_price equals last_price."""
    mock = MagicMock()
    mock.fast_info.last_price = last_price
    return mock


# ---------------------------------------------------------------------------
# compute_pct_change
# ---------------------------------------------------------------------------

class TestComputePctChange:
    def test_positive_move_five_percent(self):
        assert price_tracker.compute_pct_change(100, 105) == pytest.approx(5.0)

    def test_negative_move_five_percent(self):
        assert price_tracker.compute_pct_change(100, 95) == pytest.approx(-5.0)

    def test_no_change_returns_zero(self):
        assert price_tracker.compute_pct_change(100, 100) == pytest.approx(0.0)

    def test_fractional_change(self):
        assert price_tracker.compute_pct_change(200, 205) == pytest.approx(2.5)

    def test_doubling_is_100_percent(self):
        assert price_tracker.compute_pct_change(10, 20) == pytest.approx(100.0)

    def test_full_loss_is_minus_100_percent(self):
        assert price_tracker.compute_pct_change(10, 0) == pytest.approx(-100.0)

    def test_non_round_prices(self):
        assert price_tracker.compute_pct_change(178.45, 187.20) == pytest.approx(
            (187.20 - 178.45) / 178.45 * 100, rel=1e-5
        )

    def test_zero_old_price_raises_value_error(self):
        with pytest.raises(ValueError, match="non-zero"):
            price_tracker.compute_pct_change(0, 100)

    def test_result_is_float(self):
        assert isinstance(price_tracker.compute_pct_change(100, 110), float)

    def test_signed_direction_positive(self):
        assert price_tracker.compute_pct_change(50, 60) > 0

    def test_signed_direction_negative(self):
        assert price_tracker.compute_pct_change(60, 50) < 0


# ---------------------------------------------------------------------------
# get_underlying_price
# ---------------------------------------------------------------------------

class TestGetUnderlyingPrice:
    def test_returns_price_from_fast_info(self):
        with patch("price_tracker.yf.Ticker", return_value=_mock_ticker(178.45)):
            result = price_tracker.get_underlying_price("AAPL")
        assert result == pytest.approx(178.45)

    def test_calls_ticker_with_correct_symbol(self):
        with patch("price_tracker.yf.Ticker", return_value=_mock_ticker(100.0)) as mock_cls:
            price_tracker.get_underlying_price("TSLA")
        mock_cls.assert_called_once_with("TSLA")

    def test_return_type_is_float(self):
        with patch("price_tracker.yf.Ticker", return_value=_mock_ticker(178)):
            result = price_tracker.get_underlying_price("AAPL")
        assert isinstance(result, float)

    def test_raises_value_error_when_price_is_none(self):
        with patch("price_tracker.yf.Ticker", return_value=_mock_ticker(None)):
            with pytest.raises(ValueError, match="AAPL"):
                price_tracker.get_underlying_price("AAPL")

    def test_ticker_name_in_none_price_error(self):
        with patch("price_tracker.yf.Ticker", return_value=_mock_ticker(None)):
            with pytest.raises(ValueError) as exc_info:
                price_tracker.get_underlying_price("NVDA")
        assert "NVDA" in str(exc_info.value)

    def test_raises_runtime_error_on_yfinance_exception(self):
        with patch("price_tracker.yf.Ticker", side_effect=Exception("network down")):
            with pytest.raises(RuntimeError, match="TSLA"):
                price_tracker.get_underlying_price("TSLA")

    def test_ticker_name_in_exception_error(self):
        with patch("price_tracker.yf.Ticker", side_effect=Exception("timeout")):
            with pytest.raises(RuntimeError) as exc_info:
                price_tracker.get_underlying_price("MSFT")
        assert "MSFT" in str(exc_info.value)

    def test_original_exception_is_chained(self):
        """The yfinance exception is attached as __cause__ on the RuntimeError."""
        original = ConnectionError("DNS failure")
        with patch("price_tracker.yf.Ticker", side_effect=original):
            with pytest.raises(RuntimeError) as exc_info:
                price_tracker.get_underlying_price("SPY")
        assert exc_info.value.__cause__ is original


# ---------------------------------------------------------------------------
# estimate_option_value
# ---------------------------------------------------------------------------

class TestEstimateOptionValue:
    # --- call direction ---

    def test_call_increases_on_positive_underlying_move(self):
        pos = _pos(option_type="call", avg_cost=3.20)
        result = price_tracker.estimate_option_value(pos, 100.0, 105.0)
        assert result > pos.avg_cost

    def test_call_decreases_on_negative_underlying_move(self):
        pos = _pos(option_type="call", avg_cost=3.20)
        result = price_tracker.estimate_option_value(pos, 100.0, 95.0)
        assert result < pos.avg_cost

    def test_call_exact_five_percent_gain(self):
        """+5 % underlying → avg_cost * 1.05 for a call."""
        pos = _pos(option_type="call", avg_cost=4.00)
        assert price_tracker.estimate_option_value(pos, 100.0, 105.0) == pytest.approx(4.20)

    def test_call_exact_five_percent_loss(self):
        """-5 % underlying → avg_cost * 0.95 for a call."""
        pos = _pos(option_type="call", avg_cost=4.00)
        assert price_tracker.estimate_option_value(pos, 100.0, 95.0) == pytest.approx(3.80)

    # --- put direction ---

    def test_put_increases_on_negative_underlying_move(self):
        pos = _pos(option_type="put", avg_cost=3.20)
        result = price_tracker.estimate_option_value(pos, 100.0, 95.0)
        assert result > pos.avg_cost

    def test_put_decreases_on_positive_underlying_move(self):
        pos = _pos(option_type="put", avg_cost=3.20)
        result = price_tracker.estimate_option_value(pos, 100.0, 105.0)
        assert result < pos.avg_cost

    def test_put_exact_five_percent_drop(self):
        """-5 % underlying → avg_cost * 1.05 for a put."""
        pos = _pos(option_type="put", avg_cost=4.00)
        assert price_tracker.estimate_option_value(pos, 100.0, 95.0) == pytest.approx(4.20)

    def test_put_exact_five_percent_rise(self):
        """+5 % underlying → avg_cost * 0.95 for a put."""
        pos = _pos(option_type="put", avg_cost=4.00)
        assert price_tracker.estimate_option_value(pos, 100.0, 105.0) == pytest.approx(3.80)

    # --- edge cases ---

    def test_no_price_change_returns_avg_cost(self):
        pos = _pos(option_type="call", avg_cost=3.20)
        assert price_tracker.estimate_option_value(pos, 100.0, 100.0) == pytest.approx(3.20)

    def test_value_clamped_to_zero_not_negative(self):
        """A -100 % underlying move produces 0.0, not a negative option value."""
        pos = _pos(option_type="call", avg_cost=1.00)
        result = price_tracker.estimate_option_value(pos, 100.0, 0.0)  # -100 % move
        assert result == 0.0

    def test_put_clamped_to_zero_on_extreme_rise(self):
        """A 200 % underlying rise should not produce a negative put value."""
        pos = _pos(option_type="put", avg_cost=1.00)
        result = price_tracker.estimate_option_value(pos, 100.0, 300.0)  # +200 %
        assert result == 0.0

    def test_result_is_float(self):
        pos = _pos(option_type="call", avg_cost=3.0)
        result = price_tracker.estimate_option_value(pos, 100.0, 110.0)
        assert isinstance(result, float)

    def test_raises_on_zero_old_underlying(self):
        pos = _pos(option_type="call")
        with pytest.raises(ValueError, match="non-zero"):
            price_tracker.estimate_option_value(pos, 0.0, 100.0)

    def test_call_and_put_are_symmetric_for_equal_moves(self):
        """A +X% move on a call and a -X% move on a put should yield the same estimate."""
        call_pos = _pos(option_type="call", avg_cost=5.0)
        put_pos = _pos(option_type="put", avg_cost=5.0)
        call_result = price_tracker.estimate_option_value(call_pos, 100.0, 110.0)
        put_result = price_tracker.estimate_option_value(put_pos, 100.0, 90.0)
        assert call_result == pytest.approx(put_result)
