"""The sign-in grammar: one fact per session delivered, whatever obtained it.

A session issued by a password, an OAuth round-trip, a passkey or a mailed confirmation link is the
same fact — someone is now signed in. The mechanism that produced it is a *detail of* that fact, not
a fact of its own, so it rides in the payload rather than splitting the vocabulary into one kind per
ceremony (which is how a 2FA sign-in ended up recorded under ``auth.mfa_verified`` and an OAuth one
under a kind emitted before the session even existed).
"""

import uuid

import pytest

from apps.auth.contract.events import SignedIn
from apps.auth.infra.router import relayed_method
from apps.shared.events.repository import event_to_record


def test_a_sign_in_records_how_the_session_was_obtained():
    actor = uuid.uuid7()

    row = event_to_record(SignedIn(user_id=actor, method="passkey", two_factor=False))

    assert (row.app_name, row.verb, row.user_id, row.payload) == (
        "auth",
        "signed_in",
        actor,
        {"method": "passkey", "two_factor": False},
    )


def test_a_sign_in_records_that_a_second_factor_was_cleared():
    # The 2FA passage is a property of the session, not a separate ceremony to name: the same kind
    # carries it, so "how many people signed in" stays one query.
    row = event_to_record(SignedIn(user_id=uuid.uuid7(), method="password", two_factor=True))

    assert row.payload == {"method": "password", "two_factor": True}


@pytest.mark.parametrize(
    ("relayed", "expected"),
    [
        ("password", "password"),
        ("oauth", "oauth"),
        (None, "password"),  # a relay cookie the browser dropped
        ("nonsense", "password"),  # anything a caller can forge
    ],
)
def test_the_method_that_opened_the_ceremony_survives_the_second_factor(relayed, expected):
    # The second factor is verified on a later request, so how the ceremony began travels in a
    # cookie — i.e. through the caller's hands. Narrowing it back to the closed set here is what
    # stops a forged or missing value from reaching the trail as an unknown method; falling back to
    # the password ceremony is honest, since that is the only one reachable without a relay.
    assert relayed_method(relayed) == expected
