# MewCode 子 Agent 委派 Plan

## 架构概览

### 1. Agent 定义目录

新增独立的 `mycode.agents` 包，负责角色解析、来源扫描、优先级合并、模型档位校验、诊断和热更新。它与现有 Skill 目录并列，不复用 Skill 的激活语义。

运行时持有不可变角色快照。每个任务创建时取得角色和工具策略快照，之后的热更新只影响新任务。

### 2. 统一委派入口

`Agent` 与 `Task` 作为内置控制工具注册一次，名称、schema 和注册顺序固定。`Agent` 的描述可从当前角色快照生成角色列表，但 schema 不变化。

两个控制工具由现有权限系统视为系统能力，本身不触发业务权限审批；子 Agent 实际调用的文件、命令、MCP 等工具仍逐次经过工具策略、Hook 和独立权限服务。

控制工具自行管理等待边界，不受普通工具的 10 秒执行超时包裹：

- `Agent` 可等待定义式任务完成、前台超时或 `Ctrl+B`。
- `Task wait` 只在配置和硬上限内等待。
- 显式后台与 Fork 创建后立即返回。

### 3. 父请求快照边界

主 `AgentRunner` 在每次 Provider 请求发送前，冻结本次实际 `ChatRequest` 和有效 `ToolRegistry`。执行模型返回的工具批次时，该快照通过委派运行时暴露给 `Agent` 工具。

Fork 任务复制的正是本次已发送请求，因此自然排除尚未写入历史的 Assistant 文本、本次 `Agent` 调用及同批其他调用。

Fork 子 Agent：

1. 导入父快照中的消息；
2. 追加子任务 user 消息；
3. 首次请求原样复用父快照的 system、动态 system、可选 system、工具定义、工具顺序和缓存标记；
4. 首次请求只做预算检查，不执行卸载或摘要；若追加子任务后超预算，则结构化失败，而不改写缓存前缀；
5. 后续轮次继续使用冻结的 system 与工具模板，并使用自己的消息和上下文管理状态。

### 4. 子 Agent 执行器

子任务统一由 `ChildAgentRunner` 创建一次性 `AgentRunner`：

- 定义式：空白消息历史、标准 MewCode 基础提示、项目指令和角色正文；不继承父历史、激活 Skill、长期记忆或主会话日志。
- Fork 式：使用冻结父请求模板与父消息快照，不重新构建父提示。
- 两者都使用独立的消息上下文、上下文文件目录、取消令牌、权限服务、权限审计和 Token 累加器。
- 子运行不写主 SessionJournal，也不触发主会话记忆提取。
- 子运行结束后只提交规范化终态、最终 Assistant 文本和累计用量。

子 Agent 使用现有“模型不再调用工具即完成”的循环语义；角色 `max_iterations` 替换子运行的迭代上限。

### 5. 后台任务管理器

所有子任务从创建起就由 `AgentTaskManager` 托管。“前台”只表示 `Agent` 工具正在等待该任务，不代表任务运行在主调用栈中。

管理器使用受锁保护的显式 FIFO 队列和固定数量的 daemon worker：

- 默认 4 个 worker、最多排队 32 项；
- 仅在存在运行槽时才把任务交给 worker，避免执行器内部无界排队；
- 每个任务只有一次合法终态转换；
- 前台等待从提交时开始计时，因此包含排队时间；
- 超时或 `Ctrl+B` 只原子地把投递方式改为后台，不取消、不复制任务；
- `/new` 和退出通过任务取消令牌终止排队项并请求运行项停止；
- 退出有界等待后仍未停止的 daemon worker 不阻塞进程退出。

### 6. 多层工具策略

新增与权限服务分离的 `ChildToolPolicy`，在每次工具实际执行前重新判定：

1. 全局禁止 `Agent`、`Task`、`load_skill`；
2. 定义式应用创建时冻结的角色白名单与黑名单，黑名单优先；
3. 主 Agent 处于 Plan Mode 时，定义式进一步限制为只读工具；
4. 任务已进入后台时，再与后台白名单求交；
5. 通过后才进入共享 Hook 和任务独立权限服务。

定义式请求展示经过策略过滤的工具列表。Fork 为保持缓存前缀，始终展示父快照的原工具列表，但执行前仍经过同一策略，因此禁止项只会返回结构化失败。

若任务在一次 Provider 请求期间切到后台，已经开始执行的工具不回滚；尚未执行的工具会按最新后台状态重新判定。

### 7. 权限隔离

每个任务从全局权限配置派生新的 `PermissionService`：

- 不复制父 Agent 的 session rules；
- 使用非交互拒绝处理器；
- `inherit` 继承主进程当前有效模式；
- `default` 或 `strict` 覆盖子任务模式；
- 每次判定向任务级审计器记录工具名、允许/拒绝和安全原因码，不在任务摘要中暴露原始参数或敏感目标。

角色白名单只控制可见性和调用资格，不构成权限授权。

### 8. 共享基础设施

新增线程安全的 `ProviderPool`。主 Agent、子 Agent、摘要和既有独立 Skill 按模型 ID 取得 Provider；同一协议、地址和凭据共享一个可并发使用的 HTTP 客户端。模型档位只选择池中的具体模型，不新建独立基础设施。CLI 退出时由池统一关闭客户端。

