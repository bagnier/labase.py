"""Per-app settings — cross-cutting, like :mod:`apps.shared.events.bus`/``email``/``queue``: every
app declares its settings from its own ``mount()``, so the mechanism lives here rather than in a
bounded context ``Host`` couldn't reach.

Each app, in ``mount()``, declares the settings it needs via ``host.register_settings(...)`` —
the single call that makes them editable in the console admin page (:mod:`apps.console`), seeds
their defaults, and registers the app's live :class:`AppSettings` handle in the process-wide
registry (:func:`get_settings`). The ``enabled`` gate a toggleable app checks right after is
just a declared setting (via :func:`feature_switch`), read off the returned handle.

A contract never exports a handle (README: a contract never exports a settings handle).
Three
sanctioned reads, chosen by *how the org is known*:

- **Request under** ``/{org_handle}`` — the ``app_settings(name)`` dependency
  (:mod:`apps.organizations.contract.current`): server values overlaid with the URL org's
  overrides (plain server values on any other route).
- **Org known from data, not the URL** — ``get_settings(name).for_org(session, org_id)``
  directly, e.g. a share-link download whose org comes from the file row, not a path param.
- **No org dimension** — ``get_settings(name)`` (direct attribute or ``.view()``) for
  server-wide values and all non-request code (mount, queue tasks, event handlers, helpers).

The DB stores *the value* of a setting (CRUD), nothing layered on top. A :class:`SettingDef`'s
``default`` is merely the value seeded on first declaration. Setting *metadata* (type, label,
Supabase link) lives in memory — re-declared on every ``mount()``; only the value is persisted.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.events import BusinessEvent
from apps.shared.settings.store import (
    BOOL_TRUE,
    ENABLED_KEY,
    OrgAppSetting,
    read_values,
    seed_values,
)
from apps.shared.vocabulary import AppName, PhosphorIcon

SettingType = Literal["string", "number", "boolean"]


class SettingRow(TypedDict):
    """A declared setting paired with its current stored value, as display strings — the shape
    the console settings templates iterate (and the logs screen serves alongside its timeline)."""

    key: str
    type: SettingType
    label: str
    value: str


@dataclass(frozen=True)
class SettingDef:
    """One declared setting: its key, its declared type, and the value seeded the first time the
    app declares it (stored as text, coerced by ``type``).

    Some settings are meaningful only server-wide — the promoted org handle, say — where a
    per-organisation override makes no sense at all. Those set ``org_overridable=False``, which
    drops them from the console's per-org override UI and makes the override endpoint reject them.
    """

    key: str
    type: SettingType
    default: str
    label: str
    org_overridable: bool = True


def feature_switch(label: str = "Enabled (applies on restart)") -> SettingDef:
    """The reserved on/off switch a toggleable app declares — an ordinary boolean setting.

    Global by nature (it applies on restart, across all orgs), so not org-overridable.
    """
    return SettingDef(ENABLED_KEY, "boolean", "true", label, org_overridable=False)


@dataclass(frozen=True)
class SupabaseLink:
    """A deep link into Supabase Studio for advanced, out-of-console management.

    The console prefixes the derived Studio base URL onto either:
    - ``path`` — a static Studio-relative fragment (e.g. ``auth/users``,
      ``storage/buckets/org-files``); or
    - ``table`` — a Postgres table name; the console resolves its OID at request time and
      points the Studio *table editor* straight at it (Studio has no name-based route).
    """

    label: str
    path: str = ""
    table: str | None = None


@dataclass(frozen=True)
class ConsoleLink:
    """A console screen an app contributes beyond its settings page (e.g. ``/console/accounts``).

    Declared at mount like everything else, so the console overview and the app's
    settings page link to it — and deleting the app removes the link.
    """

    label: str
    href: str


@dataclass(frozen=True)
class SettingsDeclaration:
    """What an app declares at mount: the in-memory metadata the console renders and validates,
    bundled so :meth:`Host.register_settings` takes one payload instead of a growing kwarg list."""

    app_name: AppName
    defs: list[SettingDef] = field(default_factory=list)
    supabase: SupabaseLink | None = None
    links: tuple[ConsoleLink, ...] = ()


SettingValue = str | int | bool


def _coerce(kind: SettingType, raw: str) -> SettingValue:
    if kind == "number":
        try:
            return int(raw)
        except ValueError:
            return raw
    if kind == "boolean":
        return raw == BOOL_TRUE
    return raw


def _typed(defs: list[SettingDef], values: dict[str, str]) -> dict[str, SettingValue]:
    """``values`` coerced to the type each :class:`SettingDef` declares — the console's job, so
    the apps reading them never have to.

    Every declared setting is present, falling back to its declared default when not yet
    persisted; extra persisted keys (no declaration) pass through as text.
    """
    typed: dict[str, SettingValue] = {
        d.key: _coerce(d.type, values.get(d.key, d.default)) for d in defs
    }
    for key, raw in values.items():
        typed.setdefault(key, raw)
    return typed


def _lookup(values: dict[str, SettingValue], name: str) -> Any:
    """Attribute access over a coerced values dict — shared by :class:`AppSettings` and
    :class:`SettingsView` so there's exactly one place that implements this ergonomic."""
    if name.startswith("_"):
        raise AttributeError(name)
    try:
        return values[name]
    except KeyError:
        raise AttributeError(name) from None


