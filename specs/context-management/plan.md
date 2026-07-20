# MyCode 上下文管理 Plan

## 架构概览

### 配置层

在现有应用配置中加入上下文窗口上限和轻量阈值。配置加载阶段完成默认值填充与正整数校验，向 Agent 注入不可变的上下文管理配置。

### 工具结果双视图层

工具仍向 CLI、事件流和普通调用方提供现有的受限结果，同时为上下文管理器提供完整结果视图。只有生成模型历史时才读取完整视图；通用日志和事件序列化只允许访问受限视图。

### 会话文件存储层

为每次 MyCode 进程会话创建工作区内的独立隐藏目录。该层负责原子写入完整工具结果或用户原文、生成不冲突的相对路径、校验工作区边界，以及正常退出时清理本会话目录。

### Token 估算层

把实际待发送请求规范化为稳定快照，使用“非 ASCII 字符 1 token、ASCII 字符约 3 字符 1 token”的权重计算近似值。普通请求成功返回 input usage 后记录 usage 与请求快照；后续估算只计算快照差值。

### 轻量压缩层

在普通请求组装完成后检查工具结果：先处理单项超限，再按同一次助手工具调用产生的结果集合计算合计量，并从大到小继续卸载。该层生成可回滚的候选历史，全部文件成功写入后才提交。

### 重量摘要层

把历史划分为“早期可压缩单元”和“近期原文单元”，保持工具调用与结果完整成组。摘要服务使用当前 Provider、空工具集合和专用 Prompt，解析 `<final_summary>` 并校验六个标题；成功后保存摘要状态和独立边界提示，失败时不修改活动历史。

### 上下文协调层

统一编排轻量压缩、预算判断、自动摘要、手动摘要、用户消息极端卸载、失败计数和熔断。它向 Agent 返回准备后的消息、摘要 system 块、边界 system 块以及可展示的压缩报告。

### Agent 与 CLI 接入层

`AgentRunner` 在每次普通 Provider 调用前调用上下文协调层，并在响应完成后提交 input usage 锚点。CLI 将 `/compact` 作为本地命令直接调用 Agent 的压缩入口，显示报告但不创建用户消息；CLI 退出时触发会话文件清理。

主数据流：

```text
工具执行
  → 受限结果用于事件展示
  → 完整结果进入候选历史
  → 请求前轻量卸载
  → Token 估算
  → 必要时重量摘要
  → 组装摘要/边界 system 块与近期原文
  → Provider 请求
  → 成功 usage 更新估算锚点
```

## 核心数据结构

### ContextConfig

- `window_tokens: int`：来自必填配置 `context_window_tokens`
- `tool_result_threshold_tokens: int = 8000`
- `tool_batch_threshold_tokens: int = 16000`
- 自动余量 13K、手动余量 3K、近期目标 10K、最少 5 条消息、预览首尾各 1,000 字符和熔断阈值 3 次作为本阶段固定常量，不开放额外配置

### ToolExecutionResult

- `display: ToolResult`：保持当前截断和展示语义，仅供事件、终端及普通调用方使用
- `complete: ToolResult`：包含截断前完整结果，仅交给上下文管理器
- 未发生截断的工具让两个视图引用同一不可变结果，避免复制

### ContextUnit

请求历史的原子边界：

- 普通用户或助手消息各自形成一个单元
- 带工具调用的助手消息与其全部对应工具结果形成一个不可拆分单元
- 近期保留、早期摘要和用户原文卸载都只在单元边界操作

### ContextState

- 当前活动消息
- 最近一次正式摘要
- 独立的压缩边界 system 块
- 连续摘要失败次数
- 自动摘要是否熔断
- 最近一次普通请求的 Token 锚点

### TokenAnchor

- Provider 返回的 `input_tokens`
- 该次普通请求的规范化快照估算分值
- 摘要请求的 usage 不写入此锚点

### StoredContextReference

