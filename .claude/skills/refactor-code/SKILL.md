---
name: refactor-code
description: >
  Six-axis hygiene sweep over existing code, each axis driven by a finder rather than by
  eye: formatters and linters, dead code, code smells, naming, comments, dependencies.

  Do NOT use for: reshaping vault notes (/refactor-notes).
when_to_use: >
  The user says "refactor", "refactoring discipliné", "nettoie ce code", "clean up",
  "code smells", "code mort", "dead code", "renommage", "audit des dépendances",
  "/refactor-code" — or asks for a hygiene pass over a file, a module or a repo.
---

Run all six axes, not the one that looks most promising. Each is tool-driven: run the
finder, then judge its output — never scan by eye and call it exhaustive.

Pin every finder to the project's own runtime (`uvx --python 3.14 vulture …`): on a version
it cannot parse, a finder drops the file **silently** and still exits with a normal-looking
list. Read its stderr and its file count before believing it.

A path argument scopes what you change — never the greps that verify a finding, which stay
repo-wide.

## 0. Read the gate before running anything

Open whatever the project runs as its gate — a `make`/`just` target, `.pre-commit-config.yaml`,
a CI workflow, a `package.json` script — and list the tools already in it. Those axes are
*already ratcheted*: run them once to confirm they still pass, give them one line, and spend
the sweep's attention on the axes nobody guards. A repo with a formatter, a linter and a type
checker in its gate returns nothing on axes 1, 2 and 5 every single time; rediscovering that
is not a finding, it is five-sixths of the run.

Which reframes what the sweep is *for*. Its product is not the diff — it is the answer to
*which finder should join the gate*. Sort them by what they return:

- **verdicts** — `deptry`, `pip-audit`, `cargo audit`, `npm audit`. Binary, near-zero false
  positives, no judgment per hit. Propose these for the gate. A network-bound one (any
  advisory scanner) gets its own target, so the gate stays offline and fast.
- **advisories** — `vulture`, `lizard`, `jscpd`, `knip`. Every hit needs a human. These stay
  sweep-only: in a gate they either fail the build on noise, or grow a whitelist file, which
  is a second codebase that rots.

Pin an advisory you keep as a dev dependency anyway — a finder that silently resolves to a
new version between sweeps has no baseline, and its heuristics move.

## Reporting

Close with a count per axis, including the axes that found nothing — each **over its
denominator**: `0 findings / 23 files scanned`, not `0 findings`. A finder that found nothing
and a finder that scanned nothing print the same `0`, and mistaking the second for the first
is the exact failure this skill exists to prevent. Say which axes were already gated.

## 1. Formatters & linters

Run what the project already configures — `pyproject` `[tool.*]`, `package.json` scripts,
`.pre-commit-config.yaml`. The type checker (`ty`, `mypy`, `tsc`) is part of this axis — it is
often the only one of the three with anything to say. Auto-fix, then read the diff:
`ruff --fix` and `eslint --fix` occasionally rewrite semantics.

Check what the formatter's file count actually *covers*, and compare it against the linter's —
a gap between them is real. Modern formatters reach past source files (ruff formats Python
blocks inside Markdown). A formatter with write access to generated output, fixtures, or a
catalogue that gets distributed elsewhere is a supply-chain path, not a style preference:
scope it, and prefer a format-only exclusion so the linter keeps read access.

Adding a tool or enabling new rules is a config change, not part of the sweep. One exception:
a **ceiling the config itself declares provisional** (`max-complexity`, a coverage floor)
should be ratcheted down once the sweep removes what held it up — and its comment updated to
name the new holder, or it becomes a lie.

Never silence a finding with a bare `# noqa` / `eslint-disable` / `# type: ignore`; a
suppression that is genuinely right carries its reason on the same line.

If the formatting diff is non-empty, keep it in its own commit and add its SHA to
`.git-blame-ignore-revs` so blame survives the churn.

## 2. Dead code

Finders: `vulture` and `ruff check --select F401,F841,ERA001` (Python), `knip` / `ts-prune`
(TS/JS), `cargo-udeps` (Rust), `deadcode` (Go), plus the coverage report in any language. On
a decorator-heavy codebase (CLI commands, ORM models, framework hooks), start vulture at
`--min-confidence 100` — lower, it reports the whole registry.

Before deleting a candidate, grep the whole repo for its name **including non-code files**
(templates, YAML/JSON configs, CI, docs) and **excluding worktrees and vendored copies**,
whose duplicate hits make a dead symbol look alive. Finders miss everything reached by name
rather than by call: `getattr`/`importlib`, string dispatch tables, plugin and entry-point
registries, DI containers, framework hooks (fixtures, lifecycle methods, signal receivers),
`__all__` re-exports, a class path in a config, a CLI subcommand.

For a library's public API, "unused in this repo" proves nothing — leave it. Same for a
config file whose only consumer is an external tool (an editor, a CI runner): its caller is
outside the repo by design, so silence here is not evidence.

