from pytest_bdd import given, parsers, then, when


@given(parsers.parse('the current date is "{date}"'))
def step_set_current_date(driver, date):
    driver.set_current_date(date)


@given(parsers.parse('they have uploaded "{filename}" to the org'))
def step_have_uploaded_file(driver, filename):
    driver.have_uploaded_file(filename)


@when("they view the file list")
def step_view_file_list(driver):
    driver.view_file_list()


@then(parsers.parse('"{filename}" appears in the file list'))
def step_assert_file_visible(driver, filename):
    driver.assert_file_visible(filename)


@then(parsers.parse('"{filename}" no longer appears in the file list'))
def step_assert_file_absent(driver, filename):
    driver.assert_file_absent(filename)


@then("the download succeeds")
def step_assert_download_succeeds(driver):
    driver.assert_download_succeeds()


# ── new steps ─────────────────────────────────────────────────────────────────


@when(parsers.parse('they upload "{filename}" to the org'))
def step_upload_file(driver, filename):
    driver.upload_file(filename)


@when(parsers.parse('they download "{filename}"'))
def step_download_file(driver, filename):
    driver.download_file(filename)


@when(parsers.parse('they delete "{filename}"'))
def step_delete_file(driver, filename):
    driver.delete_file(filename)


@given("the org has a file size limit of 50 MB")
def step_file_size_limit():
    pass  # no-op — limit is always enforced


@when("they upload a file of 51 MB to the org")
def step_upload_oversized(driver):
    driver.upload_oversized_file(51)


@given(parsers.parse('"{email}" has uploaded "{filename}" to the org'))
def step_upload_as(driver, email, filename):
    driver.upload_file_as(email, filename)


@given(parsers.parse('"{email}" has uploaded "{filename}" of {size_kb:d} KB to the org'))
def step_upload_as_sized(driver, email, filename, size_kb):
    driver.upload_file_as(email, filename, size_kb=size_kb)


@given(parsers.parse('"{email}" is a member of "{org_name}"'))
def step_create_user_in_org(driver, email, org_name):
    driver.create_user_in_org(email, org_name)


@given("they are an owner of the org")
def step_promote_to_owner(driver):
    driver.promote_to_owner()


@given("they are a member of the org")
def step_demote_to_member(driver):
    driver.demote_to_member()


@given(parsers.parse('they have generated a share link for "{filename}"'))
def step_generate_share_link(driver, filename):
    driver.generate_share_link(filename)


@when(parsers.parse('they rename "{filename}" to "{new_filename}"'))
def step_rename_file(driver, filename, new_filename):
    driver.rename_file(filename, new_filename)


@when(parsers.parse('"{email}" views the file list'))
def step_view_as(driver, email):
    driver.view_file_list_as(email)


@when(parsers.parse('"{email}" accesses the share link'))
def step_access_share_as(driver, email):
    driver.access_share_link_as(email)


@when("a non-member accesses the share link")
def step_access_share_unauthenticated(driver):
    driver.access_share_link_unauthenticated()


@then("the action is denied")
def step_action_denied(driver):
    driver.assert_action_denied()


@then("the action is rejected")
def step_action_rejected(driver):
    driver.assert_action_rejected()


@when(parsers.parse('they upload a file with filename "{filename}"'))
def step_upload_raw_filename(driver, filename):
    driver.upload_file_with_raw_filename(filename)


@then(parsers.parse("the upload is rejected with status {status:d}"))
def step_upload_rejected_with_status(driver, status):
    driver.assert_upload_rejected(status)


@then(
    parsers.parse(
        '"{filename}" appears in the file list with size "{size}",'
        ' uploaded by "{email}" on "{date}"'
    )
)
def step_assert_file_metadata(driver, filename, size, email, date):
    driver.assert_file_metadata(filename, size, email, date)
