# MewCode 长期团队协作 Checklist

> 本清单用于实现完成后的逐项验收。除人工观察项外，每项都给出可重复执行的验证方式。实现阶段只有在对应验证通过后，才能将项目勾选为完成。

## 1. 小组与生命周期

- [x] **AC1 — 创建并持久化小组。** 用户执行 `/team create <name>` 后，当前主会话成为 Lead；用户目录下生成按小组名隔离的目录，持久化名称、负责人、成员花名册和版本化元数据。重启 CLI 后数据仍可读取。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_commands.py tests/test_team_service.py tests/test_team_paths.py -k "create or persist"`，并在临时 HOME 中检查生成目录和 JSON 内容。

- [x] **AC2 — 显式恢复已有小组。** `/team resume <name>` 能恢复一个已持久化小组并绑定当前会话，不依赖之前的进程仍然存活。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_commands.py tests/test_team_runtime.py -k "resume"`。

- [x] **AC3 — 会话只绑定一个活动小组。** 同一主会话不能同时绑定多个小组；切换必须通过显式 `/team switch`，且不会破坏未选中小组的持久化状态。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_commands.py tests/test_team_service.py -k "switch or single_active"`。

- [x] **AC4 — 多个小组彼此隔离。** 同一用户可以保存多个小组；成员、任务、邮箱、审批、上下文与审计文件不能跨小组泄漏。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_paths.py tests/test_team_storage.py tests/test_team_service.py -k "isolation or multiple"`。

- [x] **AC5 — 成员花名册信息完整。** 每名成员都持久化名称、角色快照、工作目录、分支/工作树身份、实际运行后端、后端选择原因、审批要求和当前状态。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_service.py tests/test_team_identity.py -k "roster or member_metadata"`，并校验序列化往返一致。

- [x] **AC6 — 角色使用创建时快照。** 成员创建后继续使用当时的 Markdown Agent 角色快照；源角色文件变化不会静默改变现有成员，只有显式升级才更新快照。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_service.py tests/test_team_member_runtime.py -k "role_snapshot or role_upgrade"`。

- [x] **AC7 — 保护性归档小组。** `/team archive` 在成员运行中、存在未合并工作、脏工作树或待审批记录时拒绝执行；条件满足后将小组移动到归档位置并保留恢复所需数据。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_commands.py tests/test_team_service.py tests/test_team_worktrees.py -k "archive"`。

- [x] **AC8 — 成员工作树长期保留。** 可写成员始终使用独立 Git worktree/branch，且成员自然停下或 CLI 重启后仍保留，直到小组归档。只读成员允许共享只读目录。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_worktrees.py tests/test_team_service.py -k "long_lived or writable or readonly"`。

- [x] **AC9 — 自动后端选择可解释。** `auto` 在 tmux 可用时选择 tmux；不可用时选择 coroutine，并把降级原因写入成员元数据和用户可见输出，禁止静默降级。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_backend_selector.py tests/test_team_commands.py -k "auto or fallback or reason"`。

- [x] **AC10 — 显式后端不静默替换。** 用户显式要求 tmux 而环境不满足时，创建成员失败并说明原因；显式 coroutine 则稳定选择 coroutine。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_backend_selector.py -k "explicit"`。

- [x] **AC11 — 两种后端使用同一成员语义。** tmux worker 与同进程 coroutine 都使用相同的成员身份、任务、审批、邮箱、上下文和状态转换协议。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_tmux_backend.py tests/test_team_coroutine_backend.py tests/test_team_member_runtime.py -k "shared_contract or lifecycle"`。

## 2. 工具可见性与共享任务

- [x] **AC12 — 协作工具仅对绑定角色开放。** 已绑定 Lead 获得成员、共享任务、邮箱和集成工具；成员只获得共享任务与邮箱工具；未绑定主入口和普通一次性子 Agent 看不到任何团队协作工具。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_tools.py tests/test_tools_registry.py tests/test_agent_runner.py -k "visibility or unbound or member or lead"`。

