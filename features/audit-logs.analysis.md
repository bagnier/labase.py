# Impact analysis — Audit logs live view

## What this feature does

Adds a `/console/logs` page to the admin console that displays `audit_logs` events with:
- **Filtering** by level (info / warning / error), event name (ILIKE), and date range (from / to)
- **Live mode** (default): auto-refresh every 5 s via HTMX polling, shows the 50 most recent matching events
- **Historical mode**: triggered automatically when the user sets a date range or clicks "Load older"; auto-refresh pauses, cursor-based pagination loads 50 events at a time
- **"Back to live"** button to resume the live stream

## Module ownership

This feature belongs entirely to `apps/settings` — it extends the existing console router and templates. No new bounded context; no new domain module.

## Dependencies

- `audit_logs` table — **already exists** (`supabase/migrations/20260614000007_audit_logs.sql`). No schema change needed.
- `record_audit_event()` — already called throughout all app routers; no changes needed.
- `AdminSession` (BYPASSRLS) — required to read `audit_logs` (RLS blocks the authenticated role; consistent with all other console reads).

## Cross-cutting surfaces

| Surface                | Participates | Notes                                                                                                                                                                                                                             |
| ---------------------- | ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Admin console card** | **Yes**      | `ConsoleOverviewQuery` handler in `apps/settings/contract/integration.py` → `ConsoleOverview(key="logs", title="Audit logs", icon="scroll", data={"lines": ["N events recorded"]})`. The grid links to `/console/logs` via `key`. |
| Org dashboard          | No           | Server-wide admin tool; not org-scoped.                                                                                                                                                                                           |
| Sidebar menu           | No           | Reached via the console grid card.                                                                                                                                                                                                |
| Seeding                | No           |                                                                                                                                                                                                                                   |
| Admin settings         | No           | No tunable values.                                                                                                                                                                                                                |
| Feature switch         | No           | Core admin utility.                                                                                                                                                                                                               |

## Pagination & performance contract

Never load the full table. Every DB query is bounded:

```sql
SELECT id, created_at, level, event, user_id, ip, payload
FROM audit_logs
WHERE
  (:level  IS NULL OR level = :level)
  AND (:event   IS NULL OR event ILIKE :event)
  AND (:from_dt IS NULL OR created_at >= :from_dt)
  AND (:to_dt   IS NULL OR created_at <= :to_dt)
  AND (:before_id IS NULL OR id < :before_id)   -- cursor for "load older"
ORDER BY id DESC
LIMIT 51  -- fetch 51, render 50; if 51 returned → show "Load older" button
```

- `before_id` cursor: the ID of the 51st row (not rendered) becomes the next cursor.
- Existing indices (`created_at DESC`, `event`, `user_id`) cover the common filter patterns.
- The date range filter (`from_dt` / `to_dt`) works alongside `before_id`: the cursor stays within the range.

## Live vs historical mode

Managed client-side with Alpine.js (`x-data="{ live: true }"`):

| Trigger                       | Effect                                                                                                                      |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Page load                     | Live mode — `hx-trigger="every 5s"` on the tbody, no cursor                                                                 |
| User sets `from` or `to` date | Switches to historical mode (`live = false`), fires an immediate refresh                                                    |
| User clicks "Load older"      | Stays in historical mode; button does `hx-swap="outerHTML"` on itself, appending 50 rows + a new button with updated cursor |
| User clicks "↑ Back to live"  | Clears date range, resets to live mode                                                                                      |

## Security

- All new routes (`GET /logs`, `GET /logs/entries`) use the `CurrentAdmin` dependency — identical to every other console route.
- DB reads via `AdminSession` (BYPASSRLS) — no new RLS policy needed.
- The `logs` slug is claimed implicitly by declaring `GET /logs` before `GET /{app}` in the router, consistent with how `/admins` is protected.

## Files to create or modify

| File                                                | Action                                                                                                  |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `apps/settings/infra/repository.py`                 | Add `AuditLogRepository` with `search(level, event, from_dt, to_dt, before_id, limit=50)` and `count()` |
| `apps/settings/infra/router.py`                     | Add `GET /logs` and `GET /logs/entries` before `/{app}`                                                 |
| `apps/settings/contract/integration.py`             | Register `ConsoleOverviewQuery` handler for the logs card                                               |
| `apps/settings/templates/console/logs.html`         | New — full page (filter bar with date range + table, Alpine.js live/historical state)                   |
| `apps/settings/templates/console/_log_entries.html` | New — HTMX partial (rows + conditional "Load older" button with cursor)                                 |

No migration. No new model. No new module.
