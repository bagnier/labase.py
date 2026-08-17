# Unified logs — impact analysis

## Shape

A new bounded context **`apps/logs/`** is the single **observability read-context**. It is a
**pure reader**: it never writes logs. It presents one timeline by merging, at read time,
**three sources** and lets an admin filter/correlate/export them.

The firehose (`logger.*`) is an **stdout event stream** (12-factor) — the app does not write
it to Postgres. Audit and issues are durable **domain records** that already live in Postgres
and stay there. So there is **no `log_events` table, no tee, no sink** (all dropped from the
earlier draft).

| Source  | Where it lives                     | Written by                              |
| ------- | ---------------------------------- | --------------------------------------- |
| request/app (firehose) | rotated JSON file (`*.jsonl`), fed by structlog | `shared/observability/logging.py` |
| audit   | `audit_logs` table                 | `shared/observability/audit.py::audit()` |
| issue   | `error_events` / `error_groups`    | `apps/issues` (`ExceptionCaptured`)     |

`shared/observability/` keeps all write primitives (a foundation everyone imports downward);
`apps/logs` only reads. `apps/issues` and `apps/metrics` remain sibling contexts — the name
is `logs`, not `observability`, to not overclaim them.

## Firehose: file, not DB

- `setup_logging()` gains a **rotating JSON file sink** alongside stdout: structlog writes
  the same JSON lines to a configured path (e.g. `LOG_FILE=var/log/app.jsonl`), size/day
  rotated. stdout is unchanged (the platform still captures it).
- **Gated by the log level.** At the new default `WARNING`, only `WARNING+` firehose lines
  reach the file; lowering to `INFO` makes `request.*` lines appear. This is the existing
  structlog level filter — nothing new.
- `apps/logs` reads the file for a **recent read-time window** (`firehose_window_hours`,
  default 48): it scans the current + rotated files within the window, parses JSON lines,
  applies the active filters, caps at a max line count (safeguard), and merges with the DB
  sources.
- **Retention = file rotation** (ops concern, e.g. logrotate / size cap), *plus* the
  read-time window bound. There is **no SQL purge** for the firehose. (This is why the
  scenario asserts a read window, not a purge.)
- **Caveat (accepted): per-instance.** A file is local to one replica; in a multi-instance
  deploy the firehose view shows the reading instance's lines only. audit/issues (DB) are
  cross-instance. A central firehose across instances would need a log drain later
  (ROADMAP "Log Drains") — swappable behind the same reader port, out of scope now.

## Correlation binding (the org-filter + join unlock)

Today only `request_id` is bound into structlog contextvars. Extend it so **`user_id`** (in
auth's `CurrentUser`) and **`org_id`** (in organizations' `CurrentOrg`) also enter
contextvars. Effects, all for free:

- firehose file lines carry `org_id`/`user_id`/`request_id` (JSON fields) → org filter +
  correlation on the firehose.
- issues' `capture_context()` already snapshots contextvars → issue events gain `org_id`
  automatically (issues has no org column today; this is how it gets org attribution).
- `audit()` reads `request_id` from contextvars into the persisted row (see migration).

## Data & migration (minimal — one existing table extended, no new table)

`supabase/migrations/<ts>_audit_logs_correlation.sql`:

- Add `request_id text` and `org_id uuid` columns to **`audit_logs`**, so the org filter and
  the request-id join are first-class/indexable (today `org_id` is buried in `payload`,
  `request_id` is absent from the row). `audit()` populates both (org_id already passed;
  request_id from contextvars). Backfill: nullable columns, old rows keep `payload.org_id`.
- Indexes: `(org_id, id desc)`, `(request_id)`. Existing `audit_logs` RLS/grants unchanged
  (service_role only, admin-only).

`error_events` needs no change: `request_id` already lives in its `context` jsonb, and
`org_id` will now be captured there via the contextvar binding.

## Reader / merge

`apps/logs` builds the timeline by: (1) SQL over `audit_logs`, (2) SQL over
`error_events`+`error_groups`, (3) file scan of the firehose window — each pre-filtered by
the active filters, then merged in memory over the bounded window (hard row cap), sorted,
and offset-paginated. "Load older" widens the date window. Deep history is reached by
narrowing the **date** filter (DB sources hold full history; the firehose stays bounded by
file availability).

**Filter set** (all combine, `AND`):

- **date slice** — `from_dt`/`to_dt` (toolbar inputs *and* the graph brush write the same
  two params).
