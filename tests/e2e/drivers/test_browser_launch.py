"""Which Chromium the browser driver launches; runs without a browser."""

import pytest

from tests.e2e.drivers.browser_base import launch_options


def test_no_executable_path_keeps_playwrights_own_chromium(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHROMIUM_EXECUTABLE_PATH", raising=False)

    options = launch_options()

    assert options == {}


def test_an_executable_path_launches_that_chromium(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CHROMIUM_EXECUTABLE_PATH", "/Applications/Chromium.app/Contents/MacOS/Chromium"
    )

    options = launch_options()

    assert options == {"executable_path": "/Applications/Chromium.app/Contents/MacOS/Chromium"}


def test_an_empty_executable_path_keeps_playwrights_own_chromium(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Makefile forwards an unset variable as empty."""
    monkeypatch.setenv("CHROMIUM_EXECUTABLE_PATH", "")

    options = launch_options()

    assert options == {}
