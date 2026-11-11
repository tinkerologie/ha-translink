"""Test the HA Next workflow's release selection and PyPI classification."""

from __future__ import annotations

import io
import json
import sys
from http import HTTPStatus
from pathlib import Path
from urllib.error import HTTPError

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/ha-next.yml"
CORE_VERSION = "2026.11.1"


def _step_script(step_id: str) -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return next(
        step["run"]
        for step in workflow["jobs"]["ha-next"]["steps"]
        if step.get("id") == step_id
    )


def test_resolve_chooses_latest_installable_release(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ignore newer yanked and Python-incompatible releases."""
    releases = {
        "2026.11.0": [{"requires_python": ">=3.14.2", "yanked": False}],
        CORE_VERSION: [{"requires_python": ">=3.14.2", "yanked": False}],
        "2026.11.2": [{"requires_python": ">=3.14.2", "yanked": True}],
        "2026.12.0": [{"requires_python": ">=3.15", "yanked": False}],
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"releases": releases})))
    command = _step_script("resolve").split("python -c '", 1)[1].split("\n'", 1)[0]

    exec(compile(command, str(WORKFLOW), "exec"), {})  # noqa: S102 - run checked-in workflow code with fixture input

    assert capsys.readouterr().out.strip() == CORE_VERSION


@pytest.fixture
def pypi_releases() -> dict[str, dict]:
    """Create Home Assistant and plugin metadata with compatible release files."""
    return {
        "homeassistant": {
            "info": {"requires_dist": ["aiohttp"]},
            "urls": [{"requires_python": ">=3.14.2", "yanked": False}],
        },
        "pytest-homeassistant": {
            "info": {"requires_dist": [f"homeassistant=={CORE_VERSION}"]},
            "urls": [{"requires_python": ">=3.14.2", "yanked": False}],
        },
    }


@pytest.fixture
def classify_release(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pypi_releases: dict[str, dict]
):
    """Run the workflow classifier with local PyPI responses."""
    output = tmp_path / "output"
    monkeypatch.setenv("HA_VERSION", CORE_VERSION)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    def open_release(url: str, *, timeout: int) -> io.StringIO:
        package = url.split("/")[-3]
        response = pypi_releases.get(package)
        if response is None:
            raise HTTPError(url, HTTPStatus.NOT_FOUND, "not found", {}, None)
        return io.StringIO(json.dumps(response))

    monkeypatch.setattr("urllib.request.urlopen", open_release)
    command = _step_script("classify").split("<<'PYTHON'\n", 1)[1]
    command = command.removesuffix("PYTHON\n")

    def run() -> dict[str, str]:
        exec(compile(command, str(WORKFLOW), "exec"), {})  # noqa: S102 - run checked-in workflow code with fixture input
        return dict(line.split("=", 1) for line in output.read_text().splitlines())

    return run


def test_classify_matching_release(classify_release) -> None:
    """Install the full test harness when both release files are compatible."""
    assert classify_release() == {
        "harness": "supported",
        "reason": "matching official plugin release",
        "core_available": "true",
    }


@pytest.mark.parametrize(
    ("package", "core_available", "reason"),
    [
        ("homeassistant", "false", "Home Assistant release not published"),
        ("pytest-homeassistant", "true", "no matching pytest-homeassistant release"),
    ],
)
def test_classify_unpublished_release(
    classify_release, pypi_releases, package: str, core_available: str, reason: str
) -> None:
    """Keep an unavailable Core distinct from an unavailable test harness."""
    del pypi_releases[package]
    assert classify_release() == {
        "harness": "unsupported",
        "reason": reason,
        "core_available": core_available,
    }


@pytest.mark.parametrize(
    ("package", "core_available"),
    [("homeassistant", "false"), ("pytest-homeassistant", "true")],
)
def test_classify_incompatible_python(
    classify_release, pypi_releases, package: str, core_available: str
) -> None:
    """Recognize a package that requires a newer Python than the runner."""
    pypi_releases[package]["urls"][0]["requires_python"] = ">=3.15"
    result = classify_release()
    assert result["harness"] == "unsupported"
    assert result["core_available"] == core_available
    assert "Python-incompatible" in result["reason"]


def test_classify_rejects_incompatible_home_assistant_pin(
    classify_release, pypi_releases
) -> None:
    """Run only smoke and Hassfest when the plugin pins a different Core."""
    pypi_releases["pytest-homeassistant"]["info"]["requires_dist"] = [
        "homeassistant==2026.11.0"
    ]
    assert classify_release() == {
        "harness": "unsupported",
        "reason": "release does not pin the selected Home Assistant version",
        "core_available": "true",
    }


def test_classify_fails_with_incomplete_metadata(
    classify_release, pypi_releases
) -> None:
    """An incomplete PyPI response does not establish incompatibility."""
    del pypi_releases["homeassistant"]["urls"][0]["requires_python"]
    with pytest.raises(KeyError, match="requires_python"):
        classify_release()
