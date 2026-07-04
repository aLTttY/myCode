# myCode 工具系统 Plan

## 架构概览

本阶段在现有 myCode MVP 上增加工具系统，保持现有分层不被打散。核心调用链调整为：

```text
CLI 读取用户输入
  → ChatSession 发起第一轮 Provider 流式请求
  → Provider 输出文本增量或工具调用事件
  → ChatSession 收集至多一组工具调用
  → ToolExecutor 执行工具并生成结构化结果
  → ChatSession 把 assistant 工具调用消息和 tool 结果消息追加到历史
  → ChatSession 发起第二轮 Provider 流式请求
  → Provider 输出最终文本
  → 本轮停止，不继续自动执行后续工具调用
```

### 工具层

工具层提供统一 `Tool` 接口、工具元信息、参数 Schema、执行上下文和结构化执行结果。六个核心工具都放在该层：

- `read_file`
- `write_file`
- `edit_file`
- `run_command`
- `find_files`
- `search_code`

工具只负责“执行本地动作并返回结果”，不依赖具体 Provider，也不直接操作会话历史。

### 注册中心层

注册中心集中登记工具，提供按名称查找和导出工具声明列表的能力。Provider 不直接依赖具体工具类，只接收注册中心导出的工具声明。

本阶段优先生成 OpenAI-compatible tools 格式。Anthropic 需要的工具声明格式由 Anthropic Provider 在发送请求前做适配，避免工具层绑定单一供应商协议。

### Provider 层

Provider 层从“只输出文本事件”扩展为“输出统一流式事件”，包括：

- 文本增量
- assistant 消息结束
- 工具调用参数增量
- 工具调用结束

OpenAI-compatible Provider 解析 `tool_calls` 流式 delta。Anthropic Provider 解析 `tool_use` 相关流式事件。Provider 只负责把供应商事件转换成统一事件，不负责执行工具。

### 会话编排层

`ChatSession` 成为单轮工具闭环的编排者：

1. 追加用户消息。
2. 调用 Provider，传入消息历史和工具声明。
3. 流式输出普通文本事件给 CLI。
4. 若出现工具调用，拼接参数碎片并执行工具。
5. 把工具调用和工具结果追加到历史。
6. 发起一次后续 Provider 请求。
7. 后续请求只输出文本；即使模型再次请求工具，也返回错误提示或停止，不进入第二轮工具执行。

该设计覆盖 spec 的单轮停止要求，避免提前实现 Agent Loop。

### CLI 层

CLI 仍只负责终端交互、打印流式文本和展示工具执行状态。CLI 不解析工具参数、不查找工具、不执行工具。

当收到工具状态事件时，CLI 打印可观察提示，例如：

```text
[tool] run_command 开始
[tool] run_command 成功
[tool] edit_file 失败：old_text matched 0 times
```

### 安全边界

工具执行统一通过 `ToolContext` 获取工作区根目录、超时时间和输出大小限制。路径类工具必须先解析并确认目标路径仍在工作区根目录内。命令执行默认在工作区根目录运行。

## 核心数据结构

### ToolSpec

描述一个工具暴露给模型的元信息。

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, object]
```

字段说明：

- `name`: 工具唯一名称。
- `description`: 给模型看的用途说明。
- `parameters`: JSON Schema 风格参数约束。

### ToolContext

工具执行上下文。

```python
@dataclass(frozen=True)
class ToolContext:
    workspace_root: Path
    timeout_seconds: float
    max_output_chars: int
```

字段说明：

- `workspace_root`: 允许读写和执行命令的根目录。
- `timeout_seconds`: 工具执行超时时间。
- `max_output_chars`: 命令输出和搜索结果的最大返回字符数。

### ToolResult

工具执行后的结构化结果。

```python
@dataclass(frozen=True)
class ToolResult:
    ok: bool
    message: str
    data: dict[str, object]
```

字段说明：

- `ok`: 成功或失败。
- `message`: 给模型和终端用户看的简短说明。
- `data`: 结构化数据，例如文件内容、退出码、匹配列表、stdout、stderr。

### ToolCall

表示模型请求的一次工具调用。

```python
@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, object]
```

字段说明：

- `id`: Provider 侧工具调用 ID，用于把工具结果关联回对话历史。
- `name`: 工具名称。
- `arguments`: 已解析完成的 JSON 参数。

### PendingToolCall

用于流式拼接中的临时工具调用。

```python
@dataclass
class PendingToolCall:
    id: str
    name: str
    arguments_json_parts: list[str]
