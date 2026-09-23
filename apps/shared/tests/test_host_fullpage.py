"""A fullpage provider's keys are claimed once, by name and by the namespaced key itself.

Two apps registering under the same name used to boot fine and collide on every render —
the second provider's keys silently overwriting the first's in ``fullpage_context`` (a
``page.overwrite`` line, last writer wins). Two different names can still collide on the
namespaced key they produce (``org_nav`` returning ``extra`` and ``org`` returning
``nav_extra`` both land on ``org_nav_extra``), and a provider can collide with the keys
``fullpage_context`` seeds itself (``user``, ``nav_items``). Every one of these belongs at
startup, next to ``events.on``'s duplicate-topic check, not found as a ``page.overwrite`` log
line in production.
"""

import pytest

from apps.shared.integration.host import Host


async def _provide(query: object) -> dict:
    return {}


def test_register_fullpage_provider_rejects_a_duplicate_name():
    host = Host()
    host.register_fullpage_provider("profile", ["handle"], _provide)

    with pytest.raises(ValueError, match="profile"):
        host.register_fullpage_provider("profile", ["handle"], _provide)


def test_register_fullpage_provider_rejects_a_key_collision_across_two_names():
    host = Host()
    host.register_fullpage_provider("org_nav", ["extra"], _provide)

    with pytest.raises(ValueError, match="org_nav_extra"):
        host.register_fullpage_provider("org", ["nav_extra"], _provide)


def test_register_fullpage_provider_rejects_a_key_colliding_with_the_seeded_context():
    host = Host()

    with pytest.raises(ValueError, match="nav_items"):
        host.register_fullpage_provider("nav", ["items"], _provide)
