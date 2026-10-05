"""Public's settings: server values, as public routes carry no ``{org_handle}``."""

from typing import Annotated

from fastapi import Depends

from apps.organizations.contract.current import app_settings
from apps.shared.settings.live import SettingsView

PublicSettings = Annotated[SettingsView, Depends(app_settings("public"))]
