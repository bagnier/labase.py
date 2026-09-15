---
name: refactor-python
description: >
  Reshapes Python code across several files at once — renaming, moving, splitting, inlining —
  computed by rope over the whole project and checked against the references a search would miss,
  instead of retyping the change in every file it reaches.

  Do NOT use for: reading code for smells and dead abstractions (refactor-code), or reshaping
  vault notes (refactor-notes).
when_to_use: >
  Judge from the shape of the work, not from the words of the request. Reach for it as soon as one
  structural change to Python code has to land in more than one file — renaming a symbol used
  elsewhere, moving a function or class to another module, splitting a module that carries two
  subjects, inlining a definition back into its call sites. A plan whose steps read "the same edit
  here, then there, then there" is this skill instead of those edits. A change confined to one
  file is ordinary editing and needs nothing from here. Also on "/refactor-python".
allowed-tools: Bash(uv run:*), Bash(ruff:*), Bash(git status:*)
---

Six operations, one script, **chained as many times as the work needs**. Never hand-edit across
files for any of them: a multi-file Edit sweep for a rename or a move is the failure this skill
exists to replace, and a restructuring made of eight such changes is eight calls here, not a
reason to fall back to editing by hand.

```sh
uv run --script "${CLAUDE_SKILL_DIR}/refactor.py" <operation> [flags]
```

Run it from the project root, or pass `--project <root>`. It writes nothing without `--apply`.
Each call costs a fraction of a second on a project of a few hundred files.

## Which operation

| intent                                          | command                                                              |
| ----------------------------------------------- | -------------------------------------------------------------------- |
| a symbol takes a new name                       | `rename --file F --symbol OLD --to NEW`                              |
| a variable or function disappears into its uses | `inline --file F --symbol NAME`                                      |
| lines become a method                           | `extract-method --file F --lines 27-31 --name NEW`                   |
| an expression becomes a name                    | `extract-variable --file F --line 56 --expr '<verbatim>' --name NEW` |
| a function or class changes module              | `move-symbol --file F --symbol NAME --to DEST.py`                    |
| a module changes folder                         | `move-module --module M.py --to DEST/`                               |

No offsets, no columns: the script finds the definition from the name. When a name is defined
twice in the file it says so and asks for `--line`.

The two `extract-*` operations cannot reach past the file they run in. They belong to a sequence —
extract, then move what you extracted — not to a lone one-file edit, which is ordinary editing.

`change-signature`, `restructure` and `use-function` exist in rope and are **not** wired here.
Don't invent flags for them.

## A restructuring is a sequence, not a batch

Each call opens the project from disk, so **step N must be applied before step N+1 is computed**.
There is no plan to accumulate and commit at the end — apply as you go. Three rules make the
sequence come out right:

- **A move changes where the symbol lives.** Anything else you planned on that symbol happens
  *before* the move, or its `--file` is the new path afterwards.
- **Rename before extracting around it**, so the extracted code is written against the final name.
- **Format and test once, at the end** of the whole sequence — not after every step.

A three-step restructuring reads like this, and each step sees the one before it:

```sh
uv run --script "${CLAUDE_SKILL_DIR}/refactor.py" --apply \
  rename --file src/pkg/core.py --symbol compute --to double
uv run --script "${CLAUDE_SKILL_DIR}/refactor.py" --apply \
  move-symbol --file src/pkg/core.py --symbol double --to src/pkg/maths.py
uv run --script "${CLAUDE_SKILL_DIR}/refactor.py" --apply \
  inline --file src/pkg/maths.py --symbol scaled          # note: the new file
```

Keep the path quoted every time rather than holding it in a variable — the skill directory
contains a space in some projects, and an unquoted expansion splits it.

Dry-run a step first whenever its change set is not obvious — a rename or a move over code you
have not read. A local extraction you can apply straight away.

## Reading the result

Every call prints the change set, the diff, and one coverage line. That line is the point of the
tool:

- `every file mentioning X is in the change set` → go.
- `N file(s) mention X and were not changed` → open each one. A local variable or a word in prose
  sharing the name is expected and correct; a real call site there is a miss.
- `coverage: not checked` → the change cannot reach another file by construction (an extraction,
  or a symbol local to a function). Nothing to verify.
- `left behind: 'X' survives in strings` → rope renames code, never text. Prose in a docstring
  usually means the common noun and stays; an `__all__` entry or a `getattr` key is a reference
  that will break at import time, and it is yours to edit.
- `STOP` → nothing was applied and the exit code is 1. Either the source folders printed at the
  top don't cover the project, or the remaining references are dynamic — a string, a `getattr`,
  an entry point. In the second case `--force` applies the rest, and those call sites are yours
  to edit by hand.

Work on a clean tree (`git status`) so the whole sequence stays revertable as one.

Three refusals happen before any refactoring is computed, and each names what to fix rather than
letting rope produce something obscure downstream:

- **an unparsable module anywhere under the source folders.** rope parses them all, and a single
  broken file makes every operation fail with a message about *that* file. The script names the
  offenders up front: fix them, or move them out of the source folders it printed.
- **a name collision** — renaming onto a name already bound at module level, moving a symbol into
  a module that already defines it, moving a module into a folder that already holds one by that
  name. rope does not refuse those; it edits the wrong thing.
- **an unwritable file in the change set.** rope writes file by file, so a permission error
  half-way leaves the project inconsistent. Nothing is applied.

## What the diff will show

- `rename` leaves docstrings and comments alone. `--docs` rewrites them too, and mangles any
  sentence that merely uses the word — reach for it only when the name is a term of art.
- `move-symbol` rewrites importers as `import pkg.dest` plus a qualified call, and eats the blank
  lines around the import block. `extract-method` omits the blank line before the new def. Both
  are why the formatter runs at the end: `ruff check --fix . && ruff format .` when the project
  uses ruff, otherwise its own.
- `extract-method` refuses a region with more than one `return`, and says so in one line. Pick a
  region that is statements, not a whole branch.
- A `warning: Unknown node type` names a construct rope could not reconstruct: read that hunk
  before applying.

## The rope pin

The script pins a git SHA in its own PEP 723 header, because the PyPI release predates PEP 695
(`type X = ...`, `class C[T]`) and warns on every such file. `uv run` resolves it and caches it;
nothing is installed into the project.

To move the pin: the `# **Upcoming release**` section of rope's CHANGELOG is the queue, and
`gh api repos/python-rope/rope/commits/<sha>/check-runs` is the gate — take a commit with no
check outside `success`. When that section becomes a release, the git URL goes back to `rope>=`.
The script refuses to run on a build without PEP 695 support; `rope.VERSION` cannot tell them
apart, so don't check the version string.
