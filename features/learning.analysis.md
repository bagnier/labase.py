# Impact analysis — `learning` context (spaced repetition)

Covers three feature files that form **one** bounded context:
`apprentissage espacé.feature`, `session de révision.feature`, `ressources.feature`.

## Scope decisions (confirmed)

- **New bounded context `app/learning/`** — owns decks, cards, per-user learning state,
  sessions, and resource suggestions. Single context because all three features read/write
  the same per-card learning state (one aggregate).
- **Single shared org.** Everything behaves as if all users belong to the same org. Decks
  and cards carry `org_id` (= the shared org) and are seeded once into it; the existing
  org-scoped RLS (`org_id in user_orgs()`) works unchanged because every user is a member.
  Catalog is common to all; isolation between learners comes solely from `user_id` on the
  per-user tables. No per-org template copy needed.
- **Review experience only.** Deck/card authoring is out of scope; decks/cards are seeded
  (migration for the running app; test-built for BDD). Implemented user actions: subscribe
  to a deck, start a session, view a card, mark a card, view resources.
- **Full hexagonal slice + UI**: domain + repository + router + Jinja2/HTMX templates,
  BDD steps on both API and browser drivers, SQL migration.

## Ownership & data

This context owns all its data entirely. New tables (all `org_id`-scoped, RLS via
`public.user_orgs()`):

- `decks` — id, org_id, name, resource (nullable), position.
- `cards` — id, org_id, deck_id, external_id (`PY001`), question, answer, resource
  (nullable), position.
- `deck_subscriptions` — (user_id, deck_id) = "veut apprendre le paquet".
- `card_states` — per (user_id, card_id): level (0–9), last_reviewed_on, next_review_on.
  Absent ⇒ level 0 / unstudied.
- `card_reviews` — append-only log (user_id, card_id, reviewed_on, outcome learned|again);
  drives "resources from the last review day".

No table for sessions: a session is the computed current snapshot of the due set;
interruption semantics fall out of `card_states` + marks.

## Dependencies on existing contexts

- **auth** — reuse sign-in/identity steps (`app/auth/tests/steps.py`); `CurrentUser`.
- **organizations** — org resolution (`get_current_org` / `CurrentOrg`), RLS via
  `user_orgs()`. The feature scenarios name only learners ("Alice", "Bob") with no org
  wording: all users belong to the **single shared org**, so the catalog is common and
  "personnel à chaque utilisateur" (Bob sees no cards) is enforced purely by `user_id` on
  the per-user tables, not by org isolation.
- **shared** — `OrgScopedRepository`, `app.shared.dependencies` (CurrentUser/RlsSession/
  CurrentOrg), `app.shared.http.responses` render helpers, `app.shared.clock.now`,
  `app.shared.observability.audit`.

## Events / cross-context flows

No domain events. No hooks into notifications. Self-contained except for the auth/org
dependencies above.

## Clock / time control

Scenarios pin and advance time ("la date du jour est le 01/09/2024", "un jour passe",
"a déjà revue ... il y a N jours"). The domain reads "today" via `app.shared.clock`; BDD
steps control time by patching the `clock` module reference (existing codebase mechanism).
All scheduling math uses **dates** (day granularity), computed from the effective answer
day, never from the scheduled date.

## Algorithm summary (from the scenarios)

- Levels 0–9, capped at 9. Fibonacci interval by resulting level:
  `{1:1,2:1,3:2,4:3,5:5,6:8,7:13,8:21,9:34}`.
- "Apprise": level+1 (cap 9), next = today + interval(new level).
- "À revoir": level → 1, next = today + 1.
- Due set: level-0 always due; studied due when next_review ≤ today.
- Order: unstudied first (deck/card order), then by oldest next_review, ties by deck/card
  order; cards from all subscribed decks mixed by this single sort.
- Resources: cards still needing review (all unlearned when no session yet, else cards
  marked "à revoir" on the last review day), grouped by deck in deck order — deck resource
  first, then card resources; dedup; skip empty; skip card resource equal to deck resource.

## New wiring

- `app/main.py`: include the learning router under `/{org_slug}`.
- root `conftest.py`: add `app.learning.tests.steps` to `pytest_plugins`.
- `tests/e2e/drivers/`: add `LearningApiMixin`/`LearningBrowserMixin` to `ApiDriver`/
  `BrowserDriver` and extend `protocols.py`.
- `supabase/migrations/20260614000008_learning.sql`: tables, indexes, RLS, grants, seed.
