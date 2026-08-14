# MewCode 长期团队协作 Plan

## 架构概览

### 1. 团队控制面

新增独立的 `mycode.teams` 包承载长期团队领域，不把团队成员塞入现有 `AgentTaskManager`。现有后台子 Agent 保持进程内、短生命周期语义；团队控制面负责跨重启的团队绑定、花名册、成员状态、共享任务、邮箱、审批、审计和集成记录。

普通 CLI 始终注册 `/team` 用户命令，但普通主 Agent 不注册团队工具。`/team create|resume|switch` 成功后创建一个可信的会话到团队绑定，并由主 `AgentRunner` 在每次请求构造工具注册表时注入稳定的 Lead 工具集合。`/team status|archive` 读取或终结当前绑定。执行 `/new` 只更换主对话会话，不删除团队；新会话需要用户显式恢复团队后才能重新成为 Lead。

### 2. 文件型持久化与事务边界

每个活动团队使用 `~/.mycode/teams/<team-name>/`，归档团队移动到 `~/.mycode/teams-archive/<team-name>-<timestamp>/`。活动目录包含：

```text
team.json                    # 团队、Lead、仓库和成员花名册快照
tasks.json                   # 共享任务及版本快照
approvals.json               # 计划版本和审批快照
integrations.json            # 已集成成果与集成事务快照
mailboxes/<member>.jsonl     # Lead 和每名成员的独立邮箱
contexts/<member>.jsonl      # 成员规范化消息历史
audit.jsonl                  # 追加式审计事件
.locks/team.lock             # 团队级跨进程写锁
.locks/member-<member>.lock  # 成员运行独占锁
```

所有记录带 `schema_version`。快照更新在团队锁内执行“读取当前版本 → 校验期望版本 → 写同目录临时文件 → flush/fsync → 原子替换 → fsync 目录”；JSONL 记录以单行追加、flush 和 fsync 提交。跨快照的业务转换先生成单个事务意图写入审计，再在同一团队锁内提交所有快照；恢复器按事务 ID 检测并保守拒绝未完整提交的转换，不猜测任务、消息或审批状态。邮箱投递只要求目标单邮箱原子追加；广播按收件人分别提交并汇报部分失败。

### 3. 团队 Worktree 管理

在现有 `mycode.worktrees` 安全路径、Git 探测、初始化和文件锁基础上增加长期成员租约，不改变一次性子 Agent 的任务 worktree。团队成员使用受管名称 `teams/<team>/<member>` 和分支 `refs/heads/mewcode/team/<team>/<member>`；身份记录仍校验仓库 ID、主工作区、预期 gitdir、基线提交和初始化指纹。

成员完成任务时不释放 worktree。成功集成后，长期分支只有在工作区干净且无未记录成果时才快进或安全重放到新 Lead 基线；失败则保留原分支和工作区并把成员置为需要处理状态。团队归档复用保护性检查，任何未提交或未集成成果都会阻止清理。

### 4. 成员运行核心与后端适配器

`TeamMemberRuntime` 是后端无关的成员运行核心：加载角色快照、成员上下文、未读邮箱和任务/审批状态，构造独立 `AgentRunner`、权限服务、上下文管理器及团队成员工具注册表，运行到自然完成、失败、取消或空闲，然后持久化规范化上下文和终态通知。它不恢复临时批准或在途工具调用。

运行后端统一实现探测、启动、唤醒、停止和状态查询协议：

- `TmuxBackend` 检查 tmux 可执行文件、服务可用性和 pane 创建能力，在独立 pane 中启动内部 `team-worker` 子命令，并持久化 session/window/pane ID；唤醒通过 pane ID 发送专用信号，不模拟自然语言输入。
- `CoroutineBackend` 在 Lead 进程的受控执行器中调用同一个 `TeamMemberRuntime`，使用独立取消令牌、权限实例和上下文；可写成员仍进入自己的长期 worktree。
- `BackendSelector` 对显式后端只探测指定项并失败关闭；`auto` 固定按 tmux、coroutine 排序，返回全部探测诊断和最终选择。

内部入口 `mycode team-worker --team <team> --member <member>` 只接受规范化标识，从团队注册表取得可信身份，并在运行前取得成员独占锁。空闲 worker 自然退出；新任务或消息发现目标离线时，由已绑定 Lead 的后端管理器重新启动，避免重复 worker。

### 5. 共享任务、邮箱与审批服务

`SharedTaskService` 在团队锁内维护带乐观版本的任务图，负责权限、状态机、负责人、依赖存在性与环检测、就绪计算、工作记录和逻辑删除。依赖阻塞与可开始状态由持久状态和依赖快照确定，不交给模型自行判断。

`MailboxService` 先从 `team.json` 的名称注册表解析规范化收件人，再向对应 JSONL 邮箱追加带唯一消息 ID、可信发件人、服务端时间戳、未读状态、摘要和可选协议载荷的记录。每名收件人的读取游标和确认记录持久化在花名册中；恢复时按游标注入有界批次，只有成功写入成员上下文后才推进确认位置。运行目标通过后端适配器唤醒，唤醒失败不回滚已持久化消息。

`ApprovalService` 管理不可变计划版本与决定。成员侧副作用能力在任务需要审批且没有精确匹配的批准时被策略层移除；Lead 只能通过结构化审批动作写入批准或驳回。计划正文变化创建递增版本并使旧批准失效，批准后仍继续经过现有权限与沙箱。

### 6. 身份化工具注册表

团队工具对象在运行时启动时注册一次，schema 不随团队状态变化；每次主请求只根据可信绑定和既有 Plan/Do 模式选择固定工具子集：

- Lead：`TeamMember`、`SharedTask`、`Mailbox`、`TeamIntegrate`。
- 团队成员：成员版 `SharedTask` 与 `Mailbox`，名称保持相同但使用独立、固定的成员 schema，仅包含成员允许的动作。
- 普通主入口、普通一次性子 Agent：无团队工具。

Plan 模式使用只读 Lead 变体，只含成员/任务/邮箱查询及集成 preflight/get，不暴露任何团队写动作；Do 模式使用完整 Lead 变体。工具调用不接受可伪造的 `team_id`、`sender` 或 `actor`；这些值由绑定或 worker 身份注入。Lead、Plan 只读和成员版工具分别构造，避免把无权动作暴露后再运行时拒绝。团队工具作为动态调用工具接入现有权限目标解析，但领域服务仍执行第二层身份与状态校验。

### 7. Lead 编排与原子集成

Lead 通过共享任务服务建立 DAG、指派成员并启动全部就绪任务。成员状态通知进入 Lead 邮箱；主 Agent 在两次 Provider 请求之间读取并确认这些消息，不自动触发空闲 Lead 的模型请求。

`IntegrationService` 在专用受管 worktree 和临时分支上创建集成事务，冻结 Lead 基线、任务拓扑与每名成员待集成提交，按拓扑稳定排序合并并运行配置的验证命令。开始与最终推进前都要求 Lead 工作区干净且 HEAD 等于冻结基线。全部成功后以 `git merge --ff-only` 将 Lead 工作区推进到临时结果，再记录集成和同步成员基线；任一步失败则执行 `git merge --abort` 或删除临时 worktree/分支，Lead 原分支保持不变。冲突诊断只读返回，由 Lead 创建成员修复任务后重试。

### 8. Coordinator 能力收缩

在 `teams.coordinator.enabled` 配置和 `MEWCODE_COORDINATOR=1` 环境变量同时成立且会话已绑定团队时启用 coordinator。工具注册表先移除写文件和普通 `run_command`，再加入 `CoordinatorCommand`：其 `run(argv)` 拒绝 shell 运算符、重定向、变量展开、脚本解释器和子进程包装，只允许固定只读命令；`verify(command_id)` 只能解析用户配置中已校验的验证命令。两条路径都以参数数组、`shell=False` 执行。

