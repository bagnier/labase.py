-- Profile avatar: the blob lives in Storage under avatars/{auth_user_id}.{ext};
-- the column only records that (and which extension → content type). Presence
-- drives the <img> vs initial-letter fallback.
alter table public.profiles add column avatar_path text;
