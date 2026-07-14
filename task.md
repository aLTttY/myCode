# Structured System Prompt Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 已有 | `spec.md` | 已批准结构化系统提示需求文档 |
| 已有 | `plan.md` | 已批准结构化系统提示技术设计文档 |
| 修改 | `src/mycode/types.py` | 扩展 `TokenUsage` 缓存指标 |
| 修改 | `src/mycode/agent/config.py` | 增加模式指令重复间隔配置 |
| 修改 | `src/mycode/agent/runner.py` | 构造 `ChatRequest`，移除模式说明拼接用户文本 |
| 修改 | `src/mycode/providers/base.py` | 定义 `ChatRequest`，升级 Provider 协议 |
| 修改 | `src/mycode/providers/openai.py` | 转换系统提示/动态消息/工具描述，解析缓存字段 |
| 修改 | `src/mycode/providers/deepseek.py` | 继续复用 OpenAI-compatible 请求与缓存解析 |
| 修改 | `src/mycode/providers/anthropic.py` | 转换 Anthropic system blocks，加入缓存控制和缓存解析 |
| 修改 | `src/mycode/cli.py` | 展示 cache usage 字段 |
| 修改 | `tests/test_agent_runner.py` | AgentRunner 请求构造、模式注入和回归测试 |
| 修改 | `tests/test_providers.py` | Provider payload 与缓存字段解析测试 |
| 修改 | `tests/test_cli.py` | cache usage 展示测试 |
| 修改 | `tests/test_tool_streaming.py` | Provider 协议升级后的工具流回归测试 |
| 修改 | `tests/test_session_tools.py` | Provider 协议升级后的会话工具回归测试 |
| 修改 | `README.md` | 如有必要，补充结构化提示和缓存观测说明 |
| 新建 | `src/mycode/prompts/__init__.py` | 提示构建包导出 |
| 新建 | `src/mycode/prompts/modules.py` | 固定模块、可选模块和提示数据结构 |
| 新建 | `src/mycode/prompts/modes.py` | 模式动态指令与注入频率 |
| 新建 | `src/mycode/prompts/builder.py` | `PromptBuilder`、`PromptBundle`、环境信息构建 |
| 新建 | `src/mycode/tools/descriptions.py` | 工具描述强化 |
| 新建 | `tests/test_prompts.py` | 模块顺序、稳定/动态分离、模式注入测试 |
| 新建 | `tests/test_tool_descriptions.py` | 工具描述强化测试 |
| 新建 | `docs/manual-eval-structured-prompts.md` | 人工对比场景和观察点 |

## T1: 扩展共享类型和 Provider 请求协议

**文件：** `src/mycode/types.py`, `src/mycode/providers/base.py`, `tests/test_providers.py`

**依赖：** 已批准 `spec.md`、`plan.md`

**步骤：**

1. 为 `TokenUsage` 增加 `cache_read_tokens`、`cache_creation_tokens`、`cache_unavailable` 字段。
2. 定义 `ChatRequest`，包含稳定系统提示、动态系统消息、普通消息、可选系统提示、工具列表和缓存开关。
3. 调整 `LLMProvider` 协议为 `stream_chat(request: ChatRequest)`。
4. 更新测试中的 fake Provider 或辅助构造，使测试能记录和断言 `ChatRequest`。
5. 保持未使用缓存字段时的现有 token usage 行为兼容。

**验证：** 运行 `PYTHONPATH=src .venv/bin/python -m compileall src/mycode/types.py src/mycode/providers/base.py`，期望无语法错误。

## T2: 实现固定提示模块

**文件：** `src/mycode/prompts/__init__.py`, `src/mycode/prompts/modules.py`, `tests/test_prompts.py`

**依赖：** T1

**步骤：**

1. 定义 `PromptModule` 和 `PromptOptions`。
2. 实现 `fixed_prompt_modules()`，按身份、系统约束、任务模式、动作执行、工具使用、语气风格、文本输出的顺序返回七个固定模块。
3. 在固定模块中写入关键规则：优先专用工具、编辑前读取或搜索、工作区边界、安全约束、输出风格。
4. 实现 `optional_prompt_modules(options)`，按自定义指令、已激活 Skill、长期记忆顺序返回非空模块。
5. 编写模块顺序、固定模块数量、可选模块追加顺序、关键规则存在性测试。

