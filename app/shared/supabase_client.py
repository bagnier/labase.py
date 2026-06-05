from supabase import Client, create_client

from app.shared.config import settings

# Anon client — for user-facing auth operations (respects RLS)
supabase: Client = create_client(settings.supabase_url, settings.supabase_anon_key)

# Admin client — for server-side operations that bypass RLS
supabase_admin: Client = create_client(settings.supabase_url, settings.supabase_service_role_key)
