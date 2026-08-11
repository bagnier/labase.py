---
name: analyse
description: >
  Deep study of a subject that loads it into context instead of writing it out — read
  widely, say nothing but that it is done.

  Do NOT use for: opening a subject without digging into it (/lets-talk), or producing a
  report, note or artifact someone else will read.
when_to_use: >
  The user says "analyse", "creuse", "étudie", "documente-toi sur", "prends connaissance
  de", "familiarise-toi avec", "deep dive", "/analyse" — or wants you up to speed on a
  subject before the real conversation starts.
disallowed-tools: Edit, Write, NotebookEdit, TodoWrite, Artifact
---

The deliverable is a state, not a text: knowing the subject well enough to answer anything
about it later.

## Dig, don't sample

Long is normal here — this is where the budget goes.

- Primary sources: open the file, the commit, the page. Not what something says *about* it.
- Follow one hop past what the material points at — reference, import, linked page. That
  hop is usually where the non-obvious part sits.
- Stop when the sources start repeating each other, not when you have enough to reply.
- Two sources disagreeing is a finding: keep both, and which you trust.

## Read it yourself

No delegating the reading. A subagent returns a summary and its context dies with it — the
detail needed on the seventh turn is exactly what its report dropped. Delegate *locating*
(a broad sweep, "where does X live"), never consuming. Same on the web: search locates,
`fetch` reads — not `WebFetch`, which delegates the reading to a small model: this very
failure, one layer down.

## Say nothing, write nothing

The write tools are gone from the pool for the turn; `Bash` is not — so no command that
changes anything either, and no scratch file. The findings live in context, nowhere else.

No commentary between two reads either, and no recap of what was just read: that is the
dump. Something broken surfacing does not get fixed.

The analysis ends on one line: `✅ analysis done`. What comes after is the ordinary
conversation, and none of this skill's business.
