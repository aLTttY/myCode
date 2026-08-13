# Sub-Agent Worktree Isolation Tasks

## 文件清单

### 新建

| 文件 | 职责 |
|---|---|
| `src/mycode/worktrees/__init__.py` | 导出 Worktree 公共模型和生命周期服务 |
| `src/mycode/worktrees/models.py` | 配置规则、请求、身份、Lease、检查、诊断和结果模型 |
| `src/mycode/worktrees/paths.py` | 受管名称、分支、记录位置和目录边界校验 |
| `src/mycode/worktrees/git.py` | 有界、参数化 Git 调用和机器格式解析 |
| `src/mycode/worktrees/identity.py` | 双身份记录、初始化指纹、原子写入和只读核验 |
| `src/mycode/worktrees/locking.py` | 进程内及跨进程目标锁 |
| `src/mycode/worktrees/initializer.py` | copy、symlink、hooks 初始化和恢复核验 |
| `src/mycode/worktrees/context.py` | Worktree 专属工具、指令、记忆、提示和 Hook 上下文 |
| `src/mycode/worktrees/manager.py` | 创建、恢复、激活、检查、退出和保护性删除 |
| `src/mycode/worktrees/janitor.py` | 启动扫描、周期扫描和有界关闭 |
| `src/mycode/agents/worktree_executor.py` | Worktree 生命周期与现有子 Agent 执行器适配 |
| `tests/worktree_testkit.py` | 临时 Git 仓库、引用、时钟和故障注入辅助 |
| `tests/test_worktree_paths.py` | 名称、嵌套路径、边界和符号链接攻击测试 |
| `tests/test_worktree_identity.py` | 双记录、原子写入、损坏状态和快速恢复测试 |
| `tests/test_worktree_initializer.py` | 初始化配置、幂等、冲突、上限和脱敏测试 |
| `tests/test_worktree_manager.py` | 创建、恢复、退出、变更保护和提交保护测试 |
| `tests/test_worktree_janitor.py` | 三层过滤、过期、互斥、重启遗留和超时测试 |
| `tests/test_worktree_executor.py` | 执行上下文、终态、取消和结果合并测试 |
| `tests/test_worktree_isolation_integration.py` | 主 Agent 与多个隔离子 Agent 的端到端测试 |

### 修改

| 文件 | 职责 |
|---|---|
| `.gitignore` | 忽略专用 Worktree 根和目录身份标记 |
| `src/mycode/types.py` | 增加 Worktree 配置和任务级工具环境、排除目录 |
| `src/mycode/config.py` | 严格解析 `agents.worktree` 配置 |
| `src/mycode/agents/models.py` | 增加角色隔离字段、请求和任务工作区摘要 |
| `src/mycode/agents/parser.py` | 解析和校验角色 `isolation` frontmatter |
| `src/mycode/agents/tools.py` | 固定调用时基线并准备受信任 Worktree 请求 |
| `src/mycode/agents/tasks.py` | 增加 `cancelling`、退出后终态和工作区状态回写 |
| `src/mycode/agents/runner.py` | 消费任务级绝对工作区上下文 |
| `src/mycode/agents/__init__.py` | 导出新增 Agent 集成类型 |
| `src/mycode/tools/base.py` | 统一应用显式 cwd、环境 overlay 和排除目录 |
| `src/mycode/tools/files.py` | 强制工作区边界并保持绝对路径缓存隔离 |
| `src/mycode/tools/search.py` | 搜索时跳过受管 Worktree 根 |
| `src/mycode/tools/command.py` | 命令使用显式 cwd 和任务环境 overlay |
| `src/mycode/tools/git.py` | Git 查询使用任务 cwd 与环境 |
| `src/mycode/permissions/sandbox.py` | 拒绝排除目录及针对祖先的已知递归破坏操作 |
| `src/mycode/permissions/targets.py` | 把排除目录纳入权限目标解析 |
| `src/mycode/permissions/service.py` | 执行不可覆盖的 Worktree 边界判定 |
| `src/mycode/hooks/events.py` | Hook payload 使用任务绝对工作区 |
| `src/mycode/hooks/actions.py` | Hook 命令使用任务 cwd 和环境 |
| `src/mycode/hooks/runtime.py` | 构造 Worktree 专属 Hook scope |
| `src/mycode/commands/models.py` | `/tasks` 模型增加 Worktree 摘要 |
| `src/mycode/commands/builtins.py` | 展示清理、保留和失败状态 |
| `src/mycode/cli.py` | 装配 Worktree 服务、Janitor 与关闭顺序 |
| `config.example.yaml` | 展示初始化、超时和后台清理配置 |
| `README.md` | 说明角色声明、边界、生命周期和保留规则 |

