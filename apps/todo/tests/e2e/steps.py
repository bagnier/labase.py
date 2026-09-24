from pytest_bdd import given, parsers, then, when


@given(parsers.parse("they have todo items {titles}"))
def step_have_todo_items(driver, titles):
    items = [t.strip().strip('"') for t in titles.split(",")]
    driver.have_todo_items(items)


@given(parsers.parse('they have a todo item "{title}"'))
def step_have_todo_item(driver, title):
    driver.have_todo_items([title])


@when("they view their todo list")
def step_view_todo_list(driver):
    driver.view_todo_list()


@when(parsers.parse('they add a todo item "{title}"'))
def step_add_todo(driver, title):
    driver.add_todo(title)


@given(parsers.parse('they mark the todo item "{title}" as done'))
@when(parsers.parse('they mark the todo item "{title}" as done'))
def step_mark_todo_done(driver, title):
    driver.mark_todo_done(title)


@when(parsers.parse('they rename the todo item "{title}" to "{new_title}"'))
def step_rename_todo(driver, title, new_title):
    driver.rename_todo(title, new_title)


@when(parsers.parse('they delete the todo item "{title}"'))
def step_delete_todo(driver, title):
    driver.delete_todo(title)


@when(parsers.parse('they move the todo item "{title}" above "{above}"'))
def step_move_todo_above(driver, title, above):
    driver.move_todo_above(title, above)


@when(parsers.parse('they move the todo item "{title}" to the end'))
def step_move_todo_to_end(driver, title):
    driver.move_todo_to_end(title)


@then(parsers.parse("the items appear in order: {titles}"))
def step_assert_todo_order(driver, titles):
    items = [t.strip().strip('"') for t in titles.split(",")]
    driver.assert_todo_list_order(items)


@then(parsers.parse('"{title}" appears in their todo list'))
def step_assert_todo_visible(driver, title):
    driver.assert_todo_visible(title)


@when(parsers.parse('they mark the todo item "{title}" as not done'))
def step_mark_todo_not_done(driver, title):
    driver.mark_todo_not_done(title)


@then(parsers.parse('"{title}" is shown as completed'))
def step_assert_todo_completed(driver, title):
    driver.assert_todo_completed(title)


@then(parsers.parse('"{title}" is shown as not completed'))
def step_assert_todo_not_completed(driver, title):
    driver.assert_todo_not_completed(title)


@then(parsers.parse('"{title}" no longer appears in their todo list'))
def step_assert_todo_absent(driver, title):
    driver.assert_todo_absent(title)


@given(
    parsers.parse('the "{app}" setting "{key}" is overridden to "{value}" for their organisation')
)
def step_org_setting_override(driver, app, key, value):
    driver.seed_org_setting_override(app, key, value)


@when(parsers.parse('they try to add a todo item "{title}"'))
def step_try_add_todo(driver, title):
    driver.try_add_todo(title)


@when(parsers.parse('"{email}" views their todo list'))
def step_view_todo_list_as(driver, email):
    driver.view_todo_list_as(email)


@then(parsers.parse("the todo dashboard card reads {badges}"))
def step_assert_todo_dashboard_badges(driver, badges):
    driver.assert_dashboard_badges([b.strip().strip('"') for b in badges.split(",")])


@then(parsers.parse('"{title}" is not in that todo list'))
def step_assert_todo_hidden(driver, title):
    driver.assert_todo_hidden_from_view(title)


@when(parsers.parse('they tab to the edit button of "{title}"'))
def step_tab_to_edit_button(driver, title):
    driver.tab_to_todo_edit_button(title)


@when(parsers.parse('they tab to the delete button of "{title}"'))
def step_tab_to_delete_button(driver, title):
    driver.tab_to_todo_delete_button(title)


@then("the focused button is visible")
def step_assert_focused_button_visible(driver):
    driver.assert_focused_control_visible()


@when("they press Enter")
def step_press_enter(driver):
    driver.press_enter()


@then(parsers.parse('the rename field for "{title}" holds keyboard focus'))
def step_assert_rename_field_focused(driver, title):
    driver.assert_rename_field_focused(title)
