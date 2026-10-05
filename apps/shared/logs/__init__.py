"""Technical logs (AGENTS: facts, traces, bugs: three records).

- ``chain``: the one processor list where structlog and stdlib ``logging`` meet.
- ``sink``: the queue and drain carrying lines to ``log_lines`` (``repository``, ``models``),
  with a day-file fallback.
- ``capture``: turns ``log.exception`` into issues.
- ``dependency`` and ``loop``: decide what a failed call or a failed tick is worth.
- ``request``: the middleware writing ``request.finished`` and binding the correlation ids.

Nothing is re-exported, so importing one module never pulls in SQLAlchemy for another.
"""
