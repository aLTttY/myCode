# Mycode 五层权限系统 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mycode/permissions/__init__.py` | 导出权限系统公共接口 |
| 新建 | `src/mycode/permissions/models.py` | 权限模式、规则、请求、决定、审批和配置类型 |
| 新建 | `src/mycode/permissions/blacklist.py` | 不可配置的灾难性命令黑名单 |
| 新建 | `src/mycode/permissions/targets.py` | 各工具权限目标提取与规范化 |
| 新建 | `src/mycode/permissions/sandbox.py` | 文件路径沙箱和命令显式路径检查 |
| 新建 | `src/mycode/permissions/rules.py` | 规则解析、匹配、冲突处理和层级判定 |
| 新建 | `src/mycode/permissions/config.py` | 三层 YAML 加载、校验、模式解析和本地规则写入 |
| 新建 | `src/mycode/permissions/approval.py` | 审批协议、终端审批和无交互拒绝实现 |
| 新建 | `src/mycode/permissions/service.py` | 五层权限判定编排与会话状态 |
| 修改 | `src/mycode/tools/executor.py` | 在工具实现前统一执行权限判定 |
| 修改 | `src/mycode/tools/search.py` | 为代码搜索增加工作区内的可选搜索范围 |
| 修改 | `src/mycode/agent/executor.py` | 把权限服务传入批量工具执行器 |
| 修改 | `src/mycode/agent/runner.py` | 注入权限服务并保持拒绝结果回灌 |
| 修改 | `src/mycode/session.py` | 旧会话工具调用接入同一权限层 |
| 修改 | `src/mycode/cli.py` | 权限模式参数、配置加载和终端审批 |
| 修改 | `src/mycode/types.py` | 补充权限集成所需的结构化类型或结果字段 |
| 修改 | `.gitignore` | 忽略本地私有权限配置 |
| 修改 | `README.md` | 权限使用说明、安全边界和已知限制 |
| 修改 | `config.example.yaml` | 指向独立权限配置文件和模式入口 |
| 新建 | `tests/test_permissions_blacklist.py` | 黑名单不可绕过测试 |
| 新建 | `tests/test_permissions_sandbox.py` | 路径、符号链接和命令显式路径测试 |
| 新建 | `tests/test_permissions_rules.py` | 精确/glob、冲突和层级优先级测试 |
| 新建 | `tests/test_permissions_config.py` | YAML 校验、模式优先级和原子写入测试 |
| 新建 | `tests/test_permissions_service.py` | 三档模式、审批范围和五层编排测试 |
| 修改 | `tests/test_tools_search.py` | 搜索范围行为与越界回归测试 |
| 修改 | `tests/test_tool_executor.py` | 权限前置拦截和工具不触达测试 |
| 修改 | `tests/test_agent_executor.py` | 批量执行与审批串行化测试 |
| 修改 | `tests/test_agent_runner.py` | 权限拒绝回灌后继续循环测试 |
| 修改 | `tests/test_session_tools.py` | ChatSession 权限接入和无交互拒绝测试 |
| 修改 | `tests/test_tool_streaming.py` | 工具流式路径权限回归测试 |
| 修改 | `tests/test_cli.py` | CLI 模式、配置错误和审批交互测试 |
| 修改 | 其他受构造签名影响的现有测试 | 保持既有行为回归通过 |

## T1: 建立权限模型与规则引擎

**文件：**

- `src/mycode/permissions/__init__.py`
- `src/mycode/permissions/models.py`
- `src/mycode/permissions/rules.py`
- `tests/test_permissions_rules.py`

**依赖：** 无

**覆盖：** F6-F11，N1

**步骤：**

1. 定义 `PermissionMode`、`PermissionRule`、`PermissionLayer`、`PermissionRequest`、`PermissionDecision`、`ApprovalChoice`、`ApprovalPrompt` 和 `PermissionConfigSet`。
2. 实现完整锚定的 `工具名(模式)` 解析，拒绝空工具名、空模式和括号外多余内容。
3. 根据 `*`、`?`、`[...]` 判断精确或 glob 匹配，统一采用大小写敏感语义。
4. 实现同层“精确优先、同类型 deny 优先”。
5. 实现跨层“会话 > 本地 > 项目 > 用户”，某层有命中后不再检查低层。
6. 导出后续模块需要的稳定公共类型，避免权限模块间形成循环依赖。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_rules.py
```

期望：精确/glob 匹配、同层冲突、跨层冲突和无匹配场景全部通过。

## T2: 实现黑名单、沙箱与权限目标

**文件：**

- `src/mycode/permissions/blacklist.py`
- `src/mycode/permissions/sandbox.py`
- `src/mycode/permissions/targets.py`
- `src/mycode/tools/search.py`
- `tests/test_permissions_blacklist.py`
- `tests/test_permissions_sandbox.py`
- `tests/test_tools_search.py`

**依赖：** T1

**覆盖：** F2-F5、F7，N2、N4

**步骤：**

1. 用不可变代码常量定义灾难性命令正则，覆盖根目录或用户目录破坏、磁盘覆写或格式化、系统目录递归权限修改、关机重启和 fork bomb。
2. 同时检查原始命令与规范化空白后的命令，支持常见前缀、参数顺序和复合命令片段。
3. 实现基于 `Path.resolve()` 和路径层级关系的工作区判断，不使用字符串前缀。
4. 分别覆盖现有路径、待创建路径、绝对路径、`..`、项目内符号链接和项目外符号链接。
5. 对命令进行词法拆分，识别路径参数、路径型选项值和重定向目标；只拦截可识别的显式越界路径，不宣称限制运行时隐式访问。
6. 为六个已注册工具实现稳定权限目标解析；未知工具或关键参数无效时安全拒绝。
7. 为 `search_code` 增加可选 `path` 参数，默认 `.`，并把搜索迭代限制在经过沙箱验证的范围内。
8. 确保测试仅调用判定逻辑，不执行任何黑名单命令。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_blacklist.py tests/test_permissions_sandbox.py tests/test_tools_search.py
```