Hook 运行时拆成共享引擎与独立作用域：

- 规则快照、外部动作执行器、once 状态和诊断出口共享；
- 主 Agent 和每个子 Agent 各自拥有 turn、prompt 队列和 prompt lease；
- 子 Agent Hook 事件复用所属主会话 ID；
- Fork 首次请求为保持前缀不注入子作用域新产生的 Hook prompt，这些 prompt 延后到第二次请求；其他 Hook 动作仍正常执行。

工作区文件系统和工具对象继续共享，但每个子 Agent 使用独立上下文存储目录。

### 9. 结果投递与任务管理

任务记录保留完整的有界最终文本与累计 Token 用量。后台终态产生两条相互独立的输出：

- 终端通知器即时显示任务 ID、类型、角色和终态；
- 会话收件箱保存规范化结果。

主 `AgentRunner` 在每次 Provider 请求前的安全点原子提取本会话收件箱，并把结果作为带明确边界的后台结果消息写入主上下文和 SessionJournal。若结果超过注入预览限制，消息只包含首尾预览和 `Task get` 提示；完整结果仍可通过 `Task` 获取，并由现有工具结果外置机制处理。

收件箱不会主动启动主 Agent 请求。前台同步完成的任务直接由 `Agent` 工具返回，不重复投递收件箱通知。

### 10. CLI 与生命周期

CLI 使用 prompt-toolkit 的专用前台等待控制器处理 `Ctrl+B`。等待控制器只在定义式前台任务存在时激活，完成、超时或按键后立即退出；无交互测试使用基于 Event 的等待器。

交互循环启用安全的后台输出补丁，使任务通知显示在当前输入行上方，不破坏用户正在输入的内容。

新增 `/tasks` 本地命令读取当前 Session ID 的任务快照，不调用模型。`/new` 先取消并隔离旧会话任务和收件箱，再切换 SessionJournal；CLI 退出按“取消任务 → 有界等待 → 关闭子上下文 → 关闭 Hook → 关闭 Provider/MCP”的顺序收尾。

## 核心数据结构

### AgentDefinition

```python
AgentSource = Literal["project", "user", "builtin", "plugin"]
ModelTier = Literal["inherit", "haiku", "sonnet", "opus"]
ChildPermissionMode = Literal["inherit", "default", "strict"]

@dataclass(frozen=True)
class AgentDefinition:
    name: str
    description: str
    allowed_tools: tuple[str, ...]
    denied_tools: tuple[str, ...]
    model: ModelTier
    max_iterations: int
    permission_mode: ChildPermissionMode
    system_prompt: str
    source: AgentSource
    source_id: str
    fingerprint: str
```

角色文件固定使用以下 frontmatter，所有字段必填，未知字段拒绝：

```yaml
---
name: reviewer
description: 审查当前工作区改动
allowed_tools:
  - read_file
  - find_files
  - search_code
  - read_git_changes
denied_tools: []
model: inherit
max_iterations: 8
permission_mode: strict
---
你是只读代码审查 Agent……
```

约束：

- `name` 使用小写命令名规则；
- 工具名必须精确匹配，不支持 glob；
- 白名单和黑名单不能重复或相交；
- `max_iterations` 为 1–64；
- 正文必须为非空 UTF-8 文本；
- 符号链接入口、重复 YAML key、未知工具和全局禁止工具均产生诊断；
- 空白名单表示无业务工具，而不是允许全部工具。

### AgentSnapshot

```python
@dataclass(frozen=True)
class AgentDiagnostic:
    level: Literal["warning", "error"]
    code: str
    source_id: str
    message: str

@dataclass(frozen=True)
class AgentSnapshot:
    definitions: Mapping[str, AgentDefinition]
    diagnostics: tuple[AgentDiagnostic, ...]
    fingerprint: str
```

`definitions` 使用只读映射。项目级和用户级同层重名时，该层同名候选失效并回退到下一优先级；同一插件目录内重名同样失效。不同插件目录同名时，构造参数中的目录顺序决定优先级，先注册者生效并产生覆盖诊断。

### AgentDelegationConfig

```python
@dataclass(frozen=True)
class AgentDelegationConfig:
    model_aliases: Mapping[Literal["haiku", "sonnet", "opus"], str]
    background_allowed_tools: tuple[str, ...] = (
        "read_file",
        "find_files",
        "search_code",
        "read_git_changes",
    )
    foreground_timeout_seconds: float = 30.0
    task_wait_timeout_seconds: float = 30.0
    task_wait_max_seconds: float = 300.0
    shutdown_timeout_seconds: float = 5.0
    max_concurrency: int = 4
    max_queue_size: int = 32
    inbox_preview_chars: int = 8_000
```

它作为 `AppConfig.agents` 的一部分从项目 Provider 配置读取。配置解析时执行硬边界校验：

- 并发数 1–32；
- 队列长度 0–1024；
- 所有超时为有限正数；
- 默认等待不超过最大等待；
- 注入预览为 1,000–20,000 字符；
- 工具名语法合法，工具存在性在 MCP 和控制工具注册完成后校验。

### AgentInvocation 与 TaskInvocation

