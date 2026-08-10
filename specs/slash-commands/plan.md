# MewCode 斜杠命令注册与分发 Plan

## 设计依据

- 已批准需求：[`spec.md`](./spec.md)
- 当前交互入口：`src/mycode/cli.py` 中的同步输入与 Agent 事件循环。
- 当前输入依赖：项目已安装 `prompt_toolkit>=3.0`，本地环境为 3.0.52。
- 当前模式模型：Agent 仍兼容 `default`、`plan`、`do`，但本功能的交互状态只使用 `default` 与 `plan`。
- 当前只读工具：`read_file`、`find_files`、`search_code`；尚无安全读取 Git 工作区差异的能力。

## 架构概览

采用“命令核心 + 应用适配器”两层结构，并通过只读状态快照连接既有 Agent、上下文、记忆和权限模块。

命令核心层负责命令元数据、注册顺序、名称/别名索引、启动期冲突检测、输入分类、命令解析、分发、内置命令和补全候选。除补全渲染适配器外，核心层不依赖 `prompt_toolkit`、终端输出或具体 Agent 实现。

应用适配层位于 CLI。它实现 `CommandUI`，保存当前进程唯一的 `default/plan` 模式，负责终端显示、清屏、Agent 请求、状态查询和状态栏刷新。CLI 只创建一个 `PromptSession`，在各轮输入间复用补全器和动态底部状态栏。

状态快照层由现有领域模块提供无副作用的最小状态：上下文管理器提供估算，记忆 Worker 提供忙闲与任务数，权限服务提供会话规则数。CLI 将这些数据与启动配置、会话来源和路径组合成命令可消费的安全视图。

`/review` 使用固定提示词并以单次 `plan` 模式执行。由于现有 Plan 工具无法识别未提交差异，本功能增加无参数、固定 Git 子命令的 `read_git_changes` 专用只读工具；它不接受任意命令，也不进入权限审批。

```text
CLI 参数
  │
  ├─ create_default_command_registry
  │      └─ 名称/别名冲突 → 启动失败
  │
  ├─ 配置、Provider、权限、会话、Agent
  │
  └─ TerminalCommandUI + PromptSession
          │
          └─ InputRouter
                ├─ empty/exit → 本地结束或继续
                ├─ plain      → 当前模式 AgentRequest
                └─ command    → CommandDispatcher → CommandUI
                                      ├─ 本地/界面操作
                                      └─ review → 单次 plan AgentRequest
```

命令目录在 Provider 创建和 MCP 发现前完成构建。注册冲突产生明确的非零启动结果；单条命令异常只终止本条命令，交互循环继续。

## 核心数据结构

### `CommandSpec`

位置：`src/mycode/commands/models.py`

```python
@dataclass(frozen=True)
class CommandSpec:
    name: str
    aliases: tuple[str, ...]
    description: str
    usage: str
    command_type: Literal["local", "ui", "prompt"]
    argument_hint: str = ""
    hidden: bool = False
    handler: CommandHandler | None = None
```

规范名称不带 `/`。登记时把名称和别名统一转为小写并保存规范副本，避免查找与展示不一致。处理函数按需求允许为空；没有处理函数的命令如果被分发，返回安全的不可执行错误。

### `CommandInvocation`

位置：`src/mycode/commands/models.py`

```python
@dataclass(frozen=True)
class CommandInvocation:
    command: CommandSpec
    entered_name: str
    arguments: str
```

`entered_name` 保留用户输入的命令词供诊断；`arguments` 只去除外围空白，不解析引号、转义、管道或重定向。

### `InputRoute`

位置：`src/mycode/commands/models.py`

```python
@dataclass(frozen=True)
class InputRoute:
    kind: Literal["empty", "exit", "plain", "command", "error"]
    text: str = ""
    invocation: CommandInvocation | None = None
    message: str = ""
```

路由结果是纯数据。解析阶段不调用 Agent、不写会话、不打印消息，也不改变模式。

### `CommandRegistry`

位置：`src/mycode/commands/registry.py`

```python
class CommandRegistry:
    def register(self, command: CommandSpec) -> None: ...
    def resolve(self, name_or_alias: str) -> CommandSpec | None: ...
    def commands(self, *, include_hidden: bool = False) -> tuple[CommandSpec, ...]: ...
    def completion_candidates(self, fragment: str) -> tuple[CommandSpec, ...]: ...
```

