from fastapi import Request


async def parse_field(request: Request, field: str) -> str:
    if "application/json" in request.headers.get("content-type", ""):
        return str((await request.json()).get(field, ""))
    return str((await request.form()).get(field, ""))


def wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


def wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "")


def wants_full_page(request: Request) -> bool:
    """True when the response is a standalone HTML page (not JSON, not an HTMX swap).

    Only full pages extend base.html and therefore need the shell context.
    """
    if wants_json(request):
        return False
    return request.headers.get("HX-Request") != "true"
