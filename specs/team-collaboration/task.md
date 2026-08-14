# MewCode 长期团队协作 Tasks

> 所有实现任务都必须在 `spec.md`、`plan.md`、本文件和 `checklist.md` 全部批准后才可开始。每个任务先写或更新测试，再实现行为；验证通过后按任务建议提交边界创建 Git commit。

## 文件清单

### 新增生产文件

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | `src/mycode/teams/__init__.py` | 团队公开类型与延迟导出 |
| 新建 | `src/mycode/teams/models.py` | 团队、成员、任务、消息、审批、集成及结果模型 |
| 新建 | `src/mycode/teams/paths.py` | 用户团队根、名称、ID 和对象路径安全 |
| 新建 | `src/mycode/teams/locking.py` | 团队跨线程/进程锁和成员运行锁 |
| 新建 | `src/mycode/teams/identity.py` | Actor capability 与一次性 worker ticket |
| 新建 | `src/mycode/teams/storage.py` | JSON/JSONL、revision、staged 事务和恢复 |
| 新建 | `src/mycode/teams/audit.py` | 脱敏审计事件写入和查询 |
| 新建 | `src/mycode/teams/binding.py` | session 团队绑定与 coordinator 判定 |
| 新建 | `src/mycode/teams/service.py` | 团队和成员生命周期应用服务 |
| 新建 | `src/mycode/teams/tasks.py` | 共享任务状态机、DAG 和 CRUD |
| 新建 | `src/mycode/teams/protocols.py` | 四类结构化消息协议 |
| 新建 | `src/mycode/teams/mailbox.py` | 注册表、邮箱、广播、ack、lease 和幂等 |
| 新建 | `src/mycode/teams/approvals.py` | 计划版本、决定、失效与审批策略 |
| 新建 | `src/mycode/teams/worktrees.py` | 长期成员与临时集成 worktree 管理 |
| 新建 | `src/mycode/teams/member.py` | 可恢复成员运行核心与 runner 工厂 |
| 新建 | `src/mycode/teams/integration.py` | 原子集成、验证、推进、同步与恢复 |
| 新建 | `src/mycode/teams/coordinator.py` | 双锁、受限命令和 scoped Git 执行器 |
| 新建 | `src/mycode/teams/tools.py` | Lead、Plan 和成员工具 schema/适配器 |
| 新建 | `src/mycode/teams/commands.py` | `/team` 命令解析与 UI 适配 |
| 新建 | `src/mycode/teams/runtime.py` | CLI 装配、Lead 邮箱、后端跟踪和关闭 |
| 新建 | `src/mycode/teams/worker.py` | 内部 team-worker 入口和票据消费 |
| 新建 | `src/mycode/teams/backends/__init__.py` | 后端公开导出 |
| 新建 | `src/mycode/teams/backends/base.py` | 后端协议和共用结果 |
| 新建 | `src/mycode/teams/backends/selector.py` | 显式/auto 探测和选择 |
| 新建 | `src/mycode/teams/backends/tmux.py` | tmux pane worker 生命周期与信号唤醒 |
| 新建 | `src/mycode/teams/backends/coroutine.py` | 进程内 future/event/cancellation 后端 |

### 修改生产与文档文件

| 操作 | 文件 | 职责 |
|------|------|------|
| 修改 | `src/mycode/types.py` | 增加 TeamConfig、CoordinatorConfig、VerificationCommand |
| 修改 | `src/mycode/config.py` | 严格解析项目级 `teams` 配置 |
| 修改 | `src/mycode/cli.py` | 装配 TeamRuntime、注册 `/team`、分派 worker、关闭资源 |
| 修改 | `src/mycode/agent/runner.py` | 动态团队 registry 与 Lead 邮箱 lease 钩子 |
| 修改 | `src/mycode/commands/interfaces.py` | 增加团队命令 UI 协议 |
| 修改 | `src/mycode/commands/models.py` | 增加团队状态展示模型 |
| 修改 | `src/mycode/tools/registry.py` | 增加安全 exclude/replace registry 操作 |
| 修改 | `src/mycode/tool_safety.py` | 增加团队工具安全分类 |
| 修改 | `src/mycode/worktrees/git.py` | 增加安全参数化 Git 集成原语 |
| 修改 | `config.example.yaml` | 增加团队配置示例和双锁说明 |
| 修改 | `README.md` | 增加团队操作、后端、审批、集成和 coordinator 文档 |

