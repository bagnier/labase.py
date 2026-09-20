from pytest_bdd import scenario, scenarios

# Bound explicitly so the claims registry can hold a README sentence with it
# (`first-user-is-admin`, tests/meta/claims.py); `scenarios()` skips what is already bound.


@scenario(
    "../../../../features/server-admins.feature",
    "The first registered user becomes a server admin",
)
def test_the_first_registered_user_becomes_a_server_admin() -> None:
    """Holds the README claim: first signed-up user is admin."""


# pytest-bdd returns an anonymous wrapper; give it back the identity the registry reads.
test_the_first_registered_user_becomes_a_server_admin.__name__ = (
    "test_the_first_registered_user_becomes_a_server_admin"
)
test_the_first_registered_user_becomes_a_server_admin.__module__ = __name__

scenarios("../../../../features/server-admins.feature")
