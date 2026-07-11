from pytest_bdd import given, parsers, then, when


@when(parsers.parse('they create a page titled "{title}" with content "{content}"'))
def step_create_page(driver, title, content):
    driver.create_page(title, content)


@then(parsers.parse('"{title}" appears in the pages list'))
def step_assert_page_in_list(driver, title):
    driver.assert_page_in_list(title)


@then(parsers.parse('"{title}" no longer appears in the pages list'))
def step_assert_page_absent(driver, title):
    driver.assert_page_absent(title)


@then(parsers.parse('the page "{slug}" is a draft'))
def step_assert_draft(driver, slug):
    driver.assert_page_visibility(slug, "draft")


@then(parsers.parse('the page "{slug}" exists'))
def step_assert_exists(driver, slug):
    driver.assert_page_exists(slug)


@then(parsers.parse('the page "{slug}" no longer exists'))
def step_assert_not_exists(driver, slug):
    driver.assert_page_not_exists(slug)


@given(parsers.parse('a draft page titled "{title}" with slug "{slug}" and content "{content}"'))
def step_given_draft(driver, title, slug, content):
    driver.create_draft_page(title, slug, content)


@given(parsers.parse('a page titled "{title}" with slug "{slug}" published to members'))
def step_given_members_page(driver, title, slug):
    driver.create_published_page(title, slug, "members")


@given(parsers.parse('a page titled "{title}" with slug "{slug}" published publicly'))
def step_given_public_page(driver, title, slug):
    driver.create_published_page(title, slug, "public")


@when(parsers.parse('they change the slug of "{slug}" to "{new_slug}"'))
def step_change_slug(driver, slug, new_slug):
    driver.change_slug(slug, new_slug)


@when(parsers.parse('they update the content of "{slug}" to "{content}"'))
def step_update_content(driver, slug, content):
    driver.update_content(slug, content)


@then(parsers.parse('viewing the page "{slug}" shows the text "{text}"'))
def step_view_contains(driver, slug, text):
    driver.assert_view_contains(slug, text)


@when(parsers.parse('they delete the page "{slug}"'))
def step_delete_page(driver, slug):
    driver.delete_page(slug)


@when(parsers.parse('they view the page "{slug}"'))
def step_view_page(driver, slug):
    driver.view_page(slug)


@then(parsers.parse('the rendered page shows a heading "{text}"'))
def step_rendered_heading(driver, text):
    driver.assert_rendered_heading(text)


@then(parsers.parse('the rendered page shows a list item "{text}"'))
def step_rendered_list_item(driver, text):
    driver.assert_rendered_list_item(text)


@when(parsers.parse('they publish the page "{slug}" to members'))
def step_publish_members(driver, slug):
    driver.publish_to_members(slug)


@when(parsers.parse('they publish the page "{slug}" publicly'))
def step_publish_public(driver, slug):
    driver.publish_public(slug)


@when(parsers.parse('they try to publish the page "{slug}" to members'))
def step_try_publish_members(driver, slug):
    driver.try_publish_to_members(slug)


@given(parsers.parse('the owner has published the page "{slug}" to members'))
def step_owner_published_members(driver, slug):
    driver.owner_publish_to_members(slug)


@then(parsers.parse('the page "{slug}" is visible to members'))
def step_visible_to_members(driver, slug):
    driver.assert_visible_to_members(slug)


@then("the rendered page is shown")
def step_rendered_shown(driver):
    driver.assert_rendered_shown()


@then(parsers.parse('they cannot edit the page "{slug}"'))
def step_cannot_edit(driver, slug):
    driver.assert_cannot_edit(slug)


@then(parsers.parse('a visitor can view "{slug}" under org "{org_name}"'))
def step_visitor_can_view(driver, slug, org_name):
    driver.assert_visitor_can_view(slug, org_name)


@when(parsers.parse('a visitor opens "{slug}" under org "{org_name}"'))
def step_visitor_open(driver, slug, org_name):
    driver.visitor_open(slug, org_name)


@then("they are not allowed to see it")
def step_visitor_forbidden(driver):
    driver.assert_visitor_forbidden()


@when("they view the pages list")
def step_view_pages_list(driver):
    driver.view_pages_list()


@when(parsers.parse('"{email}" views their pages list'))
def step_view_pages_list_as(driver, email):
    driver.view_pages_list_as(email)


@then(parsers.parse('"{title}" is not in that pages list'))
def step_assert_page_hidden(driver, title):
    driver.assert_page_hidden_from_view(title)


@then(parsers.parse('"{a}", "{b}" and "{c}" appear in the pages list'))
def step_assert_three_listed(driver, a, b, c):
    for title in (a, b, c):
        driver.assert_page_in_list(title)


@when(parsers.parse('a visitor opens the public pages of org "{org_name}"'))
def step_visitor_open_list(driver, org_name):
    driver.visitor_open_list(org_name)


@then(parsers.parse('only "{title}" is listed'))
def step_only_listed(driver, title):
    driver.assert_only_listed(title)


# ── page navigation ────────────────────────────────────────────────────────────


@when("they open the navigation manager")
def step_open_nav_manager(driver):
    driver.open_nav_manager()


@when(parsers.parse('they add "{title}" to the navigation'))
def step_add_to_nav(driver, title):
    driver.add_to_nav(title)


@when(parsers.parse('they remove "{title}" from the navigation'))
def step_remove_from_nav(driver, title):
    driver.remove_from_nav(title)


@when(parsers.parse('they move "{title}" above "{other}" in the navigation'))
def step_move_nav_above(driver, title, other):
    driver.move_nav_above(title, other)


@given(parsers.parse('"{title}" is in the navigation'))
def step_given_in_nav(driver, title):
    driver.given_in_nav(title)


@given(parsers.parse('"{title}" is in the navigation at position {pos:d}'))
def step_given_in_nav_at_pos(driver, title, pos):
    driver.given_in_nav(title)


@then(parsers.parse('"{title}" appears in the navigation'))
def step_assert_in_nav(driver, title):
    driver.assert_in_nav(title)


@then(parsers.parse('"{title}" no longer appears in the navigation'))
def step_assert_not_in_nav(driver, title):
    driver.assert_not_in_nav(title)


@then(parsers.parse('the navigation shows "{a}" then "{b}"'))
def step_assert_nav_order(driver, a, b):
    driver.assert_nav_order(a, b)


@then(parsers.parse('"{title}" is not listed as a navigation candidate'))
def step_assert_not_nav_candidate(driver, title):
    driver.assert_not_nav_candidate(title)


@then(parsers.parse('the page navigation shows a link to "{title}"'))
def step_assert_page_nav_shows(driver, title):
    driver.assert_page_nav_shows(title)


@then(parsers.parse('the page navigation does not show a link to "{title}"'))
def step_assert_page_nav_not_shows(driver, title):
    driver.assert_page_nav_not_shows(title)


@given("the org is the featured public org")
def step_set_featured_org(driver, request):
    handle = driver._handle()
    acting = driver._acting_email
    driver.sign_in_as_admin("nav-admin@example.com")
    driver.set_console_setting("public", "featured_org_handle", handle)
    driver.set_acting_email(acting)

    request.addfinalizer(lambda: driver.set_console_setting("public", "featured_org_handle", ""))


@given(parsers.parse('a visitor views the public page "{slug}"'))
@when(parsers.parse('a visitor views the public page "{slug}"'))
def step_visitor_view_public_page(driver, slug):
    driver.visitor_view_public_page(slug)
