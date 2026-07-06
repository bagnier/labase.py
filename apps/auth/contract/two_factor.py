"""Two-factor (TOTP) — the auth surface the profile section calls.

GoTrue owns factors, challenges and AAL; the app wires the two UI moments
(enrolment on the profile, step-up at sign-in). The ``users.two_factor_enabled``
setting gates both — switching it off also bypasses the sign-in challenge,
which is the admin escape hatch for lost authenticators.
"""

from apps.auth.domain.service import (
    TotpEnrollment as TotpEnrollment,
)
from apps.auth.domain.service import (
    TotpError as TotpError,
)
from apps.auth.domain.service import (
    enroll_totp as enroll_totp,
)
from apps.auth.domain.service import (
    totp_challenge as totp_challenge,
)
from apps.auth.domain.service import (
    verified_totp_factor as verified_totp_factor,
)
from apps.auth.domain.service import (
    verify_totp as verify_totp,
)
