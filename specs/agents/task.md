# MewCode 子 Agent 委派 Tasks

## 文件清单

### 新建

| 文件 | 职责 |
|---|---|
| `src/mycode/agents/__init__.py` | 导出子 Agent 公共模型与运行入口 |
| `src/mycode/agents/models.py` | 角色、快照、调用、策略、任务、结果、收件箱和审计模型 |
| `src/mycode/agents/parser.py` | 严格解析角色 Markdown 与 YAML frontmatter |
| `src/mycode/agents/catalog.py` | 多来源扫描、覆盖、诊断与热更新指纹 |
| `src/mycode/agents/runtime.py` | 线程安全发布和查询角色快照 |
| `src/mycode/agents/policy.py` | 可见工具过滤和执行时多层工具策略 |
| `src/mycode/agents/permissions.py` | 派生任务独立权限服务并记录脱敏审计 |
| `src/mycode/agents/provider_pool.py` | 按模型复用 Provider 与共享 HTTP 连接池 |
| `src/mycode/agents/bridge.py` | 冻结、发布、复制和撤销父请求快照 |
| `src/mycode/agents/runner.py` | 构造并运行定义式及 Fork 式一次性子 Agent |
| `src/mycode/agents/tasks.py` | FIFO 调度、状态机、等待、取消、通知、收件箱和关闭 |
| `src/mycode/agents/tools.py` | 固定 `Agent`、`Task` 工具及结果序列化 |
| `src/mycode/agents/waiting.py` | Event 与 prompt-toolkit 前台等待器 |
| `src/mycode/agents/builtins/__init__.py` | 内置角色包资源入口 |
| `src/mycode/agents/builtins/explore.md` | 安全只读的内置代码探索角色 |
| `src/mycode/tools/file_cache.py` | 任务级 UTF-8 文件读取缓存与失效逻辑 |
| `tests/test_agent_definition_parser.py` | 角色字段、YAML、安全边界与模型档位测试 |
| `tests/test_agent_catalog.py` | 四来源、覆盖、插件顺序、诊断和热更新测试 |
| `tests/test_agent_policy.py` | 全局禁令、角色、Plan 与后台白名单测试 |
| `tests/test_agent_permissions.py` | 权限状态隔离、非交互拒绝和审计测试 |
| `tests/test_provider_pool.py` | 模型选择、连接复用、并发和幂等关闭测试 |
| `tests/test_agent_request_bridge.py` | 请求深复制、生命周期和稳定指纹测试 |
| `tests/test_child_agent_runner.py` | 两类子运行、上下文隔离、用量与清理测试 |
| `tests/test_agent_task_manager.py` | FIFO、状态竞争、通知、取消、收件箱与关闭测试 |
| `tests/test_agent_control_tools.py` | `Agent`/`Task` schema、参数、等待和 Session 边界测试 |
| `tests/test_agent_foreground_waiting.py` | 同步完成、超时和 `Ctrl+B` 测试 |
| `tests/test_agent_delegation_integration.py` | 定义式、Fork、收件箱和生命周期端到端测试 |

### 修改

