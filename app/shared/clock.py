import os
from datetime import UTC, datetime
from pathlib import Path

# Tests pin "now" by writing an ISO instant to this file (path passed via env so
# the server subprocess inherits it). Unset in production → real wall clock, no I/O.
_CLOCK_FILE = os.environ.get("LABASE_CLOCK_FILE")


def now() -> datetime:
    if _CLOCK_FILE:
        try:
            raw = Path(_CLOCK_FILE).read_text().strip()
        except FileNotFoundError:
            raw = ""
        if raw:
            return datetime.fromisoformat(raw)
    return datetime.now(UTC)
