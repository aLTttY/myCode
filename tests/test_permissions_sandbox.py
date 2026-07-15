from pathlib import Path

import pytest

from mycode.permissions.models import PermissionValidationError
from mycode.permissions.sandbox import resolve_workspace_path, validate_command_paths, validate_pattern_target


def test_workspace_path_returns_normalized_relative_path(tmp_path: Path) -> None:
    nested = tmp_path / "src"
    nested.mkdir()
    resolved, relative = resolve_workspace_path(tmp_path, "src/../src/new.py")
    assert resolved == nested / "new.py"
    assert relative == "src/new.py"


@pytest.mark.parametrize("value", ["/tmp/outside", "../outside"])
def test_file_path_rejects_absolute_and_parent_escape(tmp_path: Path, value: str) -> None:
    with pytest.raises(PermissionValidationError, match="项目目录|绝对路径"):
        resolve_workspace_path(tmp_path, value)


def test_file_path_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PermissionValidationError, match="项目目录"):
        resolve_workspace_path(tmp_path, "link/secret.txt")


def test_file_path_allows_internal_symlink(tmp_path: Path) -> None:
    target = tmp_path / "actual"
    target.mkdir()
    (tmp_path / "link").symlink_to(target, target_is_directory=True)
    _, relative = resolve_workspace_path(tmp_path, "link/file.txt")
    assert relative == "actual/file.txt"


def test_command_rejects_explicit_outside_path(tmp_path: Path) -> None:
    with pytest.raises(PermissionValidationError, match="项目目录"):
        validate_command_paths("cat /etc/passwd", tmp_path)


def test_command_rejects_redirection_escape(tmp_path: Path) -> None:
    with pytest.raises(PermissionValidationError, match="项目目录"):
        validate_command_paths("echo hello > ../outside.txt", tmp_path)


def test_command_rejects_symlink_path(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside-command"
    outside.mkdir()
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PermissionValidationError, match="项目目录"):
        validate_command_paths("cat link/secret.txt", tmp_path)


def test_command_allows_no_path_and_internal_path(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("ok", encoding="utf-8")
    validate_command_paths("git status", tmp_path)
    validate_command_paths("cat README.md", tmp_path)


@pytest.mark.parametrize("value", ["../*", "/tmp/*", "~/docs/*"])
def test_search_pattern_rejects_escape(value: str) -> None:
    with pytest.raises(PermissionValidationError):
        validate_pattern_target(value)
