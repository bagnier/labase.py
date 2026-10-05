"""Full-page provider collisions are refused at mount: same name, same namespaced key
(``org_nav``+``extra`` and ``org``+``nav_extra``), or a key the context seeds itself."""

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
