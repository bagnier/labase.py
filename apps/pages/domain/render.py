"""Markdown → safe HTML for CMS page bodies.

Content is user-authored and shown to anonymous visitors, so the rendered HTML is
sanitised (``nh3``) before it ever reaches a template's ``| safe``. Kept behind this
single function so the renderer can be swapped without touching the rest of the app.
"""

import mistune
import nh3

_markdown = mistune.create_markdown(escape=True)


def render_markdown(content: str) -> str:
    """Render a Markdown *body* to sanitised HTML (the page title is rendered separately)."""
    html = _markdown(content or "")
    # The default renderer returns a string; the type stub also admits a token list
    # (only with the AST renderer, which we don't use), so narrow it for the type checker.
    assert isinstance(html, str)
    return nh3.clean(html)
