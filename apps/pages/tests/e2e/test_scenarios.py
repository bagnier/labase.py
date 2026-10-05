from pytest_bdd import scenarios

from . import steps  # noqa: F401

# Imported for pytest-bdd to discover the steps.
scenarios("../../../../features/pages.feature")
scenarios("../../../../features/page-nav.feature")
