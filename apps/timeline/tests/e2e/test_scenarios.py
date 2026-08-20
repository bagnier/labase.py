import pytest
from pytest_bdd import scenarios

from apps.shared.observability.logging import apply_log_level
from apps.shared.observability.sink import clear_log_sink
from apps.timeline.contract.integration import DEFAULT_LOG_LEVEL
from tests.e2e import cleanup

# Business-event/issue/log rows are persisted through a background admin session that commits
# outside the API driver's rolled-back transaction, so they leak across scenarios (the browser
# driver already truncates between scenarios). The timeline feature is the first to *read* these
# tables, so scrub them before each scenario to keep the timeline hermetic. ``log_lines`` joined
# the list when the firehose moved off local files and into the store every instance shares.
_OBSERVABILITY_TABLES = ["business_events", "issue_occurrences", "issues", "log_lines"]


@pytest.fixture(autouse=True)
def _isolate_observability_sources():
    cleanup.truncate_tables(_OBSERVABILITY_TABLES)
    clear_log_sink()  # the queue and the fallback files
    # The firehose level is global process state; a scenario that lowers it would otherwise leak
    # into the next (info-level request noise floods the empty-state/recent-window reads).
    apply_log_level(DEFAULT_LOG_LEVEL)


scenarios("../../../../features/timeline.feature")
