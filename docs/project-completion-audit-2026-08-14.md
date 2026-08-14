# MewCode 项目完工审计报告

- 审计日期：2026-08-14（Asia/Shanghai）
- 审计提交：`90edaa9 Add team collaboration runtime`
- 审计结论：**不建议按“彻底完工”验收**
- 当前状态：**仅记录，全部待审核，未修复**

## 1. 结论摘要

项目的常规路径完成度较高：775 个测试已被收集，排除一个已确认的并发脆弱用例后 774 个测试通过；语句覆盖率为 82.39%；247 个 Python 文件均可按 Python 3.10 语法解析，144 个 `mycode` 模块均可导入；隔离 PEP 517 wheel 构建、`pip check`、CLI 帮助和 `git diff --check` 均成功。

但深入反例、故障注入和真实 tmux 测试发现了会阻止正式验收的问题：

1. Coordinator 的“禁止亲自写文件”边界可以通过被放行的只读命令参数或残留的第三方副作用工具绕过。
2. 通用命令沙箱可借助环境变量改变工作目录后读取工作区外文件。
3. 带陈旧 revision 的团队归档会先删除成员 worktree，随后才报告 revision conflict，产生已拒绝操作仍破坏资源的结果。
4. Git 集成推进 Lead 时会执行仓库 `post-merge` hook，并能在工作区已被 hook 写脏后仍把集成标记为 completed。
5. 团队角色快照中的 `permission_mode` 没有进入成员权限实例，审批也因此不能证明“不扩大既有权限”。
6. 任务、成员、邮箱、审批等业务转换没有按设计形成同一可恢复事务；运行任务取消后可把成员永久留在 running 状态。
7. 默认 tmux worker 在当前交付环境中无法启动，自定义 `--config` 也不会传给 worker；启动异常会把成员留在 starting，auto 模式对真实启动失败不回退。
8. 业务审计几乎没有接入：实际只记录 actor=`system` 的 `store_transaction` intent/committed，团队审计实现覆盖率为 0%。
9. 超时不会终止正在执行的工具线程或 shell 子进程树，已返回“超时”的操作仍可稍后修改文件。
10. 持久化存在单次 `os.write` 导致短写损坏、最大合法任务链递归溢出、损坏字段被静默转成 `None` 等问题。

本报告共记录：

| 等级 | 数量 | 含义 |
|---|---:|---|
| P0 | 3 | 安全/能力边界可绕过，应阻止发布 |
| P1 | 11 | 数据破坏、状态不一致或核心功能不可用 |
| P2 | 12 | 明确功能缺陷、恢复缺口或显著可靠性风险 |
| P3/质量 | 5 | 测试、类型、环境或可维护性信号 |

## 2. 审计范围与方法

### 2.1 盘点范围

- Python 文件：247 个，共 36,165 行。
- 可导入 `mycode` 模块：144 个。
- Pytest 收集：775 个测试。
- 重点审查：Agent loop、工具执行、权限/路径沙箱、Provider、会话、MCP、Hook、worktree、团队持久化、任务、邮箱、审批、后端、Coordinator、Git 集成、CLI 装配与规格/验收文档。
- 团队规格基线：`specs/team-collaboration/spec.md`、`plan.md`、`checklist.md`。

### 2.2 已执行验证

| 验证 | 结果 |
|---|---|
| `pytest --collect-only` | 775 个测试 |
| 完整测试（`PYTHONHASHSEED=0`） | 1 failed, 774 passed；并发完成顺序用例失败 |
| 单个并发用例重复 30 次 | 3 次失败，约 10% |
| 排除上述用例并启用覆盖率 | 774 passed, 1 deselected，78.14s |
| 语句覆盖率 | 82.39%（10,858 / 13,179） |
| 排除上述用例并使用 `-W error` | 1 failed, 773 passed, 1 deselected；暴露未关闭 SessionJournal |
| Python 3.10 AST 兼容解析 | 247/247 成功 |
| 全模块导入 | 144/144 成功 |
| 隔离 PEP 517 wheel 构建 | 成功，`mycode-0.1.0-py3-none-any.whl` |
| `pip check` | 无损坏依赖 |
| CLI `--help` | 成功 |
| `git diff --check` | 成功 |
| 敏感串扫描 | 只命中检测规则本身及测试用假 secret，没有发现交付凭据 |
| Ruff 默认规则 | 360 项，其中 209 项可自动修复；需区分格式噪音与真实风险 |
| Mypy（无项目专用配置） | 141 个 error；团队工具/存储/运行时和会话流最密集 |
| 当前虚拟环境 `pip-audit` | 1 个已知漏洞，来自项目未声明的额外顶层包，见 Q-04 |
| 真实 tmux pane/PID/SIGUSR1 | 测试替身可通过；默认交付入口实际失败，见 F-08 |

