from collections import deque
from collections.abc import Mapping
import json
from types import MappingProxyType

from mycode.agent.config import AgentRequest
from mycode.agent.runner import AgentRunner
from mycode.agents.bridge import ParentRequestBridge
from mycode.agents.models import AgentDefinition, AgentSnapshot, ChildRunSpec, TaskOutcome
from mycode.agents.permissions import ChildPermissionFactory
from mycode.agents.runner import ChildAgentExecutor
from mycode.agents.runtime import AgentRoleRuntime
from mycode.agents.tasks import AgentTaskManager
from mycode.agents.tools import AgentTool, TaskTool
from mycode.permissions.service import PermissionService
from mycode.sessions import SessionJournal
from mycode.tools.registry import ToolRegistry
from mycode.types import AgentDelegationConfig, StreamEvent, ToolContext, ToolResult, ToolSpec


class ScriptedProvider:
    def __init__(self, responses):
        self.responses = deque(responses)
        self.requests = []

    def stream_chat(self, request):
        self.requests.append(request)
        yield from self.responses.popleft()


class SnapshotTool:
    def __init__(self, bridge, session_id, seen):
        self.bridge = bridge
        self.session_id = session_id
        self.seen = seen

    @property
    def spec(self):
        return ToolSpec("read_file", "capture", {"type": "object"})

    def run(self, arguments: Mapping[str, object], context: ToolContext):
        self.seen.append(self.bridge.current(self.session_id))
        return ToolResult(True, "captured", {})


def tool_call_events():
    return [
        StreamEvent(
            type="tool_call_delta",
            tool_call_id="call-1",
            tool_name="read_file",
            arguments_delta='{"path":"x"}',
        ),
        StreamEvent(
            type="tool_call_done", tool_call_id="call-1", tool_name="read_file"
        ),
        StreamEvent(type="message_done"),
    ]


def completed_events(text="done"):
    return [
        StreamEvent(type="text_delta", text=text),
        StreamEvent(type="message_done"),
    ]


def test_parent_request_snapshot_exists_only_for_active_tool_batch(tmp_path) -> None:
    journal = SessionJournal(tmp_path)
    bridge = ParentRequestBridge()
    seen = []
    registry = ToolRegistry()
    registry.register(SnapshotTool(bridge, journal.session_id, seen))
    provider = ScriptedProvider([tool_call_events(), completed_events()])
    runner = AgentRunner(
        provider,
        registry,
        ToolContext(tmp_path),
        session_journal=journal,
        request_bridge=bridge,
    )

    list(runner.run(AgentRequest("inspect")))

    assert len(seen) == 1
    assert seen[0].request == provider.requests[0]
    assert seen[0].request.messages[-1].content == "inspect"
    try:
        bridge.current(journal.session_id)
    except Exception:
        pass
    else:
        raise AssertionError("request bridge leaked past tool batch")
    runner.close()


def task_spec(task_id: str, session_id: str) -> ChildRunSpec:
    return ChildRunSpec(
        task_id, session_id, "fork", "background", None, "model", True,
        "default", None,
    )


def test_background_inbox_is_injected_at_next_request_boundary_and_journaled(tmp_path) -> None:
    journal = SessionJournal(tmp_path)
    manager = AgentTaskManager(
        lambda spec, cancellation: TaskOutcome("completed", result="background result"),
        max_concurrency=1,
    )
    manager.submit(task_spec("task-1", journal.session_id))
    manager.wait_task(journal.session_id, "task-1", 1)
    provider = ScriptedProvider([completed_events("answer")])
    runner = AgentRunner(
        provider,
        ToolRegistry(),
        ToolContext(tmp_path),
        session_journal=journal,
        task_manager=manager,
    )

    assert len(provider.requests) == 0
    list(runner.run(AgentRequest("next question")))

    injected = provider.requests[0].messages[-1].content
    assert "<mewcode_agent_result>" in injected
    assert "task_id: task-1" in injected
    assert "background result" in injected
    assert "<current_user_message>\nnext question" in injected
    assert manager.take_inbox(journal.session_id) == ()
    assert runner.messages[0].content == injected
    runner.close()
    manager.shutdown(1)


def agent_call_events(arguments):
    return [
        StreamEvent(
            type="tool_call_delta",
            tool_call_id="agent-call",
            tool_name="Agent",
            arguments_delta=json.dumps(arguments),
        ),
        StreamEvent(
            type="tool_call_done", tool_call_id="agent-call", tool_name="Agent"
        ),
        StreamEvent(type="message_done"),
    ]


