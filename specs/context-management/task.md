# MyCode 上下文管理 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mycode/context/__init__.py` | 导出上下文管理公共类型 |
| 新建 | `src/mycode/context/models.py` | 配置、状态、历史单元、锚点、引用和报告模型 |
| 新建 | `src/mycode/context/estimator.py` | 请求快照、近似估算和 usage 锚点 |
| 新建 | `src/mycode/context/storage.py` | 会话目录、原子写入、事务文件与清理 |
| 新建 | `src/mycode/context/prompts.py` | 摘要 Prompt、固定标题和边界提示 |
| 新建 | `src/mycode/context/summary.py` | 摘要请求、流收集、标记解析和校验 |
| 新建 | `src/mycode/context/manager.py` | 历史管理、两层压缩、预算、事务和熔断 |
| 修改 | `src/mycode/types.py` | 上下文配置和双视图工具执行结果 |
| 修改 | `src/mycode/config.py` | 必填窗口、可选阈值及校验 |
| 修改 | `src/mycode/agent/runner.py` | 上下文请求前置、usage 锚定和手动入口 |
| 修改 | `src/mycode/agent/events.py` | 上下文超限停止原因和安全状态事件 |
| 修改 | `src/mycode/agent/executor.py` | 双视图传递与工具调用顺序恢复 |
| 修改 | `src/mycode/tools/base.py` | 双视图构造辅助函数 |
| 修改 | `src/mycode/tools/executor.py` | 统一的双视图错误包装 |
| 修改 | `src/mycode/tools/files.py` | 文件工具完整结果视图 |
| 修改 | `src/mycode/tools/command.py` | 命令输出完整结果视图 |
| 修改 | `src/mycode/tools/search.py` | 搜索输出完整结果视图 |
| 修改 | `src/mycode/mcp/tool.py` | MCP 文本与结构化结果完整视图 |
| 修改 | `src/mycode/session.py` | 适配双视图并保持旧 Session 行为 |
| 修改 | `src/mycode/cli.py` | `/compact`、报告和退出清理 |
| 修改 | `config.example.yaml` | 上下文配置示例 |
| 修改 | `.gitignore` | 忽略异常退出遗留上下文目录 |
| 修改 | `README.md` | 配置、压缩行为和生命周期文档 |
| 新建 | `tests/test_context_estimator.py` | Token 估算测试 |
| 新建 | `tests/test_context_storage.py` | 会话文件与事务测试 |
| 新建 | `tests/test_context_summary.py` | 摘要协议测试 |
| 新建 | `tests/test_context_manager.py` | 两层压缩和熔断测试 |
| 新建 | `tests/test_context_integration.py` | 长会话端到端测试 |
| 修改 | `tests/test_config.py` | 上下文配置测试 |
| 修改 | `tests/test_tools_files.py` | 文件工具双视图测试 |
| 修改 | `tests/test_tools_command.py` | 命令工具双视图测试 |
| 修改 | `tests/test_tools_search.py` | 搜索工具双视图测试 |
| 修改 | `tests/test_mcp_tool.py` | MCP 双视图测试 |
| 修改 | `tests/test_tool_executor.py` | 执行器双视图测试 |
| 修改 | `tests/test_agent_executor.py` | 批次结果和顺序测试 |
| 修改 | `tests/test_session.py` | 旧 Session 回归测试 |
| 修改 | `tests/test_agent_runner.py` | Agent 上下文接入测试 |
| 修改 | `tests/test_cli.py` | 手动命令、报告和清理测试 |
| 修改 | `tests/test_providers.py` | 压缩后 system 块与消息合法性测试 |

## T1: 增加上下文配置与领域模型

**文件：** `src/mycode/types.py`、`src/mycode/config.py`、`src/mycode/context/__init__.py`、`src/mycode/context/models.py`、`tests/test_config.py`

**依赖：** 无

**步骤：**