### 扩展现有测试

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

## 通用执行约束

- 所有实现以已批准的 `spec.md` 和 `plan.md` 为准；不得增加合并、变基、推送、跨目录同步、Fork 隔离或用户可见 Worktree 管理入口。
- 不调用 `os.chdir()` 或 `Path.chdir()`；每次工具、Git 和 Hook 子进程调用都显式传入绝对 `cwd`。
- 新建、恢复、退出、删除和 Janitor 必须复用同一套路径、身份与目标锁组件，不能添加宽松旁路。
- 任何状态不确定、Git 超时、身份不匹配或删除部分失败都以保留数据为默认结果。
- 测试中的 Git 仓库、远端引用和恶意目录全部建在 pytest 临时目录中，不操作开发仓库的真实 Worktree。
- 每个任务完成后先运行所列验证；失败时修复并重跑，通过后才进入依赖它的任务。

## T0：锁定开发基线与能力边界

**文件：** 无实现修改

**依赖：** 已批准的 `spec.md`、`plan.md`、`task.md` 和 `checklist.md`

**步骤：**

1. 记录当前提交、分支、工作树状态、Python 与 Git 版本。
2. 运行完整测试，区分本功能引入的失败和既有失败。
3. 确认 Git 支持 `worktree add --lock --no-track`、`worktree list --porcelain -z`、`worktree unlock` 和 `update-ref` 的所需能力。
4. 记录开发开始前已存在的用户修改；后续不得覆盖或回退无关改动。
5. 确认 `.venv` 与 pytest 可用；若不可用，记录可复现证据并在不改变需求的前提下恢复开发环境。

**验证：**

```bash
git status --short
git log -1 --oneline --decorate
git --version
.venv/bin/python --version
PYTHONPATH=src .venv/bin/python -m pytest
```

期望：获得可复现的基线结果，不修改业务代码或真实 Git Worktree。

**提交边界：** 无提交。

## T1：建立配置、角色隔离字段和核心模型

**文件：** `src/mycode/types.py`、`src/mycode/config.py`、`src/mycode/agents/models.py`、`src/mycode/agents/parser.py`、`src/mycode/agents/__init__.py`、`src/mycode/worktrees/__init__.py`、`src/mycode/worktrees/models.py`、`.gitignore`、`tests/test_config.py`、`tests/test_agent_definition_parser.py`

**依赖：** T0

**步骤：**

1. 定义不可变的 `WorktreeConfig`、`WorktreeInitRule`、请求、身份、Lease、初始化结果、检查、处置、诊断和任务摘要模型；状态值与 `plan.md` 一致。
2. 给定义式角色增加归一化后的 `isolation` 快照字段；缺失为 `shared`，显式值只接受 `worktree`，并把字段纳入角色 fingerprint。
3. 保持 Fork 调用模型和 `Agent` 工具 schema 不变，使 Fork 无法声明隔离。
4. 为 `AppConfig.agents.worktree` 增加安全默认值，严格校验未知字段、类型、有限正数、初始化动作、required 值和 action 对应的 target 约束。
5. 在配置加载期拒绝绝对路径、反斜杠、空段、`.`、`..`、重复或冲突目标及专用 Worktree 根路径；错误需定位到规则序号和字段，不包含源文件内容。
6. 写入五条默认可选初始化规则，并保证旧配置不声明 `agents.worktree` 时仍可加载。
7. 在 `.gitignore` 中加入 `.mycode/worktrees/` 与 `.mycode/worktree.json`，不改变其他忽略规则。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_config.py tests/test_agent_definition_parser.py
git check-ignore .mycode/worktrees/probe .mycode/worktree.json
```

期望：默认值、合法自定义值、所有非法边界和角色兼容性测试通过；两个受管路径均被忽略。

**建议提交：** `Define worktree isolation configuration and models`

## T2：实现安全路径和目标锁

**文件：** `src/mycode/worktrees/paths.py`、`src/mycode/worktrees/locking.py`、`tests/test_worktree_paths.py`

**依赖：** T1

**步骤：**

1. 实现受管名称校验：每段匹配 `[a-z0-9][a-z0-9_-]{0,63}`，总长不超过 200，允许 `/` 嵌套。
2. 明确拒绝空段、`.`、`..`、绝对路径、反斜杠、非法字符、超长段和超长名称。
3. 统一计算固定根 `.mycode/worktrees/`、`tasks/<task-id>` 目录、`.records/<task-id>.json`、目录标记和 `refs/heads/mewcode/worktree/<task-id>`。
4. 对现存父目录和符号链接执行规范化边界核验，拒绝根本身、根外路径、规范化逃逸和 symlink 逃逸。
5. 任务 ID 只由已有系统生成器提供；路径组件不接受 prompt、角色正文或工具参数中的字符串。
6. 以“仓库绝对路径 + 受管名称”为 key 实现进程内锁与 OS advisory 文件锁；锁文件放入固定 records/locks 区域。
7. 支持非阻塞尝试、有界等待、幂等释放和异常退出后 OS 自动释放；不同目标可并发，同一目标互斥。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_paths.py -v
```

