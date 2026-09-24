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

# The two workflows that run Claude headless: one issue to a pull request, one review to a push.
_BOTS = ("fix.yml", "rework.yml")

# What each bot puts on its subject while it holds it, and releases when it lets go.
_IN_FLIGHT = {"fix.yml": "fixing", "rework.yml": "reworking"}


def _workflow(name: str) -> dict:
    return yaml.safe_load((_WORKFLOWS / name).read_text())


def _jobs(workflow: str) -> dict:
    return _workflow(workflow)["jobs"]


def _only_job(workflow: str) -> dict:
    (job,) = _jobs(workflow).values()
    return job


def _is_action(step: dict) -> bool:
    return str(step.get("uses", "")).startswith("anthropics/")


def _bot_job(workflow: str) -> dict:
    """The job that runs Claude — the one the pacing rules are about."""
    return next(job for job in _jobs(workflow).values() if any(map(_is_action, job["steps"])))


def _action_step(workflow: str) -> dict:
    return next(step for step in _bot_job(workflow)["steps"] if _is_action(step))


def _tool_lists(workflow: str) -> tuple[set[str], set[str]]:
    args = _action_step(workflow)["with"]["claude_args"]
    flags = [line.split(maxsplit=1) for line in args.splitlines() if line.strip()]
    allowed, disallowed = (
        {name for flag, rest in flags if flag == wanted for name in rest.strip('"').split(",")}
        for wanted in ("--allowedTools", "--disallowedTools")
    )
    return allowed, disallowed


@pytest.mark.parametrize("workflow", _BOTS)
def test_a_skipped_run_cannot_cancel_the_live_one(workflow):
    """Every label fires the workflow, and the bot's own in-flight label is one. A workflow-level
    group is joined before the job's `if` skips the run, so that run cancels the live one; a
    job-level group is joined only by a job that runs."""
    document = _workflow(workflow)

    assert ("concurrency" in document, "concurrency" in _bot_job(workflow)) == (False, True)


@pytest.mark.parametrize(
    ("workflow", "group"), [("fix.yml", "fix-bot"), ("rework.yml", "rework-bot")]
)
def test_a_bot_run_never_runs_beside_another_of_its_own(workflow, group):
    """One run in flight per bot, to spread the subscription window. The group names the bot, not
    the issue or the pull request, so a second hand-off waits instead of taking its own runner —
    and nothing is cancelled: a run that must stop is cancelled by hand and lands on `stalled`."""
    concurrency = _bot_job(workflow)["concurrency"]

    assert concurrency == {"group": group, "cancel-in-progress": False}


def test_a_fork_s_workflow_named_fix_cannot_tick():
    """`workflow_run` matches the upstream workflow by name, so a fork's pull request can add its
    own "Fix" and fire the tick with the base repository's secrets. A Fix run fired by an issue
    has this repository as its head; a fork's does not."""
    job = _only_job("tick.yml")

    assert job.get("if") == (
        "github.event_name != 'workflow_run' || "
        "github.event.workflow_run.head_repository.full_name == github.repository"
    )


def test_the_tick_hears_the_end_of_both_bots():
    """The tick is what starts the next run, so the end of a run is what drains the queue behind
    it. A bot the tick does not listen to only drains on the cron — best effort, once in six
    hours the day it was added."""
    triggers = _workflow("tick.yml")[True]

    assert triggers["workflow_run"]["workflows"] == ["Fix", "Rework"]


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


def test_a_mention_answers_the_owner_only():
    """The rework workflow fires on every comment of a public repository; the job that acts on a
    mention runs only for a body that mentions `@claude`, written by the owner — the action's own
    write-access check is the other half of that guard."""
    guard = _jobs("rework.yml")["queue"]["if"]

    assert ("@claude" in guard, "repository_owner" in guard) == (True, True)


def test_a_mention_queues_the_pull_request_instead_of_starting_a_run():
    """A run fired by the mention itself is a run the tick never saw: ten mentions at once take
    ten runners. The mention only puts `to-rework` on; the tick alone hands the pull request over
    by putting `reworking` on it, and that label is what fires the run."""
    guard = _bot_job("rework.yml")["if"]

    assert guard == (
        "github.event.label.name == 'reworking' && github.actor == github.repository_owner"
    )


def test_the_queueing_job_waits_for_nothing():
    """The label is the queue, so it has to land while the mention is still fresh. In the bot's
    own group it would sit behind the two-hour run it is meant to line up after."""
    queue = _jobs("rework.yml")["queue"]

    assert "concurrency" not in queue


def test_each_headless_run_invokes_a_skill_that_exists():
    """Every headless run is a skill invocation — the skill and `CLAUDE.md` carry the runner's
    rules, the workflow only names it. A name no skill answers to leaves the run with a bare
    prompt and none of those rules, and nothing else fails."""
    invoked = {_action_step(w)["with"]["prompt"].split(" ")[0].removeprefix("/") for w in _BOTS}
    existing = {path.parent.name for path in _SKILLS.glob("*/SKILL.md")}

    assert invoked - existing == set()


@pytest.mark.parametrize("workflow", _BOTS)
def test_a_run_that_dies_releases_its_subject(workflow):
    """The in-flight label is set by the bot, so a run that ends before its own end — cancelled,
    timed out, or a turn that stopped — leaves it with nobody behind it, and the tick reads the
    queue as busy forever. A step that runs whatever happened turns it into a terminal state the
    owner can see."""
    steps = _bot_job(workflow)["steps"]
    action = next(i for i, step in enumerate(steps) if _is_action(step))
    after = [step for step in steps[action + 1 :] if step.get("if") == "always()"]

    assert [(_IN_FLIGHT[workflow] in s["run"], "stalled" in s["run"]) for s in after] == [
        (True, True)
    ]