### 2.3 覆盖率风险分布

总体覆盖率不能代表新增团队主链路已被充分验证。关键模块覆盖率如下：

| 模块 | 覆盖率 |
|---|---:|
| `src/mycode/teams/audit.py` | 0.00% |
| `src/mycode/teams/worker.py` | 27.37% |
| `src/mycode/teams/tools.py` | 38.97% |
| `src/mycode/teams/runtime.py` | 46.41% |
| `src/mycode/teams/worktrees.py` | 56.83% |
| `src/mycode/teams/coordinator.py` | 57.30% |
| `src/mycode/teams/backends/tmux.py` | 63.54% |
| `src/mycode/teams/service.py` | 66.04% |
| `src/mycode/teams/tasks.py` | 67.93% |
| `src/mycode/teams/integration.py` | 74.10% |

## 3. P0：安全与能力边界绕过

### F-01 Coordinator “只读命令”可读工作区外文件并写入工作区

- 状态：动态复现，未修复。
- 位置：`src/mycode/teams/coordinator.py:47-67`。
- 违反：AC36、AC37、AC38、AC47；Plan 约定 Coordinator 不能注入任意路径或危险 Git 选项。

反例 A：在双锁开启的 Coordinator 中执行：

```text
argv = ["rg", "AUDIT_SECRET", "../outside.txt"]
```

策略接受该 argv，并读取到了工作区外测试文件。实现只拒绝参数恰好等于 `..` 或以 `/` 开头，没有拒绝 `../outside.txt`。

反例 B：执行：

```text
argv = ["git", "diff", "--output=.mycode/coordinator-write"]
```

命令被当作只读 `git diff` 接受，返回成功并创建文件。当前校验只屏蔽 `--config` 和 `ext::`，没有屏蔽 `--output`、外部 diff/textconv 等写入/执行型选项。

影响：Coordinator 可绕过“剥夺写文件工具”的核心能力边界，读取团队工作区外数据或直接生成文件。

### F-02 Coordinator 只移除三个内置工具，第三方副作用工具仍保留

- 状态：动态复现，未修复。
- 位置：`src/mycode/teams/tools.py:407-419`。
- 违反：AC36、AC47；Plan 明确“不注册任何等价写工具”。

反例：向主 registry 注册一个名为 `remote__delete` 的副作用工具，开启 Coordinator 双锁后调用 `registry_for`，该工具仍然存在。实现仅执行：

```python
registry.exclude({"write_file", "edit_file", "run_command"})
```

MCP 工具按项目规则全部属于副作用工具，因此任意 MCP 写操作、专用删除/发布/数据库工具都可能继续暴露给 Coordinator。

影响：Coordinator 的能力收缩依赖工具名称而非安全分类，无法对扩展工具生态成立。

### F-03 通用 shell 路径校验可通过环境变量和 `cd` 逃离工作区

- 状态：动态复现，未修复。
- 位置：`src/mycode/permissions/sandbox.py:75-145`、`src/mycode/tools/command.py:28-44`。

反例：在 `ToolContext.process_environment` 中设置 `MEWCODE_AUDIT_OUTSIDE=<外部目录>`，然后执行：

```sh
cd $MEWCODE_AUDIT_OUTSIDE && cat secret.txt
```

`validate_command_paths` 接受该命令，`RunCommandTool` 使用 `shell=True` 和合并后的环境执行，成功读到工作区外的 secret。

根因：带 `$` 但不含 `/` 的 token 不会被视为路径；校验器也不跟踪前一个 shell 段执行 `cd` 后的新 cwd，后续相对路径仍按原始 workspace 判断。

影响：路径沙箱的判定结果与真实 shell 语义不一致。只要该命令通过权限层，工作区边界即可被绕过。

## 4. P1：数据破坏、核心状态和主流程缺陷

### F-04 陈旧 revision 的归档请求会先删除 worktree 再失败

