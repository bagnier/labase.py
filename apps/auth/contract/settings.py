"""The ``users`` settings for a request: server-wide auth policy (session TTL, 2FA, passkeys,
OAuth), with no org overlay. Not through organizations' ``app_settings``: auth must not import
the context built on it.
"""

from typing import Annotated

from fastapi import Depends

from apps.shared.settings.live import SettingsView, get_settings


def _users_settings() -> SettingsView:
    return get_settings("users").view()


UsersSettings = Annotated[SettingsView, Depends(_users_settings)]
