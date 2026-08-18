"""The two string vocabularies every app surface spells out, named once so no field repeats them."""

type AppName = str
"""A bounded context's id — its package name under ``apps/`` (``"todo"``, ``"files"``).

The same spelling identifies the app on every surface: it prefixes the event kinds it owns
(``todo.created``), keys its settings group, its console tile and its dashboard card. An app is
therefore findable from any of them by that one string.
"""

type PhosphorIcon = str
"""A `Phosphor <https://phosphoricons.com/>`_ icon name, as the templates render it — ``"circle"``,
``"clipboard-text"``.

Each app carries the icons it shows on the surfaces it contributes, so nothing shared ever holds a
table mapping an app to its icon.
"""
