"""What an app's ``mount(host)`` is written against (AGENTS: an app declares every surface it
contributes).

- ``host``: the :class:`~apps.shared.integration.host.Host` each ``mount`` receives.
- ``contribs``: the pull registry; the push side is :mod:`apps.shared.events`.
- ``fullpage``: composes a full page's context from the slices apps register.
- ``slugs``: the URL namespace, its reserved slugs and cross-context uniqueness.

Each app's own ``contract/integration.py`` holds its ``mount``, the caller of this package.
"""