- [x] **AC13 — Plan/Do 工具权限分离。** Plan 模式下 Lead 只能使用团队只读操作；Do 模式才开放获准的变更操作，工具 schema 与运行时授权一致。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_tools.py tests/test_tools_registry.py -k "plan or do or readonly"`。

- [x] **AC14 — Lead 可管理完整任务生命周期。** Lead 能创建、查询、更新、指派、取消和逻辑删除共享任务，并能设置依赖关系。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_shared_tasks.py tests/test_team_tools.py -k "lead_crud or assign or cancel or delete"`。

- [x] **AC15 — 成员任务权限受限。** 成员可读取同组任务、创建任务、更新自己任务的状态和工作日志；不能更改指派、依赖、取消或删除任务，也不能更新他人任务状态。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_shared_tasks.py tests/test_team_tools.py -k "member_permissions"`。

- [x] **AC16 — 依赖引用合法。** 任务依赖只能指向同一小组内存在且未逻辑删除的任务；缺失引用、跨组引用和自依赖被拒绝并返回明确错误。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_shared_tasks.py -k "missing_dependency or cross_team or self_dependency"`。

- [x] **AC17 — 循环依赖被拒绝。** 创建或更新依赖时检测完整有向图，任何直接或间接环都不能落盘。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_shared_tasks.py -k "cycle"`。

- [x] **AC18 — 未满足依赖阻止开工。** 任务只有在全部直接依赖处于完成状态后才能进入进行中或触发成员执行；失败时说明阻塞任务。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_shared_tasks.py tests/test_team_member_runtime.py -k "blocked or dependency_completion"`。

- [x] **AC19 — 删除为受约束逻辑删除。** 删除保留记录和审计历史；仍被活动任务依赖、正在执行或关联待审批的任务不可删除。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_shared_tasks.py tests/test_team_storage.py -k "logical_delete or delete_guard"`。

## 3. 邮箱与结构化协议

- [x] **AC20 — 消息按规范持久化。** 每条邮箱消息落盘时包含发件人、正文、服务端时间戳、默认未读状态和摘要；JSONL 记录可在重启后继续读取。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_mailbox.py -k "persist or defaults or restart"`。

- [x] **AC21 — 名称注册表与邮箱两段式投递。** 发送前通过同组名称注册表解析目标，再原子追加到目标邮箱；未知、歧义或跨组目标被拒绝。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_identity.py tests/test_team_mailbox.py -k "registry or resolve or unknown or cross_team"`。

- [x] **AC22 — 点对点与广播正确投递。** 点对点消息只进入目标邮箱；广播进入除发送者外的全部当前成员邮箱，并为每位接收者保留独立已读状态。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_mailbox.py -k "direct or broadcast"`。

- [x] **AC23 — 只接受约定结构化协议。** 系统识别并校验任务指派/变更、审批请求、批准/驳回、状态通知等结构化消息；未知类型、缺字段或字段类型错误不能进入业务状态机。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_protocols.py tests/test_team_mailbox.py -k "schema or invalid or message_type"`。

- [x] **AC24 — tmux 投递后额外唤醒目标。** 消息先成功落盘，再通过已验证的 pane PID 发送 SIGUSR1 唤醒 tmux worker；唤醒失败不丢消息，并产生可见状态/审计记录。coroutine 后端不执行进程信号。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_tmux_backend.py tests/test_team_mailbox.py -k "wake or signal or persisted_first"`。

- [x] **AC25 — 邮箱游标与已读确认可恢复。** 成员只处理游标之后的新消息；确认读取后持久化已读状态和游标，重启不会无故重复消费或跳过未确认消息。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_mailbox.py tests/test_team_member_runtime.py -k "cursor or ack or unread or recovery"`。

## 4. 审批、成员恢复与 Lead 编排

- [x] **AC26 — 需审批成员先提交计划。** 标记为需要审批的成员在执行写操作前，必须发送绑定成员、任务和计划版本的审批请求，并停在等待状态。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_approvals.py tests/test_team_member_runtime.py -k "request or gate or waiting"`。