| 文件 | 职责 |
|---|---|
| `src/mycode/types.py` | 增加 Agent 配置，并允许 `ToolContext` 持有任务级文件缓存 |
| `src/mycode/config.py` | 严格解析模型映射、白名单、超时、并发、队列和预览配置 |
| `src/mycode/providers/base.py` | 定义共享传输和关闭边界 |
| `src/mycode/providers/anthropic.py` | 使用注入的共享 HTTP client |
| `src/mycode/providers/openai.py` | 使用注入的共享 HTTP client |
| `src/mycode/providers/factory.py` | 支持指定模型及共享 client 构造 Provider |
| `src/mycode/agent/cancellation.py` | 改用线程 Event 提供并发安全取消 |
| `src/mycode/agent/events.py` | 增加子运行和策略失败所需停止原因 |
| `src/mycode/agent/executor.py` | 在 Hook 和权限前接入子工具策略，增加 `policy` 结果来源 |
| `src/mycode/agent/runner.py` | 发布父快照、注入收件箱并支持冻结请求模板和子 profile |
| `src/mycode/context/manager.py` | 支持 Fork 首轮只估算不改写及注入失败恢复所需接口 |
| `src/mycode/tools/executor.py` | 允许自行限时的控制工具在当前执行线程运行 |
| `src/mycode/tools/files.py` | 读取使用任务级缓存，写入和编辑后使缓存失效 |
| `src/mycode/tools/registry.py` | 安全冻结/复制有序 Registry |
| `src/mycode/tool_safety.py` | 注册 `Agent`、`Task` 系统控制工具和子运行全局禁令 |
| `src/mycode/permissions/service.py` | 支持独立派生、判定观察器和稳定非交互拒绝原因 |
| `src/mycode/hooks/models.py` | 增加 Agent scope 和 `policy` 结果来源 |
| `src/mycode/hooks/events.py` | 在事件 payload 中写入作用域，隔离并发 turn |
| `src/mycode/hooks/runtime.py` | 拆分共享规则/once/动作与独立 turn/prompt/lease 状态 |
| `src/mycode/skills/isolated.py` | 从 ProviderPool 获取模型 Provider，保持既有 Skill 语义 |
| `src/mycode/commands/models.py` | 增加任务摘要展示模型 |
| `src/mycode/commands/interfaces.py` | 增加任务摘要查询 UI 接口 |
| `src/mycode/commands/builtins.py` | 注册并格式化 `/tasks` |
| `src/mycode/commands/__init__.py` | 导出任务命令相关类型和格式化函数 |
| `src/mycode/cli.py` | 组装角色目录、ProviderPool、桥、任务管理器、控制工具、通知和生命周期 |
| `tests/test_config.py` | Agent 配置默认值、合法值与边界错误测试 |
| `tests/test_providers.py` | 共享 client 下 Provider payload 与流式行为回归 |
| `tests/test_agent_executor.py` | 策略顺序、Hook 来源和控制工具执行回归 |
| `tests/test_agent_runner.py` | 快照发布/撤销、收件箱注入和 Fork 首轮前缀测试 |
| `tests/test_tool_executor.py` | 自管理超时工具不被外层截断测试 |
| `tests/test_tools_files.py` | 文件缓存命中、stat 变化和写后失效测试 |
| `tests/test_permissions_service.py` | 派生实例不继承 session rules 测试 |
| `tests/test_hooks_events.py` | Agent scope payload 测试 |
| `tests/test_hooks_runtime.py` | 并发 scope、共享 once 和 prompt lease 隔离测试 |
| `tests/test_hooks_integration.py` | 主/子 Agent 并发 Hook 回归测试 |
| `tests/test_skill_isolated.py` | 池化 Provider 后独立 Skill 回归测试 |
| `tests/test_command_builtins.py` | `/tasks` 本地执行与脱敏输出测试 |
| `tests/test_cli.py` | 热更新、通知、`Ctrl+B`、`/new` 和退出清理测试 |
| `tests/test_context_manager.py` | Fork 首轮不改写和后台结果边界测试 |
| `tests/test_session_journal.py` | 收件箱组合消息持久化和恢复测试 |
| `config.example.yaml` | 增加 Agent 配置示例和安全默认值 |
| `README.md` | 说明角色格式、两种委派、后台管理、权限和阶段边界 |
| `pyproject.toml` | 打包内置 Agent Markdown 资源 |

## T0：锁定开发基线与保护边界

**文件：** 无代码修改

**依赖：** 已批准的 `specs/agents/spec.md`、`specs/agents/plan.md`、`specs/agents/task.md`、`specs/agents/checklist.md`

**步骤：**

1. 记录开始开发时的 `git status --short`、当前提交和完整测试结果。
2. 确认 Hooks 功能已经位于当前基线提交中；后续只做作用域化增量修改，不回退其既有行为。
3. 标记所有任务允许修改的文件，发现新的用户改动或重叠修改时先比较 diff，再决定如何合并。
4. 确认 `.venv`、Python 版本和测试依赖可用；若完整基线本身失败，先记录失败证据，不把既有失败归因于本功能。

**验证：**

```bash
git status --short
git log -1 --oneline --decorate
PYTHONPATH=src .venv/bin/python -m pytest
```

期望：获得可复现的干净基线或明确的既有失败清单，不修改业务代码。

**提交边界：** 无提交。

## T1：建立 Agent 配置与公共模型

**文件：** `src/mycode/types.py`、`src/mycode/config.py`、`src/mycode/agents/__init__.py`、`src/mycode/agents/models.py`、`tests/test_config.py`

**依赖：** T0

**步骤：**

