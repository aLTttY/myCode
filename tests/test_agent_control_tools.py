from types import MappingProxyType
import json

from mycode.agents.bridge import ParentRequestBridge, freeze_parent_request
from mycode.agents.models import AgentDefinition, AgentSnapshot, TaskOutcome
from mycode.agents.runtime import AgentRoleRuntime
from mycode.agents.tasks import AgentTaskManager
from mycode.agents.tools import AgentTool, TaskTool
from mycode.providers.base import ChatRequest
from mycode.tools.registry import create_default_registry
from mycode.types import AgentDelegationConfig, Message, ToolContext


def definition(name="explore"):
    return AgentDefinition(
        name, "read code", ("read_file",), (), "inherit", 4, "strict",
        "prompt", "project", f"{name}.md", name,
    )


def setup_tools(tmp_path):
    roles = AgentRoleRuntime(
        AgentSnapshot(MappingProxyType({"explore": definition()}), (), "one")
    )
    bridge = ParentRequestBridge()
    registry = create_default_registry()
    bridge.publish(
        freeze_parent_request(
            "session",
            "default",
            ChatRequest("system", (), (Message(role="user", content="parent"),), tools=tuple(registry.tool_specs())),
            registry,
        )
    )
    manager = AgentTaskManager(
        lambda spec, cancellation: TaskOutcome("completed", result=spec.prompt),
        max_concurrency=1,
    )
    config = AgentDelegationConfig(model_aliases=MappingProxyType({}))
    agent = AgentTool(
        roles, bridge, manager, lambda: "session", lambda: "model", config
    )
    task = TaskTool(manager, lambda: "session", config)
    return roles, bridge, manager, agent, task


def test_control_tool_schemas_stay_stable_when_roles_change(tmp_path) -> None:
    roles, bridge, manager, agent, task = setup_tools(tmp_path)
    before_agent = agent.spec.parameters
    before_task = task.spec.parameters
    roles.publish(
        AgentSnapshot(MappingProxyType({"other": definition("other")}), (), "two")
    )

    assert agent.spec.parameters == before_agent
    assert task.spec.parameters == before_task
    assert "other" in agent.spec.description
    manager.shutdown(1)


def test_defined_completes_inline_and_fork_is_forced_background(tmp_path) -> None:
    roles, bridge, manager, agent, task = setup_tools(tmp_path)
    context = ToolContext(tmp_path)

    defined = agent.run(
        {"type": "defined", "prompt": "inspect", "role": "explore"}, context
    )
    forked = agent.run(
        {"type": "fork", "prompt": "continue", "background": False}, context
    )

    assert defined.ok is True
    assert defined.data["status"] == "completed"
    assert defined.data["result"] == "inspect"
    json.dumps(defined.data)
    assert forked.ok is True
    assert forked.data["kind"] == "fork"
    assert forked.data["delivery_mode"] == "background"
    task_id = forked.data["task_id"]
    waited = task.run(
        {"action": "wait", "task_id": task_id, "timeout_seconds": 1}, context
    )
    assert waited.ok is True
    manager.shutdown(1)


def test_invalid_agent_arguments_do_not_create_task(tmp_path) -> None:
    roles, bridge, manager, agent, task = setup_tools(tmp_path)
    result = agent.run({"type": "defined", "prompt": "x"}, ToolContext(tmp_path))

    assert result.ok is False
    assert manager.list_tasks("session") == ()
    manager.shutdown(1)


def test_manual_foreground_detach_keeps_same_task_running(tmp_path) -> None:
    import threading

    gate = threading.Event()
    starts = []

    def execute(spec, cancellation):
        starts.append(spec.task_id)
        gate.wait(1)
        return TaskOutcome("completed", result="done")

    class ManualWaiter:
        def wait(self, task_id, done, timeout_seconds):
            return "manual"

    roles, bridge, old_manager, _, _ = setup_tools(tmp_path)
    old_manager.shutdown(1)
    manager = AgentTaskManager(execute, max_concurrency=1)
    agent = AgentTool(
        roles,
        bridge,
        manager,
        lambda: "session",
        lambda: "model",
        AgentDelegationConfig(),
        ManualWaiter(),
    )

    result = agent.run(
        {"type": "defined", "prompt": "inspect", "role": "explore"},
        ToolContext(tmp_path),
    )
    task_id = result.data["task_id"]
    gate.set()
    manager.wait_task("session", task_id, 1)

    assert result.data["delivery_mode"] == "background"
    assert starts == [task_id]
    manager.shutdown(1)
