-- Fulltext search over pages: a stored, generated tsvector across title + body,
-- indexed with GIN. The list screen ranks matches with ts_rank / websearch_to_tsquery.
-- Immutable expression (constant 'english' regconfig), so it is valid as a generated column.
alter table public.pages
  add column search_vector tsvector
  generated always as (
    to_tsvector('english', coalesce(title, '') || ' ' || coalesce(content, ''))
  ) stored;

create index if not exists pages_search_vector_idx
  on public.pages using gin (search_vector);
