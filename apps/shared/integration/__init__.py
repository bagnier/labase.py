"""The mount surface — what an app's ``mount(host)`` touches, and nothing else does.

Every bounded context plugs itself in through exactly one call, and these four modules are what
that call reaches:

- ``host`` — the :class:`~apps.shared.integration.host.Host` handed to each ``mount``: it carries
  the FastAPI app, the event bus and the contribs registry, and it is where an app declares its
  routes, nav, settings, background workers and the events it owns.
- ``contribs`` — the *pull* half of inter-app collaboration. A host asks "who contributes to this
  query?" and aggregates the answers, isolating a failing provider so a down app cannot break the
  page that gathers it. The *push* half is a different animal on purpose and lives in
  :mod:`apps.shared.events`: a fact is durable, a contribution is best-effort.
- ``fullpage`` — the collector that composes a full HTML page's context from the slices each app
  registers here, namespaced by provider so no app can silently overwrite another's key.
- ``slugs`` — the one URL namespace: validation, the slugs a context reserves so no org handle can
  shadow them, and the cross-context uniqueness check.

They are one package because they are one moment. Each is reached by whoever is mounting, in the
window before the server starts serving, and their coupling runs between themselves rather than
outward — ``host`` reads ``contribs`` and ``slugs``, ``fullpage`` reads ``host``.

Not to be confused with each app's own ``contract/integration.py``, which is the *caller*: that
module holds one app's ``mount(host)``, this package holds what every such mount is written
against.
"""