期望：合法单段/多段名称、全部路径攻击、同目标竞争、不同目标并发和异常释放测试通过。

**建议提交：** `Validate and lock managed worktree paths`

## T3：实现有界 Git 适配层和测试仓库工具

**文件：** `src/mycode/worktrees/git.py`、`tests/worktree_testkit.py`、`tests/test_worktree_manager.py`

**依赖：** T1、T2

**步骤：**

1. 实现只接受参数数组、`shell=False`、显式绝对 cwd、非交互环境、禁用 pager 和统一超时的 `GitRunner`。
2. 只读调用叠加 `GIT_OPTIONAL_LOCKS=0`；错误只暴露命令阶段、返回码和脱敏摘要，不输出环境值或凭据。
3. 用原始 bytes 和 NUL 分隔解析 `status --porcelain=v1 -z` 与 `worktree list --porcelain -z`，拒绝缺失字段、重复字段和无法证明的注册状态。
4. 提供捕获仓库身份、当前 `HEAD`、当前本地分支、ref tip、新增 commit、祖先关系、可靠 upstream 和同名远端跟踪 ref 的只读方法。
5. 提供受限的 Worktree add/lock/unlock/remove 与 `update-ref -d <ref> <expected-old>` 方法；不提供 fetch、pull、push、merge、rebase 或 prune 接口。
6. 对 detached HEAD、缺失仓库、超时、非零返回、畸形 porcelain 和本地引用缺失实施失败关闭。
7. 建立临时 Git 仓库测试工具，支持创建提交、未跟踪文件、本地 bare remote、remote-tracking ref、Worktree 和可控 Git 失败；禁止指向开发仓库。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_manager.py -k 'git_runner or porcelain or repository or capability' -v
```

期望：机器格式解析、超时、能力探测、detached HEAD、引用关系和无网络约束测试通过。

**建议提交：** `Add bounded git worktree operations`

## T4：实现双身份记录和纯文件系统恢复核验

**文件：** `src/mycode/worktrees/identity.py`、`src/mycode/worktrees/models.py`、`tests/test_worktree_identity.py`

**依赖：** T2、T3

**步骤：**

1. 为主记录与目录标记实现版本化、未知字段失败的严格 JSON schema；所有时间、路径、ref、状态和 manifest 字段逐项验证。
2. 生成不包含秘密内容的初始化规则指纹；manifest 只保存动作、相对源/目标和必要性。
3. 使用同目录临时文件、权限 `0600`、flush、`fsync` 和原子替换写入两份记录；写入失败不得留下可被识别为完整的身份。
4. 实现主记录、目录标记和 Worktree 根 `.git` 指针的三方比较，核对仓库、任务、角色、受管名称、绝对路径、branch、base、expected gitdir、初始化指纹和生命周期状态。
5. 快速恢复入口只用文件系统读取，不调用 Git、不改写文件、不补记录、不 repair；`creating`、损坏、缺失、未知版本或任一不匹配都拒绝。
6. 恢复比较复制目标时不把文件内容或可逆秘密摘要写入记录或错误；只报告规则索引和安全原因码。
7. 覆盖原子写入各阶段中断、两份记录不一致、`.git` 指针伪造、路径替换和配置指纹变化。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_identity.py -v
```

