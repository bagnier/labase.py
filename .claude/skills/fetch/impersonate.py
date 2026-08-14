#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["curl-cffi==0.16.0", "typing_extensions"]
# ///
"""Rung 2 of the fetch skill — a browser's TLS/HTTP2 fingerprint, without a browser.

When to reach for it and how to call it: SKILL.md, next to this file. To update, bump
the pin above; `typing_extensions` is listed because curl-cffi 0.16.0 fails to.
"""

import argparse
import os
import sys
import typing
from pathlib import Path

from curl_cffi import requests
from curl_cffi.requests.impersonate import BrowserTypeLiteral

DEFAULT_TARGET = "safari"  # Alias: tracks the newest Safari in the build.


def resolve_output(out: str) -> Path:
    """Same rule as `curl-verdict.sh`: `--output` is a *name*, and whatever directory it carries
    is dropped. The cwd is whatever the session is rooted at and never a scratch space, so the
    directory is not the caller's to choose — `FETCH_DIR` moves every download at once."""
    session = os.environ.get("CLAUDE_CODE_SESSION_ID", "shared")
    # A predictable /tmp path is the point — the alternative is the cwd, i.e. the project.
    fetch_dir = Path(os.environ.get("FETCH_DIR", f"/tmp/fetch/{session}"))  # noqa: S108
    fetch_dir.mkdir(parents=True, exist_ok=True)
    return fetch_dir / Path(out).name


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("url", nargs="?")
    p.add_argument("-o", "--output", help="output file (required unless --list)")
    p.add_argument("--impersonate", default=DEFAULT_TARGET)
    p.add_argument("--max-time", type=float, default=30.0)
    p.add_argument("-H", "--header", action="append", default=[])
    p.add_argument("--no-redirect", action="store_true")
    p.add_argument("--list", action="store_true", help="list targets and exit")
    a = p.parse_args()

    targets = list(typing.get_args(BrowserTypeLiteral))

    if a.list:
        print("\n".join(targets))
        return 0

    if not a.url or not a.output:
        p.error("url and -o are required")

    if a.impersonate not in targets:
        print(f"unknown target: {a.impersonate} (see --list)", file=sys.stderr)
        return 2

    headers = {}
    for h in a.header:
        if ":" in h:
            k, v = h.split(":", 1)
            headers[k.strip()] = v.strip()

    try:
        r = requests.get(
            a.url,
            impersonate=a.impersonate,
            timeout=a.max_time,
            allow_redirects=not a.no_redirect,
            headers=headers or None,
        )
    except Exception as e:  # noqa: BLE001 — the verdict must survive any failure
        print(f"http=000 0b - ERROR {type(e).__name__}: {e}", file=sys.stderr)
        return 35

    out = resolve_output(a.output)
    out.write_bytes(r.content)

    # Decoded body, not curl's wire-byte `%{size_download}` — hence the suffix.
    print(
        f"http={r.status_code} {len(r.content)}b(decoded) "
        f"{r.headers.get('content-type', '-')} "
        f"redir={len(r.history)} as={a.impersonate} file={out} {r.url}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