class SettingsView:
    """A read-only, already-merged settings snapshot — same attribute ergonomics as
    :class:`AppSettings` (``view.max_upload_mb``), returned by :meth:`AppSettings.for_org`
    / :meth:`AppSettings.merged_for_org` so callers never see a raw dict."""

    __slots__ = ("values",)

    def __init__(self, values: dict[str, SettingValue]) -> None:
        self.values = values

    def __getattr__(self, name: str) -> Any:
        return _lookup(self.values, name)


@dataclass(frozen=True, kw_only=True)
class SettingsChanged(BusinessEvent):
    """A server-wide setting of ``target_app`` was edited in the console.

    One fact, two faces: it is **persisted** on the journal as the record of who changed what
    (``user_id`` + ``key``/``value``, the platform peer of the per-org override events), *and*
    it drives cross-instance **propagation** — it carries the full fresh ``values`` so each app's
    :meth:`AppSettings.reload` (subscribed via ``spread``) re-points its in-memory handle. Generic:
    the console emits it knowing nothing of what the keys mean; each app filters on its own id.
    Server-wide, so ``org_id`` stays ``None``.
    """

    verb: ClassVar[str] = "server_changed"
    app_name: ClassVar[AppName] = "settings"
    icon: ClassVar[PhosphorIcon] = "gear"

    # Not the class-level ``app_name``, which names the app owning this *kind*: the fact is owned
    # by "settings" and speaks about another app.
    target_app: AppName
    key: str
    value: str
    values: dict[str, str] = field(default_factory=dict)


class AppSettings:
    """An app's settings: read a setting as an attribute — ``settings.max_upload_mb`` — and get
    its declared-typed value (``str``/``int``/``bool``); coercion is the console's job, so apps
    never do it.

    A handle is never half-built: both the declaration and the values are required at
    construction, so no reader has to ask whether binding has happened yet. Live handles come from
    ``host.register_settings(declaration)`` — which seeds values, does the initial read, registers
    the handle in the process registry (:func:`get_settings`) and subscribes it to
    ``SettingsChanged``, all in one call from ``mount()``. Direct construction (no I/O) remains for
    tests; an empty ``raw`` means "nothing persisted yet", and declared defaults answer every read.
    """

    def __init__(self, raw: dict[str, str], declaration: SettingsDeclaration) -> None:
        self._raw_values = raw
        self._declaration = declaration
        self._typed: dict[str, SettingValue] | None = None  # None = stale, recoerce on read

    @property
    def declaration(self) -> SettingsDeclaration:
        return self._declaration

    @declaration.setter
    def declaration(self, declaration: SettingsDeclaration) -> None:
        self._declaration = declaration
        self._typed = None

    @property
    def _defs(self) -> list[SettingDef]:
        return self._declaration.defs

    @property
    def _raw(self) -> dict[str, str]:
        return self._raw_values

    @_raw.setter
    def _raw(self, raw: dict[str, str]) -> None:
        # The one write path — read, reload, a test poking values in — so the cache cannot survive
        # a value change.
        self._raw_values = raw
        self._typed = None

    def read(self) -> None:
        """Read current values from the DB — call once at ``mount`` (sync, before the serving
        loop; :func:`read_values` drives :func:`asyncio.run`, which can't run inside it)."""
        self._raw = read_values(self._declaration.app_name)

    def snapshot(self) -> dict[str, str]:
        """This handle's values, copied — the in-memory half of a rollback. See
        :func:`settings_snapshot`."""
        return dict(self._raw)

    def restore(self, raw: dict[str, str]) -> None:
        """Re-point this handle at a :meth:`snapshot`, no I/O. See :func:`settings_snapshot`."""
        self._raw = raw

    @property
    def values(self) -> dict[str, SettingValue]:
        if self._typed is None:
            self._typed = _typed(self._defs, self._raw)
        return self._typed

    def view(self) -> SettingsView:
        """The server-wide values as a read-only view — what a request outside any org gets."""
        return SettingsView(self.values)

    def rows(self) -> list[SettingRow]:
        """Every declared setting with its current value as a render-ready display string.

        Stored values are already normalised text (``validate`` normalises on write; defaults are
        declared as text), so no coercion is needed — this is the same shape the console settings
        page iterates, exposed on the settings model so callers never hand-roll it."""
        raw = self._raw
        return [
            SettingRow(key=d.key, type=d.type, label=d.label, value=str(raw.get(d.key, d.default)))
            for d in self._defs
        ]

    def __getattr__(self, name: str) -> Any:
        """A setting's value, coerced to its declared ``str``/``int``/``bool``. Statically ``Any``:
        which of the three it is depends on the key, and only setting keys reach here."""
        return _lookup(self.values, name)

    async def reload(self, event: SettingsChanged) -> None:
        """Console event handler: adopt the fresh values when they're for this app."""
        if event.target_app == self._declaration.app_name:
            self._raw = event.values

    def merged_for_org(self, overrides: dict[str, str]) -> SettingsView:
        """Server-wide values overlaid with per-org overrides, coerced to declared types."""
        return SettingsView(_typed(self._defs, {**self._raw, **overrides}))

    async def for_org(self, session: AsyncSession, org_id: uuid.UUID) -> SettingsView:
        """This org's effective settings — the server value unless the console overrode it.

        Read fresh per call through the caller's session: the RLS policy lets org
        members read their own org's overrides, so the regular request session works
        and no cache needs invalidating across instances.
        """
        return self.merged_for_org(await org_values(session, self.declaration.app_name, org_id))


