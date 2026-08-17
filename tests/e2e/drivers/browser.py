from apps.api_keys.tests.e2e import ApiKeysBrowserMixin
from apps.auth.tests.e2e import AuthBrowserMixin
from apps.calendar.tests.e2e import CalendarBrowserMixin
from apps.console.tests.e2e import ConsoleBrowserMixin
from apps.files.tests.e2e import OrgFileBrowserMixin
from apps.issues.tests.e2e import IssuesBrowserMixin
from apps.learning.tests.e2e import LearningBrowserMixin
from apps.metrics.tests.e2e import MetricsBrowserMixin
from apps.organizations.tests.e2e import OrgBrowserMixin
from apps.pages.tests.e2e import PagesBrowserMixin
from apps.profile.tests.e2e import ProfileBrowserMixin
from apps.timeline.tests.e2e import TimelineBrowserMixin
from apps.todo.tests.e2e import TodoBrowserMixin
from tests.e2e.drivers.browser_base import BrowserBase


class BrowserDriver(
    AuthBrowserMixin,
    ApiKeysBrowserMixin,
    IssuesBrowserMixin,
    MetricsBrowserMixin,
    TimelineBrowserMixin,
    ConsoleBrowserMixin,
    ProfileBrowserMixin,
    TodoBrowserMixin,
    LearningBrowserMixin,
    OrgFileBrowserMixin,
    PagesBrowserMixin,
    CalendarBrowserMixin,
    OrgBrowserMixin,
    BrowserBase,
):
    """Playwright e2e driver: feature mixins over the BrowserBase substrate."""
