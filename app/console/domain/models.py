from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.shared import clock
from app.shared.persistence.base import Base


class AppSetting(Base):
    """A persisted *override* for one app setting. Unset keys fall back to the declared default."""

    __tablename__ = "app_settings"

    app: Mapped[str] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str]  # stored as text; coerced by the app's declared SettingDef.type
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: clock.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: clock.now()
    )

    __mapper_args__ = {"version_id_col": version}
