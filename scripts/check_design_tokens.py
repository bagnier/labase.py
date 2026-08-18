"""Design-token guard — `make lint` calls this to keep the styling system honest.

The base has one styling source of truth: daisyUI semantic tokens (base-*, primary,
success…) driven by the active theme. Two ways that truth erodes over time, both caught
here so a regression fails CI instead of shipping:

1. **Raw palette / hex colours.** A `text-gray-500` or a `#1e1e2e` bypasses the token
   system: it ignores the active theme and breaks under the dark / non-default themes.
   Templates must use semantic tokens; the same holds for the component layer in
   ``static/css/input.css``. (Transactional *email* templates are exempt — mail clients
   can't resolve CSS variables, so inline hex there is correct.)

2. **Theme-list drift.** The themes offered to admins are declared twice — in
   ``input.css`` (the two custom ``@plugin "daisyui/theme"`` blocks plus the built-in
   ``themes:`` roster) and in ``apps/console/contract/appearance.py`` (``THEMES``). If the
   two disagree the console can offer a theme the CSS never built, or vice-versa. This
   asserts they are the same set.

Read-only. Exits non-zero (and prints every offence) on any violation.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT_CSS = ROOT / "static" / "css" / "input.css"
APPEARANCE = ROOT / "apps" / "console" / "contract" / "appearance.py"

_PALETTE_NAMES = (
    "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|"
    "teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose"
)
# A Tailwind palette utility carrying a numeric shade — ``text-gray-500``, ``bg-indigo-600``,
# ``border-slate-200``. daisyUI tokens (``bg-primary``, ``text-base-content``) carry no shade, so
# they never match.
RAW_PALETTE = re.compile(
    r"\b(?:text|bg|border|ring|ring-offset|from|via|to|divide|fill|stroke|outline|"
    r"shadow|decoration|accent|caret)-(?:" + _PALETTE_NAMES + r")-"
    r"(?:50|100|200|300|400|500|600|700|800|900|950)\b"
)

# A CSS hex literal. A Phosphor glyph escape (``content: "\e058"``) uses a backslash, not a hash, so
# it never matches.
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def _iter_template_files():
    """Served Jinja templates, minus email bodies (inline hex there is legitimate)."""
    for path in (ROOT / "apps").rglob("*.html"):
        parts = set(path.parts)
        if "templates" in parts and "email" not in parts:
            yield path


def scan_colours() -> list[str]:
    offences: list[str] = []
    targets = [*_iter_template_files(), INPUT_CSS]
    for path in targets:
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            for pat, label in ((RAW_PALETTE, "raw palette utility"), (HEX, "hex colour")):
                offences.extend(
                    f"{rel}:{lineno}: {label} `{m.group()}` — use a daisyUI token"
                    for m in pat.finditer(line)
                )
    return offences


def _css_theme_names() -> set[str]:
    css = INPUT_CSS.read_text(encoding="utf-8")
    names: set[str] = set()
    # Custom themes: @plugin "daisyui/theme" { name: "labase-light"; ... }
    names.update(re.findall(r'name:\s*"([^"]+)"', css))
    # Built-in roster: @plugin "daisyui" { themes: light, dark, …; }
    block = re.search(r'@plugin\s+"daisyui"\s*\{(.*?)\}', css, re.DOTALL)
    if block:
        listed = re.search(r"themes:\s*(.*?);", block.group(1), re.DOTALL)
        if listed:
            names.update(t.strip() for t in listed.group(1).split(",") if t.strip())
    return names


def _appearance_themes() -> set[str]:
    # Parsed by regex rather than importing/ast-parsing the module: keeps the guard
    # free of app imports and independent of the runner's Python (appearance.py uses
    # PEP 758 unparenthesized `except`, which only parses on 3.14+).
    src = APPEARANCE.read_text(encoding="utf-8")
    block = re.search(r"THEMES\s*=\s*\[(.*?)\]", src, re.DOTALL)
    if not block:
        raise SystemExit(f"{APPEARANCE.relative_to(ROOT)}: THEMES assignment not found")
    return set(re.findall(r'"([^"]+)"', block.group(1)))


def check_theme_sync() -> list[str]:
    css = _css_theme_names()
    py = _appearance_themes()
    if css == py:
        return []
    only_css = ", ".join(sorted(css - py)) or "—"
    only_py = ", ".join(sorted(py - css)) or "—"
    return [
        "theme list drift between input.css and appearance.py THEMES:",
        f"  only in input.css: {only_css}",
        f"  only in appearance.py: {only_py}",
    ]


def main() -> int:
    offences = scan_colours() + check_theme_sync()
    if offences:
        print("Design-token check failed:\n", file=sys.stderr)
        for line in offences:
            print(f"  {line}", file=sys.stderr)
        print(
            "\nStyling must go through daisyUI semantic tokens "
            "(base-*, primary, success…). See README 'Styling'.",
            file=sys.stderr,
        )
        return 1
    print("Design tokens OK: no raw palette/hex, theme lists in sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
