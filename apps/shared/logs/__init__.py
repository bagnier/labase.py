"""The technical log subsystem — one cohesive package of focused modules.

The twin of :mod:`apps.shared.events` on the technical side: where that one carries *facts*
(what changed the domain, kept forever, transactional), this one carries *traces* (what the
machinery did, kept for a window, never on the critical path).

A line is written through ``chain`` — the single processor list where our ``structlog`` calls and
the libraries' stdlib ``logging`` meet, and the only place a tee may sit. From there it goes two
ways: to stdout, and into ``sink`` — the bounded queue, the background ``LogDrain`` and the day-file
fallback that together carry it to ``log_lines``, whose SQL lives in ``repository`` over the
``models`` mapping. An exception takes a third way at the same seam: ``capture`` folds it into an
``ExceptionCaptured`` and fans it out to whoever tracks issues, without shared ever naming them.

Two modules decide what a line *is worth* rather than where it goes. ``dependency`` judges a failed
call out of the process — the dependency answered no (ordinary, ``info``) or is broken (a bug) — and
``loop`` judges a failed tick inside it, so a background worker that stopped working opens one issue
instead of warning forever. Both are read all over the codebase; they are the fault vocabulary, not
plumbing.

``request`` is the ASGI middleware that writes the one line every served exchange leaves
(``request.finished``) and binds the correlation contextvars the rest of the chain reads.

This ``__init__`` re-exports **nothing** — the same rule as
:mod:`apps.shared.events`: everything is reached at its submodule path (``apps.shared.logs.chain`` /
``.sink`` / ``.capture`` / ``.repository`` / ``.dependency`` / ``.loop`` / ``.request``), so
importing one of them never drags in SQLAlchemy or the DB engine on another's behalf.
"""
