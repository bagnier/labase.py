-- Per-organisation IANA timezone: the wall-clock zone an org's dates are entered
-- and displayed in (the calendar interprets form input in this zone and renders
-- stored UTC instants back into it). Defaults to UTC so existing behaviour is
-- unchanged until an owner picks a zone.
alter table public.organizations add column timezone text not null default 'UTC';
