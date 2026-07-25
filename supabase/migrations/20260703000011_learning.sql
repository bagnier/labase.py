-- Spaced-repetition learning context.
-- Catalog (decks/cards) is org-scoped and shared with all members of the org;
-- progress (subscriptions/states/reviews) is additionally per-user (auth.uid()).

create table public.decks (
  id         uuid primary key default public.uuidv7(),
  org_id     uuid not null references public.organizations(id) on delete cascade,
  name       text not null,
  resource   text,
  position   integer not null default 0,
  version    integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (org_id, name)
);

create trigger decks_updated_at
  before update on public.decks
  for each row execute procedure public.set_updated_at();

create table public.cards (
  id          uuid primary key default public.uuidv7(),
  org_id      uuid not null references public.organizations(id) on delete cascade,
  deck_id     uuid not null references public.decks(id) on delete cascade,
  external_id text not null,
  question    text not null,
  answer      text not null,
  resource    text,
  position    integer not null default 0,
  version     integer not null default 1,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (deck_id, external_id)
);

create trigger cards_updated_at
  before update on public.cards
  for each row execute procedure public.set_updated_at();

create table public.deck_subscriptions (
  id         uuid primary key default public.uuidv7(),
  org_id     uuid not null references public.organizations(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  deck_id    uuid not null references public.decks(id) on delete cascade,
  version    integer not null default 1,
  created_at timestamptz not null default now(),
  unique (user_id, deck_id)
);

create table public.card_states (
  id               uuid primary key default public.uuidv7(),
  org_id           uuid not null references public.organizations(id) on delete cascade,
  user_id          uuid not null references auth.users(id) on delete cascade,
  card_id          uuid not null references public.cards(id) on delete cascade,
  level            integer not null default 0,
  last_reviewed_on date,
  next_review_on   date,
  version          integer not null default 1,
  created_at       timestamptz not null default now(),
  unique (user_id, card_id)
);

create index cards_org_deck_position on public.cards (org_id, deck_id, position);
create index deck_subscriptions_user on public.deck_subscriptions (user_id);
create index card_states_user_next on public.card_states (user_id, next_review_on);

-- RLS: catalog readable by org members, writable by org owners; progress private to the acting user.
alter table public.decks enable row level security;
alter table public.cards enable row level security;
alter table public.deck_subscriptions enable row level security;
alter table public.card_states enable row level security;

create policy "decks: org members read"
  on public.decks for select
  using (org_id in (select public.user_orgs()));

create policy "decks: org owner write"
  on public.decks for all
  using (public.user_is_org_owner(org_id))
  with check (public.user_is_org_owner(org_id));

create policy "cards: org members read"
  on public.cards for select
  using (org_id in (select public.user_orgs()));

create policy "cards: org owner write"
  on public.cards for all
  using (public.user_is_org_owner(org_id))
  with check (public.user_is_org_owner(org_id));

create policy "deck_subscriptions: own rows"
  on public.deck_subscriptions for all
  using (org_id in (select public.user_orgs()) and user_id = auth.uid())
  with check (org_id in (select public.user_orgs()) and user_id = auth.uid());

create policy "card_states: own rows"
  on public.card_states for all
  using (org_id in (select public.user_orgs()) and user_id = auth.uid())
  with check (org_id in (select public.user_orgs()) and user_id = auth.uid());

grant select on public.decks, public.cards to authenticated;
grant insert, update, delete on public.decks, public.cards to authenticated;
grant select, insert, update, delete
  on public.deck_subscriptions, public.card_states to authenticated;
grant select, insert, update, delete
  on public.decks, public.cards, public.deck_subscriptions, public.card_states to service_role;

-- Demo seed: a single shared org + the catalog used in the scenarios.
-- Wiring registered users into this org for the live app is a follow-up; the
-- BDD tests build their own org and catalog and do not rely on this seed.
insert into public.organizations (id, name, handle)
values ('00000000-0000-0000-0000-0000000a5e11', 'Shared learning', 'shared-learning')
on conflict (id) do nothing;

insert into public.decks (id, org_id, name, resource, position) values
  ('00000000-0000-0000-0000-0000000dec01', '00000000-0000-0000-0000-0000000a5e11',
   'débuter Python', 'https://docs.python.org/fr/3/tutorial/index.html', 0),
  ('00000000-0000-0000-0000-0000000dec02', '00000000-0000-0000-0000-0000000a5e11',
   'Python avancé', 'https://docs.python.org/fr/3/reference/index.html', 1)
on conflict (org_id, name) do nothing;

insert into public.cards (org_id, deck_id, external_id, question, answer, resource, position) values
  ('00000000-0000-0000-0000-0000000a5e11', '00000000-0000-0000-0000-0000000dec01', 'PY001',
   'Comment déclare-t-on une variable en Python ?', 'nom_variable = valeur',
   'https://docs.python.org/fr/3/tutorial/introduction.html#using-python-as-a-calculator', 0),
  ('00000000-0000-0000-0000-0000000a5e11', '00000000-0000-0000-0000-0000000dec01', 'PY002',
   'Quelle est la syntaxe d''une boucle for en Python ?', 'for element in sequence:',
   'https://docs.python.org/fr/3/tutorial/controlflow.html#for-statements', 1),
  ('00000000-0000-0000-0000-0000000a5e11', '00000000-0000-0000-0000-0000000dec01', 'PY003',
   'Comment définit-on une fonction en Python ?', 'def nom_fonction(paramètres):',
   'https://docs.python.org/fr/3/tutorial/controlflow.html#defining-functions', 2),
  ('00000000-0000-0000-0000-0000000a5e11', '00000000-0000-0000-0000-0000000dec02', 'PYA01',
   'Qu''est-ce qu''un décorateur en Python ?', '@nom_decorateur',
   'https://docs.python.org/fr/3/glossary.html#term-decorator', 0),
  ('00000000-0000-0000-0000-0000000a5e11', '00000000-0000-0000-0000-0000000dec02', 'PYA02',
   'Comment définir une classe en Python ?', 'class NomClasse:',
   'https://docs.python.org/fr/3/tutorial/classes.html', 1)
on conflict (deck_id, external_id) do nothing;