### 新增测试文件

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | `tests/test_team_paths.py` | 名称、路径、符号链接、归档边界 |
| 新建 | `tests/test_team_locking.py` | 线程/进程互斥与超时 |
| 新建 | `tests/test_team_storage.py` | schema、原子快照、revision、事务恢复 |
| 新建 | `tests/test_team_identity.py` | capability 防伪与 worker ticket |
| 新建 | `tests/test_team_service.py` | 团队/成员 saga 与保护性归档 |
| 新建 | `tests/test_shared_tasks.py` | CRUD、状态机、DAG、权限、并发和删除 |
| 新建 | `tests/test_team_mailbox.py` | 单播、广播、ack、lease、幂等和恢复 |
| 新建 | `tests/test_team_protocols.py` | 四类协议严格校验 |
| 新建 | `tests/test_team_approvals.py` | 计划版本、决定、失效和 gating |
| 新建 | `tests/test_team_worktrees.py` | 长期 worktree、同步与保护清理 |
| 新建 | `tests/test_team_backend_selector.py` | tmux 优先和可见降级 |
| 新建 | `tests/test_team_tmux_backend.py` | pane、ticket、SIGUSR1、停止与隔离 |
| 新建 | `tests/test_team_coroutine_backend.py` | 单实例、唤醒、取消与回收 |
| 新建 | `tests/test_team_member_runtime.py` | 上下文恢复、自然完成、阻塞和续派 |
| 新建 | `tests/test_team_tools.py` | 工具 schema、身份注入和可见性 |
| 新建 | `tests/test_team_integration.py` | 合并、验证、冲突、推进和恢复 |
| 新建 | `tests/test_team_coordinator.py` | 双锁和命令绕过防护 |
| 新建 | `tests/test_team_commands.py` | `/team` 命令和绑定输出 |
| 新建 | `tests/test_team_runtime.py` | Lead 邮箱、关闭和恢复顺序 |
| 新建 | `tests/test_team_collaboration_integration.py` | 团队完整端到端场景 |

### 修改现有测试文件

| 操作 | 文件 | 职责 |
|------|------|------|
| 修改 | `tests/test_config.py` | 团队配置缺省、合法值和拒绝场景 |
| 修改 | `tests/test_agent_runner.py` | 动态团队 registry 与邮箱 lease 回归 |
| 修改 | `tests/test_cli.py` | team-worker 分派、命令注册和 shutdown |
| 修改 | `tests/test_tools_registry.py` | exclude/replace 与工具顺序 |
| 修改 | `tests/test_agent_delegation_integration.py` | 普通子 Agent 不见团队工具 |
| 修改 | `tests/test_worktree_isolation_integration.py` | 一次性 worktree 语义不受团队扩展影响 |

## T1：配置、模型、路径与锁基础

**文件：**

- `src/mycode/types.py`
- `src/mycode/config.py`
- `src/mycode/teams/__init__.py`
- `src/mycode/teams/models.py`
- `src/mycode/teams/paths.py`
- `src/mycode/teams/locking.py`
- `tests/test_config.py`
- `tests/test_team_paths.py`
- `tests/test_team_locking.py`

**依赖：** 无

**步骤：**

1. 定义 Plan 中的 TeamConfig、CoordinatorConfig、VerificationCommand 以及团队领域冻结模型、Literal 状态和结构化错误；保持 Python 3.10 可用，不使用 3.11+ 专属语法或库。
2. 在 `AppConfig` 增加缺省 `teams`，严格解析所有上限、timeout、验证命令 ID/argv 和未知字段；确认 `teams` 只来自项目配置，coordinator 默认关闭。
3. 实现团队/成员/任务/消息/集成 ID 规范化，固定 `~/.mycode/teams` 与 archive root，并允许测试显式注入用户根，禁止从模型或配置指定根路径。
4. 对活动、归档、邮箱、上下文、事务和锁路径执行 lexical + resolved 双重边界检查，拒绝绝对路径、反斜杠、`.`、`..`、保留名和任一路径前缀符号链接。
5. 复用现有锁模式实现线程锁 + `fcntl.flock`，提供有界 timeout、幂等 release 和异常安全 context manager；团队锁与成员锁使用互不碰撞的固定路径。
6. 为默认值、最小/最大值、重复验证命令、非法 argv、环境引用、名称碰撞、符号链接逃逸、跨线程/进程竞争与锁超时编写测试。

**验证：**

```text
.venv/bin/python -m pytest tests/test_config.py tests/test_team_paths.py tests/test_team_locking.py -q
```

**提交边界：** 配置、模型、路径和锁测试全部通过后提交一次。

## T2：文件存储、跨文件事务与审计

**文件：**

- `src/mycode/teams/storage.py`
- `src/mycode/teams/audit.py`
- `src/mycode/teams/models.py`
- `src/mycode/teams/paths.py`
- `tests/test_team_storage.py`

**依赖：** T1

**步骤：**

1. 实现 `FileTeamStore` 的严格 JSON snapshot 和 JSONL parser/serializer；拒绝未知字段、schema 版本、无时区时间、重复键、非法交叉引用、符号链接文件及超出配置的邮箱/上下文大小。
2. 实现 aggregate 一致读取和 revision 校验，所有快照读取均在团队锁中完成；并发调用基于旧 revision 时返回结构化冲突，不覆盖新状态。
3. 实现同目录临时文件、flush/fsync、原子 replace 和目录 fsync；异常注入时读取者只能看到完整 before 或完整 after。
4. 实现 `.transactions/<id>` manifest、before/after hash、完整 staged after 文件及 intent/commit/failed 记录；恢复仅在目标 hash 属于 before/after 集合时确定性向前完成，第三种内容安全拒绝。
5. 把 staged mailbox JSONL 行纳入事务，利用 idempotency key 防止恢复或重试重复追加；完成后安全回收已提交事务目录，失败事务保留定位信息。
6. 实现 AuditWriter/Reader 的有界摘要与字段白名单；安全关键事务无法写 intent 时不得开始，不持久化消息正文、计划正文、提示、权限目标、完整命令或凭据。
7. 覆盖进程中断点、部分 replace、重复恢复、损坏 hash、未知 schema、revision 竞争、fsync/审计失败和多团队隔离测试。