Git 写操作不通过任意 argv 放行。`CoordinatorCommand git(integration_id, operation)` 与 `TeamIntegrate` 共同调用参数化的 `ScopedIntegrationGitExecutor`；operation 只能是集成状态机当前允许的 `merge_next`、`abort_merge`、`stage_integration`、`commit_integration` 或 `advance_lead`，目标 worktree、ref、commit、路径集合和提交信息全部从冻结的 IntegrationRecord 解析。Lead 可通过 `CoordinatorCommand run` 查看 Git 状态、差异和冲突，但源码修改必须创建任务交给成员。工具子集、命令策略和现有权限服务三层共同执行限制，所有拒绝进入审计。

### 9. 生命周期与故障隔离

CLI 组合根负责创建 `TeamRuntime`，把团队命令、主 Agent 动态工具提供器、后端管理器和关闭钩子连接起来。关闭时先冻结新调度，再取消协程成员、请求 tmux worker 停止、等待有界收尾并持久化离线状态，最后关闭现有后台任务、MCP、Hook、记忆和 Provider 资源。

团队目录损坏、schema 不兼容或事务不完整只阻止对应团队恢复。成员启动、邮箱唤醒、审计或集成失败都返回带团队、成员、任务、消息或集成 ID 的结构化诊断；不关闭其他成员、其他团队或普通会话。

## 核心数据结构

以下模型均使用冻结 dataclass 和显式 `Literal` 状态；持久化时只写 JSON 基本类型、ISO 8601 含时区时间和规范化相对路径。所有外部输入先规范化为内部 ID，服务层不以任意字符串拼接路径。

### TeamConfig

新增到 `AppConfig.teams`，缺省时启用团队基础能力但 coordinator 默认关闭：

```python
TeamConfig(
    max_members=8,                    # 1..32
    max_tasks=1_000,                  # 1..10_000
    max_dependencies_per_task=32,     # 0..128
    max_message_chars=20_000,         # 1..100_000
    message_summary_chars=240,        # 32..1_000
    mailbox_batch_size=50,            # 1..500
    max_mailbox_bytes=52_428_800,     # 每成员，1 MiB..1 GiB
    max_context_bytes=104_857_600,    # 每成员，1 MiB..2 GiB
    max_work_log_entries=1_000,       # 每任务，1..10_000
    lock_timeout_seconds=5.0,
    shutdown_timeout_seconds=5.0,
    backend_start_timeout_seconds=10.0,
    integration_timeout_seconds=300.0,
    verification_commands=(),         # tuple[VerificationCommand, ...]
    coordinator=CoordinatorConfig(enabled=False),
)
```

所有数值有解析上限；单条验证命令包含唯一 ID、非空 argv 和有界 timeout，禁止 shell 控制符与环境展开，并始终 `shell=False`。验证命令来自用户配置，因此可以显式使用 `python3 -m pytest` 等解释器调用；模型只能引用 ID，不能改写 argv。邮箱或上下文达到硬上限时拒绝继续追加并通知 Lead，不静默截断或覆盖未审计内容；用户需完成集成后归档团队。无自定义命令时集成仍执行内置 Git 一致性检查和 `git diff --check`。

### TeamSnapshot

```python
TeamSnapshot(
    schema_version: int,
    revision: int,
    name: str,
    status: Literal["active", "freezing", "archive_ready", "archived"],
    lead_name: str,
    repository_id: str,
    workspace_root: str,
    lead_branch_ref: str,
    created_at: datetime,
    updated_at: datetime,
    members: Mapping[str, TeamMemberSnapshot],
    last_transaction_id: str,
)
```

`name` 同时是规范化团队标识，只允许小写字母、数字、`_`、`-`，长度 1–64；显示名称本阶段不另设。`lead_name` 固定为保留身份 `lead`，不可被成员占用。`workspace_root` 保存创建时绝对规范路径，恢复时必须重新验证仓库 ID 和 Git 公共目录。

### TeamBinding

```python
TeamBinding(
    session_id: str,
    team_name: str,
    actor: LeadIdentity,
    coordinator_enabled: bool,
    bound_at: datetime,
)
```

绑定仅存在于当前进程，不写入主会话历史；`/team create|resume|switch` 构造，`/new`、切换和归档清除。`LeadIdentity` 与 `MemberIdentity` 由运行时签发，包含团队名、主体名、仓库 ID 和不可由工具参数构造的随机 capability token。

### AgentRoleSnapshot

```python
AgentRoleSnapshot(
    name: str,
    description: str,
    allowed_tools: tuple[str, ...],
    denied_tools: tuple[str, ...],
    model: ModelTier,
    max_iterations: int,
    permission_mode: ChildPermissionMode,
    system_prompt: str,
    source: AgentSource,
    source_id: str,
    fingerprint: str,
    isolation: Literal["shared", "worktree"],
)
```

该模型是现有 `AgentDefinition` 的可持久化冻结副本。添加或升级成员时从 `AgentCatalog` 当前快照复制并重新校验工具与模型映射；成员运行不回读源角色文件。

### TeamMemberSnapshot

```python
TeamMemberSnapshot(
    member_id: str,
    name: str,
    revision: int,
    role: AgentRoleSnapshot,
    writable: bool,
    approval_required: bool,
    backend_preference: Literal["auto", "tmux", "coroutine"],
    actual_backend: Literal["tmux", "coroutine"] | None,
    backend_diagnostics: tuple[BackendDiagnostic, ...],
    lifecycle: Literal[
        "provisioning", "offline", "starting", "running",
        "waiting_approval", "blocked", "idle", "stopping",
        "failed", "needs_attention",
    ],
    current_task_id: str | None,
    worktree: TeamWorktreeIdentity | None,
    process: MemberProcessIdentity | None,
    mailbox_cursor: int,
    context_sequence: int,
    created_at: datetime,
    updated_at: datetime,
)
```

`member_id` 为创建时生成的稳定随机 ID，重命名本阶段不支持；目录和分支使用规范化名称加 ID 摘要避免碰撞。`MemberProcessIdentity` 对 tmux 保存 server socket、session、window、pane ID 和 pane PID，对 coroutine 保存本进程内运行 token；这些字段只用于探测，不能单独证明 worker 身份。

### TeamWorktreeIdentity

扩展现有 `WorktreeIdentity` 的验证字段并替换一次性 `task_id`：

```python
TeamWorktreeIdentity(
    schema_version: int,
    repository_id: str,
    team_name: str,
    member_id: str,
    managed_name: str,
    main_workspace: str,
    worktree_path: str,
    branch_ref: str,
    base_commit: str,
    integrated_commit: str,
    expected_gitdir: str,
    initialization_fingerprint: str,
    lifecycle_state: Literal["creating", "active", "retained", "cleanup_failed"],
    created_at: datetime,
    last_active_at: datetime,
)
```

`integrated_commit` 是该成员最后一次成功纳入 Lead 的提交边界，用于计算尚未集成成果和幂等重试。

### SharedTaskRecord

```python
SharedTaskRecord(
    task_id: str,                     # team_task_<16 hex>
    revision: int,
    title: str,
    description: str,
    status: Literal[
        "pending", "dependency_blocked", "waiting_approval", "ready",
        "running", "blocked", "completed", "cancelled",
    ],
    assignee_id: str | None,
    dependency_ids: tuple[str, ...],
    creator: ActorRef,
    work_log: tuple[TaskWorkEntry, ...],
    plan_version: int | None,
    result_commit: str | None,
    integrated_by: str | None,
    deleted_at: datetime | None,
    created_at: datetime,
    updated_at: datetime,
)
```

`revision` 是乐观并发令牌，所有更新必须携带 `expected_revision`。`dependency_blocked` 与 `ready` 由服务在每次依赖终态变化时同事务重算；`result_commit` 必须属于负责人长期分支且位于 `integrated_commit` 之后。`integrated_by` 指向成功集成事务，避免重复纳入。

### MailboxRecord

邮箱 JSONL 使用两类事件，序号在单邮箱内严格递增：

