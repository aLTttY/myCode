# myCode 工具系统 Checklist

> 每一项通过运行代码或观察行为来验证，聚焦系统行为。

## 实现完整性

- [ ] 工具系统中每个工具都暴露名称、描述、参数 Schema 和执行行为。（验证：运行 `pytest tests/test_tools_registry.py`，检查默认工具声明）
- [ ] `read_file` 能读取工作区内文件内容，并返回路径、大小和内容。（验证：运行 `pytest tests/test_tools_files.py -k read`）
- [ ] `read_file` 对越界路径返回结构化失败，不读取工作区外文件。（验证：运行 `pytest tests/test_tools_files.py -k outside`）
- [ ] `write_file` 能向工作区内目标文件写入完整内容。（验证：运行 `pytest tests/test_tools_files.py -k write`）
- [ ] `write_file` 对越界路径返回结构化失败，不写入工作区外文件。（验证：运行 `pytest tests/test_tools_files.py -k outside`）
- [ ] `edit_file` 在 `old_text` 唯一匹配时完成替换并返回成功结果。（验证：运行 `pytest tests/test_tools_files.py -k edit`）
- [ ] `edit_file` 在 `old_text` 匹配 0 次或多次时不修改文件，并返回明确失败原因。（验证：运行 `pytest tests/test_tools_files.py -k match`）
- [ ] `run_command` 能在工作区内执行命令并返回退出码、stdout、stderr。（验证：运行 `pytest tests/test_tools_command.py -k success`）
- [ ] `run_command` 对非零退出码返回结构化失败，不导致 myCode 崩溃。（验证：运行 `pytest tests/test_tools_command.py -k failure`）
- [ ] `run_command` 超时时返回结构化超时失败结果。（验证：运行 `pytest tests/test_tools_command.py -k timeout`）
- [ ] `find_files` 能按模式返回匹配文件列表，并跳过排除目录。（验证：运行 `pytest tests/test_tools_search.py -k find`）
- [ ] `search_code` 能返回匹配文件、行号和内容摘要。（验证：运行 `pytest tests/test_tools_search.py -k search`）
- [ ] `search_code` 对非法正则返回结构化失败。（验证：运行 `pytest tests/test_tools_search.py -k regex`）
- [ ] 工具结果按最大输出长度截断，避免大输出污染上下文。（验证：运行 `pytest tests/test_tools_command.py tests/test_tools_search.py -k truncate`）

## 注册与执行

- [ ] 默认注册中心登记六个核心工具。（验证：运行 `pytest tests/test_tools_registry.py -k default`）
- [ ] 注册中心能按名称查找工具，未知工具返回清晰错误。（验证：运行 `pytest tests/test_tools_registry.py -k lookup`）
- [ ] 注册中心能生成 OpenAI-compatible 工具声明列表。（验证：运行 `pytest tests/test_tools_registry.py -k openai`）
- [ ] 工具执行器能执行已注册工具并返回 `ToolResult`。（验证：运行 `pytest tests/test_tool_executor.py -k success`）
- [ ] 工具执行器能把未知工具、参数错误、工具异常包装成结构化失败。（验证：运行 `pytest tests/test_tool_executor.py -k "unknown or argument or exception"`）
- [ ] 工具执行器超时时返回结构化失败，不让会话永久阻塞。（验证：运行 `pytest tests/test_tool_executor.py -k timeout`）

## Provider 集成

- [ ] Provider 接口支持传入工具声明，普通文本路径保持兼容。（验证：运行 `pytest tests/test_session.py tests/test_providers.py -k factory`）
- [ ] OpenAI Provider 请求体包含工具声明时格式正确。（验证：运行 `pytest tests/test_providers.py -k "openai and tools"`）
- [ ] OpenAI Provider 能转换 assistant tool_calls 和 tool result 消息。（验证：运行 `pytest tests/test_providers.py -k "openai and message"`）
- [ ] OpenAI Provider 能从流式响应中解析工具调用名称和 JSON 参数碎片。（验证：运行 `pytest tests/test_providers.py -k "openai and tool_call"`）
- [ ] DeepSeek Provider 复用 OpenAI-compatible 工具声明和流式解析行为。（验证：运行 `pytest tests/test_providers.py -k deepseek`）
- [ ] Anthropic Provider 能把通用工具声明转换为 Anthropic tools 格式。（验证：运行 `pytest tests/test_providers.py -k "anthropic and tools"`）
- [ ] Anthropic Provider 能转换 tool_use 和 tool_result 消息。（验证：运行 `pytest tests/test_providers.py -k "anthropic and message"`）
- [ ] Anthropic Provider 能从流式响应中解析工具调用参数碎片和结束事件。（验证：运行 `pytest tests/test_providers.py -k "anthropic and tool_call"`）
- [ ] Claude thinking 配置在工具系统加入后仍按原逻辑启用或省略。（验证：运行 `pytest tests/test_providers.py -k thinking`）

## 会话编排

