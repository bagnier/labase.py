---
name: explore
description: >
  Exploratory browser testing — wander the running app like a curious, demanding
  human. Two jobs: (1) is it BROKEN — dead links, hard errors, a11y gaps,
  cross-tenant leaks; (2) is it GOOD — visual coherence, information architecture,
  feature completeness, interaction finish. The second job needs pixels + a
  standard + a product model, not a click-through.
  TRIGGER when: the user says "explore", "test exploratoire", "/explore", or asks
  to hunt for bugs / broken links / weird or unfinished behaviour in the running
  app via the browser.
  Do NOT use for: writing BDD scenarios (that's /feature), unit/integration bugs,
  or anything not driven through a real browser.
---

# Exploratory browser testing

Model-driven wander through the running app — a perceive→judge→act loop, not a
script. Complements the BDD suite by finding what no assertion covers. Drive it with
the **Playwright MCP** tools (interactive session only — not available headless/cron).

You have **two complementary jobs**:

- **Broken?** — hard errors, dead links, a11y gaps, tenant leaks. High bar, confirmed only.
- **Good?** — is the design coherent, the information architecture findable, the
  feature complete, the interaction finished? This is *critique*, not a pass/fail test.
  A click-through that only asks "did it 500?" answers everything with "fine" and
  misses everything a user actually notices. Judging "good" needs three things a
  crawl doesn't have by default: **pixels** (screenshots, not the a11y tree), **a
  yardstick** (what a mature version looks like), and **a goal** (a persona doing a task).

Args: `--area=<app>` to focus one context, `--budget=<N>p|<N>m` (default 40 pages **or**
15 min, first reached wins).

## Preconditions

- **Launch the server yourself** as a background task: `make dev > reports/explore-<date>/server.log 2>&1`.
  Poll `http://localhost:8000` until it answers. `make down` only if *you* started the
  stack — never tear down a stack that was already running.
- **Seed:** `make db-seed` (idempotent). If it can't resolve the DB host from the shell
  (`host.docker.internal` only resolves *inside* Docker), run it in the app container:
  `docker cp scripts/. <app-container>:/app/scripts && docker exec -e PYTHONPATH=/app -w /app <app-container> uv run python scripts/seed.py`.
- Login **A** = `dev@labase.dev` / `Devpass123!` — server admin.
- **Perceive in two modalities.** The a11y **snapshot** is for *acting and locating* (refs).
  For *judging* look, layout, hierarchy, colour and "is this even visible", you must
  **screenshot** — the a11y tree flattens away exactly what design findings live in.
  At each meaningful page take a screenshot at **desktop (1440)** and **mobile (390)**;
  save every shot to `reports/explore-<date>/`. Colour/alignment/visibility/consistency
  findings are impossible without these.

## Orient first — build the yardstick

Before you can call something incomplete or incoherent you need the standard to judge
against. Spend the first few minutes building it, and jot it into the report dir:

- **Visual system.** Skim the base templates / shared component partials (buttons,
  cards, form rows, tables) so you know the *intended* language — spacing scale, colour
  roles, primary-vs-secondary CTA, the one card pattern. Later, a page that departs from
  it is a finding; without this baseline you can't see the departure.
- **Completeness model.** For each app context write one line: *what a mature version of
  this feature does*. Calendar → multi-day & recurring events, timezone-aware. SRS/learning
  → one card at a time, grade, next-due. Pages → full-text search, images, drafts. Settings
  with many sections → grouped/tabbed. Absence is invisible at the click level; it only
  shows up against this model.

## Two ways to move (do both)

1. **Crawl** — visit every context, exercise every form and safe button. Mechanical
   coverage; this is what catches hard errors and tenant leaks. Keep a visited-URL set;
   distinct HTMX states count as new.
2. **Personas with a goal** — *be* someone and complete a real task, narrating friction,
   hesitation and every "wait, where is this?". Goal-driven navigation is where
   information-architecture findings are born (a crawl never feels lost):
   - **New owner:** sign up → create an org → invite a member → set a limit → publish/brand a page.
   - **Admin on a fire:** a request just failed — find out why (issues, logs, metrics).
     Note anything important that's buried, mislabelled, or two clicks too deep.

## Backend-fault oracle

A backend fault often leaves the UI looking fine. After actions, check the truth source:
the DB-backed **/console/logs** viewer (one timeline: request firehose + audit + issues)
and the `error_events` / `error_groups` tables — `count(*) = 0` since session start means
clean; any new row is a tracked issue worth a finding. Do **not** rely on `server.log`
alone: once `make dev` stops attaching it goes quiet even while the app runs. Note the
`request_id` on anything suspicious and pivot the logs viewer to it.

## Oracles

- **Hard** — dead links, 4xx/5xx, JS/console errors, broken assets, `hx-*` swap that errors
  or leaves the fragment empty, plus any server error in the logs/issues viewer. *Confirmed only.*
- **Tenant** — provision **B** (`POST /auth/register` with a `<uuid>@test.local` email —
  auto-confirmed locally — or a 2nd org), own cookie jar. Oracle: **B never sees A's data**,
  even via a URL guessed from A's session, on **both** the HTML routes and the JSON API
  (`Authorization: Bearer lbk_…` + `Accept: application/json`; A's key on B's org must 403).
- **a11y** — missing landmarks/labels, invisible focus, `aria-hidden` on non-decorative,
  contrast, keyboard traps.
- **Design** *(needs the screenshots)* — a page that breaks the shared visual language
  (its own colour/spacing/component/card style); weak affordance hierarchy (primary CTA not
  visually distinct); alignment / vertical-rhythm breaks; wrong or inconsistent link & state
  colours; something technically on the page but effectively **invisible**. Most of these are
  **relative** — lay screenshots of sibling pages side by side; incoherence only shows up in
  comparison, never page-by-page.
- **IA / product** *(needs the yardstick)* — feature should do more than it does; page
  overloaded and should be split/tabbed; an important thing buried or hard to find; a
  destructive/important action with no confirm or no post-save feedback; a config option
  meaningless in its context; naming that misleads; a results panel you can't locate.

## Report the impression — don't self-censor the "good?" job

For **hard/tenant**, only file what you confirmed. For **design/IA/product**, file the
*impression*: "feels unfinished", "inconsistent with the rest", "I couldn't find X",
"a real user would expect Y" are valid findings **even though they're subjective** — that
subjective read is the entire deliverable of this pass. The old bias toward high-confidence
hard findings is what makes an app look "clean" when it's merely unbroken. Still dedup.

## Two critique passes to close out

After crawl + personas, do two deliberate fresh-eyes passes over the collected screenshots —
this is where the non-obvious findings are:

- **Design critic.** Put the screenshots next to each other. *What breaks the visual system?
  What looks unfinished? What's hard to see? Which page feels like a different app?*
- **Product critic.** Each context against your yardstick. *What would a demanding user expect
  that's absent, awkward, or in the wrong place? What's named for how it's built, not how it's used?*

## Denylist — never click (account A is admin; this guards the session itself)

Impersonate a user · delete/disable another user · disable an app · change runtime log
level · self-serve account deletion · email change (fires a confirmation mail). Everything
else — create/edit todos, pages, events, uploads, share tokens, org invites — is fair game.

## Output — deduplicated items in ROADMAP.md

Append under a single `## exploratory findings` section at the top of `ROADMAP.md`. Read it
first; skip duplicates (dedup key = url + symptom), never touch `[x]` items. One line each:

```
- [ ] **[dur|ux|a11y|tenant|design|ia · P0-P2]** {symptom} — `{url}` — repro/why: {1 line} — [preuve](reports/explore-<date>/…) (YYYY-MM-DD)
```

Lanes: `dur` hard break · `ux` broken interaction (dead-end, no-effect button, empty state)
· `a11y` · `tenant` leak · `design` visual/coherence · `ia` architecture/completeness/finish.
P0 leak/data-loss · P1 blocks a task · P2 cosmetic / friction / polish. Screenshots and
console/network dumps live in `reports/explore-<date>/`, linked — never inline.
