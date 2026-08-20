"""Every value the code reads, split by the one thing that separates them: lifetime.

Two kinds of setting, and knowing which one you want is the whole of choosing a module:

- ``env`` — read **once**, from the environment (``.env``), and cached for the life of the
  process. DB URLs, SMTP credentials, poll intervals, cache TTLs. Changing one means a restart,
  which is exactly right for a value a deployment owns. ``preflight`` is its gate: it refuses a
  production boot whose ``env`` would serve traffic on development defaults.
- ``live`` — declared by each app at its ``mount()``, stored in Postgres, editable from the console
  and reloaded without a restart, per app and overridable per org. The ``enabled`` switch a
  toggleable app checks is just one of these.

They used to be called ``config`` and ``settings``, two words for the same thing that said nothing
about which was which. The path says it now: ``settings.env`` versus ``settings.live``.

``store`` is ``live``'s own persistence — the tables and the mount-time CRUD, kept here rather than
under ``persistence/`` because it is nobody else's business.

A contract never exports a settings handle, and there are three sanctioned reads of ``live``,
chosen by *how the org is known* — see :mod:`apps.shared.settings.live` for the rule.

This ``__init__`` re-exports **nothing**, the same rule as :mod:`apps.shared.events` and
:mod:`apps.shared.logs`: reaching ``settings.env`` must not drag SQLAlchemy in on the other's
behalf.
"""