- 状态：动态复现，未修复。
- 位置：`src/mycode/teams/service.py:190-208`。
- 违反：AC7、AC41；保护性归档与乐观并发语义。

反例：读取团队 revision，随后让团队产生一次更新，再用陈旧 revision 调用 `archive_team`。结果为：

```text
error = revision_conflict
team.status = active
member.worktree.exists = false
```

根因：成员 worktree 在带 expected revision 的 `store.transact` 之前被逐个 dispose。事务拒绝后没有补偿恢复。

影响：一个被明确拒绝的归档操作仍可删除成员工作资源，属于破坏性并发错误。

### F-05 Lead fast-forward 会执行 Git hook，且工作区写脏后仍标记 completed

- 状态：动态复现，未修复。
- 位置：`src/mycode/worktrees/git.py:89-103`、`src/mycode/teams/integration.py:217-243`。
- 违反：AC32、AC46；Plan 要求关闭 Git hooks，并在推进后重新确认 clean status。

反例：在 Lead 仓库增加 `.git/hooks/post-merge`，hook 创建一个文件。团队集成返回：

```text
integration.status = completed
hook marker exists = true
lead clean = false
```

临时集成的 `merge_no_ff` 使用 `core.hooksPath=/dev/null`，但最终 `fast_forward` 只是普通 `git merge --ff-only`。推进后只检查 HEAD 是否等于 merged commit，不再检查工作区是否干净。

影响：集成过程可触发用户/攻击者控制的本地代码，产生未经验证的文件改动，同时持久化状态宣称成功。

### F-06 成员角色的 `permission_mode` 只被持久化，没有用于成员权限实例

- 状态：代码路径确认，未修复。
- 位置：`src/mycode/cli.py:453-523`、`src/mycode/teams/worker.py:28-80`；团队目录内 `permission_mode` 仅在模型/存储中出现。
- 违反：F11、F33、AC6、AC28；角色快照和审批“不扩大既有权限”的语义。

`_CLIMemberAgent` 直接复用主 CLI 的 `permission_service`；`_WorkerMemberAgent` 从工作区权限配置以 override=`None` 新建权限服务。两条路径都没有读取 `member.role.permission_mode`。

影响：角色声明为 `strict` 的团队成员可继承主会话/default/allow 语义；角色快照不能完整决定成员权限。批准计划后的有效能力也可能大于角色所声明的基础权限。

### F-07 业务状态转换没有按设计组成原子、可恢复事务

- 状态：动态故障注入 + 代码路径确认，未修复。
- 位置：`src/mycode/teams/tasks.py:219-281`，审批和投递也采用类似多次事务编排。
- 违反：AC41；Plan 中“决定、任务新状态和结构化回复同事务提交”等约束。

已确认的窗口包括：

- `request_start` 先把任务改为 running，再单独设置成员 `current_task_id`；第二步失败会得到 running task + 未指派成员。
- `complete` 先把任务改为 completed，再单独清成员和重算依赖；任一步失败都会留下部分终态。
- `cancel` 只改任务，不清理当前执行成员。
- 指派/状态变化后才单独发邮箱通知；通知失败时 API 可返回失败，但业务状态已经提交。
- 审批 submit/decide 也跨任务、审批、邮箱多步提交，只对一小部分通知提供 resume 修补。

这些业务步骤虽然每个底层文件事务有 intent/committed，但整体业务转换不是单一事务，也没有统一 saga 状态。

### F-08 默认 tmux worker 装配在当前交付环境中不可运行，且丢失自定义配置

- 状态：真实 tmux 动态复现，未修复。
- 位置：`src/mycode/teams/backends/tmux.py:25-87`、`src/mycode/teams/worker.py:84-89`。
- 违反：AC9、AC10、AC11、AC45。

当前环境：

```text
tmux = /usr/local/bin/tmux
shutil.which("mycode") = None
.venv/bin/mycode exists = true
```

`TmuxBackend` 默认硬编码 executable=`"mycode"`。真实启动结果：

```text
which_mycode None
start_error tmux_identity_failed 无法验证成员 tmux pane 身份。
```

现有真实 tmux 测试使用自己创建的 `fake-mycode`，因此没有覆盖默认入口。另一个问题是启动命令没有 `--config`，而 worker 默认读取 `config.yaml`；Lead 若使用 `mycode --config custom.yaml`，隔离 worker 会找不到或使用错误的 Provider/团队配置。

