# Sub-Agent Worktree Isolation Checklist

> 本清单依据已批准的 [spec.md](./spec.md)、[plan.md](./plan.md) 与 [task.md](./task.md) 生成。实现完成前所有条目保持未勾选；只有运行对应验证并检查实际证据后才能改为 `[x]`。

## 0. 验收环境与基线

- [x] 记录开发基线的提交、分支、工作树状态、Python 版本、Git 版本和完整测试结果。
  - 验证：运行 `git status --short`、`git log -1 --oneline --decorate`、`.venv/bin/python --version`、`git --version` 和 `PYTHONPATH=src .venv/bin/python -m pytest`，保存原始输出。
- [x] Worktree 所需 Git 能力在项目支持环境中可用，能力不足时功能失败关闭且共享 Agent 仍可运行。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_manager.py -k capability -v`，并核对能力探测不创建开发仓库 Worktree。
- [x] 测试只操作 pytest 临时 Git 仓库，不在当前开发仓库留下测试 Worktree、分支或后台线程。
  - 验证：在定向与完整测试前后分别运行 `git worktree list --porcelain` 和 `git branch --list 'mewcode/worktree/*'`，比较结果并检查测试资源清理断言。

## 1. 角色声明与配置

- [x] AC1：未声明 `isolation` 的定义式角色继续使用主工作区；`isolation: worktree` 使用独立工作区；非法值使角色定义失效；Fork 继续共享主工作区。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_definition_parser.py tests/test_worktree_executor.py tests/test_agent_delegation_integration.py -k isolation -v`，核对四种分流结果。
- [x] `isolation` 已进入不可变角色 fingerprint 和任务快照，角色热更新不会改变已排队或运行任务的隔离模式。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_definition_parser.py tests/test_worktree_executor.py -k 'fingerprint or snapshot or reload' -v`。
- [x] AC10：合法 `agents.worktree` 配置与安全默认规则可加载；绝对路径、遍历、反斜杠、未知字段、类型错误、冲突目标和专用根规则在写文件前被拒绝。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_config.py tests/test_worktree_initializer.py -k 'config or rule or invalid or conflict' -v`，核对错误包含规则位置但不含源内容。
- [x] 旧配置无需增加 Worktree 字段即可启动，五条默认初始化规则均为可选，固定根不暴露为配置项。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_config.py -k 'default or legacy or worktree' -v`，并人工核对解析后的配置对象。

## 2. 路径、创建与身份恢复

- [x] AC2：两个隔离任务得到不同绝对目录和临时分支；目录都在仓库内 `.mycode/worktrees/`，共享 Git 对象且专用根被忽略。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_manager.py tests/test_worktree_isolation_integration.py -k 'distinct or shared_objects or ignored' -v`，再运行 `git check-ignore .mycode/worktrees/probe`。
- [x] AC3：安全单段/多段名称可解析；空段、`.`、`..`、绝对路径、反斜杠、非法字符、超长段/总长、规范化逃逸和 symlink 逃逸全部被拒绝。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_paths.py -v`，确认攻击矩阵逐项有断言。
- [x] 路径和分支只由系统任务 ID 推导，Agent schema、LLM prompt 和子 Agent 工具中不存在自定义 Worktree 路径、分支或强制删除参数。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_control_tools.py tests/test_worktree_paths.py -k 'schema or managed or task_id or force' -v`，并检查工具 schema 快照。
- [x] AC4：主工作区存在已跟踪与未跟踪修改时，隔离目录仍严格来自调用时 `HEAD`；身份记录的 base commit 准确，排队期间 HEAD 前进不改变基线。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_manager.py tests/test_worktree_isolation_integration.py -k 'baseline or uncommitted or queued' -v`。
- [x] AC5：目录、分支或任务身份冲突均不会被覆盖；创建各阶段失败时子 Agent 不启动，本次明确创建的资源被回滚或保持为不可恢复的不完整状态。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_manager.py tests/test_worktree_executor.py -k 'conflict or rollback or creating or partial' -v`。
- [x] AC6：合法已有目录可仅通过只读文件系统核验恢复；禁用所有 Git 调用时仍成功。任一身份字段、记录、`.git` 指针或 manifest 不匹配都拒绝且目录字节不变。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_identity.py tests/test_worktree_manager.py -k 'recover or filesystem or no_git or mismatch' -v`，使用 Git spy 和目录快照证明零调用、零写入。
- [x] 双身份记录采用严格 schema、权限 `0600` 和原子替换；未知版本、未知字段、`creating` 状态和部分写入不会被当作 active/retained 身份。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_identity.py -k 'schema or permission or atomic or creating or corrupt' -v`。

