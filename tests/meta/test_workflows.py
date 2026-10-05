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

# The workflows running Claude headless: an issue to a pull request, a review to a push.
_BOTS = ("fix.yml", "rework.yml")

# Each bot's in-flight label.
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
    """Any label fires the workflow, the bot's own included: a workflow-level group would let a
    skipped run cancel the live one."""
    document = _workflow(workflow)

    assert ("concurrency" in document, "concurrency" in _bot_job(workflow)) == (False, True)


@pytest.mark.parametrize(
    ("workflow", "group"), [("fix.yml", "fix-bot"), ("rework.yml", "rework-bot")]
)
def test_a_bot_run_never_runs_beside_another_of_its_own(workflow, group):
    """One run per bot (the group names the bot), queued, never cancelled."""
    concurrency = _bot_job(workflow)["concurrency"]

    assert concurrency == {"group": group, "cancel-in-progress": False}


def test_a_fork_s_workflow_named_fix_cannot_tick():
    """`workflow_run` matches by name: a fork's "Fix" must not fire the tick with our secrets."""
    job = _only_job("tick.yml")

    assert job.get("if") == (
        "github.event_name != 'workflow_run' || "
        "github.event.workflow_run.head_repository.full_name == github.repository"
    )


def test_the_tick_hears_the_end_of_both_bots():
    """The end of each bot's run fires the tick, else its queue drains only on the cron."""
    triggers = _workflow("tick.yml")[True]

    assert triggers["workflow_run"]["workflows"] == ["Fix", "Rework"]


@pytest.mark.parametrize("workflow", _BOTS)
def test_the_bot_cannot_hand_its_turn_to_a_harness_that_never_returns(workflow):
    """Headless, a tool promising a later wake-up (`ScheduleWakeup`, a cron, a `Monitor`) ends the
    run with nothing pushed."""
    allowed, disallowed = _tool_lists(workflow)
    never = {"ScheduleWakeup", "CronCreate", "RemoteTrigger", "Workflow", "Monitor"}

    assert (never <= disallowed, never & allowed) == (True, set())


def test_the_fix_bot_cannot_reach_the_raw_github_api():
    """No `gh api`, where `-f body=@file` posts the string `@file`."""
    _, disallowed = _tool_lists("fix.yml")

    assert sorted(name for name in disallowed if name.startswith("Bash(")) == ["Bash(gh api:*)"]


def test_a_mention_answers_the_owner_only():
    """On a public repository's comments: only the owner's `@claude` mention acts."""
    guard = _jobs("rework.yml")["queue"]["if"]

    assert ("@claude" in guard, "repository_owner" in guard) == (True, True)


def test_a_mention_queues_the_pull_request_instead_of_starting_a_run():
    """The mention only queues (`to-rework`); the tick starts runs, one at a time."""
    guard = _bot_job("rework.yml")["if"]

    assert guard == (
        "github.event.label.name == 'reworking' && github.actor == github.repository_owner"
    )


def test_the_queueing_job_waits_for_nothing():
    """Outside the bot's group, which would hold it behind a two-hour run."""
    queue = _jobs("rework.yml")["queue"]

    assert "concurrency" not in queue


def test_each_headless_run_invokes_a_skill_that_exists():
    """An unknown skill name would leave the run with a bare prompt, silently."""
    invoked = {_action_step(w)["with"]["prompt"].split(" ")[0].removeprefix("/") for w in _BOTS}
    existing = {path.parent.name for path in _SKILLS.glob("*/SKILL.md")}

    assert invoked - existing == set()


@pytest.mark.parametrize("workflow", _BOTS)
def test_a_run_that_dies_releases_its_subject(workflow):
    """A run ending early would leave its label, and the queue busy forever: an always-run step
    sets a visible terminal state."""
    steps = _bot_job(workflow)["steps"]
    action = next(i for i, step in enumerate(steps) if _is_action(step))
    after = [step for step in steps[action + 1 :] if step.get("if") == "always()"]

    assert [(_IN_FLIGHT[workflow] in s["run"], "to-unblock" in s["run"]) for s in after] == [
        (True, True)
    ]