### F-09 后端真实启动失败会把成员留在 starting，auto 不做启动级回退

- 状态：动态故障注入，未修复。
- 位置：`src/mycode/teams/runtime.py:40-79`、`src/mycode/teams/backends/selector.py:24-47`。
- 违反：F14、AC9、AC43；Plan 的 preparing/补偿和 auto 恢复语义。

向选中后端注入 `start_boom` 后，调用抛错，持久化成员生命周期仍为 `starting`。`TeamService.start_member` 只允许 offline/idle/failed，因而同一会话不能直接重试。auto 的 fallback 只发生在 probe 阶段；tmux probe 成功但实际 pane 启动失败时，不会尝试 coroutine。

### F-10 独立 worker 无法可靠点对点唤醒另一个成员

- 状态：动态复现，未修复。
- 位置：`src/mycode/teams/runtime.py:34-104`。
- 违反：F25、F29、AC21、AC24、AC45。

在没有 Lead session binding 的 worker 运行时中，成员向另一成员发送消息：消息能落盘，但唤醒返回警告。其 backend manager 没有目标 backend 的进程内映射，于是调用 `start_member`；后者再通过 `bound_team_for_member` 扫描当前进程的 Lead bindings，独立 worker 中没有该绑定，最终失败。

影响：成员之间“无需 Lead 中转”的邮箱持久化成立，但实时唤醒/恢复不成立，尤其是 tmux 独立进程互相协作场景。

### F-11 超时只停止等待，不停止实际工具/子进程副作用

- 状态：两种动态反例均复现，未修复。
- 位置：`src/mycode/tools/executor.py:65-86`、`src/mycode/tools/command.py:28-105`。

反例 A：自定义慢写工具超过 ToolExecutor timeout。调用先返回“工具执行超时”，标记文件当时不存在；稍后后台线程继续运行并创建了文件。`future.cancel()` 无法终止已运行的 Python 线程，`shutdown(wait=False)` 允许副作用继续。

反例 B：运行：

```sh
(sleep 0.25; echo late > child-late.txt) & wait
```

timeout 设为 0.05 秒。工具返回超时，但子进程稍后仍创建 `child-late.txt`。`subprocess.run(shell=True)` 超时终止的是外层 shell 等待，不是受控进程组的全部后代。

影响：调用者看到失败/超时后不能假设没有写入；审批、重试和事务语义都可能被破坏。

### F-12 单次 `os.write` 可造成成功返回但持久化 JSON 被截断

- 状态：动态短写注入，未修复。
- 位置：`src/mycode/teams/storage.py:644-655, 757-763`、`src/mycode/teams/audit.py:28-41`、`src/mycode/teams/identity.py:128`。
- 违反：AC39、AC41；持久化完整性。

将 `os.write` 注入为只写入一半字节后，`FileTeamStore.create` 返回成功；重新加载团队得到 `invalid_json`。批量 JSONL 路径已经正确循环写完全部字节，但单记录 append、原子 JSON 临时文件、审计和 worker ticket 仍只调用一次 `os.write`。

影响：短写虽不常见，但属于 POSIX 允许行为；磁盘/文件系统压力下可产生不可恢复的半文件，同时上层误认为成功。

### F-13 Worktree 初始化会跟随目录内部 symlink 复制外部内容

- 状态：动态复现，未修复。
- 位置：`src/mycode/teams/worktrees.py:107-147`。
- 违反：AC39；路径与符号链接逃逸约束。

反例：初始化 source 目录本身位于工作区内，但目录内部包含指向外部 secret 的 symlink。`rglob(...).is_file()` 会跟随该链接统计，随后 `shutil.copytree(..., symlinks=False)` 把外部 secret 内容复制为成员 worktree 中的普通文件。

影响：工作区内一个链接可把任意可读外部文件带进团队 worktree 和模型上下文。项目已有的通用 `WorkspaceInitializer` 对此更严格，但 TeamWorktreeManager 没复用该保护。

### F-14 Provider 流消费期间取消令牌无效，可无限等待

- 状态：动态阻塞 Provider 反例，未修复。
- 位置：ProviderPool/OpenAI/Anthropic 使用 `httpx.Client(timeout=None)`；Agent 只在进入/离开流消费边界检查取消。

反例：fake provider 在产生下一个流事件前阻塞，随后设置 cancellation token。0.2 秒后 runner 线程仍存活；只有手工释放 provider 后才结束。

