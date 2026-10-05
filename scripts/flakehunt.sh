#!/bin/bash

# Flake hunt for the browser-driver scenarios.
#
# Runs the target N times and counts failures per test. No rerun plugin: it would hide the
# flakes. Each run gets a fresh schema, so a leftover row never passes for a flake.
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
    provision_out="$(make provision-test 2>&1)"
    printf '%s\n' "$provision_out" > "$OUT/provision$i.log"
    # The schema/bucket provision-test named after its `make` pid, not .env.test's default.
    if [[ "$provision_out" =~ Provisioned\ schema\ \'([^\']+)\'\ \+\ bucket\ \'([^\']+)\'\. ]]; then
        schema="${BASH_REMATCH[1]}"
        bucket="${BASH_REMATCH[2]}"
    else
        echo "run $i: could not read the provisioned schema/bucket. Tail:"
        tail -5 "$OUT/provision$i.log"
        exit 1
    fi
    env --ignore-environment ENV_FILE=.env.test PATH="$PATH" \
        SUPABASE_DATABASE_SCHEMA="$schema" SUPABASE_STORAGE_BUCKET="$bucket" \
        CHROMIUM_EXECUTABLE_PATH="${CHROMIUM_EXECUTABLE_PATH:-}" \
        uv run pytest "${TARGET[@]}" \
        -k "test_scenarios or test_browser_isolation" --driver=browser \
        -q -rf > "$log" 2>&1
    ec=$?
    summary="$(grep -oE '[0-9]+ (passed|failed|error)[^$]*' "$log" | tail -1)"
    printf '  run %2d : exit=%d  %s\n' "$i" "$ec" "$summary"
    # Only 0 and 1 are results: any other exit ran no test and would count as green.
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
