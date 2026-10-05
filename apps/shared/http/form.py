"""A form is JSON at the door (AGENTS: a form is JSON at the door).

FastAPI can document and validate a JSON body, not a urlencoded form parsed into the same model,
so this middleware re-encodes the form before routing. Multipart passes through untouched.

A repeated key keeps its last value: a hidden ``false`` input before a checkbox of the same name
is how an unticked box says ``false``. A blank value stays ``""``, distinct from "not sent".
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
    return dict(pairs)


async def _whole_body(receive: Receive) -> bytes:
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body", False):
            return body


class FormAsJson:
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
                return await receive()  # e.g. a disconnect
            replayed = True
            return {"type": "http.request", "body": encoded, "more_body": False}

        await self.app({**scope, "headers": headers}, receive_json, send)
