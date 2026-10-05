"""Files' facts: uploads, renames, deletes, share links. A share download has no actor. A share
token is never carried, only the file's id and name.
"""

from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, EntityCreated, EntityDeleted, EntityUpdated, OrgScoped
from apps.shared.vocabulary import AppName, PhosphorIcon


class FileEvent(BusinessEvent):
    app_name: ClassVar[AppName] = "files"
    icon: ClassVar[PhosphorIcon] = "folder"


@dataclass(frozen=True, kw_only=True)
class FileUploaded(OrgScoped, FileEvent, EntityCreated):
    verb: ClassVar[str] = "uploaded"


@dataclass(frozen=True, kw_only=True)
class FileDeleted(OrgScoped, FileEvent, EntityDeleted):
    pass


@dataclass(frozen=True, kw_only=True)
class FileRenamed(OrgScoped, FileEvent, EntityUpdated):
    verb: ClassVar[str] = "renamed"
    # entity_name is the new name
    old_filename: str


@dataclass(frozen=True, kw_only=True)
class FileShareLinkCreated(OrgScoped, FileEvent):
    verb: ClassVar[str] = "share_link_created"


@dataclass(frozen=True, kw_only=True)
class FileShareDownloaded(OrgScoped, FileEvent):
    verb: ClassVar[str] = "share_downloaded"