Registry 同时保存登记顺序和归一化 token 到规范命令的查找表。`register` 在写入前验证整条命令，任何名称或别名重复都抛出 `CommandRegistrationError`，不会覆盖已有命令。

### `CommandUI`

位置：`src/mycode/commands/interfaces.py`

```python
class CommandUI(Protocol):
    @property
    def current_mode(self) -> Literal["default", "plan"]: ...

    def display_message(self, text: str, *, error: bool = False) -> None: ...
    def clear_screen(self) -> None: ...
    def send_user_message(
        self,
        text: str,
        *,
        mode_override: Literal["default", "plan"] | None = None,
    ) -> None: ...
    def switch_mode(self, mode: Literal["default", "plan"]) -> None: ...
    def compact_context(self) -> CompactionReport: ...
    def token_status(self) -> TokenStatus: ...
    def session_status(self) -> SessionStatus: ...
    def memory_status(self) -> MemoryStatus: ...
    def permission_status(self) -> PermissionStatus: ...
    def application_status(self) -> ApplicationStatus: ...
    def new_session(self) -> None: ...
    def refresh_status(self) -> None: ...
```

命令处理函数只依赖此协议。生产实现可以同步运行 Agent 并渲染事件；测试实现记录调用即可。

### 安全状态快照

`ContextStatus` 放在 `src/mycode/context/models.py`，使上下文和 Agent 不反向依赖命令包：

```python
@dataclass(frozen=True)
class ContextStatus:
    estimated_tokens: int
    window_tokens: int
    message_count: int
    has_summary: bool
    automatic_summary_tripped: bool
```

其余面向命令的视图放在 `src/mycode/commands/models.py`：

```python
@dataclass(frozen=True)
class TokenStatus:
    last_usage: TokenUsage | None
    context: ContextStatus

@dataclass(frozen=True)
class SessionStatus:
    session_id: str
    message_count: int
    origin: Literal["new", "restored"]
    context: ContextStatus

@dataclass(frozen=True)
class MemoryStatus:
    project_count: int
    user_count: int
    project_index_path: Path
    user_index_path: Path
    worker_state: Literal["idle", "busy"]
    pending_jobs: int

@dataclass(frozen=True)
class PermissionSourceStatus:
    source: Literal["session", "local", "project", "user"]
    path: Path | None
    loaded: bool
    rule_count: int

@dataclass(frozen=True)
class PermissionStatus:
    effective_mode: Literal["strict", "default", "allow"]
    mode_source: str
    sources: tuple[PermissionSourceStatus, ...]

@dataclass(frozen=True)
class ApplicationStatus:
    mode: Literal["default", "plan"]
    provider: str
    model: str
    token: TokenStatus
    session: SessionStatus
    memory: MemoryStatus
    permission: PermissionStatus
```

`MemoryWorkerStatus` 放在 `src/mycode/memory/models.py`，只含 `state` 与 `pending_jobs`。领域模块不导入 `mycode.commands`，依赖方向保持为 CLI/commands 读取领域状态。

所有快照只包含枚举、数字、布尔值和批准展示的路径，不包含记忆正文、权限表达式、API Key、Provider URL 或 MCP header。

### 压缩 Token 字段

`SummaryOutput` 增加 `token_usage: TokenUsage | None = None`；`CompactionReport` 增加 `summary_token_usage: TokenUsage | None = None`。`SummaryFailure` 同样允许携带已收到的用量，使摘要格式校验失败时仍可报告 Provider 已返回的统计。

最近 Token 的定义是最近完成的 Provider 请求，不累计整个会话。普通 Agent 请求由终端适配器从 token 事件更新；`/compact` 由 `CompactionReport.summary_token_usage` 更新。隐藏 `/new` 清空 Token 快照但保留进程模式。

## 模块设计

### 命令注册与冲突检测

**位置：** `src/mycode/commands/registry.py`

**职责：** 校验、归一化、登记、查找、可见枚举和补全候选。

**命名规则：**

- 规范名称匹配 `[a-z][a-z0-9_-]*`。
- 别名匹配相同规则，或精确为 `?`。
- 名称和别名不得带 `/`、空白或空字符串。
- 使用 `lower()` 归一化；内置标识均为 ASCII。
- 名称—名称、名称—别名、别名—别名、仅大小写不同以及同一命令内部重复均视为冲突。

**启动行为：** `create_default_command_registry()` 在 `main` 解析 CLI 参数后立即执行，并固定注册顺序。异常由 `main` 转成安全错误和退出码 1，不继续创建 Provider 或连接 MCP。

