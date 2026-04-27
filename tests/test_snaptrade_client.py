"""Tests for snaptrade_client.py.

All SnapTrade SDK calls are mocked via `build_client`; no network access occurs.
"""

from unittest.mock import MagicMock, patch, call

import pytest

from database import Position
import snaptrade_client as sc


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_config(*, user_secret: str = "existing-secret") -> MagicMock:
    """Return a mock Config with sensible defaults."""
    cfg = MagicMock()
    cfg.snaptrade_user_id = "cai"
    cfg.snaptrade_user_secret = user_secret
    cfg.snaptrade_consumer_key = "consumer-key"
    cfg.snaptrade_client_id = "client-id"
    return cfg


def _make_raw_holding(
    sym_id: str = "bsym-1",
    ticker: str = "AAPL",
    option_type: str = "CALL",
    strike: float = 180.0,
    expiry: str = "2026-05-16",
    units: int = 1,
    avg_cost: float = 3.20,
) -> dict:
    """Build a minimal dict matching the OptionsPosition SDK response shape."""
    return {
        "symbol": {
            "id": sym_id,
            "option_symbol": {
                "ticker": f"{ticker} {strike}{'C' if option_type=='CALL' else 'P'} {expiry}",
                "option_type": option_type,
                "strike_price": strike,
                "expiration_date": expiry,
                "underlying_symbol": {"symbol": ticker},
            },
        },
        "units": units,
        "average_purchase_price": avg_cost,
    }


def _make_snaptrade_mock(
    accounts: list | None = None,
    holdings_by_account: dict | None = None,
) -> MagicMock:
    """Return a MagicMock SnapTrade client with pre-canned response bodies."""
    if accounts is None:
        accounts = [{"id": "account-1"}]
    if holdings_by_account is None:
        holdings_by_account = {"account-1": [_make_raw_holding()]}

    mock = MagicMock()
    mock.account_information.list_user_accounts.return_value.body = accounts

    def _holdings(user_id=None, user_secret=None, account_id=None):
        resp = MagicMock()
        resp.body = holdings_by_account.get(account_id, [])
        return resp

    mock.options.list_option_holdings.side_effect = _holdings
    return mock


# ---------------------------------------------------------------------------
# register_user
# ---------------------------------------------------------------------------

class TestRegisterUser:
    def test_skips_when_secret_already_set(self):
        """No API call is made when SNAPTRADE_USER_SECRET is already populated."""
        cfg = _make_config(user_secret="already-set")
        with patch.object(sc, "build_client") as mock_build:
            result = sc.register_user(cfg)

        mock_build.assert_not_called()
        assert result == "already-set"

    def test_calls_api_when_secret_missing(self):
        """register_snap_trade_user is called when no secret is configured."""
        cfg = _make_config(user_secret=None)
        mock_snaptrade = MagicMock()
        mock_snaptrade.authentication.register_snap_trade_user.return_value.body = {
            "userId": "cai",
            "userSecret": "brand-new-secret",
        }

        with patch.object(sc, "build_client", return_value=mock_snaptrade), \
             patch.object(sc, "set_key") as mock_set_key:
            result = sc.register_user(cfg, env_path=".env.test")

        mock_snaptrade.authentication.register_snap_trade_user.assert_called_once_with(
            user_id="cai"
        )
        assert result == "brand-new-secret"

    def test_saves_secret_to_env_file(self):
        """Newly issued secret is persisted via set_key to the given path."""
        cfg = _make_config(user_secret=None)
        mock_snaptrade = MagicMock()
        mock_snaptrade.authentication.register_snap_trade_user.return_value.body = {
            "userId": "cai",
            "userSecret": "fresh-secret",
        }

        with patch.object(sc, "build_client", return_value=mock_snaptrade), \
             patch.object(sc, "set_key") as mock_set_key:
            sc.register_user(cfg, env_path="/tmp/test.env")

        mock_set_key.assert_called_once_with(
            "/tmp/test.env", "SNAPTRADE_USER_SECRET", "fresh-secret"
        )

    def test_re_raises_api_exception(self):
        """Errors from the registration API propagate to the caller."""
        cfg = _make_config(user_secret=None)
        mock_snaptrade = MagicMock()
        mock_snaptrade.authentication.register_snap_trade_user.side_effect = (
            RuntimeError("network error")
        )

        with patch.object(sc, "build_client", return_value=mock_snaptrade), \
             pytest.raises(RuntimeError, match="network error"):
            sc.register_user(cfg)


# ---------------------------------------------------------------------------
# get_options_positions
# ---------------------------------------------------------------------------

