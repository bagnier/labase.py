"""Every app's authorization rules (see ``tests/authorization.py``)."""

from apps.api_keys.tests.rules import API_KEYS
from apps.files.tests.rules import FILES
from apps.learning.tests.rules import LEARNING
from apps.organizations.tests.rules import ORGANIZATIONS
from apps.pages.tests.rules import PAGES

BOOKS = [API_KEYS, FILES, LEARNING, ORGANIZATIONS, PAGES]
