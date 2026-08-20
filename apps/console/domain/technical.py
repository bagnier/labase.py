"""Environment / process diagnostics — framework-free. Feeds the "Settings" console tab that
shows admins what the running process actually sees: env vars, config, and resource usage.

Values whose name looks sensitive (secret, password, token, key, credential, private, auth, or
a database connection URL) are masked before leaving this module — never returned in the clear.
"""

import asyncio
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

import psutil

from apps.shared import clock
from apps.shared.settings.env import get_technical_settings

_SENSITIVE_SUBSTRINGS = ("secret", "password", "token", "key", "credential", "private", "auth")

_PROCESS = psutil.Process()
_PROCESS.cpu_percent(interval=None)
"""Primed at import, so the first request already reports a meaningful, non-zero CPU share."""


class EnvVar(TypedDict):
    name: str
    value: str
    masked: bool


def _is_sensitive(name: str) -> bool:
    lname = name.lower()
    if any(s in lname for s in _SENSITIVE_SUBSTRINGS):
        return True
    return "database" in lname and "url" in lname


def _mask(value: str) -> str:
    return f"•••• ({len(value)} chars)" if value else "(empty)"


def _env_var(name: str, value: str) -> EnvVar:
    masked = _is_sensitive(name)
    return EnvVar(name=name, value=_mask(value) if masked else value, masked=masked)


def env_snapshot() -> list[EnvVar]:
    """Every variable the process sees, masking anything whose name looks sensitive."""
    return [_env_var(n, v) for n, v in sorted(os.environ.items())]


def technical_settings_snapshot() -> dict[str, str]:
    """The app's own parsed config (:class:`TechnicalSettings`), same masking rule."""
    return {
        key: _mask(str(value)) if _is_sensitive(key) else str(value)
        for key, value in get_technical_settings().model_dump().items()
    }


class ProcessSnapshot(TypedDict):
    python_version: str
    executable: str
    pid: int
    cwd: str
    platform: str
    started_at: str
    uptime_seconds: int
    rss_mb: float
    cpu_percent: float
    asyncio_tasks: int


def process_snapshot() -> ProcessSnapshot:
    started_at = datetime.fromtimestamp(_PROCESS.create_time(), tz=UTC)
    rss_bytes = _PROCESS.memory_info().rss
    return ProcessSnapshot(
        python_version=sys.version.split()[0],
        executable=sys.executable,
        pid=os.getpid(),
        cwd=str(Path.cwd()),
        platform=platform.platform(),
        started_at=started_at.isoformat(),
        uptime_seconds=int((clock.now() - started_at).total_seconds()),
        rss_mb=round(rss_bytes / (1024 * 1024), 1),
        cpu_percent=_PROCESS.cpu_percent(interval=None),
        asyncio_tasks=len(asyncio.all_tasks()),
    )
