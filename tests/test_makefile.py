"""Concurrent `make` test runs in one checkout each get a schema from their own pid, so one's
rebuild or truncation never touches the other's rows."""

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGETS = ["test", "test-e2e", "meta", "perf-smoke"]


def _dry_run(target: str) -> str:
    return subprocess.run(
        ["make", "-n", target],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _provisioned_schema_and_bucket(output: str) -> tuple[str, str]:
    match = re.search(r"provision_schema\.py --schema (\S+) --bucket (\S+)", output)
    assert match, output
    return match.group(1), match.group(2)


def _run_schema_and_bucket(output: str) -> tuple[str, str]:
    match = re.search(r"SUPABASE_DATABASE_SCHEMA=(\S+) SUPABASE_STORAGE_BUCKET=(\S+)", output)
    assert match, output
    return match.group(1), match.group(2)


@pytest.mark.parametrize("target", TARGETS)
def test_target_runs_against_the_schema_and_bucket_it_provisioned(target: str) -> None:
    output = _dry_run(target)

    provisioned = _provisioned_schema_and_bucket(output)
    run_against = _run_schema_and_bucket(output)

    assert run_against == provisioned


@pytest.mark.parametrize("target", TARGETS)
def test_two_invocations_of_the_same_target_provision_different_schemas(target: str) -> None:
    first_schema, first_bucket = _provisioned_schema_and_bucket(_dry_run(target))
    second_schema, second_bucket = _provisioned_schema_and_bucket(_dry_run(target))

    assert (first_schema, first_bucket) != (second_schema, second_bucket)
