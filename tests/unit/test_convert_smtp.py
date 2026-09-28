"""Tests for the SMTP send path in convert.py (Kindle/device delivery)."""

from email.message import EmailMessage
from unittest.mock import AsyncMock, patch

import pytest

from brainycat import convert
from brainycat.config import settings


def test_smtp_from_prefers_explicit_setting() -> None:
    with patch.object(settings, "smtp_from", "books@ecb.pm"), patch.object(settings, "smtp_user", "user@ecb.pm"):
        assert convert._smtp_from() == "books@ecb.pm"


def test_smtp_from_falls_back_to_user() -> None:
    with patch.object(settings, "smtp_from", ""), patch.object(settings, "smtp_user", "user@ecb.pm"):
        assert convert._smtp_from() == "user@ecb.pm"


def test_smtp_from_falls_back_to_host_default() -> None:
    with patch.object(settings, "smtp_from", ""), patch.object(settings, "smtp_user", ""), patch.object(settings, "smtp_host", "mailserver"):
        assert convert._smtp_from() == "brainycat@mailserver"


@pytest.mark.asyncio
async def test_smtp_send_passes_credentials_when_configured() -> None:
    msg = EmailMessage()
    with (
        patch.object(settings, "smtp_host", "mail.ecb.pm"),
        patch.object(settings, "smtp_port", 587),
        patch.object(settings, "smtp_user", "brainycat@ecb.pm"),
        patch.object(settings, "smtp_password", "secret"),
        patch("brainycat.convert.aiosmtplib.send", new_callable=AsyncMock) as mock_send,
    ):
        await convert._smtp_send(msg)
        mock_send.assert_awaited_once_with(
            msg, hostname="mail.ecb.pm", port=587, use_tls=False, username="brainycat@ecb.pm", password="secret"
        )


@pytest.mark.asyncio
async def test_smtp_send_no_auth_kwargs_when_unconfigured() -> None:
    msg = EmailMessage()
    with (
        patch.object(settings, "smtp_host", "mailserver"),
        patch.object(settings, "smtp_port", 25),
        patch.object(settings, "smtp_user", ""),
        patch("brainycat.convert.aiosmtplib.send", new_callable=AsyncMock) as mock_send,
    ):
        await convert._smtp_send(msg)
        mock_send.assert_awaited_once_with(msg, hostname="mailserver", port=25, use_tls=False)


@pytest.mark.asyncio
async def test_smtp_send_uses_implicit_tls_on_465() -> None:
    msg = EmailMessage()
    with (
        patch.object(settings, "smtp_host", "mail.ecb.pm"),
        patch.object(settings, "smtp_port", 465),
        patch.object(settings, "smtp_user", ""),
        patch("brainycat.convert.aiosmtplib.send", new_callable=AsyncMock) as mock_send,
    ):
        await convert._smtp_send(msg)
        mock_send.assert_awaited_once_with(msg, hostname="mail.ecb.pm", port=465, use_tls=True)


@pytest.mark.asyncio
async def test_resend_send_posts_attachment_and_returns_id() -> None:
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json = lambda: {"id": "abc123"}
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)

    with (
        patch.object(settings, "resend_api_key", "re_test_key"),
        patch.object(settings, "smtp_from", "brainycat@ecb.pm"),
        patch("brainycat.convert.get_client", return_value=mock_client),
    ):
        result = await convert._resend_send(to="a@kindle.com", subject="Title", text="body", filename="book.epub", content=b"hi")

    assert result == {"id": "abc123"}
    args, kwargs = mock_client.post.call_args
    assert args[0] == "https://api.resend.com/emails"
    assert kwargs["headers"]["Authorization"] == "Bearer re_test_key"
    assert kwargs["json"]["from"] == "brainycat@ecb.pm"
    assert kwargs["json"]["to"] == ["a@kindle.com"]
    assert kwargs["json"]["attachments"][0]["filename"] == "book.epub"


@pytest.mark.asyncio
async def test_resend_send_surfaces_api_error() -> None:
    mock_resp = AsyncMock()
    mock_resp.status_code = 422
    mock_resp.text = "invalid from address"
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch.object(settings, "resend_api_key", "re_test_key"), patch("brainycat.convert.get_client", return_value=mock_client):
        result = await convert._resend_send(to="a@kindle.com", subject="Title", text="body", filename="book.epub", content=b"hi")

    assert "error" in result
    assert "422" in result["error"]


@pytest.mark.asyncio
async def test_check_send_status_without_key_configured() -> None:
    with patch.object(settings, "resend_api_key", ""):
        result = await convert.check_send_status("abc123")
    assert result == {"error": "Resend is not configured"}