## 3. 环境初始化

- [x] AC11：配置声明的本地文件/目录可复制到相同相对目标；可选源缺失只产生脱敏诊断，必需源缺失阻止启动，越界 symlink 和内容不会泄入诊断。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_initializer.py -k 'copy or required or optional or diagnostic or secret' -v`。
- [x] 目录复制不跟随 symlink，并受文件数和总字节硬上限约束；达到上限时规则失败且不留下被误认为完整的目标。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_initializer.py -k 'copy_limit or directory or symlink_escape or rollback' -v`。
- [x] AC12：大型依赖目录通过指向已验证主工作区源的 symlink 复用而不复制；目标冲突、源越界、循环链接和源类型错误不覆盖目标并失败关闭。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_initializer.py -k symlink -v`，检查 inode/链接目标和冲突目录快照。
- [x] AC13：Worktree Git 子进程通过运行时环境使用独立 `core.hooksPath`，主工作区及另一 Worktree 的 Git 配置和 hooks 行为保持不变；required/optional 语义正确。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_initializer.py tests/test_hooks_actions.py tests/test_agent_hook_scopes.py -k 'hooks_path or worktree or required' -v`，比较三个工作区的 hook 观测结果与配置文件。
- [x] AC14：被 Git 忽略但运行需要的文件和目录按规则补齐并保持 ignored；复制、链接、缺失源和冲突使用同一安全约束。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_initializer.py -k 'ignored or supplemental' -v`，对目标执行临时仓库内的 `git check-ignore`。
- [x] AC15：对恢复 Worktree 重复初始化不会重写正确文件、改变正确链接或重复 hooks 配置；不一致目标明确失败，子 Agent 不在半初始化环境运行。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_initializer.py tests/test_worktree_executor.py -k 'idempotent or existing or mismatch or half_initialized' -v`，比较重复调用前后的 stat/内容快照。
- [x] 初始化记录和诊断不保存配置文件内容、环境变量值、凭据或可用于猜测秘密的内容摘要。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_identity.py tests/test_worktree_initializer.py -k 'secret or redacted or manifest' -v`，向 fixture 注入唯一 secret 并确认记录、异常和日志均无该值。

## 4. 显式工作目录与上下文隔离

- [x] AC7：隔离任务进入、执行、Hook 和退出前后的进程 cwd 完全不变；系统提示包含绝对 Worktree 路径、主工作区边界和禁止跨目录说明。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_executor.py tests/test_child_agent_runner.py -k 'cwd or isolation_instruction' -v`，用 cwd 哨兵覆盖成功、失败和取消。
- [x] AC8：读、写、编辑、搜索、命令和 Git 查询的相对路径均解析到任务 Worktree，主工作区同名文件不被读取或修改，工具没有隐式 cwd 回退。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tools_files.py tests/test_tools_search.py tests/test_tools_command.py tests/test_tools_git.py tests/test_worktree_executor.py -k worktree -v`。
- [x] AC9：相同相对路径在两个 Worktree 中保存不同内容、指令和项目记忆时，各任务只观察自身数据；缓存按规范化绝对路径隔离且不依赖全局清空。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_executor.py tests/test_tools_files.py -k 'cache or instruction or memory or prompt or concurrent' -v`。
- [x] 隔离定义式任务不继承主 Agent 用户记忆、会话历史或激活 Skill；Worktree 项目记忆缺失时保持为空；共享/Fork 原行为不变。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_executor.py tests/test_child_agent_runner.py tests/test_agent_delegation_integration.py -k 'memory or history or skill or shared or fork' -v`。
- [x] 主 Agent 文件与搜索工具排除 `.mycode/worktrees/`；直接、规范化或 symlink 访问专用根被拒绝。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tools_files.py tests/test_tools_search.py tests/test_permissions_sandbox.py tests/test_permissions_service.py -k 'excluded or worktree or symlink' -v`。
- [x] 已知会递归破坏 Worktree 根祖先的删除、`find -delete` 和危险 Git clean 组合被不可覆盖地拒绝，普通共享目录命令保持兼容。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_sandbox.py tests/test_permissions_service.py tests/test_tools_command.py -k 'recursive or find_delete or git_clean or worktree' -v`。
- [x] Worktree Hook payload 和 Hook command 都绑定任务绝对 cwd 与环境 overlay；主 scope、两个隔离 scope 的事件/命令不串目录，既有共享 `once` 语义不变。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_actions.py tests/test_hooks_runtime.py tests/test_agent_hook_scopes.py -k 'workspace or cwd or environment or once' -v`。

