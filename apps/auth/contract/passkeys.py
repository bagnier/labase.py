"""Passkeys, called by the profile. GoTrue owns credentials and challenges.
``users.passkeys_enabled`` gates management and sign-in; GoTrue also needs ``[auth.passkey]`` in
``supabase/config.toml``.
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