影响：用户取消、团队 shutdown timeout 和 coroutine stop 都不能打断卡住的网络流。该问题也与 `docs/agent-code-review-recommendations.md` 中已有的 cancellation blind spot 一致。

## 5. P2：功能、恢复和可靠性缺陷

### F-15 取消 running 任务会把成员永久留在 running

- 状态：动态复现，未修复。
- 位置：`src/mycode/teams/tasks.py:274-281`。

运行任务被 Lead cancel 后：

```text
task.status = cancelled
member.current_task_id = <该任务>
member.lifecycle = running
```

成员随后尝试完成任务会得到 `invalid_task_transition`。当前没有由 cancel 触发的成员停止、清理或 needs_attention 转换。

### F-16 Mailbox `get_message` 永久搜索不到批次之外的消息

- 状态：动态复现，未修复。
- 位置：`src/mycode/teams/mailbox.py:111-133, 164-176`。

把 `mailbox_batch_size` 设为 2，发送 3 条消息后，用第三条 ID 调 `get_message`，返回 `message_not_found`。实现始终通过 `list_messages(..., limit=batch_size)` 查找，且视图从最早记录切片；已读消息仍占据该批次。`commit_lease` 的序号恢复也受相同查找限制。

### F-17 最大合法 1,000 任务链触发 `RecursionError`

- 状态：动态复现，未修复。
- 位置：`src/mycode/teams/storage.py:597-625`。

按默认 `max_tasks=1000` 构造一条合法无环链 `task999 -> ... -> task0`，`_validate_aggregate` 在递归 DFS 中触发 Python `RecursionError`，没有返回领域错误。资源限制允许的边界值本身不可可靠处理。

### F-18 “严格”持久化解析会静默吞掉损坏字段

- 状态：动态复现，未修复。
- 位置：`src/mycode/teams/storage.py:157-168` 及若干 `str(...)`/可选字段转换。

把持久化 `pane_pid` 改为字符串 `"corrupt"`，团队仍成功加载，只是该值被静默转为 `None`。相同模式还会把部分 ID/可选字段的错误类型强制字符串化或置空。

影响：磁盘损坏或不兼容 schema 被伪装成“值缺失”，恢复逻辑无法区分真实离线与元数据破坏。

### F-19 显式后端选择仍会探测所有后端

- 状态：动态计数复现，未修复。
- 位置：`src/mycode/teams/backends/selector.py:24-39`。
- 违反：Plan 明确“显式后端只探测指定项”。

显式选择 coroutine 时，tmux probe 和 coroutine probe 各被调用一次。除多余延迟外，未选择后端的探测异常也可能阻止本应稳定的显式选择。

### F-20 Coroutine 取消事件没有传入真实 Agent 执行

- 状态：代码路径确认，未修复。
- 位置：`src/mycode/teams/runtime.py:124-134`、`src/mycode/teams/member.py:69-129`、CLI/worker MemberAgent 接口。

CoroutineBackend 把 `threading.Event` 传给 `TeamMemberRuntime.run(identity, cancellation)`，但该参数之后没有被读取；`MemberAgent.run` 协议也不接收 cancellation。因而 stop/close 只能等待自然返回，无法取消 Provider 或工具轮次。

### F-21 集成验证命令可修改临时 worktree，普通集成路径不检测

- 状态：代码路径确认，未修复。
- 位置：`src/mycode/teams/integration.py:343-368`。

CoordinatorCommand 的 verification 执行前后会比较 Git status，但 `IntegrationService._verify` 直接执行配置命令，只按 returncode 判断，不比较前后状态。一个返回 0、同时生成或修改文件的验证命令可让集成继续，并使 cleanup 失败或把未验证副作用留在 worktree。

### F-22 Worktree 初始化失败时可能因 locked worktree 无法补偿清理

- 状态：动态复现，未修复。
- 位置：Team worktree provision/initialization 流程。

注入 `initialization_not_ignored` 后，初始失败随后产生 `worktree_cleanup_failed`。原因是 worktree 创建时被 lock，异常补偿直接 remove 而没有先 unlock；失败资源可能留在 Git 注册和磁盘中。

### F-23 `hooks` 初始化规则实际上是 no-op

- 状态：代码路径确认，未修复。
- 位置：`src/mycode/teams/worktrees.py:116-119, 156-157`。