class TestGetOptionsPositions:
    def test_raises_when_user_secret_missing(self):
        """ValueError is raised immediately when SNAPTRADE_USER_SECRET is unset."""
        cfg = _make_config(user_secret=None)
        with pytest.raises(ValueError, match="SNAPTRADE_USER_SECRET"):
            sc.get_options_positions(cfg)

    def test_returns_normalized_position(self):
        """Happy path: one account, one holding → one Position."""
        cfg = _make_config()
        mock_st = _make_snaptrade_mock()

        with patch.object(sc, "build_client", return_value=mock_st):
            result = sc.get_options_positions(cfg)

        assert len(result) == 1
        pos = result[0]
        assert isinstance(pos, Position)
        assert pos.id == "bsym-1"
        assert pos.ticker == "AAPL"
        assert pos.strike == 180.0
        assert pos.expiry == "2026-05-16"
        assert pos.quantity == 1
        assert pos.avg_cost == pytest.approx(3.20)
        assert pos.status == "open"

    def test_option_type_normalised_to_lowercase(self):
        """'CALL' / 'PUT' from the SDK are lowercased in the Position."""
        cfg = _make_config()
        call_holding = _make_raw_holding(option_type="CALL")
        put_holding = _make_raw_holding(sym_id="bsym-2", ticker="TSLA", option_type="PUT")
        mock_st = _make_snaptrade_mock(
            holdings_by_account={"account-1": [call_holding, put_holding]}
        )

        with patch.object(sc, "build_client", return_value=mock_st):
            result = sc.get_options_positions(cfg)

        types = {p.option_type for p in result}
        assert types == {"call", "put"}

    def test_aggregates_across_multiple_accounts(self):
        """Positions from every account are collected into a single list."""
        cfg = _make_config()
        mock_st = _make_snaptrade_mock(
            accounts=[{"id": "acc-A"}, {"id": "acc-B"}],
            holdings_by_account={
                "acc-A": [_make_raw_holding(sym_id="s1", ticker="AAPL")],
                "acc-B": [_make_raw_holding(sym_id="s2", ticker="TSLA")],
            },
        )

        with patch.object(sc, "build_client", return_value=mock_st):
            result = sc.get_options_positions(cfg)

        assert len(result) == 2
        tickers = {p.ticker for p in result}
        assert tickers == {"AAPL", "TSLA"}

    def test_filters_non_option_holdings(self):
        """Holdings without option_symbol are silently excluded."""
        cfg = _make_config()
        non_option = {"symbol": {"id": "stock-sym"}, "units": 10, "average_purchase_price": 5.0}
        option = _make_raw_holding()
        mock_st = _make_snaptrade_mock(
            holdings_by_account={"account-1": [non_option, option]}
        )

        with patch.object(sc, "build_client", return_value=mock_st):
            result = sc.get_options_positions(cfg)

        assert len(result) == 1
        assert result[0].ticker == "AAPL"

    def test_skips_malformed_holding_and_continues(self):
        """A ValueError from _normalize_position is logged and skipped; others process."""
        cfg = _make_config()
        malformed = {"symbol": {}}  # has symbol but no id, no option_symbol
        good = _make_raw_holding(sym_id="good-sym")
        mock_st = _make_snaptrade_mock(
            holdings_by_account={"account-1": [malformed, good]}
        )

        with patch.object(sc, "build_client", return_value=mock_st):
            result = sc.get_options_positions(cfg)

        assert len(result) == 1
        assert result[0].id == "good-sym"

    def test_empty_accounts_returns_empty_list(self):
        """No accounts → empty result list, no exceptions."""
        cfg = _make_config()
        mock_st = _make_snaptrade_mock(accounts=[], holdings_by_account={})

        with patch.object(sc, "build_client", return_value=mock_st):
            result = sc.get_options_positions(cfg)

        assert result == []

    def test_empty_holdings_returns_empty_list(self):
        """Account with no holdings → empty result list."""
        cfg = _make_config()
        mock_st = _make_snaptrade_mock(holdings_by_account={"account-1": []})

        with patch.object(sc, "build_client", return_value=mock_st):
            result = sc.get_options_positions(cfg)

        assert result == []

    def test_re_raises_accounts_fetch_failure(self):
        """Exceptions from list_user_accounts propagate to the caller."""
        cfg = _make_config()
        mock_st = MagicMock()
        mock_st.account_information.list_user_accounts.side_effect = (
            ConnectionError("API down")
        )

        with patch.object(sc, "build_client", return_value=mock_st), \
             pytest.raises(ConnectionError, match="API down"):
            sc.get_options_positions(cfg)

    def test_continues_after_single_account_holdings_failure(self):
        """A failed holdings fetch for one account does not abort the others."""
        cfg = _make_config()
        mock_st = MagicMock()
        mock_st.account_information.list_user_accounts.return_value.body = [
            {"id": "acc-bad"},
            {"id": "acc-good"},
        ]

        def _holdings(user_id=None, user_secret=None, account_id=None):
            if account_id == "acc-bad":
                raise RuntimeError("brokerage timeout")
            resp = MagicMock()
            resp.body = [_make_raw_holding(sym_id="g1")]
            return resp

        mock_st.options.list_option_holdings.side_effect = _holdings

        with patch.object(sc, "build_client", return_value=mock_st):
            result = sc.get_options_positions(cfg)

        assert len(result) == 1
        assert result[0].id == "g1"

    def test_avg_cost_none_defaults_to_zero(self):
        """average_purchase_price=None in response yields avg_cost=0.0."""
        cfg = _make_config()
        holding = _make_raw_holding()
        holding["average_purchase_price"] = None
        mock_st = _make_snaptrade_mock(holdings_by_account={"account-1": [holding]})

        with patch.object(sc, "build_client", return_value=mock_st):
            result = sc.get_options_positions(cfg)

        assert result[0].avg_cost == 0.0


