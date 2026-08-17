---
name: lsp-rename
description: >
  Renames a Python symbol and every use of it through pyright's language server, following
  imports and `contract/` re-exports that a textual replace misses.

  Do NOT use for: extract, inline or any other refactoring — no Python server here offers them.
when_to_use: >
  Renaming a function, class, method or variable used in more than one place — the user says
  "renomme", "rename", "change le nom de", "/lsp-rename". Also before a rename done by hand, to
  see the real list of sites.
---


## Why a script rather than the LSP tool

The built-in `LSP` tool exposes nine read-only operations. `rename` is not among them, and the
issue asking for it is open with no answer. The protocol serves it; only the tool does not.


## Call it

```sh
uv run .claude/skills/lsp-rename/rename.py <file> <line> <column> <new-name>
uv run .claude/skills/lsp-rename/rename.py apps/auth/infra/user_repository.py 17 7 AdminStatus --dry-run
```

Line and column are 1-based, as an editor shows them and as the `LSP` tool takes them. Point at
the symbol's definition; `LSP goToDefinition` finds it when you only hold a use site.

Files are rewritten in place. `--dry-run` lists the sites and writes nothing — worth a first pass
when the symbol crosses several modules.


## Two measured facts it encodes

> [!warning] Never `ty` for this
> Its providers beat pyright's and it is faster, but on this repo it under-applies every rename
> crossing a `contract/` re-export: 17 symbols out of 17, silently. On `find_user_id_by_email`
> it reports 13 references and rewrites 3. Its `references` are right; its rename is not.

A cold pyright under-reports. Asked straight after `didOpen`, a rename answers from a partial
index — 2 edits where the warm answer is 6. pyright emits no progress notification, so the script
waits for the first diagnostics on the document, the only readiness signal it gives, then still
requires two consecutive answers to agree. A run costs about 0.6s.


## What it does not do

No extract, no inline, no organize-imports — pyright serves zero code actions, and the servers
that do (jedi, rope) fail to parse six files of `apps/` on 3.14 syntax. A rename is the whole
scope.

> [!warning] Save your buffers first
> It reads and writes files on disk. An editor holding unsaved changes computes the rename from
> stale content and is left with a stale buffer over rewritten files.

It renames the symbol, not the concept. Untouched:

- docstrings, comments and strings
- Markdown and other prose
- the DB columns or API fields a class may mirror

→ read the diff before committing.
