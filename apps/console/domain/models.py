"""The console routes' bodies and answers."""

from typing import TypedDict

from pydantic import BaseModel, ConfigDict

from apps.console.domain.technical import EnvVar, ProcessSnapshot
from apps.shared.settings.live import SettingType


class AdminGrant(BaseModel):
    email: str = ""


class AdminFlag(BaseModel):
    """``false`` comes from the hidden input the ticked box overrides."""

    is_admin: bool = False


class OrgOverrideCreate(BaseModel):
    org_handle: str = ""
    key: str = ""
    value: str = ""


class SettingValue(BaseModel):
    """As text; the declared type coerces or refuses it."""

    value: str = ""


# ── What the console screens answer ─────────────────────────────────────────────────────────


class SettingView(TypedDict):
    key: str
    type: SettingType
    label: str
    value: str
    org_overridable: bool


class EventsByApp(TypedDict):
    app: str
    kinds: list[str]


class OverviewRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    key: str
    title: str
    disabled: bool


class ConsoleHome(BaseModel):
    overviews: list[OverviewRow]


class AdminRow(BaseModel):
    email: str
    is_admin: bool


class AdminList(BaseModel):
    admins: list[AdminRow]


class SettingsPage(BaseModel):
    theme: list[SettingView]
    env_vars: list[EnvVar]
    process: ProcessSnapshot
    technical_config: dict[str, str]


class Reaction(BaseModel):
    app: str
    name: str


class EventRow(BaseModel):
    kind: str
    owner: str
    reactions: list[Reaction]


class EventCatalogue(BaseModel):
    events: list[EventRow]
    by_app: list[EventsByApp]


class OverrideRow(BaseModel):
    key: str
    value: str
    org_id: str
    handle: str


class Link(BaseModel):
    label: str
    href: str


class AppPage(BaseModel):
    app: str
    settings: list[SettingView]
    org_overrides: list[OverrideRow]
    supabase: dict[str, str] | None
    links: list[Link]


class OrgOverrides(BaseModel):
    app: str
    org_overrides: list[OverrideRow]


class SettingsUpdated(BaseModel):
    app: str
    settings: list[SettingView]