```python
MailboxMessage(
    schema_version: int,
    record_type: Literal["message"],
    sequence: int,
    message_id: str,
    sender: ActorRef,
    body: str,
    timestamp: datetime,
    read: Literal[False],
    summary: str,
    protocol: ProtocolPayload | None,
    idempotency_key: str,
)

MailboxAck(
    schema_version: int,
    record_type: Literal["ack"],
    sequence: int,
    message_id: str,
    reader: ActorRef,
    timestamp: datetime,
)
```

读取模型将存在合法 `MailboxAck` 的消息投影为 `read=true`；原消息不可就地改写。`idempotency_key` 在收件箱内唯一，重试返回原消息 ID。协议载荷为四个带判别字段的联合类型：`TaskAssignmentPayload`、`PlanApprovalRequestPayload`、`PlanDecisionPayload`、`TaskStatusPayload`。自由文本消息的 `protocol` 为 `None`。

### ApprovalRecord

```python
ApprovalRecord(
    task_id: str,
    member_id: str,
    plan_version: int,
    plan_fingerprint: str,
    plan_body: str,
    status: Literal["pending", "approved", "rejected", "superseded"],
    requested_at: datetime,
    decided_at: datetime | None,
    decided_by: ActorRef | None,
    reason: str,
    decision_message_id: str | None,
)
```

主键是 `(member_id, task_id, plan_version)`。提交新计划先冻结正文并计算 fingerprint，再在同一团队事务中把旧 pending/approved 版本标为 `superseded`、任务置为 `waiting_approval` 并发送请求。批准事务校验 Lead 身份、当前任务负责人、版本与 fingerprint 全部一致。

### MemberContextRecord

```python
MemberContextRecord(
    schema_version: int,
    sequence: int,
    timestamp: datetime,
    message: Message,
    source_message_ids: tuple[str, ...],
)
```

只追加现有 `Message` 的有效规范化前缀。带工具调用的 Assistant 消息必须紧跟全部对应 Tool 消息才算一个可提交批次；进程中断时尾部不完整批次在恢复时截断。邮箱消息成功形成 user 输入并提交上下文后，才追加对应 ack 并推进成员游标。

### IntegrationRecord

```python
IntegrationRecord(
    integration_id: str,
    revision: int,
    status: Literal[
        "preparing", "merging", "validating", "ready_to_advance",
        "advancing", "completed", "conflicted", "failed", "aborted",
    ],
    lead_branch_ref: str,
    base_commit: str,
    task_ids: tuple[str, ...],
    member_commits: Mapping[str, tuple[str, ...]],
    integration_branch_ref: str,
    integration_worktree: str,
    merged_commit: str | None,
    verification_results: tuple[VerificationResult, ...],
    conflict_paths: tuple[str, ...],
    failure_reason: str,
    created_at: datetime,
    finished_at: datetime | None,
)
```

进入 `ready_to_advance` 后再次确认 Lead HEAD 和工作区干净；推进成功才把任务 `integrated_by` 与成员 `integrated_commit` 更新到同一事务 ID。进程在推进边界崩溃时，恢复器比较 Git ref 与记录：只有 ref 明确等于冻结基线或已验证合并提交时才能确定性补记，否则标记 `needs_attention` 并拒绝自动继续。

### AuditEvent

```python
AuditEvent(
    schema_version: int,
    event_id: str,
    transaction_id: str,
    timestamp: datetime,
    actor: ActorRef,
    action: str,
    object_type: str,
    object_id: str,
    outcome: Literal["intent", "committed", "rejected", "failed"],
    reason_code: str,
    summary: str,
)
```

审计只保存 ID、状态和有界摘要，不保存计划正文、完整消息、命令参数、提示正文、权限目标或凭据。

## 核心接口

### TeamStore

```python
class TeamStore(Protocol):
    def create(self, request: TeamCreateRequest) -> TeamSnapshot: ...
    def load(self, team_name: str) -> TeamAggregate: ...
    def transact(
        self,
        team_name: str,
        expected_revisions: RevisionSet,
        mutation: Callable[[TeamAggregate], TeamAggregate],
    ) -> TeamAggregate: ...
    def append_mailbox(self, team_name: str, recipient: str, record: MailboxRecord) -> int: ...
    def append_context(self, team_name: str, member: str, records: Sequence[MemberContextRecord]) -> int: ...
    def archive(self, team_name: str, expected_revision: int) -> Path: ...
```

`TeamAggregate` 一次加载团队、任务、审批和集成快照，并验证 schema、事务 ID 与交叉引用。所有读取都在团队锁内取得一致视图；回调不得执行 Provider、tmux 或 Git 等外部操作。

### TeamBindingManager

```python
bind(session_id, team_name) -> TeamBinding
switch(session_id, team_name) -> TeamBinding
current(session_id) -> TeamBinding | None
clear(session_id) -> None
```

绑定前验证团队活动状态、仓库身份和 Lead 工作区；coordinator 判定只在 bind/switch 时从已解析配置与进程环境计算，不接受工具参数覆盖。

### TeamService

```python
create_team(name, actor_context) -> TeamSnapshot
resume_team(name, actor_context) -> TeamSnapshot
freeze_for_archive(identity) -> ArchiveReadiness
archive_team(identity, expected_revision) -> ArchiveResult
add_member(identity, MemberCreateRequest) -> TeamMemberSnapshot
upgrade_member(identity, member_id, expected_revision) -> TeamMemberSnapshot
start_member(identity, member_id) -> BackendStartResult
stop_member(identity, member_id) -> MemberStopResult
status(identity) -> TeamStatusView
```

服务编排存储、角色目录、长期 worktree 和后端，但外部操作使用显式 `preparing` 状态和补偿清理，绝不在持有团队文件锁时调用慢操作。

### SharedTaskService

```python
list_tasks(identity, query) -> tuple[SharedTaskView, ...]
get_task(identity, task_id, include_deleted=False) -> SharedTaskView
create_task(identity, request) -> SharedTaskView
update(identity: LeadIdentity, request, expected_revision) -> SharedTaskView
update_own(identity: MemberIdentity, request, expected_revision) -> SharedTaskView
assign(identity: LeadIdentity, task_id, member_id, expected_revision) -> SharedTaskView
set_dependencies(identity: LeadIdentity, task_id, dependency_ids, expected_revision) -> SharedTaskView
request_start(identity: MemberIdentity, task_id, expected_revision) -> StartDecision
complete(identity: MemberIdentity, task_id, result_summary, expected_revision) -> SharedTaskView
start_ready(identity: LeadIdentity, task_ids=()) -> tuple[StartDecision, ...]
cancel(identity: LeadIdentity, task_id, expected_revision) -> SharedTaskView
delete(identity: LeadIdentity, task_id, expected_revision) -> SharedTaskView
```

环检测对包含候选边的完整未删除 DAG 执行确定性 DFS；批量 `start_ready` 按拓扑层和任务 ID 稳定排序，单个启动失败不回滚其他已经启动的独立任务，但逐项报告。

### MailboxService

```python
send(identity, recipient, body, protocol=None, idempotency_key=None) -> DeliveryResult
broadcast(identity, body, protocol=None, idempotency_key=None) -> BroadcastResult
list_messages(identity, unread_only=True, limit=None) -> tuple[MailboxMessageView, ...]
get_message(identity, message_id) -> MailboxMessageView
ack(identity, message_ids) -> AckResult
reserve_unread(identity, limit) -> MailboxLease
commit_lease(identity, lease_id, context_sequence) -> AckResult
release_lease(identity, lease_id) -> None
```

运行时使用 reserve/commit 两阶段读取，工具查询不推进运行时游标。`send` 成功持久化后在锁外调用后端唤醒；唤醒失败作为 delivery warning 返回，不改变消息提交结果。

### ApprovalService