1. 定义不可变的 `ContextConfig`、`ContextState`、`ContextUnit`、`TokenAnchor`、`StoredContextReference`、`SummaryOutput` 和 `CompactionReport`。
2. 在应用配置中加入必填 `context_window_tokens`，以及默认 8K/16K 的两个可选阈值。
3. 对缺失值、布尔值冒充整数、零、负数和错误类型给出精确配置错误。
4. 保持用户级 MCP 配置只参与 MCP 合并；上下文与 Provider 配置继续以项目级配置为准。
5. 为后续模块导出稳定的上下文类型。

**验证：**

运行 `pytest -q tests/test_config.py`，确认合法配置加载默认值和覆盖值，所有非法边界在启动前失败。

## T2: 建立双视图工具执行管线

**文件：** `src/mycode/types.py`、`src/mycode/tools/base.py`、`src/mycode/tools/executor.py`、`src/mycode/agent/executor.py`、`src/mycode/session.py`、`tests/test_tool_executor.py`、`tests/test_agent_executor.py`、`tests/test_session.py`

**依赖：** T1

**步骤：**

1. 定义 `ToolExecutionResult(display, complete)`，提供同视图结果的便捷构造方式。
2. 让权限拒绝、未知工具、超时和异常路径也返回合法双视图，两个视图内容一致。
3. 让终端事件只接收 `display`，Agent 历史管线接收完整执行记录。
4. 对只读并发批次按原始工具调用顺序汇总结果，避免完成顺序改变消息关联。
5. 更新旧 `Session` 仅消费展示视图，维持原有行为和测试契约。

**验证：**

运行 `pytest -q tests/test_tool_executor.py tests/test_agent_executor.py tests/test_session.py`，确认错误路径、并发顺序、事件内容和旧 Session 全部通过。

## T3: 为内置工具和 MCP 产生完整结果视图

**文件：** `src/mycode/tools/files.py`、`src/mycode/tools/command.py`、`src/mycode/tools/search.py`、`src/mycode/mcp/tool.py`、`tests/test_tools_files.py`、`tests/test_tools_command.py`、`tests/test_tools_search.py`、`tests/test_mcp_tool.py`

**依赖：** T2

**步骤：**

1. 文件读取、命令 stdout/stderr 和搜索文本同时生成当前受限视图与字符截断前的完整视图。
2. 保留搜索最大匹配数、命令超时和路径边界等语义限制，只绕过 `max_output_chars` 字符截断。
3. MCP 文本和可序列化 `structuredContent` 生成完整视图；展示视图继续遵守现有大小边界。
4. 不支持的 MCP 内容类型、远端错误和不可序列化结构仍以两个相同的失败视图返回。
5. 测试确保完整内容不会出现在展示结果或终端事件中。

**验证：**

运行 `pytest -q tests/test_tools_files.py tests/test_tools_command.py tests/test_tools_search.py tests/test_mcp_tool.py`，确认短结果行为不变，超长结果只在完整视图中可恢复。

## T4: 实现 Token 估算与 usage 锚点

**文件：** `src/mycode/context/estimator.py`、`src/mycode/context/models.py`、`tests/test_context_estimator.py`

**依赖：** T1

**步骤：**

1. 为 `ChatRequest` 的系统提示、动态提示、消息、工具调用和工具定义生成排序稳定、编码稳定的规范化快照。
2. 实现非 ASCII 每字符 1 token、ASCII 每 3 字符约 1 token 的向上取整估算。
3. 无锚点时估算完整请求；有锚点时使用真实 input usage 加当前与锚点快照分值差。
4. 估算结果下限为零，缺失 `input_tokens` 时不更新锚点。
5. 明确区分普通请求锚点更新与摘要请求忽略路径。

**验证：**

运行 `pytest -q tests/test_context_estimator.py`，确认快照稳定、中文/ASCII 权重、增删差量、工具定义变化和缺失 usage 均符合设计。

## T5: 实现会话上下文存储与事务文件

**文件：** `src/mycode/context/storage.py`、`src/mycode/context/models.py`、`tests/test_context_storage.py`、`.gitignore`