1. 定义 `AgentDelegationConfig`、角色来源、模型档位、权限模式、调用类型、任务状态、投递状态、任务结果、收件箱和权限审计等不可变公共模型。
2. 把 Agent 配置作为 `AppConfig.agents` 的默认字段，保证旧配置文件无需新增字段即可加载。
3. 严格解析 `model_aliases`、`background_allowed_tools`、前台等待、Task 等待默认值与硬上限、关闭超时、并发、队列和收件箱预览长度。
4. 校验数值为有限值且落在已批准范围；拒绝布尔值伪装数字、重复工具、非法工具名、未知字段和错误容器类型。
5. 允许模型档位映射部分缺失；缺失映射由角色目录使相应角色失效，而不是阻止不使用该档位的应用启动。
6. 保持 Provider、MCP、Thinking 和 Context 既有配置语义与错误信息兼容。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_config.py
```

期望：默认值、全部合法边界、非法范围、重复值、未知字段和旧配置回归均通过。

**建议提交：** `Add sub-agent configuration and core models`

## T2：实现角色解析、四来源目录和热更新快照

**文件：** `src/mycode/agents/parser.py`、`src/mycode/agents/catalog.py`、`src/mycode/agents/runtime.py`、`src/mycode/agents/builtins/__init__.py`、`src/mycode/agents/builtins/explore.md`、`src/mycode/agents/__init__.py`、`pyproject.toml`、`tests/test_agent_definition_parser.py`、`tests/test_agent_catalog.py`

**依赖：** T1

**步骤：**

1. 实现拒绝重复 YAML key 的 frontmatter 解析，要求七个角色字段和非空正文，未知字段直接诊断。
2. 校验小写角色名、单行说明、精确工具名、白黑名单重复或相交、模型档位、1–64 最大轮次和三种权限模式。
3. 拒绝符号链接入口、无法读取或非 UTF-8 文件、全局禁止工具和当前快照中的未知工具；诊断只包含来源、字段和安全原因。
4. 扫描 `<workspace>/.mycode/agents/`、`~/.mycode/agents/`、包内资源及构造参数注入的有序插件目录。
5. 按“项目 > 用户 > 内置 > 插件”选取有效定义；同层重复使该层候选失效并回退，插件目录之间先注册者胜出并产生覆盖诊断。
6. 当角色引用未配置模型档位时只使该角色无效；`inherit` 始终有效。
7. 计算覆盖内容、来源和文件状态的稳定指纹；无变化刷新复用旧快照，有变化生成新不可变快照。
8. 实现 `AgentRoleRuntime` 的线程安全发布、查询和角色目录说明；运行中持有的旧定义对象不随 publish 改变。
9. 提供只读 `explore` 内置角色并配置包资源打包。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_definition_parser.py tests/test_agent_catalog.py
```

期望：字段校验、四来源优先级、插件顺序、回退、模型映射、诊断脱敏、热增删改和快照冻结全部通过。

**建议提交：** `Load and refresh declarative agent roles`

## T3：池化 Provider 并共享 HTTP 基础设施

**文件：** `src/mycode/agents/provider_pool.py`、`src/mycode/providers/base.py`、`src/mycode/providers/anthropic.py`、`src/mycode/providers/openai.py`、`src/mycode/providers/factory.py`、`src/mycode/skills/isolated.py`、`tests/test_provider_pool.py`、`tests/test_providers.py`、`tests/test_skill_isolated.py`

**依赖：** T1

**步骤：**

1. 让 OpenAI、Anthropic 和 DeepSeek Provider 接受注入的线程安全 HTTP client，同时保留直接构造时的兼容路径。
2. 保证 Provider 实例不保存请求级流状态；响应、SSE 解析和工具增量状态继续局限在单次调用。
3. 实现按具体模型 ID 缓存轻量 Provider 的 `ProviderPool`，同一协议、地址和凭据共享一个连接池。
4. 对并发 `get`、重复模型和不同模型加锁，确保不会重复创建底层 client，也不会串改 Provider 的模型配置。
5. 实现幂等 `close`；关闭后拒绝创建或取得新 Provider，并且只关闭一次共享 client。
6. 为现有独立 Skill 增加 Provider supplier/pool 接口，同时保留测试可注入 factory 和原有模型覆盖语义。
7. 回归三个 Provider 的 payload、cache usage 解析、错误脱敏和流式事件顺序。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_provider_pool.py tests/test_providers.py tests/test_skill_isolated.py
```

期望：同/不同模型并发复用、幂等关闭、既有 Provider 与独立 Skill 行为全部通过。

**建议提交：** `Share provider transports across agent runs`

## T4：建立并发安全取消与任务级文件读缓存

**文件：** `src/mycode/agent/cancellation.py`、`src/mycode/types.py`、`src/mycode/tools/file_cache.py`、`src/mycode/tools/files.py`、`src/mycode/tools/registry.py`、`tests/test_tools_files.py`、`tests/test_agent_task_manager.py`

**依赖：** T1

**步骤：**

1. 用 `threading.Event` 实现幂等、跨线程可见的 `CancellationToken`，保持现有 `cancel()` 和 `is_cancelled()` 接口。
2. 实现任务级 `FileReadCache`，以解析后路径及文件 stat 标识验证缓存有效性，只缓存成功的完整 UTF-8 内容。
3. 给 `ToolContext` 增加可选缓存；未提供时保持当前无缓存行为。
4. `read_file` 优先读取当前 Context 的缓存，展示截断和 complete 结果仍保持现有语义。
5. `write_file` 与 `edit_file` 成功后使当前任务对应路径缓存失效；外部修改通过 stat 不匹配自动失效。
6. 为 Registry 增加保持注册顺序的安全冻结/复制能力；冻结对象共享不可变工具实例，但不共享可变注册表。
7. 用并发取消测试证明任务线程能及时观察取消，且父 Agent 和不同子 Agent 的缓存对象互不命中。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_tools_files.py tests/test_agent_task_manager.py tests/test_tools_registry.py
```

