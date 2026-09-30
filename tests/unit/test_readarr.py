"""Tests for the Readarr search/add integration (mocked — no live Readarr instance)."""

from unittest.mock import AsyncMock, patch

import pytest

from brainycat.config import settings
from brainycat.experimental.readarr import add_to_readarr, search_readarr


@pytest.mark.asyncio
async def test_search_without_config_returns_clear_error() -> None:
    with patch.object(settings, "readarr_url", ""), patch.object(settings, "readarr_api_key", ""):
        result = await search_readarr("dune")
    assert "not configured" in result["error"]


@pytest.mark.asyncio
async def test_search_parses_nested_book_shape() -> None:
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json = lambda: [
        {"book": {"title": "Dune", "releaseDate": "1965-08-01", "overview": "..."}, "author": {"authorName": "Frank Herbert"}}
    ]
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.object(settings, "readarr_url", "http://readarr:8787"),
        patch.object(settings, "readarr_api_key", "key123"),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        result = await search_readarr("dune")

    assert result["results"][0]["title"] == "Dune"
    assert result["results"][0]["author"] == "Frank Herbert"
    assert result["results"][0]["year"] == "1965"
    assert result["results"][0]["book"]["title"] == "Dune"


@pytest.mark.asyncio
async def test_add_without_config_returns_clear_error() -> None:
    with patch.object(settings, "readarr_url", ""), patch.object(settings, "readarr_api_key", ""):
        result = await add_to_readarr({"title": "Dune"})
    assert "not configured" in result["error"]


@pytest.mark.asyncio
async def test_add_auto_detects_root_folder_and_quality_profile() -> None:
    def make_resp(status, body):
        r = AsyncMock()
        r.status_code = status
        r.json = lambda: body
        r.text = str(body)
        return r

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(
        side_effect=[
            make_resp(200, [{"path": "/data/incoming"}]),
            make_resp(200, [{"id": 1, "name": "Standard"}]),
        ]
    )
    mock_client.post = AsyncMock(return_value=make_resp(201, {}))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.object(settings, "readarr_url", "http://readarr:8787"),
        patch.object(settings, "readarr_api_key", "key123"),
        patch.object(settings, "readarr_root_folder", ""),
        patch.object(settings, "readarr_quality_profile_id", ""),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        result = await add_to_readarr({"title": "Dune"})

    assert result["ok"] is True
    posted_payload = mock_client.post.call_args.kwargs["json"]
    assert posted_payload["rootFolderPath"] == "/data/incoming"
    assert posted_payload["qualityProfileId"] == 1
    assert posted_payload["monitored"] is True
    assert posted_payload["addOptions"] == {"searchForNewBook": True}