- [ ] 会话层能拼接单个工具调用的 JSON 参数碎片并解析为完整参数。（验证：运行 `pytest tests/test_tool_streaming.py -k single`）
- [ ] 会话层能在同一轮中保留多个工具调用的拼接顺序。（验证：运行 `pytest tests/test_tool_streaming.py -k multiple`）
- [ ] 非法 JSON 参数会被包装成结构化工具失败结果。（验证：运行 `pytest tests/test_tool_streaming.py -k invalid`）
- [ ] 工具调用成功后，assistant tool_calls 和 tool result 会追加到对话历史。（验证：运行 `pytest tests/test_session_tools.py -k success`）
- [ ] 工具调用失败后，失败结果会作为 tool 消息回灌给模型。（验证：运行 `pytest tests/test_session_tools.py -k failure`）
- [ ] 工具结果回灌后会触发一次后续模型请求生成最终回复。（验证：运行 `pytest tests/test_session_tools.py -k followup`）
- [ ] 一次用户输入最多执行一轮工具调用；后续模型再次请求工具时不会继续执行。（验证：运行 `pytest tests/test_session_tools.py -k stop`）
- [ ] 无工具调用的普通聊天仍保持现有流式文本输出和多轮历史能力。（验证：运行 `pytest tests/test_session.py tests/test_session_tools.py -k plain`）

## CLI 行为

- [ ] CLI 启动时创建默认工具注册中心和工作区工具上下文。（验证：运行 `pytest tests/test_cli.py -k tool_context`）
- [ ] CLI 收到 `tool_started` 事件时显示工具开始提示。（验证：运行 `pytest tests/test_cli.py -k tool_started`）
- [ ] CLI 收到成功 `tool_finished` 事件时显示工具成功状态。（验证：运行 `pytest tests/test_cli.py -k tool_success`）
- [ ] CLI 收到失败 `tool_finished` 事件时显示工具失败原因。（验证：运行 `pytest tests/test_cli.py -k tool_failure`）
- [ ] CLI 普通聊天流式文本输出、配置错误、Provider 错误和退出命令保持可用。（验证：运行 `pytest tests/test_cli.py`）

## 安全与边界

- [ ] 文件类工具拒绝绝对路径和 `..` 越界路径。（验证：运行 `pytest tests/test_tools_files.py -k outside`）
- [ ] 文件类工具拒绝符号链接解析后的工作区外路径。（验证：运行 `pytest tests/test_tools_files.py -k symlink`）
- [ ] 命令工具始终以 `workspace_root` 为工作目录运行。（验证：运行 `pytest tests/test_tools_command.py -k cwd`）
- [ ] 搜索工具跳过 `.git`、`.venv`、`__pycache__` 和二进制文件。（验证：运行 `pytest tests/test_tools_search.py -k skip`）
- [ ] README 明确本阶段不是完整自动 Agent Loop。（验证：阅读 `README.md`，确认存在单轮边界说明）

## 编译与测试

- [ ] Python 源码语法检查通过。（验证：运行 `python -m compileall src`）
- [ ] 文件工具测试通过。（验证：运行 `pytest tests/test_tools_files.py`）
- [ ] 命令工具测试通过。（验证：运行 `pytest tests/test_tools_command.py`）
- [ ] 搜索工具测试通过。（验证：运行 `pytest tests/test_tools_search.py`）
- [ ] 注册中心测试通过。（验证：运行 `pytest tests/test_tools_registry.py`）
- [ ] 工具执行器测试通过。（验证：运行 `pytest tests/test_tool_executor.py`）
- [ ] 流式工具参数拼接测试通过。（验证：运行 `pytest tests/test_tool_streaming.py`）
- [ ] 会话工具闭环测试通过。（验证：运行 `pytest tests/test_session_tools.py`）
- [ ] Provider 测试通过。（验证：运行 `pytest tests/test_providers.py`）
- [ ] CLI 测试通过。（验证：运行 `pytest tests/test_cli.py`）
- [ ] 全量自动化测试通过。（验证：运行 `pytest`）
- [ ] 项目中没有新增错误项目名。（验证：运行 `rg -n "Mew[C]ode|mew[c]ode"`，人工确认只在历史说明或允许位置出现）
- [ ] 项目中没有提交真实 API Key。（验证：运行 `rg -n "sk-[A-Za-z0-9]"`，期望无匹配）

## 端到端场景

- [ ] 场景 1：模型请求读取文件，myCode 执行 `read_file` 后回灌结果并输出最终回复。（验证：用 fake Provider 或集成测试模拟工具调用，观察工具状态和最终文本）
- [ ] 场景 2：模型请求修改文件，`old_text` 唯一匹配时文件被替换，终端显示工具成功。（验证：用临时工作区运行会话集成测试，检查文件内容）
- [ ] 场景 3：模型请求修改文件但 `old_text` 不存在，文件不变，模型收到失败结果并生成解释。（验证：用临时工作区运行会话集成测试，检查文件内容和失败消息）
- [ ] 场景 4：模型请求执行失败命令，myCode 不崩溃，工具结果包含退出码和 stderr，最终回复能说明失败。（验证：用 fake Provider 或 CLI 测试模拟 `run_command` 失败）
- [ ] 场景 5：模型在工具结果回灌后再次请求工具，myCode 不执行第二轮工具调用。（验证：运行 `pytest tests/test_session_tools.py -k stop`，检查执行次数为 1）
- [ ] 场景 6：没有工具调用的普通多轮聊天仍可用。（验证：运行现有 session 和 CLI 普通聊天测试）

## 验收记录要求

- [ ] 每个 checklist 条目执行后记录实际结果，不用“应该可以”代替证据。
- [ ] 若任一测试失败，先定位是否属于本阶段变更，再修复并重跑相关验证。
- [ ] 最终验收报告需要列出通过项数量、失败项、修复动作和关键命令输出。
