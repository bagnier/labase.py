from apps.auth.tests.e2e import AuthApiMixin
from apps.files.tests.e2e import OrgFileApiMixin
from apps.learning.tests.e2e import LearningApiMixin
from apps.organizations.tests.e2e import OrgApiMixin
from apps.profile.tests.e2e import ProfileApiMixin
from apps.settings.tests.e2e import ConsoleApiMixin
from apps.todo.tests.e2e import TodoApiMixin
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