- [x] **AC27 — 只有匹配的结构化决定生效。** Lead 的批准/驳回必须使用规定结构，且成员、任务、计划版本完全匹配；过期、重复、伪造或由非 Lead 发出的决定无效。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_approvals.py tests/test_team_protocols.py -k "approve or reject or stale or unauthorized"`。

- [x] **AC28 — 审批不扩大既有权限。** 批准只解除当前计划版本的团队审批门禁，不授予工具、文件或命令层面的额外权限；计划变更后必须重新审批。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_approvals.py tests/test_team_tools.py -k "permission or plan_version or reapprove"`。

- [x] **AC29 — 空闲成员可从磁盘恢复。** 成员自然完成后标记为空闲并通知 Lead；后续消息能恢复其规范化对话、元数据、当前任务、有效审批状态和邮箱游标继续工作，不恢复临时授权或中断中的工具调用。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_member_runtime.py tests/test_team_coroutine_backend.py tests/test_team_tmux_backend.py -k "idle or restore or context"`。

- [x] **AC30 — Lead 按依赖拆解与派工。** Lead 能把用户目标写成带依赖任务，只有就绪任务可被派发；成员完成或失败后更新共享状态并通知 Lead，使后继任务可被重新评估。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_shared_tasks.py tests/test_team_runtime.py tests/test_team_collaboration_integration.py -k "orchestration or dependency_dispatch"`。

- [x] **AC31 — 集成前置条件完整。** 只有已完成、已提交、工作树干净且提交属于对应成员分支的任务才能进入集成；未完成依赖、脏目录、无提交或身份不匹配都会阻止集成。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_integration.py tests/test_team_worktrees.py -k "precondition or dirty or identity"`。

- [x] **AC32 — 按拓扑顺序原子集成。** 系统在临时 integration worktree/branch 中按任务依赖拓扑顺序合并成员提交并运行配置的验证命令；全部成功后才以 fast-forward 推进 Lead。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_integration.py tests/test_team_collaboration_integration.py -k "topological or atomic or fast_forward"`。

- [x] **AC33 — 无法自动解决的冲突不污染 Lead。** 冲突可在临时集成环境中解决；不能安全解决时中止并上报，Lead 分支、索引和工作树保持原样，失败状态与诊断被持久化。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_integration.py -k "conflict or rollback or lead_unchanged"`。

- [x] **AC34 — 集成可从崩溃恢复。** 在合并、验证、提交或推进 Lead 的任一阶段中断后，重启能根据持久化集成记录和 Git 状态安全继续或回滚，不重复推进和不遗留错误锁。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_integration.py tests/test_team_storage.py -k "crash or recovery or idempotent"`。

## 5. Coordinator、安全与兼容性

- [x] **AC35 — Coordinator 由两把锁共同启用。** 只有配置 `teams.coordinator.enabled=true` 且环境变量 `MEWCODE_COORDINATOR=1` 同时满足时才启用；任一缺失都保持普通 Lead 模式，并输出可诊断原因。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_coordinator.py tests/test_config.py -k "two_lock or enabled or env"`。

- [x] **AC36 — Coordinator 失去通用写能力。** 开启后，Lead 看不到 `write_file`、`edit_file`、`run_command` 等通用写工具，只保留读类工具及受限协调、终止、消息和集成能力。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_coordinator.py tests/test_tools_registry.py -k "tool_surface or remove_write"`。

- [x] **AC37 — Coordinator shell 受结构化白名单限制。** shell 只能执行只读 argv、配置中通过校验的验证命令，或绑定具体 integration id 的固定 Git 操作；模型不能注入任意路径、ref、提交、消息、重定向或 shell 控制符。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_coordinator.py tests/test_team_integration.py -k "command_allowlist or injection or scoped_git"`。

- [x] **AC38 — Coordinator 不亲自修改冲突。** 遇到需要改文件的集成冲突时，Coordinator 只能派发冲突修复任务给成员、等待新提交并重新集成，不能通过自身工具改源文件。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_coordinator.py tests/test_team_collaboration_integration.py -k "delegate_conflict"`。

