from mycode.agents.bridge import ParentRequestBridge, freeze_parent_request, request_fingerprint
from mycode.providers.base import ChatRequest
from mycode.tools.registry import create_default_registry
from mycode.types import Message


def test_freeze_parent_request_preserves_order_and_deep_copies() -> None:
    registry = create_default_registry()
    request = ChatRequest(
        stable_system_prompt="system",
        dynamic_system_messages=(),
        messages=(Message(role="user", content="hello"),),
        optional_system_prompt="optional",
        tools=tuple(registry.tool_specs()),
    )

    snapshot = freeze_parent_request("session", "default", request, registry)

    assert snapshot.request == request
    assert snapshot.request is not request
    assert snapshot.registry is not registry
    assert snapshot.registry.names() == registry.names()
    assert snapshot.request_fingerprint == request_fingerprint(request)


def test_parent_request_bridge_checks_session_and_clear_fingerprint() -> None:
    request = ChatRequest("system", (), (Message(role="user", content="hello"),))
    snapshot = freeze_parent_request("session", "plan", request, create_default_registry())
    bridge = ParentRequestBridge()
    bridge.publish(snapshot)

    assert bridge.current("session") == snapshot
    bridge.clear("wrong")
    assert bridge.current("session") == snapshot
    bridge.clear(snapshot.request_fingerprint)

    try:
        bridge.current("session")
    except Exception as exc:
        assert "没有可用于 Fork" in str(exc)
    else:
        raise AssertionError("cleared bridge returned a snapshot")
