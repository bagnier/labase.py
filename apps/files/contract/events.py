"""Files' business events — uploads, renames, deletes and share-link activity.

CRUD-ish actions derive from the shared abstracts (overriding ``verb`` for the domain word:
*uploaded*, *renamed*); the share-link actions are bespoke (anonymous downloads carry no actor,
a rejected link is ``warning``), so they subclass :class:`~apps.shared.events.BusinessEvent`
directly with an explicit ``kind``. Share tokens are redacted by name in the stored payload.
"""

from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, EntityCreated, EntityDeleted, EntityUpdated


class FileEvent(BusinessEvent):
    entity: ClassVar[str] = "files"
    icon: ClassVar[str] = "folder"


@dataclass(frozen=True, kw_only=True)
class FileUploaded(FileEvent, EntityCreated):
    verb: ClassVar[str] = "uploaded"


@dataclass(frozen=True, kw_only=True)
class FileDeleted(FileEvent, EntityDeleted):
    pass


@dataclass(frozen=True, kw_only=True)
class FileRenamed(FileEvent, EntityUpdated):
    verb: ClassVar[str] = "renamed"
    old_filename: str | None = None
    new_filename: str | None = None


@dataclass(frozen=True, kw_only=True)
class FileShareLinkCreated(FileEvent):
    kind: ClassVar[str] = "files.share_link_created"
    token: str | None = None


@dataclass(frozen=True, kw_only=True)
class FileShareLinkRejected(FileEvent):
    kind: ClassVar[str] = "files.share_link_rejected"
    level: ClassVar[str] = "warning"
    token: str | None = None
    reason: str | None = None


@dataclass(frozen=True, kw_only=True)
class FileShareDownloaded(FileEvent):
    kind: ClassVar[str] = "files.share_downloaded"
    token: str | None = None