## 5. 任务退出、变更保护与查询

- [x] AC16：正常完成、执行失败和运行中取消都会进入 `finally` 退出检查；检查失败时保留目录；受管 ignored 初始化产物不计为业务变化。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_executor.py tests/test_worktree_manager.py -k 'completed or failed or cancelled or status_unknown or managed_ignored' -v`。
- [x] AC17：工作树无已跟踪修改、无未忽略未跟踪文件且无新增 commit 时，任务结束自动删除 Git Worktree、目录和临时分支，结果为 `cleaned`。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_manager.py tests/test_worktree_executor.py -k 'clean_exit or cleaned or no_changes' -v`，同时检查 Git 注册、路径和 ref 均消失。
- [x] AC18：存在已跟踪修改或未忽略未跟踪文件时任务结束保留 Worktree，结果为 `retained_changes`，并包含路径、分支、基线和脱敏原因。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_manager.py tests/test_worktree_executor.py -k 'retained_changes or tracked or untracked' -v`，检查文件内容保持不变。
- [x] 任务结束时工作树虽干净但存在任何新增 commit，均先返回 `retained_commits`，不因其已合并或已送达而当场删除。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_manager.py tests/test_worktree_executor.py -k 'task_exit and commit' -v`，分别覆盖未送达、已合并和已有 remote-tracking ref。
- [x] AC19：后续保护性重检中，未合并且未出现在可靠同名 remote-tracking/upstream ref 的新增 commit 阻止删除；已合并或已送达后允许删除，全程无网络调用。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_manager.py -k 'protected_commit or delivered or merged or no_network' -v`，用 Git 调用 spy 断言无 fetch/push。
- [x] AC20：路径越界、同名陌生目录、身份记录不匹配、Git 注册不匹配或状态不确定均使内部删除拒绝；LLM/子 Agent 可见入口中无 force bypass。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_manager.py tests/test_agent_control_tools.py -k 'delete or mismatch or unknown or force' -v`。
- [x] 安全删除不用 `--force`，临时分支用 expected-old 删除；Worktree 删除后若分支 tip 已并发变化则保留分支并报告 `cleanup_failed`。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_manager.py -k 'expected_old or concurrent_ref or partial_delete' -v`，核对 Git 参数记录。
- [x] AC21：任务查询区分 preparing、active、cleaned、retained_changes、retained_commits 和 cleanup_failed，并展示必要身份与最后活动时间；共享任务没有伪造摘要。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_task_manager.py tests/test_agent_control_tools.py tests/test_command_builtins.py -k worktree -v`。
- [x] running 任务取消先进入 `cancelling`，退出检查和结果回写完成后才进入 `cancelled` 并通知；queued 取消不创建 Worktree。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_task_manager.py tests/test_worktree_executor.py -k 'cancelling or queued_cancel or notification' -v`，断言事件顺序。

## 6. 后台清理与进程遗留

- [x] AC22：应用启动扫描一次，运行期间按配置周期扫描，仅选择超过阈值的候选；单次扫描失败不阻止启动、当前任务或下一轮扫描。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_janitor.py tests/test_cli.py -k 'startup or periodic or stale or scan_failure' -v`。
- [x] AC23：路径层拒绝专用根本身、根外路径、非法名称、规范化逃逸和 symlink 逃逸，不对这些目标执行删除命令。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_janitor.py -k path_filter -v`，用删除 spy 断言零调用。
- [x] AC24：身份层拒绝记录缺失/损坏、目录标记不匹配、仓库/分支不匹配和 Git 注册不匹配；陌生目录保持原样。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_janitor.py -k identity_filter -v`，比较扫描前后目录快照。
- [x] AC25：状态层拒绝未过期、活动锁占用、已跟踪变化、未忽略未跟踪文件、未合并且未送达 commit 和 Git 状态未知目标。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_janitor.py -k state_filter -v`。
- [x] AC26：只有路径、身份、状态三层全部通过才删除；任一失败只产生脱敏 skip/failure，不 repair、接管、prune 或部分删除陌生目标。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_janitor.py -k 'three_layers or no_repair or foreign' -v`，核对调用记录和诊断。
- [x] AC27：Janitor 与同一目标的创建、恢复、运行和退出共用目标锁，只能有一个操作持有；活动目录不会被清理，安全遗留项可在后续轮次删除。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_janitor.py tests/test_worktree_manager.py -k 'lock or concurrent or active or later_scan' -v`。
- [x] AC28：保留 Worktree 后系统不自动 merge、rebase、cherry-pick、sync、fetch、push 或建远端分支；上层处理后仅由内部保护性生命周期重检删除。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_manager.py tests/test_worktree_janitor.py -k 'no_network or retained or protected_delete' -v`，并审计 Git adapter 暴露的操作集合。
- [x] 候选只来自严格有效的主身份记录，`creating`、损坏记录和仅存在于目录树中的陌生 Worktree 不成为清理候选。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_janitor.py -k 'candidate or creating or corrupt or foreign' -v`。

## 7. 崩溃恢复、故障隔离与时间边界

- [x] AC29：身份写入、初始化、Git 状态检查和删除各阶段模拟进程中断后，重启不会把不完整状态视为可恢复或可删除，仍存在的用户文件不丢失。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_identity.py tests/test_worktree_initializer.py tests/test_worktree_manager.py tests/test_worktree_janitor.py -k 'interruption or crash or partial or restart' -v`。
- [x] AC30：单个隔离任务在创建、初始化、运行、退出或清理失败时，主 Agent、共享定义式/Fork 任务及其他隔离任务继续执行；错误不包含秘密。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_executor.py tests/test_agent_delegation_integration.py tests/test_worktree_janitor.py -k 'failure_isolation or redacted or concurrent' -v`。
- [x] AC33：Git 命令和后台扫描持续无响应时均在配置/系统边界内结束；应用可有界关闭，其他任务与后续扫描不被无限阻塞。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_manager.py tests/test_worktree_janitor.py tests/test_cli.py -k 'timeout or bounded or shutdown or hung' -v`，使用 fake clock/Event 而非长时间 sleep。
- [x] 生命周期操作使用“进程内锁 + OS advisory 锁”；异常退出后 OS 锁可释放，不同目标仍可并行。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_paths.py tests/test_worktree_janitor.py -k 'lock or process or distinct' -v`。
- [x] 所有 Git 与后台操作都有限时和并发边界；清理只读本地 ref，不要求网络、外部服务或新增依赖。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_manager.py tests/test_worktree_janitor.py tests/test_config.py -k 'timeout or no_network or dependency' -v`，并检查 `pyproject.toml` 依赖差异。

