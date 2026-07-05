from pytest_bdd import given, parsers, then, when


@given(parsers.parse('they have created an API key named "{name}"'))
@when(parsers.parse('they create an API key named "{name}"'))
def step_create_api_key(driver, name):
    driver.create_api_key(name)


@then("the API key secret is revealed once")
def step_assert_secret_revealed(driver):
    driver.assert_api_key_secret_revealed()


@then("the key authenticates a sessionless request to the organisation's todos")
def step_assert_key_authenticates(driver):
    driver.assert_api_key_authenticates()


@when(parsers.parse('they revoke the API key "{name}"'))
def step_revoke_api_key(driver, name):
    driver.revoke_api_key(name)


@then("the key no longer authenticates sessionless requests")
def step_assert_key_rejected(driver):
    driver.assert_api_key_rejected()


@then("the key is rejected on the active organisation")
def step_assert_key_rejected_on_active_org(driver):
    driver.assert_api_key_rejected_on_active_org()


@when("they try to open the API keys page")
def step_try_open_api_keys_page(driver):
    driver.try_open_api_keys_page()