A run of members from one ordered set flagged together (three of five enum values, say) is
almost never dead — it is a scale with unused rungs, and usually a **documentation** finding:
the option exists in code and is missing from the manifest/API the docs publish. Route it to
axis 4, do not delete.

An abstraction, hook or config option with a single caller and no second one in sight belongs
to this axis: it is a deletion, not a refactor.

Commented-out code is dead code: delete it, git is the archive.

## 3. Code smells

Finders: one complexity meter — `ruff check --select C901,B,SIM` (Python) or `lizard` (any
language) — plus `jscpd` for copy-paste. Do not stack several: they disagree on the metric
*and* on the threshold, and arbitrating between them produces nothing. If the project already
configures one, that is the meter; a second one only buys an argument you cannot win.

Duplication is what they over-report: rule of three, and never unify two blocks that merely
*look* alike — if they change for different reasons, duplication is cheaper than the wrong
abstraction. Two exceptions worth taking at two occurrences, not three:

- byte-identical method bodies in sibling classes under a common base — that is a hoist, not
  an abstraction, and the base already exists;
- an inverse pair (`merge`/`remove`, `encode`/`decode`) that share a *classification* — the
  table of which key is a set, a map, a scalar. The leaves differ; the table must not drift
  between them, so extract the table and leave the leaves alone.

If the report is dominated by test fixtures, say so and leave them: collapsing them into a
`conftest.py` is a test refactor, not a hygiene pass.

## 4. Naming

Two finders, and the second is where the findings are.

- A verb histogram —
  `grep -rhoE '^\s*(def|function) _?[a-z_]+' src | sed -E 's/.*(def|function) _?//; s/_.*//' | sort | uniq -c | sort -rn`
  — surfacing competing families (`fetch`/`get`/`load`, `user`/`account`/`member`). Strip the
  leading `_` as shown, or every private collapses into one meaningless blank row.
- The **documented vocabulary against the code's**: the nouns and verbs in the README, the
  `--help` output and the published API, versus the model fields, enum members and CLI verbs
  that implement them. A histogram reads signatures only, and the naming that actually carries
  a project lives in its prose — a manifest field the code has and the docs don't is a naming
  finding.

Converge families before polishing individual names: pick the dominant word, rename all of it.
A half-done rename is worse than none.

Rename with a symbol-aware tool (IDE/LSP) when there is one. Without one, a token-exact
replace is safe exactly when the token is **globally unique** — prove that with a repo-wide
grep first, then use a word-boundary pattern (`\bold_name\b`, never a bare `sed s/old/new/`)
and verify with the type checker and the suite. Either way, grep the string form afterwards
for what neither can see: docs, templates, string literals, CLI flags, serialised keys, and
**test function names**, where the leading `test_` eats the word boundary and leaves
`test_old_name_does_x` silently behind.

Propose instead of applying when the rename reaches a public API, a CLI surface or a stored
format (DB column, JSON key) — that one is a migration. Tool availability is not the gate;
token ambiguity is.

## 5. Comments

Grep for the mechanical cases first: commented-out code, `TODO`/`FIXME` with no owner or
issue, docstrings that repeat the signature (`:param path: the path`). Placeholder text inside
scaffolding and fixtures will match those greps — check what the hit is *in* before counting
it.

Then, per comment: would it still be true after the block is rewritten? Then it is intent —
keep it. Does it narrate the lines below? Cut it, or make the code say it. What survives is
the *why*: the alternative rejected, the source of a magic value, an ordering constraint the
caller cannot see, the ticket behind a workaround.

A trailing comment enumerating a closed set of string values is a type waiting to happen —
report it, do not convert it here; that is a design change, not hygiene.

Never touch licence headers, shebangs and encoding lines, tool directives (`# fmt: off`,
`# noqa: E501 — reason`, `prettier-ignore`, `@ts-expect-error`) with their reason, or
docstrings that generate `--help` output or published docs.

## 6. Dependencies

`deptry` (Python), `depcheck` / `knip` (JS/TS), `cargo-udeps` (Rust) for the two mismatches:
declared but never imported (remove), imported but never declared (you are riding someone
else's transitive dependency — declare it). Check the import-name mapping before believing
either: a package whose module name differs from its distribution name (`pyyaml`→`yaml`,
`beautifulsoup4`→`bs4`, `Pillow`→`PIL`) gets reported as **both** mismatches at once, and that
pair is one false positive, not two findings.

Check the finder's root too — these tools scan a package directory, so a `tests/` tree passed
as a second argument may report `0` because it scanned nothing.

Then `pip-audit` / `npm audit` / `cargo audit` / `osv-scanner` for vulnerable ones. On a uv or
poetry project the auditor has no environment to read, so feed it the resolved set:

```sh
uv export --no-hashes --all-groups --no-emit-project | pip-audit --no-deps -r /dev/stdin
```

Report version **bumps**, do not apply them: an upgrade changes behaviour, the rest of the
sweep does not. Adding or removing a dependency is the different case — it is the direct fix
for what the finder just reported, so propose it, and pin it exactly as its neighbours are
pinned. What stays banned is regenerating the lockfile wholesale; recording one deliberate
add is not that churn.
