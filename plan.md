# myCode Agent Loop Plan

## 架构概览

本阶段在已有工具系统上新增独立 Agent 层，把“多轮循环、停止条件、事件流、工具分批执行、Plan Mode”从 `ChatSession` 和 CLI 中分离出来。

核心调用链调整为：

```text
CLI 读取用户输入
  → 识别普通输入、/plan、/do、取消信号
  → AgentRunner.run(request)
  → 输出 AgentEvent 异步事件流
  → CLI 只消费事件并展示

AgentRunner 每轮：
  → 发出 iteration_started 进度事件
  → 调用 Provider.stream_chat(messages, tools)
  → StreamCollector 双路收集：实时转发 text_delta，同时累计完整响应和 tool calls
  → 若无工具调用：追加 assistant 回复，发出 done，停止
  → 若有工具调用：ToolBatcher 按安全性分批
  → ToolBatchExecutor 并发执行读类批次、串行执行有副作用批次
  → 工具结果按 tool_call_id 回写历史
  → 进入下一轮
```

### 分层职责

- **Provider 层**：继续只负责把供应商流式响应转换为统一 `StreamEvent`，不执行工具、不控制循环。
- **工具层**：继续提供工具声明、执行和结果结构；新增工具安全分类能力。
- **Agent 层**：负责 ReAct 循环、停止条件、事件流、工具批处理和 Plan Mode。
- **CLI 层**：只负责输入命令解析和消费 Agent 事件，不直接操作工具调用细节。

### 为什么新增 Agent 层

当前 `ChatSession` 已经承担了一轮工具回灌编排。继续在 `ChatSession` 里堆 Agent Loop 会把会话历史、Provider 流解析、工具执行策略、停止条件和终端展示耦合在一起。新增 Agent 层后：

- `ChatSession` 可以保留或退化为轻量历史容器。
- `AgentRunner` 成为可测试的核心执行器。
- CLI、未来 TUI、测试 fake consumer 都可以只消费事件流。

## 核心数据结构

### AgentMode

表示 Agent 运行模式。

```python
AgentMode = Literal["default", "plan", "do"]
```

规则：

- `default`: 普通用户输入，使用完整工具集合和 Agent Loop。
- `plan`: `/plan` 输入，只开放读类工具，输出计划，不允许副作用工具。
- `do`: `/do` 输入，使用完整工具集合执行任务或已有计划。

### AgentConfig

Agent Loop 运行配置。

```python
@dataclass(frozen=True)
class AgentConfig:
    max_iterations: int = 8
    max_unknown_tool_calls: int = 2
```

字段说明：

- `max_iterations`: 最大循环轮数，达到后停止。
- `max_unknown_tool_calls`: 连续未知工具调用上限。

### AgentRequest

一次 Agent 运行请求。

```python
@dataclass(frozen=True)
class AgentRequest:
    text: str
    mode: AgentMode = "default"
```

字段说明：

- `text`: 用户输入正文。
- `mode`: 普通、计划或执行模式。

### AgentStopReason

结构化停止原因。

```python
AgentStopReason = Literal[
    "completed",
    "max_iterations",
    "cancelled",
    "unknown_tools",
    "stream_error",
    "tool_parse_error",
]
```

### AgentEvent

Agent 对外输出的统一事件。

```python
@dataclass(frozen=True)
class AgentEvent:
    type: Literal[
        "text_delta",
        "tool_call_started",
        "tool_result",
        "token_usage",
        "progress",
        "done",
        "error",
    ]
    text: str = ""
    iteration: int = 0
    max_iterations: int = 0
    tool_call_id: str = ""
    tool_name: str = ""
    tool_result: ToolResult | None = None
    stop_reason: AgentStopReason | None = None
    message: str = ""
    token_usage: TokenUsage | None = None
```

约定：

- CLI 只消费 `AgentEvent`。
- Provider 原始 `StreamEvent` 不直接暴露给 CLI。
- `progress` 表示轮次、批次、停止原因等过程状态。
- `done` 表示 Agent 本次请求已停止。

### TokenUsage

Token 用量事件载体。

```python
@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
```

规则：

