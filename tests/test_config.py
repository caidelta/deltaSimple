"""Tests for config.py — env var loading, validation, masking, and type parsing."""

import pytest

from config import Config, load_config, _mask


_BASE_ENV = {
    "SNAPTRADE_CLIENT_ID": "client_id_abc123",
    "SNAPTRADE_CONSUMER_KEY": "consumer_key_xyz789",
    "SNAPTRADE_USER_ID": "cai",
    "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/123/abcdef",
    "POLL_INTERVAL_SECONDS": "30",
    "PRICE_ALERT_THRESHOLD_PCT": "5.0",
    "ENV": "development",
}


class TestLoadConfig:
    """Tests for load_config()."""

    def test_loads_all_fields_correctly(self, monkeypatch):
        """All required fields load with correct types and values."""
        for key, val in _BASE_ENV.items():
            monkeypatch.setenv(key, val)

        cfg = load_config()

        assert cfg.snaptrade_client_id == "client_id_abc123"
        assert cfg.snaptrade_consumer_key == "consumer_key_xyz789"
        assert cfg.snaptrade_user_id == "cai"
        assert cfg.discord_webhook_url == "https://discord.com/api/webhooks/123/abcdef"
        assert cfg.poll_interval_seconds == 30
        assert cfg.price_alert_threshold_pct == 5.0
        assert cfg.env == "development"

    def test_optional_telegram_fields_default_to_none(self, monkeypatch):
        """TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID default to None when absent."""
        for key, val in _BASE_ENV.items():
            monkeypatch.setenv(key, val)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

        cfg = load_config()

        assert cfg.telegram_bot_token is None
        assert cfg.telegram_chat_id is None

    def test_optional_telegram_blank_string_becomes_none(self, monkeypatch):
        """Empty string for optional Telegram vars is normalised to None."""
        for key, val in _BASE_ENV.items():
            monkeypatch.setenv(key, val)
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "")

        cfg = load_config()

        assert cfg.telegram_bot_token is None
        assert cfg.telegram_chat_id is None

    def test_optional_snaptrade_user_secret_defaults_to_none(self, monkeypatch):
        """SNAPTRADE_USER_SECRET is optional and defaults to None."""
        for key, val in _BASE_ENV.items():
            monkeypatch.setenv(key, val)
        monkeypatch.delenv("SNAPTRADE_USER_SECRET", raising=False)

        cfg = load_config()

        assert cfg.snaptrade_user_secret is None

    def test_optional_env_defaults_to_production(self, monkeypatch):
        """ENV defaults to 'production' when not set."""
        for key, val in _BASE_ENV.items():
            monkeypatch.setenv(key, val)
        monkeypatch.delenv("ENV", raising=False)

        cfg = load_config()

        assert cfg.env == "production"

    def test_price_alert_threshold_parsed_as_float(self, monkeypatch):
        """PRICE_ALERT_THRESHOLD_PCT is returned as a Python float."""
        for key, val in _BASE_ENV.items():
            monkeypatch.setenv(key, val)
        monkeypatch.setenv("PRICE_ALERT_THRESHOLD_PCT", "2.75")

        cfg = load_config()

        assert isinstance(cfg.price_alert_threshold_pct, float)
        assert cfg.price_alert_threshold_pct == 2.75

    def test_poll_interval_parsed_as_int(self, monkeypatch):
        """POLL_INTERVAL_SECONDS is returned as a Python int."""
        for key, val in _BASE_ENV.items():
            monkeypatch.setenv(key, val)

        cfg = load_config()

        assert isinstance(cfg.poll_interval_seconds, int)
        assert cfg.poll_interval_seconds == 30

    def test_telegram_fields_load_when_provided(self, monkeypatch):
        """Optional Telegram fields are populated when present."""
        for key, val in _BASE_ENV.items():
            monkeypatch.setenv(key, val)
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot_token_123")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100123456")

        cfg = load_config()

        assert cfg.telegram_bot_token == "bot_token_123"
        assert cfg.telegram_chat_id == "-100123456"


class TestMissingRequiredVars:
    """Tests that missing required vars raise ValueError with clear messages."""

    @pytest.mark.parametrize("missing_key", [
        "SNAPTRADE_CLIENT_ID",
        "SNAPTRADE_CONSUMER_KEY",
        "SNAPTRADE_USER_ID",
        "DISCORD_WEBHOOK_URL",
        "POLL_INTERVAL_SECONDS",
        "PRICE_ALERT_THRESHOLD_PCT",
    ])
    def test_missing_required_var_raises_value_error(self, monkeypatch, missing_key):
        """Each required var raises ValueError when absent."""
        for key, val in _BASE_ENV.items():
            monkeypatch.setenv(key, val)
        monkeypatch.delenv(missing_key)

        with pytest.raises(ValueError, match=missing_key):
            load_config()

    def test_error_message_names_the_missing_variable(self, monkeypatch):
        """ValueError message explicitly names the missing variable."""
        for key, val in _BASE_ENV.items():
            monkeypatch.setenv(key, val)
        monkeypatch.delenv("SNAPTRADE_CLIENT_ID")

        with pytest.raises(ValueError) as exc_info:
            load_config()

        assert "SNAPTRADE_CLIENT_ID" in str(exc_info.value)

    def test_invalid_poll_interval_raises_value_error(self, monkeypatch):
        """Non-integer POLL_INTERVAL_SECONDS raises ValueError."""
        for key, val in _BASE_ENV.items():
            monkeypatch.setenv(key, val)
        monkeypatch.setenv("POLL_INTERVAL_SECONDS", "not_a_number")

        with pytest.raises(ValueError, match="POLL_INTERVAL_SECONDS"):
            load_config()

    def test_invalid_threshold_raises_value_error(self, monkeypatch):
        """Non-float PRICE_ALERT_THRESHOLD_PCT raises ValueError."""
        for key, val in _BASE_ENV.items():
            monkeypatch.setenv(key, val)
        monkeypatch.setenv("PRICE_ALERT_THRESHOLD_PCT", "five_percent")

        with pytest.raises(ValueError, match="PRICE_ALERT_THRESHOLD_PCT"):
            load_config()


class TestSecretMasking:
    """Tests for the _mask helper and Config.__str__ masking."""

    def test_mask_shows_only_last_four_chars(self):
        """_mask reveals only the last 4 characters of a secret."""
        assert _mask("abcdefgh") == "****efgh"

    def test_mask_short_value_is_fully_hidden(self):
        """_mask hides values of 4 chars or fewer entirely."""
        assert _mask("ab") == "****"
        assert _mask("abcd") == "****"

    def test_mask_none_returns_none_string(self):
        """_mask returns 'None' for None or empty string."""
        assert _mask(None) == "None"
        assert _mask("") == "None"

    def test_config_str_masks_secret_fields(self, monkeypatch):
        """Config.__str__ does not expose full secret values."""
        for key, val in _BASE_ENV.items():
            monkeypatch.setenv(key, val)

        cfg = load_config()
        output = str(cfg)

        assert "client_id_abc123" not in output
        assert "consumer_key_xyz789" not in output
        assert "abcdef" not in output  # webhook URL fragment

    def test_config_str_shows_non_secret_fields_plainly(self, monkeypatch):
        """Config.__str__ shows non-secret fields in plain text."""
        for key, val in _BASE_ENV.items():
            monkeypatch.setenv(key, val)

        cfg = load_config()
        output = str(cfg)

        assert "cai" in output
        assert "30" in output
        assert "5.0" in output
