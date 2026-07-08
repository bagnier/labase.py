import pytest
from pytest_bdd import scenarios

from apps.logs.contract.integration import DEFAULT_LOG_LEVEL
from apps.shared.observability.firehose import clear_firehose
from apps.shared.observability.logging import apply_log_level
from tests.e2e import cleanup

# Audit/issue rows are persisted through a background admin session that commits outside the
# API driver's rolled-back transaction, so they leak across scenarios (the browser driver
# already truncates between scenarios). The unified logs feature is the first to *read* these
# tables, so scrub them before each scenario to keep the timeline hermetic. The firehose lives
# in files, outside any transaction, so it needs the same scrub.
_OBSERVABILITY_TABLES = ["audit_logs", "error_events", "error_groups"]


@pytest.fixture(autouse=True)
def _isolate_observability_sources():
    cleanup.truncate_tables(_OBSERVABILITY_TABLES)
    clear_firehose()
    # The firehose level is global process state; a scenario that lowers it would otherwise leak
    # into the next (info-level request noise floods the empty-state/recent-window reads).
    apply_log_level(DEFAULT_LOG_LEVEL)


scenarios("../../../../features/unified-logs.feature")
