"""Settings, split by lifetime (AGENTS: no magic number).

- ``env``: technical, read once from the environment at boot; ``preflight`` refuses a production
  boot on development defaults.
- ``live``: declared by each app at mount, stored in Postgres (``store``), edited from the console,
  reloaded without restart, overridable per org.

Nothing is re-exported, so importing ``env`` never pulls in SQLAlchemy.
"""
