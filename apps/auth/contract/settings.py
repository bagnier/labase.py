"""Auth's settings dependency — the server-wide ``users`` settings for a request.

``users`` settings are server-wide auth policy (session TTL, 2FA, passkeys, OAuth switches):
they carry no org dimension, and their consumers (auth's own routes, profile's) never run
under ``/{org_handle}``. So this resolves the plain server view via :func:`get_settings` — no
org overlay is ever applicable, and, crucially, **no dependency on the organizations context**.
Routing it through organizations' ``app_settings`` would invert the layering (auth is a
foundation organizations builds on) and close an identity↔org import cycle.
"""

from typing import Annotated

from fastapi import Depends

from apps.shared.settings import SettingsView, get_settings


def _users_settings() -> SettingsView:
    return get_settings("users").view()


UsersSettings = Annotated[SettingsView, Depends(_users_settings)]
