-- Profiles table linked to Supabase auth.users
create table public.profiles (
  id          uuid primary key default gen_random_uuid(),
  auth_user_id uuid not null unique references auth.users(id) on delete cascade,
  email       text not null,
  display_name text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

-- Auto-update updated_at
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

-- RLS: users can only read/update their own profile
alter table public.profiles enable row level security;

create policy "profiles: own read"
  on public.profiles for select
  using (auth.uid() = auth_user_id);

create policy "profiles: own update"
  on public.profiles for update
  using (auth.uid() = auth_user_id);

-- Auto-create profile on user signup
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into public.profiles (auth_user_id, email)
  values (new.id, new.email);
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();
