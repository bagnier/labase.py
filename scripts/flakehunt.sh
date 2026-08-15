#!/bin/bash

# Flake hunt for the browser-driver scenarios.
#
# Runs the target N times in a row and aggregates failures per test: one that fails 3 times
# out of 15 is intermittent, not broken. No rerun plugin here on purpose — a rerun would hide
# exactly what this is looking for.
#
# Each run gets a fresh test schema (provision-test) so a leftover row from run N-1 cannot
# masquerade as a flake in run N.
#
# Usage:
#   scripts/flakehunt.sh [N] [pytest target...]
#   scripts/flakehunt.sh                 # 10 iterations on the browser-driver scenarios
#   scripts/flakehunt.sh 15
#   scripts/flakehunt.sh 20 apps/auth/tests/e2e/test_scenarios.py

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

N="${1:-10}"
if [[ "$N" =~ ^[0-9]+$ ]]; then shift || true; else N=10; fi
TARGET=("${@:-apps/ tests/e2e/drivers/}")

OUT="$(mktemp -d)"
FAILURES="$OUT/failures.txt"
: > "$FAILURES"

echo "flakehunt: $N iterations on ${TARGET[*]} (browser driver)"
echo "logs: $OUT"
echo

for i in $(seq 1 "$N"); do
    log="$OUT/run$i.log"
    make provision-test > "$OUT/provision$i.log" 2>&1
    env --ignore-environment ENV_FILE=.env.test PATH="$PATH" \
        uv run pytest "${TARGET[@]}" \
        -k "test_scenarios or test_browser_isolation" --driver=browser --no-cov \
        -q -rf > "$log" 2>&1
    ec=$?
    summary="$(grep -oE '[0-9]+ (passed|failed|error)[^$]*' "$log" | tail -1)"
    printf '  run %2d : exit=%d  %s\n' "$i" "$ec" "$summary"
    # Only 0 (all passed) and 1 (tests failed) are results. Anything else — usage error,
    # collection error, interrupt — means the run never happened, and produces no FAILED
    # line: without this, the aggregation below would report a clean green on zero tests.
    if [ "$ec" -gt 1 ]; then
        echo
        echo "run $i did not run (exit $ec) — the hunt proves nothing. Tail:"
        tail -5 "$log"
        exit "$ec"
    fi
    grep -oE '^FAILED [^ ]+' "$log" | sed 's/^FAILED //' >> "$FAILURES"
done

echo
echo "=== Intermittent tests (failures / $N) ==="
if [ -s "$FAILURES" ]; then
    sort "$FAILURES" | uniq -c | sort -rn
    echo
    echo "Full logs: $OUT"
    exit 1
else
    echo "No failure over $N iterations. 🟢"
fi
