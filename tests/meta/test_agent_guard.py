"""The `Agent|Task` hooks of `.claude/settings.json` run under dash on the runner: a bashism exits
2, which refuses every agent call."""

import json
import os
import subprocess
from pathlib import Path

_SETTINGS = Path(__file__).resolve().parents[2] / ".claude" / "settings.json"


def _agent_hooks() -> list[str]:
    (entry,) = json.loads(_SETTINGS.read_text())["hooks"]["PreToolUse"]
    return [hook["command"] for hook in entry["hooks"]]


def test_a_top_level_background_agent_passes_every_guard_under_dash():
    call = json.dumps({"tool_input": {"run_in_background": True}})
    env = {"PATH": os.environ["PATH"]}

    codes = [
        subprocess.run(["dash", "-c", hook], input=call, text=True, env=env, check=False).returncode
        for hook in _agent_hooks()
    ]

    assert codes == [0, 0]
