from __future__ import annotations

from dataclasses import dataclass, field

from mycode.commands import CommandDispatcher, InputRouter, create_default_command_registry
from mycode.skills.commands import commands_from_snapshot
from mycode.skills.models import SkillDefinition, SkillSnapshot, immutable_mapping


def definition(name: str, *, mode: str = "shared") -> SkillDefinition:
    return SkillDefinition(
        name=name,
        description=f"{name} description",
        allowed_tools=("read_file",),
        mode=mode,  # type: ignore[arg-type]
        history=2 if mode == "isolated" else None,
        model="special" if mode == "isolated" else None,
        sop="secret sop",
        compiled_sop="secret sop",
        source="project",
        source_id=f"test:{name}",
        package_root=None,
        dedicated_tools=(),
        fingerprint=f"fp:{name}",
    )


def snapshot(*items: SkillDefinition) -> SkillSnapshot:
    return SkillSnapshot(
        definitions=immutable_mapping({item.name: item for item in items}),
        dedicated_tools=immutable_mapping(),
    )


@dataclass
class FakeUI:
    calls: list[tuple[str, str]] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def invoke_skill(self, name: str, input_text: str) -> None:
        self.calls.append((name, input_text))

    def display_message(self, text: str, *, error: bool = False) -> None:
        self.messages.append(text)


def test_dynamic_skill_command_forwards_arguments_and_review_alias() -> None:
    registry = create_default_command_registry()
    registry.replace_dynamic(commands_from_snapshot(snapshot(definition("review", mode="isolated"))))
    route = InputRouter(registry).route("/rev inspect this")
    ui = FakeUI()

    assert route.invocation is not None
    CommandDispatcher(registry).dispatch(route.invocation, ui)  # type: ignore[arg-type]

    assert ui.calls == [("review", "inspect this")]
    command = registry.resolve("review")
    assert command is not None
    assert command.origin == "skill"
    assert command.skill_mode == "isolated"
    assert command.skill_history == 2
    assert command.skill_model == "special"


def test_help_shows_safe_skill_metadata_but_not_sop() -> None:
    registry = create_default_command_registry()
    registry.replace_dynamic(commands_from_snapshot(snapshot(definition("review", mode="isolated"))))
    route = InputRouter(registry).route("/help review")
    ui = FakeUI()

    assert route.invocation is not None
    CommandDispatcher(registry).dispatch(route.invocation, ui)  # type: ignore[arg-type]

    text = ui.messages[0]
    assert "Skill 来源：project" in text
    assert "Skill 模式：isolated" in text
    assert "历史轮数：2" in text
    assert "指定模型：special" in text
    assert "secret sop" not in text


def test_dynamic_replace_updates_completion_and_removes_deleted_skill() -> None:
    registry = create_default_command_registry()
    registry.replace_dynamic(commands_from_snapshot(snapshot(definition("commit"))))
    assert registry.resolve("commit") is not None

    registry.replace_dynamic(commands_from_snapshot(snapshot(definition("test"))))

    assert registry.resolve("commit") is None
    assert [item.name for item in registry.completion_candidates("t")] == ["test"]
