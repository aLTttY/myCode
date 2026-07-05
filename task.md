# myCode 工具系统 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 已有 | `spec.md` | 已批准工具系统需求文档 |
| 已有 | `plan.md` | 已批准工具系统技术设计文档 |
| 修改 | `src/mycode/types.py` | 扩展消息、流式事件、工具调用和工具结果类型 |
| 修改 | `src/mycode/providers/base.py` | 扩展 Provider 接口以接收工具声明 |
| 修改 | `src/mycode/providers/openai.py` | 支持 OpenAI-compatible 工具声明、工具调用流式解析和工具消息格式 |
| 修改 | `src/mycode/providers/deepseek.py` | 继续复用 OpenAI-compatible 工具能力 |
| 修改 | `src/mycode/providers/anthropic.py` | 支持 Anthropic 工具声明、工具调用流式解析和工具结果消息格式 |
| 修改 | `src/mycode/session.py` | 编排单轮工具调用、工具执行和一次结果回灌 |
| 修改 | `src/mycode/cli.py` | 初始化工具系统并展示工具执行状态 |
| 新建 | `src/mycode/tools/__init__.py` | 工具包导出 |
| 新建 | `src/mycode/tools/base.py` | Tool 接口、参数校验、路径安全工具 |
| 新建 | `src/mycode/tools/registry.py` | 工具注册中心和默认工具集合 |
| 新建 | `src/mycode/tools/executor.py` | 工具执行器、错误包装和超时处理 |
| 新建 | `src/mycode/tools/files.py` | 读文件、写文件、原文唯一替换工具 |
| 新建 | `src/mycode/tools/command.py` | 执行命令工具 |
| 新建 | `src/mycode/tools/search.py` | 按模式找文件和搜索代码内容工具 |
| 修改 | `README.md` | 说明工具系统能力和非 Agent Loop 边界 |
| 修改 | `tests/test_providers.py` | 扩展 Provider 工具声明、消息转换和工具事件解析测试 |
| 修改 | `tests/test_cli.py` | 扩展 CLI 工具状态展示测试 |
| 新建 | `tests/test_tools_files.py` | 文件工具测试 |
| 新建 | `tests/test_tools_command.py` | 命令工具测试 |
| 新建 | `tests/test_tools_search.py` | 搜索工具测试 |
| 新建 | `tests/test_tools_registry.py` | 注册中心测试 |
| 新建 | `tests/test_tool_executor.py` | 工具执行器错误和超时测试 |
| 新建 | `tests/test_tool_streaming.py` | JSON 参数碎片拼接测试 |
| 新建 | `tests/test_session_tools.py` | 工具结果回灌和单轮停止测试 |

## T1: 扩展共享类型

**文件：** `src/mycode/types.py`

**依赖：** 已批准 `spec.md`、`plan.md`

**步骤：**

1. 增加 `ToolSpec`、`ToolContext`、`ToolResult`、`ToolCall`、`PendingToolCall`。
2. 扩展 `Message.role`，支持 `tool` 消息。
3. 为 `Message` 增加 `tool_calls` 和 `tool_call_id` 字段。
4. 扩展 `StreamEvent.type`，支持 `tool_call_delta`、`tool_call_done`、`tool_started`、`tool_finished`。
5. 为 `StreamEvent` 增加工具调用 ID、工具名、参数增量和工具结果字段。
6. 增加 `ToolError`，用于工具系统内部错误表达。
7. 保持现有文本聊天字段向后兼容。

**验证：** 运行 `python -m compileall src/mycode/types.py`，期望无语法错误。

## T2: 实现工具基础设施

**文件：** `src/mycode/tools/__init__.py`, `src/mycode/tools/base.py`

**依赖：** T1

**步骤：**

1. 定义 `Tool` Protocol，包含 `spec` 和 `run()`。
2. 实现必填字符串参数读取辅助函数。
3. 实现可选布尔值、整数值、浮点数参数读取辅助函数。
4. 实现 `resolve_workspace_path()`，把相对路径解析到 `workspace_root` 下。
5. 对绝对路径、`..` 越界路径和符号链接解析后的越界路径返回 `ToolError`。
6. 实现工具结果输出截断辅助函数。
7. 在 `__init__.py` 中导出基础类型和工具类入口。

**验证：** 运行 `python -m compileall src/mycode/tools`，期望无语法错误。

## T3: 实现文件工具

**文件：** `src/mycode/tools/files.py`, `tests/test_tools_files.py`

**依赖：** T1, T2

**步骤：**

1. 实现 `ReadFileTool`，参数为 `path`。
2. 读取工作区内文件并返回 `content`、`path`、`size`。
3. 对不存在、目录路径、越界路径返回结构化失败。
4. 实现 `WriteFileTool`，参数为 `path`、`content`。
5. 写入工作区内文件，必要时创建父目录，并返回写入字节数或字符数。
6. 对越界路径和写入失败返回结构化失败。
7. 实现 `EditFileTool`，参数为 `path`、`old_text`、`new_text`。
8. 当 `old_text` 唯一出现时替换并返回成功。
9. 当匹配 0 次或多次时不修改文件，并返回明确失败原因。
10. 编写成功读取、越界读取、成功写入、越界写入、唯一替换、0 次匹配、多次匹配测试。

