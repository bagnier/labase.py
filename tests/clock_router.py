"""Test-only endpoint to mock the server clock in a running subprocess.

Mounted by app.main only when ENABLE_TEST_CLOCK=1, so it never exists in
production. It monkeypatches app.shared.clock.now inside the app subprocess,
which the browser BDD driver cannot reach with an in-process patch.
"""

from datetime import datetime

from fastapi import APIRouter, Request

from app.shared import clock

router = APIRouter(prefix="/__test__", include_in_schema=False)

_real_now = clock.now


@router.post("/clock")
async def set_clock(request: Request) -> dict:
    body = await request.json()
    raw = body.get("now")
    if raw:
        fixed = datetime.fromisoformat(raw)
        clock.now = lambda: fixed  # ty: ignore[invalid-assignment]
    else:
        clock.now = _real_now
    return {"now": raw}