期望：有效身份可读取；所有部分状态和伪造状态均失败关闭；测试可令 Git 完全不可调用而成功完成合法快速恢复核验。

**建议提交：** `Persist and verify worktree identities`

## T5：实现请求固定、创建、恢复和初始化前回滚

**文件：** `src/mycode/worktrees/manager.py`、`src/mycode/worktrees/models.py`、`src/mycode/agents/tools.py`、`tests/test_worktree_manager.py`、`tests/test_agent_control_tools.py`

**依赖：** T3、T4

**步骤：**

1. 在 `Agent` 工具收到定义式角色调用、生成系统任务 ID 后立即准备 `WorktreeRequest`，固定调用时的仓库身份、`HEAD`、本地分支、受管名称、目标目录和临时分支。
2. 先用文件系统判断目标：目录存在时只构造恢复请求且禁止 Git；目录不存在时才用只读 Git 捕获基线。
3. 对目标目录、主记录、临时分支或 Git Worktree 注册的部分冲突失败关闭，不覆盖、不接管、不自动修复。
4. `enter` 获取并在 Lease 生命周期持续持有目标锁；新建时执行 `git worktree add --no-track --lock -b`，再写入 `creating` 双身份。
5. 恢复时再次执行 T4 的纯文件系统三方核验，返回 `recovered=True` 的 Lease；不得在该路径调用任何 Git 或写操作。
6. 为 add 成功、身份写入失败等创建阶段注入故障；仅回滚本次创建且身份明确的资源，不删除预先存在的路径或 ref。
7. 初始化尚未激活时不得向 `ChildAgentExecutor` 暴露工作目录；创建失败只影响本任务。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_manager.py tests/test_agent_control_tools.py -k 'prepare or create or enter or recover or rollback or conflict or baseline' -v
```

期望：基线固定、主工作区未提交内容不进入 Worktree、纯文件系统恢复、冲突保护和故障回滚测试通过。

**建议提交：** `Create and recover managed worktrees safely`

## T6：实现幂等环境初始化与激活

**文件：** `src/mycode/worktrees/initializer.py`、`src/mycode/worktrees/manager.py`、`src/mycode/worktrees/identity.py`、`tests/test_worktree_initializer.py`、`tests/test_worktree_manager.py`

**依赖：** T5

**步骤：**

1. 按配置顺序执行 copy、symlink、hooks；每条规则先重新验证源、目标、相对路径、规范化边界和源类型。
2. copy 支持文件和有文件数、总字节硬上限的目录，不跟随目录内 symlink，不复制 Worktree 根；首次创建时验证目标保持 Git ignored。
3. symlink 只允许指向已验证的主工作区源；拒绝源越界、循环、类型不符、目标冲突和不匹配的既有链接，不进行大型目录复制。
4. hooks 验证主工作区 hooks 目录，并通过 Lease 的 Git 环境 overlay 注入 `core.hooksPath`；不得修改共享或 Worktree Git config。
5. 可选源缺失时跳过并追加脱敏 warning；必需源缺失或任一安全冲突时停止初始化，子 Agent 不启动。
6. 只回滚本次规则创建且能证明未被并发改动的目标；保留原有文件，失败诊断不含配置内容。
7. 首次成功后生成 manifest 和环境 overlay，通过 `activate` 原子把两份身份切换为 `active`。
8. 恢复 Lease 依据 manifest 做纯文件系统实时比较；正确目标不重写，不一致目标不覆盖，配置指纹变化拒绝恢复。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_initializer.py tests/test_worktree_manager.py -k 'initialize or activate or manifest or hooks or copy or symlink or ignored' -v
```

期望：安全默认规则、必需/可选源、复制上限、链接与 hooks 隔离、幂等恢复、冲突和秘密脱敏测试通过。

**建议提交：** `Initialize isolated worktree environments`

## T7：实现状态检查、任务退出与保护性删除

**文件：** `src/mycode/worktrees/git.py`、`src/mycode/worktrees/identity.py`、`src/mycode/worktrees/manager.py`、`tests/test_worktree_manager.py`

**依赖：** T5、T6

**步骤：**

