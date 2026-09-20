from apps.shared.http.content_type import is_htmx, wants_full_page, wants_json
from apps.shared.http.etag import with_etag
from apps.shared.http.responses import (
    HTML_AFTER_DELETE,
    delete_response,
    json_and_html,
    mutation_response,
    or_404,
    render_list,
)

__all__ = [
    "HTML_AFTER_DELETE",
    "delete_response",
    "is_htmx",
    "json_and_html",
    "mutation_response",
    "or_404",
    "render_list",
    "wants_full_page",
    "wants_json",
    "with_etag",
]