- Provider 能解析到用量时填充字段。
- Provider 不支持或未返回时允许字段为空。

### CollectedResponse

流式双路收集后的完整模型响应。

```python
@dataclass(frozen=True)
class CollectedResponse:
    assistant_text: str
    tool_calls: tuple[ToolCall, ...]
    parse_errors: tuple[ToolResult, ...]
    token_usage: TokenUsage | None = None
```

字段说明：

- `assistant_text`: 本轮模型输出的完整文本。
- `tool_calls`: 本轮模型请求的全部工具调用。
- `parse_errors`: 工具调用参数 JSON 解析失败等结构化错误。
- `token_usage`: 本轮模型用量。

### ToolSafety

工具安全分类。

```python
ToolSafety = Literal["read", "side_effect"]
```

分类规则：

- `read`: 无副作用工具，可并发执行。包括 `read_file`、`find_files`、`search_code`。
- `side_effect`: 有副作用工具，必须串行执行。包括 `write_file`、`edit_file`、`run_command`。

### ToolBatch

一次模型响应中的工具调用批次。

```python
@dataclass(frozen=True)
class ToolBatch:
    safety: ToolSafety
    calls: tuple[ToolCall, ...]
```

规则：

- 相邻同类安全等级的工具调用归入同一批次。
- `read` 批次可并发。
- `side_effect` 批次串行。
- 批次执行结果仍按原 `tool_call_id` 回写历史。

### CancellationToken

用户取消信号。

```python
class CancellationToken:
    def cancel(self) -> None: ...
    def is_cancelled(self) -> bool: ...
```

用途：

- CLI 捕获 Ctrl+C 或后续取消命令时设置取消状态。
- Agent 每轮模型调用前、工具批次前和工具执行后检查取消。

## 模块设计

### `mycode.types`

**职责：**

- 扩展 Provider `StreamEvent`，允许 Provider 发出可选 `token_usage` 事件。
- 新增或复用 `TokenUsage`，作为 Provider 和 Agent 之间的用量载体。
- 保持 Provider `StreamEvent` 与 Agent `AgentEvent` 分离。

**对外接口：**

- 继续提供 `Message`、`ToolCall`、`ToolResult`、`StreamEvent`。
- 新增 `TokenUsage`。

**依赖：**

- 标准库。

### `mycode.providers.*`

**职责：**

- 保持现有文本和工具调用流式事件转换。
- 在供应商流式响应包含 token usage 时，转换为 `StreamEvent(type="token_usage")`。
- 不保证所有供应商都有 token usage；无用量字段时不产生该事件。

**对外接口：**

- `LLMProvider.stream_chat(...) -> Iterator[StreamEvent]`

**依赖：**

- `mycode.types`

### `mycode.agent.events`

**职责：**

- 定义 `AgentEvent`、`AgentStopReason`、`TokenUsage`。
- 提供事件构造辅助函数，减少 AgentRunner 中硬编码事件字段。

**对外接口：**

- `AgentEvent`
- `TokenUsage`
- `progress_event(...)`
- `done_event(...)`

**依赖：**

- `mycode.types`

### `mycode.agent.config`

**职责：**

- 定义 `AgentConfig`、`AgentRequest`、`AgentMode`。
- 维护默认最大迭代次数和未知工具阈值。

**对外接口：**

- `AgentConfig`
- `AgentRequest`

**依赖：**

- 标准库。

### `mycode.agent.collector`

**职责：**

- 消费 Provider 的 `StreamEvent`。
- 一边把文本增量转换成 `AgentEvent(type="text_delta")` 实时发给界面。
- 一边累计完整 `assistant_text`。
- 拼接工具调用 JSON 参数碎片。
- 生成 `CollectedResponse`。
- 捕获 JSON 解析错误并转换为 `parse_errors`。
- 转发 token usage 事件。

**对外接口：**

```python
class StreamCollector:
    def collect(
        self,
        events: Iterable[StreamEvent],
    ) -> Iterator[AgentEvent | CollectedResponse]:
        ...
```

**依赖：**

- `mycode.types`
- `mycode.agent.events`

### `mycode.agent.tools`

**职责：**

