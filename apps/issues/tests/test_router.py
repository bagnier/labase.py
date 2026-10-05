"""The router narrows both status inputs; an unknown value would be a 500 from the driver."""

import pytest
from fastapi import HTTPException

from apps.issues.domain.models import IssueStatus
from apps.issues.infra.router import _status_filter, _triage_status


def test_an_empty_filter_means_every_status():
    assert _status_filter("") is None


def test_a_known_status_narrows_the_filter():
    assert _status_filter("regressed") is IssueStatus.regressed


def test_an_unknown_status_filter_is_refused_at_the_edge():
    with pytest.raises(HTTPException) as refused:
        _status_filter("not-a-status")

    assert refused.value.status_code == 400


def test_triage_accepts_the_three_statuses_a_human_may_set():
    assert [_triage_status(s) for s in ("resolved", "ignored", "unresolved")] == [
        IssueStatus.resolved,
        IssueStatus.ignored,
        IssueStatus.unresolved,
    ]


def test_triage_refuses_a_status_only_the_tracker_may_set():
    with pytest.raises(HTTPException) as refused:
        _triage_status("regressed")

    assert refused.value.status_code == 400
