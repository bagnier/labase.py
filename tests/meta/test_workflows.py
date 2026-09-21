"""GitHub Actions workflows — the rules their triggers make easy to break."""

from pathlib import Path

import yaml

_FIX = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "fix.yml"


def test_a_skipped_fix_run_cannot_cancel_the_live_one():
    """Every label fires the workflow, and the bot's own `fixing` label is one. A workflow-level
    group is joined before the job's `if` skips the run, so that run cancels the live fix; a
    job-level group is joined only by a job that runs."""
    workflow = yaml.safe_load(_FIX.read_text())

    assert ("concurrency" in workflow, "concurrency" in workflow["jobs"]["fix"]) == (False, True)