**依赖：** T1、T4

**步骤：**

1. 在 `.mycode/context/<随机会话 ID>/` 下延迟创建会话目录，并验证解析后的目录仍位于工作区内。
2. 工具结果以 UTF-8 JSON 写入，用户消息以 UTF-8 文本写入，文件名包含唯一标识且不接受外部路径。
3. 使用同目录临时文件和原子改名完成单文件提交。
4. 提供压缩事务，能够跟踪本次新文件并在候选状态失败时回滚。
5. 正常关闭时递归删除本会话目录；清理错误转换为不含正文的安全警告。
6. 将整个上下文根目录加入 Git 忽略，覆盖异常退出残留。

**验证：**

运行 `pytest -q tests/test_context_storage.py`，确认内容完整、路径可由 `read_file` 使用、文件不覆盖、越界/符号链接被拒绝、失败回滚且正常清理。

## T6: 实现无工具摘要协议

**文件：** `src/mycode/context/prompts.py`、`src/mycode/context/summary.py`、`src/mycode/context/models.py`、`tests/test_context_summary.py`

**依赖：** T1

**步骤：**

1. 编写专用 system Prompt，明确禁止工具调用，要求先输出 `<analysis_draft>` 再输出 `<final_summary>`。
2. 在正式摘要中固定六个唯一 Markdown 标题，并加入不臆测文件细节的约束。
3. 使用当前 Provider 构造 `tools=()`、不启用普通缓存标记的独立请求。
4. 收集文本与工具调用事件；出现任何工具调用时拒绝摘要，不执行工具。
5. 校验外层标记顺序、唯一性和六个标题；立即丢弃草稿，只返回正式摘要。
6. 将 Provider、空响应、解析和格式错误转换为可区分且不泄露正文的失败。

**验证：**

运行 `pytest -q tests/test_context_summary.py`，确认空工具、草稿丢弃、六段解析、工具调用拒绝及各失败类型。

## T7: 实现轻量压缩和历史原子单元

**文件：** `src/mycode/context/manager.py`、`src/mycode/context/models.py`、`tests/test_context_manager.py`

**依赖：** T3、T4、T5

**步骤：**

1. 让 `ContextManager` 接收用户、助手和按原调用顺序排列的一批完整工具结果。
2. 把普通消息建成单消息单元，把助手工具调用及全部对应结果建成不可拆分单元。
3. 用完整工具结果序列化内容估算单项大小；超过 8K 时生成首尾各 1,000 字符的预览引用。
4. 对同一次模型响应剩余的未卸载结果计算合计量，超过 16K 时按体积降序卸载直到满足阈值。
5. 轻量阶段使用候选状态和存储事务；所有文件成功后一次性提交，失败时恢复原历史。
6. 保证预览包含相对路径、原始字符数、近似 token 数和重新读取说明。

**验证：**

运行 `pytest -q tests/test_context_manager.py -k 'lightweight or unit or batch or preview or rollback'`，确认单项阈值、合计阈值、降序选择、消息分组和原子回滚。

## T8: 实现重量摘要、用户原文保护和熔断

**文件：** `src/mycode/context/manager.py`、`src/mycode/context/models.py`、`src/mycode/context/prompts.py`、`tests/test_context_manager.py`

**依赖：** T4、T5、T6、T7

**步骤：**

1. 从尾部按完整历史单元选择近期区，直到同时满足约 10K token 和至少 5 条消息。
2. 把旧摘要与本次早期历史交给摘要服务，成功后生成独立摘要和边界动态 system 块。
3. 保留早期用户消息原文；最终估算仍超目标时，按时间顺序把最早用户消息原文存盘并替换为路径引用。
4. 自动模式使用窗口减 13K 的预算，手动模式使用窗口减 3K，并在手动模式下强制尝试摘要。
5. 摘要、用户卸载和轻量结果使用同一候选事务；解析失败、存储失败或最终仍超预算时整体回滚。
6. 实现连续失败计数、第三次自动失败熔断、手动成功清零恢复，以及熔断期间的请求拒绝。
7. 生成不含正文的成功、失败、无需压缩和熔断报告。

