"""Profile's settings: server values, as profile routes carry no ``{org_handle}``."""

from typing import Annotated

from fastapi import Depends

from apps.organizations.contract.current import app_settings
from apps.shared.settings.live import SettingsView

ProfileSettings = Annotated[SettingsView, Depends(app_settings("profile"))]
