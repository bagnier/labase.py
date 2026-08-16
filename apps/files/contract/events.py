"""Files' business events — uploads, renames, deletes and share-link activity.

CRUD-ish actions derive from the shared abstracts (overriding ``verb`` for the domain word:
*uploaded*, *renamed*); the share-link actions are bespoke (anonymous downloads carry no actor,
a rejected link is ``warning``), so they subclass :class:`~apps.shared.events.BusinessEvent`
directly with an explicit ``kind``. Share tokens are redacted by name in the stored payload.
"""

from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, EntityCreated, EntityDeleted, EntityUpdated, OrgScoped


class FileEvent(BusinessEvent):
    app_name: ClassVar[str] = "files"
    icon: ClassVar[str] = "folder"


@dataclass(frozen=True, kw_only=True)
class FileUploaded(OrgScoped, FileEvent, EntityCreated):
    verb: ClassVar[str] = "uploaded"


@dataclass(frozen=True, kw_only=True)
class FileDeleted(OrgScoped, FileEvent, EntityDeleted):
    pass


@dataclass(frozen=True, kw_only=True)
class FileRenamed(OrgScoped, FileEvent, EntityUpdated):
    verb: ClassVar[str] = "renamed"
    # the new name is the subject's name (entity_name); only the previous one is extra payload
    old_filename: str


@dataclass(frozen=True, kw_only=True)
class FileShareLinkCreated(OrgScoped, FileEvent):
    verb: ClassVar[str] = "share_link_created"


@dataclass(frozen=True, kw_only=True)
class FileShareDownloaded(OrgScoped, FileEvent):
    verb: ClassVar[str] = "share_downloaded"
