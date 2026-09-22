"""Granting admin to an account that is already admin changes nothing — only an effective
change is a fact. Driven through the API driver, over real HTTP, against the real journal."""

from sqlalchemy import text


def _admin_grant_facts(driver, email: str) -> list[str]:
    async def read() -> list[str]:
        async with driver.test_session_factory()() as session:
            rows = await session.execute(
                text(
                    "SELECT entity_name FROM business_events "
                    "WHERE kind = 'settings.admin_granted' AND entity_name = :email"
                ),
                {"email": email},
            )
            return [row.entity_name for row in rows]

    return driver.run(read())


def _admin_revoke_facts(driver, email: str) -> list[str]:
    async def read() -> list[str]:
        async with driver.test_session_factory()() as session:
            rows = await session.execute(
                text(
                    "SELECT entity_name FROM business_events "
                    "WHERE kind = 'settings.admin_revoked' AND entity_name = :email"
                ),
                {"email": email},
            )
            return [row.entity_name for row in rows]

    return driver.run(read())


def test_granting_an_already_admin_account_records_no_second_fact(driver):
    driver.sign_in_as_admin("admin-grant-noop@example.com")
    driver.register_regular_user("bob-grant-noop@example.com")

    driver.add_server_admin_by_email("bob-grant-noop@example.com")
    driver.add_server_admin_by_email("bob-grant-noop@example.com")

    assert driver.response.status_code == 200
    assert _admin_grant_facts(driver, "bob-grant-noop@example.com") == [
        "bob-grant-noop@example.com"
    ]


def test_granting_a_new_admin_records_the_fact(driver):
    driver.sign_in_as_admin("admin-grant-new@example.com")
    driver.register_regular_user("bob-grant-new@example.com")

    driver.add_server_admin_by_email("bob-grant-new@example.com")

    assert driver.response.status_code == 200
    assert _admin_grant_facts(driver, "bob-grant-new@example.com") == ["bob-grant-new@example.com"]


def test_setting_admin_to_its_current_value_records_no_fact(driver):
    driver.sign_in_as_admin("admin-set-noop@example.com")
    driver.register_regular_user("bob-set-noop@example.com")

    driver.designate_server_admin("bob-set-noop@example.com")
    driver.designate_server_admin("bob-set-noop@example.com")

    assert _admin_grant_facts(driver, "bob-set-noop@example.com") == ["bob-set-noop@example.com"]


def test_changing_admin_status_records_the_fact(driver):
    driver.sign_in_as_admin("admin-set-change@example.com")
    driver.register_regular_user("bob-set-change@example.com")
    driver.designate_server_admin("bob-set-change@example.com")

    driver.revoke_server_admin("bob-set-change@example.com")

    assert driver.response.status_code == 200
    assert _admin_revoke_facts(driver, "bob-set-change@example.com") == [
        "bob-set-change@example.com"
    ]
