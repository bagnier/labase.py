"""Studio deep links — the console's knowledge, exported for apps that surface one.

The Load screen links its database stats into Studio; routing that through this contract keeps
one place deciding what a Studio URL is (and when there is none to link to).
"""

from apps.console.domain.studio import studio_base_url, studio_link

__all__ = ["studio_base_url", "studio_link"]