**验证：** 运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_prompts.py -k modules`，期望全部通过。

## T3: 实现模式动态指令

**文件：** `src/mycode/prompts/modes.py`, `src/mycode/agent/config.py`, `tests/test_prompts.py`

**依赖：** T2

**步骤：**

1. 定义 `DynamicInstruction`。
2. 实现 `mode_instruction(mode, iteration, repeat_interval)`。
3. 实现首轮完整、间隔轮完整、其他轮精简的注入策略。
4. 为 Plan Mode 完整指令写入只读、只计划、不写文件、不改文件、不执行命令规则。
5. 为 Do/default 完整指令写入完整工具集、编辑前观察、专用工具优先规则。
6. 在 `AgentConfig` 增加默认重复间隔，建议默认值为 `3`。
7. 编写 Plan/Do/default 的完整与精简指令测试。

**验证：** 运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_prompts.py -k modes`，期望全部通过。

## T4: 实现 PromptBuilder

**文件：** `src/mycode/prompts/builder.py`, `src/mycode/prompts/__init__.py`, `tests/test_prompts.py`

**依赖：** T2, T3

**步骤：**

1. 定义 `EnvironmentInfo` 和 `PromptBundle`。
2. 实现 `PromptBuilder.build(mode, iteration, environment, options)`。
3. 将七个固定模块渲染到 `stable_system_prompt`，模块之间用稳定分隔。
4. 将环境信息渲染为 `<mewcode_environment>...</mewcode_environment>`。
5. 将模式规则渲染为 `<mewcode_runtime_instruction>...</mewcode_runtime_instruction>`。
6. 将可选模块渲染到 `optional_system_prompt`，并保持默认空值。
7. 测试 `stable_system_prompt` 不包含 cwd、日期、用户输入、迭代次数等动态内容。
8. 测试环境变化不改变稳定提示文本。

**验证：** 运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_prompts.py`，期望全部通过。

## T5: 实现工具描述强化

**文件：** `src/mycode/tools/descriptions.py`, `tests/test_tool_descriptions.py`

**依赖：** T1

**步骤：**

1. 实现 `reinforce_tool_spec(spec)`，返回新的 `ToolSpec`，保留 name 和 parameters 不变。
2. 实现 `reinforce_tool_specs(specs)`。
3. 为 `read_file`、`find_files`、`search_code` 描述追加专用工具优先规则。
4. 为 `edit_file` 描述追加编辑前必须读取或搜索确认的规则。
5. 为文件和命令相关工具描述追加工作区边界规则。
6. 编写描述强化、schema 不变、关键规则存在性测试。

**验证：** 运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tool_descriptions.py`，期望全部通过。

## T6: 迁移 OpenAI-compatible Provider

**文件：** `src/mycode/providers/openai.py`, `src/mycode/providers/deepseek.py`, `tests/test_providers.py`

**依赖：** T1, T4, T5

**步骤：**

1. 将 `OpenAIProvider.stream_chat` 入参改为 `ChatRequest`。
2. 增加 payload 构建 helper，把稳定系统提示、环境动态消息、可选系统提示、模式动态消息、普通历史按顺序转为 `messages`。
3. 工具列表使用 `ChatRequest.tools` 转换为 OpenAI-compatible `tools`。
4. 对支持字段的情况预留稳定内容缓存标记，默认保持兼容不破坏普通 OpenAI-compatible 服务。
5. 从 `usage.prompt_tokens_details.cached_tokens` 解析 `cache_read_tokens`。
6. 兼容 `cache_creation_input_tokens`、`cache_read_input_tokens` 等等价字段。
7. 未返回缓存字段时设置 `cache_unavailable=True`。
8. 确认 `DeepSeekProvider` 继续继承或复用该行为。
9. 编写系统消息顺序、工具转换、缓存字段解析、无缓存字段降级测试。

**验证：** 运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_providers.py -k "openai or deepseek or usage or cache"`，期望全部通过。

## T7: 迁移 Anthropic Provider

**文件：** `src/mycode/providers/anthropic.py`, `tests/test_providers.py`

**依赖：** T1, T4, T5

**步骤：**

1. 将 `AnthropicProvider.stream_chat` 和 `_build_payload` 入参改为 `ChatRequest`。
2. 将稳定系统提示转为顶层 `system` content block，并添加 `cache_control: {"type": "ephemeral"}`。
3. 将环境动态消息、可选系统提示和模式动态消息按优先级追加为非缓存 system blocks。
4. 工具定义在支持时添加缓存控制，工具参数 schema 保持不变。
5. 保持现有 assistant tool use 和 tool result 转换逻辑。
6. 从 `usage.cache_read_input_tokens` 和 `usage.cache_creation_input_tokens` 解析统一缓存字段。
7. 未返回缓存字段时设置 `cache_unavailable=True`。
8. 编写 Anthropic system block 顺序、cache_control、工具定义、缓存字段解析测试。

**验证：** 运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_providers.py -k "anthropic or cache"`，期望全部通过。