**验证：** 运行 `pytest tests/test_tools_files.py`，期望全部通过。

## T4: 实现命令工具

**文件：** `src/mycode/tools/command.py`, `tests/test_tools_command.py`

**依赖：** T1, T2

**步骤：**

1. 实现 `RunCommandTool`，参数为 `command` 和可选 `timeout_seconds`。
2. 使用 `workspace_root` 作为命令工作目录。
3. 返回 `exit_code`、`stdout`、`stderr`。
4. 成功退出码返回 `ok=True`。
5. 非零退出码返回 `ok=False`，但不抛异常。
6. 工具超时时返回 `ok=False` 和超时说明。
7. 限制单次命令超时不超过 `ToolContext.timeout_seconds`。
8. 对输出按 `max_output_chars` 截断并标记截断状态。
9. 编写成功命令、失败命令、超时、输出截断、工作目录验证测试。

**验证：** 运行 `pytest tests/test_tools_command.py`，期望全部通过。

## T5: 实现搜索工具

**文件：** `src/mycode/tools/search.py`, `tests/test_tools_search.py`

**依赖：** T1, T2

**步骤：**

1. 实现 `FindFilesTool`，参数为 `pattern`。
2. 在工作区内按路径或文件名模式匹配文件。
3. 跳过 `.git`、`.venv`、`__pycache__` 和常见缓存目录。
4. 对返回文件数量和输出字符数做限制。
5. 实现 `SearchCodeTool`，参数为 `query` 和可选 `regex`。
6. 支持普通文本搜索和正则搜索。
7. 返回匹配文件、行号和内容摘要。
8. 跳过二进制文件和被排除目录。
9. 对非法正则返回结构化失败。
10. 编写模式找文件、排除目录、文本搜索、正则搜索、非法正则、输出限制测试。

**验证：** 运行 `pytest tests/test_tools_search.py`，期望全部通过。

## T6: 实现工具注册中心

**文件：** `src/mycode/tools/registry.py`, `tests/test_tools_registry.py`

**依赖：** T3, T4, T5

**步骤：**

1. 实现 `ToolRegistry.register()`。
2. 实现 `ToolRegistry.get()`，未知工具返回清晰错误。
3. 实现 `ToolRegistry.tool_specs()`。
4. 实现 `ToolRegistry.as_openai_tools()`，输出 OpenAI-compatible tools 声明。
5. 实现 `create_default_registry()`，登记六个核心工具。
6. 防止重复工具名覆盖。
7. 编写默认六工具登记、按名查找、未知工具、重复注册、OpenAI 声明格式测试。

**验证：** 运行 `pytest tests/test_tools_registry.py`，期望全部通过。

## T7: 实现工具执行器

**文件：** `src/mycode/tools/executor.py`, `tests/test_tool_executor.py`

**依赖：** T6

**步骤：**

1. 实现 `ToolExecutor`，接收 `ToolRegistry` 和 `ToolContext`。
2. 根据 `ToolCall.name` 查找工具并执行。
3. 对未知工具返回 `ToolResult(ok=False)`。
4. 对参数类型错误返回 `ToolResult(ok=False)`。
5. 捕获工具运行中的未处理异常并包装为结构化失败。
6. 对工具执行应用超时策略。
7. 保证任何工具失败都不会抛到 CLI 或 Provider。
8. 编写成功执行、未知工具、参数错误、工具异常、超时测试。

**验证：** 运行 `pytest tests/test_tool_executor.py`，期望全部通过。

## T8: 扩展 Provider 接口

**文件：** `src/mycode/providers/base.py`, `src/mycode/types.py`, `tests/test_providers.py`

**依赖：** T1

**步骤：**

1. 修改 `LLMProvider.stream_chat()` 签名，增加 `tools` 参数。
2. 保持默认 `tools=()`，让无工具调用路径继续兼容。
3. 调整现有 fake provider 测试对象以接受 `tools` 参数。
4. 验证现有普通文本测试仍能通过。

**验证：** 运行 `pytest tests/test_session.py tests/test_providers.py -k factory`，期望全部通过。

## T9: 扩展 OpenAI-compatible Provider

**文件：** `src/mycode/providers/openai.py`, `src/mycode/providers/deepseek.py`, `tests/test_providers.py`

**依赖：** T1, T6, T8

**步骤：**

1. 在请求体中加入由 `ToolSpec` 转换得到的 `tools`。
2. 将包含 `tool_calls` 的 assistant 消息转换为 OpenAI Chat Completions 消息格式。
3. 将 `tool` 消息转换为 OpenAI tool result 消息格式。
4. 解析 `choices[0].delta.tool_calls` 中的工具调用 ID、名称和参数碎片。
5. 输出 `tool_call_delta` 和 `tool_call_done` 事件。
6. 保持 `[DONE]` 生成 `message_done`。
7. 保证 DeepSeek 继续复用该行为。
8. 编写工具声明入参、assistant tool_calls 消息转换、tool result 消息转换、参数碎片解析、DeepSeek 复用测试。

