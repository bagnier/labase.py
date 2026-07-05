"""Local stack health *and latency* checks — `make doctor`.

Reachability alone is not health: a degraded Docker proxy (seen after an
OrbStack freeze) still accepts TCP but multiplies every round-trip, silently
turning the ~100s test suite into 8 minutes. Each check therefore reports its
round-trip time and warns beyond `WARN_SECONDS`.

Run host-side against the local stack: `make doctor` (ENV_FILE=.env.test).
The guardrail test in tests/test_config.py reuses these checks so a degraded
environment fails the suite loudly instead of just slowly.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable

import asyncpg
import httpx

from apps.shared.config import get_technical_settings

WARN_SECONDS = 0.5
TIMEOUT_SECONDS = 5.0


async def check_postgres() -> None:
    settings = get_technical_settings()
    dsn = settings.supabase_database_admin_url.replace("postgresql+asyncpg", "postgresql")
    conn = await asyncpg.connect(dsn)
    try:
        await conn.fetchval("SELECT 1")
    finally:
        await conn.close()


async def check_gotrue() -> None:
    settings = get_technical_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{settings.supabase_api_url}/auth/v1/health",
            headers={"apikey": settings.supabase_publishable_key},
        )
        resp.raise_for_status()


async def check_mailpit_api() -> None:
    settings = get_technical_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"http://{settings.smtp_host}:54324/api/v1/messages")
        resp.raise_for_status()


async def check_smtp_greeting() -> None:
    settings = get_technical_settings()
    reader, writer = await asyncio.open_connection(settings.smtp_host, settings.smtp_port)
    try:
        greeting = await reader.readline()
        if not greeting.startswith(b"220"):
            raise RuntimeError(f"unexpected SMTP greeting: {greeting!r}")
    finally:
        writer.close()
        await writer.wait_closed()


CHECKS: list[tuple[str, Callable[[], Awaitable[None]]]] = [
    ("postgres", check_postgres),
    ("gotrue", check_gotrue),
    ("mailpit api", check_mailpit_api),
    ("smtp catcher", check_smtp_greeting),
]


async def timed(check: Callable[[], Awaitable[None]]) -> float:
    """Round-trip seconds of one check, bounded by TIMEOUT_SECONDS."""
    start = time.monotonic()
    await asyncio.wait_for(check(), timeout=TIMEOUT_SECONDS)
    return time.monotonic() - start


async def main() -> int:
    failures = 0
    for name, check in CHECKS:
        try:
            elapsed = await timed(check)
        except Exception as exc:
            failures += 1
            print(f"FAIL {name:<14} {exc!r}")
            continue
        slow = "  ⚠ slow — proxy/DNS degraded? try restarting Docker"
        flag = "" if elapsed < WARN_SECONDS else slow
        print(f"ok   {name:<14} {elapsed * 1000:6.0f}ms{flag}")
    if failures:
        print(f"\n{failures} check(s) failed — is the stack up? try `make db-start`")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
