"""Public's settings dependency — the request's effective values; public routes carry no
``{org_handle}`` (and are mostly anonymous), so this resolves to the server values."""

from typing import Annotated

from fastapi import Depends

from apps.organizations.contract.current import app_settings
from apps.shared.settings.live import SettingsView

PublicSettings = Annotated[SettingsView, Depends(app_settings("public"))]