```python
@dataclass(frozen=True)
class AgentInvocation:
    kind: Literal["defined", "fork"]
    prompt: str
    role: str | None
    background: bool

@dataclass(frozen=True)
class TaskInvocation:
    action: Literal["list", "get", "wait", "cancel"]
    task_id: str | None
    timeout_seconds: float | None
```

`Agent` schema 始终包含 `type`、`prompt`、`role`、`background`；`Task` schema 始终包含 `action`、`task_id`、`timeout_seconds`。跨字段限制由运行时验证，避免 Provider 对条件式 JSON Schema 支持不一致。

### ForkRequestSnapshot

```python
@dataclass(frozen=True)
class ForkRequestSnapshot:
    session_id: str
    mode: Literal["default", "plan"]
    request: ChatRequest
    registry: ToolRegistry
    request_fingerprint: str
```

`request` 和 `registry` 是本次父 Provider 请求实际使用内容的深复制快照。`request_fingerprint` 对 system、消息、工具及顺序做稳定序列化后计算，用于测试 Fork 首次请求的前缀一致性，不作为缓存命中承诺。

### ChildRunSpec

```python
@dataclass(frozen=True)
class ChildRunSpec:
    task_id: str
    session_id: str
    kind: Literal["defined", "fork"]
    prompt: str
    role: AgentDefinition | None
    model_id: str
    initial_background: bool
    parent_mode: Literal["default", "plan"]
    fork_snapshot: ForkRequestSnapshot | None
    tool_policy: ChildToolPolicy
```

任务创建时完整冻结。定义式要求 `role`，Fork 要求 `fork_snapshot`，两者不能同时存在。

### TaskRecord 与 TaskSnapshot

```python
TaskStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
DeliveryMode = Literal["foreground", "background"]

@dataclass
class TaskRecord:
    spec: ChildRunSpec
    status: TaskStatus
    delivery_mode: DeliveryMode
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested: bool
    outcome: TaskOutcome | None
    cancellation: CancellationToken
    done: threading.Event
    notification_attempted: bool

@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    session_id: str
    kind: Literal["defined", "fork"]
    role: str | None
    status: TaskStatus
    delivery_mode: DeliveryMode
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested: bool
    token_usage: TokenUsage | None
    failure_reason: str
```

`TaskRecord` 只能在管理器锁内修改。对外只返回 `TaskSnapshot`，不暴露 prompt、工具参数、原始权限目标或可变对象。

状态转换固定为：

```text
queued ──→ running ──→ completed
   │           ├─────→ failed
   │           └─────→ cancelled
   └────────────────→ cancelled

foreground ──→ background
```

执行状态和投递状态正交；`background` 不可切回 `foreground`。

### TaskOutcome

```python
@dataclass(frozen=True)
class PermissionAuditEntry:
    occurred_at: datetime
    tool_name: str
    allowed: bool
    reason_code: str

@dataclass(frozen=True)
class TaskOutcome:
    status: Literal["completed", "failed", "cancelled"]
    result: str
    failure_reason: str
    token_usage: TokenUsage | None
    permission_audit: tuple[PermissionAuditEntry, ...]
```

Token 累加覆盖每轮 Provider usage 和上下文摘要 usage，包括 input、output、total、cache read、cache creation 与 cache unavailable。

### InboxItem

```python
@dataclass(frozen=True)
class InboxItem:
    task_id: str
    session_id: str
    kind: Literal["defined", "fork"]
    role: str | None
    status: Literal["completed", "failed", "cancelled"]
    result_preview: str
    result_truncated: bool
    failure_reason: str
    token_usage: TokenUsage | None
    finished_at: datetime
```

收件箱不复制权限审计和 prompt。完整结果保留在任务终态中；预览超限时保留首尾并提示调用 `Task get`。

## 核心接口

### AgentCatalog

```python
class AgentCatalog:
    def load_initial(
        self,
        known_tools: Collection[str],
        model_aliases: Mapping[str, str],
    ) -> AgentSnapshot: ...

    def refresh(
        self,
        current: AgentSnapshot,
        known_tools: Collection[str],
        model_aliases: Mapping[str, str],
    ) -> AgentRefreshReport: ...
```

构造参数包括 workspace、用户目录覆盖、内置文本和有序插件目录。状态指纹覆盖项目、用户和插件目录。

### AgentRoleRuntime

```python
class AgentRoleRuntime:
    @property
    def snapshot(self) -> AgentSnapshot: ...

    def publish(self, snapshot: AgentSnapshot) -> None: ...

    def definition(self, name: str) -> AgentDefinition: ...

    def catalog_prompt(self) -> str: ...
```

内部使用 `RLock`。`Agent` 工具描述调用 `catalog_prompt()`，但工具对象本身不重新注册。

### ParentRequestBridge

```python
class ParentRequestBridge:
    def publish(self, snapshot: ForkRequestSnapshot) -> None: ...
    def current(self, session_id: str) -> ForkRequestSnapshot: ...
    def clear(self, request_fingerprint: str) -> None: ...
```

只允许主 `AgentRunner` 在 Provider 请求到工具批次之间发布快照。无活动请求、Session 不匹配或快照已清除时，Fork 创建返回结构化失败。

### ChildToolPolicy

