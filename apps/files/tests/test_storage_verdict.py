"""Storage failures: the status the caller gets and the dependency verdict."""

import pytest
from storage3.exceptions import StorageApiError
from structlog.testing import capture_logs

from apps.files.infra.router import storage_failure

# Storage sends its status as text.
_REFUSED = StorageApiError("Object not found", "NoSuchKey", "404")
_BROKEN = StorageApiError("Service unavailable", "InternalError", "503")


@pytest.mark.parametrize(
    ("exc", "status_code"), [(_REFUSED, 400), (_BROKEN, 500)], ids=["refused", "broken"]
)
def test_only_a_refusal_is_the_callers_fault(exc, status_code):
    with capture_logs():
        raised = storage_failure("files.upload_failed", exc, path="acme/x.txt")

    assert raised.status_code == status_code


@pytest.mark.parametrize(
    ("exc", "level"), [(_REFUSED, "info"), (_BROKEN, "error")], ids=["refused", "broken"]
)
def test_only_a_breakage_earns_an_issue(exc, level):
    with capture_logs() as logs:
        storage_failure("files.upload_failed", exc, path="acme/x.txt")

    assert [(e["event"], e["log_level"]) for e in logs] == [("files.upload_failed", level)]
