"""The .gitignore pattern a worktree's own `node_modules` link depends on.

`make worktree` links a fresh worktree's `node_modules` to the shared install as a symlink
(`scripts/worktree.py`, `SHARED_LINKS`) rather than run `npm install` again. Git tracks a
symlink as a plain file, so a pattern with a trailing slash — which matches a directory only —
lets that symlink slip through and get staged by a plain `git add -A`.
"""

import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)


def test_a_node_modules_symlink_is_gitignored(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text((_ROOT / ".gitignore").read_text())
    _run("git", "init", "--quiet", cwd=tmp_path)
    (tmp_path / "real_target").mkdir()
    (tmp_path / "node_modules").symlink_to(tmp_path / "real_target")

    result = _run("git", "check-ignore", "node_modules", cwd=tmp_path)

    assert result.returncode == 0