```python
@dataclass(frozen=True)
class ToolPolicyDecision:
    allowed: bool
    reason_code: str
    message: str

class ChildToolPolicy:
    def visible_registry(
        self,
        registry: ToolRegistry,
        *,
        background: bool,
    ) -> ToolRegistry: ...

    def authorize_call(
        self,
        tool_name: str,
        *,
        background: bool,
    ) -> ToolPolicyDecision: ...
```

可见性过滤和执行前判定使用同一规则源。Fork 只使用 `authorize_call`，不改变冻结的可见工具列表。

### ChildPermissionFactory

```python
class ChildPermissionFactory:
    def create(
        self,
        mode: ChildPermissionMode,
        audit_sink: Callable[[PermissionAuditEntry], None],
    ) -> PermissionService: ...
```

每次调用创建空 session rule 列表，并使用非交互审批处理器。全局配置层为不可变共享输入，不共享服务实例。

### ProviderPool

```python
class ProviderPool:
    def get(self, model_id: str) -> LLMProvider: ...
    def close(self) -> None: ...
```

内部按模型 ID 缓存 Provider，所有 Provider 共享一个线程安全 HTTP client。`close()` 幂等且只由 CLI 根生命周期调用。

### HookScope

```python
class HookRuntime:
    def fork_scope(self, session_id: str, scope_id: str) -> HookScope: ...

class HookScope:
    def begin_turn(self, mode: str, input_kind: str) -> int: ...
    def end_turn(self, stop_reason: str) -> None: ...
    def reserve_prompts(self) -> HookPromptLease: ...
    def close(self) -> None: ...
```

`HookScope.close()` 只清理该作用域的 prompt 与 lease，不关闭共享动作执行器。

### ChildAgentExecutor

```python
class ChildAgentExecutor:
    def run(
        self,
        spec: ChildRunSpec,
        cancellation: CancellationToken,
    ) -> TaskOutcome: ...
```

职责是构造子 `AgentRunner`、累计事件用量、提取最后一个无工具调用的 Assistant 文本、生成安全失败原因，并始终关闭子 ContextStore 和 HookScope。

### AgentTaskManager

```python
class AgentTaskManager:
    def submit(self, spec: ChildRunSpec) -> TaskSnapshot: ...

    def finish_foreground_wait(
        self,
        task_id: str,
        reason: Literal["completed", "timeout", "manual"],
    ) -> ForegroundWaitResult: ...

    def list_tasks(self, session_id: str) -> tuple[TaskSnapshot, ...]: ...
    def get_task(self, session_id: str, task_id: str) -> TaskDetails: ...
    def wait_task(
        self,
        session_id: str,
        task_id: str,
        timeout_seconds: float,
    ) -> TaskDetails: ...
    def cancel_task(self, session_id: str, task_id: str) -> TaskSnapshot: ...

    def take_inbox(self, session_id: str) -> tuple[InboxItem, ...]: ...
    def cancel_session(self, session_id: str, *, clear_inbox: bool) -> int: ...
    def shutdown(self, timeout_seconds: float) -> ShutdownReport: ...
```

`finish_foreground_wait` 在锁内解决完成与切后台的竞争：若任务已经终止则返回同步结果；否则切为后台并返回任务 ID。后台终态的通知与收件箱投递也在同一锁内取得唯一发送权。

### ForegroundWaiter

```python
class ForegroundWaiter(Protocol):
    def wait(
        self,
        task_id: str,
        done: threading.Event,
        timeout_seconds: float,
    ) -> Literal["completed", "timeout", "manual"]: ...
```

提供 `EventForegroundWaiter` 和 `PromptToolkitForegroundWaiter` 两种实现。

### AgentTool 与 TaskTool

```python
class AgentTool:
    manages_own_timeout = True

class TaskTool:
    manages_own_timeout = True
```

`ToolExecutor` 识别 `manages_own_timeout`，在当前线程直接执行这些已自行限时的控制工具；其他工具继续使用现有超时执行器。

`AgentTool` 依赖角色运行时、父请求桥、任务管理器和前台等待器。`TaskTool` 只依赖任务管理器与当前 Session ID supplier。

### AgentRunner 扩展点

`AgentRunner` 新增以下可选依赖：

```python
request_bridge: ParentRequestBridge | None
task_inbox: TaskInbox | None
child_profile: ChildRunnerProfile | None
tool_policy: ChildToolPolicy | None
context_store: ContextStore | None
hook_scope: HookScope | None
```

主运行器发布请求快照并注入收件箱；子运行器使用冻结模板、独立存储和调用策略。缺少这些依赖时保持当前行为。

## 模块设计

### 角色定义模块

**职责：**

- 严格解析角色 frontmatter 与正文；
- 扫描项目、用户、内置及有序插件来源；
- 校验工具名、模型映射、同名覆盖及安全字段；
- 生成不可变快照、指纹与脱敏诊断；
- 在主请求前检测热更新。

**依赖：** 工具名称注册表、模型档位配置。

**不依赖：** AgentRunner、任务管理器、权限服务。解析层保持纯函数，便于测试。

### 控制工具模块

**职责：**

- 固定注册 `Agent`、`Task`；
- 验证类型参数和跨字段约束；
- 将委派请求转换成冻结的 `ChildRunSpec`；
- 将管理请求限制在当前 Session ID；
- 统一序列化任务状态、结果和用量。

