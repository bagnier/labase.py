from behave import given, then, when

from features.steps.common import get_client, run


@given("the app is running")
def step_app_running(context):
    context.client = get_client()


@when('I GET "{path}"')
def step_get(context, path):
    context.response = run(context.client.get(path))


@when('I GET "{path}" without auth')
def step_get_no_auth(context, path):
    context.response = run(context.client.get(path))


@when('I POST "{path}" with form data:')
def step_post_form(context, path):
    data = {row["field"]: row["value"] for row in context.table}
    context.response = run(context.client.post(path, data=data))


@then("the response status is {code:d}")
def step_status(context, code):
    assert context.response.status_code == code, (
        f"Expected {code}, got {context.response.status_code}\n{context.response.text[:500]}"
    )


@then('the response contains "{text}"')
def step_contains(context, text):
    assert text in context.response.text, (
        f"'{text}' not found in response:\n{context.response.text[:500]}"
    )
