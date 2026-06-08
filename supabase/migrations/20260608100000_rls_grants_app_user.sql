-- Rôle applicatif pour le trafic utilisateur (RLS actif, pas de BYPASSRLS)
-- Hérite de `authenticated` pour que auth.uid() et les policies Supabase fonctionnent.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'app_user') then
    create role app_user noinherit login password 'app_user_password';
  end if;
end
$$;

grant authenticated to app_user;

-- Schéma public
grant usage on schema public to authenticated;
grant select, insert, update, delete on public.profiles to authenticated;
grant select, insert, update, delete on public.todos     to authenticated;

-- Politique INSERT manquante sur profiles (nécessaire pour que bind_rls permette l'écriture)
do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'profiles' and policyname = 'profiles: own insert'
  ) then
    execute $p$
      create policy "profiles: own insert"
        on public.profiles for insert
        with check (auth.uid() = auth_user_id)
    $p$;
  end if;
end
$$;

-- Schéma test (utilisé par les tests automatisés)
do $$
begin
  if exists (select 1 from information_schema.schemata where schema_name = 'test') then
    execute 'grant usage on schema test to authenticated';
    execute 'grant select, insert, update, delete on all tables in schema test to authenticated';
    execute 'alter default privileges in schema test grant select, insert, update, delete on tables to authenticated';
  end if;
end
$$;
