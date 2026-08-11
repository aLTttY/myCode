from __future__ import annotations

from pathlib import Path

from mycode.agent.cancellation import CancellationToken
from mycode.permissions.service import PermissionService
from mycode.providers.base import ChatRequest
from mycode.skills.isolated import IsolatedSkillRunner
from mycode.skills.models import (
    SkillDefinition,
    SkillInvocation,
    SkillSnapshot,
    immutable_mapping,
)
from mycode.tools.registry import create_default_registry
from mycode.types import AppConfig, ContextConfig, Message, StreamEvent, ToolContext


class ScriptedProvider:
    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        self.scripts = scripts
        self.calls: list[ChatRequest] = []

    def stream_chat(self, request: ChatRequest):
        self.calls.append(request)
        yield from self.scripts[min(len(self.calls) - 1, len(self.scripts) - 1)]


class ProviderFactory:
    def __init__(self, provider: ScriptedProvider) -> None:
        self.provider = provider
        self.configs: list[AppConfig] = []

    def __call__(self, config: AppConfig):
        self.configs.append(config)
        return self.provider


def definition(
    name: str,
    *,
    mode: str = "isolated",
    history: int | None = 0,
    model: str | None = None,
    tools: tuple[str, ...] = ("read_file",),
) -> SkillDefinition:
    return SkillDefinition(
        name=name,
        description=f"{name} description",
        allowed_tools=tools,
        mode=mode,  # type: ignore[arg-type]
        history=history,
        model=model,
        sop=f"SOP FOR {name}",
        compiled_sop=f"SOP FOR {name}",
        source="project",
        source_id=f"test:{name}",
        package_root=None,
        dedicated_tools=(),
        fingerprint=f"fp:{name}",
    )


def snapshot(*definitions: SkillDefinition) -> SkillSnapshot:
    return SkillSnapshot(
        definitions=immutable_mapping({item.name: item for item in definitions}),
        dedicated_tools=immutable_mapping(),
    )


def config(model: str = "main-model") -> AppConfig:
    return AppConfig(
        protocol="openai",
        model=model,
        base_url="https://example.invalid",
        api_key="secret",
        context=ContextConfig(window_tokens=128_000),
    )


def invocation(name: str, text: str = "current input") -> SkillInvocation:
    return SkillInvocation(name=name, input_text=text, origin="slash", runtime_mode="default")


def runner(
    tmp_path: Path,
    root: SkillDefinition,
    provider: ScriptedProvider,
    *others: SkillDefinition,
) -> tuple[IsolatedSkillRunner, ProviderFactory]:
    factory = ProviderFactory(provider)
    definitions = snapshot(root, *others)
    return (
        IsolatedSkillRunner(
            app_config=config(),
            base_registry=create_default_registry(),
            tool_context=ToolContext(workspace_root=tmp_path),
            permission_service=PermissionService.with_mode("allow"),
            snapshot_supplier=lambda: definitions,
            provider_factory=factory,
        ),
        factory,
    )


def tool_call(call_id: str, name: str, arguments: str) -> list[StreamEvent]:
    return [
        StreamEvent(type="tool_call_delta", tool_call_id=call_id, tool_name=name, arguments_delta=arguments),
        StreamEvent(type="tool_call_done", tool_call_id=call_id),
        StreamEvent(type="message_done"),
    ]


def test_isolated_uses_history_and_returns_only_final_assistant(tmp_path: Path) -> None:
    root = definition("review", history=1)
    provider = ScriptedProvider([
        [StreamEvent(type="text_delta", text="final review"), StreamEvent(type="message_done")]
    ])
    isolated, _ = runner(tmp_path, root, provider)
    history = (Message(role="user", content="earlier"), Message(role="assistant", content="answer"))

    result = isolated.run(invocation("review"), root, history, CancellationToken())

    assert result.status == "completed"
    assert result.summary == "final review"
    assert [message.content for message in provider.calls[0].messages] == [
        "earlier",
        "answer",
        "使用 Skill `review`。\n\nSkill 输入：\ncurrent input",
    ]
    assert "SOP FOR review" in provider.calls[0].optional_system_prompt
    assert {tool.name for tool in provider.calls[0].tools} == {"read_file", "load_skill"}


def test_isolated_model_override_only_changes_model(tmp_path: Path) -> None:
    root = definition("review", model="special-model")
    provider = ScriptedProvider([
        [StreamEvent(type="text_delta", text="done"), StreamEvent(type="message_done")]
    ])
    isolated, factory = runner(tmp_path, root, provider)

    result = isolated.run(invocation("review"), root, (), CancellationToken())

    assert result.status == "completed"
    assert factory.configs[0] == config(model="special-model")


def test_isolated_failure_and_cancellation_have_deterministic_summary(tmp_path: Path) -> None:
    root = definition("review")
    provider = ScriptedProvider([tool_call("1", "read_file", '{"path":"missing"}')])
    isolated, _ = runner(tmp_path, root, provider)
    token = CancellationToken()
    token.cancel()

    cancelled = isolated.run(invocation("review"), root, (), token)

    assert cancelled.status == "cancelled"
    assert cancelled.summary == "独立 Skill 已取消。"
    assert provider.calls == []


def test_isolated_can_temporarily_activate_shared_skill(tmp_path: Path) -> None:
    root = definition("review")
    shared = definition("helper", mode="shared", history=None, tools=("find_files",))
    provider = ScriptedProvider([
        tool_call("1", "load_skill", '{"name":"helper"}'),
        [StreamEvent(type="text_delta", text="used helper"), StreamEvent(type="message_done")],
    ])
    isolated, _ = runner(tmp_path, root, provider, shared)

    result = isolated.run(invocation("review"), root, (), CancellationToken())

    assert result.status == "completed"
    assert result.summary == "used helper"
    assert {tool.name for tool in provider.calls[1].tools} == {"read_file", "find_files", "load_skill"}
    assert "SOP FOR helper" in provider.calls[1].optional_system_prompt


def test_isolated_rejects_nested_isolated_skill(tmp_path: Path) -> None:
    root = definition("review")
    nested = definition("other")
    provider = ScriptedProvider([
        tool_call("1", "load_skill", '{"name":"other"}'),
        [StreamEvent(type="text_delta", text="handled"), StreamEvent(type="message_done")],
    ])
    isolated, _ = runner(tmp_path, root, provider, nested)

    result = isolated.run(invocation("review"), root, (), CancellationToken())

    assert result.status == "completed"
    tool_message = next(message for message in provider.calls[1].messages if message.role == "tool")
    assert "nested_isolated_skill" in tool_message.content


def test_isolated_does_not_reuse_temporary_activation_across_calls(tmp_path: Path) -> None:
    root = definition("review")
    shared = definition("helper", mode="shared", history=None, tools=("find_files",))
    provider = ScriptedProvider([
        [StreamEvent(type="text_delta", text="first"), StreamEvent(type="message_done")],
        [StreamEvent(type="text_delta", text="second"), StreamEvent(type="message_done")],
    ])
    isolated, _ = runner(tmp_path, root, provider, shared)

    first = isolated.run(invocation("review"), root, (), CancellationToken())
    second = isolated.run(invocation("review"), root, (), CancellationToken())

    assert (first.summary, second.summary) == ("first", "second")
    assert all({tool.name for tool in call.tools} == {"read_file", "load_skill"} for call in provider.calls)
