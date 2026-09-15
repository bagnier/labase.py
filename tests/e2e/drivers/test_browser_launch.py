"""Which Chromium the browser driver launches.

Playwright's own download is Google's Chrome for Testing. ``CHROMIUM_EXECUTABLE_PATH`` names a
Chromium installed on the machine instead; unset, the driver keeps Playwright's, which is what CI
runs. Pure over the environment, so it runs in every lane without starting a browser.
"""

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
    """Empty is what the Makefile forwards from a shell that never exported the variable."""
    monkeypatch.setenv("CHROMIUM_EXECUTABLE_PATH", "")

    options = launch_options()

    assert options == {}
