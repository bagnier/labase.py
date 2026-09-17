"""Every app's authorization rules (see ``tests/authorization.py``)."""

from apps.api_keys.tests.rules import API_KEYS
from apps.learning.tests.rules import LEARNING
from apps.organizations.tests.rules import ORGANIZATIONS
from apps.pages.tests.rules import PAGES

BOOKS = [API_KEYS, LEARNING, ORGANIZATIONS, PAGES]
