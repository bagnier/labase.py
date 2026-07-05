from apps.api_keys.tests.e2e import ApiKeysApiMixin
from apps.auth.tests.e2e import AuthApiMixin
from apps.calendar.tests.e2e import CalendarApiMixin
from apps.files.tests.e2e import OrgFileApiMixin
from apps.learning.tests.e2e import LearningApiMixin
from apps.organizations.tests.e2e import OrgApiMixin
from apps.pages.tests.e2e import PagesApiMixin
from apps.profile.tests.e2e import ProfileApiMixin
from apps.settings.tests.e2e import ConsoleApiMixin
from apps.todo.tests.e2e import TodoApiMixin
from tests.e2e.drivers.api_base import ApiBase


class ApiDriver(
    AuthApiMixin,
    ApiKeysApiMixin,
    ConsoleApiMixin,
    ProfileApiMixin,
    TodoApiMixin,
    LearningApiMixin,
    OrgFileApiMixin,
    PagesApiMixin,
    CalendarApiMixin,
    OrgApiMixin,
    ApiBase,
):
    """In-process API driver: feature mixins over the ApiBase substrate."""