- 工作区相对路径
- 内容种类：工具结果或用户原文
- 原始字符数与近似 token 数
- 对应工具调用 ID 或消息序号

### SummaryOutput

- 解析器确认 `<analysis_draft>` 区块存在后立即丢弃其内容，不把草稿放入返回对象
- 从 `<final_summary>` 提取的正式摘要
- 六个固定标题的校验结果

### CompactionReport

- 状态：成功、失败、无需压缩或熔断
- 触发方式：自动或手动
- 压缩前后估算量及目标预算
- 卸载工具结果数量、卸载用户消息数量、摘要消息数量
- 安全的失败阶段与原因，不包含原始正文

## 核心接口

### ContextStore

- 创建工作区内的会话目录
- 原子写入完整工具结果或用户原文
- 返回模型可读取的工作区相对路径
- 正常退出时清理本会话目录
- 写入失败时删除本次尚未提交的临时文件

### TokenEstimator

- 把完整 `ChatRequest` 转成稳定的 Provider 无关快照
- 计算混合字符权重分值
- 无锚点时估算完整请求
- 有锚点时计算 `input usage + 当前分值 - 锚点分值`
- 只接受成功普通请求更新锚点

### SummaryService

- 使用当前 Provider 和专用摘要 Prompt 发起空工具请求
- 收集完整文本但不转发草稿到终端
- 拒绝任何工具调用事件
- 提取 `<final_summary>` 并校验六个固定标题
- 返回正式摘要或结构化失败

### ContextManager

- 持有 `ContextState` 和会话存储
- 接收用户、助手及一整批双视图工具结果
- 在请求前执行轻量卸载
- 组装摘要与边界两个动态 system 块
- 估算完整请求并按自动或手动预算决定重量摘要
- 原子提交压缩结果
- 维护失败计数和熔断状态
- 产生 `CompactionReport`
- 当预算仍超限时返回拒绝结果，不调用普通 Provider

### AgentRunner

- 把历史所有权委托给 `ContextManager`
- 为当前模式生成不含历史的请求模板
- 请求上下文管理器准备最终 `ChatRequest`
- Provider 成功后提交该请求及 input usage
- 暴露 `compact()` 给 CLI
- 保留只读 `messages` 属性，兼容现有测试和观察入口

### CLI

- 在解析 `/plan`、`/do` 前先识别精确命令 `/compact`
- 直接调用 `AgentRunner.compact()`，不创建 `AgentRequest`
- 格式化 `CompactionReport`
- 在进程退出的 `finally` 路径中执行上下文目录清理

另外新增 `context_overflow` 停止原因：它表示请求因预算保护未发送，与 Provider 流错误区分开。

## 模块交互

### 普通请求前置流程

1. `AgentRunner` 先把本轮用户消息加入 `ContextManager`。
2. `AgentRunner` 根据当前 default、plan 或 do 模式生成请求模板。
3. `ContextManager` 基于完整工具结果创建候选历史。
4. 轻量阶段先卸载单项超限结果，再处理同一模型响应中的工具结果合计阈值。
5. 使用候选历史、当前摘要、边界提示、系统提示和工具定义组装完整候选请求。
6. `TokenEstimator` 估算候选请求。
7. 未达到自动预算时，提交轻量结果并发送普通请求。
8. 达到自动预算时，选择近期完整 `ContextUnit`，把更早历史交给 `SummaryService`。
9. 摘要成功后，候选状态保存正式摘要、边界 system 块、早期用户原文和近期原文。
10. 若仍超预算，按时间顺序卸载最早的用户原文，直到满足预算或没有可卸载消息。
11. 只有所有文件写入、摘要校验和最终预算检查都成功，才一次性提交候选状态并发送普通请求。
12. Provider 成功返回后，用实际发送的请求快照和 `input_tokens` 更新锚点。

### 工具结果流程

