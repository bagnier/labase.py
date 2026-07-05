import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.persistence.base import Base, Timestamped, Versioned

# Stored form of a boolean setting value.
BOOL_TRUE = "true"
BOOL_FALSE = "false"

# Reserved key for an app's on/off switch, stored like any other setting value.
ENABLED_KEY = "enabled"


class AppSetting(Base, Versioned, Timestamped):
    """The persisted value of one app setting — seeded on declaration, edited from the console."""

    __tablename__ = "app_settings"

    app: Mapped[str] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str]  # stored as text; coerced by the app's declared SettingDef.type


class OrgAppSetting(Base, Versioned, Timestamped):
    """A per-organisation override of one app setting — managed from the console.

    Unset (app, key, org) triples fall back to the server-wide `AppSetting` value.
    """

    __tablename__ = "org_app_settings"

    app: Mapped[str] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    value: Mapped[str]
