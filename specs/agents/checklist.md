# Sub-Agent Delegation 验收清单

> 本清单依据 [spec.md](./spec.md)、[plan.md](./plan.md) 与 [task.md](./task.md) 生成。实现完成前所有条目保持未勾选；只有在对应验证命令通过并检查证据后才能改为 `[x]`。

## 验收结果（2026-08-13）

- 完整测试：`656 passed in 16.72s`（包含需绑定回环临时端口的 MCP HTTP 集成测试）。
- Agent 定向测试：`42 passed in 1.37s`；其中 Defined/Fork/Inbox 端到端测试为 4 项。
- Python 3.12.10 下 `compileall`、模块导入、内置角色包资源检查与 `git diff --check` 均通过。
- 静态审计未发现 TODO/TBD、跳过测试、调试器、硬编码模型档位、Worktree 或任务持久化实现。

## 0. 验收环境与基线

- [x] 使用项目虚拟环境运行测试，记录 Python 与依赖版本，确保结果可复现。
  - 验证：运行 `.venv/bin/python --version` 和 `.venv/bin/python -m pip freeze`，将环境信息附在验收记录中。
- [x] 实现前基线测试通过，新增功能没有建立在已知失败之上。
  - 验证：运行 `PYTHONPATH=src .venv/bin/pytest -q`，保存基线结果并与最终全量测试对比。
- [x] Agent 功能在默认配置下可启动，旧配置文件无需新增字段即可加载。
  - 验证：运行 `.venv/bin/pytest -q tests/test_config.py tests/test_cli.py`，确认缺省 Agent 配置采用规范中的默认值。

## 1. 统一控制工具与 Fork 请求保真

- [x] `Agent` 是唯一的子 Agent 创建工具，schema 通过 `type` 参数稳定分流 `defined` 与 `fork`，包含 `prompt`、可选 `role` 和可选 `background`，不因角色或模式变化而改变父 Agent 工具列表。（AC1）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_control_tools.py tests/test_agent_request_bridge.py`，断言多次注册及热更新前后的工具名称、顺序和 JSON schema 完全一致。
- [x] `Task` 工具始终与 `Agent` 一起稳定注册，支持 `list|get|wait|cancel`，字段为 `action`、可选 `task_id`、可选 `timeout_seconds`。（AC1、AC20）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_control_tools.py`。
- [x] Defined Agent 以空白消息历史和固定角色系统提示启动，不继承父消息、父技能、父 memory 或父 journal；其可见工具经过角色与运行时策略过滤。（AC2）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_runner.py tests/test_child_agent_runner.py tests/test_agent_request_bridge.py`。
- [x] Fork Agent 冻结父级实际 `ChatRequest` 快照，保留 system、父历史、当前 user、工具定义与顺序，排除正在生成的 assistant 内容及本次 `Agent` tool call，再追加子任务 user 消息。（AC3）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_request_bridge.py tests/test_agent_delegation_integration.py`，逐字段比较父请求快照与子请求首轮前缀。
- [x] Fork 首次请求不做压缩、offload、额外 Hook prompt 或其他前缀改写，只有子任务 user 消息追加在缓存前缀之后。（AC3）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_request_bridge.py tests/test_agent_runner.py tests/test_child_agent_runner.py`，核对序列化请求指纹及消息顺序。
- [x] Fork 首轮保持父工具名称、顺序与 schema 完全一致，包括 `Agent`/`Task`；嵌套调用由执行时硬拒绝，不通过删除工具破坏缓存前缀。（AC4、AC13）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_request_bridge.py tests/test_agent_policy.py`。

## 2. 角色格式、来源、覆盖与热加载

