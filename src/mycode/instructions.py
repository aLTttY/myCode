from __future__ import annotations

import shlex
import os
from dataclasses import dataclass
from pathlib import Path


MAX_INCLUDE_DEPTH = 5


@dataclass(frozen=True)
class InstructionWarning:
    code: str
    source: str
    target: str


@dataclass(frozen=True)
class InstructionBundle:
    content: str = ""
    loaded_files: tuple[str, ...] = ()
    warnings: tuple[InstructionWarning, ...] = ()


class InstructionLoader:
    def load(self, workspace_root: Path, user_root: Path | None = None) -> InstructionBundle:
        workspace = workspace_root.resolve()
        user = (user_root or (Path.home() / ".mycode")).resolve()
        warnings: list[InstructionWarning] = []
        loaded: list[str] = []
        sections: list[str] = []

        project_visited: set[Path] = set()
        entries = (
            ("项目 .mycode 指令（最高优先级）", workspace / ".mycode" / "MYCODE.md", workspace, project_visited),
            ("项目根指令", workspace / "MYCODE.md", workspace, project_visited),
            ("用户指令（最低优先级）", user / "MYCODE.md", user, set()),
        )
        for title, path, scope, visited in entries:
            if not path.is_file():
                continue
            text = self._read(path, scope, visited, warnings, loaded, depth=0)
            if text.strip():
                sections.append(f"### {title}\n{text.rstrip()}")

        if not sections:
            return InstructionBundle(warnings=tuple(warnings), loaded_files=tuple(loaded))
        prefix = "以下自定义指令按优先级从高到低排列；发生冲突时必须优先遵循靠前内容。"
        return InstructionBundle(
            content=prefix + "\n\n" + "\n\n".join(sections),
            loaded_files=tuple(loaded),
            warnings=tuple(warnings),
        )

    def _read(
        self,
        path: Path,
        scope: Path,
        visited: set[Path],
        warnings: list[InstructionWarning],
        loaded: list[str],
        *,
        depth: int,
    ) -> str:
        source = self._display(path, scope)
        try:
            lexical = path.absolute()
            resolved = path.resolve(strict=True)
        except OSError:
            warnings.append(InstructionWarning("unreadable", source, source))
            return ""
        if not self._inside(resolved, scope):
            code = "symlink_escape" if self._inside(lexical, scope) else "outside_scope"
            warnings.append(InstructionWarning(code, source, source))
            return ""
        if resolved in visited:
            warnings.append(InstructionWarning("cycle", source, source))
            return ""
        visited.add(resolved)
        loaded.append(self._display(resolved, scope))
        try:
            lines = resolved.read_text(encoding="utf-8").splitlines(keepends=True)
        except (OSError, UnicodeError):
            warnings.append(InstructionWarning("unreadable", source, source))
            return ""

        output: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped.startswith("@include"):
                output.append(line)
                continue
            try:
                parts = shlex.split(stripped)
            except ValueError:
                parts = []
            if len(parts) != 2 or parts[0] != "@include":
                output.append(line)
                continue
            target_text = parts[1]
            target = Path(target_text)
            if depth >= MAX_INCLUDE_DEPTH:
                warnings.append(InstructionWarning("max_depth", source, target_text))
                continue
            if target.is_absolute():
                warnings.append(InstructionWarning("outside_scope", source, target_text))
                continue
            candidate = resolved.parent / target
            if not self._lexically_inside(candidate, scope):
                warnings.append(InstructionWarning("outside_scope", source, target_text))
                continue
            try:
                target_resolved = candidate.resolve(strict=True)
            except FileNotFoundError:
                warnings.append(InstructionWarning("missing_include", source, target_text))
                continue
            except OSError:
                warnings.append(InstructionWarning("unreadable", source, target_text))
                continue
            if not self._inside(target_resolved, scope):
                warnings.append(InstructionWarning("symlink_escape", source, target_text))
                continue
            output.append(
                self._read(
                    target_resolved,
                    scope,
                    visited,
                    warnings,
                    loaded,
                    depth=depth + 1,
                )
            )
        return "".join(output)

    @staticmethod
    def _inside(path: Path, root: Path) -> bool:
        try:
            path.resolve(strict=False).relative_to(root.resolve(strict=False))
            return True
        except ValueError:
            return False

    @staticmethod
    def _display(path: Path, root: Path) -> str:
        try:
            return path.resolve(strict=False).relative_to(root.resolve(strict=False)).as_posix()
        except ValueError:
            return path.name

    @staticmethod
    def _lexically_inside(path: Path, root: Path) -> bool:
        candidate = Path(os.path.abspath(path))
        boundary = Path(os.path.abspath(root))
        try:
            candidate.relative_to(boundary)
            return True
        except ValueError:
            return False
