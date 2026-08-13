from __future__ import annotations

import subprocess
from pathlib import Path


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", *args),
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip()


def init_repo(path: Path) -> Path:
    path.mkdir()
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "MewCode Test")
    git(path, "config", "user.email", "mewcode@example.invalid")
    (path / ".gitignore").write_text(
        ".mycode/worktrees/\n.mycode/worktree.json\n.mycode/memory/\nconfig.yaml\n.venv/\n*.log\n",
        encoding="utf-8",
    )
    (path / "tracked.txt").write_text("base\n", encoding="utf-8")
    git(path, "add", ".gitignore", "tracked.txt")
    git(path, "commit", "-m", "base")
    return path
