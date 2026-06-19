"""The files context's dashboard overview.

Public surface consumed by the composition root (:mod:`app.overviews`). Org-scoped:
counts every file in the org and sums their stored size.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.files.infra.repository import OrgFileRepository
from app.organizations.contract.overviews import Overview

_RECENT = 3


def _human_size(num: int) -> str:
    size = float(num)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:g} {unit}"
        size /= 1024
    return f"{size:g} GB"


async def overview(session: AsyncSession, org_id: uuid.UUID) -> Overview:
    files = await OrgFileRepository(session, org_id).all()
    if files:
        total = sum(f.size_bytes for f in files)
        lines = [f"{len(files)} files", _human_size(total)]
    else:
        lines = ["No files yet"]
    return Overview(
        key="files",
        title="Files",
        icon="folder",
        href="files",
        template="files/_overview.html",
        data={"lines": lines, "recent": [f.filename for f in files[:_RECENT]]},
    )
