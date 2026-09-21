from pytest_bdd import scenario, scenarios

# Bound explicitly so the claims registry can hold README sentences with them
# (`first-user-is-admin`, `admins-promote-admins`, tests/meta/claims.py); `scenarios()` skips what
# is already bound.


@scenario(
    "../../../../features/server-admins.feature",
    "The first registered user becomes a server admin",
)
def test_the_first_registered_user_becomes_a_server_admin() -> None:
    """Holds the README claim: whoever signs up while the server has no admin becomes one."""


# pytest-bdd returns an anonymous wrapper; give it back the identity the registry reads.
test_the_first_registered_user_becomes_a_server_admin.__name__ = (
    "test_the_first_registered_user_becomes_a_server_admin"
)
test_the_first_registered_user_becomes_a_server_admin.__module__ = __name__


@scenario("../../../../features/server-admins.feature", "An admin adds another admin by email")
def test_an_admin_adds_another_admin_by_email() -> None:
    """Holds the README claim: an admin can then promote any other user as admin."""


test_an_admin_adds_another_admin_by_email.__name__ = "test_an_admin_adds_another_admin_by_email"
test_an_admin_adds_another_admin_by_email.__module__ = __name__

scenarios("../../../../features/server-admins.feature")
