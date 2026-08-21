"""The guard over the registry: a claim is quoted from the README, and someone holds it.

``tests/meta/claims.py`` is a list of sentences the README makes about this codebase, each bound
to the test that proves it — or to the reason none does yet. These four tests are what make that
list cost something:

- a claim whose quote no longer occurs in the README is a sentence someone reworded, and the
  rewording is the decision this test forces into the open;
- a claim bound to nothing at all is neither held nor waived, which is the one state the registry
  does not allow;
- the number of unheld claims is written down, and only ever goes down.

The README is the product's front door and the only document read by people who will never open
`apps/`. Nothing else in the suite reads it, so until this file existed every sentence in it was
an assertion no run could contradict.
"""

from tests.meta.claims import CLAIMS, UNHELD_TODAY
from tests.meta.readme import README, normalised


def test_every_claim_quotes_the_readme_verbatim():
    """Whitespace-normalised, because the README wraps its lines and a claim may span two."""
    readme = normalised(README.read_text())

    stale = sorted(claim.name for claim in CLAIMS if normalised(claim.quote) not in readme)

    assert stale == []


def test_every_claim_is_either_held_or_waived():
    """The registry's only forbidden state: a sentence listed as a claim and then forgotten."""
    undecided = sorted(claim.name for claim in CLAIMS if not (claim.held_by or claim.waiver))

    assert undecided == []


def test_every_holder_is_a_test():
    """A claim held by a helper is held by nothing — the helper runs only if a test calls it."""
    not_tests = sorted(
        f"{claim.name} → {holder.__module__}.{holder.__name__}"
        for claim in CLAIMS
        for holder in claim.held_by
        if not holder.__name__.startswith("test_")
    )

    assert not_tests == []


def test_claim_names_are_unique():
    names = [claim.name for claim in CLAIMS]

    assert sorted(set(names)) == sorted(names)


def test_the_unheld_claims_are_the_backlog(request):
    """The one number this package exists to lower.

    Written through pytest's own reporter rather than ``print``: the count is worth a line on
    every run, and ``-v`` spells out which claims it covers — a backlog nobody can read is a
    backlog nobody works.
    """
    unheld = sorted(claim.name for claim in CLAIMS if not claim.held_by)
    reporter = request.config.pluginmanager.getplugin("terminalreporter")
    reporter.write_line(f"\n{len(unheld)} README claims nothing holds yet (tests/meta/claims.py)")
    if request.config.option.verbose > 0:
        for name in unheld:
            reporter.write_line(f"  {name}")

    assert len(unheld) == UNHELD_TODAY


def test_the_registry_is_populated():
    # Guards the guard: an empty registry would make every assertion above vacuously true.
    assert len(CLAIMS) > 8
