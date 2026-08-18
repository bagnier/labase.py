-- The app-side face of an account: one profile row per `auth.users` row, kept in step by two
-- triggers on GoTrue's own table.

create table public.profiles (
  id          uuid        primary key default public.uuidv7(),
  user_id     uuid        not null unique references auth.users(id) on delete cascade
                          deferrable initially immediate,
  email       text        not null,
  -- Set lazily in Python on first profile access, hence nullable — and hence a *partial* unique
  -- index rather than a unique constraint: several profiles may sit at null at once.
  handle      text,
  -- The blob lives in Storage under avatars/{user_id}.{ext}; this only records that it exists
  -- (and which extension → content type). Presence drives the <img> vs initial-letter fallback.
  avatar_path text,
  version     integer     not null default 1,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create unique index profiles_handle_idx on public.profiles (handle) where handle is not null;
create index profiles_email_idx on public.profiles (email);

create trigger profiles_updated_at
  before update on public.profiles
  for each row execute procedure public.set_updated_at();

alter table public.profiles enable row level security;

create policy "profiles: own read"
  on public.profiles for select
  using (auth.uid() = user_id);

create policy "profiles: own update"
  on public.profiles for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "profiles: own insert"
  on public.profiles for insert
  with check (auth.uid() = user_id);

grant select, insert, update, delete on public.profiles to authenticated;


-- ── Signup: the profile and the first fact, in GoTrue's transaction ─────────────────────────
--
-- Creating a user happens in GoTrue, on its own connection — the app has no session to join and
-- no rollback. So the `auth.user_created` fact is written by this very trigger rather than emitted
-- best-effort afterwards: atomic with the user row, for every creation path (email/password,
-- OAuth, admin API) uniformly. The app's durable `on(UserCreated)` reactions (personal org, admin
-- bootstrap, welcome seeders) then run off the journal.
--
-- `user_id` on the fact is an unconstrained reference (no FK): the journal must survive the
-- user's deletion, so it is never cascade-removed.
--
-- Each worktree schema gets its own clone of this function and its own trigger
-- (`on_auth_user_created__<schema>`, see scripts/provision_schema.py), so the body writes to its
-- own schema only — a cross-schema write would duplicate the fact, the journal having no
-- unique key.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into public.profiles (user_id, email, handle)
    values (new.id, new.email, null) on conflict do nothing;
  insert into public.business_events (app_name, verb, icon, user_id, entity_id, payload)
    values ('auth', 'user_created', 'user-plus', new.id, new.id,
            jsonb_build_object('email', new.email));
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();


-- ── Email change: profiles.email mirrors auth.users.email ───────────────────────────────────
--
-- A trigger covers every change path (app flow, Studio, support scripts) — no app-side sync to
-- forget. Soft-deleted users are skipped: GoTrue's soft delete obfuscates the email, and that
-- scramble must not propagate — besides, the deletion flow removes the profile row in the same
-- open transaction, so this UPDATE would block on it.
create or replace function public.sync_profile_email()
returns trigger
language plpgsql
security definer set search_path = ''
as $$
begin
  update public.profiles set email = new.email where user_id = new.id;
  return new;
end;
$$;

create trigger on_auth_user_email_changed
  after update of email on auth.users
  for each row
  when (old.email is distinct from new.email and new.deleted_at is null)
  execute procedure public.sync_profile_email();
