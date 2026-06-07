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


@when(parsers.parse('they mark "{title}" as done'))
def step_mark_todo_done(driver, title):
    driver.mark_todo_done(title)


@when(parsers.parse('they rename "{title}" to "{new_title}"'))
def step_rename_todo(driver, title, new_title):
    driver.rename_todo(title, new_title)


@when(parsers.parse('they delete "{title}"'))
def step_delete_todo(driver, title):
    driver.delete_todo(title)


@when(parsers.parse('they move "{title}" above "{above}"'))
def step_move_todo_above(driver, title, above):
    driver.move_todo_above(title, above)


@when(parsers.parse('they move "{title}" to the end'))
def step_move_todo_to_end(driver, title):
    driver.move_todo_to_end(title)


@then(parsers.parse("the items appear in order: {titles}"))
def step_assert_todo_order(driver, titles):
    items = [t.strip().strip('"') for t in titles.split(",")]
    driver.assert_todo_list_order(items)


@then(parsers.parse('"{title}" appears in their todo list'))
def step_assert_todo_visible(driver, title):
    driver.assert_todo_visible(title)


@then(parsers.parse('"{title}" is shown as completed'))
def step_assert_todo_completed(driver, title):
    driver.assert_todo_completed(title)


@then(parsers.parse('"{title}" no longer appears in their todo list'))
def step_assert_todo_absent(driver, title):
    driver.assert_todo_absent(title)
