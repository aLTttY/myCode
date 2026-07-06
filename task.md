# myCode Agent Loop Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 已有 | `spec.md` | 已批准 Agent Loop 需求文档 |
| 已有 | `plan.md` | 已批准 Agent Loop 技术设计文档 |
| 修改 | `src/mycode/types.py` | 扩展 Provider 事件以承载 Token 用量 |
| 修改 | `src/mycode/providers/openai.py` | 解析 OpenAI-compatible token usage 事件 |
| 修改 | `src/mycode/providers/deepseek.py` | 继续复用 OpenAI-compatible 行为 |
| 修改 | `src/mycode/providers/anthropic.py` | 解析 Anthropic token usage 事件 |
| 修改 | `src/mycode/cli.py` | 改为创建 AgentRunner、解析 `/plan` 和 `/do`、消费 AgentEvent |
| 修改 | `src/mycode/session.py` | 保留兼容层，避免继续承载 Agent Loop 主逻辑 |
| 修改 | `README.md` | 说明 Agent Loop、停止条件、Plan Mode 和范围边界 |
| 新建 | `src/mycode/agent/__init__.py` | Agent 包导出 |
| 新建 | `src/mycode/agent/config.py` | AgentConfig、AgentRequest、AgentMode |
| 新建 | `src/mycode/agent/events.py` | AgentEvent、TokenUsage、停止原因和事件构造 |
| 新建 | `src/mycode/agent/cancellation.py` | CancellationToken |
| 新建 | `src/mycode/agent/collector.py` | StreamCollector 双路流式收集 |
| 新建 | `src/mycode/agent/tools.py` | 工具安全分类、只读注册中心和批处理 |
| 新建 | `src/mycode/agent/executor.py` | BatchToolExecutor，并发读批次、串行副作用批次 |
| 新建 | `src/mycode/agent/runner.py` | AgentRunner ReAct 循环和停止条件 |
| 新建 | `tests/test_agent_collector.py` | 流式双路收集测试 |
| 新建 | `tests/test_agent_tools.py` | 工具分类、只读注册中心、批处理测试 |
| 新建 | `tests/test_agent_executor.py` | 批次执行、并发/串行、取消测试 |
| 新建 | `tests/test_agent_runner.py` | 正常完成、迭代上限、未知工具、流错误测试 |
| 修改 | `tests/test_cli.py` | `/plan`、`/do`、AgentEvent 展示和取消回归测试 |
| 修改 | `tests/test_providers.py` | Token 用量事件解析测试 |
| 修改 | `tests/test_session.py` | 兼容层回归测试 |

## T1: 扩展基础事件类型

**文件：** `src/mycode/types.py`, `tests/test_providers.py`

**依赖：** 已批准 `spec.md`、`plan.md`

**步骤：**

1. 新增 `TokenUsage` 数据结构，字段允许为空。
2. 扩展 `StreamEvent.type`，支持 `token_usage`。
3. 为 `StreamEvent` 增加 `token_usage` 字段。
4. 保持现有 `text_delta`、`tool_call_delta`、`tool_call_done`、`message_done` 行为兼容。
5. 更新测试中的 `StreamEvent` 构造断言。

**验证：** 运行 `pytest tests/test_providers.py tests/test_session.py`，期望已有测试通过。

## T2: 增加 Agent 配置和事件模型

**文件：** `src/mycode/agent/__init__.py`, `src/mycode/agent/config.py`, `src/mycode/agent/events.py`, `tests/test_agent_runner.py`

**依赖：** T1

**步骤：**

1. 定义 `AgentMode`，支持 `default`、`plan`、`do`。
2. 定义 `AgentConfig`，包含 `max_iterations` 和 `max_unknown_tool_calls`。
3. 定义 `AgentRequest`。
4. 定义 `AgentStopReason`。
5. 定义 `AgentEvent`，支持文本、工具开始、工具结果、token usage、进度、done、error。
6. 提供 `progress_event()` 和 `done_event()` 辅助构造函数。
7. 在 `__init__.py` 中导出核心 Agent 类型。

**验证：** 运行 `.venv/bin/python -m compileall src/mycode/agent`，期望无语法错误。

## T3: 实现取消信号

**文件：** `src/mycode/agent/cancellation.py`, `tests/test_agent_executor.py`, `tests/test_agent_runner.py`

**依赖：** T2

**步骤：**

1. 实现 `CancellationToken.cancel()`。
2. 实现 `CancellationToken.is_cancelled()`。
3. 保证重复取消是幂等操作。
4. 编写取消 token 基础行为测试。

**验证：** 运行 `pytest tests/test_agent_executor.py -k cancellation`，期望通过。

## T4: 实现流式双路收集器

