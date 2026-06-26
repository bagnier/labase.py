# Phase 1 — Scenarios (`features/<name>.feature`)

Write the Gherkin file iteratively, **before any code**. Do not touch Python until the
`.feature` is agreed upon, then wait for user validation.

- Build the scenarios one by one via dialogue: propose, discuss edge cases, revise wording.
- Write in **english**.
- Reuse existing steps from any context's `apps/<module>/tests/e2e/steps.py` when possible
  (e.g. auth/sign-in steps in `apps/auth/tests/e2e/steps.py`).
- Aim for scenarios readable by a non-technical user.
- Steps express **user intent**, not technical actions:
  - ✗ `When they click the submit button`
  - ✗ `When a POST request is sent to /auth/login`
  - ✓ `When they sign in with email "alice@example.com" and password "Secret1!"`
- Steps include **concrete values** (emails, passwords, names…), never vague placeholders
  like "valid credentials" or "some email".
- If a `Given` step is identical in every scenario, extract it to a `Background:` block.
- Every precondition is explicit via a `Given` step — no hidden state, no assumed context:
  - ✗ `When they update their profile` ← who is logged in? how did they get there?
  - ✓ `Given a user is signed in as "alice@example.com" with password "Secret1!"`
    then `When they update their display name to "Alice"`

## Project conventions (match the existing `.feature` files)

- **Feature header** uses the narrative form:
  `Feature: <name>` / `As a <role>` / `I want <capability>` / `So that <value>`.
- **Group scenarios with `#` comment headers** (`# Bootstrapping`, `# List`, `# Rename`…).
  This project does **not** use tags (`@...`), `Scenario Outline` / `Examples`, or `Rule:` —
  stay with plain `Scenario:` blocks.
- **Name actors by quoted email** in multi-user scenarios — it maps to the per-actor session
  isolation in the drivers (`"alice@example.com" views their organisation list`).
- **Both drivers must express every step.** A scenario runs under API *and* browser, so avoid
  steps only meaningful in one (no "they see the red border"); phrase outcomes both can assert.
- **Pin time explicitly** for date-dependent scenarios — there's a test clock; start with a
  `Given the current date is "2026-06-26"` style step rather than relying on "today".
- Reuse the established outcome phrasings (e.g. `Then the action is forbidden`) for consistency.

## Don't forget the overview surfaces

A feature is rarely just its own screens. When relevant, **propose scenarios for the
overview surfaces too**, so they get the same BDD coverage:

- **Org dashboard** — does this feature add a card? Propose a scenario asserting what the
  user sees on the dashboard (counts, recent items, empty state).
  - ✓ `Then they see a "To-do" card showing "2 open" and "1 done"`
- **Admin console** — does it add a server-wide stat? Propose a scenario for the console view.
  - ✓ `Then the console shows "3 organisations" under "Organisations"`

Keep these readable and value-driven like any other scenario; the empty state is worth its
own scenario.

Wait for user validation before moving to Impact.