- [x] Markdown + YAML frontmatter 能解析角色名、用途说明、工具白名单、工具黑名单、模型、最大轮次、权限模式，正文完整保留为生命周期系统提示。（AC5）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_definition_parser.py`，覆盖完整字段、空列表、正文多段与合法最小定义。
- [x] 非法 YAML、缺少必填字段、未知模型别名、非法最大轮次、非法权限模式会产生可定位诊断，不会生成半有效角色。（AC5、AC8、AC26）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_definition_parser.py`。
- [x] 角色来源优先级严格为项目级 > 用户级 > 内置 > 插件，项目或用户同名角色完整覆盖低优先级定义。（AC6）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_catalog.py`。
- [x] 插件角色仅从配置注入的目录加载，不做插件自动发现；多个插件目录同名时第一个目录胜出并输出诊断。（AC6）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_catalog.py`。
- [x] 角色目录在启动时及每次主 Agent 请求前重载；修改、新增或删除角色后，下一次请求看到新目录。（AC7）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_catalog.py tests/test_agent_delegation_integration.py`。
- [x] 已创建的子 Agent 持有不可变角色快照，运行期间角色文件变化不会改变它的模型、提示、工具或权限策略。（AC7）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_catalog.py tests/test_agent_runner.py tests/test_child_agent_runner.py`。
- [x] `inherit|haiku|sonnet|opus` 模型别名按配置解析为供应商模型 ID；`inherit` 使用父模型，缺失显式别名映射会使角色失效并给出诊断。（AC8）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_definition_parser.py tests/test_provider_pool.py`。

## 3. 运行时隔离、共享基础设施与跑到底

- [x] 每个子 Agent 拥有独立消息列表、token 用量、权限会话、文件读取缓存、取消状态及 Hook scope，任务间无可观察状态串扰。（AC9）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_runner.py tests/test_child_agent_runner.py tests/test_agent_permissions.py tests/test_tools_files.py`。
- [x] 子 Agent 共享 LLM 客户端底层 HTTP 连接、Hook 引擎和文件系统实现，但不会共享可变会话状态。（AC9）
  - 验证：运行 `.venv/bin/pytest -q tests/test_provider_pool.py tests/test_agent_runner.py tests/test_child_agent_runner.py tests/test_agent_hook_scopes.py tests/test_hooks_runtime.py`，分别断言共享对象身份与独立 scope 身份。
- [x] 子 Agent 非交互连续运行：模型返回工具调用时继续执行，模型不再调用工具时完成，达到最大轮次时以明确状态终止。（AC10）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_runner.py tests/test_child_agent_runner.py`。
- [x] 子 Agent 不显示权限确认弹窗；被拒权限作为结构化 tool result 返回模型，并允许模型在剩余轮次内调整方案。（AC11）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_permissions.py tests/test_agent_runner.py tests/test_child_agent_runner.py`。
- [x] `inherit`、`default`、`strict` 三种权限模式语义符合规范，子 Agent 的临时授权独立于父 Agent 与其他子 Agent，且不存在 bypass。（AC11）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_permissions.py`。

## 4. 多层工具策略与防嵌套

- [x] 工具决策按全局硬禁止、模式约束、角色 allow/deny、Plan 只读约束、后台 allowlist、Hook 与独立权限的既定层次求交集，任一上层拒绝都不能被下层放宽。（AC12）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_policy.py tests/test_agent_permissions.py`。
- [x] Defined Agent 从暴露列表中移除 `Agent`、`Task` 和 `load_skill`；Fork 为缓存保留父工具 schema，但实际调用同样被硬拒绝。（AC13）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_policy.py tests/test_agent_runner.py tests/test_child_agent_runner.py`。
- [x] 通过别名、Hook 或角色白名单均无法绕过子 Agent 嵌套禁令。（AC13、AC26）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_policy.py`。
- [x] 后台默认仅允许四类只读工具；配置只能增加后台候选 allowlist，最终仍与全局限制、角色限制、Plan 模式及权限策略求交集。（AC14）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_policy.py tests/test_config.py`。
- [x] 后台任务尝试写文件、执行 shell 或使用未授权工具时收到结构化拒绝，且任务管理器不会因此崩溃。（AC14、AC26）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_delegation_integration.py`。

## 5. 任务管理器、前后台切换与容量控制

