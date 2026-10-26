"""Bounded transport and session ownership for optional trip-page enrichment."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.translink.api import client as client_module
from custom_components.translink.client import (
    TranslinkClient,
    TranslinkConnectionError,
    TranslinkResponseError,
)

TRIP_ID = "s_T_RPSP_8_20261026_39766414"
HTML = (Path(__file__).parent / "fixtures/trip_page/success.html").read_bytes()


class Response:
    def __init__(
        self, body=HTML, status=200, content_type="text/html", content_length=None
    ):
        self.body, self.status, self.content_type, self.content_length = (
            body,
            status,
            content_type,
            content_length,
        )
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def iter_chunked(self, size):
        for start in range(0, len(self.body), size):
            yield self.body[start : start + size]


def _client(response=None):
    session = MagicMock()
    session.closed = False
    session.get.return_value = response or Response()
    return TranslinkClient(session=session), session


async def test_authentic_transport_and_session_ownership():
    client, session = _client()
    result = await client.async_get_trip_timetable(TRIP_ID)
    assert len(result.departures) == 36
    assert session.get.call_args.kwargs["allow_redirects"] is False
    assert session.get.call_args.kwargs["headers"] == {"Accept": "text/html"}
    await client.close()
    session.close.assert_not_called()
    client, session = _client(Response(b"<html>No timetable</html>"))
    assert await client.async_get_trip_timetable("valid-id") is None
    client, session = _client()
    session.get.return_value = Response(b"<html>No timetable</html>")
    await client.async_get_trip_timetable("a /?#%")
    url = session.get.call_args.args[0]
    assert url.raw_path.endswith("a%20%2F%3F%23%25")


@pytest.mark.parametrize("trip_id", ["", "x" * 129, "bad\nID"])
async def test_invalid_id_has_no_request(trip_id):
    client, session = _client()
    with pytest.raises(TranslinkResponseError):
        await client.async_get_trip_timetable(trip_id)
    session.get.assert_not_called()


@pytest.mark.parametrize(
    "response",
    [
        Response(status=500),
        Response(status=302),
        Response(content_type="application/json"),
        Response(content_length=2**30),
        Response(body=b"\xff"),
    ],
)
async def test_rejected_response(response):
    client, _ = _client(response)
    with pytest.raises(TranslinkResponseError):
        await client.async_get_trip_timetable(TRIP_ID)


async def test_streamed_body_bound(monkeypatch):
    monkeypatch.setattr(client_module, "TRIP_PAGE_MAX_BYTES", 10)
    client, _ = _client(Response(b"x" * 11))
    with pytest.raises(TranslinkResponseError):
        await client.async_get_trip_timetable(TRIP_ID)


@pytest.mark.parametrize("error", [TimeoutError(), aiohttp.ClientConnectionError()])
async def test_network_error_conversion(error):
    client, session = _client()
    session.get.side_effect = error
    with pytest.raises(TranslinkConnectionError):
        await client.async_get_trip_timetable(TRIP_ID)


async def test_concurrency_bound():
    active = 0
    peak = 0

    class SlowResponse(Response):
        async def __aenter__(self):
            nonlocal active, peak
            active += 1
            peak = max(active, peak)
            await asyncio.sleep(0.01)
            return self

        async def __aexit__(self, *args):
            nonlocal active
            active -= 1

    client, session = _client()
    session.get.side_effect = lambda *a, **kw: SlowResponse()
    await asyncio.gather(*(client.async_get_trip_timetable(TRIP_ID) for _ in range(5)))
    assert peak == 2
    assert active == 0
