from app.auth.tests.driver_mixin import AuthBrowserMixin
from app.console.tests.driver_mixin import ConsoleBrowserMixin
from app.files.tests.driver_mixin import OrgFileBrowserMixin
from app.learning.tests.driver_mixin import LearningBrowserMixin
from app.organizations.tests.driver_mixin import OrgBrowserMixin
from app.profile.tests.driver_mixin import ProfileBrowserMixin
from app.todo.tests.driver_mixin import TodoBrowserMixin
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
