"""Tests for notifier.py — httpx is always mocked, no real network calls."""

from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

import notifier

WEBHOOK_URL = "https://discord.com/api/webhooks/123/test-token"
SAMPLE_EMBED = {"embeds": [{"title": "Test Alert", "color": 65280}]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_http_context(post_responses):
    """Return a patched httpx.AsyncClient context manager.

    post_responses: list of MagicMock response objects returned in order.
    """
    mock_client = AsyncMock()
    if len(post_responses) == 1:
        mock_client.post = AsyncMock(return_value=post_responses[0])
    else:
        mock_client.post = AsyncMock(side_effect=post_responses)

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_cm, mock_client


def _resp(status: int, is_success: bool | None = None) -> MagicMock:
    """Build a mock httpx response."""
    r = MagicMock()
    r.status_code = status
    r.is_success = (status < 400) if is_success is None else is_success
    return r


# ---------------------------------------------------------------------------
# send_discord — happy path
# ---------------------------------------------------------------------------

class TestSendDiscordSuccess:
    async def test_posts_to_correct_url(self):
        mock_cm, mock_client = _mock_http_context([_resp(204)])
        with patch("notifier.httpx.AsyncClient", return_value=mock_cm):
            await notifier.send_discord(SAMPLE_EMBED, WEBHOOK_URL)
        mock_client.post.assert_called_once_with(WEBHOOK_URL, json=SAMPLE_EMBED)

    async def test_posts_correct_payload(self):
        mock_cm, mock_client = _mock_http_context([_resp(200)])
        with patch("notifier.httpx.AsyncClient", return_value=mock_cm):
            await notifier.send_discord(SAMPLE_EMBED, WEBHOOK_URL)
        _, kwargs = mock_client.post.call_args
        assert kwargs["json"] == SAMPLE_EMBED

    async def test_does_not_raise_on_200(self):
        mock_cm, _ = _mock_http_context([_resp(200)])
        with patch("notifier.httpx.AsyncClient", return_value=mock_cm):
            await notifier.send_discord(SAMPLE_EMBED, WEBHOOK_URL)

    async def test_does_not_raise_on_204(self):
        mock_cm, _ = _mock_http_context([_resp(204)])
        with patch("notifier.httpx.AsyncClient", return_value=mock_cm):
            await notifier.send_discord(SAMPLE_EMBED, WEBHOOK_URL)

    async def test_post_called_exactly_once_on_success(self):
        mock_cm, mock_client = _mock_http_context([_resp(204)])
        with patch("notifier.httpx.AsyncClient", return_value=mock_cm):
            await notifier.send_discord(SAMPLE_EMBED, WEBHOOK_URL)
        assert mock_client.post.call_count == 1


# ---------------------------------------------------------------------------
# send_discord — error handling and retry
# ---------------------------------------------------------------------------

class TestSendDiscordErrors:
    async def test_does_not_raise_on_http_500(self):
        """HTTP 500 on both attempts must not propagate an exception."""
        mock_cm, _ = _mock_http_context([_resp(500), _resp(500)])
        with patch("notifier.httpx.AsyncClient", return_value=mock_cm):
            await notifier.send_discord(SAMPLE_EMBED, WEBHOOK_URL)  # must not raise

    async def test_retries_once_on_500(self):
        """The POST is attempted twice when the first response is 5xx."""
        mock_cm, mock_client = _mock_http_context([_resp(500), _resp(500)])
        with patch("notifier.httpx.AsyncClient", return_value=mock_cm):
            await notifier.send_discord(SAMPLE_EMBED, WEBHOOK_URL)
        assert mock_client.post.call_count == 2

    async def test_succeeds_after_500_retry(self):
        """A 500 followed by a 200 resolves without error, only one retry used."""
        mock_cm, mock_client = _mock_http_context([_resp(500), _resp(200)])
        with patch("notifier.httpx.AsyncClient", return_value=mock_cm):
            await notifier.send_discord(SAMPLE_EMBED, WEBHOOK_URL)
        assert mock_client.post.call_count == 2

    async def test_does_not_raise_on_http_400(self):
        """Client errors (4xx) are logged and swallowed — no exception."""
        mock_cm, _ = _mock_http_context([_resp(400, is_success=False)])
        with patch("notifier.httpx.AsyncClient", return_value=mock_cm):
            await notifier.send_discord(SAMPLE_EMBED, WEBHOOK_URL)

    async def test_no_retry_on_400(self):
        """4xx errors are not retried (only 5xx triggers retry)."""
        mock_cm, mock_client = _mock_http_context([_resp(400, is_success=False)])
        with patch("notifier.httpx.AsyncClient", return_value=mock_cm):
            await notifier.send_discord(SAMPLE_EMBED, WEBHOOK_URL)
        assert mock_client.post.call_count == 1

    async def test_does_not_raise_on_http_error_exception(self):
        """An httpx.HTTPError is caught, logged, and not re-raised."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=notifier.httpx.HTTPError("connection refused")
        )
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        with patch("notifier.httpx.AsyncClient", return_value=mock_cm):
            await notifier.send_discord(SAMPLE_EMBED, WEBHOOK_URL)  # must not raise

    async def test_retries_once_on_http_error(self):
        """An httpx.HTTPError on the first attempt triggers one retry."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=notifier.httpx.HTTPError("timeout")
        )
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        with patch("notifier.httpx.AsyncClient", return_value=mock_cm):
            await notifier.send_discord(SAMPLE_EMBED, WEBHOOK_URL)
        assert mock_client.post.call_count == 2


# ---------------------------------------------------------------------------
# send_telegram — stub
# ---------------------------------------------------------------------------

class TestSendTelegram:
    def test_does_not_raise(self):
        notifier.send_telegram("Hello from deltaSimple")

    def test_returns_none(self):
        result = notifier.send_telegram("test")
        assert result is None

    def test_logs_skip_message(self):
        """send_telegram logs a 'Telegram not yet implemented' message via loguru."""
        from loguru import logger
        captured = []
        sink_id = logger.add(lambda msg: captured.append(str(msg)), level="INFO")
        try:
            notifier.send_telegram("test")
        finally:
            logger.remove(sink_id)
        assert any("Telegram" in m for m in captured)

    def test_accepts_any_string(self):
        notifier.send_telegram("")
        notifier.send_telegram("a" * 4096)
