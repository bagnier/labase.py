from pytest_bdd import given, parsers, then, when


@then("they have exactly one organisation")
def step_assert_org_count_one(driver):
    driver.assert_org_count(1)


@then("they are its owner")
def step_assert_is_owner(driver):
    driver.assert_is_owner()


@when(parsers.parse('"{email}" views their organisation list'))
def step_view_org_list_as(driver, email):
    driver.view_org_list_as(email)


@then(parsers.parse('"{email}"\'s organisation does not appear in the list'))
def step_assert_other_org_absent(driver, email):
    driver.assert_other_org_absent(email)


@given(parsers.parse('they have also joined "{org_name}" as member "{email}"'))
def step_join_org_as_member(driver, org_name, email):
    driver.join_org_as_member(org_name, email)


@when("they view their organisation list")
def step_view_org_list(driver):
    driver.view_org_list()


@then(parsers.parse('"{org_name}" appears in their organisation list'))
def step_assert_org_in_list(driver, org_name):
    driver.assert_org_in_list(org_name)


@then(parsers.parse('"{org_name}" no longer appears in their organisation list'))
def step_assert_org_absent(driver, org_name):
    driver.assert_org_absent(org_name)


@when(parsers.parse('they rename the active organisation to "{new_name}"'))
def step_rename_org(driver, new_name):
    driver.rename_org(new_name)


@given(parsers.parse('"{email}" is a member of the org'))
def step_member_of_org(driver, email):
    driver.add_member_to_org(email)


@given(parsers.parse('they are signed in as "{email}" in the same org'))
def step_sign_in_as_member(driver, email):
    driver.sign_in_as_member(email)


@then("the action is forbidden")
def step_action_forbidden(driver):
    driver.assert_action_forbidden()


@then(parsers.parse('"{org_name}" appears as a workspace card'))
def step_assert_workspace_card(driver, org_name):
    driver.assert_workspace_card(org_name)


@when("they view the member list")
def step_view_member_list(driver):
    driver.view_member_list()


@then(parsers.parse('"{email}" appears in the member list with role "{role}"'))
def step_assert_member_with_role(driver, email, role):
    driver.assert_member_with_role(email, role)


@then(parsers.parse('"{email}" does not appear in the member list'))
def step_assert_member_absent(driver, email):
    driver.assert_member_absent(email)


@when(parsers.parse('they set the role of "{email}" to "{role}"'))
def step_set_member_role(driver, email, role):
    driver.set_member_role(email, role)


@when(parsers.parse('they remove "{email}" from the org'))
def step_remove_member(driver, email):
    driver.remove_member(email)


@when("they leave the organisation")
def step_leave_org(driver):
    driver.leave_org()


@when(parsers.parse('they invite "{email}" to the organisation with role "{role}"'))
def step_invite_member(driver, email, role):
    driver.invite_member(email, role)


@when("they view the pending invitations list")
def step_view_pending_invitations(driver):
    driver.view_pending_invitations()


@then(
    parsers.parse(
        'an invitation for "{email}" appears in the pending invitations list with role "{role}"'
    )
)
def step_assert_invitation_pending(driver, email, role):
    driver.assert_invitation_pending(email, role)


@then(parsers.parse('"{email}" does not appear in the pending invitations list'))
def step_assert_invitation_absent(driver, email):
    driver.assert_invitation_absent(email)


@when(parsers.parse('they revoke the invitation for "{email}"'))
def step_revoke_invitation(driver, email):
    driver.revoke_invitation(email)


@when(parsers.parse('"{email}" registers through the invitation link and accepts it'))
def step_register_via_invitation(driver, email):
    driver.register_via_invitation_and_accept(email)


@when(parsers.parse('"{email}" accepts the invitation'))
def step_accept_invitation(driver, email):
    driver.accept_invitation(email)


@when(parsers.parse('"{email}" tries to accept the revoked invitation'))
def step_try_accept_revoked(driver, email):
    driver.try_accept_revoked_invitation(email)


@when(parsers.parse('"{email}" follows the invitation link again'))
def step_follow_invitation_link_again(driver, email):
    driver.follow_invitation_link_again(email)


@then("they are redirected to the organisation dashboard")
def step_assert_redirected_to_org_dashboard(driver):
    driver.assert_redirected_to_org_dashboard()


@then(parsers.parse('the action fails with error "{message}"'))
def step_action_fails_with(driver, message):
    driver.assert_action_fails_with(message)


@when("they try to access an org dashboard without signing in")
def step_access_org_dashboard_unauthenticated(driver):
    driver.visit_org_dashboard_unauthenticated()


@when("they view their org dashboard")
def step_view_org_dashboard(driver):
    driver.view_org_dashboard()


@then("the org dashboard is visible")
def step_org_dashboard_visible(driver):
    driver.assert_org_dashboard_visible()


# ── Dashboard overviews ───────────────────────────────────────────────────────


@then(parsers.parse('the "{key}" overview is visible on the dashboard'))
def step_overview_visible(driver, key):
    driver.assert_overview_visible(key)


@then(parsers.parse('the "{key}" overview shows "{text}"'))
def step_overview_shows(driver, key, text):
    driver.assert_overview_shows(key, text)


@then(parsers.parse('the "{key}" overview lists "{text}"'))
def step_overview_lists(driver, key, text):
    driver.assert_overview_lists(key, text)
