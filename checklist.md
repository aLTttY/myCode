# myCode Agent Loop Checklist

> 每一项通过运行代码或观察行为来验证，聚焦系统行为。

## 实现完整性

- [ ] Agent 能在一次用户请求中执行多轮“模型响应 → 工具执行 → 结果回写 → 再次模型响应”。（验证：运行 `pytest tests/test_agent_runner.py -k completed`）
- [ ] 模型不再请求工具时，Agent 正常停止并输出最终文本。（验证：运行 `pytest tests/test_agent_runner.py -k completed`）
- [ ] 达到最大迭代次数时，Agent 停止并产生 `max_iterations` 停止原因。（验证：运行 `pytest tests/test_agent_runner.py -k max_iterations`）
- [ ] 用户取消时，Agent 停止后不再继续调用模型或工具，并产生 `cancelled` 事件。（验证：运行 `pytest tests/test_agent_runner.py tests/test_agent_executor.py -k cancelled`）
- [ ] 连续未知工具调用达到阈值时，Agent 停止并说明未知工具。（验证：运行 `pytest tests/test_agent_runner.py -k unknown_tools`）
- [ ] Provider 流式错误会停止 Agent 并产生 `stream_error`。（验证：运行 `pytest tests/test_agent_runner.py -k stream_error`）
- [ ] 工具调用参数解析错误会停止 Agent 或回写结构化错误，并产生 `tool_parse_error`。（验证：运行 `pytest tests/test_agent_runner.py tests/test_agent_collector.py -k "tool_parse_error or invalid"`）

## 事件流

- [ ] Agent 对外输出统一 `AgentEvent`，CLI 不直接消费 Provider `StreamEvent`。（验证：运行 `pytest tests/test_cli.py tests/test_agent_runner.py`，并 review CLI 只处理 `AgentEvent`）
- [ ] 文本增量能实时作为 `text_delta` 事件发出。（验证：运行 `pytest tests/test_agent_collector.py -k text`）
- [ ] StreamCollector 同时累计完整 assistant 文本用于循环判断。（验证：运行 `pytest tests/test_agent_collector.py -k collected`）
- [ ] 工具调用开始事件包含工具名和 tool call id。（验证：运行 `pytest tests/test_agent_executor.py -k started`）
- [ ] 工具结果事件包含工具结果和 tool call id。（验证：运行 `pytest tests/test_agent_executor.py -k result`）
- [ ] Token 用量事件可从 Provider 事件转发到 Agent 事件；无用量时允许缺省。（验证：运行 `pytest tests/test_providers.py tests/test_agent_collector.py -k usage`）
- [ ] 每轮循环都会产生进度事件，包含当前迭代和最大迭代。（验证：运行 `pytest tests/test_agent_runner.py -k progress`）
- [ ] done/error 事件包含结构化停止原因。（验证：运行 `pytest tests/test_agent_runner.py -k stop_reason`）

## 多工具执行

- [ ] Agent 能识别一次模型响应中的多个工具调用。（验证：运行 `pytest tests/test_agent_collector.py -k multiple`）
- [ ] `read_file`、`find_files`、`search_code` 被分类为读类工具。（验证：运行 `pytest tests/test_agent_tools.py -k classify`）
- [ ] `write_file`、`edit_file`、`run_command` 被分类为有副作用工具。（验证：运行 `pytest tests/test_agent_tools.py -k classify`）
- [ ] 多个读类工具调用可以并发执行，并正确回写每个结果。（验证：运行 `pytest tests/test_agent_executor.py -k concurrent`）
- [ ] 多个有副作用工具调用按原顺序串行执行。（验证：运行 `pytest tests/test_agent_executor.py -k serial`）
- [ ] 混合工具调用会按安全性分批，读类和副作用批次不会无序交叉。（验证：运行 `pytest tests/test_agent_tools.py tests/test_agent_executor.py -k batch`）
- [ ] 工具结果按对应 tool call id 写入历史，下一轮模型能看到全部结果。（验证：运行 `pytest tests/test_agent_runner.py -k history`）

## Plan 与 Do Mode

- [ ] `/plan` 被解析为 `AgentRequest(mode="plan")`。（验证：运行 `pytest tests/test_cli.py -k plan`）
- [ ] `/plan` 模式只开放 `read_file`、`find_files`、`search_code`。（验证：运行 `pytest tests/test_agent_tools.py tests/test_agent_runner.py -k plan`）
- [ ] `/plan` 模式下写文件、改文件、执行命令不会被开放给模型。（验证：运行 `pytest tests/test_agent_runner.py -k plan`）
- [ ] `/plan` 模式能基于读类工具结果输出计划文本。（验证：运行 `pytest tests/test_agent_runner.py -k plan`）
- [ ] `/do` 被解析为 `AgentRequest(mode="do")`。（验证：运行 `pytest tests/test_cli.py -k do`）
- [ ] `/do` 模式使用完整工具集合，可执行副作用工具。（验证：运行 `pytest tests/test_agent_runner.py -k do`）
- [ ] 普通输入默认进入完整 Agent Loop。（验证：运行 `pytest tests/test_cli.py tests/test_agent_runner.py -k default`）

