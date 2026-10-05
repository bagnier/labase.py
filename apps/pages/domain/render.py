"""Page Markdown to HTML, sanitised with ``nh3``: authored by users, read by anonymous visitors
through ``| safe``."""

import mistune
import nh3

_markdown = mistune.create_markdown(escape=True)


def render_markdown(content: str) -> str:
    """The body only; the title is rendered by the template."""
    html = _markdown(content or "")
    # The stub also admits the AST renderer's token list.
    assert isinstance(html, str)
    return nh3.clean(html)
