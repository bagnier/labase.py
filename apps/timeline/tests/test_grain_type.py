"""The grain is a type the checker holds, not a runtime-only check.

The router narrows the requested bucket to ``_GRAINS`` once, then passes it on. Below that
narrowing, nothing stopped a wrong literal from reaching ``bucket_key`` or ``_axis_keys`` — a
call the type checker waved through, and the domain silently mis-bucketed at runtime. Held here
at the boundary ``ty`` actually checks: a value outside the four grains is a type error, not a
value the store falls back on.
"""

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]

_BAD_CALL = """\
from datetime import UTC, datetime

from apps.timeline.infra.repository import bucket_key

bucket_key(datetime(2026, 1, 1, tzinfo=UTC), "yeer")
"""


def test_ty_rejects_an_unknown_grain_literal(tmp_path):
    script = tmp_path / "bad_grain_call.py"
    script.write_text(_BAD_CALL)

    result = subprocess.run(
        [sys.executable, "-m", "ty", "check", "--project", str(_ROOT), str(script)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
