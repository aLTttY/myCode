from collections import deque

from mycode.agent.cancellation import CancellationToken
from mycode.agents.bridge import freeze_parent_request
from mycode.agents.models import AgentDefinition, ChildRunSpec
from mycode.agents.permissions import ChildPermissionFactory
from mycode.agents.policy import ChildToolPolicy
from mycode.agents.runner import ChildAgentExecutor
from mycode.permissions.service import PermissionService
from mycode.providers.base import ChatRequest
from mycode.tools.registry import create_default_registry
from mycode.types import Message, StreamEvent, TokenUsage, ToolContext
from mycode.types import ToolResult, ToolSpec
from collections.abc import Mapping


class RecordingProvider:
    def __init__(self, responses):
        self.responses = deque(responses)
        self.requests = []

    def stream_chat(self, request):
        self.requests.append(request)
        yield from self.responses.popleft()


def role() -> AgentDefinition:
    return AgentDefinition(
        "explore", "explore", ("read_file",), (), "inherit", 4, "strict",
        "ROLE PROMPT", "builtin", "builtin:explore.md", "fingerprint",
    )


def executor(tmp_path, provider, registry=None):
    base = registry or create_default_registry()
    return ChildAgentExecutor(
        provider_supplier=lambda model: provider,
        base_registry=base,
        tool_context=ToolContext(tmp_path),
        permission_factory=ChildPermissionFactory(PermissionService.with_mode("default")),
        background_supplier=lambda task_id: False,
    )


def test_defined_agent_starts_with_clean_history_and_accumulates_usage(tmp_path) -> None:
    provider = RecordingProvider(
        [[
            StreamEvent(type="text_delta", text="done"),
            StreamEvent(
                type="token_usage",
                token_usage=TokenUsage(input_tokens=3, output_tokens=1, total_tokens=4),
            ),
            StreamEvent(type="message_done"),
        ]]
    )
    definition = role()
    policy = ChildToolPolicy(
        role=definition,
        parent_mode="default",
        background_allowed_tools=("read_file",),
    )
    spec = ChildRunSpec(
        "task", "session", "defined", "inspect", definition, "model", False,
        "default", None, policy,
    )

    outcome = executor(tmp_path, provider).run(spec, CancellationToken())

    assert outcome.status == "completed"
    assert outcome.result == "done"
    assert outcome.token_usage == TokenUsage(input_tokens=3, output_tokens=1, total_tokens=4)
    assert provider.requests[0].messages == (Message(role="user", content="inspect"),)
    assert "ROLE PROMPT" in provider.requests[0].optional_system_prompt
    assert [tool.name for tool in provider.requests[0].tools] == ["read_file"]


def test_fork_agent_preserves_parent_request_prefix_and_cache_usage(tmp_path) -> None:
    provider = RecordingProvider(
        [[
            StreamEvent(type="text_delta", text="forked"),
            StreamEvent(
                type="token_usage",
                token_usage=TokenUsage(cache_read_tokens=12, cache_creation_tokens=2),
            ),
            StreamEvent(type="message_done"),
        ]]
    )
    registry = create_default_registry()
    parent = ChatRequest(
        "system", (), (Message(role="user", content="parent"),),
        optional_system_prompt="optional", tools=tuple(registry.tool_specs()),
    )
    snapshot = freeze_parent_request("session", "default", parent, registry)
    policy = ChildToolPolicy(
        role=None,
        parent_mode="default",
        background_allowed_tools=registry.names(),
    )
    spec = ChildRunSpec(
        "task", "session", "fork", "child", None, "model", True,
        "default", snapshot, policy,
    )

    outcome = executor(tmp_path, provider, registry).run(spec, CancellationToken())

    first = provider.requests[0]
    assert first.stable_system_prompt == parent.stable_system_prompt
    assert first.optional_system_prompt == parent.optional_system_prompt
    assert first.tools == parent.tools
    assert first.messages[:-1] == parent.messages
    assert first.messages[-1] == Message(role="user", content="child")
    assert outcome.token_usage.cache_read_tokens == 12
    assert outcome.token_usage.cache_creation_tokens == 2


class ForbiddenAgentTool:
    def __init__(self):
        self.calls = 0

    @property
    def spec(self):
        return ToolSpec("Agent", "nested", {"type": "object"})

    def run(self, arguments: Mapping[str, object], context: ToolContext):
        self.calls += 1
        return ToolResult(True, "should not run", {})


def test_fork_keeps_agent_schema_but_runtime_denies_nested_call(tmp_path) -> None:
    forbidden = ForbiddenAgentTool()
    registry = create_default_registry()
    registry.register(forbidden)
    provider = RecordingProvider(
        [
            [
                StreamEvent(
                    type="tool_call_delta",
                    tool_call_id="nested",
                    tool_name="Agent",
                    arguments_delta='{"type":"fork","prompt":"nested"}',
                ),
                StreamEvent(
                    type="tool_call_done", tool_call_id="nested", tool_name="Agent"
                ),
                StreamEvent(type="message_done"),
            ],
            [
                StreamEvent(type="text_delta", text="recovered"),
                StreamEvent(type="message_done"),
            ],
        ]
    )
    parent = ChatRequest(
        "system", (), (Message(role="user", content="parent"),),
        tools=tuple(registry.tool_specs()),
    )
    snapshot = freeze_parent_request("session", "default", parent, registry)
    policy = ChildToolPolicy(
        role=None,
        parent_mode="default",
        background_allowed_tools=("Agent",),
    )
    spec = ChildRunSpec(
        "task", "session", "fork", "child", None, "model", True,
        "default", snapshot, policy,
    )

    outcome = executor(tmp_path, provider, registry).run(spec, CancellationToken())

    assert outcome.status == "completed"
    assert outcome.result == "recovered"
    assert forbidden.calls == 0
    assert "child_global_deny" in provider.requests[1].messages[-1].content
