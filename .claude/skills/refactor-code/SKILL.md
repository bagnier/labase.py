---
name: refactor-code
description: >
  Reads existing code for what no linter reports — design smells, dead abstractions, weak
  types, deprecated calls — and returns each finding with its evidence and a verdict.

  Do NOT use for: reshaping vault notes (/refactor-notes), or re-running the project's own
  formatter, linter and type checker, which its gate already does.
when_to_use: >
  The user says "refactor", "nettoie ce code", "clean up", "code smells", "code mort",
  "/refactor-code" — or asks for a hygiene pass over a file, a module or a repo.
---

**You are not a linter. You are the developer who inherits this code and has to change it.**
A linter is already installed, runs in a second, and never needed a model to run it. What it
cannot do is read a file and understand what it *means* — that these three parameters are an
address, that this class knows too much about that one, that this hook was built for a caller
nobody ever wrote. That reading is the whole of this skill, and it is judgment: which is why
every finding below carries its evidence and its cost rather than a rule number.

Run the project's gate once (`make check`, `just lint`, `npm run lint`, the pre-commit
config). What it reports is its job, not yours: give it one line and move on. **This skill is
what green misses** — the smells no rule encodes, read by a model that understands what the
code means.

**Install nothing.** The sweep's only commands are that gate, `git` and `grep`: a finder you
had to add is a finder nobody runs again next month, and a second complexity meter beside the
project's own buys nothing but an argument over whose threshold is right. Which makes the
config the project already runs the first thing you read, before a line of code —
`[tool.ruff.lint]`, the `eslintrc`, whatever it keeps. It answers two questions at once:

- **which smells are already ruled**, and are therefore not findings. A private-access rule
  selected and the gate green means nobody reaches into another object's internals; going to
  look anyway is the whole failure this skill exists to avoid.
- **where the ceilings sit** — and that is where the eye earns its keep. `max-args = 6` makes
  a five-argument signature invisible; `max-complexity = 11` keeps a ten-branch knot green. A
  ceiling is not a verdict, it is the line under which only reading finds anything.

Three things hold that reading honest, and they replace the linter's rigour:

- **A declared perimeter.** Name the files you will read, read them whole, and say so in the
  report. You cannot claim exhaustiveness by tool any more; you claim coverage by perimeter.
  A repo too big to read is a perimeter to negotiate, not a sweep to fake.
- **Evidence, never the label.** "These three parameters travel together through four
  signatures" is a finding; "Data Clumps" is a catalogue entry. The label files it, the
  observation proves it. No observation, no finding.
- **A verdict per finding**, one of three:
  - **fix** — local, reversible, no surface moves. Apply it.
  - **propose** — changes a design, a public API, a stored format. Write it up, do not apply.
  - **leave** — the smell is real and the cure costs more. Name the cure and what makes it
    expensive, in the detail a *fix* would carry; a named non-finding is worth more than a
    silent one. A leave you can argue for without having worked out what the fix would be is a
    skip wearing a verdict's clothes — and it reads exactly like the real thing, including to
    you, because it is written in this file's own vocabulary.

And one filter over all of it: **name what the smell costs** — the change it makes expensive,
the bug it invites. A smell whose cost you cannot name is a taste, and taste does not go in
the report.

## Sniff code smells

