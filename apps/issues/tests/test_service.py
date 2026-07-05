from apps.issues.domain.models import IssueStatus
from apps.issues.domain.service import fingerprint, status_after_event, title_for


def _boom() -> ValueError:
    try:
        raise ValueError("user 42 not found")
    except ValueError as exc:
        return exc


def _boom_elsewhere() -> ValueError:
    try:
        raise ValueError("user 43 not found")
    except ValueError as exc:
        return exc


def test_fingerprint_ignores_the_variable_message():
    assert fingerprint(_boom()) == fingerprint(_boom())
    # same type, same message, different raise site → different issue
    assert fingerprint(_boom()) != fingerprint(_boom_elsewhere())


def test_fingerprint_distinguishes_exception_types():
    try:
        raise KeyError("user 42 not found")
    except KeyError as exc:
        key_error = exc
    assert fingerprint(_boom()) != fingerprint(key_error)


def test_fingerprint_manual_override_wins():
    first = fingerprint(_boom(), override="custom")
    assert first == fingerprint(_boom_elsewhere(), override="custom")


def test_title_keeps_type_and_message():
    assert title_for(_boom()) == "ValueError: user 42 not found"


def test_resolved_group_regresses_on_another_version():
    status = status_after_event(IssueStatus.resolved, "abc123", "def456")
    assert status is IssueStatus.regressed


def test_resolved_group_tolerates_events_from_the_fix_version():
    status = status_after_event(IssueStatus.resolved, "abc123", "abc123")
    assert status is IssueStatus.resolved


def test_ignored_and_triaged_statuses_are_sticky():
    assert status_after_event(IssueStatus.ignored, None, "v2") is IssueStatus.ignored
    assert status_after_event(IssueStatus.new, None, "v2") is IssueStatus.new
    assert status_after_event(IssueStatus.unresolved, None, "v2") is IssueStatus.unresolved