**覆盖：** F1、F2、F19、F20，N1、N4、N5。

### 输入路由与命令分发

**位置：** `src/mycode/commands/router.py`

**职责：** 把原始输入转换成 `InputRoute`，并将命令调用交给处理函数。

**解析顺序：**

1. 对完整输入执行 `strip()`；结果为空返回 `empty`。
2. 大小写不敏感地检查 `exit`、`quit`、`退出`，返回 `exit`。
3. 不以 `/` 开头返回 `plain`，文本使用已经去除外围空白的值。
4. 移除首个 `/`，按第一次空白执行一次切分。
5. 命令词为空返回 `error`；否则通过 Registry 解析名称或别名。
6. 未命中返回带 `/help` 引导的 `error`；命中则形成 `CommandInvocation`。

**参数约束：** 除 `/help` 接受零个或一个命令词外，其余内置命令统一调用无参数验证辅助函数。`/help` 的参数也不解析引号或多词名称。

**异常边界：** `CommandExecutionError` 展示预先构造的安全消息；其他 `Exception` 只展示异常类型和命令名，不展示 `str(exc)`。`KeyboardInterrupt`、`EOFError`、`SystemExit` 等非 `Exception` 控制流不被吞掉。

**覆盖：** F3、F4、F7、F21，N2、N4、N5、N8。

### 内置命令

**位置：** `src/mycode/commands/builtins.py`

**职责：** 集中登记元数据、类型、参数提示、隐藏标记、处理函数和固定审查提示。

注册顺序固定为：

```text
help → compact → clear → plan → do
→ session → memory → permission → status → review
→ new（隐藏）
```

类型映射：

| 命令 | 类型 |
|---|---|
| help、compact、session、memory、permission、status、new | local |
| clear、plan、do | ui |
| review | prompt |

各处理函数行为：

- `help`：无参数时按注册顺序格式化可见命令；有参数时通过名称或别名解析，允许显式查询隐藏命令。
- `compact`：调用 `compact_context`，展示既有压缩报告和可用的摘要 Token。
- `clear`：只调用 `clear_screen`。
- `plan`、`do`：分别切到 `plan`、`default`，显示确认并调用 `refresh_status`。
- `session`、`memory`、`permission`、`status`：读取对应安全快照并格式化，不访问正文或网络。
- `review`：用 `mode_override="plan"` 发送固定提示词，不改变 `current_mode`。
- `new`：调用 `new_session`；CLI 更新会话来源、清空最近 Token，模式保持不变。

固定 review 提示要求 Agent 先调用 `read_git_changes`，按需用读文件和搜索工具核对上下文，只报告可操作的缺陷、回归、安全问题和测试缺口，按严重度给出文件定位，不修改文件；无发现时明确说明。

**覆盖：** F5、F9—F20，N2、N3、N6、N7。

### 命令补全

**位置：** `src/mycode/commands/completion.py`

**职责：** 将 Registry 的纯候选规则适配成 `prompt_toolkit.completion.Completer`。

**候选规则：**

1. 只检查光标前文本；不是单个斜杠命令词或已经进入参数区时返回空。
2. fragment 完整匹配非隐藏别名时，只返回该别名对应的规范命令。
3. 否则只用可见规范名称做前缀匹配，不把别名作为独立菜单项。
4. 候选按注册顺序返回；隐藏命令始终过滤。
5. Completion 的替换范围覆盖当前完整命令词，插入 `/<name> `；display meta 使用描述和参数提示。

CLI 使用 `complete_while_typing=False` 和列式菜单，让 Tab 触发：一个候选直接补全，多个候选打开菜单。测试通过 `Document` 与 PipeInput/DummyOutput 验证候选和中文宽字符行为。

**覆盖：** F8、F19、F20，N1、N7、N9。

### 终端 `CommandUI` 与输入循环

**位置：** `src/mycode/cli.py`

**职责：** 实现 `CommandUI`，组合领域状态，维护模式和最近 Token，复用 Agent 事件渲染。

CLI 将现有 `_run_interactive` 拆成三个聚焦部分：PromptSession 输入循环、输入路由/命令分发、单轮 Agent 事件渲染。生产 `TerminalCommandUI.send_user_message` 根据 `mode_override or current_mode` 构造 `AgentRequest`，同步调用单轮渲染；普通输入和 `/review` 因而复用同一取消与错误处理路径。