## 8. 架构与范围控制

- [x] `mycode.worktrees` 不导入 `mycode.agents`；Agent 适配仅位于 `mycode.agents.worktree_executor`，模块可独立导入且无循环依赖。
  - 验证：运行 `! rg -n '^from mycode\.agents|^import mycode\.agents' src/mycode/worktrees`，再运行 `PYTHONPATH=src .venv/bin/python -c "import mycode.worktrees; import mycode.agents.worktree_executor; import mycode.cli"`。
- [x] 创建、恢复、退出与 Janitor 复用相同路径/身份校验和目标锁；只有 Manager 执行 Worktree add/remove/unlock 与临时分支删除。
  - 验证：运行 `rg -n 'worktree (add|remove|unlock)|update-ref' src/mycode`，人工确认操作只封装在已批准 Git/Manager 边界且调用者复用 Manager。
- [x] 源码没有调用进程级 `chdir`，所有工具、Git 与 Hook 子进程入口显式传入 cwd。
  - 验证：运行 `! rg -n '\bos\.chdir\b|\.chdir\(' src/mycode`，并运行 cwd 相关定向测试。
- [x] Worktree 包不提供 fetch、pull、push、merge、rebase、cherry-pick、repair、prune 或强制删除接口。
  - 验证：运行 `rg -n '\b(fetch|pull|push|merge|rebase|cherry-pick|repair|prune)\b|--force' src/mycode/worktrees`，人工确认无可执行实现；允许文档化拒绝或测试常量时需记录理由。