```

字段说明：

- `arguments_json_parts`: 保存模型流式返回的 JSON 参数碎片。

### StreamEvent

扩展现有 `StreamEvent`，支持工具相关事件。

```python
@dataclass(frozen=True)
class StreamEvent:
    type: Literal[
        "text_delta",
        "message_done",
        "tool_call_delta",
        "tool_call_done",
        "tool_started",
        "tool_finished",
    ]
    text: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    arguments_delta: str = ""
    tool_result: ToolResult | None = None
```

约定：

- Provider 只产生 `text_delta`、`message_done`、`tool_call_delta`、`tool_call_done`。
- `ChatSession` 或 `ToolExecutor` 产生 `tool_started`、`tool_finished`。
- CLI 只根据事件打印，不执行业务逻辑。

### Message

扩展现有会话消息以表达工具调用和工具结果。

```python
@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str = ""
```

约定：

- 普通 user/assistant 消息继续使用 `content`。
- assistant 请求工具时，`tool_calls` 保存模型请求。
- tool 消息使用 `tool_call_id` 关联对应工具调用，`content` 保存 `ToolResult` JSON。

### Tool 接口

```python
class Tool(Protocol):
    @property
    def spec(self) -> ToolSpec:
        ...

    def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult:
        ...
```

约定：

- 每个工具自行校验参数类型和必填字段。
- 工具内部异常必须被包装为 `ToolResult(ok=False, ...)`。
- 不把异常透出到 CLI 或 Provider。

### ToolRegistry

```python
class ToolRegistry:
    def register(self, tool: Tool) -> None:
        ...

    def get(self, name: str) -> Tool:
        ...

    def tool_specs(self) -> list[ToolSpec]:
        ...

    def as_openai_tools(self) -> list[dict[str, object]]:
        ...
```

用途：

- 集中登记六个核心工具。
- 按名称查找工具。
- 向 Provider 提供工具声明。

### ToolExecutor

```python
class ToolExecutor:
    def execute(self, call: ToolCall) -> ToolResult:
        ...
```

职责：

- 查找工具。
- 处理未知工具。
- 捕获参数和执行错误。
- 应用超时策略。
- 返回结构化结果。

## 模块设计

### `mycode.types`

**职责：**

- 扩展共享数据结构：`Message`、`StreamEvent`。
- 新增工具相关类型：`ToolSpec`、`ToolContext`、`ToolResult`、`ToolCall`、`PendingToolCall`。
- 保留现有 `ConfigError`、`ProviderError`。
- 新增 `ToolError`，用于内部包装工具系统错误；对模型返回时转换为 `ToolResult`。

**对外接口：**

- dataclass 类型和用户可读异常。

**依赖：**

- 标准库。

### `mycode.tools.base`

**职责：**

- 定义 `Tool` Protocol。
- 定义工具参数读取辅助函数，例如必填字符串、布尔值、整数值校验。
- 定义路径安全辅助函数，确保目标路径在 `workspace_root` 内。

**对外接口：**

- `Tool`
- `require_str(arguments, key)`
- `resolve_workspace_path(root, path)`

**依赖：**

- `mycode.types`

### `mycode.tools.registry`

**职责：**

- 实现 `ToolRegistry`。
- 提供 `create_default_registry()`，登记六个核心工具。
- 提供 OpenAI-compatible 工具声明转换。

**对外接口：**

- `ToolRegistry`
- `create_default_registry()`

**依赖：**

- `mycode.tools.files`
- `mycode.tools.command`
- `mycode.tools.search`

### `mycode.tools.executor`

**职责：**

- 实现 `ToolExecutor`。
- 执行 `ToolCall`。
- 对未知工具、参数错误、执行异常和超时返回 `ToolResult(ok=False, ...)`。
- 对所有工具应用统一 `ToolContext`。

**对外接口：**

- `ToolExecutor.execute(call)`

**依赖：**

- `mycode.types`
- `mycode.tools.registry`

### `mycode.tools.files`

**职责：**

- 实现 `ReadFileTool`。
- 实现 `WriteFileTool`。
- 实现 `EditFileTool`。
- 所有路径必须限制在 `workspace_root` 内。
- `EditFileTool` 使用 `old_text` 唯一匹配替换为 `new_text`。

**对外接口：**

- 三个工具类。

**参数设计：**

- `read_file`: `path`
- `write_file`: `path`, `content`
- `edit_file`: `path`, `old_text`, `new_text`

**依赖：**

- `mycode.tools.base`
- 标准库 `pathlib`

### `mycode.tools.command`

**职责：**

- 实现 `RunCommandTool`。
- 在 `workspace_root` 内执行命令。
- 返回 `exit_code`、`stdout`、`stderr`。
- 超时返回结构化失败。
- 非零退出码不抛异常，作为 `ok=False` 工具结果返回。

**参数设计：**

- `command`: 命令字符串。
- `timeout_seconds`: 可选，不能超过 `ToolContext.timeout_seconds`。

**依赖：**

- 标准库 `subprocess`
- `mycode.tools.base`

### `mycode.tools.search`

**职责：**

- 实现 `FindFilesTool`。
- 实现 `SearchCodeTool`。
- 搜索范围限制在 `workspace_root` 内。
- 默认跳过 `.git`、`.venv`、`__pycache__`、二进制文件和常见缓存目录。
- 对结果数量和输出字符数做限制。

**参数设计：**

- `find_files`: `pattern`
- `search_code`: `query`, `regex`

**依赖：**

- 标准库 `pathlib`、`fnmatch`、`re`

### `mycode.providers.base`

**职责：**

- 扩展 `LLMProvider.stream_chat()`，允许传入工具声明。

**对外接口：**

```python
class LLMProvider(Protocol):
    def stream_chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
    ) -> Iterator[StreamEvent]:
        ...