**验证：**

```text
.venv/bin/python -m pytest tests/test_team_storage.py -q
```

**提交边界：** 存储原子性、恢复与审计测试全部通过后提交一次。

## T3：可信身份、worker 票据与会话绑定

**文件：**

- `src/mycode/teams/identity.py`
- `src/mycode/teams/binding.py`
- `src/mycode/teams/models.py`
- `tests/test_team_identity.py`

**依赖：** T1、T2

**步骤：**

1. 实现不可由工具参数构造的 LeadIdentity、MemberIdentity 和 ActorRef；capability 使用安全随机值，只在进程内保留明文，持久化与审计仅保存安全引用。
2. 实现 WorkerLaunchTicket 的签发、0600 文件写入、hash/到期时间记录、单次消费和删除；错误团队、成员、仓库、过期、重复消费或权限异常全部失败关闭。
3. 实现 TeamBindingManager 的 bind/switch/current/clear，绑定前重验团队 active 状态、workspace、repository ID 和 Lead branch。
4. 只在 bind/switch 时计算 `teams.coordinator.enabled && MEWCODE_COORDINATOR == "1"`；缺任一锁时保存明确原因，拒绝模型参数覆盖。
5. 切换、`/new`、归档和进程退出撤销 capability；旧工具实例再调用时必须被领域身份校验拒绝。
6. 测试 Actor 冒充、跨团队 capability、ticket 重放/篡改/权限、同 session 切换、双锁四种组合和 capability 撤销。

**验证：**

```text
.venv/bin/python -m pytest tests/test_team_identity.py -q
```

**提交边界：** 身份、防重放与绑定测试全部通过后提交一次。

## T4：长期成员 Worktree 与安全 Git 原语

**文件：**

- `src/mycode/teams/worktrees.py`
- `src/mycode/worktrees/git.py`
- `src/mycode/teams/models.py`
- `tests/test_team_worktrees.py`
- `tests/test_worktree_isolation_integration.py`

**依赖：** T1、T2、T3

**步骤：**

1. 扩展 GitRunner，使用参数数组和安全环境实现仓库/branch/HEAD/clean/ancestor/commit range、worktree add/remove、merge/abort、ref、ff-only 和 diff-check 原语；禁止 shell、hooks、alias、pager、外部 diff/textconv 和 credential prompt。
2. 实现 TeamWorktreeIdentity、固定受管名称 `teams/<team>/<member-id>` 与 `refs/heads/mewcode/team/...`；校验仓库 ID、主 workspace、expected gitdir、初始化 fingerprint 和所有 marker/record。
3. 实现长期成员 worktree provision/recover/inspect：可写成员创建独立 worktree，readonly 成员只返回受限共享 workspace；失败补偿只删除本事务创建且身份完全匹配的资源。
4. 实现 `integrated_commit` 到 HEAD 的待集成 commit 检查、工作区 clean 检查和成功集成后的 `sync_baseline`；无法安全快进时保留原成果并返回 needs_attention。
5. 实现保护性 dispose：未提交、未集成、状态未知、路径/marker/ref 不匹配时拒绝删除；干净且已集成时才移除 worktree 和团队 branch。
6. 保持现有一次性 WorktreeManager 的 public API、路径、branch、清理与测试行为不变。

**验证：**

```text
.venv/bin/python -m pytest tests/test_team_worktrees.py tests/test_worktree_isolation_integration.py -q
```

**提交边界：** 长期 worktree 与现有隔离回归全部通过后提交一次。

## T5：共享任务状态机、DAG 与 CRUD

**文件：**

- `src/mycode/teams/tasks.py`
- `src/mycode/teams/models.py`
- `tests/test_shared_tasks.py`

**依赖：** T1、T2、T3、T4

**步骤：**

1. 实现 SharedTaskRecord、TaskWorkEntry、TaskGraph、ApprovalLookup 协议和显式状态转换表，拒绝未知状态、终态倒退和非法负责人。
2. 实现 list/get/create、Lead update/assign/set_dependencies/start_ready/cancel/delete 以及 member update_own/request_start/complete；从 identity 决定权限，不接受 actor 参数。
3. 对完整未删除任务图执行依赖存在、自依赖和确定性 DFS 环检测；依赖终态变化时在同事务重算 dependency_blocked/ready。
4. 所有更新要求 expected_revision，追加有界 work log 并留下状态审计；并发旧 revision 失败且不产生部分更新。
5. member request_start 重验负责人、依赖与注入 ApprovalLookup；Lead start_ready 按拓扑层和 task ID 稳定排序，逐项返回启动决定。
6. 完成可写任务时使用 T4 只读 Git inspector 校验 clean、正确 branch、新提交和 HEAD，固定 result_commit；readonly 任务保存有界结果摘要。
7. 实现受约束逻辑删除：运行中先取消、存在未删除依赖者拒绝、默认查询隐藏但审计查询仍可见。
8. 测试 Lead/member 权限、图环、并行 ready、审批阻塞、revision 竞争、完成 commit、脏工作区、终态、取消和删除边界。