`Agent`、`Task` 被加入系统工具集合，但子 Agent 策略在权限服务之前硬拒绝两者。它们的注册位置固定在现有业务工具和 MCP 工具之后、`load_skill` 之前，后续角色更新不改变顺序。

### 父请求桥接模块

**职责：**

- 在主请求实际发给 Provider 前深复制 `ChatRequest` 和有效 Registry；
- 生成稳定请求指纹；
- 在当前工具批次结束后撤销活动快照；
- 拒绝跨 Session、过期或缺失快照的 Fork。

桥接器只保存一个当前主请求快照，因为当前 CLI 同一主会话一次只运行一个主 Agent turn。子任务持有自己的不可变副本，不受桥接器清理影响。

### 子运行模块

**职责：**

- 为定义式或 Fork 式构造一次性运行器；
- 创建独立 ContextManager、ContextStore、文件读取缓存、PermissionService、HookScope 和 TokenAccumulator；
- 执行到自然完成、限制、取消或失败；
- 将异常转成不含敏感内容的 `TaskOutcome`；
- 无论成功失败都清理子上下文文件和 Hook 作用域。

文件读取缓存采用任务级 `FileReadCache`。缓存键包含解析后的路径与文件 stat 标识；每次命中前重新检查 stat，写入或编辑后使当前任务缓存失效。父 Agent 和每个子 Agent 使用不同缓存对象，因此不会共享缓存内容；工作区文件本身仍然共享。

### 工具策略与执行模块

**职责：**

- 定义式生成过滤后的可见 Registry；
- Fork 保留冻结 Registry，但在执行前重新授权；
- 对后台状态采用动态白名单；
- 对策略拒绝生成 `reason_code` 稳定的结构化 ToolResult；
- 通过后再调用 Hook 和权限服务。

执行顺序固定为：

```text
工具存在性
→ 子 Agent 全局禁令
→ 角色白名单/黑名单
→ Plan Mode 只读限制
→ 当前是否后台及后台白名单
→ Hook tool_before
→ 独立权限服务
→ 工具执行
→ Hook tool_after
→ 权限审计
```

策略拒绝也触发 `tool_after`，结果来源标记为 `policy`。它不会进入人工审批，也不会执行工具。

普通工具继续使用现有线程超时。控制工具声明自行管理超时，避免外层 10 秒超时提前返回后内部任务仍失去关联。

### 权限派生模块

**职责：**

- 从不可变的用户、项目、本地权限层构造任务级服务；
- 清空 session rules；
- 根据角色选择有效模式；
- 使用始终拒绝的非交互 ApprovalHandler；
- 对每次判定写入脱敏任务审计。

`default` 模式中未命中规则的操作会得到与“无交互审批可用”对应的稳定拒绝原因，而不是伪装成用户主动拒绝。

### Provider 池模块

**职责：**

- 按具体模型 ID 返回轻量 Provider；
- 在相同协议和端点下共享线程安全 HTTP client、连接池和凭据配置；
- 支持主 Agent、子 Agent、摘要、记忆和独立 Skill 并发请求；
- 汇总关闭并保证幂等。

Provider 不保存请求级流状态；工具增量、SSE 解析器和响应对象仍局限在各次 `stream_chat` 调用中。共享的是传输连接池，不共享消息或 Token 状态。

### Hook 作用域模块

**职责：**

- 保留一份 Hook 规则和动作执行器；
- 为主 Agent 及每个子任务分配独立事件工厂、turn 状态、prompt 队列和 lease；
- 在共享锁下维护 `once` 消费状态；
- 保证并发事件 payload 不串 Session、turn 或任务；
- 单个作用域关闭不关闭全局动作执行器。

Hook payload 增加可选 `agent_scope`：

```json
{
  "kind": "main | defined | fork",
  "task_id": "...",
  "role": "reviewer"
}
```

主 Agent 保持兼容；条件解析器不要求使用新字段。Fork 首轮产生的 prompt action 延迟到第二轮，确保首次请求前缀不变。

### 任务管理模块

**职责：**

- 生成不可猜测且进程内唯一的任务 ID；
- 管理显式 FIFO、daemon worker、并发槽和队列上限；
- 维护合法状态转换；
- 实现等待、查询、取消、Session 清理和进程收尾；
- 唯一决定是否生成终端通知与收件箱条目。

任务结果只保存在内存。任务列表按创建时间排序；任务终态记录保留到所属 Session 被 `/new` 清理或进程退出。

### 收件箱模块

**职责：**

- 按 Session ID 隔离待处理结果；
- 保证每个后台任务最多投递一次；
- 对结果生成有界首尾预览；
- 在主 Agent 下一次请求开始时原子取走。

为避免新增不被 Provider 支持的消息角色，主运行器将待处理结果与当前用户输入组合成一个有边界的 user 消息：

```text
<background-task-results>
[task ... 的规范化结果]
</background-task-results>

<current-user-message>
[用户本次输入]
</current-user-message>
```

该组合消息写入 ContextManager 与 SessionJournal，因此结果可以随现有会话恢复；Hook 的 `message_received` 仍只接收用户原始输入，避免把后台结果误记为用户行为。收件箱注入失败时项目重新入队，不丢失结果。

