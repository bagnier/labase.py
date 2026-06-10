from pytest_bdd import given, parsers, then, when


@given(parsers.parse('they have uploaded "{filename}" to the org'))
def step_have_uploaded_file(driver, filename):
    driver.have_uploaded_file(filename)


@when(parsers.parse('they upload a file "{filename}" to the org'))
def step_upload_file(driver, filename):
    driver.upload_file(filename)


@when("they view the file list")
def step_view_file_list(driver):
    driver.view_file_list()


@when(parsers.parse('they download the file "{filename}"'))
def step_download_file(driver, filename):
    driver.download_file(filename)


@when(parsers.parse('they delete the file "{filename}"'))
def step_delete_file(driver, filename):
    driver.delete_file(filename)


@then(parsers.parse('"{filename}" appears in the file list'))
def step_assert_file_visible(driver, filename):
    driver.assert_file_visible(filename)


@then(parsers.parse('"{filename}" no longer appears in the file list'))
def step_assert_file_absent(driver, filename):
    driver.assert_file_absent(filename)


@then("the download succeeds")
def step_assert_download_succeeds(driver):
    driver.assert_download_succeeds()
