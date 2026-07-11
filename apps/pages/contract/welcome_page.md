Welcome. You are looking at a page served by **labase.py** — an open-source Python
SaaS foundation where everything below is already built, wired, and tested. Clone it,
delete the demos, and start shipping your product on day one.

## Sign in every way

Email and password with mailed confirmation, resend for unconfirmed accounts, and a
full forgot/reset flow. Social sign-in with Google and GitHub. Two-factor
authentication with TOTP. Passkeys (WebAuthn). Email change with mailed confirmation
and self-serve account deletion — both admin-switchable. Machine access through
per-organisation API keys. Nothing to bolt on: the entire identity surface is done.

## Multi-tenant from the first click

Every account gets a personal organisation at sign-up. Invite teammates, manage
members and roles, create as many organisations as you need. Isolation is not a
Python `if` — it is **row-level security enforced by Postgres itself**, versioned as
plain SQL migrations. The database is the guard, not the app.

## An admin console that sees everything

Server-wide stats from every app, admin-tunable settings with per-organisation
overrides, and runtime feature switches — disable an app and it vanishes everywhere,
re-enable it with one click. Accounts management with bannered, audited
impersonation. A unified log viewer merging application logs, the audit trail and
error events. Error tracking with fingerprint-grouped issues and a lifecycle
(open → resolved → regressed). Live load graphs. All of it ships in the box.

## Postgres as everything

No Kafka, no Redis, no Elastic, no Mongo. A durable task queue with outbox
semantics, cross-instance rate limiting, error tracking, per-minute load metrics
with rollups, and fulltext search — each one a plain Postgres table on Supabase.
One database to operate, back up, and reason about.

## One handler, three faces

Every business endpoint answers JSON, an HTMX fragment, or a full page through
content negotiation. One implementation buys you a documented REST API **and** a
dynamic server-rendered front end — no separate frontend project, no JS build step.
The OpenAPI schema even regenerates a typed Python client, kept honest by
performance smokes that drive the real API through it.

## Apps that unplug

The base is a collection of self-contained apps. Each declares everything it
contributes — routes, sidebar entry, dashboard card, console stats, settings,
seeds — in a single mount call, and reacts to others only through typed events.
Boundaries are enforced by import-linter, not by discipline. **Deleting an app
leaves no trace.** This very page was seeded by one of them.

## Observability built in

Structured logs correlated per request. Every domain event on the bus is logged
with sensitive fields redacted. Sensitive actions land in an append-only audit
trail, browsable from the console. A Prometheus endpoint feeds the load screen.
You will know what your app is doing before your users tell you.

## Tested sincerely

The same plain-language scenarios run twice — over real HTTP and through a real
browser — against a real database, real mailboxes, and real TOTP codes. Nothing
business-critical is mocked. When the suite is green, the product works.

---

Sign up and see for yourself: your organisation arrives already alive — a dashboard,
starter content, and every feature above, ready to be replaced by your idea.
