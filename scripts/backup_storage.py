"""Back up every object in the Supabase Storage bucket to a local directory.

Storage bytes are NOT part of a Postgres dump (see docs/backups.md), so they need
their own backup. Run on a schedule against production:

    make backup-storage DEST=/backups/storage ENV_FILE=.env.production

Mirrors the whole bucket into ``DEST/<bucket>/<object-path>``, recursing into
folders. Idempotent: re-runs overwrite, so the destination stays a full mirror.
"""

import argparse
import asyncio
from pathlib import Path
from typing import Any

from apps.shared.persistence.storage import admin_storage, bucket


async def _walk(store: Any, prefix: str) -> list[str]:
    """Return every object path under ``prefix`` (recursing into folders).

    Supabase Storage lists a single level; folder entries carry a null ``id``.
    """
    paths: list[str] = []
    for entry in await store.list(prefix):
        name = entry["name"]
        path = f"{prefix}/{name}" if prefix else name
        if entry.get("id") is None:  # a folder, not an object
            paths.extend(await _walk(store, path))
        else:
            paths.append(path)
    return paths


async def backup(dest: Path) -> int:
    bucket_name = bucket()
    store = admin_storage().from_(bucket_name)
    paths = await _walk(store, "")
    root = dest / bucket_name
    for path in paths:
        data = await store.download(path)
        out = root / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    return len(paths)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mirror the Supabase Storage bucket to disk.")
    parser.add_argument("--dest", default="backups/storage", help="destination directory")
    args = parser.parse_args()
    count = asyncio.run(backup(Path(args.dest)))
    print(f"backed up {count} object(s) to {args.dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
