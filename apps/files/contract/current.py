"""Files' settings for the request; see :func:`apps.organizations.contract.current.app_settings`."""

from typing import Annotated

from fastapi import Depends

from apps.organizations.contract.current import app_settings
from apps.shared.settings.live import SettingsView

FilesSettings = Annotated[SettingsView, Depends(app_settings("files"))]