```python
submit_plan(identity: MemberIdentity, task_id, plan_body, expected_task_revision) -> ApprovalRecord
decide(identity: LeadIdentity, task_id, member_id, plan_version, decision, reason) -> ApprovalRecord
effective_approval(member_id, task_id, plan_version, fingerprint) -> ApprovalRecord | None
invalidate_for_task_change(task_id, reason) -> tuple[ApprovalRecord, ...]
```

`decide` 同事务写决定、任务状态和结构化邮箱消息。成员 runner 在每轮构造工具策略前查询 `effective_approval`；无匹配批准时仅保留读取、任务、邮箱和提交计划能力。

### TeamMemberBackend

```python
class TeamMemberBackend(Protocol):
    name: Literal["tmux", "coroutine"]
    def probe(self, request: BackendProbeRequest) -> BackendProbeResult: ...
    def start(self, member: TeamMemberSnapshot) -> BackendStartResult: ...
    def wake(self, member: TeamMemberSnapshot, message_id: str) -> BackendWakeResult: ...
    def stop(self, member: TeamMemberSnapshot, timeout_seconds: float) -> MemberStopResult: ...
    def inspect(self, member: TeamMemberSnapshot) -> BackendStatus: ...
```

`TmuxBackend.wake` 通过 tmux 查询已记录 pane 的 PID 并发送 worker 专用 `SIGUSR1`；pane 身份或 PID 不匹配时不发送信号。`CoroutineBackend` 使用进程内 condition/event。两者都依赖成员锁实现单实例，不能只信任 pane 或 future 状态。

### TeamMemberRuntime

```python
run(identity: MemberIdentity, cancellation: CancellationToken) -> MemberRunOutcome
```

运行步骤固定为：验证身份和长期 worktree → 取得成员锁 → 恢复有效上下文前缀 → reserve 未读消息 → 构造当前任务与审批提示 → 构造成员固定工具注册表 → 运行 `AgentRunner` → 原子追加完整消息批次 → commit 邮箱 lease → 更新任务/成员状态并通知 Lead → 释放锁。没有待处理消息或可运行任务时直接返回 idle。

### TeamToolRegistryProvider

```python
for_lead(base: ToolRegistry, binding: TeamBinding, mode: PromptMode) -> ToolRegistry
for_member(base: ToolRegistry, identity: MemberIdentity, policy: MemberPolicy) -> ToolRegistry
```

Lead 默认从主 registry 合并四个团队工具；coordinator 先移除写工具和普通命令，再合并 `CoordinatorCommand` 与四个团队工具。成员先应用角色白黑名单、全局嵌套禁止和审批策略，再合并固定成员版 `SharedTask`、`Mailbox`；普通 Agent/Fork 路径不调用该 provider。

### IntegrationService

```python
preflight(identity: LeadIdentity, task_ids=()) -> IntegrationPlan
start(identity: LeadIdentity, plan: IntegrationPlan) -> IntegrationRecord
get(identity: LeadIdentity, integration_id: str) -> IntegrationRecord
abort(identity: LeadIdentity, integration_id: str) -> IntegrationRecord
recover(team_name: str) -> tuple[IntegrationRecoveryResult, ...]
```

`IntegrationPlan` 冻结 revision、Lead HEAD、任务拓扑、负责人、成员 branch 与 commit 集合。`start` 不接受模型直接提供任意 ref、路径或 Git 参数；所有对象必须来自 preflight 结果并再次校验。Git 命令均通过现有 `GitRunner` 的参数数组扩展执行。

### CoordinatorCommandPolicy

```python
validate_read(argv: Sequence[str], binding: TeamBinding) -> CoordinatorCommandDecision
resolve_verification(command_id: str, binding: TeamBinding) -> CoordinatorCommandDecision
resolve_git_operation(integration_id: str, operation: str, binding: TeamBinding) -> ScopedGitDecision
execute(decision: CoordinatorCommandDecision, context: ToolContext) -> ToolExecutionResult
```

只读命令仅接受 JSON 参数数组，不接受命令字符串。硬编码只读集合包括受限的 `pwd`、`rg` 和 `git status|diff|log|show|rev-parse|branch --show-current`；禁止控制符、重定向、环境赋值、解释器、`-c`、Git alias、外部 diff/textconv、hooks 和分页器。验证命令不由模型任意拼装，只能引用配置加载时生成的命令 ID，并在受管集成 worktree 中执行；执行前后检查 Git 状态，出现非预期修改即失败并丢弃临时集成结果。Git 写操作只能引用活动 integration ID 和固定 operation，executor 从冻结记录解析全部参数并重验状态机；`stage_integration` 只接受该集成步骤已产生且无未合并状态的路径集合，不能由模型提供路径。

## 模块设计

### `mycode.teams.paths` 与 `mycode.teams.locking`

**职责：** 规范化团队名、成员名和对象 ID；解析活动、归档、邮箱、上下文、事务、锁和审计路径；拒绝绝对路径、保留名、符号链接与目录逃逸。提供线程锁与 `fcntl.flock` 组合的团队锁和成员运行锁。

**对外接口：** `validate_team_name`、`validate_member_name`、`team_root`、`mailbox_path`、`context_path`、`TeamLock`、`MemberRunLock`。

**依赖：** Python 标准库；路径安全规则与现有 `worktrees.paths` 保持同一风格，但用户根和项目 worktree 根分别校验。

### `mycode.teams.storage`

**职责：** 严格解析/序列化所有版本化 JSON/JSONL 记录，提供一致 aggregate 读取、乐观 revision 和可恢复跨文件事务。

每个事务先在 `.transactions/<transaction-id>/` 写入 `manifest.json`、所有目标文件的 before hash 和完整 after 文件，全部 fsync 后追加 intent 审计；随后原子替换目标并追加 committed 审计。恢复时逐个目标只接受 before hash 或 after hash：若均可识别则确定性完成向前提交；出现第三种内容、缺失 staged after 或 schema 不兼容则把团队标记为不可恢复并拒绝写入。邮箱追加也以 staged 单行和 idempotency key 纳入事务，重复恢复不会产生第二条消息。

**对外接口：** `FileTeamStore`、严格 loader/dumper、`recover_transactions`、`validate_aggregate`。

**依赖：** `paths`、`locking`、`models`。业务审计事件由调用方作为 staged JSONL 记录传入，storage 不导入 audit。

### `mycode.teams.audit`

**职责：** 生成无敏感字段的审计事件，执行长度限制、reason code 规范化、追加与读取。失败审计不能伪装业务成功；对于安全关键写入，审计 intent 无法落盘时事务不开始。

**对外接口：** `AuditWriter.intent|commit|reject|fail`、`AuditReader.list`。

**依赖：** `storage` 的 JSONL 原语，不反向调用领域服务。

### `mycode.teams.binding`

**职责：** 维护当前进程中 `session_id -> TeamBinding`，签发 Lead capability，计算 coordinator 双锁状态，并在切换、`/new`、归档和退出时撤销旧 capability。

**对外接口：** `TeamBindingManager`。

**依赖：** `storage` 只读加载、仓库身份验证、解析后的 `TeamConfig`。

### `mycode.teams.service`

**职责：** 团队创建、恢复、状态、成员添加/升级/启动/停止以及保护性归档的应用服务。慢速 Git/tmux 操作采用“锁内记录 preparing → 锁外执行 → 锁内校验 revision 并提交结果”的 saga；补偿动作只清理由本事务新建且身份完全匹配的资源。

成员启动前创建一次性 `WorkerLaunchTicket`，仅在 `team.json` 保存 hash 和到期时间，原文写入权限为 `0600` 的临时票据文件。tmux worker 使用 `--ticket-file` 消费并删除票据；协程后端直接接收内存 capability。模型工具不能提供或读取 capability。

**对外接口：** `TeamService`。

**依赖：** 角色目录、`TeamStore`、`TeamWorktreeManager`、后端选择器、审计。

### `mycode.teams.tasks`

**职责：** 任务 CRUD、Actor 权限、状态机、DAG 环检测、依赖就绪重算、逻辑删除、工作记录、结果提交校验和集成标记。