**验证：**

```text
.venv/bin/python -m pytest tests/test_shared_tasks.py -q
```

**提交边界：** 任务状态、DAG、并发和权限测试全部通过后提交一次。

## T6：结构化协议、名称注册表与邮箱

**文件：**

- `src/mycode/teams/protocols.py`
- `src/mycode/teams/mailbox.py`
- `src/mycode/teams/models.py`
- `tests/test_team_protocols.py`
- `tests/test_team_mailbox.py`

**依赖：** T1、T2、T3、T5

**步骤：**

1. 为任务指派/变更、计划审批请求、计划决定和任务状态通知实现严格判别联合 parser；校验必填字段、Actor 一致性、task/member/version/fingerprint 引用和 `additionalProperties: false` 等价规则。
2. 实现从当前 TeamSnapshot 注册表解析收件人，Lead 使用保留邮箱，成员名不存在、重复、归档、跨团队或非法时在写入前失败。
3. 实现 MailboxMessage/MailboxAck 单邮箱 sequence、可信时间戳、默认 read=false、有界摘要、message ID 和 idempotency key；查询投影 ack 后 read=true，不原地修改历史行。
4. 实现 send、broadcast、list/get/ack；broadcast 为每个收件人生成独立消息与读取状态，部分失败返回逐项结果而不撤销成功项。
5. 实现 reserve/commit/release unread lease，工具查询不推进 runtime cursor；上下文 source_message_ids 已存在但缺 ack 时补 ack，未写上下文时重新投递。
6. 注入 WakeNotifier 协议，在消息持久化后锁外唤醒；失败作为 warning，不回滚消息，也不让邮箱导入后端模块。
7. 测试消息字段、协议错误、名称解析、幂等重试、并发 append/ack、广播部分失败、lease 崩溃窗口、大小上限与敏感诊断。

**验证：**

```text
.venv/bin/python -m pytest tests/test_team_protocols.py tests/test_team_mailbox.py -q
```

**提交边界：** 协议、邮箱幂等和恢复测试全部通过后提交一次。

## T7：版本化计划审批与能力 Gating

**文件：**

- `src/mycode/teams/approvals.py`
- `src/mycode/teams/models.py`
- `tests/test_team_approvals.py`

**依赖：** T2、T3、T5、T6

**步骤：**

1. 实现 ApprovalRecord、plan fingerprint、单任务成员递增版本、pending/approved/rejected/superseded 状态和 ApprovalLookup。
2. `submit_plan` 校验当前负责人和 task revision，冻结正文/fingerprint，在单个 TeamStore transaction 中 supersede 旧版本、写新记录、更新任务 waiting_approval 并 staged Lead 请求消息。
3. `decide` 只接受 LeadIdentity，精确比较 member/task/version/fingerprint，要求结构化 approve/reject 和 reason；同事务更新审批、任务状态与成员回复消息。
4. 任务负责人、计划正文或相关任务条件变化时 invalidate 旧批准；恢复后以 approvals snapshot 为真值，不从消息正文推断决定。
5. 实现 ApprovalToolPolicy：无有效批准时普通副作用工具、MCP 副作用和 run_command 不进入成员 registry，只保留读取、SharedTask、Mailbox 与提交计划；批准后仅恢复角色/全局策略本来允许的工具。
6. 测试错误版本/fingerprint/身份、驳回修订、批准失效、并发决定、CLI 恢复、消息/快照事务和现有 PermissionService 仍生效。

**验证：**

```text
.venv/bin/python -m pytest tests/test_team_approvals.py -q
```

**提交边界：** 审批版本、结构化决定与工具 gating 测试全部通过后提交一次。

## T8：后端协议、选择器与协程后端

**文件：**

- `src/mycode/teams/backends/__init__.py`
- `src/mycode/teams/backends/base.py`
- `src/mycode/teams/backends/selector.py`
- `src/mycode/teams/backends/coroutine.py`
- `src/mycode/teams/models.py`
- `tests/test_team_backend_selector.py`
- `tests/test_team_coroutine_backend.py`

**依赖：** T1、T2、T3

**步骤：**

1. 定义 TeamMemberBackend probe/start/wake/stop/inspect 协议、诊断与结果模型，明确 timeout、失败状态和实际 backend 报告。
2. 实现 BackendSelector：显式 backend 只探测自身且失败关闭；auto 固定 tmux → coroutine，保留所有探测诊断并明确降级原因。
3. 实现 CoroutineBackend 的受控执行器、每成员 future/event/cancellation 和进程内 token；取得成员锁后才调用注入的 runtime callable。
4. 保证同一成员只能有一个 coroutine worker，wake 只设置 event，stop 有界取消并回收；一个 future 异常不关闭执行器或其他成员。
5. 后端状态变化通过回调交给上层持久化，不让 backend 直接修改 JSON；关闭时返回已停止/超时逐成员报告。
6. 用 fake tmux probe 和 fake runtime 测试优先级、显式失败、可见降级、重复启动、唤醒竞态、异常隔离、取消和线程资源上限。