**文件：** `src/mycode/agent/collector.py`, `tests/test_agent_collector.py`

**依赖：** T1, T2

**步骤：**

1. 实现 `CollectedResponse`。
2. 实现 `StreamCollector.collect()`。
3. 收到 `text_delta` 时立即产出 `AgentEvent(type="text_delta")`，同时累计完整文本。
4. 收到 `tool_call_delta` 时按 tool call id 拼接 JSON 参数碎片。
5. 收到 `tool_call_done` 时解析完整参数并生成 `ToolCall`。
6. 参数 JSON 非法时生成 `parse_errors`。
7. 收到 `token_usage` 时产出 `AgentEvent(type="token_usage")` 并记录用量。
8. 收到 `message_done` 时产出最终 `CollectedResponse`。
9. 编写实时文本转发、完整文本收集、单工具参数拼接、多工具拼接、非法 JSON、token usage 测试。

**验证：** 运行 `pytest tests/test_agent_collector.py`，期望全部通过。

## T5: 实现工具安全分类和 Plan Mode 工具集合

**文件：** `src/mycode/agent/tools.py`, `tests/test_agent_tools.py`

**依赖：** T2

**步骤：**

1. 定义 `ToolSafety`。
2. 定义 `ToolBatch`。
3. 实现 `classify_tool(name)`。
4. 将 `read_file`、`find_files`、`search_code` 分类为 `read`。
5. 将 `write_file`、`edit_file`、`run_command` 分类为 `side_effect`。
6. 实现 `create_readonly_registry(full_registry)`，只包含读类工具。
7. 实现 `ToolBatcher.batch(calls)`，按相邻安全等级分批。
8. 编写分类、只读工具集合、混合工具分批、未知工具分类测试。

**验证：** 运行 `pytest tests/test_agent_tools.py`，期望全部通过。

## T6: 实现批量工具执行器

**文件：** `src/mycode/agent/executor.py`, `tests/test_agent_executor.py`

**依赖：** T3, T5

**步骤：**

1. 实现 `BatchToolExecutor`。
2. 接收 `ToolRegistry`、`ToolContext` 和批次列表。
3. 对每个工具调用产出 `tool_call_started` 事件。
4. 对每个工具结果产出 `tool_result` 事件。
5. 对 `read` 批次使用线程池并发执行。
6. 对 `side_effect` 批次按原顺序串行执行。
7. 保留每个结果与原 `tool_call_id` 的映射。
8. 在每个批次前后检查取消信号。
9. 取消后停止后续批次执行并产出取消相关事件。
10. 编写读批次并发、写批次串行、混合批次顺序、未知工具结果、取消测试。

**验证：** 运行 `pytest tests/test_agent_executor.py`，期望全部通过。

## T7: 实现 AgentRunner 正常循环

**文件：** `src/mycode/agent/runner.py`, `tests/test_agent_runner.py`

**依赖：** T4, T5, T6

**步骤：**

1. 实现 `AgentRunner.__init__()`。
2. 保存 Provider、完整工具注册中心、工具上下文、AgentConfig 和消息历史。
3. 实现普通 `default` 模式工具集合选择。
4. 每轮循环发出 `progress` 事件，包含当前迭代和最大迭代。
5. 调用 Provider 并通过 `StreamCollector` 转换事件。
6. 无工具调用时追加 assistant 消息，发出 `done(completed)` 并停止。
7. 有工具调用时调用 `ToolBatcher` 和 `BatchToolExecutor`。
8. 将 assistant tool_calls 和 tool result 消息按 ID 追加到历史。
9. 下一轮继续调用 Provider。
10. 编写多轮工具调用后正常完成测试。

**验证：** 运行 `pytest tests/test_agent_runner.py -k completed`，期望通过。

## T8: 实现停止条件

**文件：** `src/mycode/agent/runner.py`, `tests/test_agent_runner.py`

**依赖：** T7

**步骤：**

1. 实现最大迭代次数停止。
2. 实现取消停止。
3. 实现连续未知工具停止。
4. 实现 Provider 流式错误停止。
5. 实现工具参数解析错误停止。
6. 每种停止都产出结构化 `done` 或 `error` 事件，带 `stop_reason`。
7. 编写 `max_iterations`、`cancelled`、`unknown_tools`、`stream_error`、`tool_parse_error` 测试。

**验证：** 运行 `pytest tests/test_agent_runner.py -k "max_iterations or cancelled or unknown_tools or stream_error or tool_parse_error"`，期望通过。

## T9: 实现 Plan Mode 和 Do Mode

**文件：** `src/mycode/agent/runner.py`, `src/mycode/agent/tools.py`, `tests/test_agent_runner.py`, `tests/test_agent_tools.py`

**依赖：** T7, T8

**步骤：**

