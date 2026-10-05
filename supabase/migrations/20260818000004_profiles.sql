-- The app-side face of an account: one profile row per `auth.users` row, kept in step by two
-- triggers on GoTrue's own table.

create table public.profiles (
  id          uuid        primary key default public.uuidv7(),
  user_id     uuid        not null unique references auth.users(id) on delete cascade
                          deferrable initially immediate,
  email       text        not null,
  -- Set lazily on first profile access, hence nullable and a partial unique index.
  handle      text,
  -- The image's extension in Storage (avatars/{user_id}.{ext}); null shows the initial.
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

-- Your own profile, and those of the people you share an org with: they appear next to you.
create policy "profiles: own or co-member read"
  on public.profiles for select
  using (
    auth.uid() = user_id
    or user_id in (
      select m.user_id from public.memberships as m where m.org_id in (select public.user_org_ids())
    )
  );

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
-- GoTrue creates users on its own connection, so the fact is written here, atomic with the user
-- row, whatever the creation path. Each worktree schema gets its own copy of this trigger
-- (scripts/provision_schema.py) writing to its own schema only, or the fact would be duplicated.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = '' as $$
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
-- Whatever changes it. Soft-deleted users are skipped: GoTrue scrambles their email, and the
-- deletion flow holds the profile row in its open transaction.
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
