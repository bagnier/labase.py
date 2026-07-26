-- Promote business_events.entity_id from text to uuid — the weak, table-agnostic FK to the
-- concerned entity. Every primary key is a UUIDv7, so entity_id is always a uuid pk in practice;
-- typing the column as uuid aligns it with its sibling scopes user_id/org_id (already uuid), drops
-- the str() cast on the write path, and lets the reader filter without stringifying. The column
-- stays a *weak* reference (no FK constraint): it points at whatever table the event concerns.

-- Backfill the folded user-target events: their subject used to live in payload as target_user_id
-- (a uuid string); it is now the generic entity_id. Runs before the type change while the values
-- are still comparable as text; a fresh database has no such rows (a clean no-op).
update public.business_events
   set entity_id = payload ->> 'target_user_id'
 where entity_id is null
   and payload ? 'target_user_id';

-- All surviving entity_id values are uuid strings; the cast is total. ('' would be null already.)
alter table public.business_events
  alter column entity_id type uuid using nullif(entity_id, '')::uuid;

-- The signup trigger seeded entity_id as new.id::text for the text column — now write the uuid
-- straight. CREATE OR REPLACE so each schema's clone (provision_schema) inherits the fixed body.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into public.profiles (auth_user_id, email, handle)
    values (new.id, new.email, null) on conflict do nothing;
  insert into public.business_events (level, kind, icon, user_id, entity_id, payload)
    values ('info', 'auth.user_created', 'user-plus', new.id, new.id,
            jsonb_build_object('email', new.email));
  begin
    insert into test.profiles (auth_user_id, email, handle)
      values (new.id, new.email, null) on conflict do nothing;
  exception when undefined_table then null;
  end;
  return new;
end;
$$;
