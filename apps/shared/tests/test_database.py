import apps.main
from apps.shared.persistence.database import dispose_engines


def test_the_composed_app_disposes_its_connection_pools_on_shutdown():
    handlers = apps.main.host.app.router.on_shutdown

    assert dispose_engines in handlers
