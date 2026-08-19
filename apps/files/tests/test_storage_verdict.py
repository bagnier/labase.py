"""Storage is a dependency like any other — and it used to be the one exception.

Every ``StorageApiError`` became a 400: a bucket that had gone away, a Storage answering 5xx, the
service unreachable, all told to the user as "bad request" and filed under nothing. The README
promised one verdict for GoTrue, Postgres, Storage and SMTP alike; Storage was not on it.

These pin the two halves at the one seam the router now raises through — which status the caller
is owed, and which level the failure earns.
"""

import pytest
from storage3.exceptions import StorageApiError
from structlog.testing import capture_logs

from apps.files.infra.router import storage_failure

# Supabase Storage sends its status as text, so this is the shape a real one arrives in.
_REFUSED = StorageApiError("Object not found", "NoSuchKey", "404")
_BROKEN = StorageApiError("Service unavailable", "InternalError", "503")


@pytest.mark.parametrize(
    ("exc", "status_code"), [(_REFUSED, 400), (_BROKEN, 500)], ids=["refused", "broken"]
)
def test_only_a_refusal_is_the_callers_fault(exc, status_code):
    """Answering 400 to a Storage outage tells a user their upload was malformed when it was
    fine, and hides the outage behind a status nothing alerts on."""
    with capture_logs():
        raised = storage_failure("files.upload_failed", exc, path="acme/x.txt")

    assert raised.status_code == status_code


@pytest.mark.parametrize(
    ("exc", "level"), [(_REFUSED, "info"), (_BROKEN, "error")], ids=["refused", "broken"]
)
def test_only_a_breakage_earns_an_issue(exc, level):
    """``error`` carrying the exception is the capture seam; ``info`` is an ordinary outcome."""
    with capture_logs() as logs:
        storage_failure("files.upload_failed", exc, path="acme/x.txt")

    assert [(e["event"], e["log_level"]) for e in logs] == [("files.upload_failed", level)]