```

**依赖：**

- `mycode.types`

### `mycode.providers.openai`

**职责：**

- 继续处理 OpenAI-compatible 文本流。
- 当存在工具声明时，在请求体加入 `tools`。
- 把通用 `Message` 转换为 OpenAI Chat Completions 消息格式。
- 解析 `choices[0].delta.tool_calls`，输出统一工具调用增量事件。
- 在 `[DONE]` 时输出 `message_done`。

**依赖：**

- `mycode.providers.sse`
- `mycode.types`

### `mycode.providers.deepseek`

**职责：**

- 继续复用 OpenAI-compatible 工具声明和流式解析逻辑。
- 保持独立类，便于后续扩展 DeepSeek 专用行为。

**依赖：**

- `mycode.providers.openai`

### `mycode.providers.anthropic`

**职责：**

- 把通用 `ToolSpec` 转换为 Anthropic tools 格式。
- 把通用 `Message` 转换为 Anthropic Messages 格式，包括 tool result。
- 解析 Anthropic `content_block_start`、`input_json_delta`、`content_block_stop`、`message_stop` 等事件，输出统一工具调用事件。
- 保持 Claude extended thinking 行为。

**依赖：**

- `mycode.providers.sse`
- `mycode.types`

### `mycode.session`

**职责：**

- 编排用户输入、Provider 流式响应、工具调用收集、工具执行和一次结果回灌。
- 普通文本请求保持现有行为。
- 工具请求后最多执行一轮工具并发起一次后续模型请求。
- 后续模型请求如果再次请求工具，本阶段不继续执行，返回可读错误事件或停止。

**对外接口：**

```python
class ChatSession:
    def __init__(
        self,
        provider: LLMProvider,
        tool_registry: ToolRegistry | None = None,
        tool_context: ToolContext | None = None,
    ) -> None:
        ...

    def send(self, user_text: str) -> Iterator[StreamEvent]:
        ...
```

**依赖：**

- `mycode.providers.base`
- `mycode.tools.executor`
- `mycode.tools.registry`
- `mycode.types`

### `mycode.cli`

**职责：**

- 创建默认工具注册中心和工具上下文。
- 把工作区根目录设置为当前进程启动目录。
- 打印文本增量。
- 打印工具开始和结束状态。
- 保持退出命令和错误处理行为。

**依赖：**

- `mycode.session`
- `mycode.tools.registry`
- `mycode.types`

## 模块交互

### 普通聊天路径

```text
CLI
  → ChatSession.send(user_text)
  → Provider.stream_chat(messages, tools)
  → text_delta/message_done
  → CLI 打印文本
  → ChatSession 追加 assistant 文本历史
```

### 工具调用路径

```text
CLI
  → ChatSession.send(user_text)
  → Provider.stream_chat(messages, tools)
  → tool_call_delta/tool_call_done
  → ChatSession 拼接并解析工具参数
  → ToolExecutor.execute(ToolCall)
  → ToolResult
  → ChatSession 追加 assistant tool_calls 和 tool result 消息
  → Provider.stream_chat(updated_messages, tools=())
  → text_delta/message_done
  → CLI 打印最终回复