async def org_values(session: AsyncSession, app_name: str, org_id: uuid.UUID) -> dict[str, str]:
    """Raw per-org overrides of `app` for `org_id` (RLS: members see their own org)."""
    rows = await session.execute(
        select(OrgAppSetting.key, OrgAppSetting.value).where(
            OrgAppSetting.app_name == app_name, OrgAppSetting.org_id == org_id
        )
    )
    return {key: value for key, value in rows.all()}


# One entry per declared app — the single place a live ``AppSettings`` exists. Populated by
# ``Host.register_settings`` at mount and reused on re-mount (tests build fresh ``Host``\ s), so
# ``get_settings`` consumers keep a stable handle.
_registry: dict[str, AppSettings] = {}


def get_settings(app_name: str) -> AppSettings:
    """The live server-wide handle of a mounted app. Its direct-attribute read
    (``get_settings("x").flag``) is sync and I/O-free but **server-wide only** — for non-request
    code (mount, queue tasks, event handlers) and settings with no org dimension.

    For a request's *effective* values use the ``app_settings`` dependency
    (:mod:`apps.organizations.contract.current`); when the org is known from data rather than
    ``/{org_handle}``, call ``for_org(session, org_id)`` on this handle. Those overlays read org
    overrides from the DB (behind RLS) and so are async — which is why no ``org_id`` fits here."""
    try:
        return _registry[app_name]
    except KeyError:
        raise KeyError(f"no settings registered for app '{app_name}' — is it mounted?") from None


def settings_snapshot() -> dict[str, dict[str, str]]:
    """Every registered handle's values, copied.

    A console edit does two things: it writes the ``app_settings`` row *and* re-points these
    in-memory handles, because ``SettingsChanged`` fans out through ``spread``. A test that rolls
    its transaction back undoes the row but not the handle — so a scenario turning a feature off
    leaves every scenario after it in the process running on that value. Snapshot before, restore
    after, and the two halves come back together.
    """
    return {name: handle.snapshot() for name, handle in _registry.items()}


def restore_settings(snapshot: dict[str, dict[str, str]]) -> None:
    """Re-point every handle at a :func:`settings_snapshot`."""
    for name, raw in snapshot.items():
        handle = _registry.get(name)
        if handle is not None:
            handle.restore(raw)


def bind_settings(declaration: SettingsDeclaration) -> AppSettings:
    """Seed missing values, then create (or reuse) the app's registry handle, bind
    ``declaration`` and read its current persisted values — everything
    :meth:`Host.register_settings` does that doesn't touch ``host`` itself (indexing into
    ``host.settings_handles``, subscribing to ``host.events``)."""
    seed_values(declaration.app_name, {d.key: d.default for d in declaration.defs})
    settings = _registry.setdefault(declaration.app_name, AppSettings({}, declaration))
    settings.declaration = declaration
    settings.read()
    return settings