- 定义工具安全分类。
- 根据工具名判断 `read` 或 `side_effect`。
- 创建 Plan Mode 只读工具注册中心。
- 把工具调用按安全性切分成批次。

**对外接口：**

- `classify_tool(name)`
- `create_readonly_registry(full_registry)`
- `ToolBatcher.batch(calls)`

**依赖：**

- `mycode.tools.registry`
- `mycode.types`

### `mycode.agent.executor`

**职责：**

- 执行 `ToolBatch`。
- `read` 批次使用线程池并发执行。
- `side_effect` 批次按原顺序串行执行。
- 每个工具调用发出 `tool_call_started` 和 `tool_result` 事件。
- 保证结果按 `tool_call_id` 与历史回写关联。
- 检查取消信号。

**对外接口：**

```python
class BatchToolExecutor:
    def execute_batches(
        self,
        batches: Sequence[ToolBatch],
        cancellation: CancellationToken,
    ) -> Iterator[AgentEvent | tuple[str, ToolResult]]:
        ...
```

**依赖：**

- `mycode.tools.executor`
- `mycode.agent.events`
- `mycode.agent.tools`

### `mycode.agent.runner`

**职责：**

- 实现 ReAct Agent Loop。
- 维护会话历史。
- 选择当前模式下可用工具集合。
- 每轮调用 Provider、StreamCollector、ToolBatcher、BatchToolExecutor。
- 处理停止条件。
- 产出统一 `AgentEvent`。

**对外接口：**

```python
class AgentRunner:
    def __init__(
        self,
        provider: LLMProvider,
        full_registry: ToolRegistry,
        tool_context: ToolContext,
        config: AgentConfig = AgentConfig(),
    ) -> None:
        ...

    def run(
        self,
        request: AgentRequest,
        cancellation: CancellationToken | None = None,
    ) -> Iterator[AgentEvent]:
        ...
```

**停止条件处理：**

- `completed`: 收集响应后没有工具调用。
- `max_iterations`: 当前迭代达到 `max_iterations`。
- `cancelled`: cancellation token 已取消。
- `unknown_tools`: 连续未知工具调用达到阈值。
- `stream_error`: Provider 抛出 `ProviderError` 或流式响应中断。
- `tool_parse_error`: 工具参数解析错误达到无法继续执行的程度。

**依赖：**

- `mycode.providers.base`
- `mycode.tools.registry`
- `mycode.types`
- `mycode.agent.collector`
- `mycode.agent.executor`
- `mycode.agent.tools`

### `mycode.session`

**职责：**

- 从本阶段开始不再承载 Agent Loop 主逻辑。
- 可保留现有 `ChatSession` 作为兼容层，内部委托 `AgentRunner` 或继续供旧测试使用。
- 避免新增复杂逻辑到 `ChatSession`。

**依赖：**

- `mycode.agent.runner`

### `mycode.cli`

**职责：**

- 解析 `/plan`、`/do` 和普通输入。
- 创建 `AgentRunner`。
- 捕获 Ctrl+C 并触发取消。
- 消费 `AgentEvent` 并展示文本、进度、工具状态和停止原因。
- 不直接拼接工具参数，不执行工具，不判断循环。

**展示策略：**

- 文本增量继续实时输出。
- 进度事件简短显示，例如 `iteration 2/8`。
- 工具事件沿用当前 `[tool]` 风格，本阶段不做折叠 UI。
- done/error 事件显示停止原因。

**依赖：**

- `mycode.agent.runner`
- `mycode.agent.config`
- `mycode.tools.registry`

## 模块交互

### 普通 Agent Loop

```text
CLI
  → AgentRunner.run(AgentRequest(mode="default"))
  → AgentEvent(progress iteration=1)
  → Provider.stream_chat(messages, full_tools)
  → StreamCollector 转发 text_delta 并收集 tool_calls
  → ToolBatcher.batch(tool_calls)
  → BatchToolExecutor.execute_batches(...)
  → tool results append to history
  → 下一轮 Provider.stream_chat(...)
  → 无 tool_calls
  → AgentEvent(done stop_reason="completed")
```

### Plan Mode

