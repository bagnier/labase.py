"""Passkeys (WebAuthn) — the auth surface the profile section calls.

GoTrue owns credentials and challenges (beta API, raw HTTP — no supabase-py
support yet); the app wires the two UI moments: management on the profile,
discoverable sign-in on the login page. The ``users.passkeys_enabled`` setting
gates both, and the server-side feature also needs ``[auth.passkey]`` enabled
in ``supabase/config.toml``.
"""

from apps.auth.domain.service import (
    PasskeyError as PasskeyError,
)
from apps.auth.domain.service import (
    delete_passkey as delete_passkey,
)
from apps.auth.domain.service import (
    list_passkeys as list_passkeys,
)
from apps.auth.domain.service import (
    passkey_registration_options as passkey_registration_options,
)
from apps.auth.domain.service import (
    verify_passkey_registration as verify_passkey_registration,
)