## T8: AgentRunner 接入结构化提示

**文件：** `src/mycode/agent/runner.py`, `tests/test_agent_runner.py`

**依赖：** T4, T5, T6, T7

**步骤：**

1. 在每轮模型调用前构造 `EnvironmentInfo`。
2. 使用 `PromptBuilder` 生成 `PromptBundle`。
3. 根据当前模式选择只读或完整工具注册中心。
4. 对当前工具列表调用 `reinforce_tool_specs`。
5. 构造 `ChatRequest` 并调用 Provider。
6. 删除或停用把 Plan/Do 模式说明拼接到用户文本的逻辑。
7. 确保用户消息历史只保存原始用户输入。
8. 编写默认模式、Plan Mode、Do Mode 的 `ChatRequest` 断言测试。
9. 编写 Plan Mode 首轮完整、间隔轮完整、其他轮精简的注入测试。
10. 保持现有 Agent Loop 完成、工具回写、停止条件测试通过。

**验证：** 运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py`，期望全部通过。

## T9: CLI 展示缓存用量

**文件：** `src/mycode/cli.py`, `tests/test_cli.py`

**依赖：** T1, T8

**步骤：**

1. 扩展 `format_token_usage()`，展示 `cache_read` 和 `cache_create`。
2. 当 `cache_unavailable=True` 且没有缓存 token 字段时展示 `cache=unavailable` 或等价文本。
3. 保持 input、output、total 展示兼容。
4. 编写缓存读取、缓存创建、缓存不可验证、普通 token usage 展示测试。

**验证：** 运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py -k usage`，期望全部通过。

## T10: 编写人工对比场景文档

**文件：** `docs/manual-eval-structured-prompts.md`

**依赖：** T4, T5, T8

**步骤：**

1. 记录“读取后编辑”场景，观察是否先读或搜再编辑。
2. 记录 “Plan Mode 只读”场景，观察只读工具集合和动态指令。
3. 记录“专用工具优先”场景，观察找文件、读文件、搜代码是否使用对应工具。
4. 记录“环境变化缓存稳定”场景，观察稳定提示不随环境变化。
5. 记录“多轮动态注入”场景，观察完整/精简规则频率。
6. 为每个场景写明输入、预期观察点和通过标准。

**验证：** 人工阅读 `docs/manual-eval-structured-prompts.md`，确认五个场景均包含输入、观察点和通过标准。

## T11: Provider 和 Agent 回归收敛

**文件：** `tests/test_providers.py`, `tests/test_agent_runner.py`, `tests/test_tool_streaming.py`, `tests/test_session_tools.py`

**依赖：** T6, T7, T8

**步骤：**

1. 更新所有 fake Provider 到 `ChatRequest` 协议。
2. 更新断言，使用 `request.messages` 和 `request.tools` 检查历史与工具列表。
3. 确保旧的工具流解析、工具结果回写和会话工具测试仍覆盖原行为。
4. 对因接口升级失效的测试做最小必要调整，不改变被测行为。

**验证：** 运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_providers.py tests/test_agent_runner.py tests/test_tool_streaming.py tests/test_session_tools.py`，期望全部通过。

## T12: 全量测试和文档一致性检查

**文件：** `README.md`, `spec.md`, `plan.md`, `task.md`

**依赖：** T1-T11

**步骤：**

1. 检查 README 是否需要补充结构化系统提示、缓存观测或 Plan/Do 注入行为说明。
2. 如 README 已有行为描述仍准确，则不做无关改动。
3. 检查 `spec.md`、`plan.md`、`task.md` 与实际实现术语一致。
4. 运行全量测试。

**验证：** 运行 `PYTHONPATH=src .venv/bin/python -m pytest`，期望全部通过。

## 执行顺序

```text
T1 -> T2 -> T3 -> T4 -> T5 -> T6 -> T7 -> T8 -> T9 -> T10 -> T11 -> T12
```