def test_defined_delegation_runs_end_to_end_without_child_history_pollution(tmp_path) -> None:
    journal = SessionJournal(tmp_path)
    bridge = ParentRequestBridge()
    permission = PermissionService.with_mode("default")
    registry = ToolRegistry()
    child_provider = ScriptedProvider([completed_events("child result")])
    holder = {}
    child = ChildAgentExecutor(
        provider_supplier=lambda model: child_provider,
        base_registry=registry,
        tool_context=ToolContext(tmp_path),
        permission_factory=ChildPermissionFactory(permission),
        background_supplier=lambda task_id: holder["manager"].is_background(task_id),
    )
    manager = AgentTaskManager(child.run, max_concurrency=1)
    holder["manager"] = manager
    definition = AgentDefinition(
        "worker", "work", (), (), "inherit", 4, "strict", "ROLE",
        "project", "worker.md", "worker",
    )
    roles = AgentRoleRuntime(
        AgentSnapshot(MappingProxyType({"worker": definition}), (), "roles")
    )
    config = AgentDelegationConfig(foreground_timeout_seconds=1)
    registry.register(
        AgentTool(
            roles, bridge, manager, lambda: journal.session_id,
            lambda: "model", config,
        )
    )
    registry.register(TaskTool(manager, lambda: journal.session_id, config))
    main_provider = ScriptedProvider(
        [
            agent_call_events(
                {"type": "defined", "prompt": "child task", "role": "worker"}
            ),
            completed_events("parent answer"),
        ]
    )
    runner = AgentRunner(
        main_provider,
        registry,
        ToolContext(tmp_path),
        session_journal=journal,
        request_bridge=bridge,
        task_manager=manager,
    )

    list(runner.run(AgentRequest("parent task")))

    assert child_provider.requests[0].messages[-1].content == "child task"
    assert [message.role for message in runner.messages] == [
        "user", "assistant", "tool", "assistant"
    ]
    assert runner.messages[-1].content == "parent answer"
    assert all("ROLE" not in message.content for message in runner.messages)
    tasks = manager.list_tasks(journal.session_id)
    assert len(tasks) == 1 and tasks[0].status == "completed"
    runner.close()
    manager.shutdown(1)


def test_fork_delegation_preserves_parent_prefix_and_delivers_once(tmp_path) -> None:
    journal = SessionJournal(tmp_path)
    bridge = ParentRequestBridge()
    permission = PermissionService.with_mode("default")
    registry = ToolRegistry()
    child_provider = ScriptedProvider([completed_events("fork result")])
    notifications = []
    holder = {}
    child = ChildAgentExecutor(
        provider_supplier=lambda model: child_provider,
        base_registry=registry,
        tool_context=ToolContext(tmp_path),
        permission_factory=ChildPermissionFactory(permission),
        background_supplier=lambda task_id: holder["manager"].is_background(task_id),
    )
    manager = AgentTaskManager(
        child.run,
        max_concurrency=1,
        notification_sink=notifications.append,
    )
    holder["manager"] = manager
    config = AgentDelegationConfig()
    roles = AgentRoleRuntime()
    registry.register(
        AgentTool(
            roles, bridge, manager, lambda: journal.session_id,
            lambda: "model", config,
        )
    )
    registry.register(TaskTool(manager, lambda: journal.session_id, config))
    main_provider = ScriptedProvider(
        [
            agent_call_events({"type": "fork", "prompt": "fork task"}),
            completed_events("delegated"),
            completed_events("after inbox"),
        ]
    )
    runner = AgentRunner(
        main_provider,
        registry,
        ToolContext(tmp_path),
        session_journal=journal,
        request_bridge=bridge,
        task_manager=manager,
    )

    list(runner.run(AgentRequest("parent request")))
    task = manager.list_tasks(journal.session_id)[0]
    manager.wait_task(journal.session_id, task.task_id, 1)

    parent_request = main_provider.requests[0]
    fork_request = child_provider.requests[0]
    assert fork_request.stable_system_prompt == parent_request.stable_system_prompt
    assert fork_request.dynamic_system_messages == parent_request.dynamic_system_messages
    assert fork_request.optional_system_prompt == parent_request.optional_system_prompt
    assert fork_request.tools == parent_request.tools
    assert fork_request.messages[:-1] == parent_request.messages
    assert fork_request.messages[-1].content == "fork task"
    assert len(notifications) == 1

    list(runner.run(AgentRequest("continue")))

    injected = main_provider.requests[2].messages[-1].content
    assert "fork result" in injected
    assert task.task_id in injected
    assert len(notifications) == 1
    runner.close()
    manager.shutdown(1)
