from pathlib import Path

import pytest

from mycode.teams.models import TaskCreateRequest, TeamError
from mycode.teams.tasks import SharedTaskService

from team_testkit import team_store


def test_task_permissions_dependencies_and_cycle_detection(tmp_path: Path) -> None:
    store, authority, lead, members, identities = team_store(tmp_path, approval_names=())
    service = SharedTaskService(store, authority)
    first = service.create_task(lead, TaskCreateRequest("first", assignee_id=members["alice"].member_id))
    second = service.create_task(lead, TaskCreateRequest(
        "second", assignee_id=members["bob"].member_id, dependency_ids=(first.task_id,),
    ))
    assert first.status == "ready"
    assert second.status == "dependency_blocked"
    with pytest.raises(TeamError, match="循环"):
        service.set_dependencies(lead, first.task_id, (second.task_id,), first.revision)
    with pytest.raises(TeamError, match="不能指派"):
        service.create_task(identities["alice"], TaskCreateRequest("illegal", assignee_id=members["alice"].member_id))


def test_completed_dependency_makes_successor_ready(tmp_path: Path) -> None:
    store, authority, lead, members, identities = team_store(tmp_path, approval_names=())
    service = SharedTaskService(store, authority)
    first = service.create_task(lead, TaskCreateRequest("first", assignee_id=members["alice"].member_id))
    second = service.create_task(lead, TaskCreateRequest("second", assignee_id=members["bob"].member_id, dependency_ids=(first.task_id,)))
    running = service.request_start(identities["alice"], first.task_id, first.revision)
    service.complete(identities["alice"], first.task_id, "done", running.revision)
    assert service.get_task(lead, second.task_id).status == "ready"
