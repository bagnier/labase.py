"""GitHub Actions workflows — the rules their triggers make easy to break."""

from pathlib import Path

import yaml

_FIX = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "fix.yml"


def _fix_job() -> dict:
    return yaml.safe_load(_FIX.read_text())["jobs"]["fix"]


def _claude_args() -> str:
    step = next(s for s in _fix_job()["steps"] if str(s.get("uses", "")).startswith("anthropics/"))
    return step["with"]["claude_args"]


def test_a_skipped_fix_run_cannot_cancel_the_live_one():
    """Every label fires the workflow, and the bot's own `fixing` label is one. A workflow-level
    group is joined before the job's `if` skips the run, so that run cancels the live fix; a
    job-level group is joined only by a job that runs."""
    workflow = yaml.safe_load(_FIX.read_text())

    assert ("concurrency" in workflow, "concurrency" in workflow["jobs"]["fix"]) == (False, True)


def test_the_bot_cannot_hand_its_turn_to_a_harness_that_never_returns():
    """Headless, the end of the turn is the end of the run: a tool that promises to bring the
    model back later (`ScheduleWakeup`, a cron) ends the run with nothing pushed — the first
    Sonnet run did exactly that while `make finalize` was still running."""
    disallowed = {
        name
        for line in _claude_args().splitlines()
        if line.strip().startswith("--disallowedTools")
        for name in line.split(maxsplit=1)[1].strip('"').split(",")
    }

    assert {"ScheduleWakeup", "CronCreate", "RemoteTrigger", "Workflow"} <= disallowed
