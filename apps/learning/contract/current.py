"""Learning's settings dependency — the request's effective values (server ⊕ current-org
overrides), resolved fresh per request; see
:func:`apps.organizations.contract.current.app_settings`."""

from typing import Annotated

from fastapi import Depends

from apps.organizations.contract.current import app_settings
from apps.shared.settings import SettingsView

LearningSettings = Annotated[SettingsView, Depends(app_settings("learning"))]