期望：缓存命中、外部 stat 变化、写后失效、缓存隔离、取消可见性和 Registry 顺序均通过。

**建议提交：** `Isolate cancellation and file-read caches per agent`

## T5：把 Hook 运行时拆成共享引擎和独立作用域

**文件：** `src/mycode/hooks/models.py`、`src/mycode/hooks/events.py`、`src/mycode/hooks/runtime.py`、`tests/test_hooks_events.py`、`tests/test_hooks_runtime.py`、`tests/test_hooks_integration.py`

**依赖：** T0

**步骤：**

1. 定义主、定义式和 Fork 式 Agent scope，Hook payload 增加可选的种类、任务 ID 和角色字段。
2. 把规则快照、动作执行器、once claim/consume 和诊断出口保留为共享引擎状态。
3. 把 Session/turn 事件工厂、prompt 队列、active lease 和序列号移入 `HookScope`，主 Agent 使用默认 scope。
4. `fork_scope` 为每个子任务创建独立状态并复用所属主 Session ID；scope 关闭只清理自身数据。
5. 共享锁保证 once 规则在并发 scope 中至多消费一次，单个 scope 的 prompt reserve/refresh/commit/release 不影响其他 scope。
6. 为 Fork scope 支持首轮延迟 prompt lease：事件和非 prompt 动作正常执行，prompt 从第二次 Provider 请求起可见。
7. 加入 `policy` 工具结果来源，并保证策略、Hook、权限和工具结果都使用同一 `tool_after` 事件结构。
8. 保持现有主 Session 开始/结束、十类事件、fail-open、异步动作和幂等关闭测试通过。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_events.py tests/test_hooks_runtime.py tests/test_hooks_integration.py
```

期望：并发 scope 不串 turn/prompt，once 全局一致，Fork 首轮无 prompt 污染，既有 Hooks 回归通过。

**建议提交：** `Scope hooks for concurrent child agents`

## T6：实现子工具策略和独立权限派生

**文件：** `src/mycode/agents/policy.py`、`src/mycode/agents/permissions.py`、`src/mycode/permissions/service.py`、`src/mycode/tool_safety.py`、`src/mycode/agent/executor.py`、`src/mycode/agent/events.py`、`tests/test_agent_policy.py`、`tests/test_agent_permissions.py`、`tests/test_permissions_service.py`、`tests/test_agent_executor.py`

**依赖：** T2、T4、T5

**步骤：**

1. 固定 `Agent`、`Task`、`load_skill` 为子运行不可覆盖的全局禁止项；把 `Agent`、`Task` 注册为主 Agent 系统控制工具。
2. 实现定义式可见 Registry：全局禁令、角色白名单、角色黑名单、Plan 只读限制和后台白名单依次求交，黑名单优先。
3. 实现执行前 `authorize_call`；Fork 不过滤冻结工具定义，但调用同样经过全局、Plan 和后台策略。
4. 后台状态通过只读 supplier 动态查询，使 `Ctrl+B` 后尚未执行的调用立即收紧，已启动调用不回滚。
5. 在 BatchToolExecutor 中把存在性和策略检查放到 Hook、权限和工具执行之前；策略拒绝产生稳定 reason code 并触发来源为 `policy` 的 `tool_after`。
6. 为 `PermissionService` 增加安全判定观察器和独立派生入口，派生实例复用不可变配置层、动态工具前缀，但 session rules 为空。
7. 角色 `inherit` 使用主有效模式，`default`/`strict` 覆盖；所有子实例使用无交互拒绝处理器。
8. 未命中规则的 default 子调用返回“无交互审批不可用”的稳定原因，审计只记录时间、工具名、允许状态和原因码。
9. 验证白名单从不授予权限，后台配置也无法解禁全局禁止项，任务之间不泄漏临时授权。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_policy.py tests/test_agent_permissions.py tests/test_permissions_service.py tests/test_agent_executor.py
```