1. 工具生成 `ToolExecutionResult`。
2. `display` 视图进入 `tool_result` 事件，维持现有终端行为。
3. `complete` 视图随工具调用 ID 进入上下文历史。
4. 同一次模型响应产生的全部工具结果记录为同一批次，不受只读并发执行完成顺序影响。
5. 模型历史仍按原始工具调用顺序排列，不按并发完成顺序排列。
6. “完整结果”只移除现有字符截断；搜索最大匹配数、命令超时、远端协议限制等既有语义边界保持不变。

### 重量摘要流程

1. 按 `ContextUnit` 从尾部向前选择，直到同时满足约 10K token 和至少 5 条消息。
2. 摘要输入包括旧摘要和本次较早历史，使多次压缩能够延续已有状态。
3. 专用 system Prompt 禁止工具，并规定两个 XML 风格区块与六个 Markdown 标题。
4. 摘要请求使用当前 Provider、`tools=()`、禁用普通请求缓存标记，也不进入普通压缩前置流程。
5. 收集响应时若出现工具调用、Provider 错误、标记不完整、标题缺失或重复，立即失败。
6. 只保存 `<final_summary>`；`<analysis_draft>` 不进入日志、事件或历史。
7. 成功候选还必须重新估算；未达到目标预算则先尝试卸载早期用户原文，仍超限时整体失败。
8. 自动失败计数加一；成功清零。第三次自动失败后熔断。
9. 熔断期间，低于自动预算的请求仍可发送；达到预算的请求直接拒绝。手动成功后恢复自动摘要。

### 原子提交与文件回滚

- 每次压缩建立独立事务对象，记录原状态和本次新建文件。
- 单个文件先写同目录临时文件，刷新关闭后原子改名。
- 候选历史尚未提交前，新文件不被任何活动消息引用。
- 任一步骤失败时删除本事务新文件并保留原状态。
- 提交成功后才替换活动状态。
- 清理旧摘要已不再引用的上下文文件不放在关键提交路径；本阶段统一在会话退出时删除整个会话目录。

### `/compact` 流程

1. CLI 在创建 `AgentRequest` 前识别完全匹配的 `/compact`。
2. Agent 使用最近一次普通请求的模式和工具集合生成估算模板；尚无普通请求时使用 default 模式。
3. 先执行轻量阶段，再强制尝试重量摘要，不要求达到自动阈值。
4. 没有足够的早期历史时返回“无需压缩”。
5. 成功要求压缩后估算量低于压缩前，且不超过窗口减 3K 的预算。
6. CLI 只打印安全的 `CompactionReport` 字段。