### CLI 集成模块

**职责：**

- 注册 `/tasks`；
- 在主请求前刷新角色目录；
- 使用 prompt-toolkit 小型等待 Application 捕获 `Ctrl+B`；
- 通过安全终端输出显示异步通知；
- `/new` 和退出时协调任务清理顺序；
- 输出角色诊断和任务关闭警告。

`/tasks` 只展示摘要，不展示 prompt、最终全文、权限目标或工具参数。

## 模块交互

### 定义式同步完成

```text
主 Provider 返回 Agent(type=defined)
→ AgentTool 校验角色并冻结定义、模型、工具策略
→ TaskManager 创建 queued 任务
→ worker 将其置为 running
→ ChildAgentExecutor 从空白历史运行
→ TaskManager 写入 completed
→ ForegroundWaiter 观察到完成
→ AgentTool 原子领取同步结果
→ ToolResult 回灌主 Agent
```

同步完成不发送终端后台通知，也不写收件箱。

### 定义式进入后台

```text
任务提交
→ AgentTool 前台等待
→ 显式 background / 排队与运行累计超时 / Ctrl+B
→ TaskManager 原子切换 delivery_mode=background
→ AgentTool 返回 task_id 与当前状态
→ 原任务继续排队或运行
→ 到达唯一终态
→ 通知器显示一次
→ Inbox 写入一次
→ 主 Agent 空闲时不调用模型
→ 下一次用户请求开始时注入并持久化结果
```

若完成与切后台并发发生，锁内先发生的状态决定返回路径：

- 已完成后领取：作为同步结果返回，不通知；
- 已切后台后完成：按后台结果通知和投递。

### Fork 执行

```text
主请求准备完成
→ ParentRequestBridge 发布实际请求快照
→ Provider 返回 Agent(type=fork)
→ AgentTool 从桥接器复制快照并立即提交后台
→ Fork 子运行导入父 messages
→ 追加子任务 user 消息
→ 首次 Provider 请求复用冻结 system 和 tools
→ 后续运行使用子上下文
→ 工具调用执行前按 Fork 策略硬限制
→ 终态通知并投递收件箱
```

Fork 首轮只做估算，不触发摘要、卸载、Hook prompt 注入或工具重排。超预算时任务失败并报告明确原因。

### Task 管理

```text
Task list
→ 当前 Session 过滤后的 TaskSnapshot 列表

Task get
→ 当前 Session 校验
→ 返回状态、完整有界结果、失败原因和用量

Task wait
→ 校验 timeout ≤ 配置硬上限
→ Event 有界等待
→ 返回终态或当前运行状态

Task cancel
→ queued：从 FIFO 移除并置 cancelled
→ running：设置 CancellationToken
→ terminal：幂等返回现状
```

`Task` 被 Fork 看见但策略硬拒绝；定义式 Registry 中不存在该工具。

### `/new` 与退出

```text
/new
→ 冻结旧 Session ID
→ cancel_session(clear_inbox=true)
→ 有界等待旧 Session 运行项
→ 清理旧子 ContextStore
→ 切换主 SessionJournal 与主 ContextManager
→ 清除父请求桥
→ 开始新 Hook Session

CLI 退出
→ TaskManager.shutdown()
→ 取消 queued/running
→ 有界等待并汇总未结束项
→ 关闭所有子作用域与上下文
→ 关闭主 Agent/Journal/Memory
→ 关闭 Hook 共享动作执行器
→ 关闭 ProviderPool
→ 关闭 MCPManager
```

已执行的文件修改不会回滚。崩溃时没有任务恢复逻辑。

## 文件组织

### 新建文件

| 文件 | 职责 |
|---|---|
| `src/mycode/agents/__init__.py` | 导出子 Agent 公共类型与运行入口 |
| `src/mycode/agents/models.py` | 角色、快照、调用、任务、结果、收件箱和审计模型 |
| `src/mycode/agents/parser.py` | 严格解析 Markdown + YAML frontmatter |
| `src/mycode/agents/catalog.py` | 多来源扫描、优先级合并、诊断和热更新指纹 |
| `src/mycode/agents/runtime.py` | 线程安全发布及查询角色快照 |
| `src/mycode/agents/policy.py` | 可见工具过滤和执行时多层策略判定 |
| `src/mycode/agents/permissions.py` | 派生独立权限服务与记录脱敏审计 |
| `src/mycode/agents/provider_pool.py` | 按模型复用 Provider 和共享 HTTP 连接池 |
| `src/mycode/agents/bridge.py` | 冻结、发布和撤销父请求快照 |
| `src/mycode/agents/runner.py` | 构造并运行定义式/Fork 式一次性子 Agent |
| `src/mycode/agents/tasks.py` | FIFO、daemon worker、状态机、等待、取消、收件箱和关闭 |
| `src/mycode/agents/tools.py` | 固定 `Agent`、`Task` 工具及结果序列化 |
| `src/mycode/agents/waiting.py` | Event 与 prompt-toolkit 两种前台等待器 |
| `src/mycode/tools/file_cache.py` | 任务级文件读取缓存和失效逻辑 |
| `src/mycode/agents/builtins/__init__.py` | 内置角色包资源 |
| `src/mycode/agents/builtins/explore.md` | 内置只读代码探索角色 |
| `tests/test_agent_definition_parser.py` | frontmatter、字段、安全和模型档位测试 |
| `tests/test_agent_catalog.py` | 四来源、覆盖、插件顺序、诊断和热更新测试 |
| `tests/test_agent_policy.py` | 全局禁令、角色限制、Plan 和后台白名单测试 |
| `tests/test_agent_permissions.py` | 权限状态隔离、非交互拒绝和审计测试 |
| `tests/test_provider_pool.py` | 模型选择、连接复用、并发和幂等关闭测试 |
| `tests/test_agent_request_bridge.py` | 快照生命周期、深复制和稳定指纹测试 |
| `tests/test_child_agent_runner.py` | 两类子运行、上下文隔离、用量和清理测试 |
| `tests/test_agent_task_manager.py` | 状态机、FIFO、竞争、通知、取消和关闭测试 |
| `tests/test_agent_control_tools.py` | `Agent`/`Task` schema、参数和 Session 边界测试 |
| `tests/test_agent_foreground_waiting.py` | 同步完成、超时和 `Ctrl+B` 测试 |
| `tests/test_agent_delegation_integration.py` | 定义式、Fork、收件箱及生命周期端到端测试 |