**验证：** 运行 `pytest tests/test_providers.py -k "openai or deepseek"`，期望全部通过。

## T10: 扩展 Anthropic Provider

**文件：** `src/mycode/providers/anthropic.py`, `tests/test_providers.py`

**依赖：** T1, T6, T8

**步骤：**

1. 把通用 `ToolSpec` 转换为 Anthropic tools 格式。
2. 将包含 `tool_calls` 的 assistant 消息转换为 Anthropic `tool_use` 内容块。
3. 将 `tool` 消息转换为 Anthropic `tool_result` 内容块。
4. 保持现有 thinking 配置行为。
5. 解析 `content_block_start` 中的工具 ID 和工具名。
6. 解析 `input_json_delta` 中的参数碎片。
7. 在 `content_block_stop` 时输出 `tool_call_done`。
8. 在 `message_stop` 时输出 `message_done`。
9. 编写工具声明转换、工具消息转换、工具结果消息转换、参数碎片解析、thinking 回归测试。

**验证：** 运行 `pytest tests/test_providers.py -k anthropic`，期望全部通过。

## T11: 实现工具调用参数拼接

**文件：** `src/mycode/session.py`, `tests/test_tool_streaming.py`

**依赖：** T1, T8, T9, T10

**步骤：**

1. 在会话层维护 `PendingToolCall` 集合。
2. 收到 `tool_call_delta` 时按工具调用 ID 追加 JSON 参数碎片。
3. 收到 `tool_call_done` 时解析完整 JSON。
4. 参数合法时生成 `ToolCall`。
5. 参数不是合法 JSON 时生成失败 `ToolResult`。
6. 支持同一轮中多个工具调用的拼接和顺序保留，但本阶段只执行这一轮。
7. 编写单工具碎片拼接、多工具拼接、非法 JSON 失败结果测试。

**验证：** 运行 `pytest tests/test_tool_streaming.py`，期望全部通过。

## T12: 实现会话单轮工具闭环

**文件：** `src/mycode/session.py`, `tests/test_session_tools.py`, `tests/test_session.py`

**依赖：** T7, T11

**步骤：**

1. 修改 `ChatSession.__init__()`，接收可选 `ToolRegistry` 和 `ToolContext`。
2. 用户输入后第一轮 Provider 请求携带工具声明。
3. 普通文本回复继续汇总并追加 assistant 消息。
4. 出现工具调用时，汇总 assistant 的工具调用消息并追加历史。
5. 对每个 `ToolCall` 发送 `tool_started` 事件。
6. 通过 `ToolExecutor` 执行工具。
7. 对每个结果发送 `tool_finished` 事件。
8. 把工具结果序列化为 tool 消息追加历史。
9. 发起一次后续 Provider 请求，生成最终文本回复。
10. 后续 Provider 请求不携带工具声明，避免第二轮自动工具执行。
11. 如果后续回复仍产生工具调用事件，本阶段不执行，并返回清晰停止边界。
12. 编写普通聊天回归、工具成功回灌、工具失败回灌、未知工具、单轮停止边界测试。

**验证：** 运行 `pytest tests/test_session.py tests/test_session_tools.py`，期望全部通过。

## T13: 集成 CLI 工具状态展示

**文件：** `src/mycode/cli.py`, `tests/test_cli.py`

**依赖：** T12

**步骤：**

1. CLI 启动时创建默认工具注册中心。
2. CLI 启动时创建默认 `ToolContext`，工作区根目录为当前进程启动目录。
3. 构造 `ChatSession` 时传入工具注册中心和工具上下文。
4. 收到 `tool_started` 时打印工具开始提示。
5. 收到 `tool_finished` 时打印成功或失败状态和简短消息。
6. 保持文本增量流式打印。
7. 保持配置错误、Provider 错误和退出命令行为。
8. 编写工具开始展示、工具成功展示、工具失败展示、普通聊天回归测试。

**验证：** 运行 `pytest tests/test_cli.py`，期望全部通过。

## T14: 更新文档说明

**文件：** `README.md`

**依赖：** T13

**步骤：**

1. 增加工具系统能力说明。
2. 列出六个核心工具。
3. 明确文件和命令默认限制在工作区内。
4. 明确本阶段不是完整自动 Agent Loop。
5. 补充工具系统测试命令。

**验证：** 阅读 `README.md`，确认没有暗示多轮自动工具循环已经实现。

## T15: 全量回归和静态检查

**文件：** `src/mycode/**`, `tests/**`

**依赖：** T1-T14

**步骤：**

1. 运行 Python 语法检查。
2. 运行全部 pytest。
3. 搜索旧项目名或错误项目名。
4. 搜索明显真实 API Key 模式。
5. 修复本阶段引入的失败。

**验证：** 运行 `python -m compileall src` 和 `pytest`，期望全部通过；运行项目名和 API Key 搜索，确认无新增问题。

## 执行顺序

```text
T1
→ T2
→ T3 → T4 → T5
→ T6
→ T7
→ T8
→ T9 → T10
→ T11
→ T12
→ T13
→ T14
→ T15
```