**验证：**

```text
.venv/bin/python -m pytest tests/test_team_backend_selector.py tests/test_team_coroutine_backend.py -q
```

**提交边界：** 后端选择与协程生命周期测试全部通过后提交一次。

## T9：tmux 强隔离后端与内部 Worker 入口

**文件：**

- `src/mycode/teams/backends/tmux.py`
- `src/mycode/teams/worker.py`
- `src/mycode/teams/backends/__init__.py`
- `tests/test_team_tmux_backend.py`

**依赖：** T2、T3、T8

**步骤：**

1. 实现 tmux 探测：通过安全 PATH 查找固定 `tmux`、以参数数组运行版本/服务检查，区分 binary_missing、server_unavailable、unsupported 和 timeout 诊断，不创建或修改项目文件。
2. 实现固定 `mewcode-<team>` session 和成员 window/pane 启动，所有 subprocess 调用 `shell=False`；命令行只包含内部 worker 入口、规范化 team/member ID 与 ticket file，不传 API key、提示、消息或任意命令。
3. 从 tmux 格式化输出解析并持久化 server socket、session、window、pane ID、pane PID；任何字段缺失、重复、身份不匹配或进程退出均安全失败。
4. 实现 wake：重查 pane ID/PID/worker identity 后向 PID 发送专用 SIGUSR1；实现有界 stop：先请求 worker 正常停止，超时后只关闭仍与已记录身份匹配的 pane，绝不杀死复用 ID 的无关进程。
5. 实现 `run_team_worker` 参数解析、ticket 单次消费、成员运行锁、SIGUSR1/SIGTERM handler、注入式 runtime 调用和明确退出码；没有合法 ticket 时不能仅凭 team/member 参数获得身份。
6. 空闲 worker 正常退出并清理 process identity；正在运行时的 wake 只设置安全事件，不把文本模拟输入到终端。
7. 使用 fake tmux executable/subprocess/signal 覆盖成功启动、binary 缺失、pane 创建失败、解析异常、ticket 泄露检查、PID 复用、重复 worker、唤醒失败、停止超时和其他成员隔离。

**验证：**

```text
.venv/bin/python -m pytest tests/test_team_tmux_backend.py -q
```

**提交边界：** tmux 后端、worker 身份与失败隔离测试全部通过后提交一次。

## T10：团队与成员生命周期应用服务

**文件：**

- `src/mycode/teams/service.py`
- `src/mycode/teams/models.py`
- `tests/test_team_service.py`

**依赖：** T2、T3、T4、T8、T9

**步骤：**

1. 实现 create_team：校验 Git 仓库、团队名、同名活动/归档冲突和仓库身份，创建 team/tasks/approvals/integrations、Lead 邮箱/审计初始事务，不在项目仓库写团队数据。
2. 实现 resume/status：先恢复存储事务，再重验 schema、workspace、repository ID、Lead branch、成员 worktree 和交叉引用；单个损坏团队失败关闭，不影响其他团队。
3. 实现 add_member saga：从当前 AgentCatalog 复制并持久化角色快照，写 provisioning，锁外 provision 长期 worktree、选择后端，锁内重验 revision 后提交 actual backend 和 idle/offline 状态。
4. 实现角色 upgrade：只升级同名当前有效角色，重新校验工具/模型，成功才原子替换快照；失败保留旧版本和成员上下文。
5. 实现 start/stop：签发 ticket 或内存 capability，持久化 starting，锁外调用后端，重验并提交 running/idle/failed；auto 模式在 tmux 探测或实际启动失败时可继续 coroutine，并把每次原因返回 Lead，显式 tmux 不降级。
6. 实现归档 saga：冻结新任务、停止成员、检查运行任务/待审批/脏工作区/未集成 commit；不满足时恢复 active 并逐项说明，满足时保护清理 worktree/ref、写 archived、移动 archive root 并撤销 binding。
7. 所有慢 Git/tmux 操作在团队锁外执行；补偿只清理本事务新建且身份匹配资源，revision 漂移时不覆盖并发新状态。
8. 测试非 Git、多个团队、角色快照热更新、后端真实启动降级、显式失败、saga 中断、并发成员操作、恢复损坏和保护性归档。

**验证：**

```text
.venv/bin/python -m pytest tests/test_team_service.py -q
```

**提交边界：** 团队/成员生命周期和归档保护测试全部通过后提交一次。

## T11：可恢复成员运行核心

**文件：**

- `src/mycode/teams/member.py`
- `src/mycode/teams/models.py`
- `tests/test_team_member_runtime.py`

**依赖：** T4、T5、T6、T7、T8、T9、T10

**步骤：**

