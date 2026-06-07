---
name: feature
description: >
  Guide the development of a new feature using BDD (pytest-bdd + Gherkin).
  TRIGGER when: the user describes a new feature idea, wants to add a scenario,
  or says "feature", "nouvelle fonctionnalité", "/feature".
  Do NOT use for: bug fixes, refactoring, infrastructure changes.
---

# Feature development process

This project uses **pytest-bdd** with two drivers run on every scenario:

- `BrowserDriver` (Playwright, end-to-end via browser)
- `ApiDriver` (direct HTTP calls)

Each BDD scenario must pass under **both** drivers.

## Project layout

```
features/          ← Gherkin .feature files
tests/bdd/
  steps.py         ← shared step definitions (driver-agnostic)
  drivers/
    browser.py     ← BrowserDriver (Playwright)
    api.py         ← ApiDriver
  conftest.py      ← fixtures, driver wiring
  test_features.py ← pytest entry point
app/
  <module>/
    domain/        ← business logic
    infra/         ← router, repository, dependencies
```

## Scenarios — Write the `.feature` file (iterative, before any code)

- User describes the feature idea in natural language.
- Together, build the Gherkin scenarios one by one via dialogue.
  - Write or update the in `features/<name>.feature` file`.
  - Use english language.
  - Propose scenarios, discuss edge cases, revise wording.
  - Reuse existing steps from `tests/bdd/steps.py` when possible.
  - Aim for scenarios that are readable by a non-technical user.
  - Steps must express **user intent**, not technical actions:
    - ✗ `When they click the submit button`
    - ✗ `When a POST request is sent to /auth/login`
    - ✓ `When they sign in with email "alice@example.com" and password "Secret1!"`
  - Steps must include **concrete values** (emails, passwords, names…), not vague placeholders like "valid credentials" or "some email".
  - If a `Given` step is identical in every scenario, extract it to a `Background:` block instead of repeating it.
  - Every precondition must be explicit in the scenario via a `Given` step. No hidden state, no assumed context:
    - ✗ `When they update their profile` ← who is logged in? how did they get there?
    - ✓ `Given a user is signed in as "alice@example.com" with password "Secret1!"` / `When they update their display name to "Alice"`
- **Do not touch any Python code until the `.feature` is agreed upon.**
- Wait for user validation to go forth.

## Impact — Integration analysis (before any code)

Perform an impact analysis: identify how the new feature interacts with existing bounded contexts.

Ask open questions like:

- Which existing modules, services, or entities does this feature depend on or modify?
- Does this feature emit or consume domain events? Does it need to hook into existing flows (auth, permissions, notifications…)?
- Does it share data with another context, or does it own its data entirely?
- Are there existing endpoints, repositories, or domain models that need to be extended?

Produce a short written summary of the decisions (a few bullet points is enough). Use english language.Update the scenarios accordingly. Store it in `features/<name>.analysis.md`. **No code yet.**

Wait for user validation to go forth.

## Design — UI mockup (before any code)

Produce an **HTML mockup** of the feature's screens and interactions.

- Use a single static `.html` file stored at `features/<name>.mockup.html` (no backend, inline CSS is fine).
- Show the full page layout for each relevant state (empty state, populated, error…).
- Mark interactive elements clearly (forms, buttons, links).
- HTMX attributes (`hx-post`, `hx-swap`…) may appear as hints but are not required.
- The mockup is for alignment, not production — keep it rough.

Iterate with the user until the layout and interactions are agreed upon. Update the scenarios accordingly. **No Python code yet.**

Wait for user validation to go forth.

## Build — Implement (test-driven, strictly per scenario)

For **each scenario** in the `.feature` file, execute the following steps **in order** before moving to the next scenario. Run `make test` after each sub-step.

### Per-scenario cycle (repeat for every scenario)

#### Step definitions (`tests/bdd/steps.py`)

- Add missing `@given` / `@when` / `@then` decorators.
- Steps must be driver-agnostic: they only call methods on `driver`.
- Steps that need a new driver method → add a `NotImplementedError` stub first.
- Run `make test` → the scenario must fail with `NotImplementedError`, not a missing step error.

#### Drivers (`tests/bdd/drivers/browser.py` and `api.py`)

- Implement the new methods on **both** drivers.
- If a brand-new driver is needed (e.g. email, queue), create it without asking.
- Run `make test` → the scenario must fail with an application error (404, missing route…), not a driver error.

#### Application code (`app/<module>/`)

- Implement domain logic first (`domain/`), then infra (`infra/`).
- Follow the existing pattern: `domain/service.py` → `infra/router.py` + `infra/repository.py`.
- Run `make test` → **the scenario must pass before moving to the next one.**

### Refactoring

- **Minor** (rename, extract variable, simplify condition): do it immediately.
- **Major** (new abstraction, cross-module restructure): note as TODO, do it later.

## Rules

- Never skip phase boundaries: no code before Scenarios is settled; no Build before Impact and Design are agreed.
- The per-scenario cycle in Build is **strict**: feature → steps → drivers → prod code, one scenario at a time.
- Claude works autonomously through Implement Phase; user reviews diffs and commits.