# ---------------------------------------------------------------------------
# _normalize_position
# ---------------------------------------------------------------------------

class TestNormalizePosition:
    def test_valid_call_option(self):
        """Full valid CALL holding normalizes without error."""
        pos = sc._normalize_position(_make_raw_holding(option_type="CALL"))
        assert pos is not None
        assert pos.option_type == "call"
        assert pos.ticker == "AAPL"
        assert pos.strike == pytest.approx(180.0)

    def test_valid_put_option(self):
        """Full valid PUT holding normalizes without error."""
        pos = sc._normalize_position(
            _make_raw_holding(ticker="TSLA", option_type="PUT", strike=250.0)
        )
        assert pos is not None
        assert pos.option_type == "put"
        assert pos.ticker == "TSLA"

    def test_returns_none_for_non_option(self):
        """Holding with no option_symbol returns None (filtered, not an error)."""
        raw = {"symbol": {"id": "stock-1"}, "units": 5, "average_purchase_price": 10.0}
        assert sc._normalize_position(raw) is None

    def test_raises_on_missing_symbol_key(self):
        """Top-level 'symbol' key missing raises ValueError."""
        with pytest.raises(ValueError, match="missing 'symbol'"):
            sc._normalize_position({"units": 1})

    def test_raises_on_missing_option_type(self):
        """option_symbol missing option_type raises ValueError with field name."""
        raw = _make_raw_holding()
        del raw["symbol"]["option_symbol"]["option_type"]
        with pytest.raises(ValueError, match="option_type"):
            sc._normalize_position(raw)

    def test_raises_on_missing_strike_price(self):
        """option_symbol missing strike_price raises ValueError."""
        raw = _make_raw_holding()
        del raw["symbol"]["option_symbol"]["strike_price"]
        with pytest.raises(ValueError, match="strike_price"):
            sc._normalize_position(raw)

    def test_raises_on_missing_expiration_date(self):
        """option_symbol missing expiration_date raises ValueError."""
        raw = _make_raw_holding()
        del raw["symbol"]["option_symbol"]["expiration_date"]
        with pytest.raises(ValueError, match="expiration_date"):
            sc._normalize_position(raw)

    def test_raises_on_missing_underlying_symbol(self):
        """option_symbol missing underlying_symbol raises ValueError."""
        raw = _make_raw_holding()
        del raw["symbol"]["option_symbol"]["underlying_symbol"]
        with pytest.raises(ValueError, match="underlying_symbol"):
            sc._normalize_position(raw)

    def test_raises_on_missing_underlying_ticker(self):
        """underlying_symbol missing 'symbol' (the ticker) raises ValueError."""
        raw = _make_raw_holding()
        raw["symbol"]["option_symbol"]["underlying_symbol"] = {}
        with pytest.raises(ValueError, match="'symbol'"):
            sc._normalize_position(raw)

    def test_raises_on_missing_symbol_id(self):
        """symbol missing 'id' raises ValueError."""
        raw = _make_raw_holding()
        del raw["symbol"]["id"]
        with pytest.raises(ValueError, match="'id'"):
            sc._normalize_position(raw)

    def test_returns_position_dataclass(self):
        """Return type is always a Position instance."""
        pos = sc._normalize_position(_make_raw_holding())
        assert isinstance(pos, Position)

    def test_status_is_always_open(self):
        """Normalized positions always have status='open'."""
        pos = sc._normalize_position(_make_raw_holding())
        assert pos.status == "open"

    def test_all_required_fields_populated(self):
        """Every Position field is set and has the expected type."""
        pos = sc._normalize_position(
            _make_raw_holding(
                sym_id="sym-99",
                ticker="NVDA",
                option_type="PUT",
                strike=900.0,
                expiry="2026-06-20",
                units=3,
                avg_cost=12.50,
            )
        )
        assert pos.id == "sym-99"
        assert pos.ticker == "NVDA"
        assert pos.option_type == "put"
        assert pos.strike == pytest.approx(900.0)
        assert pos.expiry == "2026-06-20"
        assert pos.quantity == 3
        assert pos.avg_cost == pytest.approx(12.50)
        assert isinstance(pos.opened_at, str) and len(pos.opened_at) > 0