期望：黑名单样例全部硬拒绝；普通开发命令不被黑名单误拒绝；文件与显式命令路径逃逸均被拦截；限定范围搜索正常工作。

## T3: 实现分层配置与永久规则存储

**文件：**

- `src/mycode/permissions/config.py`
- `tests/test_permissions_config.py`

**依赖：** T1

**覆盖：** F6、F8-F10、F13、F19，N2、N6

**步骤：**

1. 实现用户、项目、本地三个固定配置路径的可选加载。
2. 使用能检测重复键的安全 YAML 加载器，只接受 `mode`、`allow`、`deny`。
3. 校验字段类型、权限模式、规则格式和真实注册工具名；缺失文件返回空层，无效文件抛出可理解配置错误。
4. 按 CLI > 本地 > 项目 > 用户 > `default` 解析有效权限模式。
5. 实现 `LocalRuleStore.add_exact_allow`：重新读取、严格校验、去重追加、保留已有字段。
6. 使用同目录临时文件和原子替换写入 `.mycode/permissions.local.yaml`，写入失败不得报告成功。
7. 验证本地永久写入不会修改项目级或用户级配置。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_config.py
```

期望：三层加载、模式优先级、缺失文件、所有无效配置、去重追加和原子写入场景全部通过。

## T4: 实现审批接口与五层权限服务

**文件：**

- `src/mycode/permissions/approval.py`
- `src/mycode/permissions/service.py`
- `src/mycode/permissions/__init__.py`
- `tests/test_permissions_service.py`

**依赖：** T1、T2、T3

**覆盖：** F1-F3、F8-F18，N1-N7、N10

**步骤：**

1. 定义可注入的 `ApprovalHandler`，实现始终拒绝的非交互处理器。
2. 在 `PermissionService` 中按“目标解析、黑名单、沙箱、分层规则、权限模式、审批”固定顺序编排。
3. 确保黑名单、沙箱和显式 deny 直接拒绝，永远不调用审批器。
4. 实现 strict 拒绝、default 审批、allow 放行的未命中行为。
5. 实现拒绝、本次、本会话、永久四种审批结果。
6. 会话放行添加当前目标的精确内存规则；永久放行通过 `LocalRuleStore` 写入精确规则。
7. 对审批、会话规则和永久写入使用锁，避免并发提示和状态竞态。
8. 统一生成不泄露敏感参数的原因码和面向模型的结构化拒绝说明。
9. 永久写入失败或审批异常时安全拒绝，不留下声称已持久化的状态。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_service.py
```

期望：五层顺序、不可覆盖拒绝、三档模式、四种用户决定、会话生命周期、永久写入和无交互拒绝全部通过。

## T5: 在 ToolExecutor 建立统一权限门禁

**文件：**

- `src/mycode/tools/executor.py`
- `src/mycode/types.py`
- `tests/test_tool_executor.py`
- `tests/test_tools_files.py`
- `tests/test_tools_command.py`

**依赖：** T4

**覆盖：** F1、F4-F5、F16-F17，N3、N8

**步骤：**

1. 为 ToolExecutor 注入 `PermissionService`，且在提交线程执行工具实现前完成权限判断。
2. 将权限拒绝转换成 `ToolResult(ok=False)`，包含稳定原因码、工具名和安全摘要。
3. 验证被拒绝时工具实现调用次数为零。
4. 保留未知工具、超时、工具异常和输出截断的既有结构化行为。
5. 更新直接构造 ToolExecutor 的测试，显式提供对应权限模式或测试权限服务。
6. 补充文件工具符号链接逃逸与命令显式路径拦截的执行层回归。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_tool_executor.py tests/test_tools_files.py tests/test_tools_command.py
```

期望：拒绝调用不触达工具；获准工具、超时和异常路径保持正常；现有文件与命令测试通过。

## T6: 接入 AgentRunner、批量执行与 ChatSession

**文件：**

- `src/mycode/agent/executor.py`
- `src/mycode/agent/runner.py`
- `src/mycode/session.py`
- `tests/test_agent_executor.py`
- `tests/test_agent_runner.py`
- `tests/test_session_tools.py`
- `tests/test_tool_streaming.py`

**依赖：** T5

**覆盖：** F1、F15、F17-F18，N3、N7-N9

**步骤：**

1. 把同一个权限服务从 AgentRunner 传到 BatchToolExecutor 和每个 ToolExecutor。
2. 保持有副作用工具串行执行，只让权限判定已通过的只读工具并发运行。
3. 确保权限拒绝仍产生正常 `tool_result` 事件并写入消息历史。
4. 添加两轮模型脚本：第一轮调用被拒绝，第二轮选择安全替代方案并完成任务。
5. 确认权限拒绝不新增 stop reason，也不重置已有未知工具计数逻辑。
6. 让 ChatSession 使用同一权限服务；未提供交互审批时采用安全拒绝处理器。
7. 更新受构造签名影响的会话和流式测试。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_executor.py tests/test_agent_runner.py tests/test_session_tools.py tests/test_tool_streaming.py
```