1. `inspect` 在目标锁下重新执行路径、双身份和 Git 注册核验，再读取工作树状态和 `base_commit..branch_ref` 新提交。
2. 把已跟踪变化与未忽略未跟踪文件视为业务变化；Git ignored 的受管初始化产物不计入业务变化。
3. `exit` 只在无业务变化且没有任何新增 commit 时自动清理；有文件变化返回 `retained_changes`，有任何新增 commit 返回 `retained_commits`，即使 commit 已合并或已送达也先保留。
4. 后续 `delete` 要求工作树干净，并逐个确认新增 commit 已成为创建时 `base_ref` 当前 tip 的祖先，或已成为可靠 upstream/同名远端跟踪 ref 的祖先。
5. 缺少可靠远端跟踪 ref、任一未合并且未送达 commit、Git 超时或状态不确定时拒绝删除；检查不得触发网络访问。
6. 安全删除前再次核验身份，执行 unlock、无 `--force` 的 worktree remove、带 expected-old 的分支删除和主记录删除。
7. 若 Worktree 已移除但分支 tip 并发变化，保留分支并返回 `cleanup_failed`；不得强删或隐瞒部分失败。
8. 更新 `last_active_at`、lifecycle state、检查结果和脱敏原因；所有正常保护结果使用 `WorktreeDisposition` 返回。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_manager.py -k 'inspect or exit or delete or retained or commit or delivery or cleanup or timeout' -v
```

期望：无变更自动清理、文件变化保留、任务结束时任意 commit 保留、后续合并/送达后可删、未送达与不确定状态保护全部通过。

**建议提交：** `Protect worktree changes during cleanup`

## T8：让工具显式绑定 cwd、环境和排除目录

**文件：** `src/mycode/types.py`、`src/mycode/tools/base.py`、`src/mycode/tools/files.py`、`src/mycode/tools/search.py`、`src/mycode/tools/command.py`、`src/mycode/tools/git.py`、`tests/test_tools_files.py`、`tests/test_tools_search.py`、`tests/test_tools_command.py`、`tests/test_tools_git.py`

**依赖：** T1、T2

**步骤：**

1. 给 `ToolContext` 增加不可变 `process_environment` overlay 和 `excluded_roots`；共享任务未提供时保持兼容。
2. 统一把相对文件路径解析到 `workspace_root`，规范化后再次检查边界与排除目录；拒绝 symlink 逃逸和显式进入排除根。
3. 主 Agent 的专用文件与搜索工具跳过 `.mycode/worktrees/`；子 Agent 只以自己的 Worktree 为根，不隐式回退主目录。
4. 文件缓存继续使用规范化绝对文件路径和文件指纹，两个 Worktree 的同名相对路径不能交叉命中；不以清空全局缓存实现隔离。
5. `RunCommandTool` 始终显式传入当前任务 cwd，并把 overlay 叠加到执行时进程环境；不保存完整环境快照。
6. `ReadGitChangesTool` 使用相同 cwd/overlay，再叠加只读 Git 环境；输出只反映当前 Worktree。
7. 添加哨兵测试，在工具执行前后检查 `Path.cwd()` 不变，并并发验证两个不同 cwd 的文件、搜索、命令和 Git 结果互不干扰。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_tools_files.py tests/test_tools_search.py tests/test_tools_command.py tests/test_tools_git.py
```

期望：显式 cwd、环境 overlay、绝对缓存 key、主目录排除和跨 Worktree 并发隔离测试通过，既有共享工具行为不回退。

**建议提交：** `Bind tools to explicit workspace contexts`

## T9：加固权限目标和破坏性命令边界

**文件：** `src/mycode/permissions/sandbox.py`、`src/mycode/permissions/targets.py`、`src/mycode/permissions/service.py`、`tests/test_permissions_sandbox.py`、`tests/test_permissions_service.py`

**依赖：** T2、T8

**步骤：**

