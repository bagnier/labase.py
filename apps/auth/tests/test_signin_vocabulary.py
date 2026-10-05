"""One ``SignedIn`` per session delivered, whatever the ceremony (AGENTS: signing in is one
fact)."""

import uuid

import pytest

from apps.auth.contract.events import SignedIn
from apps.auth.infra.router import relayed_method
from apps.shared.events.repository import event_to_record


def test_a_sign_in_records_how_the_session_was_obtained():
    actor = uuid.uuid7()

    record = event_to_record(SignedIn(user_id=actor, method="passkey", two_factor=False))

    assert (record.app_name, record.verb, record.user_id, record.payload) == (
        "auth",
        "signed_in",
        actor,
        {"method": "passkey", "two_factor": False},
    )


def test_a_sign_in_records_that_a_second_factor_was_cleared():
    record = event_to_record(SignedIn(user_id=uuid.uuid7(), method="password", two_factor=True))

    assert record.payload == {"method": "password", "two_factor": True}


@pytest.mark.parametrize(
    ("relayed", "expected"),
    [
        ("password", "password"),
        ("oauth", "oauth"),
        ("passkey", "passkey"),
        (None, "password"),  # cookie dropped
        ("nonsense", "password"),  # cookie forged
    ],
)
def test_the_method_that_opened_the_ceremony_survives_the_second_factor(relayed, expected):
    """The method travels in a cookie the caller controls; password is the only ceremony
    reachable without it."""
    assert relayed_method(relayed) == expected