The families are from [refactoring.guru](https://refactoring.guru/refactoring/smells); what
follows is not their definition but the *tell* — what it looks like in real code — and the
verdict it usually earns.

### Bloaters

- **Long Method** — the body needs a comment to introduce each paragraph, or the name carries
  an "and". → *fix* when a paragraph extracts as a pure move (one output, no re-entry into
  the locals); *propose* when the extraction needs new state.
- **Large Class** — two groups of fields with no method touching both. → *propose*.
- **Primitive Obsession** — the same validation on a `str` in three places; a `dict[str, Any]`
  whose keys are known and fixed; constants standing in for a closed set. → *propose*.
- **Long Parameter List** — the signatures sitting just under the config's ceiling, and any
  boolean parameter at all: a flag that splits the body in two is two functions. → *fix* the
  flag split, *propose* the parameter object.
- **Data Clumps** — the same two or three names, in the same order, across several signatures,
  or always assigned together. → *propose*.
- **Complexity** — the number is a map, not a verdict, and the functions worth reading are the
  ones just under the ceiling. The tell is nesting that mixes levels — a business rule wrapped
  around an I/O retry. → *fix* the flattening (guard clauses, early returns); *propose* the
  rest.

### Object-Orientation Abusers

- **Alternative Classes with Different Interfaces** — two classes the caller switches on,
  whose methods do the same thing under different names. → *propose*; align the names first,
  that part is cheap and reversible.
- **Refused Bequest** — an override that raises `NotImplementedError`, returns `None`, or is
  empty; a subclass using a tenth of its base. → *propose* composition.
- **Switch Statements** — a single exhaustive match on a closed enum is good code, not a
  smell. The tell is *repetition*: the same dispatch on the same type in three places. →
  *propose* polymorphism at the third occurrence, not the first.
- **Temporary Field** — a field written by one method, read by one other, null the rest of the
  time. → *fix* into a parameter or a local when both live in the same class; *propose* when
  it crosses a boundary.

### Change Preventers

These two are read in the history, not in the file:

- **Divergent Change** — `git log --format=%s -- <file>` and read the verbs: two unrelated
  reasons to change the same file. → *propose* the split.
- **Shotgun Surgery** — the inverse. `git log --name-only -20` and look for the file cluster
  that keeps recurring under one intent. → *propose*.

### Dispensables

- **Comments** — enumerate them with the language's tokenizer, not a `#` grep, which invents
  them inside strings and misses the trailing ones. Then three questions, and the last two are
  where the findings are. Does it narrate the lines? → *fix*: cut it. **Is it still true?** —
  what rots is what points outside its own file, and it rots silently, a dead claim reading
  exactly like a live one; open what it names, and "probably" is → *fix*: delete. **What would
  deleting it lose?** — that has to land where it cannot drift: a name, else a type, else a
  test, an ordering or a cross-file invariant holding in no name and having been prose only
  for want of a test. What survives is the *why* — the alternative rejected, the source of a
  magic value. Never touch licence headers, shebangs or tool directives carrying their reason;
  every docstring that isn't published output is in scope, stale claims hide there too.
- **Duplicate Code** — rule of three, and never unify two blocks that merely look alike: if
  they change for different reasons, duplication is cheaper than the wrong abstraction →
  *leave*, and say so. Two exceptions worth taking at the second occurrence: byte-identical
  bodies in sibling classes under an existing base (a hoist, not an abstraction), and an
  inverse pair (`encode`/`decode`, `merge`/`remove`) sharing a *classification* — extract the
  table, leave the leaves. → *fix*.
- **Data Class** — a record type is fine; the tell is that every caller runs the same
  computation over its fields. → *propose* moving the behaviour in.
- **Dead Code** — before deleting, grep the whole repo for the name **including non-code
  files** (templates, YAML, CI, docs) and excluding vendored copies. Nothing is dead if it is
  reached by name rather than by call: `getattr`/`importlib`, string dispatch, entry points,
  framework hooks, `__all__` re-exports, a class path in a config, a CLI subcommand. A
  library's public API unused *in this repo* proves nothing → *leave*. Otherwise → *fix*,
  git is the archive. Commented-out code is dead code.
- **Lazy Class** — one field and one method, or a wrapper that adds nothing. → *fix*: inline.
- **Speculative Generality** — one implementation of an interface, one caller of a hook, a
  parameter always passed the same value, anything justified by "for when we need to". →
  *fix*: delete.

### Couplers

- **Feature Envy** — a method whose body names another object's fields more often than its
  own. → *fix* when it is a private helper, *propose* the move otherwise.
- **Inappropriate Intimacy** — the per-object half is ruled wherever a private-access rule is
  selected; what stays yours is the module-level version, two modules reaching into each
  other's internals with nothing private in sight. → *propose*.
- **Message Chains** — `a.b().c().d()`. Fluent and builder APIs are chains by design, not
  smells → *leave* those. The tell is a chain across *ownership* boundaries. → *propose*.
- **Circular imports** — the workaround is the evidence: an import inside a function body, or
  a `TYPE_CHECKING` guard whose only purpose is to break the cycle. A config that ignores the
  deferred-import rule has traded the cycle for silence — read what that ignore covers. A
  cycle is a layering error. → *propose*.

## Hunt deprecations

The dependency audit is not yours: `deptry`, `pip-audit` and their equivalents are verdict
machines — binary, nothing to judge per hit — and they belong in the gate, where this project
already keeps them. If a version gap surfaces anyway, weigh its *cost* (a major behind is a
migration to schedule, a patch behind is noise) and report the bump, never apply it: an
upgrade changes behaviour, the rest of this pass does not.

What the auditors cannot see:

- **Deprecated API calls** — the tell is a warning the suite already emits and swallows. Run
  it once with deprecations promoted to errors (`-W error::DeprecationWarning`). A deprecated
  call behind one abstraction is a contained → *fix*; the same call spread across the
  codebase is a → *propose*.
- **The project's own deprecations** — a `@deprecated` marker or a "legacy" comment with live
  callers is a migration nobody finished. Name the callers; that count is the finding.
- **A wrapper working around a library's API** — a local `utils` whose whole body patches what
  the library does is usually a version behind, and the bump deletes the wrapper. Read it here
  rather than as a coupling smell: the finding is the gap, not the indirection.

## Track types

Type coverage is mechanical, but what it hides is not.

- **Lack of types** — where the annotations stop matters more than how many are missing:
  untyped boundaries (public API, I/O, deserialisation) with a typed interior means the types
  guard nothing. → *fix* the boundary first.
- **Weak types** — `Any`, `object`, `dict[str, Any]`, and `| None` that spreads. A `| None`
  forcing a check at every call site is a design finding, not a typing one — the null is the
  smell. A `dict[str, Any]` crossing three functions is a Data Clump: route it above.
- **Silenced violations** — `# noqa`, `# type: ignore`, `eslint-disable` with no code and no
  reason. → *fix*: narrow it to the specific rule and give it its reason on the same line, or
  remove it and see what it was hiding — often enough, a real bug. Never add a bare one.

## Suggest corrections

One entry per finding, and nothing in it is optional:

- **where** — `file:line`;
- **what** — the observation, in the code's own terms;
- **what it costs** — the change it makes expensive, the bug it invites;
- **the verdict** — fix, propose, leave.

Then apply the fixes and write up the proposals — **never in the same diff**. A refactor that
carries a design change is unreviewable, and the design change is the one that needed the
review.

Close on the perimeter: which files were read whole, and which were not.

## Suggest disciplined linting

The run's second product, and the one that outlives it — but always a rule in the config the
project already runs, never a new tool. Most of what you just read has no rule at all; that is
why it had to be read. The rest maps onto families the config can simply select:

| what you found                            | what would have caught it            |
| ----------------------------------------- | ------------------------------------ |
| reaching into another object's internals  | `SLF`                                |
| commented-out code                        | `ERA`                                |
| an argument nobody reads                  | `ARG`                                |
| a bare `# noqa` / `# type: ignore`        | `PGH`                                |
| an import buried in a function body       | `PLC0415`                            |
| a superseded idiom                        | `UP`                                 |
| a layer importing upwards                 | `banned-api` (flake8-tidy-imports)   |
| a knot, a signature, a class too wide     | `C901`, `PLR0913`, `PLR0912`         |

The names are ruff's; every ecosystem carries the same families under other spellings.

Three moves, and the last two are worth more than the first:

- **select a family the config lacks** — but run it once before proposing it. A family that
  returns forty hits is not a gate, it is a whitelist file waiting to be born, and a whitelist
  file is a second codebase that rots. Zero hits is not automatically a yes either: a family
  guarding a dependency the project doesn't have is noise in a config someone has to read.
  Select it where the project could plausibly grow the mistake. Verdict machines only.
- **ratchet a ceiling down.** A ceiling is set where the code stood, not where it should be.
  Once the sweep removes what held it up, lower it to just above the worst survivor and update
  its comment to name the new holder — otherwise the comment is a lie, and the next sweep
  reads a line nobody chose.
- **audit the suppressions.** Every entry in an `ignore` or a `per-file-ignores` list is a
  claim about the codebase — true the day it was written, re-checked by nobody since. Suspend
  them and count: `ruff check --config 'lint.per-file-ignores = {}' --select <rule> <path>`,
  or the equivalent flag elsewhere — but **prove the suspension took, on a rule you know
  fires, before trusting a zero.** The analogous `--config 'lint.ignore = []'` is silently
  disregarded (ruff 0.16.3), and answers *no hits* for every entry in the global list: a clean
  bill of health that retires live suppressions wholesale. `--extend-select <rule>` is what
  re-arms one there, CLI selection outranking a file's `ignore`. Retire the ones now at zero,
  and on the survivors read the stated reason against the actual hits — an ignore whose
  comment no longer describes what it covers is the finding, and it is usually covering
  something else by now. Cheapest yield of the sweep, and the only move that removes room to
  drift rather than adding a rule.

The test config belongs here too, for the same reason and at the same price — no new
dependency, and each line turns a section above into a gate: deprecations promoted to errors,
strict markers so a typo'd `@mark.xfial` cannot silently do nothing, and `xfail_strict`,
without which a recorded bug that gets fixed stays green and says nothing.