`current_mode` 初始为 `default`，只由 `plan/do` 修改。`do` 生成 `mode="default"` 的请求；Agent 内部仍保留旧 `mode="do"` 的兼容支持，避免扩大迁移范围。

终端只创建一个 `PromptSession`。`bottom_toolbar` 使用可调用文本读取 `current_mode` 并返回 `[DEFAULT]` 或 `[PLAN]`。`refresh_status` 在应用活动时请求重绘；命令执行发生在一轮 prompt 返回之后时，下一轮 prompt 也会立即使用新值。

`clear_screen` 使用 Prompt Toolkit 的终端清屏能力，不触碰 Agent、会话、上下文、Token 或模式。Ctrl+C 等待输入时退出进程、Agent 执行时取消本轮、Ctrl+D 退出的既有语义保持。

**覆盖：** F6、F7、F11—F13、F17、F18、F21，N3、N8、N9。

### 上下文与 Agent 状态

**位置：** `src/mycode/context/manager.py`、`src/mycode/agent/runner.py`

`ContextManager.status(template)` 只用当前 entries、summary、boundary 和 estimator 构建临时请求并估算，不开启存储 transaction、不卸载内容、不调用摘要服务、不改变 anchor 或熔断状态。

`AgentRunner.context_status(mode)` 使用该模式对应的 Registry 和提示模板生成 `ContextStatus`。`AgentRunner.compact(mode)` 改为显式接受当前持久模式，避免最近一次 `/review` 的单次 plan 覆盖污染后续压缩模式；缺省参数保留现有测试和内部兼容。

会话 ID 从当前 `SessionJournal` 读取，消息数从 ContextManager 当前消息读取。CLI 单独保存 `origin`；恢复启动为 `restored`，新启动和 `/new` 后为 `new`。

**覆盖：** F10、F12—F14、F17，N2、N7、N8。

### 记忆状态

**位置：** `src/mycode/memory/models.py`、`src/mycode/memory/worker.py`

Worker 增加锁内 `status()`：`_jobs` 非空即 `busy`，数量为 queued + active 的任务总数；查询不 drain、不等待、不取消。MemoryStore 继续通过现有 `list_notes` 校验后计数，CLI 只读取 count 和 `root_for(scope) / "index.md"`。

**覆盖：** F15、F17，N6、N7。

### 权限状态

**位置：** `src/mycode/permissions/service.py`、`src/mycode/cli.py`

PermissionService 增加线程安全的 `session_rule_count` 只读属性，不暴露 `_session_rules` 内容。CLI 使用已经加载的 PermissionConfigSet、标准三层路径、路径存在性、CLI `--permission-mode` 参数和 session count 形成状态：

- 优先级固定显示 `session > local > project > user`。
- `loaded` 表示对应配置文件在成功加载后存在；session 没有路径。
- mode source 为 `cli`、`local`、`project`、`user` 或 `default`，按现有生效顺序推导。
- 只显示规则数量，不显示表达式。

**覆盖：** F16、F17，N6、N7。

### 压缩 Token 传播

**位置：** `src/mycode/context/summary.py`、`src/mycode/context/manager.py`、`src/mycode/context/models.py`

SummaryService 按现有 StreamCollector 语义保存最后一个 `token_usage` 事件。成功解析后写入 SummaryOutput；工具调用违规或格式校验失败时把已收到的用量附到 SummaryFailure。ContextManager 在成功或失败 CompactionReport 中继续传播；在根本没有摘要请求、或 Provider 在统计前失败时保持 `None`。

该改动不改变摘要选择、历史回滚、熔断、预算或上下文卸载算法。

**覆盖：** F10、F17，N2、N8。

### `read_git_changes` 专用只读工具

**位置：** `src/mycode/tools/git.py`

工具 schema 是不允许额外字段的空对象。运行时再次拒绝任何非空 arguments。它使用 `subprocess.run` 的参数数组、`shell=False` 和工作区 cwd，依次执行：

```text
git status --short --untracked-files=all
git diff --no-ext-diff --no-textconv --
git diff --cached --no-ext-diff --no-textconv --
```

三次调用共享 `ToolContext.timeout_seconds` 的 monotonic 截止时间。结果按 `status`、`unstaged_diff`、`staged_diff` 组织；未跟踪文件只出现在 status 中，Agent 再用 `read_file` 读取。非 Git 工作区、Git 不存在、非零退出和超时转成不含环境或配置细节的结构化错误。