1. `AgentRunner` 根据 `AgentRequest.mode` 选择工具集合。
2. `plan` 模式使用只读工具注册中心。
3. `do` 模式使用完整工具注册中心。
4. `default` 模式使用完整工具注册中心。
5. `/plan` 阶段如果模型请求副作用工具，应被视为未知或不可用工具结果。
6. 编写 `plan` 模式工具限制测试。
7. 编写 `plan` 模式能输出计划文本测试。
8. 编写 `do` 模式能使用副作用工具测试。
9. 编写普通输入默认完整工具集合测试。

**验证：** 运行 `pytest tests/test_agent_runner.py -k "plan or do or default"`，期望通过。

## T10: Provider Token 用量事件解析

**文件：** `src/mycode/providers/openai.py`, `src/mycode/providers/anthropic.py`, `tests/test_providers.py`

**依赖：** T1

**步骤：**

1. OpenAI-compatible 流中出现 usage 字段时产出 `StreamEvent(type="token_usage")`。
2. DeepSeek 继续复用 OpenAI-compatible 行为。
3. Anthropic 流中出现 usage 字段时产出 `StreamEvent(type="token_usage")`。
4. 未出现 usage 时不产出 token usage 事件。
5. 编写 OpenAI usage、DeepSeek usage、Anthropic usage 测试。

**验证：** 运行 `pytest tests/test_providers.py -k usage`，期望通过。

## T11: CLI 切换到 AgentRunner

**文件：** `src/mycode/cli.py`, `tests/test_cli.py`

**依赖：** T7, T8, T9

**步骤：**

1. CLI 启动时创建 `AgentRunner`。
2. 普通输入解析为 `AgentRequest(mode="default")`。
3. `/plan ...` 解析为 `AgentRequest(mode="plan")`。
4. `/do ...` 解析为 `AgentRequest(mode="do")`。
5. CLI 捕获 Ctrl+C 时触发 `CancellationToken.cancel()`。
6. CLI 消费 `AgentEvent(type="text_delta")` 并实时打印文本。
7. CLI 消费 `progress` 事件并简短展示迭代进度。
8. CLI 消费 `tool_call_started` 和 `tool_result` 事件并展示工具状态。
9. CLI 消费 `done` 和 `error` 事件并展示停止原因。
10. 保持退出命令、配置错误、Provider 错误展示行为。
11. 编写普通输入、`/plan`、`/do`、工具事件展示、停止原因展示、退出命令回归测试。

**验证：** 运行 `pytest tests/test_cli.py`，期望全部通过。

## T12: 兼容层和旧测试回归

**文件：** `src/mycode/session.py`, `tests/test_session.py`, `tests/test_session_tools.py`

**依赖：** T11

**步骤：**

1. 明确 `ChatSession` 是兼容层还是委托 `AgentRunner`。
2. 保持已有 `tests/test_session.py` 通过。
3. 根据新 AgentRunner 行为调整或保留 `tests/test_session_tools.py`。
4. 确保旧的一轮工具回灌测试不与新默认 Agent Loop 语义冲突。

**验证：** 运行 `pytest tests/test_session.py tests/test_session_tools.py`，期望全部通过。

## T13: 更新文档说明

**文件：** `README.md`

**依赖：** T11

**步骤：**

1. 增加 Agent Loop 能力说明。
2. 说明默认输入会进入多轮 Agent Loop。
3. 说明停止条件：完成、迭代上限、取消、未知工具、流错误。
4. 说明 `/plan` 只开放读类工具。
5. 说明 `/do` 使用完整工具集合。
6. 明确本阶段仍不做权限系统、上下文压缩、交互式确认和复杂 TUI。
7. 补充 Agent Loop 测试命令。

**验证：** 阅读 `README.md`，确认范围边界与 `spec.md` 一致。

## T14: 全量验证

**文件：** `src/mycode/**`, `tests/**`

**依赖：** T1-T13

**步骤：**

1. 运行 Python 语法检查。
2. 运行新增 Agent 测试。
3. 运行现有工具系统测试。
4. 运行 Provider、Session、CLI 回归测试。
5. 运行全量 `pytest`。
6. 搜索错误项目名。
7. 搜索明显真实 API Key 模式。
8. 修复本阶段引入的失败后重跑相关验证。

**验证：** 运行 `PYTHONPYCACHEPREFIX=.pycache .venv/bin/python -m compileall src tests` 和 `PYTHONPYCACHEPREFIX=.pycache .venv/bin/python -m pytest`，期望全部通过；项目名和 API Key 扫描无新增问题。

## 执行顺序

```text
T1
→ T2
→ T3
→ T4
→ T5
→ T6
→ T7
→ T8
→ T9
→ T10
→ T11
→ T12
→ T13
→ T14
```