1. 把 `excluded_roots` 传入权限目标提取与判定，路径解析后命中受管 Worktree 根时执行不可覆盖的拒绝。
2. 对主 Agent 命令中的绝对、相对、规范化和 symlink 形式的 Worktree 根访问应用相同边界。
3. 识别针对 Worktree 根祖先的已知递归破坏模式，包括递归删除、`find -delete` 和会清除 ignored Worktree 的破坏性 Git clean 组合。
4. 保持子 Agent 的权限根为自身 Worktree；既有角色权限、全局黑名单和 Hook 顺序不变。
5. 明确测试普通 shell 不被宣传为 OS 级沙箱；只验收已定义的路径隔离与已知误操作保护。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_sandbox.py tests/test_permissions_service.py tests/test_tools_command.py -k 'worktree or excluded or recursive or symlink or clean'
```

期望：所有直接/间接 Worktree 根访问和已知祖先破坏命令被拒绝，普通共享目录命令保持兼容。

**建议提交：** `Protect managed worktrees from parent commands`

## T10：构造 Worktree 专属指令、记忆、提示和缓存上下文

**文件：** `src/mycode/worktrees/context.py`、`src/mycode/agents/runner.py`、`src/mycode/tools/files.py`、`tests/test_worktree_executor.py`、`tests/test_child_agent_runner.py`

**依赖：** T6、T8

**步骤：**

1. `WorkspaceContextFactory` 以规范化绝对 Worktree 根构造 `ChildWorkspaceContext`，包含工具上下文、环境 overlay、独立文件缓存和隔离说明。
2. 从 Worktree 重新加载项目指令并构建系统提示；缓存 key 包含绝对 workspace、资源种类和绝对 source。
3. 只读取 Worktree 内 `.mycode/memory/index.md` 作为项目记忆；不存在时为空，不继承主工作区项目记忆、用户记忆、会话历史或已激活 Skill。
4. 隔离说明写明绝对 cwd、主工作区边界、每次调用使用显式 cwd 和禁止跨目录操作。
5. 调整 `ChildAgentExecutor.run` 消费任务上下文；共享定义式与 Fork 任务继续使用既有主工作区上下文。
6. 以两个含相同相对文件、不同指令和不同项目记忆的 Worktree 并发测试，证明提示、记忆和缓存不交叉且不调用 `chdir`。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_executor.py tests/test_child_agent_runner.py -k 'context or instruction or memory or prompt or cache or cwd or shared or fork' -v
```

期望：绝对路径上下文隔离成立，共享与 Fork 回归通过，执行前后进程 cwd 不变。

**建议提交：** `Build per-worktree agent contexts`

## T11：绑定 Worktree Hook scope

**文件：** `src/mycode/hooks/events.py`、`src/mycode/hooks/actions.py`、`src/mycode/hooks/runtime.py`、`tests/test_hooks_actions.py`、`tests/test_hooks_runtime.py`、`tests/test_agent_hook_scopes.py`

**依赖：** T8、T10

**步骤：**

1. 扩展 `HookRuntime.fork_scope`，接收任务绝对 workspace 和进程环境 overlay，创建 Worktree 专属 event factory 与 action executor。
2. Hook payload 的 workspace、路径字段和诊断均指向当前 Worktree，不回退主工作区。
3. Hook command 使用显式 Worktree cwd 及同一环境 overlay，使运行时 `core.hooksPath` 只影响该子任务派生的 Git 进程。
4. 保持规则快照和 `once` 消费状态共享，turn、prompt lease、cwd 与环境按 scope 隔离。
5. 并发运行主 scope 与两个 Worktree scope，验证 Hook 读取、命令、事件和 once 行为不串目录。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_actions.py tests/test_hooks_runtime.py tests/test_agent_hook_scopes.py
```

期望：Hook event 和 command 均绑定正确 Worktree，主工作区与另一 Worktree 的 hooks 行为不变，既有 once 语义通过。

**建议提交：** `Scope hooks to isolated worktrees`

## T12：接入子 Agent 执行、取消和任务结果

**文件：** `src/mycode/agents/worktree_executor.py`、`src/mycode/agents/runner.py`、`src/mycode/agents/tasks.py`、`src/mycode/agents/tools.py`、`src/mycode/agents/models.py`、`src/mycode/agents/__init__.py`、`tests/test_worktree_executor.py`、`tests/test_agent_task_manager.py`、`tests/test_agent_control_tools.py`、`tests/test_agent_delegation_integration.py`

**依赖：** T5、T6、T7、T10、T11

**步骤：**

1. 实现 `WorktreeTaskExecutor` 分流：共享/Fork 直接调用原执行器，只有快照为 `worktree` 的定义式角色进入隔离生命周期。
2. 按 `enter → initialize → activate → build context → child run → finally exit` 编排；任何运行异常、Provider 错误和取消都必须进入退出检查。
3. 初始化失败时不启动子 Agent，调用受保护的 abort 路径并保留无法安全回滚的数据。
4. 给任务状态机增加 `cancelling`；running 取消只设置 token 和 cancel request，等待 executor 完成退出检查后才写 `cancelled` 和通知。
5. queued 取消保持不创建 Worktree；正常完成、失败、取消都只在 Worktree disposition 合并进结果后成为终态。
6. `TaskOutcome`、`TaskSnapshot` 和 Inbox 增加可选 `WorktreeTaskSummary`；共享任务为 `None`。
7. 返回清理/保留状态、绝对路径、临时分支、基线、最后活动时间和脱敏原因；不得返回配置内容或环境值。
8. 验证角色热更新不改变已排队任务的隔离快照，单任务失败不影响其他 worker、主 Agent 或共享任务。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_executor.py tests/test_agent_task_manager.py tests/test_agent_control_tools.py tests/test_agent_delegation_integration.py
```

