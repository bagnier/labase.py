from pytest_bdd import scenario, scenarios

# Bound explicitly so the claims registry can hold a README sentence with it
# (`personal-org-at-signup`, tests/meta/claims.py); `scenarios()` skips what is already bound.


@scenario(
    "../../../../features/organizations.feature",
    "A new user gets a personal organisation on registration",
)
def test_a_new_user_gets_a_personal_organisation_on_registration() -> None:
    """Holds the README claim: every account gets a personal organization at sign-up."""


# pytest-bdd returns an anonymous wrapper; give it back the identity the registry reads.
test_a_new_user_gets_a_personal_organisation_on_registration.__name__ = (
    "test_a_new_user_gets_a_personal_organisation_on_registration"
)
test_a_new_user_gets_a_personal_organisation_on_registration.__module__ = __name__

scenarios("../../../../features/organizations.feature")
scenarios("../../../../features/org-members.feature")
scenarios("../../../../features/org-invitations.feature")
scenarios("../../../../features/dashboard_widgets.feature")
