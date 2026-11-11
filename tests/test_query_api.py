"""Exercise the opt-in raw planner capture through the CLI."""

import runpy
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

QUERY_API = Path(__file__).resolve().parents[1] / "script" / "query-api"


def run_cli(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    """Run the script through its command-line entry point."""
    monkeypatch.setattr(sys, "argv", [str(QUERY_API), *args])
    monkeypatch.setattr(sys, "path", sys.path.copy())
    with pytest.raises(SystemExit) as raised:
        runpy.run_path(str(QUERY_API), run_name="__main__")
    return raised.value.code


@pytest.mark.parametrize("http_status", [200, 502])
def test_raw_plan_preserves_unmodeled_response(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    http_status: int,
) -> None:
    """Capture the sent request and the raw planner response without validation."""
    raw = '{"itineraries":[{"transfers":0,"legs":[{"sameVehicleContinuation":true}]}]}'
    response = MagicMock(status=http_status)
    response.text = AsyncMock(return_value=raw)
    session = MagicMock()
    session.post.return_value.__aenter__ = AsyncMock(return_value=response)
    monkeypatch.setattr(
        aiohttp,
        "ClientSession",
        MagicMock(return_value=MagicMock(__aenter__=AsyncMock(return_value=session))),
    )
    exit_status = run_cli(
        monkeypatch,
        "--raw-plan",
        "2026-11-11T13:00",
        "ST:place_censta",
        "ST:place_kprsta",
    )
    assert exit_status == (0 if http_status == 200 else 1)

    call = session.post.call_args
    assert call.args == ("https://jp.translink.com.au/api/plan?id=1355966139",)
    assert session.get.call_count == 0
    captured, url, request_id, body, status, payload = (
        capsys.readouterr().out.splitlines()
    )
    assert datetime.fromisoformat(
        captured.removeprefix("# Captured UTC: ")
    ).utcoffset() == timedelta(0)
    assert url == f"# Request URL: {call.args[0]}"
    assert request_id == "# Request ID: 1355966139"
    assert body == f"# Request body: {call.kwargs['data']}"
    assert status == f"# HTTP status: {http_status}"
    assert payload == raw


@pytest.mark.parametrize(
    ("target", "start_id", "message"),
    [
        ("2026-11-11T13:00", "unverified-place", "needs public station IDs"),
        ("2026-02-31T13:00", "ST:place_censta", "needs a Brisbane date and time"),
    ],
)
def test_raw_plan_rejects_invalid_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    target: str,
    start_id: str,
    message: str,
) -> None:
    """Reject an unsupported ID or invalid date without contacting the planner."""
    session_factory = MagicMock()
    monkeypatch.setattr(aiohttp, "ClientSession", session_factory)

    assert run_cli(monkeypatch, "--raw-plan", target, start_id, "ST:place_kprsta") == 2
    assert message in capsys.readouterr().err
    session_factory.assert_not_called()