期望：多层顺序、定义式可见性、Fork 运行时拒绝、无审批、审计脱敏和权限隔离全部通过。

**建议提交：** `Enforce child-agent tools and permission isolation`

## T7：实现后台任务管理器、FIFO 和收件箱

**文件：** `src/mycode/agents/tasks.py`、`src/mycode/agents/models.py`、`src/mycode/agent/cancellation.py`、`tests/test_agent_task_manager.py`

**依赖：** T1、T4

**步骤：**

1. 实现不可猜测任务 ID、`TaskRecord`、不可变快照和 `queued → running → terminal` 状态转换校验。
2. `submit` 在管理器锁内生成最终任务 ID、冻结 `ChildRunSpec` 并决定立即运行、进入显式 FIFO 或因队列满拒绝；拒绝时不留下任务记录。
3. 启动固定数量 daemon worker；worker 只从显式队列取任务，运行槽和队列数量始终可观察且不依赖执行器内部队列。
4. 捕获执行器全部异常并转换为安全失败结果；无论何种路径都设置一次 finished time 和 done Event。
5. 将投递状态与执行状态正交管理；实现 `finish_foreground_wait` 原子解决完成、超时和手动切后台竞争。
6. 只有后台投递模式的终态任务领取一次通知权并写入一次 Session 收件箱；同步领取任务不通知、不投递。
7. 实现 list/get/wait/cancel 的 Session 所属校验、有界等待和幂等终态行为；queued 取消从 FIFO 删除，running 取消设置 token。
8. 实现收件箱原子取出及失败恢复，生成有界首尾预览；完整结果只保留在任务记录中。
9. 实现 `cancel_session(clear_inbox=True)`，清除旧 Session 排队项、请求取消运行项、删除未注入结果并拒绝新 Session 访问旧任务。
10. 实现有界 `shutdown`：取消所有任务、等待到 deadline、汇总未结束 daemon worker，重复调用幂等。
11. 使用 Barrier/Event 编排完成与超时、完成与取消、多个 worker 和通知失败竞争，避免依赖真实 sleep 的脆弱测试。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_task_manager.py -v
```

期望：默认/自定义并发、FIFO、队列满、唯一终态、唯一通知、Session 隔离、取消和有界关闭全部通过。

**建议提交：** `Manage bounded asynchronous agent tasks`

## T8：冻结父请求并建立 Fork 首轮上下文路径

**文件：** `src/mycode/agents/bridge.py`、`src/mycode/tools/registry.py`、`src/mycode/context/manager.py`、`src/mycode/agent/runner.py`、`tests/test_agent_request_bridge.py`、`tests/test_context_manager.py`、`tests/test_agent_runner.py`

**依赖：** T2、T4

**步骤：**

1. 对实际发送的 `ChatRequest`、有序 Registry 和 Session/Mode 做深复制快照，禁止后续父状态修改快照内容。
2. 使用稳定 JSON 序列化计算请求指纹，覆盖 stable system、dynamic system、optional system、完整消息、工具 schema/说明/顺序及缓存标记。
3. `ParentRequestBridge` 只允许当前 Session 读取活动快照；重复 publish、错误指纹 clear、跨 Session 和无活动请求返回确定错误。
4. 主 Runner 在每次请求准备完成且即将调用 Provider 前 publish；若无工具调用、批次执行结束、异常或取消则在 finally 中 clear。
5. 快照只包含发送前内容，因此不包含 Provider 在途 Assistant 文本、本次 `Agent` 调用或同批其他工具调用。
6. 给 ContextManager 增加 Fork 首轮只估算接口：在冻结父 request.messages 后追加子任务 user 消息，不运行工具结果外置、用户消息外置或摘要。
7. 追加后低于预算则原样返回；超过预算则结构化失败，不退回普通压缩路径。
8. 后续轮次允许子 ContextManager 使用正常外置和摘要，但 system 模板及工具顺序继续来自冻结快照。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_request_bridge.py tests/test_context_manager.py tests/test_agent_runner.py
```

期望：深复制、Session 边界、发布/撤销、异常清理、序列化前缀逐字段一致及超预算不改写均通过。

**建议提交：** `Freeze parent requests for cacheable agent forks`

## T9：实现定义式与 Fork 式子 Agent 跑到底执行器

