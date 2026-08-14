from pathlib import Path

from mycode.teams.runtime import TeamRuntime
from mycode.tools.registry import create_default_registry
from mycode.types import AppConfig

from team_testkit import git_repo, role


def test_runtime_binds_one_team_and_injects_tools_only_after_binding(tmp_path: Path) -> None:
    repo = git_repo(tmp_path / "repo")
    config = AppConfig("deepseek", "demo", "https://example.com", "key")
    runtime = TeamRuntime(config, repo, lambda name: role(name), user_root=tmp_path)
    base = create_default_registry()
    assert runtime.registry_for(base, "session", "default") is base
    binding = runtime.create("session", "alpha")
    names = set(runtime.registry_for(base, "session", "default").names())
    assert binding.team_name == "alpha"
    assert {"TeamMember", "SharedTask", "Mailbox", "TeamIntegrate"} <= names
    runtime.clear_session("session")
    assert runtime.registry_for(base, "session", "default") is base
    runtime.close()