显示视图遵守 `max_output_chars`，完整视图沿用现有 ToolExecutionResult 与 ContextManager 卸载机制，避免把大差异直接留在下一轮上下文。工具在默认 Registry 中先于 MCP 注册，并加入 `READ_TOOLS`，因此 Plan Registry 可用、只读批次可并发，且绕过权限规则和人工审批。

工具描述明确仅用于读取当前工作区未提交变更，不接受 revision、路径、Git 参数或任意命令。

**覆盖：** F18、AC17，N2、N5—N8。

## 模块交互

### 启动

```text
main(argv)
  → 解析 CLI 参数
  → create_default_command_registry()
       → 任一冲突：安全错误 + return 1
  → load_config / create_provider / create_default_tool_registry
  → PermissionConfigLoader / MCP discovery / Session restore
  → AgentRunner
  → TerminalCommandUI
  → CommandCompleter + PromptSession(bottom_toolbar=mode)
  → 输入循环
```

### 普通消息

```text
raw input
  → InputRouter(kind=plain)
  → CommandUI.send_user_message(text, current_mode)
  → AgentRunner.run
  → token_usage event 更新最近 Token
  → 既有事件渲染、会话记录和记忆提交
```

### 模式切换

```text
/plan 或 /do
  → Dispatcher
  → switch_mode(plan/default)
  → refresh_status
  → 下一轮 toolbar 显示 [PLAN]/[DEFAULT]
  → 不构造 AgentRequest，不写会话
```

### Review

```text
/review
  → 固定 REVIEW_PROMPT
  → send_user_message(mode_override=plan)
  → readonly Registry 包含 read_git_changes
  → Agent 读取 status/diff
  → 按需 read_file/find_files/search_code
  → 只输出 findings
  → 持久模式不变
```

### 状态命令

```text
/session | /memory | /permission | /status
  → 拉取本地不可变快照
  → 只格式化批准字段
  → display_message
  → 不调用 Provider/MCP，不写会话
```

### Compact

```text
/compact
  → AgentRunner.compact(current_mode)
  → ContextManager manual compaction
       ├─ 无摘要：本地报告
       └─ 摘要：Provider → token_usage → CompactionReport
  → 显示报告
  → 如有 usage，更新最近 Token
  → 不进入 Agent Loop、不写用户消息
```

## 文件组织

### 新建文件

| 文件 | 职责 |
|---|---|
| `src/mycode/commands/__init__.py` | 导出命令公共接口 |
| `src/mycode/commands/models.py` | 命令、分流结果和安全状态快照 |
| `src/mycode/commands/interfaces.py` | `CommandUI` 协议与命令错误 |
| `src/mycode/commands/registry.py` | 注册、冲突检测、查找和补全候选 |
| `src/mycode/commands/router.py` | 输入分类、命令解析和统一分发 |
| `src/mycode/commands/builtins.py` | 可见命令、隐藏 `/new`、固定 review 提示和输出格式 |
| `src/mycode/commands/completion.py` | Prompt Toolkit 补全适配器 |
| `src/mycode/tools/git.py` | 固定参数的只读 Git 变更工具 |
| `tests/test_command_registry.py` | 元数据、冲突、别名和顺序 |
| `tests/test_command_router.py` | 空白、普通消息、退出、解析和异常 |
| `tests/test_command_builtins.py` | 十一条命令及三种执行类型 |
| `tests/test_command_completion.py` | 单匹配、多匹配、别名优先和隐藏过滤 |
| `tests/test_tools_git.py` | Git 状态、差异、超时、非仓库和输出边界 |

### 修改文件

