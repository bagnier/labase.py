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
