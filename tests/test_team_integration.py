import subprocess
from pathlib import Path

from mycode.teams.integration import IntegrationService
from mycode.teams.models import TaskCreateRequest
from mycode.teams.tasks import SharedTaskService

from team_testkit import live_team


def _commit_member(member, filename: str, content: str) -> str:
    path = Path(member.worktree.worktree_path)
    (path / filename).write_text(content, encoding="utf-8")
    subprocess.run(("git", "add", filename), cwd=path, check=True)
    subprocess.run(("git", "commit", "-m", f"change {filename}"), cwd=path, check=True, capture_output=True)
    return subprocess.run(("git", "rev-parse", "HEAD"), cwd=path, check=True, capture_output=True, text=True).stdout.strip()


def test_atomic_integration_advances_lead_only_after_validation(tmp_path: Path) -> None:
    repo, store, authority, service, lead, members, identities = live_team(tmp_path)
    tasks = SharedTaskService(store, authority)
    member = members["alice"]
    task = tasks.create_task(lead, TaskCreateRequest("change", assignee_id=member.member_id))
    running = tasks.request_start(identities["alice"], task.task_id, task.revision)
    commit = _commit_member(member, "feature.txt", "done\n")
    tasks.complete(identities["alice"], task.task_id, "done", running.revision, result_commit=commit)
    integration = IntegrationService(store, authority, git=service.git, worktrees=service.worktrees)
    plan = integration.preflight(lead)
    result = integration.start(lead, plan)
    assert result.status == "completed"
    assert (repo / "feature.txt").read_text(encoding="utf-8") == "done\n"
    assert store.load("alpha").tasks[task.task_id].integrated_by == result.integration_id


def test_integration_failure_retry_leaves_lead_unchanged(tmp_path: Path) -> None:
    repo, store, authority, service, lead, members, identities = live_team(tmp_path, ("alice", "bob"))
    tasks = SharedTaskService(store, authority)
    before = subprocess.run(("git", "rev-parse", "HEAD"), cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
    task_records = []
    for name, content in (("alice", "alice\n"), ("bob", "bob\n")):
        member = members[name]
        task = tasks.create_task(lead, TaskCreateRequest(name, assignee_id=member.member_id))
        running = tasks.request_start(identities[name], task.task_id, task.revision)
        commit = _commit_member(member, "README.md", content)
        tasks.complete(identities[name], task.task_id, "done", running.revision, result_commit=commit)
        task_records.append(task)
    integration = IntegrationService(store, authority, git=service.git, worktrees=service.worktrees)
    result = integration.start(lead, integration.preflight(lead))
    assert result.status == "conflicted"
    after = subprocess.run(("git", "rev-parse", "HEAD"), cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
    assert after == before
    assert (repo / "README.md").read_text(encoding="utf-8") == "base\n"

    integration.abort(lead, result.integration_id)
    alice_path = Path(members["alice"].worktree.worktree_path)
    bob_commit = store.load("alpha").tasks[task_records[1].task_id].result_commit
    merge = subprocess.run(("git", "merge", "--no-edit", bob_commit), cwd=alice_path, capture_output=True)
    assert merge.returncode != 0
    (alice_path / "README.md").write_text("alice + bob\n", encoding="utf-8")
    subprocess.run(("git", "add", "README.md"), cwd=alice_path, check=True)
    subprocess.run(("git", "commit", "-m", "resolve delegated conflict"), cwd=alice_path, check=True, capture_output=True)
    resolved_commit = subprocess.run(("git", "rev-parse", "HEAD"), cwd=alice_path, check=True, capture_output=True, text=True).stdout.strip()
    fix = tasks.create_task(lead, TaskCreateRequest(
        "resolve conflict", assignee_id=members["alice"].member_id,
        dependency_ids=tuple(item.task_id for item in task_records),
    ))
    running = tasks.request_start(identities["alice"], fix.task_id, fix.revision)
    tasks.complete(identities["alice"], fix.task_id, "resolved", running.revision, result_commit=resolved_commit)
    retry = integration.start(lead, integration.preflight(lead, (fix.task_id,)))
    assert retry.status == "completed"
    assert (repo / "README.md").read_text(encoding="utf-8") == "alice + bob\n"
