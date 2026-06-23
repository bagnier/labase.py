from pytest_bdd import scenarios

from . import steps  # noqa: F401

# Ensure step definitions are imported so pytest-bdd can discover them.
# Importing for side-effects; keep noqa to avoid unused-import lint error.

scenarios("../../../../features/files.feature")
