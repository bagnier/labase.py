"""Boot the app on the test schema, run the Locust smoke headless, propagate its verdict.

Invoked by ``make perf-smoke`` with ENV_FILE=.env.test. The Locust side
(scripts/smoke.py) enforces the blocking thresholds; this script only owns the
app lifecycle so the smoke needs no ``make dev``.
"""

import os
import socket
import subprocess
import sys
import time
import urllib.request

USERS = os.environ.get("PERF_USERS", "8")
SPAWN_RATE = os.environ.get("PERF_SPAWN_RATE", "4")
DURATION = os.environ.get("PERF_DURATION", "15s")

# A perf-smoke tunable like the three above: this drives a *real* server, so its background loops
# must be on. ``.env.test`` disables them (=0) for pytest, which drives them by hand — without them
# the async signup consumer never runs and the personal org is never created. Env wins over the
# dotenv.
SERVER_WORKER_INTERVAL = os.environ.get("PERF_WORKER_INTERVAL", "1.0")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_ready(url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:  # noqa: S310
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError(f"app not ready after {timeout}s at {url}")


def main() -> int:
    port = _free_port()
    host = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "PYTHONPATH": f".{os.pathsep}client",
        "TASK_WORKER_INTERVAL_SECONDS": SERVER_WORKER_INTERVAL,
    }
    server = subprocess.Popen(
        [sys.executable, "-m", "hypercorn", "apps.main:app", "--bind", f"127.0.0.1:{port}"],
        env=env,
    )
    try:
        _wait_ready(f"{host}/health/ready")
        return subprocess.call(
            [
                sys.executable,
                "-m",
                "locust",
                "-f",
                "scripts/smoke.py",
                "--headless",
                "-u",
                USERS,
                "-r",
                SPAWN_RATE,
                "-t",
                DURATION,
                "--host",
                host,
                "--only-summary",
            ],
            env=env,
        )
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    sys.exit(main())