- [x] 没有新增用户或 LLM 可见 Worktree 管理 CLI/工具；现有 `Task` 只读查询/取消与 `/tasks` 摘要是唯一用户界面变化。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_control_tools.py tests/test_command_builtins.py -k schema -v`，比较工具和命令注册表快照。
- [x] 普通定义式 Agent 与 Fork Agent 的共享路径、权限、Hooks、缓存、会话恢复和 CLI 行为保持兼容；实现不声称提供容器或 OS 级恶意代码隔离。
  - 验证：运行定向回归和完整测试，并人工核对 `README.md` 的隔离边界说明。
- [x] README、配置示例和 `.gitignore` 与实现一致，说明角色声明、默认初始化、HEAD 基线、保留规则、Janitor、无网络清理和不做事项。
  - 验证：运行 `rg -n 'isolation: worktree|agents.worktree|retained_changes|retained_commits|cleanup_failed|HEAD|Janitor|fetch|push|merge|Fork' README.md config.example.yaml .gitignore` 并人工核对。
- [x] 实现没有遗留 TODO、TBD、占位异常、调试器或跳过的 Worktree 测试。
  - 验证：运行 `rg -n 'TODO|TBD|FIXME|NotImplemented|breakpoint\(|pytest\.skip|@pytest\.mark\.skip' src/mycode/worktrees src/mycode/agents/worktree_executor.py tests/test_worktree_*.py`，人工确认输出为空或有明确非占位理由。

## 9. 编译、测试与回归

- [x] Worktree 新增单元测试全部通过。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_paths.py tests/test_worktree_identity.py tests/test_worktree_initializer.py tests/test_worktree_manager.py tests/test_worktree_janitor.py tests/test_worktree_executor.py -v`。
- [x] Agent、工具、权限、Hooks、命令与 CLI 定向回归全部通过。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_definition_parser.py tests/test_agent_control_tools.py tests/test_agent_task_manager.py tests/test_child_agent_runner.py tests/test_agent_delegation_integration.py tests/test_config.py tests/test_tools_files.py tests/test_tools_search.py tests/test_tools_command.py tests/test_tools_git.py tests/test_permissions_sandbox.py tests/test_permissions_service.py tests/test_hooks_actions.py tests/test_hooks_runtime.py tests/test_agent_hook_scopes.py tests/test_command_builtins.py tests/test_cli.py`。
- [x] AC32：现有定义式 Agent、Fork、权限、工具、Hooks、任务前后台、缓存、项目指令、记忆、会话恢复和 CLI 回归均通过，支持的 Python/Git 环境可运行全套测试。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest`，记录通过数、耗时、Python/Git 版本及任何 skip 原因。
- [x] 源码和测试可编译，无语法或导入错误。
  - 验证：运行 `PYTHONPYCACHEPREFIX=/tmp/mewcode-worktree-pycache PYTHONPATH=src .venv/bin/python -m compileall -q src tests`。
- [x] 项目未配置独立 lint 工具时，以编译检查、测试和 Git whitespace 检查作为静态门禁；没有行尾空白或冲突标记。
  - 验证：运行 `git diff --check` 和 `! rg -n '^(<<<<<<<|=======|>>>>>>>)' src tests README.md config.example.yaml`。
- [x] 完整测试连续运行两次均通过，未出现后台线程、锁、端口、执行顺序或临时目录导致的不稳定失败。
  - 验证：连续两次运行 `PYTHONPATH=src .venv/bin/python -m pytest` 并保存两份结果。

## 10. 端到端场景

