from __future__ import annotations

import os
import shutil
import signal
import subprocess
from pathlib import Path

from mycode.teams.identity import WorkerTicketManager
from mycode.teams.models import MemberProcessIdentity, TeamError, TeamMemberSnapshot

from .base import (
    BackendProbeRequest,
    BackendProbeResult,
    BackendStartResult,
    BackendStatus,
    BackendWakeResult,
    MemberStopResult,
)


class TmuxBackend:
    name = "tmux"

    def __init__(
        self,
        team_name: str,
        repository_id: str,
        *,
        tickets: WorkerTicketManager | None = None,
        executable: str = "mycode",
        timeout_seconds: float = 10.0,
    ) -> None:
        self.team_name = team_name
        self.repository_id = repository_id
        self.tickets = tickets or WorkerTicketManager()
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def probe(self, request: BackendProbeRequest) -> BackendProbeResult:
        executable = shutil.which("tmux")
        if executable is None:
            return BackendProbeResult("tmux", False, "tmux_not_found", "PATH 中未找到 tmux。")
        try:
            result = subprocess.run(
                (executable, "-V"), shell=False, capture_output=True, check=False,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return BackendProbeResult("tmux", False, "tmux_probe_timeout", "tmux 版本探测超时。")
        if result.returncode != 0:
            return BackendProbeResult("tmux", False, "tmux_probe_failed", "tmux 版本探测失败。")
        return BackendProbeResult("tmux", True, "available", result.stdout.decode("utf-8", errors="replace").strip())

    def start(self, member: TeamMemberSnapshot) -> BackendStartResult:
        if self.inspect(member).running:
            return BackendStartResult(False, "tmux", member.process, "成员 tmux pane 已在运行。")
        ticket = self.tickets.issue(self.team_name, member.member_id, self.repository_id)
        session = self._session_name(member)
        command = (
            self.executable, "team-worker", "--team", self.team_name, "--member", member.member_id,
            "--ticket", str(ticket.path),
        )
        try:
            completed = subprocess.run(
                ("tmux", "new-session", "-d", "-s", session, "-n", "worker", *command),
                shell=False, capture_output=True, check=False, timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            ticket.path.unlink(missing_ok=True)
            raise TeamError("tmux_start_failed", "无法启动或等待成员 tmux pane。") from exc
        if completed.returncode != 0:
            ticket.path.unlink(missing_ok=True)
            raise TeamError("tmux_start_failed", "无法创建成员 tmux pane。")
        try:
            pane, pid = self._pane_identity(session)
        except TeamError:
            subprocess.run(
                ("tmux", "kill-session", "-t", session), shell=False,
                capture_output=True, check=False, timeout=self.timeout_seconds,
            )
            ticket.path.unlink(missing_ok=True)
            raise
        process = MemberProcessIdentity(
            "tmux", tmux_session=session, tmux_window="worker", tmux_pane=pane, pane_pid=pid,
        )
        return BackendStartResult(True, "tmux", process, "成员 tmux pane 已启动。")

    def wake(self, member: TeamMemberSnapshot, message_id: str) -> BackendWakeResult:
        process = member.process
        if process is None or process.backend != "tmux" or not process.tmux_session:
            return BackendWakeResult(False, "成员没有可验证的 tmux 进程身份。")
        try:
            pane, pid = self._pane_identity(process.tmux_session)
        except TeamError as exc:
            return BackendWakeResult(False, exc.user_message)
        if pane != process.tmux_pane or pid != process.pane_pid:
            return BackendWakeResult(False, "tmux pane 身份或 PID 已变化，未发送信号。")
        try:
            os.kill(pid, signal.SIGUSR1)
        except OSError:
            return BackendWakeResult(False, "消息已落盘，但 SIGUSR1 唤醒失败。")
        return BackendWakeResult(True)

    def stop(self, member: TeamMemberSnapshot, timeout_seconds: float) -> MemberStopResult:
        session = member.process.tmux_session if member.process is not None else self._session_name(member)
        try:
            result = subprocess.run(("tmux", "kill-session", "-t", session), shell=False, capture_output=True, check=False, timeout=min(timeout_seconds, self.timeout_seconds))
        except FileNotFoundError:
            return MemberStopResult(True, "tmux 已不可用；成员进程按已停止处理。")
        except subprocess.TimeoutExpired:
            return MemberStopResult(False, "停止成员 tmux session 超时。")
        if result.returncode not in {0, 1}:
            return MemberStopResult(False, "停止成员 tmux session 失败。")
        return MemberStopResult(True, "成员 tmux session 已停止。")

    def inspect(self, member: TeamMemberSnapshot) -> BackendStatus:
        session = member.process.tmux_session if member.process is not None and member.process.tmux_session else self._session_name(member)
        try:
            result = subprocess.run(("tmux", "has-session", "-t", session), shell=False, capture_output=True, check=False, timeout=self.timeout_seconds)
        except (OSError, subprocess.TimeoutExpired):
            return BackendStatus(False, "tmux session 不可探测。")
        return BackendStatus(result.returncode == 0)

    @staticmethod
    def _session_name(member: TeamMemberSnapshot) -> str:
        return f"mycode-{member.member_id[-16:]}"

    @staticmethod
    def _pane_identity(session: str) -> tuple[str, int]:
        result = subprocess.run(
            ("tmux", "display-message", "-p", "-t", f"{session}:worker.0", "#{pane_id} #{pane_pid}"),
            shell=False, capture_output=True, check=False, timeout=10.0,
        )
        if result.returncode != 0:
            raise TeamError("tmux_identity_failed", "无法验证成员 tmux pane 身份。")
        text = result.stdout.decode("ascii", errors="strict").strip()
        pane, separator, pid_text = text.partition(" ")
        if not separator or not pane.startswith("%") or not pid_text.isdigit():
            raise TeamError("tmux_identity_failed", "tmux pane 身份格式无效。")
        return pane, int(pid_text)
