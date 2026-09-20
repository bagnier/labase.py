"""Every JSON answer the API lane receives is checked against the schema its route declares.

A route that says ``responses=json_and_html(list[TodoRead])`` has made a promise to the generated
client; nothing else in the suite reads that promise back. Hooked onto the API driver's httpx
client, this validates each 2xx JSON body against the OpenAPI schema of the operation that served
it, so every scenario the lane already runs also proves the documentation of every route it
touches — a DTO declared wrong, a field added without regenerating, a dict assembled by hand
where a model is declared, all fail the scenario that met them, by name.

A face the schema leaves blank is not checked: ``tests/meta/test_routes`` counts those, and the
count is what has to reach zero.
"""

import re
from typing import Any

import httpx
import jsonschema

_TEMPLATE_VAR = re.compile(r"\{[^}]+\}")


class Conformance:
    """The check, bound to one OpenAPI document — the app's, or a test's own."""

    def __init__(self, schema: dict[str, Any]) -> None:
        self._schema = schema
        # Most literal template first: `/{org_handle}/todos` beats `/{slug}` on `/acme/todos`.
        self._templates = sorted(
            (
                (re.compile("^" + _TEMPLATE_VAR.sub("[^/]+", path) + "$"), path)
                for path in schema["paths"]
            ),
            key=lambda entry: -len(_TEMPLATE_VAR.sub("", entry[1])),
        )

    def _operation(self, method: str, path: str) -> tuple[str, dict[str, Any] | None]:
        for pattern, template in self._templates:
            if pattern.match(path) and method.lower() in self._schema["paths"][template]:
                return template, self._schema["paths"][template][method.lower()]
        return path, None

    def check(self, response: httpx.Response) -> None:
        """Raise if a 2xx JSON body strays from what its operation declares."""
        if not 200 <= response.status_code < 300:
            return
        if "application/json" not in response.headers.get("content-type", ""):
            return
        method, path = response.request.method, response.request.url.path
        template, operation = self._operation(method, path)
        if operation is None:
            raise AssertionError(f"{method} {path} answered JSON but the schema has no operation")
        declared = (
            (operation.get("responses") or {})
            .get(str(response.status_code), {})
            .get("content", {})
            .get("application/json", {})
            .get("schema")
        )
        if not declared:
            return
        response.read()
        root = {**declared, "components": self._schema.get("components", {})}
        errors = sorted(jsonschema.Draft202012Validator(root).iter_errors(response.json()), key=str)
        if errors:
            said = "; ".join(f"{list(e.absolute_path)}: {e.message}" for e in errors[:3])
            raise AssertionError(
                f"{method} {template} answered JSON that strays from its declared schema: {said}"
            )
