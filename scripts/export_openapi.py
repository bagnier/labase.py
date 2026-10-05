"""Export the FastAPI OpenAPI schema for the generated client.

Usage:
    ENV_FILE=.env.test PYTHONPATH=. uv run python scripts/export_openapi.py <output-path>

Every app is forced on, so a switched-off one still exports its routes.
"""

import json
import sys
from collections.abc import Callable
from pathlib import Path

import apps.shared.settings.live as settings_live
from apps.shared.settings.store import BOOL_TRUE, ENABLED_KEY

ReadValues = Callable[[str], dict[str, str]]


def force_all_apps_enabled(read_values: ReadValues) -> ReadValues:
    """``read_values`` with every ``enabled`` switch on."""

    def _all_enabled(app: str) -> dict[str, str]:
        values = read_values(app)
        values[ENABLED_KEY] = BOOL_TRUE
        return values

    return _all_enabled


_original_read_values = settings_live.read_values
settings_live.read_values = force_all_apps_enabled(_original_read_values)
try:
    from apps.main import host  # mounts under the patch
finally:
    settings_live.read_values = _original_read_values


def build_schema() -> dict:
    """The schema, with ``org_handle`` declared: ``CurrentOrg`` hides it from FastAPI, and
    openapi-python-client rejects an undeclared path variable."""
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
    # Not stdout, where the app's logs go.
    Path(sys.argv[1]).write_text(json.dumps(build_schema(), indent=2))


if __name__ == "__main__":
    main()
