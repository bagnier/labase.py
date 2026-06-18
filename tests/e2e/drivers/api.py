from app.auth.tests.driver_mixin import AuthApiMixin
from app.console.tests.driver_mixin import ConsoleApiMixin
from app.files.tests.driver_mixin import OrgFileApiMixin
from app.learning.tests.driver_mixin import LearningApiMixin
from app.organizations.tests.driver_mixin import OrgApiMixin
from app.profile.tests.driver_mixin import ProfileApiMixin
from app.todo.tests.driver_mixin import TodoApiMixin
from tests.e2e.drivers.api_base import ApiBase


class ApiDriver(
    AuthApiMixin,
    ConsoleApiMixin,
    ProfileApiMixin,
    TodoApiMixin,
    LearningApiMixin,
    OrgFileApiMixin,
    OrgApiMixin,
    ApiBase,
):
    """In-process API driver: feature mixins over the ApiBase substrate."""
