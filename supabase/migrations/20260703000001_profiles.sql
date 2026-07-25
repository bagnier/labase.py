create table public.profiles (
  id           uuid primary key default public.uuidv7(),
  auth_user_id uuid not null unique references auth.users(id) on delete cascade,
  email        text not null,
  handle       text,
  version      integer not null default 1,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

-- Partial unique index: nulls allowed (handle set lazily in Python on first profile access)
create unique index profiles_handle_unique on public.profiles (handle)
  where handle is not null;

create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger profiles_updated_at
  before update on public.profiles
  for each row execute procedure public.set_updated_at();

-- Auto-create profile on user signup; also inserts into test.profiles (silenced if absent)
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into public.profiles (auth_user_id, email, handle)
    values (new.id, new.email, null) on conflict do nothing;
  begin
    insert into test.profiles (auth_user_id, email, handle)
      values (new.id, new.email, null) on conflict do nothing;
  exception when undefined_table then null;
  end;
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

alter table public.profiles enable row level security;

create policy "profiles: own read"
  on public.profiles for select
  using (auth.uid() = auth_user_id);

create policy "profiles: own update"
  on public.profiles for update
  using (auth.uid() = auth_user_id)
  with check (auth.uid() = auth_user_id);

create policy "profiles: own insert"
  on public.profiles for insert
  with check (auth.uid() = auth_user_id);

grant usage on schema public to authenticated;
grant select, insert, update, delete on public.profiles to authenticated;

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'app_user') then
    create role app_user noinherit login password 'app_user_password';
  end if;
end
$$;

grant authenticated to app_user;
