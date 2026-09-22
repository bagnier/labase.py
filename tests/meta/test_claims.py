"""The guard over the registry: a claim is quoted from its document, and someone holds it.

``tests/meta/claims.py`` is a list of sentences AGENTS.md and the README make about this codebase,
each bound to the test that proves it — or to the reason none does yet. These tests are what make
that list cost something:

- a claim whose quote no longer occurs in exactly one of the two is a sentence someone reworded or
  wrote twice, and that is the decision this test forces into the open;
- a claim bound to nothing at all is neither held nor waived, which is the one state the registry
  does not allow;
- the number of unheld claims is written down, and only ever goes down.

AGENTS.md is what every agent working on the base reads, and the README the front door for people
who will never open `apps/`. Nothing else in the suite reads them, so until this file existed
every sentence in them was an assertion no run could contradict.
"""

import re

from tests.meta.claims import CLAIMS, UNHELD_TODAY
from tests.meta.readme import AGENTS, DOCUMENTS, normalised, stated


def test_every_claim_quotes_exactly_one_document_verbatim():
    """Whitespace-normalised, because the documents wrap their lines and a claim may span two. In
    exactly one of them: a sentence stated in both is a decision written twice, free to drift."""
    documents = [normalised(stated(document)) for document in DOCUMENTS]

    misplaced = sorted(
        claim.name
        for claim in CLAIMS
        if sum(normalised(claim.quote) in document for document in documents) != 1
    )

    assert misplaced == []


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
    reporter.write_line(f"\n{len(unheld)} claims nothing holds yet (tests/meta/claims.py)")
    if request.config.option.verbose > 0:
        for name in unheld:
            reporter.write_line(f"  {name}")

    assert len(unheld) == UNHELD_TODAY


def _principles_sentences() -> list[str]:
    """The sentences of AGENTS.md's Principles, headings aside — split where a sentence ends and
    the next begins with a capital, a code span or emphasis."""
    agents = AGENTS.read_text()
    start = agents.index("## Principles\n")
    end = agents.find("\n## ", start + 1)
    section = agents[start : end if end != -1 else len(agents)]
    prose = normalised(re.sub(r"^#+ .*$", "", section, flags=re.MULTILINE))
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z`*_])", prose) if s]


def test_every_principles_sentence_is_a_claim():
    """ "The principles below are mechanically verifiable" is only as true as the registry is
    complete: a Principles sentence no claim quotes moves no counter, so `UNHELD_TODAY` could
    reach zero while it stays unproven. Each one is quoted by a claim — held, or waived with its
    reason, and then counted."""
    quotes = [normalised(claim.quote) for claim in CLAIMS]

    unbound = [s for s in _principles_sentences() if not any(q in s for q in quotes)]

    assert unbound == []


def test_the_registry_is_populated():
    # Guards the guard: an empty registry would make every assertion above vacuously true.
    assert len(CLAIMS) > 8
