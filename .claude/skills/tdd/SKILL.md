---
name: tdd
description: >
  Red-green-refactor loop for implementing a feature or fix: one failing test at a time,
  confirmed red for the right reason, minimal implementation to green, then refactor
  without breaking green — with checks against the model gaming its own tests. Governs the
  loop only; what goes inside the test is write-tests', and the two are used together.

  Do NOT use for: exploratory/manual testing of a running app (exploration-testing).
when_to_use: >
  The user says "TDD", "test-driven", "red-green-refactor", or asks to implement a
  feature or fix a bug test-first.
---

## Iron Law

No production code without a failing test that proves it's needed. If you wrote
implementation before the test, delete it — don't keep it "as reference," don't adapt it
while writing the test around it.

## Scope one seam at a time

Before writing a test, name the public behavior it exercises (the seam) — not an internal
method, not a mock's return value. One seam → one failing test → the minimal code to pass
it → repeat. Don't write every test for the whole feature before implementing any of it
(that hides broken assumptions until the end, and tempts a big-bang implementation pass);
slice vertically, one behavior end to end.

## 1. Write the test

What goes *in* the test belongs to `write-tests` — which case comes next, how it is named,
one equality over the whole expected value, time and env pinned by the test itself. Read it
before writing: this loop stops at the test's content and picks up again at its result.

One rule of it is repeated here, because the loop is where it gets broken: assert on real,
observable behavior — never on a mock's own record, and never with the formula the
implementation will use (`expect(add(a,b)).toBe(a+b)` passes by construction). Either one
sails through step 2 looking red for the right reason, then goes green in step 3 with nothing
implemented.

## 2. Confirm RED — mandatory, never skip

Run it, paste the actual output. Check the failure, not just that it failed:
- it *fails*, not *errors* (no typo, no import mistake in the test itself)
- the failure message matches what's actually missing
- it fails because the behavior doesn't exist yet — not a mistake in the test

Passes immediately? The test isn't testing anything new — fix the test before moving on.
Checkpoint it now (commit, or note the diff): this is what lets you catch tampering later.

## 3. Implement until GREEN

Give this instruction verbatim — to yourself, or, for real isolation, to a fresh subagent
that only sees the failing test and the task, not your reasoning about the internals:

> Write the implementation. Do not modify the tests. Keep going until all tests pass.

Verify GREEN with the same rigor as RED: paste the full run, pristine (nothing silently
skipped/xfail'd), no other test regressed. Diff the test files against the step 2
checkpoint. Anything changed there is tampering, not progress — revert the test edit and
fix the implementation instead.

## 4. Refactor until GREEN

Only after green, and only reshaping — no new behavior, no new tests, tests green
throughout:

> Refactor the implementation. Do not modify the tests. Keep going until all tests pass.

Same test-file diff check as step 3.

## Red flags — stop and restart the loop

- "I'll write the test after" — a test added once the code already passes proves nothing;
  you never watched it fail.
- Hardcoding a value that matches the test's exact input instead of the real logic.
- Weakening an assertion, adding a mock, or catching-and-swallowing to force green instead
  of fixing the bug.
- "This case is different, I'll skip the test for it" — no exceptions inside a seam you
  already agreed to cover.

Any of these: revert the shortcut, go back to step 1 for that seam.