TeamWorktreeManager 遇到 `action == "hooks"` 只校验 source 是目录后 `continue`，恢复验证也直接 `continue`。通用 WorkspaceInitializer 会通过 Git 配置处理 hooksPath；团队 worktree 没有等价行为。

### F-24 更新任务说明不执行创建时的 20,000 字符上限

- 状态：代码路径确认，未修复。
- 位置：`src/mycode/teams/tasks.py:69, 100-118`。

`create_task` 限制 description 长度为 20,000；`update` 对新 description 直接 replace，没有长度校验。可绕过配置/领域资源限制写入超长任务说明。

### F-25 成员上下文会重复保存同一批 inbox 内容

- 状态：组合路径确认，未修复。
- 位置：`src/mycode/teams/member.py:90-120`、`src/mycode/cli.py:500-517`、`src/mycode/teams/worker.py:65-74`。

TeamMemberRuntime 先把每条 inbox 作为原始 user Message 加入 context；实际 MemberAgent 又把全部 inbox 拼成一个新的 AgentRequest，AgentRunner 将该 user prompt 包含在 `new_messages` 中返回。Runtime 随后保存 `(*inbox, *result.messages)`，同一内容以“原始消息 + 聚合 prompt”重复进入持久上下文。

影响：上下文膨胀、模型重复看到信息，source_message_ids 只标在第一份记录上，恢复审计也变得含混。

### F-26 并发只读工具完成事件顺序测试约 10% 波动

- 状态：动态重复 30 次，3 次失败，未修复。
- 位置：`src/mycode/agent/executor.py:124-153`、`tests/test_agent_executor.py:207-234`。

测试预期较快的第二个调用先产生 completion event，再产生第一个；实际有时得到 `1, 2`。`as_completed()` 只保证“完成后可迭代”，当两个 future 在开始迭代前都已完成时，不保证二者的完成时间顺序。历史结果最终仍按原调用顺序回灌，但实时 UI/事件顺序不稳定。

## 6. P3 与质量/环境信号

### Q-01 Mypy 基线有 141 个错误

无项目专用 mypy 配置、使用 `--ignore-missing-imports` 扫描 `src/mycode`：

| 错误族 | 数量 |
|---|---:|
| `arg-type` | 62 |
| `attr-defined` | 26 |
| `assignment` | 24 |
| `has-type` | 8 |
| `union-attr` | 8 |
| 其他 | 13 |

团队 storage/tasks/tools/runtime、会话 streaming 和 Agent runner 最密集。其中一些只是当前缺少严格类型配置，但 `teams/tools.py` 中同一局部变量承载 tuple、task、approval、delivery 等不同类型，确实降低了审查可靠性。

### Q-02 Ruff 基线有 360 项

主要包括 142 个未排序 import、52 个宽泛 `except Exception`、30 个未使用 unpack 变量、29 个 `try/except/pass`、27 个未使用 import。安全规则中的 YAML 报告是 `SafeLoader` 子类导致的误报，不应作为漏洞；`httpx timeout=None`、partial executable path 和 `shell=True` 则与本报告已复现风险一致。

### Q-03 `-W error` 暴露未关闭 SessionJournal

- 位置：`src/mycode/agent/runner.py:515-540`。

`AgentRunner.new_session()` 即使 runner 初始没有 journal，也会创建一个新的 `SessionJournal`。相关测试没有关闭 runner，后续测试触发 GC 时报告 unclosed file ResourceWarning。常规测试把它当 warning 隐藏；使用 `-W error` 后 suite 失败。

### Q-04 当前虚拟环境有一个额外包漏洞，但不属于项目声明依赖

`pip-audit --local` 报告：

```text
cryptography 49.0.0  PYSEC-2026-3552  fix: 50.0.0
```

`pip list --not-required` 显示它是当前 venv 的顶层额外包，`pyproject.toml` 没有声明它，`pip show` 也没有项目包依赖它。因此这是交付环境卫生风险，不计入上面的项目 P0-P2 数量，但若该 venv 用于发布/运行仍应在审核范围内。

### Q-05 虚拟环境的 `pip` 启动脚本 shebang 已失效

直接执行 `.venv/bin/pip` 报：

```text
bad interpreter: .../.venv312/bin/python3.12: no such file or directory
```

`.venv/bin/python -m pip` 仍可用。说明虚拟环境可能被移动/重命名过，直接脚本的可复现性不足。