任务完成请求对可写成员执行 Git 前置校验：工作区必须干净、HEAD 必须位于成员分支、相对 `integrated_commit` 必须有新提交，并把 HEAD 固定为 `result_commit`；只读任务以持久化结果摘要完成。成员自然停止时 runtime 也执行同一确定性完成检查：满足条件则自动提交完成；不满足时不得声称完成，而是把成员置为 `needs_attention`，任务转为 `blocked` 并通知 Lead。

**对外接口：** `SharedTaskService`、`TaskStateMachine`、`TaskGraph`。

**依赖：** `storage`、`identity`、只读 Git inspector、注入的 `ApprovalLookup` 协议、审计。`ApprovalLookup` 在 tasks 中声明，approvals 实现，tasks 不导入 approvals 模块。

### `mycode.teams.mailbox`

**职责：** 名称注册表解析、单播、广播、结构化协议校验、摘要、幂等、message/ack 投影、两阶段 unread lease 和后端唤醒。

邮箱 lease 自身有随机 ID、消息序列集合和有界到期时间，保存在进程内并可从未 ack 记录重新构造；崩溃只会导致再次 reserve，不会丢消息。成员上下文记录携带 `source_message_ids`，恢复时若发现消息已进入有效上下文但缺 ack，则确定性补 ack，避免重复注入。

**对外接口：** `MailboxService`、四类 protocol parser。

**依赖：** `storage`、`identity`、注入的 `WakeNotifier` 协议、审计。`BackendManager` 实现唤醒回调，mailbox 不导入 backends。

### `mycode.teams.approvals`

**职责：** 不可变计划版本、fingerprint、提交、决定、失效、恢复和审批工具策略。审批请求与决定通过 `MailboxService` 的结构化载荷投递，但审批真值来自 `approvals.json`，不能仅凭消息正文推断。

**对外接口：** `ApprovalService`、`ApprovalToolPolicy`。

**依赖：** `storage`、`models`、`protocols`、审计。它直接在 aggregate mutation 中校验任务并构造 staged mailbox 记录，不导入 `SharedTaskService` 或 `MailboxService`，避免领域服务环。

### `mycode.teams.worktrees`

**职责：** 把现有一次性 worktree 的 GitRunner、路径验证、初始化器和身份检查组合为长期成员与临时集成 worktree 管理器。一次性 `WorktreeManager` API 和记录格式不改变。

**对外接口：** `TeamWorktreeManager.provision|recover|inspect|sync_baseline|dispose`、`IntegrationWorktreeManager.create|dispose`。

**依赖：** `mycode.worktrees.git|initializer|identity` 中可复用原语、团队存储和审计。

### `mycode.teams.backends`

**职责：** 后端协议、探测与确定性选择；tmux pane 生命周期、票据传递、PID/SIGUSR1 唤醒；协程 future、event 与 cancellation 生命周期。`BackendManager` 在状态变更前后同步成员快照，屏蔽后端差异。

`TmuxBackend` 所有调用使用参数数组和 `shell=False`，固定新建 `mewcode-<team>` session 与成员 window，读取 tmux 格式化字段取得 pane ID/PID。启动命令只含内部 worker 入口、规范化团队/成员 ID 和票据文件；不在命令行传 API key、提示或消息正文。

**对外接口：** `TeamMemberBackend`、`BackendSelector`、`BackendManager`。

**依赖：** subprocess、signal、`identity` 签发/校验的票据、成员状态 store；不导入 TeamService。

### `mycode.teams.member`

**职责：** 后端无关的 `TeamMemberRuntime`、成员 AgentRunner 工厂、上下文恢复、邮箱注入、审批 gating、终态收尾和 Lead 通知。

成员 runner 复用当前 Provider 工厂、Hook 工厂、上下文管理与工具执行器，但每次恢复都创建新的权限服务、文件读取缓存、取消令牌和 Token 累加器；不注册主会话 journal、长期记忆写入、`Agent`、现有 `Task` 或 `load_skill`。角色允许/拒绝列表先应用于普通业务工具，团队成员工具随后按可信身份固定加入。

**对外接口：** `TeamMemberRuntime`、`TeamMemberRunnerFactory`、`MemberRunOutcome`。

**依赖：** agents 角色/runner 原语、tasks、mailbox、approvals、worktrees、权限与上下文模块。

### `mycode.teams.integration`

**职责：** 集成 preflight、冻结输入、临时 worktree、拓扑合并、冲突收集、验证、Lead 快进、成员基线同步、幂等记录、abort 和崩溃恢复。

Git 操作全部使用参数数组；关闭 Git hooks、外部 diff/textconv、pager、credential prompt 和可配置 alias。验证命令仅来自加载后的配置 ID，在临时集成 worktree 中运行且有总超时。推进 Lead 前再次比较仓库 ID、branch ref、HEAD、clean status 和成员 commit；任何漂移都把事务标记失败而不尝试修正用户分支。

**对外接口：** `IntegrationService`。

**依赖：** tasks、长期/集成 worktree manager、扩展 GitRunner、storage、audit。

### `mycode.teams.coordinator`

**职责：** 双锁判定、Lead registry 收缩、参数数组命令校验、验证命令 ID 解析、受集成事务约束的 Git operation 解析和写入拒绝审计。普通 `RunCommandTool` 不复用，因为它使用 `shell=True`；coordinator 注册独立的 `CoordinatorCommandTool`，并与 `TeamIntegrate` 共享 `ScopedIntegrationGitExecutor`。

**对外接口：** `CoordinatorCommandPolicy`、`CoordinatorCommandTool`、`coordinator_enabled`。

**依赖：** ToolRegistry、ToolContext、binding、TeamConfig、audit。

### `mycode.teams.tools`

**职责：** 构造四个 Lead 工具和两个成员工具，解析 action 联合 schema，绑定可信 identity，把领域错误规范化为有 reason code 的 `ToolExecutionResult`。同名 Lead/成员工具是不同实例与固定 schema，不能在调用期间切换。

**对外接口：** `LeadTeamMemberTool`、`LeadSharedTaskTool`、`MemberSharedTaskTool`、`LeadMailboxTool`、`MemberMailboxTool`、`TeamIntegrateTool`、`TeamToolRegistryProvider`。

**依赖：** 团队领域服务；不直接读写 JSON 或调用 Git/tmux。

### `mycode.teams.commands` 与 `mycode.teams.runtime`

**职责：** `/team` 子命令解析与 UI 输出；CLI 组合根的服务装配、动态 binding 注入、Lead 邮箱 lease、成员后端跟踪和有界关闭。内部 `team-worker` 入口独立于 slash command 路由，仅供后端启动。

**对外接口：** `register_team_command`、`TeamRuntime`、`run_team_worker`。

**依赖：** CLI CommandUI 扩展、AgentRunner 动态 registry hook、Provider/Hook/权限工厂。

## 模块交互

### 创建、绑定与工具注入

1. 用户输入 `/team create <name>`；命令路由只解析名称，不调用模型。
2. `TeamService` 验证 Git 仓库、团队名、用户目录和同名冲突，创建 staged 初始快照并提交审计事务。
3. `TeamBindingManager` 校验团队与当前 workspace/repository ID 后签发 `LeadIdentity`，同时计算 coordinator 两把锁。
4. 下一次主请求进入 `AgentRunner._registry_for_request`：先应用现有 Skill/Plan 模式规则，再由 `TeamToolRegistryProvider` 根据当前 session binding 与模式合并完整或只读 Lead 工具；没有 binding 时完全不调用团队 provider。
5. Lead 邮箱在用户消息写主 session journal 前 reserve，有消息时以有界、带 ID 的系统化区块与本次 user 文本组合；主 session 成功持久化后才 ack，失败则 release。邮箱本身不唤醒空闲 Lead。

### 添加和启动成员

