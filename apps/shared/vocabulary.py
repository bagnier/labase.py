"""String types every app surface uses."""

type AppName = str
"""A context's package name under ``apps/`` (``"todo"``): it prefixes the app's event kinds and
keys its settings, console tile and dashboard card."""

type PhosphorIcon = str
"""A `Phosphor <https://phosphoricons.com/>`_ icon name, ``"clipboard-text"``. Each app declares
its own icons; nothing shared maps apps to icons."""