## 7. 验收证据与实际测试的落差

`specs/team-collaboration/checklist.md` 已把 AC1-AC47 和最终交付项全部勾选，但以下勾选与本次反例直接冲突：

- AC7：归档在 revision conflict 时仍先删除 worktree。
- AC9/AC10：实际启动失败不回退、显式选择仍探测全部后端。
- AC21/AC24：独立成员进程无法可靠唤醒其他成员。
- AC28：角色 `permission_mode` 未进入权限实例。
- AC32/AC46：Lead fast-forward 执行 hook，完成后可能不干净。
- AC36/AC37/AC47：Coordinator 可通过 argv 和残留副作用工具写入。
- AC39：初始化目录内部 symlink 可读取工作区外内容。
- AC40：最大合法任务链递归失败，timeout 后副作用继续。
- AC41：业务转换跨多个独立事务，审计没有业务 actor/action。
- AC44/AC45/AC47：所谓“完整闭环”测试证据不足。

尤其是 `tests/test_team_collaboration_integration.py` 只有 25 行、1 个测试。它只创建一个任务、提交/批准计划、发送一条邮箱消息并断言消息可见；没有真正启动两个 coroutine 成员、没有依赖 DAG 执行、没有成员自然 idle/resume、没有 Git 提交与原子集成，也没有 Coordinator 双锁/冲突委派。因此它不能支撑 AC44 或 AC47 的“完整闭环”声明。

真实 tmux 测试验证了 pane/PID/SIGUSR1 原语，但使用 `fake-mycode`，没有验证默认 worker 可执行入口、ticket 消费后的实际 TeamRuntime、custom config、CLI 重启恢复或成员继续执行，不能单独支撑 AC45。

## 8. 目前通过且未发现问题的部分

为避免报告只呈现失败，以下项目在本轮验证中表现正常：

- Python 3.10 语法兼容性和当前 Python 3.12 导入均正常。
- 隔离 wheel 构建成功，package-data 基本装配可用。
- 当前声明依赖满足安装一致性，`pip check` 无破损。
- CLI entry point 的帮助输出正常。
- 测试收集完整，没有 collection error。
- 排除已确认脆弱用例后，常规 774 个测试全部通过。
- 当前提交没有 whitespace/diff-check 错误。
- 没有在项目文件中发现真实 API key 或私钥；命中项为检测实现和测试假 secret。
- mailbox 先持久化后报告唤醒 warning 的基本语义存在；问题集中在目标恢复/唤醒实现。
- 临时 integration worktree 中的 no-ff merge 已关闭 hook；遗漏发生在最终 Lead fast-forward。
- JSONL batch 写路径使用循环处理短写；遗漏集中在其他单写路径。

## 9. 审核顺序建议（不等于授权修复）

建议审核时按以下门禁顺序决定是否进入修复阶段：

1. 先确认 Coordinator 的安全模型：是严格只读/无副作用，还是允许受信第三方工具。当前实现与批准规格是前者，但实际是后者。
2. 再确认 shell 权限边界是否必须保证 workspace containment。若必须，F-03 是发布阻断项。
3. 确认团队业务转换是否要求 AC41 所述的真正跨文件原子/可恢复语义；当前实现只保证底层文件替换事务，不能保证业务事务。
4. 确认 Git 集成是否允许执行用户 hooks。当前 Plan 明确不允许，因此 F-05 应视为发布阻断项。
5. 明确 tmux worker 应从当前 Python 环境启动还是依赖全局安装，并明确 custom config 的传递方式。
6. 重新定义 AC44/45/47 的最小真实 E2E，避免再次用组件测试替代闭环验收。

## 10. 审计边界

- 本轮没有修改任何生产代码、测试或既有规格/checklist。
- 所有故障注入、外部文件、Git 仓库、tmux session、覆盖率和审计工具均使用临时目录；审计产生的仓库内 `.coverage`/`build` 已移出项目。
- 没有测试真实 Provider 凭据、付费 API、远程 MCP Server 或跨机器分布式场景；这些不应被本报告视为已验证。
- 依赖闭包的独立临时重解析因 `pip-audit` 创建隔离环境耗时超过审计等待窗口而被中止；已完成当前实际 venv 的公开漏洞扫描。
- 本报告只落盘问题和证据。任何修复、测试改写、checklist 回退或版本升级均等待人工审核后另行授权。
