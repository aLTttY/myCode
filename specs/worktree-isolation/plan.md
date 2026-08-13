# Sub-Agent Worktree Isolation Plan

## 设计依据

- 已批准需求：[`spec.md`](./spec.md)
- Git Worktree 的创建、锁定、机器可读枚举、删除和每工作区配置语义：[Git Worktree 官方文档](https://git-scm.com/docs/git-worktree.html)
- Git 运行时配置环境与配置优先级：[Git Config 官方文档](https://git-scm.com/docs/git-config/2.43.6.html)
- `core.hooksPath` 与 Hook 执行目录语义：[Git Hooks 官方文档](https://git-scm.com/docs/githooks)

## 架构概览

本功能在现有任务管理器与子 Agent 执行器之间增加一层 `WorktreeTaskExecutor`，不改变 `Agent` 工具 schema。任务 ID 仍由系统生成；只有角色快照声明 `isolation: worktree` 时才进入 Worktree 路径，普通定义式任务和 Fork 任务继续走现有共享工作区路径。

执行链如下：

```text
AgentTool
→ AgentTaskManager 排队
→ WorktreeTaskExecutor 判断隔离模式
  → 共享模式：直接运行 ChildAgentExecutor
  → Worktree 模式：
      WorktreeManager 创建或只读恢复
      → WorkspaceInitializer 幂等初始化
      → WorkspaceContextFactory 构造绝对 cwd 上下文
      → ChildAgentExecutor 执行
      → WorktreeManager 检查并清理或保留
→ TaskOutcome 返回结果与工作区状态
```

### 角色与配置层

角色解析器增加可选 `isolation` 字段。字段缺失映射为内部 `shared`；字段存在时只接受 `worktree`。Fork 请求没有角色，因此不能进入 Worktree 路径。

项目配置的 `agents.worktree` 管理 Git 超时、清理周期、过期时间和初始化规则。Worktree 根目录固定为 `.mycode/worktrees/`，不允许配置，减少路径攻击面。

### Worktree 生命周期层

新增独立的 `worktrees` 包，统一负责：

- 安全标识和绝对路径计算；
- 从当前 `HEAD` 创建分支与 Worktree；
- 只读快速恢复；
- 原子身份记录；
- 工作树、提交、合并和远端跟踪状态检查；
- 受保护删除；
- 进程内及跨进程目标锁。

Git Worktree 共享仓库对象、为每个工作目录维护独立 `HEAD` 和管理记录。脚本解析使用官方保证稳定的 `git worktree list --porcelain -z`，不直接猜测 `.git/worktrees` 的内部名称。

### 环境初始化层

`WorkspaceInitializer` 执行配置声明的复制、软链接、忽略文件补齐和 hooks 配置。规则在配置加载期完成路径与目标冲突校验，在任务启动期完成源文件和符号链接边界校验。

安全默认规则为：

- 可选复制 `config.yaml`；
- 可选复制 `.mycode/permissions.local.yaml`；
- 可选复制 `.mycode/hooks.local.yaml`；
- 可选软链接 `.venv`；
- 可选使用主工作区 `.git/hooks`。

Git hooks 通过子任务专属环境向 Git 注入 `core.hooksPath`，不会启用 `extensions.worktreeConfig`，也不会修改共享 `.git/config`。Git 官方的 Worktree 专属配置模式需要先修改共享仓库配置启用扩展；运行时配置环境只影响派生进程，因此选择后者满足“不改变主工作区 Git 配置”的要求。

### 工作区执行上下文层

`WorkspaceContextFactory` 以规范化绝对工作目录构造：

- `ToolContext.workspace_root`；
- 文件读取缓存；
- Worktree 专属子进程环境；
- 项目指令；
- 当前 Worktree 内存在的项目记忆索引；
- Hook event 与 Hook command 的 cwd；
- 隔离路径说明。

隔离任务不复用启动时加载的主工作区指令。系统提示词在任务目录上下文中重新构建；文件缓存继续以解析后的绝对路径为 key。Worktree 中没有项目记忆时保持为空，不继承主工作区被忽略的项目记忆文件，也不继承主 Agent 的用户记忆。

主工作区的文件枚举和代码搜索显式排除 `.mycode/worktrees/`，避免扫描嵌套工作区。子任务的文件、命令、Git 和 Hook 调用都显式携带其 cwd，不使用 `chdir`。

### 任务状态与结果层

`TaskOutcome`、`TaskSnapshot`、Inbox 和 `/tasks` 增加可选工作区摘要，包含路径、分支、基线、生命周期状态和保留原因。取消中的 worker 仍负责完成 Worktree 退出；运行中的任务先进入 `cancelling`，清理或保留结果确定后才进入终态和投递通知。

### 后台清理层

`WorktreeJanitor` 启动后立即扫描，随后按配置周期扫描。它只读取受管身份记录作为候选入口，并复用 `WorktreeManager` 的路径、身份和状态检查以及同一套目标锁，不维护第二套删除逻辑。

关闭顺序为：停止 Janitor 接收新扫描，取消并等待子任务退出，再关闭剩余应用资源。未能在期限内退出的活动 Worktree 保留给下次启动扫描。

## 核心数据结构

### `AgentDefinition`

增加：

```python
isolation: Literal["shared", "worktree"] = "shared"
```

frontmatter 未声明时归一化为 `shared`；显式字段只接受 `worktree`。该字段进入角色不可变快照，已创建任务不受角色热更新影响。

### `WorktreeConfig`

```python
@dataclass(frozen=True)
class WorktreeConfig:
    git_timeout_seconds: float = 10.0
    cleanup_interval_seconds: float = 300.0
    stale_after_seconds: float = 86_400.0
    initialization: tuple[WorktreeInitRule, ...] = DEFAULT_INIT_RULES
```

Worktree 根目录固定为 `.mycode/worktrees/`，不暴露配置项。

### `WorktreeInitRule`

```python
@dataclass(frozen=True)
class WorktreeInitRule:
    action: Literal["copy", "symlink", "hooks"]
    source: str
    target: str | None
    required: bool
```

默认规则等价于：

```yaml
agents:
  worktree:
    git_timeout_seconds: 10
    cleanup_interval_seconds: 300
    stale_after_seconds: 86400
    initialization:
      - action: copy
        source: config.yaml
        target: config.yaml
        required: false
      - action: copy
        source: .mycode/permissions.local.yaml
        target: .mycode/permissions.local.yaml
        required: false
      - action: copy
        source: .mycode/hooks.local.yaml
        target: .mycode/hooks.local.yaml
        required: false
      - action: symlink
        source: .venv
        target: .venv
        required: false
      - action: hooks
        source: .git/hooks
        required: false
```

规则约束：

- `source` 和 `target` 均为主工作区相对路径；
- `copy` 支持单文件和有硬上限的目录复制，不跟随目录中的符号链接；
- `symlink` 只创建一个指向已验证源的链接；
- `hooks` 不复制目录，只把验证后的绝对路径注入子进程 Git 配置环境；
- `copy` 和 `symlink` 的目标在首次创建时必须通过 Git ignore 检查，否则拒绝初始化；
- 快速恢复使用身份记录中的初始化指纹和已验证目标清单，不重新调用 Git；配置变化时拒绝快速恢复。

### 初始化辅助类型

```python
@dataclass(frozen=True)
class InitializedPath:
    action: Literal["copy", "symlink", "hooks"]
    source: str
    target: str | None
    required: bool


@dataclass(frozen=True)
class WorktreeDiagnostic:
    level: Literal["warning", "error"]
    code: str
    rule_index: int | None
    message: str


@dataclass(frozen=True)
class InitializationResult:
    manifest: tuple[InitializedPath, ...]
    process_environment: Mapping[str, str]
    diagnostics: tuple[WorktreeDiagnostic, ...]
```

manifest 只保存动作、相对路径和必要性，不保存复制内容、环境变量值或配置文件内容摘要。快速恢复按 manifest 定位安全源和目标，再进行受边界约束的实时比较。

### `WorktreeRequest`

```python
@dataclass(frozen=True)
class WorktreeRequest:
    task_id: str
    role_name: str
    managed_name: str
    main_workspace: Path
    repository_id: str
    base_commit: str
    base_ref: str
    branch_ref: str
    worktree_path: Path
    initialization_fingerprint: str
    created_at: datetime
    recovery_identity: WorktreeIdentity | None = None
```

该请求在 `AgentTool` 调用时生成，而不是等到 worker 出队后生成，从而固定调用时的 `HEAD`。请求工厂先以纯文件系统方式判断目标路径：目标已存在时只读恢复身份，目标不存在时才调用只读 Git 捕获基线。

约定：

```text
managed_name = tasks/<task-id>
branch_ref   = refs/heads/mewcode/worktree/<task-id>
worktree     = <repo>/.mycode/worktrees/tasks/<task-id>
```

安全标识每段只接受 `[a-z0-9][a-z0-9_-]{0,63}`，总长度不超过 200；额外拒绝空段、`.`、`..`、反斜杠和绝对路径。生成分支后仍通过 Git ref 格式校验。

创建时要求主工作区 `HEAD` 指向一个本地分支；若处于 detached HEAD，因无法可靠确定后续“当前主分支”，本次隔离任务失败关闭。

### `WorktreeIdentity`

```python
@dataclass(frozen=True)
class WorktreeIdentity:
    schema_version: int
    repository_id: str
    task_id: str
    role_name: str
    managed_name: str
    worktree_path: Path
    branch_ref: str
    base_commit: str
    base_ref: str
    expected_gitdir: Path
    initialization_fingerprint: str
    initialization_manifest: tuple[InitializedPath, ...]
    lifecycle_state: Literal["creating", "active", "retained", "cleanup_failed"]
    created_at: datetime
    last_active_at: datetime
```

身份保存两份：

```text
主记录：.mycode/worktrees/.records/<task-id>.json
目录标记：<worktree>/.mycode/worktree.json
```

两份均使用 UTF-8、严格 schema、权限 `0600` 和临时文件加 `fsync` 后原子替换。`.gitignore` 增加：

```gitignore
.mycode/worktrees/
.mycode/worktree.json
```

快速恢复只读取主记录、目录标记和 Worktree 根部 `.git` 指针文件；三者必须完全对应。该路径不执行 Git 命令。身份记录不保存本地配置内容或可用于离线猜测秘密的内容摘要；恢复时直接在安全边界内比较源和目标。

### `WorktreeLease`

```python
@dataclass(frozen=True)
class WorktreeLease:
    identity: WorktreeIdentity
    workspace_root: Path
    recovered: bool
    lock_token: TargetLock
    process_environment: Mapping[str, str]
    initialization_diagnostics: tuple[WorktreeDiagnostic, ...]
```

`process_environment` 是不可变环境 overlay，不是完整进程环境快照。Lease 表示任务正在占用目标；持有期间后台清理不能取得同一目标锁。

### Git 与清理辅助类型

```python
@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True)
class CleanupReport:
    cleaned: int
    skipped: int
    failed: int
    diagnostics: tuple[WorktreeDiagnostic, ...]
```

Git porcelain 使用原始 bytes 和 NUL 边界解析，完成字段校验后才解码路径，避免按换行或本地化文本解析。

### `WorktreeInspection`

```python
@dataclass(frozen=True)
class WorktreeInspection:
    has_tracked_changes: bool
    has_untracked_changes: bool
    new_commits: tuple[str, ...]
    primary_ref: str
    delivery_refs: tuple[str, ...]
    protected_commits: tuple[str, ...]
    safe_for_task_exit: bool
    safe_for_protected_delete: bool
    retention_reason: Literal[
        "none",
        "uncommitted_changes",
        "unmerged_unpushed_commits",
        "status_unknown",
    ]
```

状态算法：

1. 使用 porcelain `-z` 状态读取已跟踪变更和未忽略的未跟踪文件；
2. 读取 `base_commit..branch_ref` 的新增 commit；
3. 对每个新增 commit 检查是否为创建时 `base_ref` 当前值的祖先，或是否为可靠 delivery ref 的祖先；
4. delivery ref 包括临时分支已配置且能可靠解析的 upstream，以及 `refs/remotes/<remote>/mewcode/worktree/<task-id>` 同名远端跟踪引用；
5. 任务结束自动清理要求没有任何新增 commit；只要有新增 commit，任务结束时就先保留；
6. 后续内部删除要求每个新增 commit 至少满足“已合并”或“已送达”之一；
7. 没有可靠 delivery ref 时按未推送处理，全程不执行 fetch 或其他网络访问。

### `WorktreeDisposition`

```python
@dataclass(frozen=True)
class WorktreeDisposition:
    status: Literal[
        "cleaned",
        "retained_changes",
        "retained_commits",
        "cleanup_failed",
    ]
    identity: WorktreeIdentity
    inspection: WorktreeInspection | None
    reason: str
```

所有清理、保留和失败路径都返回该结构，不用异常表示正常的“因保护而保留”。

### `ChildWorkspaceContext`

```python
@dataclass(frozen=True)
class ChildWorkspaceContext:
    workspace_key: Path
    tool_context: ToolContext
    instruction_bundle: InstructionBundle
    project_memory_prompt: str
    isolation_instruction: DynamicInstruction
    process_environment: Mapping[str, str]
```

`workspace_key` 必须是规范化绝对路径。该上下文按任务创建，不与其他 Worktree 共享可变缓存：

- 文件缓存继续使用绝对文件路径；
- 项目指令从当前 Worktree 重新加载；
- 项目记忆只读取当前 Worktree 的 `.mycode/memory/index.md`；
- 不继承主 Agent 的用户记忆、会话历史或激活 Skill；
- 系统提示词包含绝对 cwd；
- Hook event、Hook command 和工具子进程绑定同一 cwd。

`ToolContext` 增加：

```python
process_environment: Mapping[str, str] | None
excluded_roots: tuple[Path, ...]
```

主 Agent 的 `excluded_roots` 包含 `.mycode/worktrees/`；文件、搜索和命令路径校验不得显式进入该目录。子 Agent 使用自己的 Worktree 为根目录。

### `WorktreeTaskSummary`

```python
@dataclass(frozen=True)
class WorktreeTaskSummary:
    path: str
    branch: str
    base_commit: str
    status: Literal[
        "preparing",
        "active",
        "cleaned",
        "retained_changes",
        "retained_commits",
        "cleanup_failed",
    ]
    retention_reason: str
    last_active_at: datetime | None
```

该结构作为可选字段进入 `TaskOutcome`、`TaskSnapshot`、`TaskDetails` 和 `InboxItem`；共享模式任务为 `None`。

## 核心接口

### `GitRunner`

```python
run(
    args: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str] | None,
    timeout_seconds: float,
    optional_locks: bool,
) -> GitResult
```

统一使用参数数组和 `shell=False`，设置非交互、禁用 pager，并对只读检查设置 `GIT_OPTIONAL_LOCKS=0`。该接口不提供 fetch、pull 或 push 操作。

### `WorktreeRequestFactory`

```python
prepare(
    task_id: str,
    role_name: str,
    workspace: Path,
    initialization_fingerprint: str,
) -> WorktreeRequest
```

先由 `paths` 计算目标。目标已存在时，使用 `identity` 纯文件系统读取并构造恢复请求；目标、主记录和分支均不存在时，使用只读 Git 捕获调用时基线并构造新建请求。存在部分冲突时失败关闭，不尝试接管或修复。

### `WorktreeManager`

```python
enter(request: WorktreeRequest) -> WorktreeLease
activate(
    lease: WorktreeLease,
    initialization_manifest: tuple[InitializedPath, ...],
) -> WorktreeLease
abort_initialization(lease: WorktreeLease) -> WorktreeDisposition
inspect(identity: WorktreeIdentity) -> WorktreeInspection
exit(lease: WorktreeLease) -> WorktreeDisposition
delete(identity: WorktreeIdentity) -> WorktreeDisposition
managed_candidates() -> tuple[WorktreeIdentity, ...]
```

关键行为：

- `enter` 在目录不存在时以不覆盖的 `git worktree add --no-track --lock -b` 创建；目录存在时只执行文件系统快速恢复；
- `activate` 只在初始化全部成功后把两份身份状态原子更新为 `active`；
- `inspect` 每次删除前重新核验 Git 注册、分支和状态；
- `exit` 仅在没有文件变化且没有新增 commit 时调用不带 `--force` 的 `git worktree remove`；存在任何新增 commit 时先保留；
- `delete` 用于后续内部重检，只有文件干净且所有新增 commit 已合并或已送达时才删除 Worktree 和临时分支；
- 任一步骤不确定时保留数据并返回 `cleanup_failed`。

### `WorkspaceInitializer`

```python
initialize(
    lease: WorktreeLease,
    rules: tuple[WorktreeInitRule, ...],
) -> InitializationResult
```

首次创建时验证 ignore 状态并执行规则；快速恢复时依据已验证 manifest 做纯文件系统幂等检查。已存在且不一致的目标一律拒绝覆盖。

### `WorkspaceContextFactory`

```python
build(
    lease: WorktreeLease,
    initialization_result: InitializationResult,
) -> ChildWorkspaceContext
```

负责重新加载当前目录的指令和项目记忆，创建文件缓存、进程环境和隔离提示。它不调用 `chdir`。

### `WorktreeTaskExecutor`

```python
run(spec: ChildRunSpec, cancellation: CancellationToken) -> TaskOutcome
```

共享任务直接调用原 `ChildAgentExecutor`。Worktree 任务执行：

```text
enter → initialize/activate → build context
→ ChildAgentExecutor.run → exit
```

退出在 `finally` 中执行。运行中取消的任务进入 `cancelling`；清理结果合并进任务记录后才成为 `cancelled` 并投递通知。

### `WorktreeJanitor`

```python
start() -> None
scan_once() -> CleanupReport
close(timeout_seconds: float) -> None
```

候选仅来自严格解析成功的主身份记录。每个候选依次经过路径、身份、状态三层过滤，并和任务执行共用目标锁。单项异常转为诊断，不终止整轮扫描。

## 模块设计

### `mycode.worktrees.paths`

**职责：**

- 校验受管名称；
- 计算固定 Worktree 根、记录路径、目录标记路径和临时分支；
- 规范化绝对路径并验证边界；
- 排除根目录本身、符号链接逃逸和嵌套逃逸。

**依赖：** 仅标准库 `pathlib`、`re`。

所有创建、恢复和清理流程必须调用这一模块，不允许各模块自行拼接路径。

### `mycode.worktrees.git`

**职责：**

- 在显式 `cwd` 和超时下运行参数化 Git 命令；
- 捕获当前 `HEAD`、主分支和仓库身份；
- 创建、枚举、检查和删除 Worktree；
- 判断新增提交是否已合并或送达对应远端跟踪分支；
- 使用预期旧值安全删除临时引用。

**依赖：** `subprocess`。

对已存在目录的快速恢复不调用本模块。删除判断只读取本地引用；禁止提供 fetch、pull、push 接口。

### `mycode.worktrees.identity`

**职责：**

- 严格解析、校验和序列化双份身份记录；
- 生成初始化规则指纹；
- 原子写入记录；
- 比较主记录、目录标记和 `.git` 指针；
- 隔离损坏、未知版本或不完整状态。

**依赖：** `paths`。

`creating` 记录不能被当作可运行 Worktree；只有两份记录都成为 `active` 或 `retained` 后才允许恢复和进入清理检查。

### `mycode.worktrees.locking`

**职责：**

- 提供进程内目标锁；
- 提供进程间 advisory 文件锁；
- 按仓库与受管名称形成绝对锁 key；
- 在异常退出时由操作系统释放锁。

**依赖：** 标准库平台适配。

创建、恢复、初始化、运行占用、退出和 Janitor 清理使用同一把目标锁。活动任务在整个 Lease 生命周期持锁，而不是只在创建瞬间持锁。

### `mycode.worktrees.initializer`

**职责：**

- 执行复制、软链接和 hooks 初始化规则；
- 验证源、目标、符号链接、ignore 状态、目录复制上限和目标冲突；
- 生成可恢复验证的初始化 manifest；
- 在快速恢复时进行纯文件系统幂等核对。

**依赖：** `paths`、`identity`；首次创建时可调用受限 Git ignore 检查。

初始化按配置顺序执行。失败时停止后续规则；仅回滚本次创建且可以证明仍与本次输出一致的文件，不删除原有目标。

### `mycode.worktrees.manager`

**职责：**

- 在任务提交时准备固定的新建或恢复请求；
- 编排 Worktree 创建或恢复；
- 管理身份状态转换；
- 检查业务变更与提交保护；
- 保护性删除或保留；
- 输出统一诊断和 `WorktreeDisposition`。

**依赖：** `paths`、`git`、`identity`、`locking`。

它是唯一允许执行 `git worktree add/remove/unlock` 和删除临时分支的模块。Janitor 与任务执行器均复用此模块。

### `mycode.worktrees.context`

**职责：**

- 从 Worktree 绝对路径重新加载项目指令；
- 读取当前 Worktree 的项目记忆索引；
- 构造绝对路径 keyed 的提示上下文；
- 创建任务独立文件缓存和进程环境；
- 生成隔离说明；
- 为 Hook scope 提供当前 Worktree 的 event 根和 command cwd。

**依赖：** `InstructionLoader`、`MemoryStore`、`PromptBuilder`、`FileReadCache`。

内部缓存统一采用以下 key：

```text
(normalized_absolute_workspace, resource_kind, normalized_absolute_source)
```

资源指纹变化时更新对应项，不进行目录切换或全局清缓存。

### `mycode.agents.worktree_executor`

**职责：**

- 根据角色快照选择共享或 Worktree 路径；
- 在子 Agent 执行前进入并初始化 Worktree；
- 把 `ChildWorkspaceContext` 传入现有执行器；
- 在所有终态中执行退出检查；
- 合并 Agent 结果与 Worktree disposition。

**依赖：** `WorktreeManager`、`WorkspaceInitializer`、`WorkspaceContextFactory`、`ChildAgentExecutor`。

共享模式不创建任何 Worktree 类型或文件，保持原有执行路径。该适配器位于上层 `agents` 包，使底层 `worktrees` 包不反向依赖 Agent 类型。

### `mycode.worktrees.janitor`

**职责：**

- 启动扫描与周期扫描；
- 严格读取受管候选；
- 进行过期检查和三层过滤；
- 调用 Manager 的保护性删除；
- 汇总脱敏诊断；
- 有界停止后台线程。

**依赖：** `WorktreeManager`、`locking`。

Janitor 不扫描任意目录来猜测 Worktree；没有有效主身份记录的目录不是候选。

### 现有 Agent 模块调整

#### `agents.parser` / `agents.models`

- 解析并保存角色 `isolation`；
- 保留缺失字段向 `shared` 的兼容行为；
- 将隔离模式纳入角色 fingerprint。

#### `agents.tools`

- `Agent` 工具 schema 不变；
- 生成任务 ID 后构造受信任 Worktree 名称；
- 对 Worktree 角色准备创建请求或纯文件系统恢复请求；
- `Task` 返回工作区摘要，但不增加创建、删除或强制清理 action。

#### `agents.tasks`

- 增加 `cancelling` 中间态；
- 对正在运行的任务，取消只设置 token 和 `cancel_requested`，等待执行器完成退出检查后再进入终态并通知；
- 对仍在队列中的任务可直接取消，因为尚未创建 Worktree；
- Worktree 状态变化通过受控回调更新任务快照。

#### `agents.runner`

- `ChildAgentExecutor.run` 接收任务级 `ChildWorkspaceContext`；
- 工具、提示、项目指令、项目记忆和 Hook scope 均从该上下文获取；
- Fork 和共享定义式任务继续使用主工作区上下文。

### 现有基础设施调整

#### 工具与权限

- `RunCommandTool` 使用 `ToolContext.process_environment` 和明确 cwd；
- `ReadGitChangesTool` 在同一环境上叠加只读 Git 变量；
- 文件、搜索、权限路径校验统一拒绝进入 `excluded_roots`；
- 主 Agent 排除 `.mycode/worktrees/`，避免专用工具读取或修改子 Agent 工作区；
- 对 Worktree 根的显式命令路径，以及会递归破坏其祖先目录的已知命令模式，执行不可覆盖的拒绝；
- 子 Agent 的边界就是自己的 Worktree 根。

普通 shell 仍经过现有权限、Hook 和危险命令黑名单。本阶段提供 Git 工作区隔离与已知误操作保护，不宣称提供容器或 OS 级恶意代码隔离。

#### Hooks

`HookRuntime.fork_scope` 增加 Worktree 根和进程环境参数。隔离 scope 创建自己的 `HookEventFactory` 与 `HookActionExecutor`，因此 Hook payload 的 `workspace` 和 Hook command 的 cwd 都指向当前 Worktree；规则与 `once` 状态继续共享。

#### 配置与文档

- `types.py` 增加 Worktree 配置类型；
- `config.py` 严格解析 `agents.worktree`；
- `config.example.yaml` 给出默认规则与边界说明；
- `.gitignore` 忽略专用根和目录身份标记；
- README 更新角色示例、生命周期、保留行为和配置说明。

## 模块交互

### 场景一：新建并运行隔离任务

```text
AgentTool
  1. 校验定义式角色及 isolation
  2. 生成 task_id 与安全 managed_name
  3. 检查目标路径是否存在
     - 不存在：用只读 Git 捕获调用时 HEAD、主分支和仓库身份
     - 已存在：只读双份身份与 .git 指针，不调用 Git
  4. 把固定请求提交给 AgentTaskManager

Worker
  5. WorktreeTaskExecutor 获取目标锁
  6. WorktreeManager.enter
     - 新建：git worktree add --no-track --lock -b <branch> <path> <base>
     - 恢复：再次纯文件系统核验身份
  7. WorkspaceInitializer 初始化并生成 manifest
  8. 双份身份原子切换为 active
  9. WorkspaceContextFactory 构造任务上下文
 10. ChildAgentExecutor 在显式 cwd 中运行
 11. finally 中检查状态
 12. 无业务变更、无新增提交：解锁并安全删除
     有变更或受保护提交：切换为 retained
     检查失败：切换为 cleanup_failed
 13. 合并 Worktree 摘要后设置任务终态并通知
```

创建阶段使用 `git worktree add --lock`，避免初始化期间的 Git 管理记录被外部 prune。保留项继续保持锁定；安全删除前重新验证身份并执行 `unlock`。

### 场景二：快速恢复

```text
目标目录已存在
→ 获取目标锁
→ 读取主身份记录
→ 读取目录身份标记
→ 读取顶层 .git 指针
→ 校验 schema、仓库、任务、路径、分支、基线、gitdir、初始化指纹
→ 校验 manifest 中每个复制项、软链接和 hooks 源
→ 全部一致：恢复 Lease
→ 任一不确定：拒绝恢复并保持目录原样
```

此链路禁止调用 Git、写文件、补记录或修复 Worktree。只有真正进入后续运行与退出检查时才允许调用 Git。

### 场景三：环境初始化

```text
逐条规则
→ 词法路径检查
→ 规范化边界检查
→ 源类型及符号链接检查
→ 目标冲突检查
→ required 缺失判定
→ 首次创建检查目标保持 Git ignored
→ 执行 copy / symlink / hooks 环境注入
→ 记录结果摘要和安全验证信息
```

目录复制设置文件数量和总字节硬上限。达到上限时整个规则失败，不留下无法证明完整的初始化结果。

### 场景四：任务退出与保护

```text
git status --porcelain=v1 -z --untracked-files=all
→ 有已跟踪或未忽略未跟踪变化：retained_changes
→ 无文件变化：
    枚举 base_commit..branch_ref
    → 无新增提交：cleaned
    → 有任何新增提交：retained_commits
→ 任一 Git 检查超时或失败：cleanup_failed 并保留
```

任务退出阶段不会因 commit 已合并或已送达而立即删除；它总是先保留产生 commit 的工作区，并把路径、分支和基线返回给主 Agent。

### 场景五：后续保护性删除

```text
工作树必须干净
→ 枚举 base_commit..branch_ref
→ 对每个新增 commit 检查
   - 已成为创建时主分支当前 tip 的祖先；或
   - 已成为同名远端跟踪分支
     refs/remotes/<remote>/mewcode/worktree/<task-id> 的祖先；或
   - 已成为可靠 upstream 的祖先
→ 全部满足：进入安全删除
→ 任一不满足或无法判断：继续保留
```

“送达远端”只承认临时分支同名的本地远端跟踪引用，或用户显式配置且能可靠解析的 upstream；推送到任意无关分支不视为已送达。

### 场景六：安全删除

```text
重新取得目标锁
→ 路径过滤
→ 双身份与 Git 注册过滤
→ 状态保护过滤
→ git worktree unlock
→ git worktree remove（不使用 --force）
→ git update-ref -d <branch> <expected-old-tip>
→ 删除主身份记录
```

若 Worktree 已删除但分支的预期旧值不匹配，保留分支并记录 `cleanup_failed`，不尝试强制删除已并发移动的引用。

### 场景七：后台清理

```text
应用启动 → Janitor.scan_once
周期定时器 ─┘
→ 枚举 .records 中严格合法记录
→ 过期过滤
→ 尝试目标锁；锁被占用则跳过
→ 路径层
→ 身份层
→ 状态层
→ Manager.delete
→ 汇总 cleaned / skipped / failed
```

损坏记录、陌生目录和缺失目录都只产生诊断；本阶段不运行 `git worktree repair`、全局 `prune` 或强制删除。

### 场景八：取消与关闭

```text
Task cancel
→ queued：直接取消，无 Worktree
→ running：状态变为 cancelling，触发 cancellation token
→ ChildAgentExecutor 停止
→ WorktreeTaskExecutor 完成退出检查
→ 任务进入 cancelled，并附清理或保留摘要
→ 此后才发送后台通知

应用关闭
→ Janitor.close
→ TaskManager 取消并有界等待 worker
→ 仍未退出的 Worktree 保留
→ 关闭 Hook、记忆、MCP、Provider
```

## 文件组织

### 新建文件

| 文件 | 职责 |
|---|---|
| `src/mycode/worktrees/__init__.py` | 导出 Worktree 公共类型和服务 |
| `src/mycode/worktrees/models.py` | 请求、身份、Lease、检查结果、初始化结果和任务摘要 |
| `src/mycode/worktrees/paths.py` | 名称、分支和目录安全校验 |
| `src/mycode/worktrees/git.py` | 有界、参数化 Git 调用与 porcelain 解析 |
| `src/mycode/worktrees/identity.py` | 双身份记录严格解析和原子写入 |
| `src/mycode/worktrees/locking.py` | 进程内和进程间目标锁 |
| `src/mycode/worktrees/initializer.py` | copy、symlink、hooks 初始化及恢复核验 |
| `src/mycode/worktrees/context.py` | 任务 cwd、环境、指令、记忆、提示和缓存上下文 |
| `src/mycode/worktrees/manager.py` | 创建、恢复、检查、退出和保护性删除 |
| `src/mycode/worktrees/janitor.py` | 启动扫描、周期扫描和有界关闭 |
| `src/mycode/agents/worktree_executor.py` | Worktree 生命周期与子 Agent 执行器适配 |
| `tests/worktree_testkit.py` | 临时 Git 仓库、远端引用和故障注入测试辅助 |
| `tests/test_worktree_paths.py` | 名称、嵌套路径、边界和符号链接攻击 |
| `tests/test_worktree_identity.py` | 双记录、原子写入、损坏和快速恢复 |
| `tests/test_worktree_initializer.py` | 初始化规则、幂等、冲突和秘密诊断 |
| `tests/test_worktree_manager.py` | Git 生命周期、变更和提交保护 |
| `tests/test_worktree_janitor.py` | 三层过滤、过期、互斥和重启遗留 |
| `tests/test_worktree_executor.py` | 上下文绑定、取消和结果合并 |
| `tests/test_worktree_isolation_integration.py` | 主 Agent 与多个 Worktree 端到端并行隔离 |

### 修改文件

| 文件 | 修改内容 |
|---|---|
| `.gitignore` | 忽略 `.mycode/worktrees/` 和 `.mycode/worktree.json` |
| `src/mycode/types.py` | Worktree 配置和任务级工具环境 |
| `src/mycode/config.py` | 严格解析 `agents.worktree` |
| `src/mycode/agents/models.py` | 角色隔离字段、Worktree 请求和任务摘要 |
| `src/mycode/agents/parser.py` | 解析可选 `isolation` |
| `src/mycode/agents/tools.py` | 准备受信任请求，返回 Worktree 状态 |
| `src/mycode/agents/tasks.py` | `cancelling`、退出后通知和状态回写 |
| `src/mycode/agents/runner.py` | 使用任务级绝对工作区上下文 |
| `src/mycode/agents/__init__.py` | 导出新增类型 |
| `src/mycode/tools/base.py` | 统一处理排除目录 |
| `src/mycode/tools/files.py` | Worktree 边界与绝对路径缓存 |
| `src/mycode/tools/search.py` | 跳过受管 Worktree 根 |
| `src/mycode/tools/command.py` | 显式 cwd 和进程环境 overlay |
| `src/mycode/tools/git.py` | 在任务环境中执行只读 Git |
| `src/mycode/permissions/sandbox.py` | 拒绝排除目录和递归破坏祖先目录 |
| `src/mycode/permissions/targets.py` | 将排除目录传入权限目标解析 |
| `src/mycode/permissions/service.py` | 命令隔离边界判定 |
| `src/mycode/hooks/events.py` | Worktree scope 的绝对 workspace |
| `src/mycode/hooks/actions.py` | Hook command 使用任务 cwd 与环境 |
| `src/mycode/hooks/runtime.py` | 构造 Worktree 专属 Hook scope |
| `src/mycode/commands/models.py` | `/tasks` 摘要增加 Worktree 信息 |
| `src/mycode/commands/builtins.py` | 展示清理或保留状态 |
| `src/mycode/cli.py` | 装配 Manager、Executor、Janitor 及关闭顺序 |
| `config.example.yaml` | Worktree 配置和默认初始化示例 |
| `README.md` | 角色声明、隔离边界、生命周期和保留说明 |

现有相关测试同步扩展：

```text
tests/test_agent_definition_parser.py
tests/test_agent_control_tools.py
tests/test_agent_task_manager.py
tests/test_child_agent_runner.py
tests/test_agent_delegation_integration.py
tests/test_config.py
tests/test_tools_files.py
tests/test_tools_search.py
tests/test_tools_command.py
tests/test_tools_git.py
tests/test_permissions_sandbox.py
tests/test_permissions_service.py
tests/test_hooks_actions.py
tests/test_hooks_runtime.py
tests/test_agent_hook_scopes.py
tests/test_command_builtins.py
tests/test_cli.py
```

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| Worktree 根 | 固定 `.mycode/worktrees/` | 缩小配置和路径攻击面，满足仓库内忽略目录要求 |
| 任务名称 | `tasks/<system-task-id>` | 系统生成、可嵌套、无 LLM 路径输入 |
| 分支 | `mewcode/worktree/<task-id>` | 与任务一一对应，便于本地远端跟踪引用判断 |
| 创建基线 | Agent 调用时的当前 `HEAD` | 排队期间主分支变化不改变任务输入 |
| 恢复分流 | 先看目标是否存在；存在走纯文件系统，缺失才调用 Git | 严格满足快速恢复不调用 Git |
| Git 接口 | 参数数组、`shell=False`、显式 cwd、统一超时 | 防命令注入并保证可测试边界 |
| Git 能力 | 启用 Worktree 时做只读能力探测，不只比较版本号 | 兼容不同发行版回移功能 |
| Worktree 枚举 | `git worktree list --porcelain -z` | Git 官方稳定机器格式 |
| 创建保护 | `git worktree add --lock --no-track -b` | 初始化前防 prune，并避免自动 upstream 推断 |
| 身份 | 主记录、目录标记、`.git` 指针三方匹配 | 单份记录不足以证明目录身份 |
| 身份内容 | 不持久化配置文件内容或秘密可逆摘要 | 快速恢复直接比较安全源与目标，不保存秘密证据 |
| 写入 | 临时文件、flush、`fsync`、原子替换 | 避免崩溃留下看似完整的记录 |
| 锁 | 进程内锁加 OS advisory 文件锁 | 同时防线程竞争和多进程误清理 |
| 初始化 | 配置驱动，默认规则可选，冲突失败关闭 | 兼顾开箱行为和项目差异 |
| copy 安全 | 目标必须被 Git ignore；目录有文件数和字节上限 | 避免初始化制造业务变更或无界复制 |
| symlink 安全 | 只链接经验证的主工作区源 | 不跟随不明链接，不重复大型依赖 |
| hooks | Git 运行时配置环境注入 `core.hooksPath` | 不启用 `extensions.worktreeConfig`，不修改共享 `.git/config` |
| 子进程环境 | 保存不可变环境 overlay，执行时与当前进程环境合并 | 不复制或持久化整个含密钥环境 |
| cwd | 每次工具、Git、Hook 调用显式传参 | 禁止 `chdir` 带来的并发全局状态 |
| 上下文缓存 | 规范化绝对 Worktree 路径进入所有 key | 同名相对文件不会跨 Worktree 命中 |
| 主工作区搜索 | 专用文件与搜索工具跳过 `.mycode/worktrees/` | 避免把子 Agent 文件纳入主任务结果 |
| 主命令保护 | 拒绝显式访问 Worktree 根，以及针对其祖先的已知递归破坏命令 | 防止 `rm -r .mycode`、`find ... -delete`、破坏性 `git clean` 等误删隔离目录 |
| 普通 shell 风险 | 继续经过现有权限和黑名单，不宣称提供容器级恶意代码隔离 | 本阶段是 Git 工作区隔离，不是 OS 沙箱 |
| 业务变更 | Git 已跟踪变化和未忽略未跟踪文件 | 受管初始化的 ignored 文件不阻止清理 |
| 送达远端 | 同名本地远端跟踪引用或可靠 upstream | 不把推送到无关分支误判为安全 |
| 网络 | 清理只读本地 refs | 避免后台清理触发凭据、延迟或外部副作用 |
| 删除 | 重新三层验证，`worktree remove` 不用 `--force` | Git 与系统保护双重生效 |
| 分支删除 | `git update-ref -d <ref> <expected-old>` | 引用被并发移动时不误删 |
| 取消 | 运行中进入 `cancelling`，退出检查后才终态和通知 | 任务状态不能早于数据保护完成 |
| Janitor | 启动扫描加单后台线程周期扫描 | 可处理重启遗留，同时控制 Git 并发 |
| 用户入口 | 复用现有 `Task` 与 `/tasks` 查询，不增加管理 action | 满足只做内部生命周期的范围约束 |
| 外部依赖 | 不新增依赖 | 标准库和 Git 已足够，降低安装与供应链成本 |

## Spec 覆盖关系

| Spec | 设计覆盖 |
|---|---|
| F1 | 角色解析、不可变角色快照、共享与 Fork 兼容分流 |
| F2–F6 | paths、GitRunner、双身份、创建回滚、纯文件系统恢复 |
| F7–F9 | WorkspaceContext、显式 cwd、绝对路径缓存 key |
| F10–F15 | 配置模型、Initializer、默认规则、manifest 和幂等恢复 |
| F16–F22 | Inspection、Disposition、保护性删除、任务摘要 |
| F23–F27 | Janitor、三层过滤、目标锁和无网络清理 |
| N1–N4 | 失败关闭路径、双身份、原子写入、数据优先策略 |
| N5–N6 | 共享模式回归、环境 overlay、脱敏诊断 |
| N7–N8 | Git 超时、有界 Janitor、仅本地引用 |
| N9–N10 | 复制上限、链接校验、单任务故障隔离 |
| N11–N12 | 临时仓库测试、能力探测、完整回归、不新增服务 |
| AC1–AC9 | 角色、创建、恢复、cwd、缓存隔离测试 |
| AC10–AC16 | 配置与初始化矩阵、三种退出终态测试 |
| AC17–AC21 | 自动清理、修改或提交保留、任务查询测试 |
| AC22–AC30 | 启动或周期清理、三层过滤、崩溃和故障隔离测试 |
| AC31–AC33 | 并行端到端、完整回归和超时测试 |

## 依赖方向与一致性约束

依赖保持单向：

```text
worktrees.models / worktrees.paths
  ← worktrees.git / worktrees.identity / worktrees.locking
  ← worktrees.initializer / worktrees.context / worktrees.manager
  ← worktrees.janitor
  ← agents.models / agents.worktree_executor
  ← agents.tasks / agents.tools / cli
```

- `worktrees` 包不得导入任何 `agents` 模块；任务适配器位于 `agents.worktree_executor`，任务状态通过模型和回调边界传递。
- `agents.runner` 不负责创建或删除 Worktree，只消费已构造的 `ChildWorkspaceContext`。
- Janitor 不依赖任务记录内容判断安全，只用目标锁判断活跃占用，再执行完整三层检查。
- 快速恢复、正常退出和后台清理复用同一身份校验器；不得存在宽松的第二条恢复或删除路径。
- 所有失败诊断只包含阶段、受管任务 ID、必要路径和错误类型，不包含复制文件内容、环境变量值或 Git 凭据。