**验证：**

运行 `pytest -q tests/test_context_manager.py -k 'summary or recent or user or budget or breaker or manual or atomic'`，确认近期边界、重复摘要、用户保护、预算、失败三连、手动恢复和整体回滚。

## T9: 接入 Agent 请求循环与 Provider 消息

**文件：** `src/mycode/agent/runner.py`、`src/mycode/agent/events.py`、`tests/test_agent_runner.py`、`tests/test_providers.py`

**依赖：** T2、T4、T6、T8

**步骤：**

1. 把 `AgentRunner` 的历史写入和读取委托给 `ContextManager`，保留只读 `messages` 观察属性。
2. 在每次普通 Provider 调用前构建请求模板，并交由上下文管理器执行轻量与预算前置。
3. 把正式摘要和边界分别追加为动态 system 块，保持近期消息角色和工具调用关联。
4. 在成功普通响应完成后，用实际请求和 `input_tokens` 更新锚点；流错误和摘要请求不更新。
5. 自动压缩失败且仍超预算时不调用 Provider，发出安全错误及 `context_overflow` 完成事件。
6. 暴露 `compact()`，使用最近普通请求模式；无历史模板时使用 default。
7. 验证三类 Provider 的 system 块位置、空工具摘要请求和正常消息转换保持合法。

**验证：**

运行 `pytest -q tests/test_agent_runner.py tests/test_providers.py`，确认每次迭代前置、usage 锚定、拒绝不发请求、手动入口和三类协议消息合法。

## T10: 接入 CLI、生命周期和用户文档

**文件：** `src/mycode/cli.py`、`config.example.yaml`、`README.md`、`tests/test_cli.py`

**依赖：** T1、T5、T8、T9

**步骤：**

1. 在 CLI 普通请求解析前识别精确 `/compact`，不把该文本构造成用户消息。
2. 格式化压缩前后估算、目标预算、处理数量、状态和安全原因。
3. 对自动超预算拒绝显示 `/compact` 重试提示。
4. 把上下文清理接入主流程 `finally`；清理失败只告警，不阻止 MCP 和进程退出清理。
5. 更新示例配置，加入必填窗口上限与两个可选阈值。
6. 更新 README，说明两层策略、文件位置、正常清理、手动命令、熔断和超预算行为。

**验证：**

运行 `pytest -q tests/test_cli.py tests/test_config.py`，确认 `/compact` 不进入历史、报告输出不泄露正文、清理始终执行且示例配置可加载。

## T11: 完成长会话端到端与全量回归

**文件：** `tests/test_context_integration.py`、所有受影响测试文件

**依赖：** T1–T10

**步骤：**

1. 构造同时包含单项超限、多结果合计超限和累计历史超限的脚本化 Provider 长会话。
2. 验证完整工具结果按路径可重读、预览受限、早期历史形成六段摘要、边界 system 块存在且近期原文保持。
3. 覆盖用户消息极端卸载、摘要失败三次熔断、手动恢复和最终超预算不发送请求。
4. 分别通过 OpenAI、Anthropic、DeepSeek 的请求转换测试检查压缩后的协议合法性。
5. 验证正常退出后会话目录消失，错误与报告不包含原始正文。
6. 运行全量测试并修复所有上下文管理引入的回归。

**验证：**

运行 `pytest -q tests/test_context_integration.py`，再运行 `pytest -q`；期望端到端场景和项目全量测试全部通过。

## 执行顺序

```text
T1 → {T2, T4, T5, T6}
T2 → T3
{T3, T4, T5} → T7
{T6, T7} → T8
{T2, T4, T6, T8} → T9 → T10 → T11
```

建议提交边界：

```text
T1
T2–T3
T4–T5
T6
T7–T8
T9–T10
T11
```
