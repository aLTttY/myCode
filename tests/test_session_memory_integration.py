from __future__ import annotations

from pathlib import Path

from mycode.agent.config import AgentRequest
from mycode.agent.runner import AgentRunner
from mycode.instructions import InstructionBundle
from mycode.memory import MemoryStore
from mycode.permissions.service import PermissionService
from mycode.sessions import SessionJournal, SessionLoader
from mycode.tools.registry import create_default_registry
from mycode.types import Message, StreamEvent, ToolContext


class ScriptedProvider:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def stream_chat(self, request):
        self.calls.append(request)
        yield from next(self.responses)


class RecordingWorker:
    def __init__(self) -> None:
        self.snapshots = []

    def submit(self, snapshot):
        self.snapshots.append(snapshot)
        return "job"

    def drain(self, timeout=5.0):
        return ()

    def take_notices(self):
        return ()


def _response(text: str):
    return [StreamEvent(type="text_delta", text=text), StreamEvent(type="message_done")]


def test_agent_persists_then_restores_and_injects_one_time_gap(tmp_path: Path) -> None:
    journal = SessionJournal(tmp_path)
    first_provider = ScriptedProvider([_response("first")])
    worker = RecordingWorker()
    first = AgentRunner(
        first_provider,
        create_default_registry(),
        ToolContext(workspace_root=tmp_path),
        permission_service=PermissionService.with_mode("allow"),
        session_journal=journal,
        memory_worker=worker,  # type: ignore[arg-type]
    )
    list(first.run(AgentRequest("hello")))
    first.close()

    loaded = SessionLoader().load(journal.path)
    assert [message.role for message in loaded.messages] == ["user", "assistant"]
    assert worker.snapshots[0].assistant_text == "first"

    resumed_journal = SessionJournal(tmp_path, journal.session_id)
    second_provider = ScriptedProvider([_response("second"), _response("third")])
    resumed = AgentRunner(
        second_provider,
        create_default_registry(),
        ToolContext(workspace_root=tmp_path),
        permission_service=PermissionService.with_mode("allow"),
        session_journal=resumed_journal,
        restored_messages=loaded.messages,
        time_gap_reminder="距上次会话活动超过 24 小时。",
    )
    list(resumed.run(AgentRequest("continue")))
    list(resumed.run(AgentRequest("again")))
    resumed.close()

    assert any(item.tag == "mewcode_time_gap" for item in second_provider.calls[0].dynamic_system_messages)
    assert not any(item.tag == "mewcode_time_gap" for item in second_provider.calls[1].dynamic_system_messages)


def test_agent_injects_instructions_and_project_memory_before_user_memory(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path, tmp_path / "home" / ".mycode")
    project_root = store.root_for("project")
    user_root = store.root_for("user")
    project_root.mkdir(parents=True)
    user_root.mkdir(parents=True)
    (project_root / "index.md").write_text("PROJECT MEMORY", encoding="utf-8")
    (user_root / "index.md").write_text("USER MEMORY", encoding="utf-8")
    provider = ScriptedProvider([_response("done")])
    agent = AgentRunner(
        provider,
        create_default_registry(),
        ToolContext(workspace_root=tmp_path),
        instruction_bundle=InstructionBundle(content="LOCAL INSTRUCTION"),
        memory_store=store,
    )

    list(agent.run(AgentRequest("go")))

    optional = provider.calls[0].optional_system_prompt
    assert "LOCAL INSTRUCTION" in optional
    assert optional.index("PROJECT MEMORY") < optional.index("USER MEMORY")


def test_new_session_preserves_old_log_and_clears_context(tmp_path: Path) -> None:
    journal = SessionJournal(tmp_path)
    provider = ScriptedProvider([_response("done")])
    agent = AgentRunner(
        provider,
        create_default_registry(),
        ToolContext(workspace_root=tmp_path),
        session_journal=journal,
    )
    list(agent.run(AgentRequest("old")))

    new_id, warnings = agent.new_session()

    assert warnings == ()
    assert new_id != journal.session_id
    assert journal.path.exists()
    assert agent.messages == ()
    agent.close()
