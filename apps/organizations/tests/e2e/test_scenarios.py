from pytest_bdd import scenario, scenarios

# Bound explicitly for the claim `personal-org-at-signup` (tests/meta/claims.py); `scenarios()`
# skips it.


@scenario(
    "../../../../features/organizations.feature",
    "A new user gets a personal organisation on registration",
)
def test_a_new_user_gets_a_personal_organisation_on_registration() -> None:
    """Claim ``personal-org-at-signup``."""


# pytest-bdd returns an anonymous wrapper: name it for the registry.
test_a_new_user_gets_a_personal_organisation_on_registration.__name__ = (
    "test_a_new_user_gets_a_personal_organisation_on_registration"
)
test_a_new_user_gets_a_personal_organisation_on_registration.__module__ = __name__

scenarios("../../../../features/organizations.feature")
scenarios("../../../../features/org-members.feature")
scenarios("../../../../features/org-invitations.feature")
scenarios("../../../../features/dashboard_widgets.feature")
