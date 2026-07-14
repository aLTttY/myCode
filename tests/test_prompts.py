from __future__ import annotations

from mycode.prompts.builder import EnvironmentInfo, PromptBuilder
from mycode.prompts.modes import mode_instruction
from mycode.prompts.modules import PromptOptions, fixed_prompt_modules, optional_prompt_modules, render_modules


def test_fixed_prompt_modules_order_and_rules() -> None:
    modules = fixed_prompt_modules()

    assert [module.key for module in modules] == [
        "identity",
        "system_constraints",
        "task_modes",
        "action_execution",
        "tool_usage",
        "tone_style",
        "text_output",
    ]
    rendered = render_modules(modules)
    assert "优先使用专用工具" in rendered
    assert "修改文件前必须先读取" in rendered
    assert "工作区边界" in rendered


def test_optional_prompt_modules_order() -> None:
    modules = optional_prompt_modules(
        PromptOptions(
            custom_instructions="custom",
            active_skills=("skill-a", "skill-b"),
            long_term_memory="memory",
        )
    )

    assert [module.key for module in modules] == ["custom_instructions", "active_skills", "long_term_memory"]


def test_mode_instruction_full_and_compact() -> None:
    first = mode_instruction("plan", iteration=1, repeat_interval=3)
    compact = mode_instruction("plan", iteration=2, repeat_interval=3)
    repeated = mode_instruction("plan", iteration=3, repeat_interval=3)

    assert first.full is True
    assert "不得写文件" in first.content
    assert compact.full is False
    assert "提醒" in compact.content
    assert repeated.full is True


def test_prompt_builder_separates_stable_and_dynamic_environment() -> None:
    builder = PromptBuilder(repeat_interval=3)
    first = builder.build(
        mode="default",
        iteration=1,
        environment=EnvironmentInfo(cwd="/tmp/a", date="2026-07-13", mode="default"),
    )
    second = builder.build(
        mode="default",
        iteration=2,
        environment=EnvironmentInfo(cwd="/tmp/b", date="2026-07-14", mode="default"),
    )

    assert first.stable_system_prompt == second.stable_system_prompt
    assert "/tmp/a" not in first.stable_system_prompt
    assert "2026-07-13" not in first.stable_system_prompt
    assert "<mewcode_environment>" in first.environment_message.render()
    assert "/tmp/a" in first.environment_message.render()
    assert first.dynamic_system_messages[0].full is True
    assert second.dynamic_system_messages[0].full is False


def test_prompt_builder_renders_optional_prompt_separately() -> None:
    bundle = PromptBuilder().build(
        mode="do",
        iteration=1,
        environment=EnvironmentInfo(cwd="/tmp/a", date="2026-07-13", mode="do"),
        options=PromptOptions(custom_instructions="custom"),
    )

    assert "custom" in bundle.optional_system_prompt
    assert "custom" not in bundle.stable_system_prompt
