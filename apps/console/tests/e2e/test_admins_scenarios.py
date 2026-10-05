from pytest_bdd import scenario, scenarios

# Bound explicitly for the claims `first-user-is-admin` and `admins-promote-admins`
# (tests/meta/claims.py); `scenarios()` skips them.


@scenario(
    "../../../../features/server-admins.feature",
    "The first registered user becomes a server admin",
)
def test_the_first_registered_user_becomes_a_server_admin() -> None:
    """Claim ``first-user-is-admin``."""


# pytest-bdd returns an anonymous wrapper: name it for the registry.
test_the_first_registered_user_becomes_a_server_admin.__name__ = (
    "test_the_first_registered_user_becomes_a_server_admin"
)
test_the_first_registered_user_becomes_a_server_admin.__module__ = __name__


@scenario("../../../../features/server-admins.feature", "An admin adds another admin by email")
def test_an_admin_adds_another_admin_by_email() -> None:
    """Claim ``admins-promote-admins``."""


test_an_admin_adds_another_admin_by_email.__name__ = "test_an_admin_adds_another_admin_by_email"
test_an_admin_adds_another_admin_by_email.__module__ = __name__

scenarios("../../../../features/server-admins.feature")