- [x] **AC39 — 持久化路径与权限安全。** 团队数据默认位于用户目录，不写入项目仓库；名称经过安全规范化，启动票据权限为 0600，路径穿越、符号链接逃逸和跨成员锁访问被拒绝。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_paths.py tests/test_team_identity.py tests/test_team_locking.py -k "permission or traversal or symlink or ticket"`。

- [x] **AC40 — 资源限制与超时生效。** 配置的成员数、任务数、依赖数、消息/邮箱/上下文/日志大小、锁超时、worker 启动超时和集成超时均有默认值、可校验，并在越界时明确失败而非无限增长或等待。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_config.py tests/test_team_storage.py tests/test_shared_tasks.py tests/test_team_mailbox.py tests/test_team_backend_selector.py -k "limit or timeout or validation"`。

- [x] **AC41 — 跨文件更新可恢复且可审计。** 任务、审批、成员、邮箱和集成的多文件变更使用锁与暂存事务，记录 intent/commit、前后哈希和操作者；崩溃后确定性前滚，不向读者暴露半完成状态。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_storage.py tests/test_team_locking.py tests/test_team_integration.py -k "transaction or audit or forward_recovery or atomic"`。

- [x] **AC42 — 现有单 Agent 与短期委派保持兼容。** 未使用 `/team` 时，现有聊天、工具、普通子 Agent、一次性工作树隔离和安全策略的行为及测试均不回退。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_agent_runner.py tests/test_agent_delegation_integration.py tests/test_worktree_isolation_integration.py tests/test_tools_registry.py`。

- [x] **AC43 — 错误与状态对用户可见。** 后端降级、依赖阻塞、审批等待、邮箱唤醒失败、恢复、归档拒绝、集成失败和 Coordinator 锁状态均通过稳定、可操作的 CLI/工具结果呈现，且不泄露票据或敏感路径内容。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_commands.py tests/test_team_tools.py tests/test_team_runtime.py -k "diagnostic or status or redaction or error"`。

## 6. 端到端场景

- [x] **AC44 — coroutine 团队完整闭环。** 创建小组，派生两个 coroutine 成员，建立带依赖任务，完成点对点/广播消息与审批，成员空闲后恢复，最终原子集成到 Lead。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_collaboration_integration.py -k "coroutine_full_flow"`。

- [x] **AC45 — tmux 持久化与唤醒闭环。** 在可用 tmux 环境中创建成员，验证 worker 票据、邮箱先落盘再 SIGUSR1 唤醒、CLI 重启后的团队恢复和成员继续执行；无 tmux 的 CI 仅允许明确 skip，不能假装通过。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_collaboration_integration.py tests/test_team_tmux_backend.py -k "tmux_full_flow or tmux_wake"`，并在 tmux 可用的集成环境至少执行一次非 mock 场景。
  当前证据：本机 `tmux 3.7b`；`test_tmux_full_flow_uses_real_pane_and_signal` 已使用真实 session/pane/PID 完成 SIGUSR1 唤醒与清理，票据消费、邮箱先落盘和 CLI 恢复由相邻自动化场景覆盖。

- [x] **AC46 — 集成失败保持原子性。** 两名成员提交产生不可自动解决的冲突或验证失败后，临时集成记录失败、Lead 完全不变；修复提交后可安全重试并一次性推进 Lead。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_collaboration_integration.py -k "integration_failure_retry"`。