期望：批处理顺序不变；权限拒绝成功回灌并继续迭代；ChatSession 无旁路；既有流式行为通过。

## T7: 接入 CLI 权限模式、配置与终端审批

**文件：**

- `src/mycode/cli.py`
- `tests/test_cli.py`
- `tests/test_config.py`

**依赖：** T3、T4、T6

**覆盖：** F8、F10-F15、F19，N4-N6、N10

**步骤：**

1. 增加 `--permission-mode strict|default|allow`，保持 `/plan`、`/do` 语义独立。
2. 启动时加载三层权限 YAML；配置错误打印明确来源并返回非零状态。
3. 创建 `TerminalApprovalHandler` 并注入共享权限服务。
4. 审批提示展示工具名、安全截断并遮蔽敏感值的权限目标、请求原因和四个决定。
5. 对无效选择继续询问；Ctrl+C 取消当前任务；输入流结束时安全拒绝审批。
6. 增加 CLI 参数覆盖配置模式、用户拒绝、本次、本会话和永久放行的测试。
7. 确认普通 CLI 对话、token usage、Plan/Do 解析和既有错误处理继续通过。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py tests/test_config.py
```

期望：CLI 模式优先级、审批交互、配置错误与既有命令行行为全部通过。

## T8: 更新配置说明与安全文档

**文件：**

- `.gitignore`
- `README.md`
- `config.example.yaml`

**依赖：** T7

**覆盖：** N5、N8、N10，以及已知限制

**步骤：**

1. 将 `.mycode/permissions.local.yaml` 加入 `.gitignore`，不忽略项目共享 `.mycode/permissions.yaml`。
2. 在 README 记录三个配置路径、统一 YAML 格式、规则目标、精确/glob 判定和层级优先级。
3. 说明 strict、default、allow 与 Plan/Do 的区别。
4. 说明拒绝、本次、本会话、永久四个审批选择及永久规则写入位置。
5. 说明黑名单与路径沙箱不可覆盖，并明确命令运行时隐式文件访问不受本阶段强隔离。
6. 在 Provider 配置示例中只加入权限配置位置提示，避免把两类配置混为一个 YAML。
7. 检查所有新增文档统一使用 `Mycode`，不出现旧项目名称。

**验证：**

```bash
rg -n "permissions\.local\.yaml|permission-mode|strict|default|allow|隐式文件访问" README.md config.example.yaml .gitignore
rg -n "Mycode" README.md config.example.yaml src tests
```

期望：权限入口、安全边界和已知限制均可检索；项目文案中不出现旧名称。

## T9: 执行全量回归与端到端验收准备

**文件：**

- `tests/test_agent_runner.py`
- `tests/test_cli.py`
- 所有因集成暴露问题而需要修正的本任务范围内文件

**依赖：** T1-T8

**覆盖：** AC1-AC24，N8-N9

**步骤：**

1. 建立端到端场景：default 模式首次调用请求审批，拒绝结果回灌，模型下一轮改用获准工具并完成。
2. 建立端到端场景：永久放行写入本地 YAML，重新创建权限服务后相同目标直接命中。
3. 建立端到端场景：allow 模式和最高优先级 allow 规则都不能覆盖黑名单或路径沙箱。
4. 建立端到端场景：Plan Mode 仅暴露只读工具，且只读工具仍经过权限系统。
5. 运行全部测试，修复权限改造引入的回归并重复执行直到通过。
6. 执行格式与命名检查，确认没有 TODO、TBD、旧项目名称或文档宣称过度。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest
git diff --check
rg -n "TODO|TBD" spec.md plan.md task.md src tests README.md config.example.yaml || true
rg -n "Mycode" spec.md plan.md task.md README.md config.example.yaml
```

期望：全量测试通过；diff 无空白错误；本阶段文件无占位符或旧名称；端到端测试能证明拒绝后 Agent Loop 继续运行。

## 执行顺序

```text
T1 -> T2 -> T3 -> T4 -> T5 -> T6 -> T7 -> T8 -> T9
```

T2 与 T3 在完成 T1 后没有直接依赖；若未来并行实施，可以同时进行，但合并后必须先完成 T4 的联合验证再进入执行层集成。