**文件：** `src/mycode/agents/runner.py`、`src/mycode/agents/models.py`、`src/mycode/agent/runner.py`、`src/mycode/agent/events.py`、`src/mycode/context/manager.py`、`tests/test_child_agent_runner.py`、`tests/test_agent_runner.py`

**依赖：** T2、T3、T4、T5、T6、T8

**步骤：**

1. 实现 TokenAccumulator，逐轮累加 input、output、total、cache read、cache creation 和 unavailable，并计入子上下文摘要 usage。
2. 定义式运行构造空历史 Runner，使用标准稳定基础提示、项目指令和角色正文，不注入父消息、Skill 激活、Skill 目录、长期记忆、时间间隔提醒或主 SessionJournal。
3. 使用角色模型档位映射、最大轮次、冻结工具策略、独立 PermissionService、FileReadCache、ContextStore 和 HookScope。
4. Fork 运行导入父 request.messages 并追加子任务；首次请求走 T8 的冻结路径且延迟 Hook prompt，后续请求使用自己的上下文状态。
5. Fork 可见工具始终使用冻结父 tool specs/order，实际调用通过 T6 策略；定义式只展示过滤后的 Registry。
6. 消费现有 AgentEvent 直到 done；模型不再调工具且有最终 Assistant 文本时完成，取消、最大轮次、解析、Provider、上下文及内部异常映射为安全终态。
7. 只把最后一个无工具调用的 Assistant 文本作为结果，中间文本和工具轨迹不写主历史。
8. 在 finally 中关闭子 ContextStore 与 HookScope；单个关闭失败只进入安全失败原因或诊断，不泄漏敏感异常正文。
9. 验证同一工作区文件修改对其他 Agent 可见，但消息、缓存、权限审计和 Token 累加对象完全独立。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_child_agent_runner.py tests/test_agent_runner.py tests/test_agent_policy.py tests/test_agent_permissions.py
```

期望：两种启动上下文、跑到底、停止原因、模型选择、工具限制、清理和运行时隔离全部通过。

**建议提交：** `Run isolated defined and forked child agents`

## T10：实现稳定的 Agent 与 Task 控制工具

**文件：** `src/mycode/agents/tools.py`、`src/mycode/agents/models.py`、`src/mycode/tools/executor.py`、`src/mycode/tool_safety.py`、`src/mycode/tools/registry.py`、`tests/test_agent_control_tools.py`、`tests/test_tool_executor.py`、`tests/test_tools_registry.py`

**依赖：** T2、T6、T7、T8、T9

**步骤：**

1. 固定注册名为 `Agent` 和 `Task` 的 ToolSpec；schema 同时包含所有已批准字段，角色、任务和模式变化不得改变 schema 或注册顺序。
2. `Agent` 描述在取 spec 时读取当前角色目录说明，但只改变说明文本；工具实例不因热更新重新注册。
3. 运行时严格验证空 prompt、defined/fork、role/background 跨字段组合、未知角色和缺失父快照；非法请求不提交任务。
4. 定义式创建冻结任务并按 `background` 决定立即返回或调用 ForegroundWaiter；等待结束后使用管理器原子领取同步结果或切后台。
5. Fork 禁止 role、始终以后台提交；收到 `background=false` 时仍后台执行并在返回中明确说明。
6. 所有 `Agent` 返回统一包含 task ID、类型和状态；同步完成额外返回结果和完整 TokenUsage，队列满返回结构化拒绝且没有 task ID。
7. `Task` 实现 list/get/wait/cancel 参数矩阵、当前 Session 过滤和等待硬上限；get 的 display 使用有界预览，complete 保留任务完整结果供现有上下文外置。
8. 两个控制工具声明 `manages_own_timeout=True`；ToolExecutor 对此类工具在当前执行线程运行，普通工具仍走原有外层超时。
9. 把控制工具作为主 Agent 系统工具自动允许，但验证 T6 策略在任何子 Agent 中先行拒绝。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_control_tools.py tests/test_tool_executor.py tests/test_tools_registry.py
```

期望：固定 schema/顺序、全部参数组合、同步/后台结果、Session 边界和自行限时语义通过。

**建议提交：** `Expose stable Agent and Task control tools`

## T11：接入主 Agent 的快照桥与后台结果收件箱

**文件：** `src/mycode/agent/runner.py`、`src/mycode/context/manager.py`、`src/mycode/agents/tasks.py`、`tests/test_agent_runner.py`、`tests/test_context_manager.py`、`tests/test_session_journal.py`

**依赖：** T7、T8、T10

**步骤：**

