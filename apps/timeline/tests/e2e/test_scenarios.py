import pytest
from pytest_bdd import scenarios

from apps.shared.logs.chain import apply_log_level
from apps.shared.logs.sink import clear_log_sink
from apps.timeline.contract.integration import DEFAULT_LOG_LEVEL
from tests.e2e import cleanup

# Facts, occurrences and log lines commit outside the API driver's rolled-back transaction, so
# they are scrubbed before each scenario.
_OBSERVABILITY_TABLES = ["business_events", "issue_occurrences", "issues", "log_lines"]


@pytest.fixture(autouse=True)
def _isolate_observability_sources():
    cleanup.truncate_tables(_OBSERVABILITY_TABLES)
    clear_log_sink()
    # The log level is process state: reset it for the next scenario.
    apply_log_level(DEFAULT_LOG_LEVEL)


scenarios("../../../../features/timeline.feature")
