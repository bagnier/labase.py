from pytest_bdd import scenarios

from . import steps  # noqa: F401

# Importing steps for side-effects so pytest-bdd discovers them.
scenarios("../../../../features/pages.feature")
