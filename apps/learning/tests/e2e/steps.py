import pytest
from pytest_bdd import given, parsers, then, when


@pytest.fixture(autouse=True)
def _reset_learning(driver):
    driver._reset_learning()
    yield


def _iso(fr_date: str) -> str:
    """'01/09/2024' -> '2024-09-01'."""
    day, month, year = fr_date.split("/")
    return f"{year}-{month}-{day}"


def _cards(datatable: list[list[str]]) -> list[dict]:
    headers = [h.strip() for h in datatable[0]]
    cards = []
    for raw in datatable[1:]:
        row = dict(zip(headers, [c.strip() for c in raw], strict=True))
        cards.append(
            {
                "external_id": row["ID"],
                "question": row["Question"],
                "answer": row["Answer"],
                "resource": row.get("Resource", ""),
            }
        )
    return cards


def _rows(datatable: list[list[str]]) -> list[dict]:
    headers = [h.strip() for h in datatable[0]]
    return [dict(zip(headers, [c.strip() for c in raw], strict=True)) for raw in datatable[1:]]


# ── Catalog & subscription ────────────────────────────────────────────────────


@given(parsers.parse('the deck "{name}" is made of the following cards:'))
def step_define_deck(driver, name, datatable):
    driver.define_deck(name, None, _cards(datatable))


@given(parsers.parse('the org has a learning deck "{name}" with {n:d} cards'))
def step_seed_org_deck(driver, name, n):
    driver.seed_org_deck(name, n)


@given(
    parsers.parse('the deck "{name}" with resource "{resource}" is made of the following cards:')
)
def step_define_deck_with_resource(driver, name, resource, datatable):
    driver.define_deck(name, resource, _cards(datatable))


@given(parsers.parse('"{name}" wants to learn the deck "{deck}"'))
def step_want_to_learn(driver, name, deck):
    driver.want_to_learn(name, deck)


# ── Clock ─────────────────────────────────────────────────────────────────────


@given(parsers.parse("the current date is {fr_date}"))
def step_set_date(clock, fr_date):
    clock.set_current_date(_iso(fr_date))


@given("one day passes")
@when("one day passes")
def step_one_day(clock):
    clock.advance_days(1)


@given(parsers.parse("{n:d} days pass"))
@when(parsers.parse("{n:d} days pass"))
def step_n_days(clock, n):
    clock.advance_days(n)


# ── Preset progress ───────────────────────────────────────────────────────────


@given(
    parsers.parse(
        '"{name}" has already reviewed the card "{ext}" at level {level:d} {days:d} days ago'
    )
)
def step_preset_card(driver, name, ext, level, days):
    driver.preset_card(name, ext, level, days)


@given(
    parsers.parse(
        '"{name}" has already reviewed the cards of the deck "{deck}" '
        "at level {level:d} {days:d} days ago"
    )
)
def step_preset_deck(driver, name, deck, level, days):
    driver.preset_deck(name, deck, level, days)


@given(parsers.parse('"{name}" has already reviewed the following cards:'))
def step_preset_table(driver, name, datatable):
    driver.preset_table(name, _rows(datatable))


# ── Session ───────────────────────────────────────────────────────────────────


@given(parsers.parse('"{name}" starts a review session'))
@when(parsers.parse('"{name}" starts a review session'))
def step_start_session(driver, name):
    driver.start_session(name)


@given(parsers.parse('"{name}" looks at today\'s cards'))
@when(parsers.parse('"{name}" looks at today\'s cards'))
@then(parsers.parse('"{name}" looks at today\'s cards'))
def step_look_today(driver, name):
    driver.look_today(name)


@given(parsers.parse('"{name}" sees the card "{ext}" asking the question "{question}"'))
@when(parsers.parse('"{name}" sees the card "{ext}" asking the question "{question}"'))
@then(parsers.parse('"{name}" sees the card "{ext}" asking the question "{question}"'))
def step_see_card(driver, name, ext, question):
    driver.assert_first_card(name, ext, question)


@given(parsers.parse('"{name}" reveals the answer of the card "{ext}" and sees "{answer}"'))
@when(parsers.parse('"{name}" reveals the answer of the card "{ext}" and sees "{answer}"'))
def step_reveal(driver, name, ext, answer):
    driver.reveal_answer(name, ext, answer)


@given(parsers.parse('"{name}" marks the card "{ext}" as learned'))
@when(parsers.parse('"{name}" marks the card "{ext}" as learned'))
def step_mark_learned(driver, name, ext):
    driver.mark(name, ext, "learned")


@given(parsers.parse('"{name}" marks the card "{ext}" as to review'))
@when(parsers.parse('"{name}" marks the card "{ext}" as to review'))
def step_mark_again(driver, name, ext):
    driver.mark(name, ext, "again")


@given(parsers.parse('"{name}" marks all today\'s cards as learned'))
@when(parsers.parse('"{name}" marks all today\'s cards as learned'))
def step_mark_all_learned(driver, name):
    driver.mark_all_learned(name)


# ── Assertions on session ─────────────────────────────────────────────────────


@given(parsers.parse('"{name}" sees {n:d} cards to learn'))
@when(parsers.parse('"{name}" sees {n:d} cards to learn'))
@then(parsers.parse('"{name}" sees {n:d} cards to learn'))
def step_assert_count(driver, name, n):
    driver.assert_due_count(name, n)


@then(parsers.parse('"{name}" sees no card to learn'))
def step_assert_no_card(driver, name):
    driver.assert_due_count(name, 0)


@then(parsers.parse('"{name}" sees the cards in this order:'))
def step_assert_order(driver, name, datatable):
    driver.assert_order(name, _rows(datatable))


# ── Resources ─────────────────────────────────────────────────────────────────


@given(parsers.parse('"{name}" looks at the resources to review'))
@when(parsers.parse('"{name}" looks at the resources to review'))
def step_look_resources(driver, name):
    driver.look_resources(name)


@then(parsers.parse('"{name}" sees the resources in this order:'))
def step_assert_resources(driver, name, datatable):
    driver.assert_resources(name, _rows(datatable))


@then(parsers.parse('"{name}" sees no resource'))
def step_assert_no_resources(driver, name):
    driver.assert_no_resources(name)


# ── Assertions on a card's schedule (acting user from context) ────────────────


@then(parsers.parse('the card "{ext}" is at level {level:d}'))
def step_assert_level(driver, ext, level):
    driver.assert_level(ext, level)


@then(parsers.parse('the last review of "{ext}" is set to today'))
def step_assert_last_review(driver, ext):
    driver.assert_last_review_today(ext)


@then(parsers.parse('the next review of "{ext}" is scheduled in {days:d} days'))
def step_assert_next_review(driver, ext, days):
    driver.assert_next_review_in(ext, days)
