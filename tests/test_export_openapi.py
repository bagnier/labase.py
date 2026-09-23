"""`make client-gen` must describe every app, whatever a deployment's live settings currently
leave switched off — mount() reads the persisted ``enabled`` switch once at import (see
tests/e2e/cleanup.py), so a disabled app would otherwise silently drop its routes from the
generated client (README: "the OpenAPI schema is a full description of the app").
"""

from apps.shared.settings.store import BOOL_FALSE, BOOL_TRUE, ENABLED_KEY
from scripts.export_openapi import force_all_apps_enabled


def test_force_all_apps_enabled_overrides_a_disabled_apps_persisted_value():
    wrapped = force_all_apps_enabled(lambda app: {ENABLED_KEY: BOOL_FALSE})

    assert wrapped("some_app") == {ENABLED_KEY: BOOL_TRUE}
