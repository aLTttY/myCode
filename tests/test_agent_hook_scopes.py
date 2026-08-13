from mycode.hooks.events import HookEventFactory
from mycode.hooks.models import HookRule, HookSnapshot, PromptAction
from mycode.hooks.runtime import HookRuntime


def test_child_hook_scopes_isolate_prompts_and_share_once_claim(tmp_path) -> None:
    snapshot = HookSnapshot(
        (
            HookRule(
                "project:1",
                "project",
                tmp_path / "hooks.yaml",
                1,
                "message_received",
                None,
                PromptAction("one prompt", once=True),
            ),
        )
    )
    root = HookRuntime(snapshot, HookEventFactory(tmp_path))
    root.begin_session("session", "new")
    first = root.fork_scope("session", "task-1", kind="defined", role="explore")
    second = root.fork_scope("session", "task-2", kind="fork")
    first.begin_turn("default", "agent")
    second.begin_turn("default", "agent")

    first.message_received("first")
    second.message_received("second")

    assert len(first.reserve_prompts().instructions) == 1
    assert second.reserve_prompts().instructions == ()
    first.close()
    second.close()
    root.close()


def test_child_hook_event_contains_agent_scope(tmp_path) -> None:
    factory = HookEventFactory(tmp_path)
    factory.set_session("session", "defined")
    factory.set_agent_scope("defined", task_id="task-1", role="explore")

    event = factory.build("message_received", message_role="user", message_content="x")

    assert event.payload["agent"] == {
        "kind": "defined",
        "task_id": "task-1",
        "role": "explore",
    }
