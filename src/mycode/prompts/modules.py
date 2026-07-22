from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptModule:
    key: str
    title: str
    content: str
    stable: bool = True


@dataclass(frozen=True)
class PromptOptions:
    custom_instructions: str = ""
    active_skills: tuple[str, ...] = ()
    long_term_memory: str = ""


def fixed_prompt_modules() -> tuple[PromptModule, ...]:
    return (
        PromptModule(
            key="identity",
            title="身份",
            content=(
                "你是 Mycode，一个命令行 AI 编程助手。你的职责是理解用户任务，"
                "在当前工作区内借助可用工具完成代码阅读、修改、验证和说明。"
            ),
        ),
        PromptModule(
            key="system_constraints",
            title="系统约束",
            content=(
                "遵守工作区边界，只读取、写入和执行与当前任务相关的内容。"
                "不要尝试访问工作区外路径，不要泄露密钥，不要执行与任务无关或高风险的命令。"
            ),
        ),
        PromptModule(
            key="task_modes",
            title="任务模式",
            content=(
                "根据运行时补充指令区分 default、plan 和 do 模式。"
                "当补充指令限制为计划或只读时，只观察、分析并输出计划；"
                "当补充指令允许执行时，在安全边界内推进实际改动和验证。"
            ),
        ),
        PromptModule(
            key="action_execution",
            title="动作执行",
            content=(
                "先理解现有状态，再行动。修改文件前必须先读取目标文件或搜索相关代码，"
                "确认当前内容和上下文后再编辑。每次改动后运行与风险匹配的验证。"
            ),
        ),
        PromptModule(
            key="tool_usage",
            title="工具使用",
            content=(
                "优先使用专用工具：读文件用 read_file，找文件用 find_files，"
                "搜索代码用 search_code，修改现有文件用 edit_file，写新文件用 write_file。"
                "只有在专用工具不能满足任务时才使用 run_command。"
            ),
        ),
        PromptModule(
            key="tone_style",
            title="语气风格",
            content=(
                "回应应直接、务实、清晰。说明你正在做什么和发现了什么，"
                "避免空泛承诺和无依据结论。"
            ),
        ),
        PromptModule(
            key="text_output",
            title="文本输出",
            content=(
                "最终回复聚焦结果、验证证据和必要后续事项。引用文件时使用清晰路径，"
                "命令输出只总结关键事实。"
            ),
        ),
    )


def optional_prompt_modules(options: PromptOptions) -> tuple[PromptModule, ...]:
    modules: list[PromptModule] = []
    if options.custom_instructions.strip():
        modules.append(
            PromptModule(
                key="custom_instructions",
                title="自定义指令（按来源标注的优先级执行）",
                content=options.custom_instructions.strip(),
                stable=False,
            )
        )
    if options.active_skills:
        modules.append(
            PromptModule(
                key="active_skills",
                title="已激活的 Skill",
                content="\n".join(f"- {skill}" for skill in options.active_skills),
                stable=False,
            )
        )
    if options.long_term_memory.strip():
        modules.append(
            PromptModule(
                key="long_term_memory",
                title="长期记忆索引（项目级优先于用户级）",
                content=options.long_term_memory.strip(),
                stable=False,
            )
        )
    return tuple(modules)


def render_modules(modules: tuple[PromptModule, ...]) -> str:
    return "\n\n".join(f"## {module.title}\n{module.content}" for module in modules)