1. 实现 TeamMemberRunnerFactory：使用持久角色快照和当前模型映射创建独立 AgentRunner、ContextManager、PermissionService、文件 cache、CancellationToken 和 Token 统计；两种后端使用同一工厂。
2. 应用角色白/黑名单、全局禁止 `Agent`/现有 `Task`/`load_skill`、成员固定 SharedTask/Mailbox，以及 ApprovalToolPolicy；不注册主 session journal、长期记忆写入或同级任务管理。
3. 团队成员统一使用非交互权限处理：预配置允许规则照常生效，需要用户交互批准的调用获得现有结构化拒绝并可继续决策，避免 tmux 与 coroutine 权限语义不同。
4. 恢复 MemberContextRecord 的最大有效消息前缀，截断尾部不完整 tool batch；不恢复临时权限、在途调用、future、signal 或 token 累加器。
5. reserve 未读邮箱，将消息 ID、结构化载荷、当前任务/依赖/审批状态组成有界 user 输入；完整上下文批次落盘后才 commit lease，崩溃恢复利用 source_message_ids 去重。
6. 运行到自然完成、失败、取消或上限；自然完成时执行 T5 的确定性完成检查，clean+新 commit 则完成/通知/idle，否则 blocked+needs_attention；没有任务和消息时直接 idle。
7. 终态转换与 Lead 状态通知同事务提交，随后释放成员锁；异常只能影响该成员，并保留可恢复上下文和 worktree。
8. 使用 fake provider 覆盖首次运行、CLI 重启、停机消息顺序、审批前后工具变化、权限拒绝、完整/不完整 tool batch、自然完成、脏文件阻塞、取消、上下文上限与续派同一身份。

**验证：**

```text
.venv/bin/python -m pytest tests/test_team_member_runtime.py -q
```

**提交边界：** 成员恢复、审批边界、自然收尾和续派测试全部通过后提交一次。

## T12：原子代码集成与崩溃恢复

**文件：**

- `src/mycode/teams/integration.py`
- `src/mycode/teams/worktrees.py`
- `src/mycode/worktrees/git.py`
- `src/mycode/teams/models.py`
- `tests/test_team_integration.py`

**依赖：** T4、T5、T10

**步骤：**

1. 实现 preflight：选择 completed 且未 integrated 的任务，重验任务/成员 revision、DAG、Lead clean/branch/HEAD、成员 clean/result_commit 可达性，冻结 plan ID、base 和稳定拓扑顺序。
2. 创建固定受管集成 worktree/ref，按顺序参数化执行 `git merge --no-ff --no-edit`；每一步重验冻结 commit，禁止模型提供 ref、路径、commit 或提交信息。
3. 冲突时收集有界 conflict paths/diagnostic、执行 merge abort、记录 conflicted 并清理临时资源；保留所有成员 branch/commit 和原 Lead 分支。
4. 合并成功后运行 Git 一致性、`git diff --check` 和配置 VerificationCommand，统一安全环境、shell=False、单项/总 timeout；任何失败保存证据并丢弃临时结果。
5. ready_to_advance 后再次验证 Lead workspace clean、branch 和 frozen HEAD，再执行 ff-only；推进前任何漂移失败关闭，绝不 reset/rebase 用户分支。
6. 成功推进后同事务提交 integration completed、task integrated_by 和 member integrated_commit，随后逐个 sync_baseline；同步失败标成员 needs_attention 且不回滚已推进 Lead。
7. 实现 abort 和 recover：before/merged ref 明确时幂等清理或补记，未知 ref/working tree 状态时冻结 needs_attention，不猜测处理。
8. 测试并行 DAG 稳定顺序、无冲突成功、冲突、验证失败/超时、Lead 漂移、重复 start、推进边界崩溃、成员同步失败和成果保留。

**验证：**

```text
.venv/bin/python -m pytest tests/test_team_integration.py -q
```

**提交边界：** 集成原子性、幂等和恢复测试全部通过后提交一次。

## T13：Coordinator 双锁与受限命令执行

**文件：**

- `src/mycode/teams/coordinator.py`
- `src/mycode/teams/integration.py`
- `src/mycode/tools/registry.py`
- `src/mycode/tool_safety.py`
- `tests/test_team_coordinator.py`
- `tests/test_tools_registry.py`

**依赖：** T3、T12

**步骤：**

1. 为 ToolRegistry 增加保持顺序的 exclude/replace 操作；验证不会修改原 registry、重复注册或改变无关默认工具顺序。
2. 实现 coordinator registry 收缩：移除 write_file/edit_file/普通 run_command 和等价写工具，保留读取和团队编排；Plan 模式进一步只保留只读团队变体。
3. 实现 CoordinatorCommandTool 三类固定 schema：`run(argv)`、`verify(command_id)`、`git(integration_id, operation)`；不接受 command string、cwd、env、path、ref、commit 或 message。
4. `run` 只允许受限 pwd/rg/git status|diff|log|show|rev-parse|branch，拒绝 shell token、重定向、管道、环境赋值、解释器、`-c`、Git alias、外部 diff/textconv、hooks、pager 和危险选项，并始终 shell=False。
5. `verify` 只解析配置生成的 command ID，在受管集成 worktree 执行并检查前后 Git 状态；模型不能覆盖 argv、timeout 或环境。
6. 实现 ScopedIntegrationGitExecutor；`git` 仅接受活动 integration ID 与状态机允许的 merge_next/abort_merge/stage_integration/commit_integration/advance_lead，全部 ref/commit/路径/消息从冻结记录解析并重验。
7. 所有模式判断和拒绝写审计；任一锁缺失时保持普通 Lead registry 并报告具体缺失条件。
8. 建立绕过测试矩阵：分号、管道、重定向、替换、变量、alias、`git -c`、external diff、pager、Python/shell/子进程、路径注入、伪 integration、越序 operation、冲突文件直接编辑和工具别名。