## CLI 行为

- [ ] CLI 创建 `AgentRunner` 而不是直接驱动 `ChatSession` 工具闭环。（验证：运行 `pytest tests/test_cli.py`，并 review CLI 构造路径）
- [ ] CLI 能展示文本增量事件。（验证：运行 `pytest tests/test_cli.py -k streaming`）
- [ ] CLI 能展示迭代进度事件。（验证：运行 `pytest tests/test_cli.py -k progress`）
- [ ] CLI 能展示工具开始和工具结果事件。（验证：运行 `pytest tests/test_cli.py -k tool`）
- [ ] CLI 能展示完成、迭代上限、取消、未知工具和流错误等停止原因。（验证：运行 `pytest tests/test_cli.py -k stop`）
- [ ] CLI 退出命令、配置错误和 Provider 错误展示保持可用。（验证：运行 `pytest tests/test_cli.py`）

## 回归与边界

- [ ] 现有 Provider 文本流和工具调用解析保持可用。（验证：运行 `pytest tests/test_providers.py`）
- [ ] 现有工具系统测试保持通过。（验证：运行 `pytest tests/test_tools_files.py tests/test_tools_command.py tests/test_tools_search.py tests/test_tools_registry.py tests/test_tool_executor.py`）
- [ ] 旧 Session 测试保持通过，兼容层语义明确。（验证：运行 `pytest tests/test_session.py tests/test_session_tools.py`）
- [ ] 没有工具调用的普通聊天仍保持流式输出。（验证：运行 `pytest tests/test_agent_runner.py tests/test_cli.py -k plain`）
- [ ] README 明确本阶段仍不做权限系统、上下文压缩、交互式确认和复杂 TUI。（验证：阅读 `README.md`）

## 编译与测试

- [ ] Python 源码语法检查通过。（验证：运行 `PYTHONPYCACHEPREFIX=.pycache .venv/bin/python -m compileall src tests`）
- [ ] Agent collector 测试通过。（验证：运行 `pytest tests/test_agent_collector.py`）
- [ ] Agent tools 测试通过。（验证：运行 `pytest tests/test_agent_tools.py`）
- [ ] Agent executor 测试通过。（验证：运行 `pytest tests/test_agent_executor.py`）
- [ ] Agent runner 测试通过。（验证：运行 `pytest tests/test_agent_runner.py`）
- [ ] CLI 测试通过。（验证：运行 `pytest tests/test_cli.py`）
- [ ] Provider 测试通过。（验证：运行 `pytest tests/test_providers.py`）
- [ ] 全量自动化测试通过。（验证：运行 `PYTHONPYCACHEPREFIX=.pycache .venv/bin/python -m pytest`）
- [ ] 项目中没有新增错误项目名。（验证：运行 `rg -n "Mew[C]ode|mew[c]ode"`，人工确认只在历史说明或允许位置出现）
- [ ] 项目中没有提交真实 API Key。（验证：运行 `rg -n "sk-[A-Za-z0-9]"`，期望无匹配）

## 端到端场景

- [ ] 场景 1：普通输入触发两轮工具调用后完成。（验证：用 fake Provider 运行 AgentRunner，观察两轮 progress、工具结果、最终 done）
- [ ] 场景 2：模型持续请求工具直到达到迭代上限。（验证：用 fake Provider 运行 AgentRunner，观察 `max_iterations` 停止原因）
- [ ] 场景 3：用户取消正在运行的 Agent。（验证：触发 CancellationToken，观察 `cancelled` 停止原因且后续工具不再执行）
- [ ] 场景 4：一次模型响应返回多个读类工具调用。（验证：运行并发批次测试，观察每个结果按 tool call id 回写）
- [ ] 场景 5：一次模型响应返回多个副作用工具调用。（验证：运行串行批次测试，观察执行顺序与模型请求顺序一致）
- [ ] 场景 6：`/plan` 查看项目并输出计划，不产生文件修改或命令执行。（验证：用 fake Provider 检查可用工具集合只有读类工具）
- [ ] 场景 7：`/do` 使用完整工具集合执行实际修改或命令。（验证：用 fake Provider 检查副作用工具可用并能执行）
- [ ] 场景 8：没有工具调用的普通聊天直接流式输出最终回复。（验证：运行 plain chat 测试）

## 验收记录要求

- [ ] 每个 checklist 条目执行后记录实际结果，不用“应该可以”代替证据。
- [ ] 若任一测试失败，先判断是否属于本阶段变更，再修复并重跑相关验证。
- [ ] 最终验收报告需要列出通过项数量、失败项、修复动作和关键命令输出。