### 修改文件

| 文件 | 修改职责 |
|---|---|
| `src/mycode/types.py` | 增加 Agent 配置；为 `ToolContext` 增加可选任务级文件缓存 |
| `src/mycode/config.py` | 严格解析模型映射、白名单、超时、并发和队列配置 |
| `src/mycode/providers/base.py` | 增加可关闭 Provider/传输协议边界 |
| `src/mycode/providers/anthropic.py` | 注入共享 HTTP client，不再每次请求创建 client |
| `src/mycode/providers/openai.py` | 注入共享 HTTP client，不再每次请求创建 client |
| `src/mycode/providers/factory.py` | 支持由池构造指定模型 Provider |
| `src/mycode/agent/cancellation.py` | 改为基于线程 Event 的并发安全取消令牌 |
| `src/mycode/agent/events.py` | 增加子运行所需的安全停止原因 |
| `src/mycode/agent/executor.py` | 接入子工具策略和 `policy` 结果来源 |
| `src/mycode/agent/runner.py` | 发布父快照、注入收件箱、支持冻结请求模板和独立子 profile |
| `src/mycode/tools/executor.py` | 允许自行管理超时的控制工具在当前执行线程运行 |
| `src/mycode/tools/files.py` | `read_file` 使用任务级缓存，写入和编辑后失效 |
| `src/mycode/tools/registry.py` | 支持安全冻结/复制 Registry，保持顺序 |
| `src/mycode/tool_safety.py` | 注册 `Agent`、`Task` 为系统控制工具并维护子运行全局禁令 |
| `src/mycode/permissions/service.py` | 支持独立模式派生、判定观察器和稳定的无交互拒绝原因 |
| `src/mycode/hooks/models.py` | 增加 Agent scope 模型与 `policy` 结果来源 |
| `src/mycode/hooks/events.py` | 在事件 payload 中写入独立 scope，避免并发 turn 串线 |
| `src/mycode/hooks/runtime.py` | 将规则/once/动作共享状态与每个 Agent 的 turn/prompt/lease 状态拆开 |
| `src/mycode/skills/isolated.py` | 从 ProviderPool 获取 Provider，保持既有 Skill 行为 |
| `src/mycode/commands/models.py` | 增加任务摘要状态类型 |
| `src/mycode/commands/interfaces.py` | 增加任务摘要查询 UI 接口 |
| `src/mycode/commands/builtins.py` | 注册并格式化 `/tasks` |
| `src/mycode/commands/__init__.py` | 导出新增命令类型和格式化函数 |
| `src/mycode/cli.py` | 组装目录、池、桥、管理器、控制工具、通知、热更新和清理顺序 |
| `config.example.yaml` | 记录 Agent 配置示例和安全默认值 |
| `README.md` | 说明角色格式、两种委派、后台任务、权限与范围 |
| `pyproject.toml` | 打包内置 Agent Markdown 资源 |

### 扩展既有测试

| 文件 | 回归重点 |
|---|---|
| `tests/test_config.py` | Agent 配置默认值、非法边界和环境兼容 |
| `tests/test_providers.py` | 共享 client 不改变请求 payload 与流式解析 |
| `tests/test_agent_executor.py` | 策略拒绝顺序、Hook `policy` 来源和控制工具执行 |
| `tests/test_agent_runner.py` | 快照发布/撤销、收件箱注入、Fork 首轮前缀 |
| `tests/test_tool_executor.py` | 自管理超时工具不被外层超时截断 |
| `tests/test_tools_files.py` | 文件缓存命中、stat 变化和写后失效 |
| `tests/test_permissions_service.py` | 派生实例无 session rule 泄漏 |
| `tests/test_hooks_events.py` | scope payload |
| `tests/test_hooks_runtime.py` | 并发 scope、共享 once 和 prompt lease 隔离 |
| `tests/test_hooks_integration.py` | 主/子 Agent 并发 Hook 回归 |
| `tests/test_skill_isolated.py` | 池化 Provider 后现有独立 Skill 行为不变 |
| `tests/test_command_builtins.py` | `/tasks` 无参数、本地执行和脱敏输出 |
| `tests/test_cli.py` | 热更新、通知、`Ctrl+B`、`/new` 与退出清理 |
| `tests/test_context_manager.py` | Fork 首轮只估算、不改写和后台结果边界 |
| `tests/test_session_journal.py` | 收件箱组合消息可恢复且不重复 |

