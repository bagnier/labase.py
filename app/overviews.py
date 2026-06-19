"""Composition root for dashboard overviews.

Auto-discovers every context exposing a ``contract/overview.py`` with a module-level
``overview`` coroutine and registers it on the org dashboard. No central list: dropping a
new ``app/<ctx>/contract/overview.py`` is enough to participate. Providers stay pure
``OverviewProvider`` functions, ignorant of the dashboard that renders them.
"""

import importlib
import importlib.util
import pkgutil

import app
from app.organizations.contract.overviews import register_overview

_OVERVIEW_MODULE = "{ctx}.contract.overview"


def register_overviews() -> None:
    for info in pkgutil.iter_modules(app.__path__, prefix="app."):
        name = _OVERVIEW_MODULE.format(ctx=info.name)
        try:
            found = importlib.util.find_spec(name) is not None
        except ModuleNotFoundError:
            found = False  # context has no contract/ package
        if not found:
            continue
        register_overview(info.name.removeprefix("app."), importlib.import_module(name).overview)
