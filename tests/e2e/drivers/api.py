from app.auth.tests.e2e import AuthApiMixin
from app.console.tests.e2e import ConsoleApiMixin
from app.files.tests.e2e import OrgFileApiMixin
from app.learning.tests.e2e import LearningApiMixin
from app.organizations.tests.e2e import OrgApiMixin
from app.profile.tests.e2e import ProfileApiMixin
from app.todo.tests.e2e import TodoApiMixin
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