## 需求覆盖

| 需求 | 设计覆盖 |
|---|---|
| F1–F3 | 固定控制工具、父请求桥、Fork 冻结模板 |
| F4–F7 | 角色解析、四来源目录、热更新、模型档位映射 |
| F8–F9 | 独立 Runner 状态、文件缓存、权限派生、ProviderPool、HookScope |
| F10–F11 | ChildAgentExecutor 跑到底、角色轮次、非交互权限 |
| F12–F14 | ChildToolPolicy、多层执行顺序、后台动态白名单 |
| F15–F16 | 所有任务先入管理器、ForegroundWaiter、原子切后台 |
| F17–F18 | TaskRecord 状态机、显式 FIFO、daemon worker 和配置上限 |
| F19 | 唯一终态投递权、终端通知器、Session 收件箱 |
| F20–F21 | `Task` 工具与 `/tasks` 本地命令 |
| F22–F23 | Session 绑定取消、进程有界关闭、不持久化任务 |
| F24 | 统一 ToolResult、TaskOutcome、Token 累加和有界预览 |
| N1–N2 | 固定注册顺序/schema、请求指纹与 Fork 首轮冻结 |
| N3–N4 | 单锁状态转换、Event、唯一通知、结构化异常边界 |
| N5–N6 | 脱敏诊断、权限审计和摘要投影 |
| N7–N8 | 子历史隔离、收件箱规范化、现有上下文外置 |
| N9–N10 | 配置硬上限、热更新和无重启任务管理 |
| N11–N12 | 可选依赖保持旧路径、Python 3.10 并发/端到端测试 |

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 前后台实现 | 任务始终由管理器执行，前台只是等待 | 超时和 `Ctrl+B` 不需要迁移、重启或复制执行 |
| 调度器 | 显式 FIFO + 固定 daemon worker | 可精确限制运行和排队数量，也能保证退出不被失控线程无限阻塞 |
| 状态并发 | 单个 `RLock` 保护记录、队列、收件箱和通知领取权 | 简化完成/超时/取消竞争，保证唯一终态和唯一投递 |
| 完成等待 | 每任务 `threading.Event` | Python 3.10 可用，易于确定性测试和有界等待 |
| Fork 快照 | 复制实际发送的 `ChatRequest` 与有序 Registry | 比重新构造提示更能保证缓存前缀相同 |
| Fork 首轮上下文 | 只估算，不摘要或外置 | 任意改写都会破坏已确认的前缀一致性 |
| 子 Agent 循环 | 扩展现有 `AgentRunner`，不另写第二套 loop | 保留流式解析、工具批次、取消、上下文和停止语义 |
| 定义式提示 | 标准稳定基础提示 + 项目指令 + 角色正文 | 保持安全约束，同时不继承主对话、Skill 或记忆污染 |
| 控制工具权限 | 系统控制工具自动允许，子策略硬拒绝 | 主 Agent 可稳定委派，子 Agent 无法通过角色或配置解禁嵌套 |
| 工具策略位置 | 可见性过滤 + 执行前再次判定 | 同时防止误导模型和应对 Fork 工具前缀、动态切后台 |
| 后台白名单 | 执行时读取任务投递状态 | `Ctrl+B` 后未执行调用立刻收紧，已开始调用不做不安全回滚 |
| 权限服务 | 共享不可变配置、每任务新实例 | 复用规则但隔离 session 授权与审计 |
| Provider 共享 | ProviderPool + 线程安全 HTTP 连接池 | 满足基础设施共享，避免每个子任务重复建连接 |
| Hook 共享 | 共享规则/once/动作，隔离 scope/turn/prompt | 同时满足基础设施共享与并发运行状态隔离 |
| 文件缓存 | 放入每个 Runner 的 ToolContext | 工具对象可共享，而缓存天然按主/子运行隔离 |
| 后台结果角色 | 与下一次原始输入组成带标签 user 消息 | 不引入 Provider 不兼容的新角色，并可沿用会话持久化 |
| 结果大对象 | ToolResult display/complete 双层 + 收件箱预览 | 沿用现有上下文外置机制，同时允许 `Task get` 获取完整结果 |
| 热更新快照 | 创建时冻结 | 运行中行为确定，新的定义只影响后续任务 |
| 插件支持 | 有序目录注入 | 满足加载优先级而不越界实现插件系统 |
| 任务持久化 | 仅内存 | 符合本阶段明确排除的跨会话后台恢复 |
| 内置角色 | 仅提供安全只读 `explore` | 确保系统开箱可验收，不扩张成角色库 |
| 现有 Hooks 改动 | 在当前已提交实现上增量拆分 scope | 保留既有 Hooks 行为和测试，不回退或覆盖用户工作 |