期望：共享/隔离分流、三种终态、初始化失败、running/queued 取消、通知顺序和故障隔离全部通过。

**建议提交：** `Run declarative agents in managed worktrees`

## T13：实现三层 Janitor 和应用生命周期装配

**文件：** `src/mycode/worktrees/janitor.py`、`src/mycode/worktrees/manager.py`、`src/mycode/cli.py`、`tests/test_worktree_janitor.py`、`tests/test_cli.py`

**依赖：** T7、T12

**步骤：**

1. Janitor 仅从 `.records` 中严格解析成功的主身份记录枚举候选；陌生目录、损坏记录和缺失记录目录不被接管。
2. 每个候选依次执行路径层、身份层和状态层；检查过期阈值、活动目标锁、工作树、提交保护和 Git 注册。
3. 只有三层全通过才调用 Manager 的同一保护性 delete；任一失败或不确定只记录脱敏 skipped/failed 诊断。
4. 应用启动时同步触发一次不阻塞启动结果的扫描，然后由单后台线程按配置周期扫描；单项或单轮失败不终止后续扫描。
5. 为每次 Git 检查、单轮并发和 `close(timeout)` 建立边界；禁止网络访问、全局 prune、repair 和强制删除。
6. 启动扫描可识别进程重启前的 `active`、`retained` 或 `cleanup_failed` 完整遗留项，但不把 `creating` 或不完整记录视为可删候选。
7. 与任务运行复用目标锁；锁被占用时跳过，不能清理活动目录。
8. CLI 关闭先停止 Janitor 新扫描，再取消并有界等待任务，最后关闭 Hook、记忆、MCP 和 Provider；超时活动 Worktree 保留。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_janitor.py tests/test_cli.py -k 'janitor or worktree or shutdown or startup or timeout' -v
```

期望：启动/周期扫描、三层拒绝矩阵、活动互斥、重启遗留、扫描容错和有界关闭测试通过。

**建议提交：** `Clean stale worktrees with three safety filters`

## T14：展示状态并补齐用户文档

**文件：** `src/mycode/commands/models.py`、`src/mycode/commands/builtins.py`、`config.example.yaml`、`README.md`、`tests/test_command_builtins.py`、`tests/test_config.py`

**依赖：** T12、T13

**步骤：**

1. 在现有 Task 查询与 `/tasks` 输出中展示 `preparing`、`active`、`cleaned`、`retained_changes`、`retained_commits` 和 `cleanup_failed`。
2. 对保留项显示绝对目录、分支、基线、最后活动时间和简短原因；不增加 create、enter、delete、force 或其他管理 action。
3. 保持输出预览有界并对诊断脱敏；共享任务不显示空 Worktree 字段。
4. 在示例配置中说明默认初始化规则、required 行为、Git/扫描超时、扫描周期和过期阈值。
5. README 说明 `isolation: worktree` 只适用于定义式角色、基线来自调用时 HEAD、主工作区未提交内容不复制、退出保留规则及上层自行 merge 的边界。
6. 明确本功能不提供 OS/container 沙箱，不自动 fetch/push/merge/rebase，也不支持 Fork Worktree。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_builtins.py tests/test_config.py
rg -n 'isolation: worktree|retained_changes|retained_commits|cleanup_failed|agents.worktree' README.md config.example.yaml
```

期望：所有状态可区分、敏感内容不出现、共享任务输出兼容，文档完整描述能力与非目标。

**建议提交：** `Document worktree isolation lifecycle`

## T15：完成端到端、故障注入和全量回归

**文件：** `tests/test_worktree_isolation_integration.py`、本文件清单中的全部新测试及现有回归测试

