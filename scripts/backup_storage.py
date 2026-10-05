"""Mirror the Storage bucket into ``DEST/<bucket>/<path>``: a Postgres dump does not hold the
bytes (docs/backups.md). Re-runs overwrite. On a schedule, against production:

    make backup-storage DEST=/backups/storage ENV_FILE=.env.production
"""

import argparse
import asyncio
import os
from pathlib import Path
from typing import Any

from apps.shared.persistence.storage import admin_storage, bucket
from apps.shared.settings.env import get_technical_settings
from scripts.envfile import apply_host_overrides


async def _list_all(store: Any, prefix: str) -> list[dict[str, Any]]:
    """Every entry of one folder, page after page."""
    page_size = get_technical_settings().backup_storage_page_size
    entries: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = await store.list(prefix, {"limit": page_size, "offset": offset})
        entries.extend(page)
        if len(page) < page_size:
            return entries
        offset += page_size


async def walk(store: Any, prefix: str) -> list[str]:
    """Every object path under ``prefix``, recursing: Storage lists one level at a time."""
    paths: list[str] = []
    for entry in await _list_all(store, prefix):
        name = entry["name"]
        path = f"{prefix}/{name}" if prefix else name
        if entry.get("id") is None:  # a folder
            paths.extend(await walk(store, path))
        else:
            paths.append(path)
    return paths


async def backup(dest: Path) -> int:
    bucket_name = bucket()
    store = admin_storage().from_(bucket_name)
    paths = await walk(store, "")
    root = dest / bucket_name
    for path in paths:
        data = await store.download(path)
        out = root / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    return len(paths)


def main() -> int:
    # Runs on the host, where the app container's `host.docker.internal` does not resolve.
    apply_host_overrides(Path(os.getenv("ENV_FILE", ".env")))
    parser = argparse.ArgumentParser(description="Mirror the Supabase Storage bucket to disk.")
    parser.add_argument("--dest", default="backups/storage", help="destination directory")
    args = parser.parse_args()
    count = asyncio.run(backup(Path(args.dest)))
    print(f"backed up {count} object(s) to {args.dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
