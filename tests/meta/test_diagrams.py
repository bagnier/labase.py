"""The two chains the README draws, compared with the wiring they claim to picture.

A diagram is the most quoted part of this README and the least checkable: prose can be reasoned
about line by line, an ASCII drawing is read once, believed, and never revisited. Both chains here
are *fan-outs* — one event, one query, five apps — which is the shape that decays quietly: a
seeder deleted with its app leaves a box in the picture, a seeder added leaves the picture short,
and nothing anywhere disagrees.

So the drawing is parsed and compared with the registrations. What is asserted is set equality in
both directions: the diagram is neither a subset (a seeder nobody drew) nor a superset (a box
nothing implements) of what the app actually mounts.
"""

import ast
import re
from pathlib import Path

import apps.main  # noqa: F401  — mounting every app registers the seeders and the overviews
from apps.organizations.contract.events import OrganizationCreated
from apps.shared.events.wiring import wiring
from tests.meta.readme import diagram_containing

_APPS = Path(__file__).resolve().parents[2] / "apps"


def _drawn_seeders() -> set[str]:
    """The apps the sign-up diagram draws under the listener, one per ``→ name:`` box.

    Only the part below the listener line: above it the same arrow draws the chain itself
    (``→ organizations: creates personal org``), which is the emitter, not a seeder. Boxes sit two
    to a line, so the split is what separates them rather than a line anchor.
    """
    chain = diagram_containing("fans OrgCreated out")
    _, _, seeders = chain.partition("each seeder")
    return set(re.findall(r"→ (\w+):", seeders))


def _drawn_overviews() -> set[str]:
    """The apps the dashboard diagram lists as answering the query."""
    listed = re.search(
        r"^\s+← ([\w, ]+) each return an Overview",
        diagram_containing("OverviewQuery"),
        re.MULTILINE,
    )
    assert listed is not None, "the dashboard diagram no longer lists its contributors"
    return {name.strip() for name in listed.group(1).split(",")}


def _apps_naming(query: str) -> set[str]:
    """Every context whose mount names ``query`` — read as a symbol, so ``ConsoleOverviewQuery``
    does not answer for ``OverviewQuery``."""
    found = set()
    for integration in sorted(_APPS.glob("*/contract/integration.py")):
        tree = ast.parse(integration.read_text())
        if any(isinstance(node, ast.Name) and node.id == query for node in ast.walk(tree)):
            found.add(integration.parts[-3])
    return found


def test_the_signup_diagram_draws_every_welcome_seeder():
    """The chain the README puts front and centre. Its seeders are durable async consumers of
    ``OrgCreated``, registered at mount — so the wiring knows them by app, and the picture can be
    held to that list rather than to whoever last edited the paragraph."""
    seeding = {reaction.app for reaction in wiring.consumers_of(OrganizationCreated)}

    assert _drawn_seeders() == seeding


def test_the_dashboard_diagram_lists_every_contributor():
    """Same shape, the pull side: an app that stops answering `OverviewQuery` loses its card, and
    the dashboard renders one short without failing — the contribs registry logs and skips."""
    assert _drawn_overviews() == _apps_naming("OverviewQuery")
