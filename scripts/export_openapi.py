"""Export the FastAPI OpenAPI schema for the generated client.

Usage:
    ENV_FILE=.env.test PYTHONPATH=. uv run python scripts/export_openapi.py <output-path>

Every app is forced on for the export: ``mount()`` reads each app's persisted ``enabled``
switch once, synchronously, at import — so a deployment that switched one off would otherwise
silently export fewer paths. The schema must be a full description of the app, not of however
it happens to be configured (Makefile: "routes are env-independent").
"""

import json
import sys
from collections.abc import Callable
from pathlib import Path

import apps.shared.settings.live as settings_live
from apps.shared.settings.store import BOOL_TRUE, ENABLED_KEY

ReadValues = Callable[[str], dict[str, str]]


def force_all_apps_enabled(read_values: ReadValues) -> ReadValues:
    """Wrap a ``read_values``-shaped function so every app's ``enabled`` switch reads as on,
    whatever a deployment persisted."""

    def _all_enabled(app: str) -> dict[str, str]:
        values = read_values(app)
        values[ENABLED_KEY] = BOOL_TRUE
        return values

    return _all_enabled


_original_read_values = settings_live.read_values
settings_live.read_values = force_all_apps_enabled(_original_read_values)
try:
    from apps.main import host  # mount() reads settings synchronously, while patched above
finally:
    settings_live.read_values = _original_read_values


def build_schema() -> dict:
    """The exported schema, ``org_handle`` included: it is injected via the ``CurrentOrg``
    dependency and never reaches FastAPI's own parameter list, and openapi-python-client
    rejects a path template variable no operation declares as a parameter."""
    schema = host.app.openapi()

    org_handle_param = {
        "name": "org_handle",
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
    }

    for path, path_item in schema.get("paths", {}).items():
        if "{org_handle}" not in path:
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            params = operation.setdefault("parameters", [])
            if not any(p.get("name") == "org_handle" for p in params):
                params.insert(0, org_handle_param)

    return schema


def main() -> None:
    # Write to the path argument (not stdout): importing the whole app emits log
    # noise to stdout, which would corrupt a redirected JSON stream.
    Path(sys.argv[1]).write_text(json.dumps(build_schema(), indent=2))


if __name__ == "__main__":
    main()
