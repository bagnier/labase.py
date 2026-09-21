"""GitHub Actions workflows — the rules their triggers make easy to break."""

from pathlib import Path

import pytest
import yaml

_WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
_FIX = _WORKFLOWS / "fix.yml"

# The two workflows that run Claude headless: one issue to a pull request, one review to a push.
_BOTS = ("fix.yml", "review.yml")


def _fix_job() -> dict:
    return yaml.safe_load(_FIX.read_text())["jobs"]["fix"]


def _claude_args(workflow: str) -> str:
    (job,) = yaml.safe_load((_WORKFLOWS / workflow).read_text())["jobs"].values()
    step = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("anthropics/"))
    return step["with"]["claude_args"]


def test_a_skipped_fix_run_cannot_cancel_the_live_one():
    """Every label fires the workflow, and the bot's own `fixing` label is one. A workflow-level
    group is joined before the job's `if` skips the run, so that run cancels the live fix; a
    job-level group is joined only by a job that runs."""
    workflow = yaml.safe_load(_FIX.read_text())

    assert ("concurrency" in workflow, "concurrency" in workflow["jobs"]["fix"]) == (False, True)


@pytest.mark.parametrize("workflow", _BOTS)
def test_the_bot_cannot_hand_its_turn_to_a_harness_that_never_returns(workflow):
    """Headless, the end of the turn is the end of the run: a tool that promises to bring the
    model back later (`ScheduleWakeup`, a cron) ends the run with nothing pushed — the first
    Sonnet run did exactly that while `make finalize` was still running."""
    disallowed = {
        name
        for line in _claude_args(workflow).splitlines()
        if line.strip().startswith("--disallowedTools")
        for name in line.split(maxsplit=1)[1].strip('"').split(",")
    }

    assert {"ScheduleWakeup", "CronCreate", "RemoteTrigger", "Workflow"} <= disallowed


def test_a_review_run_answers_the_owner_s_mention_only():
    """The review workflow fires on every comment of a public repository; the job runs only for
    a body that mentions `@claude`, written by the owner — the action's own write-access check
    is the other half of that guard."""
    (job,) = yaml.safe_load((_WORKFLOWS / "review.yml").read_text())["jobs"].values()

    assert ("@claude" in job["if"], "repository_owner" in job["if"]) == (True, True)


def test_a_run_that_dies_does_not_leave_the_issue_on_fixing():
    """`fixing` is set by the bot, so a run that ends before its own end — cancelled, timed out,
    or a turn that stopped — leaves the label with nobody behind it. A step that runs whatever
    happened turns it into a terminal state the owner can see."""
    steps = _fix_job()["steps"]
    action = next(
        i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("anthropics/")
    )
    after = [s for s in steps[action + 1 :] if s.get("if") == "always()"]

    assert [("fixing" in s["run"], "stalled" in s["run"]) for s in after] == [(True, True)]
