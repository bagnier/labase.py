"""Export the FastAPI OpenAPI schema for the generated client.

Usage:
    uv run python scripts/export_openapi.py <output-path>

Every app is forced on for the export: ``mount()`` reads each app's persisted ``enabled``
switch once, synchronously, at import — so a deployment that switched one off would otherwise
silently export fewer paths. The schema must be a full description of the app, not of however
it happens to be configured (Makefile: "routes are env-independent").
"""

import json
import sys
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

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


with patch.object(settings_live, "read_values", force_all_apps_enabled(settings_live.read_values)):
    from apps.main import host  # mount() reads settings synchronously, inside this patch

schema = host.app.openapi()

# org_handle is injected via CurrentOrg dependency and absent from OpenAPI parameters.
# openapi-python-client rejects paths whose template vars aren't declared as parameters.
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


def main() -> None:
    # Write to the path argument (not stdout): importing the whole app emits log
    # noise to stdout, which would corrupt a redirected JSON stream.
    Path(sys.argv[1]).write_text(json.dumps(schema, indent=2))


if __name__ == "__main__":
    main()