1. 主 Runner 在每次普通 Provider 请求前按当前 Session ID 原子领取收件箱，不主动触发新请求。
2. 把后台结果按固定 XML 风格边界与本次原始用户输入组合成单条 user 消息；Hook `message_received` 仍只接收原始用户文本。
3. 组合消息同时写入 ContextManager 与 SessionJournal，保证恢复后只作为普通消息存在，不创建任务或通知。
4. 预览包含任务 ID、类型、角色、终态、失败原因、结果首尾及 TokenUsage；不包含 prompt、工具参数或权限目标。
5. 注入或日志写入失败时把未消费项目恢复到原 Session 收件箱，并返回现有 session_error，不静默丢失。
6. 每轮实际请求发布 T8 快照，工具批次执行期间保持有效，之后无论完成或失败都清除。
7. `/new` 前清除旧桥快照；没有任务管理依赖时 Runner 保持完全兼容。
8. 验证子 Agent 中间文本、工具消息和审计从不进入主历史，只有同步 ToolResult 或收件箱组合消息出现。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py tests/test_context_manager.py tests/test_session_journal.py tests/test_session_loader.py
```

期望：安全点注入、失败恢复、持久化恢复、桥生命周期和历史无污染全部通过。

**建议提交：** `Deliver child-agent results into parent turns`

## T12：接入前台等待、Tasks 命令和 CLI 生命周期

**文件：** `src/mycode/agents/waiting.py`、`src/mycode/commands/models.py`、`src/mycode/commands/interfaces.py`、`src/mycode/commands/builtins.py`、`src/mycode/commands/__init__.py`、`src/mycode/cli.py`、`tests/test_agent_foreground_waiting.py`、`tests/test_command_builtins.py`、`tests/test_cli.py`

**依赖：** T2、T3、T5、T7、T10、T11

**步骤：**

1. 实现基于 Event 的通用前台等待器，完成与 timeout 使用单调时钟且无忙轮询。
2. 实现 prompt-toolkit 小型等待 Application；只在定义式前台等待期间把 `Ctrl+B` 映射为 manual，完成或超时自动退出，不取消任务。
3. 终端不可交互、测试或 prompt-toolkit 不可用时回退 Event 等待器；`Ctrl+C` 继续取消主 Agent 当前 turn。
4. 新增 `/tasks` 无参数本地命令和 CommandUI 查询接口，按创建时间显示当前 Session 的 ID、类型、角色、投递模式、状态和用量摘要。
5. CLI 初始化 ProviderPool、空角色运行时、权限配置、Hook 主 scope、子执行器、任务管理器、请求桥和两个控制工具；注册顺序固定。
6. 在 MCP 和控制工具就绪后首次加载角色目录并验证已知工具；每次主 Agent 请求前刷新角色并输出脱敏诊断，不重新注册工具。
7. 用 prompt-toolkit 安全 stdout patch 显示后台通知，使当前输入行可恢复；通知失败不得影响任务收件箱。
8. `/new` 先对旧 Session 调用 cancel/clear 和有界等待，再关闭旧主上下文、清桥并切换 Session/Hook；新 Session 无法访问旧任务。
9. CLI 退出按任务管理器、主 Agent/Journal/Memory、Hook、ProviderPool、MCP 顺序幂等清理；未停止 daemon worker 只产生安全警告。
10. 保持无 Agent 配置、无 Hook、无 MCP、恢复 Session、Skill 热更新、Plan/Do 和各种退出路径行为兼容。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_foreground_waiting.py tests/test_command_builtins.py tests/test_cli.py
```

期望：`Ctrl+B`、`/tasks`、热更新、异步通知、三种后台入口、`/new` 和所有退出清理路径通过。

**建议提交：** `Integrate agent tasks into the interactive CLI`

## T13：完成端到端场景、内置角色和用户文档

**文件：** `tests/test_agent_delegation_integration.py`、`tests/test_hooks_integration.py`、`tests/test_skill_isolated.py`、`tests/test_cli.py`、`src/mycode/agents/builtins/explore.md`、`config.example.yaml`、`README.md`、`pyproject.toml`

**依赖：** T2–T12

**步骤：**