**依赖：** T1–T14

**步骤：**

1. 在临时 Git 仓库中并发运行主 Agent 与两个 Worktree 定义式子 Agent，使三者修改相同相对路径并断言互相不可见。
2. 覆盖一个无业务变化任务自动清理、一个有未提交修改任务保留、一个有新增未送达 commit 任务保留；随后模拟合并或更新本地远端跟踪 ref，再由内部生命周期安全删除。
3. 覆盖主工作区有已跟踪/未跟踪改动时，Worktree 仍严格来自调用时 HEAD；覆盖排队期间主分支前进但任务基线不变。
4. 覆盖正常、失败、取消、初始化失败、Git 超时、身份写入中断、删除部分失败、进程遗留和 Janitor 并发竞争。
5. 用 Git 调用 spy 证明快速恢复零 Git 调用，清理零网络调用；用 cwd 哨兵证明整个端到端过程不改变进程 cwd。
6. 覆盖相同相对文件的内容缓存、项目指令、项目记忆、系统提示和 Hook cwd 全部按绝对 Worktree 隔离。
7. 运行所有计划列出的定向回归，修复共享定义式 Agent、Fork、权限、工具、Hooks、缓存、任务、会话和 CLI 的兼容问题。
8. 运行编译检查和完整测试两次；第二次用于发现后台线程、锁、顺序和临时目录清理导致的不稳定失败。
9. 检查测试结束后没有遗留测试 Worktree、后台线程或真实仓库引用，且 `git diff --check` 通过。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_worktree_isolation_integration.py -v
PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_definition_parser.py tests/test_agent_control_tools.py tests/test_agent_task_manager.py tests/test_child_agent_runner.py tests/test_agent_delegation_integration.py tests/test_config.py tests/test_tools_files.py tests/test_tools_search.py tests/test_tools_command.py tests/test_tools_git.py tests/test_permissions_sandbox.py tests/test_permissions_service.py tests/test_hooks_actions.py tests/test_hooks_runtime.py tests/test_agent_hook_scopes.py tests/test_command_builtins.py tests/test_cli.py
PYTHONPATH=src .venv/bin/python -m compileall -q src tests
PYTHONPATH=src .venv/bin/python -m pytest
PYTHONPATH=src .venv/bin/python -m pytest
git diff --check
```

期望：端到端隔离、故障注入、定向回归、编译检查和两次完整测试全部通过，无泄漏资源。

**建议提交：** `Verify worktree isolation end to end`

## 执行顺序

```text
T0
└─ T1
   ├─ T2
   │  ├─ T3
   │  │  └─ T4
   │  │     └─ T5
   │  │        └─ T6
   │  │           └─ T7
   │  └─ T8
   │     └─ T9
   └──────── T10（依赖 T6、T8）
              └─ T11

T5 + T6 + T7 + T10 + T11
└─ T12
   ├─ T13
   └─ T14（同时依赖 T13）
      └─ T15（依赖全部任务）
```

可并行窗口：

- T3 与 T8 可在 T2 后并行。
- T9 可与 T4–T7 并行。
- T11 的基础 Hook 调整可与 T7 并行，但最终验证依赖 T10。
- T13 的 Janitor 单元实现可在 T7 后开始，CLI 装配须等待 T12。

## 覆盖关系

| 需求范围 | 实现任务 | 主要验证任务 |
|---|---|---|
| F1、AC1 | T1、T12 | T1、T12、T15 |
| F2–F6、AC2–AC6 | T2–T5 | T2–T5、T15 |
| F7–F9、AC7–AC9 | T8、T10、T11 | T8、T10、T11、T15 |
| F10–F15、AC10–AC15 | T1、T6 | T1、T6、T15 |
| F16–F22、AC16–AC21 | T7、T12、T14 | T7、T12、T14、T15 |
| F23–F27、AC22–AC28 | T7、T13 | T7、T13、T15 |
| N1–N4、AC29 | T2–T7、T13 | T2–T7、T13、T15 |
| N5–N6、AC30 | T8–T12、T14 | T8–T12、T14、T15 |
| N7–N10、AC33 | T3、T6–T9、T13 | T3、T6–T9、T13、T15 |
| N11–N12、AC31–AC32 | T0、T15 | T15 |

所有 F1–F27、N1–N12 和 AC1–AC33 均至少对应一个实现任务和一个可运行验证任务。