```text
用户输入 /plan <task>
  → AgentRequest(mode="plan")
  → AgentRunner 使用 read-only registry
  → 模型只能调用 read_file/find_files/search_code
  → 输出计划文本
  → done completed
```

### Do Mode

```text
用户输入 /do <task>
  → AgentRequest(mode="do")
  → AgentRunner 使用 full registry
  → 可执行读写改命令搜索
  → 多轮循环直到完成或停止条件触发
```

### 取消路径

```text
CLI 捕获 Ctrl+C
  → cancellation.cancel()
  → AgentRunner 在下一检查点停止
  → AgentEvent(done stop_reason="cancelled")
```

## 文件组织

```text
src/mycode/
  types.py                         # 补充 TokenUsage 或基础事件字段
  cli.py                           # 切换到 AgentRunner 事件消费
  session.py                       # 保留兼容层，避免继续承载循环复杂度
  agent/
    __init__.py                    # Agent 包导出
    config.py                      # AgentConfig、AgentRequest、AgentMode
    events.py                      # AgentEvent、TokenUsage、停止原因
    cancellation.py                # CancellationToken
    collector.py                   # StreamCollector 双路收集
    tools.py                       # 工具安全分类、只读 registry、批处理
    executor.py                    # BatchToolExecutor
    runner.py                      # AgentRunner ReAct 循环
tests/
  test_agent_collector.py          # 流式双路收集和解析错误测试
  test_agent_tools.py              # 工具安全分类、Plan Mode 工具限制、批处理测试
  test_agent_executor.py           # 并发读批次、串行副作用批次、取消测试
  test_agent_runner.py             # 正常完成、迭代上限、未知工具、流错误测试
  test_cli.py                      # /plan、/do、事件展示、取消回归测试
  test_session.py                  # 兼容层回归测试
```

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| Agent 主体位置 | 新增 `mycode.agent` 包 | 避免继续膨胀 `ChatSession` 和 CLI |
| 事件模型 | 新增 `AgentEvent`，不直接暴露 Provider `StreamEvent` | 保持 Agent 与界面解耦，后续 UI 可替换 |
| 流式收集 | `StreamCollector` 既转发文本又返回完整响应 | 满足实时展示和循环判断双需求 |
| 停止条件 | 用结构化 `AgentStopReason` | 便于测试和 CLI 展示 |
| 迭代上限默认值 | `max_iterations=8` | 足够完成小任务，同时避免失控循环 |
| 未知工具阈值 | 连续 2 次未知工具后停止 | 给模型一次纠正机会，但避免空转 |
| 多工具执行 | 读类并发，副作用串行 | 平衡效率和安全 |
| Plan Mode 工具集合 | 只开放 `read_file`、`find_files`、`search_code` | 满足计划阶段观察项目且无副作用 |
| `/do` 语义 | 使用完整工具集合执行输入任务或已有计划上下文 | 符合两段式，但不实现人工审批恢复流 |
| Token 用量 | 事件字段可为空 | 兼容不同供应商能力差异 |
| 权限确认 | 本阶段不做 | 遵守 spec，留给后续权限系统 |

## Spec 覆盖关系

- F1-F2、AC1-AC2：由 `AgentRunner` 多轮 ReAct 循环覆盖。
- F3-F6、AC3-AC6：由 `AgentStopReason` 和 `AgentRunner` 停止条件覆盖。
- F7-F8、AC7：由 `StreamCollector` 双路收集覆盖。
- F9-F10、AC8-AC9：由 `AgentEvent` 事件流和 CLI 事件消费覆盖。
- F11-F13、AC10-AC13：由 `ToolBatcher`、`BatchToolExecutor` 和历史回写覆盖。
- F14、AC14：由 `progress` 事件覆盖。
- F15：通过复用 `ToolRegistry`、`ToolExecutor`、`ToolResult` 覆盖。
- F16-F18、AC15-AC17：由 `AgentMode`、只读 registry、`/plan` 和 `/do` 解析覆盖。
- F19-F20、AC18-AC19：由 CLI 默认进入 `AgentRunner` 和无工具普通聊天路径覆盖。
- AC20：由新增 Agent 测试和现有回归测试覆盖。
