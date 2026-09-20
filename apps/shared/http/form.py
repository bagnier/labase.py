"""A form is JSON at the door.

One handler answers a browser's form and an API caller's JSON (README: every business endpoint
has two faces). FastAPI documents and validates a JSON body from the handler's signature; a body
that may also arrive ``application/x-www-form-urlencoded`` it can neither describe nor parse into
the same model. So the form is re-encoded as JSON before routing, and every mutation declares one
Pydantic body — the schema then says what each takes, and nothing reads ``request.form()``.

Plain ASGI, like the other request middlewares: the body is read once here and replayed to the
app as a single JSON message. Multipart (a file upload) is not a form in this sense and passes
through untouched. A repeated key keeps its last value, as ``dict(request.form())`` always did —
it is how a checkbox is made to say ``false``: a hidden input before it, same name, that the
ticked box overrides. A blank value stays a blank string, so a handler can still tell "sent
empty" from "not sent".
"""

import json
from urllib.parse import parse_qsl

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_FORM = b"application/x-www-form-urlencoded"


def _is_form(scope: Scope) -> bool:
    return any(
        name == b"content-type" and value.split(b";")[0].strip().lower() == _FORM
        for name, value in scope["headers"]
    )


def _fields(pairs: list[tuple[str, str]]) -> dict[str, str]:
    return dict(pairs)  # last value wins on a repeated key


async def _whole_body(receive: Receive) -> bytes:
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body", False):
            return body


class FormAsJson:
    """Re-encode a urlencoded form body as JSON, so the handler sees one body shape."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _is_form(scope):
            await self.app(scope, receive, send)
            return
        raw = await _whole_body(receive)
        encoded = json.dumps(_fields(parse_qsl(raw.decode(), keep_blank_values=True))).encode()
        headers = [
            (name, value)
            for name, value in scope["headers"]
            if name not in (b"content-type", b"content-length")
        ]
        headers += [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(encoded)).encode()),
        ]
        replayed = False

        async def receive_json() -> Message:
            nonlocal replayed
            if replayed:
                return await receive()  # anything after the body — a disconnect — is the client's
            replayed = True
            return {"type": "http.request", "body": encoded, "more_body": False}

        await self.app({**scope, "headers": headers}, receive_json, send)