1. Lead 调用 `TeamMember add`，服务从当前 `AgentSnapshot` 复制角色，写 `provisioning` 成员并签发长期 worktree 请求。
2. 锁外创建和初始化 worktree；成功后提交 worktree 身份，失败则只清理本事务创建且身份匹配的资源，并移除或标记失败成员。
3. `BackendSelector` 对显式选择失败关闭；auto 顺序探测 tmux、coroutine，把每个诊断和实际选择写成员快照并返回 Lead。
4. 启动时签发一次性 worker ticket。tmux 在新 pane 启动 `team-worker`，coroutine 在受控执行器提交 runtime；worker 消费 ticket 并取得成员锁后，状态从 starting 变为 running。
5. 没有任务或未读消息时 runtime 立即提交 idle 并退出；后端 manager 清除易失 process identity，但保留 actual backend、上下文和 worktree。

### 任务创建、依赖与调度

1. Lead 或成员调用各自 `SharedTask create`；服务校验数量和字段上限并分配稳定 ID/revision。
2. 只有 Lead schema 可调用 assign、set_dependencies、cancel、delete。依赖更新在完整未删除图上检测环，并在同事务重算受影响任务的 dependency_blocked/ready 状态。
3. `start_ready` 冻结本批任务 revision，按拓扑层和任务 ID选择 ready 项，逐项把成员 current_task 和任务状态转为 waiting_approval 或 running。
4. 每个成功启动项生成结构化任务指派消息；消息提交后在锁外启动或唤醒对应成员。失败项保持可重试状态并单独报告，不撤销不相关已启动项。
5. 成员请求开始时再次校验负责人、依赖、任务 revision 和有效审批，避免消息延迟或并发修改造成越权开工。

### 计划审批

1. 需要审批且尚无有效批准时，成员 runner 只提供读取、成员版任务/邮箱和提交计划动作；普通写工具、MCP 副作用与 run_command 均不进入 registry。
2. `Mailbox submit_plan` 冻结正文、生成递增版本和 fingerprint，在同一事务中 supersede 旧版本、置任务 waiting_approval、写审批记录和向 Lead 邮箱 staged 请求消息。
3. Lead 收到消息后调用 Lead `Mailbox decide_plan`，必须提交 task、member、version、fingerprint、`approve|reject` 和 reason；服务从 binding 注入 Lead 身份并精确比较当前记录。
4. 决定、任务新状态和发给成员的结构化回复同事务提交；锁外唤醒成员。
5. 成员恢复后重新查询审批真值。批准只恢复角色原本允许且通过全局策略的工具；随后每次调用仍经过新的 PermissionService。任务/计划变更会使批准失效并回到步骤 1。

### 点对点消息、广播与恢复

1. `Mailbox send` 从调用 identity 取得发件人，读取当前团队注册表解析目标，并校验目标活动状态与协议引用。
2. 服务为正文生成有界摘要、ID 和 idempotency key，staged 后向单邮箱追加；提交成功即返回 message ID。
3. 广播展开为每个收件人的独立 send，复用根 idempotency key 加 recipient 后缀，返回逐项成功/失败。
4. 运行成员收到 SIGUSR1 或进程内 event 后在安全轮次边界 reserve 新消息；离线/idle 成员由 backend manager 重新启动。唤醒失败只作为 warning，持久消息不回滚。
5. runtime 将 reserved 消息连同任务状态组成有界 user 输入并提交完整上下文批次，再追加 ack。若在两步之间崩溃，恢复器通过 `source_message_ids` 补 ack；若上下文未提交，则重新注入。

### 成员完成、空闲与续派

1. 成员版 `SharedTask update_own` 可追加工作记录、标记 blocked 或请求完成，但不能改负责人、依赖或删除。
2. 完成可写任务时服务锁外检查长期 worktree clean、branch 和提交边界，再锁内重验 task/member revision，写 completed 与 result_commit；只读任务保存有界结果摘要。
3. runtime 自然停止时读取任务真值：已完成/取消则将成员设为 idle 并发送相应状态通知；仍 running 时用最终 Assistant 摘要执行确定性完成检查，满足前置则原子写 completed/result_commit、发送完成通知并转 idle，不满足则将任务 blocked、成员 needs_attention 并向 Lead 说明脏文件、缺少提交或其他原因。
4. 后续指派或消息按原 actual backend 启动；若该后端已不可用，显式偏好失败，auto 重新选择并记录降级。上下文、worktree 和成员 ID 始终复用。

### 原子代码集成

1. `TeamIntegrate preflight` 选择已完成未集成任务，校验 Lead clean/HEAD、成员 worktree clean、result_commit 可达性和任务 DAG，生成带全部 revision/hash 的 `IntegrationPlan`。
2. `start` 再验 plan 后记录 preparing，锁外创建受管集成 worktree和临时分支，按拓扑稳定顺序以 `git merge --no-ff --no-edit <commit>` 合入成员结果。
3. 冲突时记录 conflict paths 和只读诊断，执行 abort，保留成员分支，清理临时资源并返回 conflicted；Lead 据此更新/创建成员修复任务后重新 preflight。
4. 合并成功后先运行内置 Git 检查和 `git diff --check`，再运行配置验证 ID。任一失败记录证据并清理临时结果，不触碰 Lead 分支。
5. 验证全部通过后记录 ready_to_advance；再次确认 Lead workspace clean、branch 与 base HEAD 未变化，然后在 Lead workspace 执行 `git merge --ff-only <integration-ref>`。
6. ref 已推进后，锁内提交 completed、任务 integrated_by 和成员 integrated_commit。崩溃恢复只对“Lead ref 明确等于已验证 merged_commit”的状态补记，否则冻结为 needs_attention。
7. 逐个同步成员基线；同步失败不回滚已成功集成，而把该成员标为 needs_attention、阻止续派并向 Lead 报告。所有成员同步完成后清理临时 worktree/ref。

### Coordinator 请求

1. binding 时只有配置 `teams.coordinator.enabled=true` 且进程环境 `MEWCODE_COORDINATOR=1` 才设置 `coordinator_enabled`，结果进入状态与审计。
2. Do 模式下 registry provider 从已经应用 Skill 规则的主 registry 移除 `write_file`、`edit_file` 和普通 `run_command`，不注册任何等价写工具，再加入 `CoordinatorCommand` 与 Lead 团队工具；Plan 模式继续只加入只读 Lead 变体和只读 `CoordinatorCommand`。
3. `CoordinatorCommand` 的 `run` 只接受只读 argv，`verify` 只接受配置命令 ID，`git` 只接受 integration ID 与固定 operation；策略拒绝未知程序、shell token、任意写 Git 子命令和危险选项，执行统一 `shell=False` 且使用安全 Git 环境。
4. 正常编排由 `TeamIntegrate` 驱动同一个 scoped Git executor；Lead 也可通过受限 shell 的 `git` action 执行状态机允许的合并、终止、暂存、提交或推进步骤。所有 ref、commit、路径和消息均来自冻结集成记录。冲突源码修改没有 Lead 接口，只能通过 SharedTask 和 Mailbox 委派成员。

### 退出、恢复与归档

1. CLI 退出时 `TeamRuntime` 冻结新启动，取消 coroutine token，向已校验 tmux pane PID 发送终止信号，并等待配置期限。
2. 已停成员提交 offline/idle 和完整上下文；超时成员记录 warning，清除过期 process identity，但不把在途调用标完成。随后关闭现有非团队资源。
3. `/team resume` 先恢复未完成存储事务和集成事务，再校验 schema、仓库、worktree、任务/审批交叉引用；任何未知内容只阻止该团队。
4. `/team archive` 先把团队置 freezing 并禁止新任务，停止成员，然后检查运行任务、待审批、未提交和未集成成果。失败恢复 active 并列明原因；成功清理受管 worktree/ref、原子移动到 archive root、撤销 binding，并保持只读审计。

## 工具与命令 Schema

Action 联合 schema 使用 `oneOf` 和固定判别字段；每个 action `additionalProperties: false`。下表是稳定公开面，具体团队、actor、sender 和工作目录均由运行时注入。