- [x] **AC47 — Coordinator 双锁与冲突委派闭环。** 分别验证零锁、单锁、双锁工具面；双锁模式下 Coordinator 只能派人、终止、发消息、执行受限验证与集成，并能把冲突修复委派给成员后完成合并。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_collaboration_integration.py tests/test_team_coordinator.py -k "coordinator_full_flow or two_lock"`。

## 7. 架构与集成约束

- [x] **长期团队域不复用短期 AgentTaskManager 状态。** `mycode.teams` 拥有独立的持久化模型和生命周期；与现有 Agent runner、工具注册表、CLI、Git worktree 支持仅通过计划中的接口集成。  
  验证：代码审查 `src/mycode/teams/` 的导入边界，并运行 `.venv/bin/python -m pytest -q tests/test_team_runtime.py tests/test_agent_delegation_integration.py`。

- [x] **模块依赖无计划外环。** storage 不导入 audit、tasks 只依赖注入的 ApprovalLookup、mailbox 只依赖注入的 WakeNotifier、backend 不导入 TeamService；顶层团队模块均可独立导入。  
  验证：运行 `.venv/bin/python -c "import mycode.teams.runtime, mycode.teams.storage, mycode.teams.tasks, mycode.teams.mailbox, mycode.teams.backends.selector"`，再进行导入关系代码审查。

- [x] **tmux 与 coroutine 共享运行时核心。** 两种后端只负责启动、停止和唤醒差异，成员任务执行、审批、邮箱与状态转换由同一 runtime contract 驱动。  
  验证：代码审查 `src/mycode/teams/backends/` 与 `src/mycode/teams/member.py`，并运行 `.venv/bin/python -m pytest -q tests/test_team_tmux_backend.py tests/test_team_coroutine_backend.py tests/test_team_member_runtime.py`。

- [x] **集成 Git 能力只有一个受限执行边界。** TeamIntegrate 与 CoordinatorCommand 共用 `ScopedIntegrationGitExecutor`，不存在第二条可接受任意 ref、路径或命令文本的集成通道。  
  验证：代码搜索所有集成 Git 调用点并审查参数来源；运行 `.venv/bin/python -m pytest -q tests/test_team_integration.py tests/test_team_coordinator.py -k "scoped"`。

- [x] **文档和示例配置同步。** `README.md` 与 `config.example.yaml` 说明团队创建/恢复、后端选择、审批、归档、Coordinator 双锁、限制项和 tmux 可选依赖，默认配置保持安全关闭 Coordinator。  
  验证：人工核对文档；运行 `.venv/bin/python -m pytest -q tests/test_config.py tests/test_cli.py -k "team or coordinator"`。

## 8. 构建、质量与最终回归

- [x] **源码可编译。** 所有新增和修改 Python 模块无语法错误。  
  验证：运行 `.venv/bin/python -m compileall -q src/mycode`。

- [x] **团队单元与集成测试全通过。** 团队领域的路径、锁、事务、身份、服务、任务、协议、邮箱、审批、工作树、后端、成员、工具、集成、Coordinator、命令和 runtime 测试全部通过。  
  验证：运行 `.venv/bin/python -m pytest -q tests/test_team_*.py tests/test_shared_tasks.py tests/test_team_collaboration_integration.py`。

- [x] **完整回归测试全通过。** 项目原有与新增测试在同一环境中全部通过，且没有通过删除、弱化或无条件跳过测试来制造成功。  
  验证：运行 `.venv/bin/python -m pytest -q`，审查 skip/xfailed 数量变化及原因。

- [x] **补丁格式与仓库卫生通过。** 无尾随空白、冲突标记、意外生成物、团队运行数据或凭据进入仓库。  
  验证：运行 `git diff --check`、`git status --short`，并搜索 `<<<<<<<|=======|>>>>>>>`；人工确认 `~/.mycode/teams` 数据未被纳入版本控制。

- [x] **CLI 冒烟验证通过。** 主命令帮助、`/team` 帮助、隐藏 worker 入口和普通非团队聊天均可启动；错误参数返回稳定非零状态与可操作提示。  
  验证：运行 `.venv/bin/python -m mycode --help`、相关 CLI 测试，以及一个使用临时 HOME/Git 仓库的创建—状态—恢复—归档冒烟流程。

## 9. 最终完成条件

- [x] AC1–AC47 均有对应自动化或明确人工证据，所有失败项均已修复或由用户书面接受。
- [x] `spec.md`、`plan.md`、`task.md`、本 `checklist.md` 与最终实现保持一致；若实现中出现需求或架构变更，先回写并重新审批相应文档。
- [x] 最终交付说明列出已执行命令、测试结果、任何环境性 skip、已知限制，以及团队数据和工作树的清理/归档方式。