- [x] Defined Agent 默认创建受管理任务并前台等待最多 30 秒（可配置）；等待期间完成则内联返回，超时后同一任务继续后台执行。（AC15）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_control_tools.py tests/test_agent_task_manager.py`。
- [x] `background:true` 立即返回 task id；Fork 无论参数如何都强制后台并立即返回 task id。（AC15）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_control_tools.py`。
- [x] 交互 CLI 等待前台 Defined Agent 时，Ctrl+B 只停止等待并将交付方式切为后台，不取消任务、不重启任务、不丢失状态。（AC16）
  - 验证：运行 `.venv/bin/pytest -q tests/test_cli.py tests/test_agent_delegation_integration.py`。
- [x] 非交互 `ask` 模式不安装 Ctrl+B 监听，并按相同超时规则返回内联结果或 task id。（AC16）
  - 验证：运行 `.venv/bin/pytest -q tests/test_cli.py`。
- [x] 任务状态至少包含 queued、running、completed、failed、cancelled；结果、错误、用量、创建/开始/结束时间均可查询。（AC17）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_task_manager.py`。
- [x] 执行状态与交付状态正交：前台等待转后台不会篡改 queued/running 状态，后台完成也不会改变最终执行结果。（AC17）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_task_manager.py`。
- [x] 默认并发上限为 4、排队上限为 32、队列为 FIFO；配置可覆盖且受合理边界校验。（AC18）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_task_manager.py tests/test_config.py`。
- [x] 队列满时新任务立即明确失败，不挤掉旧任务；排队时间计入 Defined Agent 前台超时时间。（AC18）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_task_manager.py tests/test_agent_control_tools.py`。

## 6. 完成通知、Inbox、Task 工具与 `/tasks`

- [x] 后台任务完成、失败或取消时向终端发出一次状态通知，并将一条结果记录放入所属主会话 inbox；重复回调不会重复投递。（AC19）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_task_manager.py tests/test_agent_delegation_integration.py`。
- [x] Inbox 只在模型请求之间安全注入；若主模型正在流式生成，通知等待到下一次请求边界，不修改在途请求。（AC19）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_delegation_integration.py`。
- [x] Inbox 与下一条真实用户输入组合为带明确标签的普通 user 消息并写入主历史，但不会自动唤醒模型。（AC19）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_delegation_integration.py tests/test_session_loader.py`。
- [x] `Task list|get|wait|cancel` 对参数、未知 task id、超时、终态重复取消和跨会话访问给出稳定结构化结果。（AC20、AC22）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_control_tools.py tests/test_agent_task_manager.py`。
- [x] `Task wait` 不阻塞事件循环或其他任务进度，超时只结束本次等待，不取消目标任务。（AC20）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_task_manager.py`。
- [x] `/tasks` 是只读的人类可读摘要，展示当前主会话任务状态、角色/模式、用量和简短结果，不修改任务或 inbox。（AC21）
  - 验证：运行 `.venv/bin/pytest -q tests/test_command_builtins.py tests/test_cli.py`。
- [x] 子 Agent 结果在直接返回、`Task get/wait` 和 inbox 三种路径中使用一致的结果/错误/用量语义。（AC17、AC19、AC20）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_delegation_integration.py`。

## 7. 会话生命周期、取消与非持久化

- [x] 所有任务严格绑定创建它的主会话；其他会话无法查看、等待、取消或接收其结果。（AC22）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_task_manager.py tests/test_agent_delegation_integration.py`。
- [x] `/new` 取消旧主会话的 queued/running 任务，执行有界等待，清空未投递 inbox，再建立新会话。（AC23）
  - 验证：运行 `.venv/bin/pytest -q tests/test_cli.py tests/test_agent_delegation_integration.py`。
- [x] CLI 正常退出和中断退出均取消任务并有界等待，不遗留非 daemon 阻塞线程或未关闭流。（AC23）
  - 验证：运行 `.venv/bin/pytest -q tests/test_cli.py tests/test_agent_task_manager.py`。
- [x] 任务表和未注入 inbox 不跨进程恢复；重启后 `/tasks` 为空，旧 task id 不可查询。（AC24）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_delegation_integration.py`。
- [x] 已注入主历史的后台结果作为普通消息随现有 SessionJournal 恢复，不依赖新增任务持久化格式。（AC24）
  - 验证：运行 `.venv/bin/pytest -q tests/test_session_loader.py tests/test_agent_delegation_integration.py`。