| 入口 | 可见身份 | Actions / 参数要点 |
|------|----------|--------------------|
| `/team` | 用户 | `create <name>`、`resume <name>`、`switch <name>`、`status`、`archive` |
| `TeamMember` | Do Lead | `list`、`get(name)`、`add(name, role, writable, approval_required, backend)`、`upgrade(name, expected_revision)`、`start(name)`、`stop(name)` |
| `TeamMember` | Plan Lead | `list`、`get(name)` |
| `SharedTask` | Do Lead | `list`、`get`、`create`、`update`、`assign`、`set_dependencies`、`start_ready`、`cancel`、`delete`；所有更新携带 `expected_revision` |
| `SharedTask` | Plan Lead | `list`、`get` |
| `SharedTask` | 成员 | `list`、`get`、`create`、`update_own`、`request_start`、`complete` |
| `Mailbox` | Do Lead | `list`、`get`、`send`、`broadcast`、`ack`、`decide_plan` |
| `Mailbox` | Plan Lead | `list`、`get` |
| `Mailbox` | 成员 | `list`、`get`、`send`、`broadcast`、`ack`、`submit_plan`、`notify_status` |
| `TeamIntegrate` | Do Lead | `preflight(task_ids?)`、`start(plan_id)`、`get(integration_id)`、`abort(integration_id)` |
| `TeamIntegrate` | Plan Lead | `preflight(task_ids?)`、`get(integration_id)` |
| `CoordinatorCommand` | Coordinator Lead | `run(argv)`、`verify(command_id)` 或 `git(integration_id, operation)`；Plan 模式只允许只读 `run` |

`preflight` 返回的 `plan_id` 是进程内/短期持久化冻结对象，`start` 不回显或接受任意分支、提交和路径。工具结果统一含 `ok`、中文消息、reason code、对象 ID、revision/状态和有界诊断；完整结果继续使用现有 display/complete 双层截断机制。

## 配置格式

`config.example.yaml` 新增以下项目级配置；本阶段 `teams` 与现有 `agents` 一样从项目配置读取，不从用户级配置合并，也不从环境变量展开命令 argv：

```yaml
teams:
  max_members: 8
  max_tasks: 1000
  max_dependencies_per_task: 32
  max_message_chars: 20000
  message_summary_chars: 240
  mailbox_batch_size: 50
  max_mailbox_bytes: 52428800
  max_context_bytes: 104857600
  max_work_log_entries: 1000
  lock_timeout_seconds: 5
  shutdown_timeout_seconds: 5
  backend_start_timeout_seconds: 10
  integration_timeout_seconds: 300
  verification_commands:
    - id: test
      argv: [python3, -m, pytest]
      timeout_seconds: 300
  coordinator:
    enabled: false
```

`MEWCODE_COORDINATOR` 只接受精确值 `1`；未设置、空值或其他值均视为关闭。tmux 路径固定通过安全 PATH 查找，不接受模型参数；验证命令 ID 只允许小写字母、数字、`_`、`-`，argv 每项为无 NUL 的普通字符串，禁止 `${...}` 展开。

## 文件组织

### 新增生产文件

| 文件 | 职责 |
|------|------|
| `src/mycode/teams/__init__.py` | 团队公开类型与延迟导出 |
| `src/mycode/teams/models.py` | 团队、成员、任务、消息、审批、集成、配置结果模型与错误 |
| `src/mycode/teams/paths.py` | 用户团队根、对象 ID、活动/归档/邮箱/事务路径安全 |
| `src/mycode/teams/locking.py` | 团队跨线程/进程锁与成员运行锁 |
| `src/mycode/teams/identity.py` | Lead/member capability、ActorRef、worker ticket 签发与校验 |
| `src/mycode/teams/storage.py` | 严格 JSON/JSONL、乐观 revision、staged 跨文件事务与恢复 |
| `src/mycode/teams/audit.py` | 脱敏审计事件写入与查询 |
| `src/mycode/teams/binding.py` | session 到团队绑定和 coordinator 判定 |
| `src/mycode/teams/service.py` | 团队及成员生命周期应用服务 |
| `src/mycode/teams/tasks.py` | 共享任务状态机、DAG、CRUD、完成与删除规则 |
| `src/mycode/teams/protocols.py` | 四类结构化消息载荷解析与引用校验 |
| `src/mycode/teams/mailbox.py` | 注册表、邮箱、广播、ack、lease、幂等和唤醒 |
| `src/mycode/teams/approvals.py` | 计划版本、决定、失效和审批工具策略 |
| `src/mycode/teams/worktrees.py` | 长期成员与临时集成 worktree 管理 |
| `src/mycode/teams/member.py` | 可恢复成员运行核心与 AgentRunner 工厂 |
| `src/mycode/teams/integration.py` | preflight、临时合并、验证、推进、同步和恢复 |
| `src/mycode/teams/coordinator.py` | 双锁、registry 收缩与安全参数命令工具 |
| `src/mycode/teams/tools.py` | Lead/Plan/member 固定工具 schema 与适配器 |
| `src/mycode/teams/commands.py` | `/team` CommandSpec、参数解析与 UI 适配 |
| `src/mycode/teams/runtime.py` | CLI 组合、Lead 邮箱注入、后端跟踪和 shutdown |
| `src/mycode/teams/worker.py` | 内部 team-worker 参数、票据消费与退出码 |
| `src/mycode/teams/backends/__init__.py` | 后端公开导出 |
| `src/mycode/teams/backends/base.py` | `TeamMemberBackend` 协议与共用结果 |
| `src/mycode/teams/backends/selector.py` | 显式/auto 探测和可解释选择 |
| `src/mycode/teams/backends/tmux.py` | tmux pane worker、PID 信号、状态与停止 |
| `src/mycode/teams/backends/coroutine.py` | 进程内 future/event/cancellation 后端 |

### 修改生产文件

| 文件 | 修改 |
|------|------|
| `src/mycode/types.py` | 在 `AppConfig` 增加 `TeamConfig`、`CoordinatorConfig`、`VerificationCommand` |
| `src/mycode/config.py` | 严格解析 `teams`，校验上限、重复命令 ID 和安全 argv |
| `src/mycode/cli.py` | 识别内部 worker 入口，装配 `TeamRuntime`，注册 `/team`，注入关闭顺序 |
| `src/mycode/agent/runner.py` | 增加动态团队 registry provider 与 Lead 邮箱 lease/commit/release 钩子 |
| `src/mycode/commands/interfaces.py` | `CommandUI` 增加团队命令入口和状态查询协议 |
| `src/mycode/commands/models.py` | 增加用户可见团队状态结果模型 |
| `src/mycode/tools/registry.py` | 增加安全排除/替换工具的 registry 操作，不改变默认顺序 |
| `src/mycode/tool_safety.py` | 标记团队控制工具及 coordinator 只读工具的系统/读取安全分类 |
| `src/mycode/worktrees/git.py` | 增加参数化 merge/abort/ref/ancestor/clean/ff-only 等 Git 原语及安全环境 |
| `config.example.yaml` | 增加团队配置、coordinator 双锁和验证命令说明 |
| `README.md` | 记录 `/team`、后端选择、持久化目录、审批、集成和 coordinator 用法 |

`src/mycode/agents/*` 的现有一次性子 Agent 模型、任务管理和工具 schema 不修改；团队运行只复用其角色与 runner 原语，降低回归风险。

### 新增测试文件

