"""The two fan-out diagrams in AGENTS.md, parsed and compared both ways with what is mounted."""

import re

import apps.main  # noqa: F401 — registers the seeders and overviews
from apps.organizations.contract.events import OrganizationCreated
from apps.organizations.contract.overviews import OverviewQuery
from apps.shared.events.wiring import wiring
from apps.shared.integration.contribs import contribs
from tests.meta.readme import diagram_containing


def _drawn_seeders() -> set[str]:
    """The ``→ name:`` boxes below the listener line (above it is the emitter), two per line."""
    chain = diagram_containing("fans OrgCreated out")
    _, _, seeders = chain.partition("each seeder")
    return set(re.findall(r"→ (\w+):", seeders))


def _drawn_overviews() -> set[str]:
    listed = re.search(
        r"^\s+← ([\w, ]+) each return an Overview",
        diagram_containing("OverviewQuery"),
        re.MULTILINE,
    )
    assert listed is not None, "the dashboard diagram no longer lists its contributors"
    return {name.strip() for name in listed.group(1).split(",")}


def test_the_signup_diagram_draws_every_welcome_seeder():
    seeding = {reaction.app for reaction in wiring.consumers_of(OrganizationCreated)}

    assert _drawn_seeders() == seeding


def test_the_dashboard_diagram_lists_every_contributor():
    """Read from the mounted registry, not the source."""
    contributing = {
        provider.__module__.split(".")[1] for provider in contribs.providers(OverviewQuery)
    }

    assert _drawn_overviews() == contributing
