"""Profile's business events — display/account actions the profile page owns.

Only genuinely *profile* concerns live here: the avatar, the public handle, and deleting one's own
account. Security actions (password, email, passkeys, 2FA) are auth-domain — see
``apps.auth.contract.events``. All are user-scoped (``user_id`` = the account holder,
``org_id`` = ``None``); the persister on the base records them.
"""

from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent


class ProfileEvent(BusinessEvent):
    app_name: ClassVar[str] = "profile"
    icon: ClassVar[str] = "user-circle"


@dataclass(frozen=True, kw_only=True)
class AccountDeleted(ProfileEvent):
    verb: ClassVar[str] = "account_deleted"


@dataclass(frozen=True, kw_only=True)
class AvatarUpdated(ProfileEvent):
    verb: ClassVar[str] = "avatar_updated"


@dataclass(frozen=True, kw_only=True)
class HandleChanged(ProfileEvent):
    verb: ClassVar[str] = "handle_changed"
    new_handle: str
