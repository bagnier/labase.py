"""``ty`` rejects a grain outside the four, at both call sites. The assertion pins the
diagnostic, not just a non-zero exit, which an unrelated error would also give."""

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
