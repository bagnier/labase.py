"""Composition root for cross-app seeding.

Auto-discovers every context exposing a ``contract/seed.py`` with a module-level
``seed`` hook and subscribes it to ``org.created``. No central list: dropping a
new ``app/<ctx>/contract/seed.py`` is enough to participate. Seeders stay pure
``OrgCreatedHook`` functions, ignorant of who emits the event.
"""

import importlib
import importlib.util
import pkgutil

import app
from app.organizations.contract.hooks import register_org_created

_SEED_MODULE = "{ctx}.contract.seed"


def register_seeders() -> None:
    for info in pkgutil.iter_modules(app.__path__, prefix="app."):
        name = _SEED_MODULE.format(ctx=info.name)
        try:
            found = importlib.util.find_spec(name) is not None
        except ModuleNotFoundError:
            found = False  # context has no contract/ package
        if not found:
            continue
        register_org_created(importlib.import_module(name).seed)
