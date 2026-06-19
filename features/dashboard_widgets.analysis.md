# Integration analysis — Org dashboard overviews

## Goal

Let each org-scoped app (todo, files, learning) surface an **overview** on the org
dashboard, via an **auto-discovery** mechanism mirroring `app/seeding.py` — dropping
`app/<ctx>/contract/overview.py` is enough to participate, no central list.

Each overview exposes:
- a **web view** (the app's own Jinja partial, rendered on the dashboard page),
- **structured data** (a JSON-serializable payload), exposed only through a dedicated
  REST endpoint.

Both surfaces are exercised by the two BDD drivers: **ApiDriver → REST JSON**,
**BrowserDriver → rendered web view**. The scenarios stay agnostic of rest/web.

## Scope decisions

- **Org-scoped, not user-scoped.** The dashboard is org-scoped, so overviews aggregate
  org-level data. `TodoRepository`/`OrgFileRepository` are already org-scoped. Learning's
  `LearningRepository` is user-scoped (subscriptions/states), so the learning overview uses
  org-scoped counts of `Deck`/`Card` (both carry `org_id`), NOT personal due cards.
- **No app-to-app coupling.** The organizations context owns the contract and the dashboard;
  apps depend only on `app.organizations.contract.overviews` (the `Overview` type +
  `register_overview`). Discovery wiring lives in the composition root `app/overviews.py`.
- **No new domain events.** Unlike seeding (which hooks `org.created`), overviews are pulled
  synchronously at dashboard render time using the request's RLS session.

## Contract

`app/organizations/contract/overviews.py`:
```python
@dataclass(frozen=True)
class Overview:
    key: str          # context id, e.g. "todo"
    title: str        # human title, e.g. "To-do"
    icon: str         # phosphor icon name
    href: str         # link into the app
    template: str     # app's Jinja partial (web view)
    data: dict        # JSON-serializable; conventions: "lines": list[str], "recent": list[str]

OverviewProvider = Callable[[AsyncSession, UUID], Awaitable[Overview]]   # org-scoped
def register_overview(ctx: str, provider: OverviewProvider) -> None: ...
async def collect_overviews(session, org_id) -> list[Overview]:  # ctx-sorted, deterministic
```

`data` conventions consumed by both the partial and the steps:
- `lines`: short metric strings, e.g. `["1 open", "1 done"]`, or `["No tasks yet"]` (empty state).
- `recent`: recent item labels, e.g. todo titles / filenames.

## Per-app surface (auto-discovered)

| App | contract module | repo / query | data |
|-----|-----------------|--------------|------|
| todo | `app/todo/contract/overview.py` | `TodoRepository(session, org_id).all()` | lines `["{open} open","{done} done"]`, recent = last titles |
| files | `app/files/contract/overview.py` | `OrgFileRepository(session, org_id).all()` | lines `["{n} files","{size}"]`, recent = filenames |
| learning | `app/learning/contract/overview.py` | org-scoped `count(Deck)`, `count(Card)` where `org_id` | lines `["{decks} deck(s)","{cards} cards"]` |

Each renders its own `app/<ctx>/templates/<ctx>/_overview.html` partial.

## Dashboard wiring

`app/organizations/infra/router.py`:
- `org_dashboard`: call `collect_overviews(session, org_id)`, inject `overviews` into ctx.
- new `GET /{org_handle}/dashboard/overviews.json`: return `[{key,title,data}, ...]`.

`app/organizations/templates/organizations/dashboard.html`: replace placeholder metric
cards + static todo card with a loop `{% include o.template %}` over the overviews.

## Test wiring

- New steps in `app/organizations/tests/e2e/steps.py` (overview is a dashboard/org concern):
  `the "{key}" overview is visible on the dashboard`, `... shows "{text}"`, `... lists "{text}"`.
- ApiDriver mixin (`app/organizations/tests/e2e/driver_mixin_api.py`): GET the REST JSON,
  assert against `data["lines"]` / `data["recent"]` / key presence.
- BrowserDriver mixin (`driver_mixin_browser.py`): GET the dashboard, locate
  `[data-overview="{key}"]`, assert on its rendered text.
- Extend `tests/e2e/drivers/protocols.py`. Reuse existing auth/todo/files/learning steps for
  setup. No change to `tests/plugin.py` (organizations steps already registered).

## Risks / notes

- `collect_overviews` must not let one failing provider break the dashboard — wrap each
  provider call and skip/empty on error (degrade gracefully). (Decide: skip vs. error.)
- Discovery import cost is one-time at startup, like `register_seeders()`.
