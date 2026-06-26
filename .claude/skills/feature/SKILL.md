---
name: feature
description: >
  Guide the development of a new feature using BDD (pytest-bdd + Gherkin).
  TRIGGER when: the user describes a new feature idea, wants to add a scenario,
  or says "feature", "nouvelle fonctionnalité", "/feature".
  Do NOT use for: bug fixes, refactoring, infrastructure changes.
---

# Feature development process

This project uses **pytest-bdd** with two drivers run on every scenario — each scenario
must pass under **both**:

- `BrowserDriver` (Playwright, end-to-end via browser)
- `ApiDriver` (direct HTTP calls)

## Four phases — load one reference at a time

Work the phases **in order**. Do **not** read a phase's reference until you enter that
phase: each file holds only what's needed there, so loading them all at once is wasted
context.

| Phase | Goal | Reference (read on entry) |
|-------|------|---------------------------|
| 1. Scenarios | Co-write the `.feature` file in dialogue, before any code | `references/scenarios.md` |
| 2. Impact | Decide integration: events, contracts, dashboard/console/settings/security surfaces | `references/impact.md` |
| 3. Design | Produce an HTML mockup of the screens | `references/design.md` |
| 4. Build | Implement test-first, one scenario at a time | `references/build.md` |

Each phase ends with a written artifact and **waits for user validation** before the next:
`features/<name>.feature` → `features/<name>.analysis.md` → `features/<name>.mockup.html` → code.

## Writing principle (applies to every reference)

These references state only what is **specific to this project and not guessable** — the
`contract/` boundary, the typed event bus, the logging conventions, the strict per-scenario
cycle. They deliberately skip generic tutorial material (what a FastAPI route or a domain
model is). Keep that bar when editing them.

## Rules

- Never skip phase boundaries: no code before Scenarios is settled; no Build before Impact
  and Design are agreed.
- The per-scenario cycle in Build is **strict**: feature → steps → drivers → prod code, one
  scenario at a time. Run `make test` between sub-steps.
- Claude works autonomously through the Build phase; the user reviews diffs and commits.
- When done, run `make ci` as a background task before claiming completion.
