"""Exercise the project's warning filters through pytest."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HTTP_WARNING = (
    "Inheritance class HomeAssistantApplication from web.Application is discouraged"
)
BACKOFF_WARNING = (
    "'asyncio.iscoroutinefunction' is deprecated and slated for removal in Python "
    "3.16; use inspect.iscoroutinefunction() instead"
)

CASES = [
    (
        "integration",
        "deprecated API",
        "DeprecationWarning",
        "custom_components.translink",
        "FAILED",
        False,
    ),
    (
        "sensor",
        "pending API removal",
        "PendingDeprecationWarning",
        "custom_components.translink.sensor",
        "FAILED",
        False,
    ),
    (
        "integration_backoff",
        BACKOFF_WARNING,
        "DeprecationWarning",
        "custom_components.translink",
        "FAILED",
        False,
    ),
    (
        "http",
        HTTP_WARNING,
        "DeprecationWarning",
        "homeassistant.components.http.server",
        "PASSED",
        False,
    ),
    (
        "backoff_async",
        BACKOFF_WARNING,
        "DeprecationWarning",
        "backoff._async",
        "PASSED",
        False,
    ),
    (
        "backoff_decorator",
        BACKOFF_WARNING,
        "DeprecationWarning",
        "backoff._decorator",
        "PASSED",
        False,
    ),
    (
        "similar_domain",
        "deprecated API",
        "DeprecationWarning",
        "custom_components.translink_extra",
        "PASSED",
        True,
    ),
    (
        "other_backoff_module",
        BACKOFF_WARNING,
        "DeprecationWarning",
        "backoff._common",
        "PASSED",
        True,
    ),
    (
        "other_application",
        HTTP_WARNING.replace("HomeAssistantApplication", "OtherApplication"),
        "DeprecationWarning",
        "homeassistant.components.http.server",
        "PASSED",
        True,
    ),
    (
        "longer_message",
        f"{HTTP_WARNING} in this context",
        "DeprecationWarning",
        "homeassistant.components.http.server",
        "PASSED",
        True,
    ),
    ("user_warning", "unrelated warning", "UserWarning", "unrelated", "PASSED", True),
]


@pytest.fixture(scope="module")
def child_report(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Run all warning cases in a child using the repository's configuration."""
    child = tmp_path_factory.mktemp("warning_filters") / "test_emit_warning.py"
    source = ["import warnings\n"]
    for case, message, category, module, _, _ in CASES:
        source.append(
            f"def test_{case}():\n"
            f"    warnings.warn_explicit({message!r}, {category}, {case + '.py'!r}, "
            f"1, module={module!r})\n"
        )
    child.write_text("\n".join(source), encoding="utf-8")

    env = os.environ.copy()
    for name in (
        "PYTHONWARNINGS",
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "COVERAGE_PROCESS_START",
        "COVERAGE_FILE",
        "COVERAGE_RCFILE",
        "COV_CORE_SOURCE",
        "COV_CORE_CONFIG",
        "COV_CORE_DATAFILE",
        "COV_CORE_BRANCH",
    ):
        env.pop(name, None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

    result = subprocess.run(  # noqa: S603 - fixed interpreter and generated test module
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(ROOT / "pyproject.toml"),
            "--noconftest",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
            "--color=no",
            "-rA",
            str(child),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    return result.stdout


@pytest.mark.parametrize(
    ("case", "outcome", "visible"),
    [(case, outcome, visible) for case, _, _, _, outcome, visible in CASES],
)
def test_warning_policy(
    child_report: str, case: str, outcome: str, visible: bool
) -> None:
    """Keep the upstream filters exact and reject integration deprecations."""
    lines = child_report.splitlines()
    assert any(
        line.startswith(f"{outcome} ")
        and line.partition(" - ")[0].endswith(f"::test_{case}")
        for line in lines
    )
    summary = child_report.partition("warnings summary")[2].partition("-- Docs:")[0]
    assert (f"{case}.py:1:" in summary) == visible
