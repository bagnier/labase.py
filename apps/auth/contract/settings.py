"""Auth's settings dependency — the request's effective ``users`` settings.

Lives in its own module rather than ``current.py``: the :func:`app_settings` factory
(organizations' contract) itself depends on ``current.py``'s ``OptionalCurrentUser`` /
``RlsSession``, so hosting this alias there would make the two modules import each other.
``current.py`` stays a leaf; routers (auth's own, profile's) import ``UsersSettings`` here.
"""

from typing import Annotated

from fastapi import Depends

from apps.organizations.contract.current import app_settings
from apps.shared.settings import SettingsView

UsersSettings = Annotated[SettingsView, Depends(app_settings("users"))]