| 文件 | 重点 |
|------|------|
| `tests/test_team_paths.py` | 名称、路径、符号链接和归档边界 |
| `tests/test_team_locking.py` | 线程/进程互斥、超时和释放 |
| `tests/test_team_storage.py` | 严格 schema、原子替换、revision、staged 事务与崩溃恢复 |
| `tests/test_team_identity.py` | capability、Actor 防伪和一次性 worker ticket |
| `tests/test_team_service.py` | 创建/恢复/成员 saga/保护性归档 |
| `tests/test_shared_tasks.py` | CRUD、权限、状态机、DAG、竞争、逻辑删除和完成提交 |
| `tests/test_team_mailbox.py` | 单播、广播、message/ack、幂等、lease 与恢复 |
| `tests/test_team_protocols.py` | 四类结构化消息严格校验 |
| `tests/test_team_approvals.py` | 版本/fingerprint、批准/驳回、失效和权限 gating |
| `tests/test_team_worktrees.py` | 长期 worktree、未集成边界、同步和保护清理 |
| `tests/test_team_backend_selector.py` | tmux 优先、显式失败和可见降级 |
| `tests/test_team_tmux_backend.py` | 参数数组、pane 身份、票据、SIGUSR1、停止与失败隔离 |
| `tests/test_team_coroutine_backend.py` | 单实例、事件唤醒、取消和资源回收 |
| `tests/test_team_member_runtime.py` | 上下文恢复、邮箱顺序、自然完成、阻塞与续派 |
| `tests/test_team_tools.py` | 普通/Lead/Plan/member schema、身份注入和权限范围 |
| `tests/test_team_integration.py` | 拓扑合并、验证、冲突、漂移、ff 推进、幂等与恢复 |
| `tests/test_team_coordinator.py` | 双锁、工具移除、argv allowlist 和全部绕过路径 |
| `tests/test_team_commands.py` | `/team` 解析、绑定、切换、状态与归档输出 |
| `tests/test_team_runtime.py` | Lead 邮箱 lease、shutdown、恢复顺序和故障隔离 |
| `tests/test_team_collaboration_integration.py` | tmux fake 与 coroutine 的完整团队端到端场景 |

现有 `tests/test_config.py`、`tests/test_agent_runner.py`、`tests/test_cli.py`、`tests/test_tools_registry.py`、`tests/test_agent_delegation_integration.py` 和 worktree 回归测试追加兼容性用例。

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 领域边界 | 新建 `mycode.teams`，不扩展 `AgentTaskManager` | 现有任务明确不跨进程恢复；混用会破坏其状态和清理语义 |
| 用户入口 | `/team` 建立可信绑定，模型工具只在绑定后出现 | 同时满足用户可创建团队和普通主入口不暴露工具 |
| 持久化 | 版本化 JSON 快照 + JSONL 邮箱/上下文/审计 | 符合文件邮箱要求、可检查、无新依赖，适合受限团队规模 |
| 并发 | `threading.Lock` + `fcntl.flock` + revision | 与现有 worktree 锁一致，覆盖协程线程和 tmux 独立进程 |
| 跨文件事务 | staged after 文件、before/after hash、intent/commit 审计、向前恢复 | 避免猜测回滚；重复恢复幂等，未知内容安全停机 |
| 强隔离后端 | 首版只支持 tmux pane | 稳定 pane ID、PID、启动和唤醒接口，避免平台终端脚本 |
| 轻量后端 | 受控执行器中的共享成员 runtime | 复用 Provider/Hook 基础设施但保持上下文、权限和 worktree 隔离 |
| 后端 auto | tmux → coroutine，返回完整诊断 | 强隔离优先且不静默降级；显式选择失败关闭 |
| tmux worker 身份 | 一次性 0600 ticket + hash + 成员锁 | pane 参数不能成为可伪造身份，且阻止重复实例 |
| worktree 生命周期 | 每成员一个长期 worktree/branch | 支持空闲恢复和上下文续派，不按任务反复 provision |
| 工具暴露 | Lead、Plan Lead、member 三套固定实例/schema | 从 Provider 层避免暴露无权动作，保持状态变化时 schema 稳定 |
| Actor 身份 | 运行时 capability 注入，不接受工具 actor 参数 | 防止模型冒充 Lead、成员或发件人 |
| 任务并发 | revision 乐观锁 + 团队写锁 | revision 给调用者冲突语义，文件锁保证物理提交一致 |
| 依赖 | 同团队 DAG、确定性 DFS 与拓扑排序 | 覆盖本阶段完成后依赖，拒绝环但不引入复杂调度 |
| 邮箱已读 | append-only message + ack 投影 | 保留原消息与可信时间，避免并发原地改写 JSONL |
| 邮箱消费 | reserve → 上下文提交 → ack，source ID 去重 | 崩溃后既不丢消息，也不重复注入已经持久化的内容 |
| 审批真值 | `approvals.json` 的版本/fingerprint 记录 | 结构化消息只做传输，不能伪造或替代审批状态 |
| 审批能力收缩 | 未批准时从 registry 移除副作用工具 | 比提示词约束更强；批准后仍经过现有权限系统 |
| 成员完成 | clean worktree + 新 commit 的确定性检查 | 自然停止可安全完成；脏文件或无提交时保守阻塞 |
| 集成 | 独立临时 worktree，拓扑 merge，验证后 Lead ff-only | 成功前不修改 Lead，失败清理临时结果，便于幂等恢复 |
| 冲突处理 | Lead 只读诊断并委派成员 | 满足 coordinator 禁止源码写入和已批准范围 |
| coordinator shell | 删除 `run_command`，提供 `shell=False` 只读 argv、验证 ID 与 scoped Git operation | 现有 shell=True 工具无法证明不写；专用工具阻断重定向/解释器绕过 |
| coordinator Git 写入 | `CoordinatorCommand` 与 `TeamIntegrate` 共享事务约束的参数化 Git executor | 保留 shell 合并/暂存/提交能力，但模型不能提供任意 ref、路径、提交和消息 |
| 双锁 | 配置 `enabled=true` 且 `MEWCODE_COORDINATOR=1` | 能力由管理员开放，同时要求用户本次进程主动启用 |
| Plan 模式 | 只读团队工具变体 | 保持现有 Plan 模式语义，仍允许检查团队状态与设计方案 |
| 故障策略 | 单对象失败关闭、结构化诊断、其他对象继续 | 避免损坏团队或 pane 拖垮普通会话和其他成员 |

## Spec 覆盖关系

| Spec | 设计覆盖 |
|------|----------|
| F1–F3 | `/team`、binding、TeamSnapshot、用户目录路径与 FileTeamStore |
| F4–F6 | TeamWorktreeManager、长期 identity/branch、集成后基线同步 |
| F7–F10 | TeamMemberRuntime、context/mailbox 恢复、shutdown、保护性归档 |
| F11–F14 | TeamMemberBackend、TmuxBackend、CoroutineBackend、BackendSelector/Manager |
| F15–F17 | TeamToolRegistryProvider、三套 schema、capability identity 与领域校验 |
| F18–F24 | SharedTaskRecord/Service、状态机、DAG、revision 与逻辑删除 |
| F25–F30 | 注册表、MailboxService、message/ack、广播、protocol、唤醒与幂等恢复 |
| F31–F34 | ApprovalRecord/Service、结构化决定、fingerprint 与 ApprovalToolPolicy |
| F35–F36 | start_ready 拓扑调度、成员确定性完成、状态通知与 idle/续派 |
| F37–F40 | IntegrationPlan/Record/Service、临时 worktree、验证、ff-only 与同步 |
| F41–F44 | coordinator 双锁、registry 收缩、CoordinatorCommand 与委派冲突修复 |
| N1–N3 | 团队锁、revision、staged 事务、idempotency key、唯一终态/集成标记 |
| N4–N6 | 路径/符号链接防护、capability、脱敏审计与不持久化临时授权 |
| N7–N8 | 后端共享 runtime 和确定性探测诊断 |
| N9–N11 | TeamConfig 上限、现有上下文预算、有界 timeout/cancel/shutdown |
| N12–N14 | 单团队/成员失败隔离、审计、严格 schema 与确定性事务恢复 |
| N15–N16 | 临时集成事务、幂等边界、coordinator 三层能力限制 |
| N17–N18 | 固定身份/mode schema、动态 registry 接入、现有 AgentTaskManager 不变 |
| N19–N20 | Python 3.10 类型兼容、分层测试、带对象 ID/reason code 的结果与审计 |