## 8. 失败隔离、边界条件与安全退化

- [x] Fork 缺少可冻结父请求、角色不存在/失效、模型映射缺失、队列满等创建期错误会明确返回，且不留下幽灵任务。（AC25、AC26）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_control_tools.py tests/test_agent_delegation_integration.py`。
- [x] Provider 错误、工具异常、Hook 异常、解析异常和达到最大轮次只使对应任务失败，不使主 Agent 或其他任务失败。（AC26）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_runner.py tests/test_child_agent_runner.py tests/test_agent_delegation_integration.py`。
- [x] queued 与 running 任务均可取消；取消传播到流式 Provider 与当前工具执行边界，最终状态稳定为 cancelled。（AC22、AC26）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_task_manager.py tests/test_provider_pool.py`。
- [x] 任务完成、失败和取消的竞态只能提交一个终态、一次用量结算和一次通知。（AC17、AC19、AC26）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_task_manager.py`。
- [x] 文件读取缓存按子 Agent 隔离，缓存命中不跨 Agent 泄漏内容或权限判断。（AC9、AC26）
  - 验证：运行 `.venv/bin/pytest -q tests/test_tools_files.py tests/test_agent_runner.py tests/test_child_agent_runner.py`。

## 9. 架构接线与回归

- [x] `mycode.agents` 包边界符合 plan：角色目录、任务管理、上下文构造、工具策略、权限、runner、通知职责无循环依赖。（AC27）
  - 验证：运行 `PYTHONPATH=src .venv/bin/python -c "import mycode.agents; import mycode.agents.runner; import mycode.agent.runner; import mycode.cli"`。
