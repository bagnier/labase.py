"""Profile's settings dependency — the request's effective values; profile routes carry no
``{org_handle}``, so this resolves to the server values (no org override can apply)."""

from typing import Annotated

from fastapi import Depends

from apps.organizations.contract.current import app_settings
from apps.shared.settings.live import SettingsView

ProfileSettings = Annotated[SettingsView, Depends(app_settings("profile"))]
