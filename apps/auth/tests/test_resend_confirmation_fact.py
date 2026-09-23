"""A resend answers the same way for a known and an unknown address (no enumeration), but only an
address with an account is where anything happened — only what happened is a fact."""

from unittest.mock import patch

from sqlalchemy import text


def _confirmation_resent_facts(driver) -> list[str]:
    async def read() -> list[str]:
        async with driver.test_session_factory()() as session:
            rows = await session.execute(
                text(
                    "SELECT entity_name FROM business_events "
                    "WHERE kind = 'auth.confirmation_resent'"
                )
            )
            return [row.entity_name for row in rows]

    return driver.run(read())


def test_a_resend_to_an_address_with_no_account_records_no_fact(driver):
    driver.resend_confirmation_to("ghost@example.com")

    assert _confirmation_resent_facts(driver) == []


def test_a_resend_to_an_unconfirmed_account_records_its_fact(driver):
    driver.register_unconfirmed("pending-fact@example.com", "Test1234!")

    driver.resend_confirmation_to("pending-fact@example.com")

    assert _confirmation_resent_facts(driver) == ["pending-fact@example.com"]


def test_a_resend_to_an_already_confirmed_account_records_no_fact(driver):
    driver.register_disposable("already-confirmed@example.com", "Test1234!")

    driver.resend_confirmation_to("already-confirmed@example.com")

    assert _confirmation_resent_facts(driver) == []


def test_an_address_with_no_account_still_costs_the_gotrue_call(driver):
    """GoTrue's resend is doubled because the interaction is the behaviour: skipping the call for
    an unknown address answers measurably faster, and that timing enumerates the accounts the
    neutral message hides."""
    asked: list[str] = []

    async def resend(email: str) -> None:
        asked.append(email)

    with patch("apps.auth.infra.router.resend_confirmation", resend):
        driver.resend_confirmation_to("ghost@example.com")

    assert asked == ["ghost@example.com"]