- [x] `RunnerDependencies`、ProviderPool、HookEngine/HookScope 和 CLI 生命周期完成接线，旧主 Agent 单会话路径无需启用子 Agent 也能正常运行。（AC27）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_runner.py tests/test_child_agent_runner.py tests/test_provider_pool.py tests/test_agent_hook_scopes.py tests/test_hooks_runtime.py tests/test_cli.py`。
- [x] 全部源码可编译，无语法错误或导入时副作用。
  - 验证：运行 `PYTHONPYCACHEPREFIX=/tmp/mewcode-agent-pycache .venv/bin/python -m compileall -q src tests`。
- [x] 现有命令、工具、Hooks、Skills、Plan 模式、会话恢复与 provider 测试全部通过。（AC27）
  - 验证：运行 `PYTHONPATH=src .venv/bin/pytest -q`。
- [x] 默认不使用 Agent 功能时，主请求的工具顺序除固定新增的 `Agent`/`Task` 外保持确定性，不出现基于角色动态增删导致的 prompt-cache 抖动。（AC1、AC27）
  - 验证：运行 `.venv/bin/pytest -q tests/test_tools_registry.py tests/test_agent_control_tools.py`。
- [x] 新增配置字段有类型、默认值、范围校验和清晰错误消息，旧配置兼容。（AC18、AC27）
  - 验证：运行 `.venv/bin/pytest -q tests/test_config.py`。

## 10. 文档与范围控制

- [x] README 或配套文档说明角色文件格式、四级加载优先级、插件目录注入、模型别名映射、权限模式及完整示例。
  - 验证：运行 `rg -n "Agent|Task|permission_mode|haiku|sonnet|opus|plugin" README.md docs specs/agents` 并人工核对说明与实现一致。
- [x] 文档说明三种后台进入方式、Fork 强制后台、Ctrl+B 语义、`Task`/`/tasks` 用法、并发和队列配置、会话生命周期及非持久化限制。
  - 验证：运行 `rg -n "Ctrl.B|background|/tasks|queue|concurrency|persist|session" README.md docs specs/agents` 并人工核对。
- [x] 本阶段没有实现 Worktree 文件隔离、多 Agent 团队编排或后台任务跨会话/跨进程持久化。
  - 验证：审查 `git diff --stat` 和 `git diff -- src tests README.md docs`，确认无 worktree/team-orchestration/task-persistence 模块、迁移或存储格式。
- [x] 没有遗留 `TODO`、`TBD`、占位异常或跳过的 Agent 测试。
  - 验证：运行 `rg -n "TODO|TBD|NotImplemented|pytest\.skip|@pytest\.mark\.skip" src/mycode/agents tests/test_agent_*.py`，人工确认输出为空或与本功能无关。

## 11. 端到端用户场景

- [x] Defined Agent：主 Agent 调用指定角色，子 Agent 从干净上下文按角色运行；短任务在前台内联完成，超时任务返回 task id，之后通过通知、inbox、`Task` 和 `/tasks` 取得一致结果。（AC28）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_delegation_integration.py`。
- [x] Defined Agent 手动切后台：交互等待时发送 Ctrl+B，确认任务不中断、CLI 可继续交互、任务最终只通知一次且结果在下一请求边界注入。（AC16、AC19、AC28）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_delegation_integration.py tests/test_cli.py`。
- [x] Fork Agent：继承父实际请求和相同工具 schema，首轮前缀指纹一致并强制后台；运行时嵌套 Agent/Task 被拒绝，任务仍能完成并安全回送结果。（AC29）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_delegation_integration.py`。
- [x] 多任务：同时提交超过并发上限但不超过队列容量的 Defined/Fork 混合任务，确认最多 4 个并发、FIFO 启动、各任务上下文和用量隔离、结果归属正确。（AC9、AC18、AC28、AC29）
  - 验证：运行 `.venv/bin/pytest -q tests/test_agent_delegation_integration.py`。

## 12. 验收标准覆盖矩阵

| AC | 主要检查位置 | AC | 主要检查位置 |
|---|---|---|---|
| AC1 | §1、§9 | AC16 | §5、§11 |
| AC2 | §1 | AC17 | §5、§6、§8 |
| AC3 | §1 | AC18 | §5、§9、§11 |
| AC4 | §1 | AC19 | §6、§8、§11 |
| AC5 | §2 | AC20 | §1、§6 |
| AC6 | §2 | AC21 | §6 |
| AC7 | §2 | AC22 | §6、§7、§8 |
| AC8 | §2 | AC23 | §7 |
| AC9 | §3、§8、§11 | AC24 | §7 |
| AC10 | §3 | AC25 | §8 |
| AC11 | §3 | AC26 | §2、§4、§8 |
| AC12 | §4 | AC27 | §9 |
| AC13 | §1、§4 | AC28 | §11 |
| AC14 | §4 | AC29 | §11 |
| AC15 | §5 |  |  |

## 13. 最终签收

- [x] AC1–AC29 均至少由一个自动化测试或明确的人工检查覆盖，覆盖矩阵无遗漏。
  - 验证：逐项核对 §12 与 `spec.md` 的验收标准，确认编号连续且语义一致。
- [x] 所有计划任务 T0–T14 已完成，相关提交边界可追踪，未跳过依赖任务。
  - 验证：逐项核对 `task.md`、变更记录与本清单证据。
- [x] 工作区仅包含本功能预期变更，没有覆盖或混入用户的无关改动。
  - 验证：运行 `git status --short`、`git diff --check`、`git diff --stat` 和 `git diff`，人工审查全部差异。
- [x] 最终全量测试、编译检查及两个核心 E2E 场景均通过，才可宣布功能完成。
  - 验证：依次运行 §9 的编译与全量测试命令，以及 §11 的 Defined/Fork E2E 命令，保存最终输出。
