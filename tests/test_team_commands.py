from pathlib import Path

from mycode.commands.models import CommandInvocation
from mycode.teams.commands import team_command
from mycode.teams.runtime import TeamRuntime
from mycode.types import AppConfig

from team_testkit import git_repo, role


class FakeUI:
    def __init__(self):
        self.messages = []
    def session_status(self):
        return type("Session", (), {"session_id": "session"})()
    def display_message(self, text, *, error=False):
        self.messages.append((text, error))


def test_team_command_create_status_and_resume(tmp_path: Path) -> None:
    repo = git_repo(tmp_path / "repo")
    runtime = TeamRuntime(
        AppConfig("deepseek", "demo", "https://example.com", "key"),
        repo, lambda name: role(name), user_root=tmp_path,
    )
    spec = team_command(runtime)
    ui = FakeUI()
    spec.handler(CommandInvocation(spec, "team", "create alpha"), None, ui)
    spec.handler(CommandInvocation(spec, "team", "status"), None, ui)
    assert "team=alpha" in ui.messages[-1][0]
    runtime.clear_session("session")
    spec.handler(CommandInvocation(spec, "team", "resume alpha"), None, ui)
    assert "恢复" in ui.messages[-1][0]
    runtime.close()
