# Impact analysis — Todo list

## Bounded context

The todo list is a standalone context (`app/todo/`). It owns its data and is not shared between users.

## Incoming dependencies

- **`auth/infra/dependencies.py`** — `get_current_user` is imported by `todo/infra/router.py` to protect all endpoints. No changes needed.
- **`profile/`** — not used directly. The link between a todo and its owner is via `auth_user_id` (Supabase UUID), not the `profiles` table.

## Data

New `todos` table:

| Column       | Type        | Notes                                       |
|--------------|-------------|---------------------------------------------|
| `id`         | UUID PK     |                                             |
| `user_id`    | UUID        | `auth.users.id` (Supabase)                  |
| `title`      | TEXT        |                                             |
| `done`       | BOOLEAN     | default `false`                             |
| `position`   | INTEGER     | manual order — new items inserted at top (0)|
| `created_at` | TIMESTAMPTZ |                                             |

- New SQL migration: `supabase/migrations/XXXXXX_create_todos.sql`
- New SQLModel: `app/todo/domain/models.py`

## Manual ordering

- Adding an item inserts at position 0 and shifts all existing positions (+1).
- Moving an item (move X above Y) recalculates positions for affected items.
- Items are returned sorted by `position ASC`.

## UI

- Dedicated page `/todos` (linked from the dashboard).
- HTMX interactions: add, delete, toggle done, drag-and-drop for reordering.

## New files

```
app/todo/
  domain/
    models.py      ← TodoItem, TodoCreate
    service.py     ← add, delete, toggle_done, reorder
  infra/
    repository.py  ← CRUD + reorder (SQLAlchemy)
    router.py      ← GET /todos, POST /todos, DELETE /todos/{id}, PATCH /todos/{id}, POST /todos/reorder
app/templates/todo/
  list.html
supabase/migrations/XXXXXX_create_todos.sql
```

## BDD step — `Given a user is signed in`

This generic step (no credentials) requires a new step definition in `tests/bdd/steps.py` that creates and authenticates an ephemeral user via `driver.sign_in_as_fresh_user()` — to be implemented in both drivers.
