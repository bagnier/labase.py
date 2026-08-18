-- Demo app — spaced repetition, the most domain-heavy example.
-- Delete this file with apps/learning/ when real work starts.
--
-- The catalog (decks, cards) is org-scoped and shared with every member; progress (subscriptions,
-- card states) is additionally per-user.

create table public.decks (
  id           uuid        primary key default public.uuidv7(),
  org_id       uuid        not null references public.organizations(id) on delete cascade,
  name         text        not null,
  resource_url text,
  position     integer     not null default 0,
  version      integer     not null default 1,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  unique (org_id, name)
);

create trigger decks_updated_at
  before update on public.decks
  for each row execute procedure public.set_updated_at();


create table public.cards (
  id           uuid        primary key default public.uuidv7(),
  org_id       uuid        not null references public.organizations(id) on delete cascade,
  deck_id      uuid        not null references public.decks(id) on delete cascade,
  external_id  text        not null,
  question     text        not null,
  answer       text        not null,
  resource_url text,
  position     integer     not null default 0,
  version      integer     not null default 1,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  unique (deck_id, external_id)
);

create index cards_org_deck_position_idx on public.cards (org_id, deck_id, position);

create trigger cards_updated_at
  before update on public.cards
  for each row execute procedure public.set_updated_at();


create table public.deck_subscriptions (
  id         uuid        primary key default public.uuidv7(),
  org_id     uuid        not null references public.organizations(id) on delete cascade,
  user_id    uuid        not null references auth.users(id) on delete cascade
                         deferrable initially immediate,
  deck_id    uuid        not null references public.decks(id) on delete cascade,
  version    integer     not null default 1,
  created_at timestamptz not null default now(),
  unique (user_id, deck_id)
);

create index deck_subscriptions_user_id_idx on public.deck_subscriptions (user_id);


-- Per-user progress on a card. Absence ⇒ level 0 (never studied).
create table public.card_states (
  id               uuid        primary key default public.uuidv7(),
  org_id           uuid        not null references public.organizations(id) on delete cascade,
  user_id          uuid        not null references auth.users(id) on delete cascade
                               deferrable initially immediate,
  card_id          uuid        not null references public.cards(id) on delete cascade,
  level            integer     not null default 0,
  last_reviewed_on date,
  next_review_on   date,
  version          integer     not null default 1,
  created_at       timestamptz not null default now(),
  unique (user_id, card_id)
);

create index card_states_user_next_review_idx on public.card_states (user_id, next_review_on);


-- RLS: catalog readable by org members and writable by org owners; progress private to the
-- acting user.
alter table public.decks              enable row level security;
alter table public.cards              enable row level security;
alter table public.deck_subscriptions enable row level security;
alter table public.card_states        enable row level security;

create policy "decks: member read"
  on public.decks for select
  using (org_id in (select public.user_org_ids()));

create policy "decks: owner all"
  on public.decks for all
  using (public.user_is_org_owner(org_id))
  with check (public.user_is_org_owner(org_id));

create policy "cards: member read"
  on public.cards for select
  using (org_id in (select public.user_org_ids()));

create policy "cards: owner all"
  on public.cards for all
  using (public.user_is_org_owner(org_id))
  with check (public.user_is_org_owner(org_id));

create policy "deck_subscriptions: self all"
  on public.deck_subscriptions for all
  using (org_id in (select public.user_org_ids()) and user_id = auth.uid())
  with check (org_id in (select public.user_org_ids()) and user_id = auth.uid());

create policy "card_states: self all"
  on public.card_states for all
  using (org_id in (select public.user_org_ids()) and user_id = auth.uid())
  with check (org_id in (select public.user_org_ids()) and user_id = auth.uid());

grant select, insert, update, delete on public.decks              to authenticated;
grant select, insert, update, delete on public.cards              to authenticated;
grant select, insert, update, delete on public.deck_subscriptions to authenticated;
grant select, insert, update, delete on public.card_states        to authenticated;

grant select, insert, update, delete
  on public.decks, public.cards, public.deck_subscriptions, public.card_states to service_role;