**验证：**

```text
.venv/bin/python -m pytest tests/test_team_coordinator.py tests/test_tools_registry.py -q
```

**提交边界：** coordinator 双锁、registry 收缩与全部绕过测试通过后提交一次。

## T14：身份化团队工具与固定 Schema

**文件：**

- `src/mycode/teams/tools.py`
- `src/mycode/tools/registry.py`
- `src/mycode/tool_safety.py`
- `tests/test_team_tools.py`
- `tests/test_agent_delegation_integration.py`

**依赖：** T5、T6、T7、T10、T12、T13

**步骤：**

1. 实现 Do Lead、Plan Lead 和 member 三套独立固定工具实例；action 使用 oneOf 判别联合、每个分支 additionalProperties=false，schema 不随团队状态、成员数、后端或角色更新变化。
2. 实现 TeamMember、Lead/Member SharedTask、Lead/Member Mailbox、TeamIntegrate 和 CoordinatorCommand 适配；Plan 版本只包含 list/get/preflight 等已设计只读 action。
3. 工具构造时闭包注入 LeadIdentity/MemberIdentity，不在 schema 中出现 team_id、actor、sender、workspace、branch、ref 或 capability；旧 capability 调用由领域层拒绝。
4. 将调用映射到领域服务并规范化返回：reason code、对象 ID、revision、状态、逐项诊断和 display/complete 有界结果；工具不直接读 JSON、调 Git 或 tmux。
5. 团队控制工具按系统能力分类，业务边界由绑定/领域状态执行；CoordinatorCommand 仍经过自身严格策略，不因系统分类绕过。
6. 验证普通未绑定主入口无团队工具、普通 defined/fork 子 Agent 无团队工具、Lead/Plan/member 只见各自 schema、角色白名单不能获得 TeamMember/Integrate、成员不能伪造身份。
7. 验证工具名称、schema 和顺序在状态/后端/coordinator/热更新变化下稳定，且现有 Agent/Task schema 与顺序不变。

**验证：**

```text
.venv/bin/python -m pytest tests/test_team_tools.py tests/test_agent_delegation_integration.py -q
```

**提交边界：** 工具可见性、身份与 schema 稳定测试全部通过后提交一次。

## T15：`/team`、主 Agent 注入、TeamRuntime 与 CLI 接线

**文件：**

- `src/mycode/teams/commands.py`
- `src/mycode/teams/runtime.py`
- `src/mycode/teams/worker.py`
- `src/mycode/cli.py`
- `src/mycode/agent/runner.py`
- `src/mycode/commands/interfaces.py`
- `src/mycode/commands/models.py`
- `tests/test_team_commands.py`
- `tests/test_team_runtime.py`
- `tests/test_agent_runner.py`
- `tests/test_cli.py`

**依赖：** T9、T10、T11、T14

**步骤：**

1. 实现 `/team create|resume|switch|status|archive` CommandSpec 和严格参数解析，注册到默认 CLI 命令 registry；命令不调用模型，错误包含用法和可行动原因。
2. 扩展 CommandUI/状态模型并在 CLI adapter 中连接 TeamService/BindingManager；`/new` 清除 binding/capability 但不删除团队，下一会话需显式 resume。
3. 为 AgentRunner 增加可选 TeamToolRegistryProvider：现有 Skill/Plan registry 计算后按 session binding 合并固定团队变体；未提供 provider 时行为逐字保持现状。
4. 增加 Lead 邮箱 reserve/commit/release 钩子：在写主 session user 消息前组合有界团队消息，session journal 成功后 ack，失败 release；空闲 Lead 不因邮箱自动调用 Provider。
5. 实现 TeamRuntime 组合根，装配 store、audit、identity、binding、worktree、tasks、mailbox、approval、backend、member、integration、coordinator 和工具/命令；依赖用显式构造注入，保持模块无循环 import。
6. 在 CLI 参数入口优先识别隐藏 `team-worker` 子命令并交给 T9 worker；普通启动仍使用现有参数和恢复流程，不把内部命令加入用户 help。
7. 实现关闭顺序：冻结团队调度、停止 coroutine/tmux 成员并有界等待、持久化状态，再关闭现有 AgentTaskManager、MCP、Hook、memory、Provider 和 journal；单项超时仅告警。
8. 测试命令切换、多团队、工具下一请求生效、Lead 邮箱安全注入、`/new`、worker dispatch、普通 CLI 启动、退出顺序和团队故障不影响普通会话。

**验证：**

```text
.venv/bin/python -m pytest tests/test_team_commands.py tests/test_team_runtime.py tests/test_agent_runner.py tests/test_cli.py -q
```

**提交边界：** 用户入口、主 Agent 集成、worker 分派和 shutdown 测试全部通过后提交一次。

## T16：配置示例与用户文档

**文件：**

- `config.example.yaml`
- `README.md`