```

### 错误路径

```text
工具错误 / 未知工具 / JSON 解析失败 / 超时
  → ToolResult(ok=False, message=...)
  → 作为 tool 消息写入历史
  → Provider 基于错误结果生成回复
```

Provider 网络错误仍按现有 `ProviderError` 处理，由 CLI 展示并继续会话。

## 文件组织

```text
src/mycode/
  types.py                       # 扩展共享类型
  session.py                     # 单轮工具闭环编排
  cli.py                         # 创建工具系统并展示状态
  providers/
    base.py                      # Provider 接口扩展
    openai.py                    # OpenAI-compatible 工具调用解析
    deepseek.py                  # DeepSeek 复用 OpenAI-compatible
    anthropic.py                 # Anthropic 工具调用解析
  tools/
    __init__.py                  # 工具包导出
    base.py                      # Tool 接口、参数校验、路径安全
    registry.py                  # 注册中心和默认工具集合
    executor.py                  # 工具执行、超时、错误包装
    files.py                     # read/write/edit 文件工具
    command.py                   # run_command 工具
    search.py                    # find_files/search_code 工具
tests/
  test_tools_files.py            # 文件工具测试
  test_tools_command.py          # 命令工具测试
  test_tools_search.py           # 搜索工具测试
  test_tools_registry.py         # 注册中心测试
  test_tool_executor.py          # 执行器错误和超时测试
  test_tool_streaming.py         # 流式工具调用参数拼接测试
  test_session_tools.py          # 工具结果回灌和单轮停止测试
  test_providers.py              # Provider 工具声明和事件解析扩展测试
  test_cli.py                    # 工具状态展示测试
```

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 工具声明格式 | 工具层使用通用 `ToolSpec`，Provider 负责转换 | 避免工具系统绑定 OpenAI 或 Anthropic |
| 工具执行位置 | `ChatSession` 编排，`ToolExecutor` 执行 | 保持 CLI 轻量，避免 Provider 知道本地工具 |
| 工具调用轮数 | 一次用户输入最多一轮工具执行和一次结果回灌 | 严格满足 spec，避免提前实现 Agent Loop |
| 改文件方式 | `old_text` 唯一匹配替换 | 简单、可测试、失败边界清晰 |
| 路径安全 | 所有路径解析后必须位于 `workspace_root` 内 | 降低本地工具越权风险 |
| 命令执行 | `subprocess.run(..., cwd=workspace_root, timeout=...)` | 标准库即可满足本阶段需求 |
| 命令失败处理 | 非零退出码返回 `ToolResult(ok=False)` | 让模型看到失败并调整，而不是让程序崩溃 |
| 搜索实现 | 标准库遍历、`fnmatch`、`re` | 避免新增外部依赖；后续可替换为 ripgrep |
| 输出限制 | 工具结果统一按 `max_output_chars` 截断 | 防止大文件、大命令输出污染上下文 |
| 后续工具请求 | 工具结果回灌后的第二轮不执行新工具 | 保证本阶段没有隐式循环 |

## Spec 覆盖关系

- F1、AC1：由 `Tool`、`ToolSpec` 覆盖。
- F2-F5、AC2-AC5：由 `mycode.tools.files` 覆盖。
- F6、F14、F20、AC6-AC7：由 `RunCommandTool`、`ToolExecutor`、`ToolContext` 覆盖。
- F7-F8、AC8-AC9：由 `mycode.tools.search` 覆盖。
- F9-F10、AC10-AC11：由 `ToolRegistry` 覆盖。
- F11-F12、AC12：由 Provider 工具事件和 `PendingToolCall` 拼接覆盖。
- F13、F15、AC13：由 `ToolExecutor` 和 `ToolResult` 覆盖。
- F16-F17、AC14-AC15：由 `ChatSession` 单轮编排覆盖。
- F18、AC17：由 CLI 工具状态事件展示覆盖。
- F19、N4：由 `resolve_workspace_path()` 和 `ToolContext.workspace_root` 覆盖。
- N5、AC16：普通文本事件路径保持兼容。
- N6、AC18：由新增测试文件覆盖。
- N7：README 和验收文档将明确本阶段不是完整 Agent Loop。
