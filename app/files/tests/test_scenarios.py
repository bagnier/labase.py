from app.files.tests import steps  # noqa: F401

from pytest_bdd import scenarios

scenarios("../../../features/files.feature")
