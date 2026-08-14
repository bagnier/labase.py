---
name: write-tests
description: >
  Writes and edits automated tests so they read as a spec and cannot flake: one behaviour
  per test, one equality assertion over the whole expected value, arrange/act/assert on
  their own lines, and time, env and filesystem pinned by the test itself. Governs the test
  code itself, including the one written at each red step of a tdd loop.

  Do NOT use for: manually exercising a running app (exploration-testing).
when_to_use: >
  The user asks to write, add, fix, split, un-flake or update a test, a test file, a
  fixture or a test suite — "écris un test", "ajoute des tests", "corrige ce test",
  "ce test est flaky", "/write-tests". Also alongside tdd, whose loop stops at the test's
  content.
---

## Pick one behaviour

One test covers one behaviour at the seam — the public contract something actually calls,
never an internal method and never a collaborator's return value. Choose the next case with
**ZOMBIES**: Zero → One → Many → Boundaries (min/max, off-by-one) → Interfaces (the contract
with collaborators) → Exceptions (error paths) → Simple (plainest case first, complexity
only once that one is green). A case the seam doesn't need yet is a test to delete later.

Name it scenario → expectation, as a clause: `test_push_skips_a_both_sides_divergence`,
`it('rejects a duplicate email')` — never `test_push_2`, never the method under test. The
list of names is the spec: read it back and it should state what the code promises, without
opening a single body.

Adding to an existing file, read those names first. A case they already cover, re-entered
from another angle, is one behaviour to maintain in two places.

## Assert equality

One `==` against the whole expected value. `in`, `not in`, `>`, `is not None`, `len(x) == 3`
and bare `assert x` pass for reasons that have nothing to do with the behaviour, and their
failure prints no expected side to read.

```python
assert "resynced" in out                      # passes on "nothing resynced", on another
                                              # charm's line, on a warning quoting the word
assert out.splitlines() == ["↻ house  claude-md  resynced"]
```

Too big to compare whole → **project, then compare equal**; never fall back on membership.

- the fields under test: `assert (result.status, result.name) == ("resynced", "house")`
- the lines that matter: `assert [l for l in out.splitlines() if l.startswith("  ")] == [...]`
- an order that isn't part of the contract: sort both sides, `assert sorted(names) == ["a", "b"]`

Five membership assertions in a row are one equality assertion written badly — everything
they don't name is free to drift, silently.

A value the test doesn't own (a tmp path, a timestamp, a generated id) is not a reason to
weaken the assertion: pin it (see _Control time, env, filesystem_) or substitute it out,
then compare equal. `in` survives only for genuinely unbounded text — a traceback, a
`--help` dump — and then on a distinctive anchor, never on a common word.

Two things are never the expected side. A double's own record — `mock.assert_called_once_with(...)`
asserts on your test double, stays green while the production path is broken, and fails
describing the mock; fake the collaborator, then compare the state or the value it produced
with `==`. And the implementation's own expression — `assert add(a, b) == a + b` passes by
construction, whatever `add` does.

## One statement per step

Arrange, act, assert: one statement per line, in that order, and no `# Arrange` comment
labelling them — the sequence reads without labels. The act is a statement of its own, and
its result gets a name.

```python
# no
assert push_charm_to_project(trove_root, registry_path, "myapp", "house").status == "resynced"

# yes
_make_claude_md(trove_root, "house", "house v2")
add_project(registry_path, "myapp", project_path)
result = push_charm_to_project(trove_root, registry_path, "myapp", "house")
assert result.status == "resynced"
```

- an expected failure is still one act: `with pytest.raises(X) as err:` around the call
  alone, the assertion on `err.value` after the block.
- arrangement past ~3 lines → a `_make_*` helper or a fixture. The body is a spec, not a
  construction site.
- a second act/assert pair means a second test. Unless the _sequence_ is the behaviour
  (idempotence, push-then-pull, a state machine): then one pair per step, in order, and the
  test named after the sequence.

## Control time, env, filesystem

Same tree, run twice, in any order, at any hour, on any machine → same verdict. Anything
the machine gets to decide is arranged by the test, explicitly.

| ambient | never                                                | instead                                                               |
| ------- | ---------------------------------------------------- | --------------------------------------------------------------------- |
| time    | `datetime.now()`, `sleep`, "took under 1s"           | a fixed instant: injected clock, `time_machine`, `vi.setSystemTime`   |
| env     | reading the ambient var, assigning `os.environ[...]` | `monkeypatch.setenv`, plus `delenv(name, raising=False)` for the rest |
| fs      | the repo, a hardcoded `/tmp/x`, `~`                  | `tmp_path`, `monkeypatch.chdir(tmp_path)`                             |
| other   | uuid/random, set & dict order, network, locale       | seed or inject, sort before comparing, stub, pin `TZ`/`LANG`          |

- `assert stamp == date.today().isoformat()` is the ambient form of a value built by the
  implementation's own expression: both sides move together, so it passes on a wrong date,
  and it breaks at midnight.
- `HOME` and `XDG_*` are env too — a test reaching a real config reads the developer's.
- an absolute path inside an assertion is a tmp dir leaking in: compare against
  `tmp_path / "..."`, or assert the relative part.
- every var the code reads gets set or deleted, including the ones the test doesn't care
  about — otherwise an export on one machine flips the result.
- a test that only passes when the whole file runs depends on another test: find the shared
  state (module cache, singleton, a file written outside `tmp_path`) and kill it.

## Editing an existing test

- change an assertion only when the _behaviour_ deliberately changed, and say which. A test
  edited into passing is a bug removed from sight.
- bring the lines you touch up to the rules above, and only those — no reformatting sweep
  inside a change about something else.
- an intermittent failure is fixed at its ambient source (table above), never with a retry,
  a sleep, or a looser assertion.
