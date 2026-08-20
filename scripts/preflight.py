"""Deploy gate: run the production preflight against a target env file.

    make preflight ENV_FILE=.env.production

Exits non-zero if any blocking error is found, so it can gate a deploy pipeline.
"""

import sys

from apps.shared.settings.env import get_technical_settings
from apps.shared.settings.preflight import check_production


def main() -> int:
    settings = get_technical_settings()
    errors, warnings = check_production(settings)

    for detail in warnings:
        print(f"  warn:  {detail}")
    for detail in errors:
        print(f"  ERROR: {detail}")

    if errors:
        print(f"\npreflight: {len(errors)} blocking error(s) — not production-ready.")
        return 1
    print(f"\npreflight: OK — {len(warnings)} warning(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
