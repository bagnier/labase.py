"""GitHub Actions workflows — the rules their triggers make easy to break.

A value that only configures (a cron, a token, an env var) is justified by its comment in the
YAML, not restated here; a test holds a rule a later edit could break without noticing.
"""

from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOWS = _ROOT / ".github" / "workflows"
_SKILLS = _ROOT / ".claude" / "skills"
_FIX = _WORKFLOWS / "fix.yml"

# The two workflows that run Claude headless: one issue to a pull request, one review to a push.
_BOTS = ("fix.yml", "review.yml")


def _fix_job() -> dict:
    return yaml.safe_load(_FIX.read_text())["jobs"]["fix"]


def _only_job(workflow: str) -> dict:
    (job,) = yaml.safe_load((_WORKFLOWS / workflow).read_text())["jobs"].values()
    return job


def _action_step(workflow: str) -> dict:
    return next(
        s for s in _only_job(workflow)["steps"] if str(s.get("uses", "")).startswith("anthropics/")
    )


def _tool_lists(workflow: str) -> tuple[set[str], set[str]]:
    args = _action_step(workflow)["with"]["claude_args"]
    flags = [line.split(maxsplit=1) for line in args.splitlines() if line.strip()]
    allowed, disallowed = (
        {name for flag, rest in flags if flag == wanted for name in rest.strip('"').split(",")}
        for wanted in ("--allowedTools", "--disallowedTools")
    )
    return allowed, disallowed


def test_a_skipped_fix_run_cannot_cancel_the_live_one():
    """Every label fires the workflow, and the bot's own `fixing` label is one. A workflow-level
    group is joined before the job's `if` skips the run, so that run cancels the live fix; a
    job-level group is joined only by a job that runs."""
    workflow = yaml.safe_load(_FIX.read_text())

    assert ("concurrency" in workflow, "concurrency" in workflow["jobs"]["fix"]) == (False, True)


def test_a_fork_s_workflow_named_fix_cannot_tick():
    """`workflow_run` matches the upstream workflow by name, so a fork's pull request can add its
    own "Fix" and fire the tick with the base repository's secrets. A Fix run fired by an issue
    has this repository as its head; a fork's does not."""
    job = _only_job("tick.yml")

    assert job.get("if") == (
        "github.event_name != 'workflow_run' || "
        "github.event.workflow_run.head_repository.full_name == github.repository"
    )


@pytest.mark.parametrize("workflow", _BOTS)
def test_the_bot_cannot_hand_its_turn_to_a_harness_that_never_returns(workflow):
    """Headless, the end of the turn is the end of the run: a tool that promises to bring the
    model back later (`ScheduleWakeup`, a cron, a `Monitor`) ends the run with nothing pushed —
    the first Sonnet run did exactly that while `make finalize` was still running, and the #12
    run did it again through a `Monitor` the allowed list handed it."""
    allowed, disallowed = _tool_lists(workflow)
    never = {"ScheduleWakeup", "CronCreate", "RemoteTrigger", "Workflow", "Monitor"}

    assert (never <= disallowed, never & allowed) == (True, set())


def test_the_fix_bot_cannot_reach_the_raw_github_api():
    """`ci-fix-issue` writes to GitHub through `gh issue` and `gh pr` alone. `gh api` is where a
    body goes wrong silently — the #35 run patched its comment with `-f body=@file`, which posts
    the string `@file` — so the bot is not handed it."""
    _, disallowed = _tool_lists("fix.yml")

    assert sorted(name for name in disallowed if name.startswith("Bash(")) == ["Bash(gh api:*)"]


def test_a_review_run_answers_the_owner_s_mention_only():
    """The review workflow fires on every comment of a public repository; the job runs only for
    a body that mentions `@claude`, written by the owner — the action's own write-access check
    is the other half of that guard."""
    job = _only_job("review.yml")

    assert ("@claude" in job["if"], "repository_owner" in job["if"]) == (True, True)


def test_each_headless_run_invokes_a_skill_that_exists():
    """Every headless run is a skill invocation — the skill and `CLAUDE.md` carry the runner's
    rules, the workflow only names it. A name no skill answers to leaves the run with a bare
    prompt and none of those rules, and nothing else fails."""
    invoked = {_action_step(w)["with"]["prompt"].split(" ")[0].removeprefix("/") for w in _BOTS}
    existing = {path.parent.name for path in _SKILLS.glob("*/SKILL.md")}

    assert invoked - existing == set()


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
