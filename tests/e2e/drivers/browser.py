from app.auth.tests.e2e import AuthBrowserMixin
from app.console.tests.e2e import ConsoleBrowserMixin
from app.files.tests.e2e import OrgFileBrowserMixin
from app.learning.tests.e2e import LearningBrowserMixin
from app.organizations.tests.e2e import OrgBrowserMixin
from app.profile.tests.e2e import ProfileBrowserMixin
from app.todo.tests.e2e import TodoBrowserMixin
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
