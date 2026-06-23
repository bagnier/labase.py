from apps.auth.tests.e2e import AuthBrowserMixin
from apps.files.tests.e2e import OrgFileBrowserMixin
from apps.learning.tests.e2e import LearningBrowserMixin
from apps.organizations.tests.e2e import OrgBrowserMixin
from apps.profile.tests.e2e import ProfileBrowserMixin
from apps.settings.tests.e2e import ConsoleBrowserMixin
from apps.todo.tests.e2e import TodoBrowserMixin
from tests.e2e.drivers.browser_base import BrowserBase


class BrowserDriver(
    AuthBrowserMixin,
    ConsoleBrowserMixin,
    ProfileBrowserMixin,
    TodoBrowserMixin,
    LearningBrowserMixin,
    OrgFileBrowserMixin,
    OrgBrowserMixin,
    BrowserBase,
):
    """Playwright e2e driver: feature mixins over the BrowserBase substrate."""
