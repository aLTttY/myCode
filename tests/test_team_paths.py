from pathlib import Path

import pytest

from mycode.teams.models import TeamError
from mycode.teams.paths import mailbox_path, safe_child, team_dir, validate_team_name


def test_team_name_and_mailbox_paths_are_fixed_under_user_root(tmp_path: Path) -> None:
    assert team_dir("alpha-1", tmp_path) == tmp_path / ".mycode" / "teams" / "alpha-1"
    assert mailbox_path("alpha-1", "lead", tmp_path).name == "lead.jsonl"
    for value in ("Lead", "../x", "a/b", ".locks", ""):
        with pytest.raises(TeamError):
            validate_team_name(value)


def test_safe_child_rejects_existing_symlink(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(tmp_path)
    with pytest.raises(TeamError, match="符号链接"):
        safe_child(root, "link", "escape", allow_missing=True)
