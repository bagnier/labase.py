"""A fullpage provider is claimed once per name.

Two apps registering under the same name used to boot fine and collide on every render —
the second provider's keys silently overwriting the first's in ``fullpage_context`` (a
``page.overwrite`` line, last writer wins). The collision belongs at startup, next to the
other collision-rejecting registrations (``events.declare``, ``events.on``), not at request
time.
"""

import pytest

from apps.shared.integration.host import Host


async def _provide(query: object) -> dict:
    return {}


def test_register_fullpage_provider_rejects_a_duplicate_name():
    host = Host()
    host.register_fullpage_provider("profile", _provide)

    with pytest.raises(ValueError, match="profile"):
        host.register_fullpage_provider("profile", _provide)
