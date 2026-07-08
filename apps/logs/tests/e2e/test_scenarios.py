import pytest
from pytest_bdd import scenarios

from tests.e2e import cleanup

# Audit/issue rows are persisted through a background admin session that commits outside the
# API driver's rolled-back transaction, so they leak across scenarios (the browser driver
# already truncates between scenarios). The unified logs feature is the first to *read* these
# tables, so scrub them before each scenario to keep the timeline hermetic.
_OBSERVABILITY_TABLES = ["audit_logs", "error_events", "error_groups"]


@pytest.fixture(autouse=True)
def _isolate_observability_tables():
    cleanup.truncate_tables(_OBSERVABILITY_TABLES)


scenarios("../../../../features/unified-logs.feature")
