# Structured System Prompt Checklist

> 每一项通过运行代码或观察行为来验证，聚焦系统行为。

## 实现完整性

- [ ] 结构化全局指令包含七个固定模块，顺序为身份、系统约束、任务模式、动作执行、工具使用、语气风格、文本输出。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_prompts.py -k modules`）
- [ ] 环境信息作为动态系统内容注入，改变 cwd、日期或运行模式不会改变稳定提示文本。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_prompts.py -k environment`）
- [ ] 自定义指令、已激活 Skill、长期记忆有明确可选模块位置，且不影响七个固定模块顺序。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_prompts.py -k optional`）
- [ ] 生成的提示文本有稳定分隔，快照或顺序测试能检测模块顺序和内容变化。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_prompts.py -k render`）
- [ ] 稳定系统提示不包含 cwd、日期、用户输入、对话历史或当前迭代次数。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_prompts.py -k stable`）

## 动态注入

- [ ] 运行时动态补充指令带 `<mewcode_runtime_instruction>` 或等价特殊标签，并以系统级内容发送。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_prompts.py tests/test_agent_runner.py -k runtime_instruction`）
- [ ] 环境信息带 `<mewcode_environment>` 或等价特殊标签，并以系统级内容发送。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_prompts.py tests/test_agent_runner.py -k environment`）
- [ ] Plan Mode 请求不再把模式说明拼接进用户文本，用户消息只包含原始任务正文。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py -k plan`）
- [ ] Plan Mode 首轮注入完整规则，间隔轮次重复完整规则，其余轮次注入精简提醒。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_prompts.py tests/test_agent_runner.py -k "plan and instruction"`）
- [ ] Plan Mode 动态指令明确只允许观察、分析和产出计划，不允许写文件、改文件或执行命令。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_prompts.py -k plan`）
- [ ] Do Mode 和默认模式动态指令明确允许在全局规则、安全边界和工具约定下使用完整工具集。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_prompts.py tests/test_agent_runner.py -k "do or default"`）

## 工具规则

- [ ] 工具描述中能观察到专用工具优先规则，例如读文件、找文件、搜索代码和编辑文件分别使用对应工具。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tool_descriptions.py -k dedicated`）
- [ ] 全局指令中能观察到专用工具优先规则。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_prompts.py -k tool`）
- [ ] 工具描述和全局指令中都能观察到编辑前必须读取或搜索确认当前内容的规则。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_prompts.py tests/test_tool_descriptions.py -k "edit or read"`）
- [ ] 工具描述和全局指令中都能观察到工作区边界和安全规则。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_prompts.py tests/test_tool_descriptions.py -k workspace`）
- [ ] 工具描述强化不改变工具 name 和参数 schema。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tool_descriptions.py -k schema`）

## Provider 集成