- **source** — `request` | `app` | `audit` | `issue`.
- **level** — `debug|info|warning|error`.
- **org_id** — the org filter (select resolves handle↔id via `organizations.contract`).
- **user_id** — exact match (`audit_logs.user_id`, firehose `user_id`, issue `context`).
- **request_id** — exact match (the correlation pivot; also set by clicking a row's request).
- **text** — free `ILIKE` across `event` + message + serialized `payload`/`context`.

**Smart filter controls** — each filter is a combobox: click opens a text field that
narrows candidate values as you type (typeahead). The inactive/default state renders "all"
typographically distinct (muted italic) from a chosen value (bold, with a clear affordance).
Candidate values come from a lightweight distinct-values endpoint
(`/console/logs/suggest?field=org|source|level|user|request&q=…`) returning the top matches
(+counts) over the current window; `source`/`level` are the fixed enums, `org` resolves via
`organizations.contract`, `user`/`request` are recent distinct values, `text` is free (no
list). Progressive-enhancement: the field still works as a plain typed filter without JS.

**Sortable columns** — every column header sorts asc/desc; **default `ts` desc** (newest
first). Sorting happens in-memory over the merged window (trivial once loaded — this is why
the bounded-window merge model matters), carrying a `sort`/`dir` param. Not keyset-sortable
across sources, so sort operates on the loaded window, not an unbounded stream (documented
limit). Covered by the two sorting scenarios.

## Activity graph

A stacked chart above the timeline: three series (`request`, `audit`, `issue`) counted per
time bucket over the recent window. Reuses the existing chart infra exactly as the metrics
Load screen does — a `<script type="application/json" data-chart-config>` + `<div
data-chart>` rendered by the shared `static/js/charts.js` + `apexcharts.min.js`, themed live
from daisyUI. The router shapes a `series_json` (a `_activity_chart_json` helper, mirroring
metrics' `_series_chart_json`).

- **Aggregation**: DB sources via `date_trunc` `GROUP BY` bucket over `audit_logs` and
  `error_events` (with the active filters applied); firehose via in-memory bucketing of the
  parsed file-window lines. Merge the per-bucket counts into the three series.
- **Honours filters**: the graph recomputes under the same org/level/event/date filters as
  the table (see the two activity scenarios — org filter narrows both).
- **Time brush / drill-down**: the chart is also a range selector (ApexCharts
  `selection`/`brush`). Dragging a span sets `from_dt`/`to_dt` — the *same* date-range filter
  the toolbar exposes — and one HTMX refetch narrows **both** the table (`/entries`) and the
  graph (`/activity`). Selecting inside a selection drills further; double-click / "Back to
  live" resets. The current date filter is drawn back as a highlighted band, so table and
  graph always show the same period. The brush *gesture* is browser-only sugar over the
  date-range params (the filter contract), so BDD asserts the date-range behaviour on both
  surfaces (the sync scenario), never the drag itself.
- **Testable like metrics**: scenarios assert the aggregated counts, exposed both in the
  content-negotiated JSON (`series`) and in the declarative `data-chart-config` payload —
  never the rendered canvas.

## Surfaces checklist

- **Console screen** — router at `/console/logs` (index `""`, HTMX `"/entries"`, activity
  `"/activity"`, export `"/export"`), content-negotiated JSON. Mounted **before `console`**
  in `apps/main.py` (like `issues`, `metrics`) so `/console/logs*` precedes the
  `/console/{app}` catch-all.
- **Audit viewer migration (into `apps/logs`)** — move `AuditLogRepository`,
  `console/_log_entries.html`, the `/console/logs/entries` route and the `#logs` section of
  `console/settings.html` out of `console` into `apps/logs`. Recent audit browsing =
  `source=audit` on the unified timeline; deep audit history/export = `apps/logs` reading
  `audit_logs` directly.
- **`log_level` setting migration (into `apps/logs`)** — move
  `console/contract/observability.py` (the `log_level` `SettingDef` + `apply_log_level` at
  mount + `reload` on `SettingsChanged` + the "Logging" console tile) into `apps/logs`.
  Settings **group renamed `observability` → `logs`** (`log_level` key unchanged).
- **Settings** — `register_settings("logs", [...])`: `feature_switch()`, `log_level`
  (default from `default_log_level()`), `firehose_window_hours` (default `48`),
  `SupabaseLink` to `audit_logs`.
- **Default level → WARNING** — `default_log_level()` returns `WARNING` when not in debug
  (`"DEBUG" if log_debug else "WARNING"`). Dev (`log_debug`) stays `DEBUG`.
  → **Risk**: the "defaults to WARNING" scenario needs the test env with `log_debug=false`;
  confirm in test config. Update `test_observability.py` (app_name `observability` → `logs`).
- **Feature switch** — the whole `logs` app is on/off-able (mount short-circuits, console
  still lists it).
- **Console tile** — keep the existing "Logging" settings-group tile (moved from
  `observability.overview`), showing the current level. No new dashboard card, sidebar nav,
  seeding, or reserved slug — deliberate non-goals (admin/console-only).

## Security

- Every `/console/logs*` route **admin-only** (`CurrentAdmin`), DB reads via `AdminSession`
  (BYPASSRLS), file read is a plain server-side read. Non-admin → `not found` (matches
  issues/metrics). Covered by the access scenario. Export inherits the same guard.
- The firehose file is written by the app process only; the reader parses it read-only.

## Coupling

- `apps/logs` reads `audit_logs`/`error_events` (own repositories over global tables) + the
  firehose file. For org handle↔id resolution/labels it uses a read-only
  `organizations.contract` query (add one if none fits) — no app→app import.
- No new bus event. Issues keeps emitting `IssueOpened`/`IssueRegressed` for its own alerts.

## Notes

- **`app` vs `request` source** — keep both as source values (non-request structlog lines =
  `app`), labelled "app log" in the UI. Scenarios exercise `request`.
- **"Audit at WARNING" scenario** proves audit visibility is level-independent: audit is read
  from `audit_logs` (written regardless of level), so it shows even when the firehose file,
  at WARNING, holds no INFO lines.
- **Seeding in tests** — `a request log entry …` appends a JSON line to the test-configured
  firehose file; `an audit log entry …` / error entries insert DB rows. Both drivers run
  in-process, so a test `LOG_FILE` path is shared.
