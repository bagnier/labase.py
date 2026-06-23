import json

from apps.main import app

schema = app.openapi()

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
    for _method, operation in path_item.items():
        if not isinstance(operation, dict):
            continue
        params = operation.setdefault("parameters", [])
        if not any(p.get("name") == "org_handle" for p in params):
            params.insert(0, org_handle_param)

print(json.dumps(schema, indent=2))