**依赖：** T15

**步骤：**

1. 在配置示例中列出全部 teams 默认值、合法范围、VerificationCommand 对象、coordinator 配置锁和 `MEWCODE_COORDINATOR=1` 用户锁；说明 argv 不做环境展开且 shell=False。
2. 记录 `/team` 五个子命令、显式绑定与 `/new` 行为、团队用户目录、活动/归档状态和 Git 工作区前提。
3. 记录角色快照、可写/只读成员、tmux/coroutine/auto 选择、可见降级、长期 worktree 与成员恢复语义。
4. 记录 SharedTask、Mailbox、四类结构化消息、计划版本审批、现有权限仍生效和成员非交互权限行为。
5. 记录原子集成、验证命令、冲突委派、失败保留成果，以及 coordinator 可做/不可做事项和受限 shell Git operation。
6. 明确不支持跨机器、实时流通信、守护进程、复杂调度、非 Git 写团队和归档恢复。
7. 对示例命令和配置片段执行人工核对，确保名称/schema 与实现及 Plan 一致。

**验证：**

```text
.venv/bin/python -m mycode --help
git diff --check -- README.md config.example.yaml
```

**提交边界：** 文档、示例和实际 CLI/schema 核对一致后提交一次。

## T17：端到端验收、兼容性与全量回归

**文件：**

- `tests/test_team_collaboration_integration.py`
- `tests/test_agent_delegation_integration.py`
- `tests/test_worktree_isolation_integration.py`
- 所有本功能新增测试文件

**依赖：** T1–T16

**步骤：**

1. 构造真实临时 Git 仓库和 fake Provider/tmux，覆盖创建团队、添加 tmux 成员、auto 降级 coroutine 成员、带依赖并行派工、成员直连邮箱、完成/idle 和工具隔离。
2. 覆盖审批端到端：版本一驳回、版本二批准、现有权限仍检查、CLI 关闭、停机消息、恢复同一成员/上下文及再次指派。
3. 覆盖集成端到端：多成员无冲突拓扑合并、验证、Lead 单次推进、成员基线同步；再制造冲突与验证失败，确认原 Lead 不变、临时结果清理、成员成果保留。
4. 覆盖 coordinator 端到端：双锁组合、直接/间接写入全部拒绝、只读检查和 scoped Git operation 可用、冲突修改必须委派、保护性归档保留审计。
5. 增加并发与恢复压力场景：任务 revision 竞争、消息/ack 崩溃窗口、重复 wake、worker ticket 重放、退出超时、集成推进边界恢复，验证唯一终态/消息/纳入结果。
6. 运行全部现有普通 Agent、一次性子 Agent、Skills、Hooks、MCP、权限、会话、上下文、命令、worktree 和 Provider 测试，修复回归但不扩大 Spec。
7. 运行编译、全量测试与格式差异检查，保存命令输出作为 checklist 验收证据。

**验证：**

```text
.venv/bin/python -m pytest tests/test_team_collaboration_integration.py -q
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src/mycode
git diff --check
```

**提交边界：** 端到端和全量回归全部通过后提交最终验收测试 commit；若修复涉及独立逻辑，先按对应任务边界提交修复，再提交验收测试。

## 执行顺序

可并行分支如下：

```text
T1 → T2 → T3 ─┬→ T4 → T5 → T6 → T7 ───────────────┐
              └→ T8 → T9 ───────────────┐          │
                                         ├→ T10 ────┼→ T11 ─┐
                         T4 ──────────────┘          │       │
                         T4 + T5 + T10 → T12 → T13 ─┴→ T14 ─┤
                                                              ├→ T15 → T16 → T17
                         T9 ───────────────────────────────────┘
```

约束说明：

- T4 与 T8 可在 T3 后并行。
- T5→T6→T7 与 T8→T9 两条链可并行。
- T10 等待长期 worktree 和两类后端；T11 再等待任务、邮箱、审批与生命周期服务。
- T12 可在 T10 和 T5 完成后与 T11 并行；T13、T14 汇合安全集成与领域工具。
- T15 是唯一 CLI/主 Agent 总接线任务，避免早期把半成品暴露到普通会话。
- 每个任务对应的局部验证必须通过后才可进入依赖它的任务；T17 才运行全量验收。

## Plan 模块覆盖

| Plan 组件 | Tasks |
|-----------|-------|
| 配置、模型、路径、锁 | T1 |
| 文件存储、事务、审计 | T2 |
| Actor、ticket、binding | T3 |
| 长期 worktree 与 Git | T4 |
| SharedTask/DAG | T5 |
| 协议、邮箱、广播、lease | T6 |
| 计划审批与 gating | T7 |
| backend 协议、选择、coroutine | T8 |
| tmux 与 team-worker | T9 |
| TeamService 生命周期与归档 | T10 |
| TeamMemberRuntime 与上下文恢复 | T11 |
| IntegrationService | T12 |
| coordinator 与 ScopedIntegrationGitExecutor | T13 |
| 身份化团队工具 | T14 |
| `/team`、AgentRunner、TeamRuntime、CLI | T15 |
| README 与配置示例 | T16 |
| 端到端、编译和全量回归 | T17 |
