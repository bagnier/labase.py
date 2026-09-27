"""The grain is a type the checker holds, not a runtime-only check.

The router narrows the requested bucket to ``_GRAINS`` once, then passes it on. Below that
narrowing, nothing stopped a wrong literal from reaching ``bucket_key`` or ``_axis_keys`` — a
call the type checker waved through, and the domain silently mis-bucketed or raised past the
router's one runtime check. Held here at the boundary ``ty`` actually checks: a value outside the
four grains is a type error, at both call sites, not a value either falls back or crashes on.

The assertion pins the diagnostic ``ty`` gives, not just a non-zero exit: a bare ``!= 0`` would
stay green if the grain parameter were ever mistyped back to ``str`` and the call broke for an
unrelated reason (an unresolved import, say), which would prove nothing about the grain at all.
"""

import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]

_DIAGNOSTIC = "error[invalid-argument-type]"
_EXPECTED = 'Expected `Literal["hour", "day", "week", "month"]`, found `Literal["yeer"]`'

_CALLS = {
    "bucket_key": """\
from datetime import UTC, datetime

from apps.timeline.infra.repository import bucket_key

bucket_key(datetime(2026, 1, 1, tzinfo=UTC), "yeer")
""",
    "_axis_keys": """\
from datetime import UTC, datetime

from apps.timeline.infra.router import _axis_keys

_axis_keys("yeer", datetime(2026, 1, 1, tzinfo=UTC))
""",
}


@pytest.mark.parametrize("site", sorted(_CALLS))
def test_ty_rejects_an_unknown_grain_literal(tmp_path, site):
    script = tmp_path / "bad_grain_call.py"
    script.write_text(_CALLS[site])

    result = subprocess.run(
        [sys.executable, "-m", "ty", "check", "--project", str(_ROOT), str(script)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert _DIAGNOSTIC in result.stdout
    assert _EXPECTED in result.stdout
