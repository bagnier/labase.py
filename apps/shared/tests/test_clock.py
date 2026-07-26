"""The single clock — relative-moment formatting is pure and deterministic given ``now``."""

from datetime import timedelta

import pytest

from apps.shared import clock
from apps.shared.clock import ago


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=5), "just now"),
        (timedelta(minutes=3), "3m ago"),
        (timedelta(hours=4), "4h ago"),
        (timedelta(days=2), "2d ago"),
    ],
)
def test_ago_is_a_compact_relative_moment(delta, expected):
    now = clock.now()
    assert ago(now - delta, now) == expected