1. 建立可控并发 Provider fixture，记录每次 `ChatRequest`、工具顺序、线程、用量和缓存指标，不访问真实网络。
2. 端到端验证定义式前台完成：空历史、角色提示、过滤工具、独立权限/缓存/Token，最终结果作为单个 Agent ToolResult 回灌。
3. 端到端验证 Fork：立即后台、父前缀逐字段一致、追加子任务、不含在途 Assistant/Agent 调用、运行时禁止嵌套并汇总缓存指标。
4. 验证明示后台、排队/运行累计超时和 `Ctrl+B` 三种入口使用同一任务且不重启，最终只通知和投递一次。
5. 验证 `Task` 查询结果与用量、空闲不唤醒模型、下一请求收件箱注入、超大结果预览/完整外置和主历史无中间轨迹。
6. 验证并发上限、FIFO、队列满、Hook scope、共享 Provider 连接、同工作区文件可见和状态隔离。
7. 验证 `/new`、正常退出、取消竞争和进程重启语义；旧任务不恢复，已持久化结果只作为普通历史。
8. 完善内置 `explore` 角色文案，确保只读白名单、strict 权限和有限轮次。
9. 在 `config.example.yaml` 说明所有 Agent 配置、安全默认值和模型档位映射。
10. 在 README 说明角色目录与格式、来源优先级、定义式/Fork、`Agent`/`Task`、`/tasks`、三种后台入口、权限拒绝、资源上限、缓存指标和不做的范围。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_delegation_integration.py tests/test_hooks_integration.py tests/test_skill_isolated.py tests/test_cli.py -v
rg -n "\.mycode/agents|Agent|Task|/tasks|Ctrl\+B|foreground_timeout|background_allowed_tools|haiku|sonnet|opus|Worktree|持久" README.md config.example.yaml
```

期望：AC28、AC29 的完整场景通过，文档覆盖配置、行为、安全和范围。

**建议提交：** `Document and verify sub-agent delegation end to end`

## T14：执行完整回归与交付前检查

**文件：** 所有本功能修改文件；只在验证失败时修改对应责任文件和测试

**依赖：** T13

**步骤：**

1. 运行 Agent 定义、配置、策略、权限、任务、桥、子运行、控制工具、等待和端到端定向测试。
2. 运行 Provider、Hooks、Skills、MCP、权限、上下文、Session、工具、命令和 CLI 回归测试。
3. 运行完整 pytest、Python 编译和 diff 空白检查；如失败，修复根因并重跑受影响集合与完整集合。
4. 用静态搜索确认没有 TODO/TBD、调试器、临时打印、硬编码 Claude 模型 ID、任务持久化、Worktree 或孙 Agent 创建路径。
5. 核对 `Agent`/`Task` schema 和顺序快照、Fork 请求指纹证据、通知次数、Token cache 指标、线程/子上下文清理证据。
6. 比较 T0 基线与最终状态，确认未删除或回退既有 Hooks、Skills、MCP、权限和会话能力。
7. 按已批准 `checklist.md` 逐项执行最终验收并记录实际证据。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_agent_definition_parser.py \
  tests/test_agent_catalog.py \
  tests/test_agent_policy.py \
  tests/test_agent_permissions.py \
  tests/test_provider_pool.py \
  tests/test_agent_request_bridge.py \
  tests/test_child_agent_runner.py \
  tests/test_agent_task_manager.py \
  tests/test_agent_control_tools.py \
  tests/test_agent_foreground_waiting.py \
  tests/test_agent_delegation_integration.py
PYTHONPATH=src .venv/bin/python -m pytest
PYTHONPYCACHEPREFIX=/tmp/mycode-agent-pycache PYTHONPATH=src .venv/bin/python -m compileall -q src
git diff --check
rg -n "TO""DO|TB""D|breakpoint\(|pdb\.set_trace|claude-(haiku|sonnet|opus)|worktree|list_resources|read_resource" src tests README.md config.example.yaml
```

期望：定向测试、完整测试、编译和 diff 检查通过；静态搜索只出现文档中的范围说明或测试断言，不存在未完成实现与越界能力。

**建议提交：** `Complete sub-agent delegation acceptance checks`

## 执行顺序

```text
T0 → T1
      ├→ T2 ───────────────┐
      ├→ T3 ───────────┐   │
      └→ T4 ───────┐   │   │
T0 ─────→ T5 ──────┼──→ T6 │
T1 + T4 ───────────┴──→ T7 │
T2 + T4 ───────────────→ T8│
T2 + T3 + T4 + T5 + T6 + T8 → T9
T2 + T6 + T7 + T8 + T9 ─────→ T10
T7 + T8 + T10 ───────────────→ T11
T2 + T3 + T5 + T7 + T10 + T11 → T12
T2–T12 ───────────────────────→ T13
T13 ──────────────────────────→ T14
```

可并行组：T2、T3、T4、T5 在 T1/T0 前置满足后可独立推进；T7 与 T8 在各自依赖满足后也可并行。实际开发时同一文件存在重叠的任务不得并发编辑，合并前必须先同步最新内容。