- [ ] Provider 请求中稳定全局指令、环境信息、可选模块、模式补充消息、对话历史和工具描述保持结构化分离。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_providers.py tests/test_agent_runner.py -k chat_request`）
- [ ] OpenAI-compatible payload 按顺序发送稳定 system 消息、环境 system 消息、可选 system 消息、模式 system 消息和普通历史。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_providers.py -k openai`）
- [ ] Anthropic payload 使用顶层 system content blocks 表达稳定提示、环境信息、可选模块和动态指令。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_providers.py -k anthropic`）
- [ ] 支持缓存控制的 Provider 请求包含稳定提示或工具描述的缓存标记或等价结构。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_providers.py -k cache_control`）
- [ ] 不支持缓存控制或未返回缓存字段的 Provider 能正常完成请求，并产生缓存不可验证的可观察信息。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_providers.py tests/test_cli.py -k "cache_unavailable or usage"`）
- [ ] API 返回缓存命中字段时，myCode 能解析缓存读取和缓存创建 token。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_providers.py -k cache`）
- [ ] 缓存读取、缓存创建或缓存不可验证信息能通过 token 用量事件或 CLI 输出观察到。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py -k usage`）

## Agent 与 CLI 回归

- [ ] AgentRunner 每轮调用 Provider 时传入 `ChatRequest`，并使用强化后的当前模式工具描述。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py -k chat_request`）
- [ ] Plan Mode 只开放 `read_file`、`find_files`、`search_code`，写文件、改文件和执行命令不会开放给模型。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py -k plan`）
- [ ] Do Mode 和默认模式仍开放完整工具集。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py -k "do or default"`）
- [ ] 普通无工具聊天仍保持流式输出。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py tests/test_cli.py -k "plain or text_delta"`）
- [ ] 现有 Agent Loop 工具调用和工具结果回写仍可正常运行。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py tests/test_tool_streaming.py tests/test_session_tools.py`）
- [ ] CLI 能展示 input、output、total 以及 cache usage 字段，旧格式仍兼容。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py -k usage`）

## 人工对比

- [ ] 人工对比文档覆盖“读取后编辑”场景，包含输入、观察点和通过标准。（验证：阅读 `docs/manual-eval-structured-prompts.md`）
- [ ] 人工对比文档覆盖“Plan Mode 只读”场景，包含输入、观察点和通过标准。（验证：阅读 `docs/manual-eval-structured-prompts.md`）
- [ ] 人工对比文档覆盖“专用工具优先”场景，包含输入、观察点和通过标准。（验证：阅读 `docs/manual-eval-structured-prompts.md`）
- [ ] 人工对比文档覆盖“环境变化缓存稳定”场景，包含输入、观察点和通过标准。（验证：阅读 `docs/manual-eval-structured-prompts.md`）
- [ ] 人工对比文档覆盖“多轮动态注入”场景，包含输入、观察点和通过标准。（验证：阅读 `docs/manual-eval-structured-prompts.md`）

## 编译与测试

- [ ] Python 源码语法检查通过。（验证：运行 `PYTHONPYCACHEPREFIX=.pycache .venv/bin/python -m compileall src tests`）
- [ ] 提示构建测试通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_prompts.py`）
- [ ] 工具描述强化测试通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tool_descriptions.py`）
- [ ] Provider 测试通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_providers.py`）
- [ ] AgentRunner 测试通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py`）
- [ ] CLI 测试通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py`）
- [ ] 工具流和会话工具回归测试通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tool_streaming.py tests/test_session_tools.py`）
- [ ] 全量自动化测试通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest`）
- [ ] 项目中没有提交真实 API Key。（验证：运行 `rg -n "sk-[A-Za-z0-9]"`，期望无匹配）

## 端到端场景

- [ ] 场景 1：普通输入无工具调用时直接流式输出最终回复。（验证：运行 plain chat 相关测试，观察 `text_delta` 和 `completed`）
- [ ] 场景 2：Plan Mode 查看项目并输出计划，不产生文件修改或命令执行能力暴露。（验证：运行 Plan Mode 工具集合测试，观察只读工具列表）
- [ ] 场景 3：Do Mode 或默认模式请求可使用完整工具集合执行实际任务。（验证：运行 Do/default 工具集合测试，观察副作用工具可用）
- [ ] 场景 4：多轮工具循环中首轮完整注入，下一轮精简提醒，间隔轮再次完整注入。（验证：用 fake Provider 运行 AgentRunner，观察每轮 `ChatRequest.dynamic_system_messages`）
- [ ] 场景 5：环境信息变化时稳定系统提示不变，动态环境消息变化。（验证：用不同 `EnvironmentInfo` 调用 `PromptBuilder`，比较 `stable_system_prompt` 和 `environment_message`）
- [ ] 场景 6：Provider 返回缓存命中字段时，CLI 可观察到缓存读取或创建 token。（验证：用 fake usage 事件运行 Provider/CLI usage 测试）

## 验收记录要求

- [ ] 每个 checklist 条目执行后记录实际结果，所有结论都基于命令输出或可观察行为。
- [ ] 若任一测试失败，先判断是否属于本阶段变更，再修复并重跑相关验证。
- [ ] 最终验收报告需要列出通过项数量、失败项、修复动作和关键命令输出。
