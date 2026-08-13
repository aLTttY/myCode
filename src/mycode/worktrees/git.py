from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from .models import GitResult, WorktreeError, WorktreeRegistration
from .paths import filesystem_repository_id


class GitRunner:
    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
        optional_locks: bool = False,
        check: bool = True,
    ) -> GitResult:
        if not args or any(not isinstance(item, str) or "\0" in item for item in args):
            raise WorktreeError("invalid_git_args", "Git 参数无效。")
        env = dict(os.environ)
        if environment:
            env.update(environment)
        env.update(
            {
                "GIT_PAGER": "cat",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
            }
        )
        if optional_locks:
            env["GIT_OPTIONAL_LOCKS"] = "0"
        try:
            completed = subprocess.run(
                ("git", *args),
                cwd=cwd,
                shell=False,
                input=None,
                capture_output=True,
                timeout=timeout_seconds or self.timeout_seconds,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise WorktreeError("git_timeout", f"Git 操作超时：{args[0]}。") from exc
        except OSError as exc:
            raise WorktreeError("git_unavailable", "无法启动 Git。") from exc
        result = GitResult(completed.returncode, completed.stdout, completed.stderr)
        if check and result.returncode != 0:
            raise WorktreeError("git_failed", f"Git 操作失败：{args[0]}。")
        return result

    def capture_repository(self, workspace: Path) -> tuple[str, str, str]:
        top = self._text(("rev-parse", "--show-toplevel"), workspace)
        if Path(top).resolve() != workspace.resolve():
            raise WorktreeError("workspace_not_root", "Worktree 隔离要求主工作区为仓库根目录。")
        head = self._text(("rev-parse", "--verify", "HEAD^{commit}"), workspace)
        ref = self._text(("symbolic-ref", "-q", "HEAD"), workspace)
        if not ref.startswith("refs/heads/"):
            raise WorktreeError("detached_head", "主工作区 HEAD 必须指向本地分支。")
        return filesystem_repository_id(workspace), head, ref

    def validate_branch_ref(self, workspace: Path, branch_ref: str) -> None:
        result = self.run(
            ("check-ref-format", "--branch", branch_ref.removeprefix("refs/heads/")),
            cwd=workspace,
            optional_locks=True,
            check=False,
        )
        if result.returncode != 0:
            raise WorktreeError("invalid_branch", "Worktree 临时分支名不符合 Git ref 规则。")

    def ref_exists(self, workspace: Path, ref: str) -> bool:
        return self.run(("show-ref", "--verify", "--quiet", ref), cwd=workspace, optional_locks=True, check=False).returncode == 0

    def ref_tip(self, workspace: Path, ref: str) -> str:
        return self._text(("rev-parse", "--verify", f"{ref}^{{commit}}"), workspace)

    def add_worktree(self, workspace: Path, target: Path, branch_ref: str, base: str) -> None:
        branch = branch_ref.removeprefix("refs/heads/")
        self.run(
            ("worktree", "add", "--no-track", "--lock", "-b", branch, str(target), base),
            cwd=workspace,
        )

    def unlock_worktree(self, workspace: Path, target: Path) -> None:
        self.run(("worktree", "unlock", str(target)), cwd=workspace)

    def remove_worktree(self, workspace: Path, target: Path) -> None:
        self.run(("worktree", "remove", str(target)), cwd=workspace)

    def delete_ref(self, workspace: Path, ref: str, expected_old: str) -> None:
        self.run(("update-ref", "-d", ref, expected_old), cwd=workspace)

    def registrations(self, workspace: Path) -> tuple[WorktreeRegistration, ...]:
        raw = self.run(
            ("worktree", "list", "--porcelain", "-z"),
            cwd=workspace,
            optional_locks=True,
        ).stdout
        return parse_worktree_list(raw)

    def registration_for(self, workspace: Path, target: Path) -> WorktreeRegistration | None:
        expected = target.resolve(strict=False)
        for item in self.registrations(workspace):
            if item.path.resolve(strict=False) == expected:
                return item
        return None

    def status(self, target: Path, environment: Mapping[str, str] | None = None) -> tuple[bool, bool]:
        raw = self.run(
            ("status", "--porcelain=v1", "-z", "--untracked-files=all"),
            cwd=target,
            environment=environment,
            optional_locks=True,
        ).stdout
        tracked = False
        untracked = False
        for entry in (item for item in raw.split(b"\0") if item):
            if len(entry) < 3:
                raise WorktreeError("invalid_porcelain", "Git status 机器格式无效。")
            code = entry[:2]
            if code == b"??":
                untracked = True
            elif code != b"!!":
                tracked = True
        return tracked, untracked

    def ignored_untracked(
        self,
        target: Path,
        environment: Mapping[str, str] | None = None,
    ) -> tuple[str, ...]:
        raw = self.run(
            ("ls-files", "--others", "--ignored", "--exclude-standard", "-z"),
            cwd=target,
            environment=environment,
            optional_locks=True,
        ).stdout
        paths: list[str] = []
        for item in (value for value in raw.split(b"\0") if value):
            try:
                value = item.decode("utf-8", errors="strict").rstrip("/")
            except UnicodeDecodeError as exc:
                raise WorktreeError("invalid_porcelain", "Git ignored 文件路径不是有效 UTF-8。") from exc
            candidate = Path(value)
            if not value or candidate.is_absolute() or "\\" in value or any(
                part in {"", ".", ".."} for part in value.split("/")
            ):
                raise WorktreeError("invalid_porcelain", "Git ignored 文件路径无效。")
            paths.append(value)
        return tuple(paths)

    def new_commits(self, workspace: Path, base: str, branch_ref: str) -> tuple[str, ...]:
        value = self.run(
            ("rev-list", "--reverse", f"{base}..{branch_ref}"),
            cwd=workspace,
            optional_locks=True,
        ).stdout.decode("ascii", errors="strict")
        commits = tuple(line for line in value.splitlines() if line)
        if any(len(item) != 40 or any(ch not in "0123456789abcdef" for ch in item) for item in commits):
            raise WorktreeError("invalid_commit", "Git 返回了无效 commit ID。")
        return commits

    def is_ancestor(self, workspace: Path, commit: str, ref: str) -> bool:
        result = self.run(
            ("merge-base", "--is-ancestor", commit, ref),
            cwd=workspace,
            optional_locks=True,
            check=False,
        )
        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
        raise WorktreeError("git_failed", "Git 无法判断提交祖先关系。")

    def delivery_refs(self, workspace: Path, task_id: str, branch_ref: str) -> tuple[str, ...]:
        suffix = branch_ref.removeprefix("refs/heads/")
        refs = self.run(
            ("for-each-ref", "--format=%(refname)", f"refs/remotes/*/{suffix}"),
            cwd=workspace,
            optional_locks=True,
        ).stdout.decode("utf-8", errors="strict").splitlines()
        upstream = self.run(
            ("for-each-ref", "--format=%(upstream)", branch_ref),
            cwd=workspace,
            optional_locks=True,
        ).stdout.decode("utf-8", errors="strict").strip()
        if upstream.startswith("refs/remotes/"):
            refs.append(upstream)
        return tuple(dict.fromkeys(ref for ref in refs if ref.startswith("refs/remotes/") and task_id in ref))

    def check_ignored(self, target: Path, relative: str, environment: Mapping[str, str] | None = None) -> bool:
        return self.run(
            ("check-ignore", "--quiet", "--no-index", "--", relative),
            cwd=target,
            environment=environment,
            optional_locks=True,
            check=False,
        ).returncode == 0

    def _text(self, args: Sequence[str], cwd: Path) -> str:
        try:
            return self.run(args, cwd=cwd, optional_locks=True).stdout.decode("utf-8", errors="strict").strip()
        except UnicodeDecodeError as exc:
            raise WorktreeError("invalid_git_output", "Git 返回了无效 UTF-8。") from exc


def parse_worktree_list(raw: bytes) -> tuple[WorktreeRegistration, ...]:
    records: list[WorktreeRegistration] = []
    current: dict[str, bytes | bool] = {}
    for field in raw.split(b"\0"):
        if not field:
            if current:
                records.append(_registration(current))
                current = {}
            continue
        key, separator, value = field.partition(b" ")
        name = key.decode("ascii", errors="strict")
        if name in current:
            raise WorktreeError("invalid_porcelain", "Git Worktree 机器格式含重复字段。")
        current[name] = value if separator else True
    if current:
        records.append(_registration(current))
    return tuple(records)


def _registration(fields: dict[str, bytes | bool]) -> WorktreeRegistration:
    if not isinstance(fields.get("worktree"), bytes) or not isinstance(fields.get("HEAD"), bytes):
        raise WorktreeError("invalid_porcelain", "Git Worktree 机器格式缺少必要字段。")
    branch = fields.get("branch", b"")
    if branch is True or not isinstance(branch, bytes):
        branch = b""
    try:
        return WorktreeRegistration(
            path=Path(fields["worktree"].decode("utf-8")),  # type: ignore[union-attr]
            head=fields["HEAD"].decode("ascii"),  # type: ignore[union-attr]
            branch_ref=branch.decode("utf-8"),
            locked="locked" in fields,
        )
    except UnicodeDecodeError as exc:
        raise WorktreeError("invalid_porcelain", "Git Worktree 机器格式编码无效。") from exc