- [x] AC31 / 场景一：主 Agent 与两个隔离定义式子 Agent 并发修改同一相对路径，三者只看到自身内容，目录、缓存、指令、记忆、提示和 Hook cwd 均无交叉。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_isolation_integration.py -k concurrent_isolation -v`。
- [x] AC31 / 场景二：一个任务无业务变更自动清理，一个有未提交变化保留，一个有新增未送达 commit 保留；结果状态、路径、分支和基线准确。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_isolation_integration.py -k exit_dispositions -v`。
- [x] AC31 / 场景三：上层模拟将保留 commit 合并到创建时主分支或更新可靠同名 remote-tracking ref，内部重检随后安全删除；系统本身不执行 merge/push/fetch。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_isolation_integration.py -k delivered_cleanup -v`，核对 Git 调用记录。
- [x] 场景四：进程遗留完整 Worktree → 应用重启启动扫描 → 活动/有改动/有受保护 commit 的候选保留 → 仅过期且三层安全的候选删除 → 周期扫描继续工作。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_isolation_integration.py tests/test_worktree_janitor.py -k restart_cleanup -v`。
- [x] 场景五：合法已有目录在 Git runner 被替换为“调用即失败”的 spy 时快速恢复并执行文件系统核验；任一身份篡改后拒绝且目录原样保留。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_isolation_integration.py tests/test_worktree_identity.py -k filesystem_recovery -v`。
- [x] 场景六：隔离任务在运行、初始化和退出阶段分别取消/失败，最终都完成数据保护再通知；主 Agent 和并行共享任务持续可用。
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_isolation_integration.py tests/test_worktree_executor.py -k failure_and_cancel -v`。

## 11. AC 覆盖矩阵

| Spec AC | Checklist 位置 | Spec AC | Checklist 位置 |
|---|---|---|---|
| AC1 | §1 | AC18 | §5 |
| AC2 | §2 | AC19 | §5 |
| AC3 | §2 | AC20 | §5 |
| AC4 | §2 | AC21 | §5 |
| AC5 | §2 | AC22 | §6 |
| AC6 | §2 | AC23 | §6 |
| AC7 | §4 | AC24 | §6 |
| AC8 | §4 | AC25 | §6 |
| AC9 | §4 | AC26 | §6 |
| AC10 | §1 | AC27 | §6 |
| AC11 | §3 | AC28 | §6 |
| AC12 | §3 | AC29 | §7 |
| AC13 | §3 | AC30 | §7 |
| AC14 | §3 | AC31 | §10 |
| AC15 | §3 | AC32 | §9 |
| AC16 | §5 | AC33 | §7 |
| AC17 | §5 |  |  |

## 12. 最终签收

- [x] AC1–AC33 均至少有一项可运行或可观察验证，覆盖矩阵编号连续且语义与 `spec.md` 一致。
  - 验证：逐项核对 §11 与 `spec.md`，确认每条 AC 的验证证据已记录。
- [x] T0–T15 全部按依赖完成，每个任务的定向验证先于其完成标记，提交边界可追踪。
  - 验证：逐项核对 `task.md`、开发进度、提交记录和本清单证据。
- [x] 所有未通过项都记录预期、实际结果、保留数据位置和修复方案；不存在以“应当通过”代替证据的条目。
  - 验证：检查本清单所有 checkbox 及验收报告，任何 `[ ]` 都必须出现在未通过清单中。
- [x] 工作区只包含本功能预期变更，没有覆盖或混入用户无关改动。
  - 验证：运行 `git status --short`、`git diff --check`、`git diff --stat` 和 `git diff`，人工审查全部差异。
- [x] 定向测试、两个连续完整测试、编译检查及六个端到端场景全部通过后，才可宣布功能完成。
  - 验证：保存 §9 与 §10 的最终命令输出，并在验收报告中汇总通过数、耗时和环境版本。

## 13. 验收报告（2026-08-13）

### 通过（75/75）

- [x] 开发基线：`76bd62b`（`main`），Python `3.12.10`，Git `2.39.5`；功能开发前完整套件 `656 passed`。
- [x] Worktree/Agent/工具/权限/Hook/命令/CLI 定向回归：`322 passed in 45.81s`。
- [x] 六类端到端筛选：`7 passed, 12 deselected in 12.60s`；覆盖 `concurrent_isolation`、`exit_dispositions`、`delivered_cleanup`、`restart_cleanup`、`filesystem_recovery`、`failure_and_cancel`。
- [x] 编译、导入、架构、范围、冲突标记和 whitespace 门禁：命令退出码 `0`，无诊断输出。
- [x] 最终完整回归第一轮：`737 passed in 57.62s`。
- [x] 最终完整回归第二轮：`737 passed in 58.35s`。
- [x] 资源复核：测试前后 `git worktree list --porcelain` 均只有当前主工作区，`git branch --list 'mewcode/worktree/*'` 均为空。

### 未通过

无。

### 环境说明

完整套件包含需要绑定本机回环端口的 MCP 集成测试，因此最终两轮在已批准的沙箱外测试权限下运行；两轮退出码均为 `0`，无 skip。
