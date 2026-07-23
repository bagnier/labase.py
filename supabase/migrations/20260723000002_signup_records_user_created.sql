-- Record the ``auth.user_created`` business event at the source: the signup trigger.
--
-- Creating a user happens in GoTrue, on its own connection and transaction — the app has no session
-- to join and no rollback. So the app used to emit ``UserCreated`` best-effort/detached, which raced
-- the event tailer and escaped a test's rolled-back transaction. Instead, the same AFTER INSERT
-- trigger that seeds the profile now also writes the ``UserCreated`` fact onto the trail — atomic
-- with the user row, in GoTrue's transaction, for every creation path (email/password, OAuth, admin
-- API) uniformly. The app's durable ``on(UserCreated)`` reactions (personal org, admin bootstrap,
-- welcome seeders) run off the trail unchanged.
--
-- The event goes to *this schema's* business_events only (no cross-schema write): the trail has no
-- unique key, so a dual-write would duplicate. Each schema's cloned trigger (see provision_schema)
-- writes its own row exactly once. ``user_id`` is an unconstrained reference (no FK) — the trail
-- must survive the user's deletion, so it is never cascade-removed; test teardown sweeps it by id.

create or replace function public.handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into public.profiles (auth_user_id, email, handle)
    values (new.id, new.email, null) on conflict do nothing;
  insert into public.business_events (level, kind, icon, user_id, entity_id, payload)
    values ('info', 'auth.user_created', 'user-plus', new.id, new.id::text,
            jsonb_build_object('email', new.email));
  begin
    insert into test.profiles (auth_user_id, email, handle)
      values (new.id, new.email, null) on conflict do nothing;
  exception when undefined_table then null;
  end;
  return new;
end;
$$;
