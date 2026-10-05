"""Design-token guard, run by `make lint`; prints every offence and exits non-zero.

1. No raw palette or hex colour in templates or ``static/css/input.css``: it ignores the theme.
   Email templates are exempt, since mail clients cannot resolve CSS variables.
2. The themes in ``input.css`` and ``THEMES`` in ``apps/console/contract/appearance.py`` are the
   same set.
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
# A palette utility with a shade (``text-gray-500``); daisyUI tokens have none.
RAW_PALETTE = re.compile(
    r"\b(?:text|bg|border|ring|ring-offset|from|via|to|divide|fill|stroke|outline|"
    r"shadow|decoration|accent|caret)-(?:" + _PALETTE_NAMES + r")-"
    r"(?:50|100|200|300|400|500|600|700|800|900|950)\b"
)

# A hex colour; a Phosphor glyph escape (``"\e058"``) has no hash.
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def _iter_template_files():
    """Served templates, without email bodies."""
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
    # By regex: no app import, and appearance.py needs Python 3.14 to parse.
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
            "(base-*, primary, success…). See AGENTS.md 'Styling'.",
            file=sys.stderr,
        )
        return 1
    print("Design tokens OK: no raw palette/hex, theme lists in sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
