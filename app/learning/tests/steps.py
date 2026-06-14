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
                "answer": row["Réponse"],
                "resource": row.get("Ressource", ""),
            }
        )
    return cards


def _rows(datatable: list[list[str]]) -> list[dict]:
    headers = [h.strip() for h in datatable[0]]
    return [dict(zip(headers, [c.strip() for c in raw], strict=True)) for raw in datatable[1:]]


# ── Catalog & subscription ────────────────────────────────────────────────────


@given(parsers.parse('le paquet "{name}" constitué des cartes suivantes :'))
def step_define_deck(driver, name, datatable):
    driver.define_deck(name, None, _cards(datatable))


@given(
    parsers.parse(
        'le paquet "{name}" à la resource "{resource}" est constitué des cartes suivantes :'
    )
)
def step_define_deck_with_resource(driver, name, resource, datatable):
    driver.define_deck(name, resource, _cards(datatable))


@given(parsers.parse('"{name}" veut apprendre le paquet "{deck}"'))
def step_want_to_learn(driver, name, deck):
    driver.want_to_learn(name, deck)


# ── Clock ─────────────────────────────────────────────────────────────────────


@given(parsers.parse("la date du jour est le {fr_date}"))
def step_set_date(driver, fr_date):
    driver.set_current_date(_iso(fr_date))


@given("un jour passe")
@when("un jour passe")
def step_one_day(driver):
    driver.advance_days(1)


@given(parsers.parse("{n:d} jours passent"))
@when(parsers.parse("{n:d} jours passent"))
def step_n_days(driver, n):
    driver.advance_days(n)


# ── Preset progress ───────────────────────────────────────────────────────────


@given(
    parsers.parse(
        '"{name}" a déjà revue la carte "{ext}" au niveau {level:d} il y a {days:d} jours'
    )
)
def step_preset_card(driver, name, ext, level, days):
    driver.preset_card(name, ext, level, days)


@given(
    parsers.parse(
        '"{name}" a déjà revue les cartes du paquet "{deck}" '
        "au niveau {level:d} il y a {days:d} jours"
    )
)
def step_preset_deck(driver, name, deck, level, days):
    driver.preset_deck(name, deck, level, days)


@given(parsers.parse('"{name}" a déjà revue les cartes suivantes:'))
def step_preset_table(driver, name, datatable):
    driver.preset_table(name, _rows(datatable))


# ── Session ───────────────────────────────────────────────────────────────────


@given(parsers.parse('"{name}" commence une session de révision'))
@when(parsers.parse('"{name}" commence une session de révision'))
def step_start_session(driver, name):
    driver.start_session(name)


@given(parsers.parse('"{name}" regarde les cartes du jour'))
@when(parsers.parse('"{name}" regarde les cartes du jour'))
@then(parsers.parse('"{name}" regarde les cartes du jour'))
def step_look_today(driver, name):
    driver.look_today(name)


@given(parsers.parse('"{name}" voit la carte "{ext}" posant la question "{question}"'))
@when(parsers.parse('"{name}" voit la carte "{ext}" posant la question "{question}"'))
@then(parsers.parse('"{name}" voit la carte "{ext}" posant la question "{question}"'))
def step_see_card(driver, name, ext, question):
    driver.assert_first_card(name, ext, question)


@given(parsers.parse('"{name}" consulte la réponse de la carte "{ext}" et voit "{answer}"'))
@when(parsers.parse('"{name}" consulte la réponse de la carte "{ext}" et voit "{answer}"'))
def step_reveal(driver, name, ext, answer):
    driver.reveal_answer(name, ext, answer)


@given(parsers.parse('"{name}" marque la carte "{ext}" comme apprise'))
@when(parsers.parse('"{name}" marque la carte "{ext}" comme apprise'))
def step_mark_learned(driver, name, ext):
    driver.mark(name, ext, "learned")


@given(parsers.parse('"{name}" marque la carte "{ext}" comme à revoir'))
@when(parsers.parse('"{name}" marque la carte "{ext}" comme à revoir'))
def step_mark_again(driver, name, ext):
    driver.mark(name, ext, "again")


@given(parsers.parse('"{name}" marque toutes les cartes du jour comme apprises'))
@when(parsers.parse('"{name}" marque toutes les cartes du jour comme apprises'))
def step_mark_all_learned(driver, name):
    driver.mark_all_learned(name)


# ── Assertions on session ─────────────────────────────────────────────────────


@given(parsers.parse('"{name}" voit {n:d} cartes à apprendre'))
@when(parsers.parse('"{name}" voit {n:d} cartes à apprendre'))
@then(parsers.parse('"{name}" voit {n:d} cartes à apprendre'))
def step_assert_count(driver, name, n):
    driver.assert_due_count(name, n)


@then(parsers.parse('"{name}" ne voit pas de carte à apprendre'))
def step_assert_no_card(driver, name):
    driver.assert_due_count(name, 0)


@then(parsers.parse('"{name}" voit les cartes dans l\'ordre suivant :'))
def step_assert_order(driver, name, datatable):
    driver.assert_order(name, _rows(datatable))


# ── Resources ─────────────────────────────────────────────────────────────────


@given(parsers.parse('"{name}" regarde les ressources à revoir'))
@when(parsers.parse('"{name}" regarde les ressources à revoir'))
def step_look_resources(driver, name):
    driver.look_resources(name)


@then(parsers.parse('"{name}" voit les ressources dans cet ordre:'))
def step_assert_resources(driver, name, datatable):
    driver.assert_resources(name, _rows(datatable))


@then(parsers.parse('"{name}" ne voit aucune ressource'))
def step_assert_no_resources(driver, name):
    driver.assert_no_resources(name)


# ── Assertions on a card's schedule (acting user from context) ────────────────


@then(parsers.parse('la carte "{ext}" est au niveau {level:d}'))
def step_assert_level(driver, ext, level):
    driver.assert_level(ext, level)


@then(parsers.parse('la dernière révision de "{ext}" est fixée à aujourd\'hui'))
def step_assert_last_review(driver, ext):
    driver.assert_last_review_today(ext)


@then(parsers.parse('la prochaine révision de "{ext}" est programmée dans {days:d} jours'))
def step_assert_next_review(driver, ext, days):
    driver.assert_next_review_in(ext, days)