## 文件组织

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mycode/context/__init__.py` | 导出上下文管理公共类型 |
| 新建 | `src/mycode/context/models.py` | 配置、状态、历史单元、锚点、引用和报告模型 |
| 新建 | `src/mycode/context/estimator.py` | 请求快照、混合字符估算和 usage 锚点 |
| 新建 | `src/mycode/context/storage.py` | 会话目录、原子写入、路径校验、回滚和清理 |
| 新建 | `src/mycode/context/prompts.py` | 摘要 Prompt、六段标题和边界提示 |
| 新建 | `src/mycode/context/summary.py` | 摘要请求、事件收集、标记解析与格式校验 |
| 新建 | `src/mycode/context/manager.py` | 两层压缩、历史分组、预算判断、事务提交和熔断 |
| 修改 | `src/mycode/types.py` | 应用配置和双视图工具执行结果 |
| 修改 | `src/mycode/config.py` | 上下文配置解析、默认值和校验 |
| 修改 | `src/mycode/agent/runner.py` | 请求前置、历史委托、usage 锚定和手动压缩入口 |
| 修改 | `src/mycode/agent/events.py` | 上下文超限停止原因和安全状态事件 |
| 修改 | `src/mycode/agent/executor.py` | 保持工具调用顺序并传递双视图结果 |
| 修改 | `src/mycode/tools/base.py` | 双视图结果构造辅助函数 |
| 修改 | `src/mycode/tools/executor.py` | 统一包装权限拒绝、超时和异常结果 |
| 修改 | `src/mycode/tools/files.py` | 文件读取的受限视图和完整视图 |
| 修改 | `src/mycode/tools/command.py` | stdout/stderr 的受限视图和完整视图 |
| 修改 | `src/mycode/tools/search.py` | 搜索输出的受限视图和完整视图 |
| 修改 | `src/mycode/mcp/tool.py` | MCP 文本及结构化结果的双视图 |
| 修改 | `src/mycode/session.py` | 适配双视图执行结果，维持旧 Session 行为 |
| 修改 | `src/mycode/cli.py` | `/compact`、报告显示和上下文清理 |
| 修改 | `config.example.yaml` | 必填窗口与可选阈值示例 |
| 修改 | `.gitignore` | 忽略异常退出遗留的 `.mycode/context/` |
| 修改 | `README.md` | 配置、自动压缩、手动命令和文件生命周期说明 |
| 新建 | `tests/test_context_estimator.py` | 估算与锚点测试 |
| 新建 | `tests/test_context_storage.py` | 写入、边界、回滚和清理测试 |
| 新建 | `tests/test_context_summary.py` | Prompt、空工具、解析和失败测试 |
| 新建 | `tests/test_context_manager.py` | 两层压缩、消息单元、预算和熔断测试 |
| 修改 | 现有相关测试文件 | 配置、工具、Agent、CLI、Provider 和回归测试 |
| 新建 | `tests/test_context_integration.py` | 长会话端到端场景 |

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 配置形态 | 顶层必填 `context_window_tokens`；顶层可选 `tool_result_threshold_tokens`、`tool_batch_threshold_tokens` | 延续现有简单 YAML 风格，并遵守已确认的配置名 |
| 工具输出 | 双视图结果 | 保存完整内容，同时保持终端和现有调用行为 |
| 字符截断 | 受限视图保留，完整视图绕过字符截断 | 满足可恢复要求，不取消搜索数量和超时等语义限制 |
| 会话目录 | `.mycode/context/<随机会话 ID>/` | 工作区工具可读取、会话隔离、异常残留可被 Git 忽略 |
| 文件格式 | 工具结果为 UTF-8 JSON，用户消息为 UTF-8 文本 | 保持数据语义并方便重新读取 |
| 路径引用 | 模型历史只使用工作区相对路径 | 与现有 `read_file` 接口一致，避免泄露或依赖绝对路径 |
| 历史边界 | `ContextUnit` 原子分组 | 防止孤立工具结果和非法 Provider 序列 |
| 摘要承载 | 两个动态 system 块 | 不伪造用户发言，兼容三类 Provider |
| 摘要格式 | XML 风格外层标记加六个 Markdown 标题 | 易于生成长文本，也能严格区分草稿与正式摘要 |
| Token 估算 | 规范化请求快照、混合字符权重、input usage 差量锚定 | 无 tokenizer 依赖，兼顾中文与代码 |
| 锚点来源 | 仅成功的普通请求 | 摘要请求结构不同，不能作为活动会话差量基准 |
| 批次定义 | 同一次模型响应的全部工具调用结果 | 对应单轮工具结果合计，且不受安全分批影响 |
| 自动事务 | 轻量与必要的重量压缩合并提交 | 摘要失败时不会留下半压缩历史 |
| 手动模板 | 最近普通请求模式；无历史时 default | 让估算尽量接近下一次实际请求 |
| 熔断 | 会话内连续失败三次；手动成功恢复 | 防止死循环，同时保留人工恢复通道 |
| 新依赖 | 不增加 | 标准库足以完成估算、解析、原子写入和清理 |

## Spec 覆盖

- F1–F2：配置层
- F3–F6：双视图、轻量压缩、会话存储
- F7：估算器和 usage 锚点
- F8–F13：协调层、历史单元、摘要服务及 system 块
- F14–F17：事务、格式校验、熔断、报告和请求拒绝
- N1–N11：Provider 合法性、路径安全、原子性、可观测错误及完整测试矩阵