| 文件 | 职责 |
|---|---|
| `src/mycode/cli.py` | 启动期命令目录、终端 CommandUI、PromptSession、分流和状态栏 |
| `src/mycode/agent/runner.py` | 指定模式的无副作用上下文快照及压缩模式 |
| `src/mycode/context/models.py` | 上下文状态及压缩摘要 Token 字段 |
| `src/mycode/context/manager.py` | 当前上下文估算快照和 Token 传播 |
| `src/mycode/context/summary.py` | 收集摘要调用 Token |
| `src/mycode/memory/models.py` | Worker 状态快照 |
| `src/mycode/memory/worker.py` | 非阻塞查询忙闲和任务数 |
| `src/mycode/permissions/service.py` | 安全暴露会话规则数量 |
| `src/mycode/tool_safety.py` | 将 `read_git_changes` 纳入专用只读工具 |
| `src/mycode/tools/registry.py` | 默认注册只读 Git 工具 |
| `src/mycode/tools/descriptions.py` | Git 工具使用约束 |
| `src/mycode/tools/__init__.py` | 导出新工具 |
| `tests/test_cli.py` | PromptSession、状态栏、分流和回归场景 |
| `tests/test_agent_runner.py` | 持久模式请求、review 覆盖和状态快照 |
| `tests/test_context_manager.py` | 无副作用估算与压缩 Token |
| `tests/test_context_summary.py` | 摘要成功/失败 Token 传播 |
| `tests/test_memory_worker.py` | 非阻塞后台状态 |
| `tests/test_permissions_service.py` | 会话规则计数不暴露规则正文 |
| `tests/test_agent_tools.py` | Plan 模式包含 Git 读取工具 |
| `tests/test_tools_registry.py` | 默认工具注册回归 |
| `tests/test_tool_descriptions.py` | Git 工具描述约束 |
| `README.md` | 可见命令、别名、模式和隐藏兼容行为 |

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 命令与 Agent 工具 | 使用独立注册中心 | 生命周期、参数格式和执行对象不同，避免错误复用 |
| 冲突处理 | 启动最前段构建目录，异常转为非零退出 | 在 Provider/MCP 工作前失败，同时给出冲突项 |
| 大小写 | 对命令词使用 `lower()` | 与批准需求一致；内置标识均为 ASCII |
| 命令参数 | 只做一次空白切分，处理函数自行校验 | 保留原始参数，不引入 shell 语法 |
| 模式状态 | 由终端 CommandUI 单一持有 | 状态栏、普通输入和命令切换共享唯一来源 |
| `/do` | CLI 映射到 `default`，保留 Agent 对旧 `do` 的兼容 | 满足双状态语义并降低无关回归 |
| 输入组件 | 复用一个 PromptSession | 补全器和动态状态栏需要跨轮次共享状态 |
| 补全 | Registry 产候选，Prompt Toolkit 只渲染 | 规则可无终端测试，UI 库不侵入注册层 |
| 状态查询 | 拉取不可变快照 | 无需事件总线，确保查询无副作用、不联网 |
| Token 语义 | 最近完成的 Provider 请求，不累计 | Provider 字段不总是完整，避免错误累加 |
| `/review` 数据源 | 专用只读 Git 工具 | 保持固定提示词和只读保证，同时定位变更 |
| Git 执行 | 固定数组、`shell=False`、禁用 external diff/textconv | 防止命令注入和 Git 配置触发外部处理器 |
| Git 超时 | 三次调用共享总截止时间 | 整个工具调用不超过既有时间边界 |
| 大型 Git 差异 | 沿用展示/完整双视图和上下文卸载 | 避免巨大差异直接留在模型上下文 |
| 命令异常 | 安全预期错误；未知 Exception 只显示类型；中断上抛 | 交互可恢复且保留 Ctrl+C 语义 |
| 隐藏命令 | 可解析、可显式帮助，不枚举、不补全 | 保留 `/new` 兼容且不扩大可见集合 |

## 需求覆盖

| 需求 | 设计覆盖 |
|---|---|
| F1—F2 | CommandSpec、CommandRegistry、启动期 fail-fast |
| F3—F4 | InputRouter、错误路由、参数验证 |
| F5—F7 | CommandUI、类型映射、Dispatcher、CLI 适配器 |
| F8—F9 | completion_candidates、CommandCompleter、help handler |
| F10 | 显式模式 compact、CompactionReport Token 传播 |
| F11 | TerminalCommandUI.clear_screen |
| F12—F13 | CommandUI 单一持久模式、动态 bottom toolbar |
| F14—F17 | Session/Memory/Permission/Application 安全状态快照 |
| F18 | 固定 review 提示、单次 plan、read_git_changes |
| F19—F20 | 固定别名表、隐藏 new 登记与过滤 |
| F21 | InputRouter exit 分支与 CLI 控制流 |
| N1—N4 | 确定性 Registry/Router、UI Protocol、无 Agent 本地路径 |
| N5—N7 | 异常边界、安全快照、纯本地状态查询 |
| N8—N10 | 兼容路径、Prompt Toolkit Unicode、分层自动化测试 |

依赖方向为 `cli → commands → context/types`，以及 `cli → agent/memory/permissions`；领域模块不导入命令内置实现或终端适配器。命令包不导入 CLI，Git 工具不导入命令包，因此不存在新循环依赖。
