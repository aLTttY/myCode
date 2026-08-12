# 生命周期 Hook Tasks

## 文件清单

### 新建源码

| 文件 | 职责 |
|---|---|
| `src/mycode/matching.py` | 共享 exact、regex、glob 和反向匹配 |
| `src/mycode/hooks/__init__.py` | Hook 公共导出 |
| `src/mycode/hooks/models.py` | Hook 事件、规则、动作、结果和诊断模型 |
| `src/mycode/hooks/conditions.py` | 条件解析、字段访问和 all/any 判断 |
| `src/mycode/hooks/events.py` | 十种 schema v1 Payload 构造 |
| `src/mycode/hooks/config.py` | 三层 YAML 加载与集中校验 |
| `src/mycode/hooks/actions.py` | command、HTTP、agent 占位和异步队列 |
| `src/mycode/hooks/runtime.py` | 调度、once、prompt lease 和生命周期状态 |

### 修改源码与文档

| 文件 | 职责 |
|---|---|
| `src/mycode/permissions/models.py` | 权限规则引用共享 MatchPattern |
| `src/mycode/permissions/rules.py` | 新匹配语法与冲突优先级 |
| `src/mycode/permissions/config.py` | 新语法加载和声明顺序 |
| `src/mycode/permissions/service.py` | 会话 exact 规则及安全流程兼容 |
| `src/mycode/tools/executor.py` | 保留工具结果来源 |
| `src/mycode/agent/executor.py` | 工具前后 Hook、拒绝和确定顺序 |
| `src/mycode/context/manager.py` | 动态指令替换与预算复核 |
| `src/mycode/agent/runner.py` | 轮次、消息、系统事件和 prompt lease |
| `src/mycode/skills/isolated.py` | 独立 Skill 一次性 Hook 指令 |
| `src/mycode/cli.py` | 配置加载、会话事件、退出原因和清理 |
| `README.md` | Hook 使用文档 |
| `config.example.yaml` | Hook 文件示例说明 |
| `.gitignore` | 忽略 `.mycode/hooks.local.yaml` |

### 新建测试

| 文件 | 职责 |
|---|---|
| `tests/test_matching.py` | 共享匹配语法与兼容性 |
| `tests/test_hooks_conditions.py` | 条件字段和 all/any |
| `tests/test_hooks_events.py` | 十种 Payload |
| `tests/test_hooks_config.py` | 三层加载和集中校验 |
| `tests/test_hooks_actions.py` | 四类动作、协议、超时和异步 |
| `tests/test_hooks_runtime.py` | 顺序、once、拒绝、诊断和 prompt lease |
| `tests/test_hooks_integration.py` | 主会话端到端场景 |

### 修改测试

| 文件 | 职责 |
|---|---|
| `tests/test_permissions_rules.py` | regex、反向及冲突顺序 |
| `tests/test_permissions_config.py` | 新语法和旧配置兼容 |
| `tests/test_permissions_service.py` | 安全流程集成 |
| `tests/test_tool_executor.py` | 结果来源和兼容接口 |
| `tests/test_agent_executor.py` | 工具 Hook 与只读并发顺序 |
| `tests/test_context_manager.py` | 动态指令预算复核 |
| `tests/test_agent_runner.py` | 主生命周期和 prompt lease |
| `tests/test_skill_isolated.py` | 独立 Skill 隔离 |
| `tests/test_cli.py` | 加载、切换、退出和资源清理 |

## 任务总览

- T1：实现共享匹配器并迁移权限规则
- T2：定义 Hook 模型、条件和事件 Payload
- T3：实现三层 Hook 配置加载与集中校验
- T4：实现 command、HTTP、agent 占位和异步执行
- T5：实现 Hook Runtime、once、诊断和 prompt lease
- T6：接入工具执行前后生命周期
- T7：接入 Agent、上下文和独立 Skill 生命周期
- T8：接入 CLI 会话生命周期与资源清理
- T9：补充配置示例和用户文档
- T10：完成端到端、全量回归与验收准备

## T1：实现共享匹配器并迁移权限规则

**文件：**

- `src/mycode/matching.py`
- `src/mycode/permissions/models.py`
- `src/mycode/permissions/rules.py`
- `src/mycode/permissions/config.py`
- `src/mycode/permissions/service.py`
- `tests/test_matching.py`
- `tests/test_permissions_rules.py`
- `tests/test_permissions_config.py`
- `tests/test_permissions_service.py`

**依赖：** 无

**步骤：**

1. 定义不可变 MatchPattern、解析错误和 exact/regex/glob 类型优先级。
2. 实现旧式自动 exact/glob、显式 `glob:`、`re:` 和前置 `!`；正则在解析时编译验证。
3. 实现大小写敏感 exact、`fnmatchcase` glob 和 regex search。
4. 将 PermissionRule 迁移为持有 MatchPattern，同时保留 expression 展示和现有配置外层语法。
5. 更新层内规则选择为“匹配类型 → deny → 声明顺序”，保持层级优先不变。
6. 会话审批继续生成 exact、非反向规则。
7. 补充新语法、反向、非法正则、旧语义不变及完整冲突矩阵测试。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_matching.py \
  tests/test_permissions_rules.py \
  tests/test_permissions_config.py \
  tests/test_permissions_service.py
```

预期：全部通过；既有 exact/glob 用例结果不变。

## T2：定义 Hook 模型、条件和事件 Payload

**文件：**

- `src/mycode/hooks/__init__.py`
- `src/mycode/hooks/models.py`
- `src/mycode/hooks/conditions.py`
- `src/mycode/hooks/events.py`
- `tests/test_hooks_conditions.py`
- `tests/test_hooks_events.py`

**依赖：** T1

**步骤：**

1. 定义十种事件名、四类动作、规则、快照、ActionOutcome、DispatchResult、PromptLease 和 Diagnostic。
2. 实现 `field(pattern)` 解析，复用共享 MatchPattern。
3. 为每种事件定义合法固定字段目录，以及工具参数和结果 data 的动态叶子路径。
4. 实现 JSON 标量规范化；对象、数组和缺失字段不匹配，反向也不将缺失字段变成命中。
5. 实现非空 all/any 判断，拒绝混用、嵌套和非法字段路径。
6. 建立事件工厂，构造公共 session/turn 字段和十种事件专属字段。
7. 将 Payload 深度冻结，确保条件与多个动作看到不可修改的同一快照。
8. 测试固定时间、固定工作区、结果来源、display 结果边界及 JSON 编码。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_matching.py \
  tests/test_hooks_conditions.py \
  tests/test_hooks_events.py
```

预期：全部事件可稳定编码；字段条件和 all/any 行为符合设计。

## T3：实现三层 Hook 配置加载与集中校验

**文件：**

- `src/mycode/hooks/config.py`
- `src/mycode/hooks/models.py`
- `tests/test_hooks_config.py`

**依赖：** T2

**步骤：**

1. 用重复键检测 SafeLoader 读取用户、项目和本地固定路径。
2. 缺失文件产生空层；存在文件的顶层只接受 `hooks`。
3. 按用户、项目、本地和文件声明顺序生成稳定 rule_id、来源路径及 1-based 规则序号。
4. 严格校验 rule 的 event/if/action 字段与类型。
5. 按动作类型校验必填、可选和未知字段，应用默认值。
6. 校验 command 超时范围、HTTP URL/method/header、固定 content type、prompt 和 agent 字段。
7. 拒绝 prompt 异步、非 command/HTTP 异步、所有 `tool_before` 异步以及 `session_end` prompt。
8. 验证事件与条件字段兼容性，并在加载期编译所有正则。
9. 任意层失败时抛出包含路径、规则序号和字段的 ConfigError，不返回部分 Snapshot。
10. 覆盖缺失文件、空配置、三层顺序、重复键和非法组合参数化测试。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_hooks_config.py \
  tests/test_hooks_conditions.py
```

预期：合法三层配置按确定顺序加载；所有静态错误在启动前被定位。

## T4：实现 command、HTTP、agent 占位和异步执行

**文件：**

- `src/mycode/hooks/actions.py`
- `src/mycode/hooks/models.py`
- `tests/test_hooks_actions.py`

**依赖：** T2、T3

**步骤：**

1. 实现统一 JSON 序列化、输出限制、拒绝原因截断和敏感值清理。
2. command 在工作区以 shell 和独立进程组启动，通过 stdin 接收 Payload，并有界读取 stdout/stderr。
3. 实现默认/自定义超时、取消和关闭时的子进程及后代清理。
4. 普通 command 以退出码 0 成功；`tool_before` 解析 0 allow、2 deny、其他失败并放行。
5. HTTP 使用固定 10 秒超时、JSON body 和 content type，静态 method/URL/headers，不做插值。
6. 普通 HTTP 以 2xx 成功；`tool_before` 严格解析 allow/deny JSON，其他响应失败并放行。
7. agent 动作只返回 placeholder 诊断，不导入 Agent/Provider。
8. 实现固定 daemon worker、有界队列、队列满失败、关闭拒绝新任务和不等待退出。
9. 所有运行异常转换为 failed/cancelled Outcome，不向调用方传播。
10. 覆盖 cwd、stdin Payload、协议、超时、大输出、网络错误、敏感值、异步提交和清理测试。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_actions.py
```

预期：外部动作协议、大小边界、失败隔离及资源关闭测试全部通过。

## T5：实现 Hook Runtime、once、诊断和 prompt lease

**文件：**

- `src/mycode/hooks/runtime.py`
- `src/mycode/hooks/models.py`
- `tests/test_hooks_runtime.py`

**依赖：** T2、T3、T4

**步骤：**

1. 实现会话开始/结束、轮次开始/结束及十种事件分发入口。
2. 每次分发按 Snapshot 顺序选择事件和条件并串行处理同步规则。
3. prompt 动作按触发顺序入队；agent placeholder 和动作失败输出安全诊断。
4. 实现 once 消耗矩阵：success、submitted、denied、prompt 入队和 placeholder 消耗，failed/cancelled 不消耗。
5. 实现工具 deny 立即停止该调用剩余前置规则并返回原因。
6. 实现 PromptLease 的 reserve、refresh、commit、release，限制单个活动 lease。
7. `/new` 所需的旧会话结束、新会话开始和 once/prompt/turn 状态重置由 Runtime 提供原子边界。
8. 锁只保护状态，不在锁内执行外部动作；关闭幂等且不递归分发事件。
9. 覆盖三层顺序、all/any、once 重试、异步提交、deny 短路、诊断脱敏和 lease 状态机测试。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_hooks_conditions.py \
  tests/test_hooks_events.py \
  tests/test_hooks_config.py \
  tests/test_hooks_actions.py \
  tests/test_hooks_runtime.py
```

预期：Hook 核心在未接入 Agent 前即可完整通过单元测试。

## T6：接入工具执行前后生命周期

**文件：**

- `src/mycode/tools/executor.py`
- `src/mycode/agent/executor.py`
- `tests/test_tool_executor.py`
- `tests/test_agent_executor.py`

**依赖：** T5

**步骤：**

1. 为 ToolExecutor 增加带 `tool`、`permission`、`validation` 来源的内部执行记录，同时保持原 `execute()` 返回值兼容。
2. BatchToolExecutor 接收可选 HookRuntime；未提供时保持原路径。
3. 按模型调用顺序完成所有 `tool_before`，被拒绝的调用合成 `source=hook` 的失败结果。
4. 保证 Hook 拒绝发生在工具查找、权限判定和工具启动之前，拒绝后不产生工具开始事件。
5. 对放行调用继续执行原有注册校验、黑名单、沙箱、权限审批和工具逻辑。
6. 保留只读调用并发，但在结果齐备后按原调用顺序触发一次 `tool_after`。
7. 确保权限拒绝、未知工具、异常、超时、Hook 拒绝和成功均有唯一 `tool_after`。
8. 确保 Agent 可见事件和历史结果关联仍使用原调用 ID 与原顺序。
9. 覆盖 deny 短路、allow 不绕过权限、批内其他调用继续、来源分类和并发完成乱序测试。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_tool_executor.py \
  tests/test_agent_executor.py \
  tests/test_hooks_runtime.py
```

预期：工具前置 Hook 无竞态；每个调用恰好产生一个确定顺序的后置事件。

## T7：接入 Agent、上下文和独立 Skill 生命周期

**文件：**

- `src/mycode/context/manager.py`
- `src/mycode/agent/runner.py`
- `src/mycode/skills/isolated.py`
- `tests/test_context_manager.py`
- `tests/test_agent_runner.py`
- `tests/test_skill_isolated.py`

**依赖：** T6

**步骤：**

1. ContextManager 增加替换动态系统指令并重新构造请求、复核 token 预算的通用能力，不依赖 Hook 模块。
2. AgentRunner 接收可选 HookRuntime，统一普通消息、共享 Skill 和独立 Skill 的主轮次协调。
3. 在用户消息写入前触发 `message_received`，最终 assistant 文本写入前触发 `message_sent`。
4. 用 finally 保证每轮至多一次 `turn_end`，记录 completed、cancelled、错误、Skill 失败、未知工具和迭代上限。
5. 在规定的结构化错误出口触发一次 `agent_error`，避免普通工具失败、取消和 Hook 失败误触发。
6. 自动与手动压缩仅在 success 时触发 `context_compacted`。
7. 在模型请求准备前 reserve prompt lease；压缩事件后 refresh 并重新估算；Provider 调用前 commit，未发送请求则 release。
8. BatchToolExecutor 注入同一 Runtime。
9. 独立 Skill 临时 Agent 不安装 Runtime，只接收主轮次 lease 中的动态指令及提交/释放控制。
10. 保证共享 Skill 不嵌套产生第二组主轮次事件，独立 Skill 内部工具和错误不触发 Hook。
11. 覆盖多迭代单轮、流式消息边界、各种停止原因、自动/手动压缩、预算失败保留 prompt 和 Skill 隔离测试。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_context_manager.py \
  tests/test_agent_executor.py \
  tests/test_agent_runner.py \
  tests/test_skill_isolated.py
```

预期：主生命周期事件次数和顺序正确；提示词恰好进入一次实际模型请求。

## T8：接入 CLI 会话生命周期与资源清理

**文件：**

- `src/mycode/cli.py`
- `tests/test_cli.py`

**依赖：** T3、T5、T7

**步骤：**

1. 在连接 MCP 和创建后台服务前加载并整体校验三层 Hook 配置。
2. 创建动作执行器和 Runtime，注入主 AgentRunner，并将安全诊断输出到 stderr。
3. 主 Agent 可用后触发新建或恢复来源的 `session_start`。
4. 让交互循环返回 exit、eof、interrupt 或 fatal_error 等明确结束原因。
5. Ctrl+C 取消时显式关闭 Agent 事件迭代器，使轮次 finally 立即完成。
6. `/new` 严格执行旧 session_end、旧资源关闭、Runtime 状态重置、新日志创建和新 session_start。
7. 应用退出时先触发 session_end，再关闭 Agent、日志、Hook 执行器、MCP 和其他资源。
8. 保证启动中途失败、重复 close 和未配置 Hook 路径安全。
9. 覆盖配置错误早停、新建/恢复、`/new`、exit、EOF、Ctrl+C、异常退出和清理顺序测试。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_cli.py \
  tests/test_agent_runner.py \
  tests/test_hooks_config.py
```

预期：会话事件边界及关闭顺序正确；无 Hook 时 CLI 行为保持兼容。

## T9：补充配置示例和用户文档

**文件：**

- `README.md`
- `config.example.yaml`
- `.gitignore`

**依赖：** T8

**步骤：**

1. 记录用户、项目、本地三层路径及确定执行顺序。
2. 给出三要素 YAML 示例和十种事件目录。
3. 说明 all/any、exact、glob、regex、反向及缺失字段语义。
4. 说明 command、prompt、HTTP、agent 字段、默认值和限制。
5. 说明 stdin/JSON body、工具拦截协议、fail-open、once、异步和超时语义。
6. 说明 prompt 一次性注入、`/new` 重置及独立 Skill 边界。
7. 明确子 Agent 真实执行、once 持久化和显式优先级不在本阶段。
8. 在配置示例中提供注释化 Hook 文件样例，不误导用户把 hooks 写进 Provider 配置。
9. 将 `.mycode/hooks.local.yaml` 加入默认忽略。

**验证：**

```bash
rg -n \
  "hooks.yaml|hooks.local.yaml|tool_before|context_compacted|once|async|decision|re:|glob:" \
  README.md config.example.yaml .gitignore
```

预期：所有配置入口、事件、动作和关键边界均可从文档检索并与实现一致。

## T10：完成端到端、全量回归与验收准备

**文件：**

- `tests/test_hooks_integration.py`
- 必要时修改本任务涉及的测试文件

**依赖：** T1–T9

**步骤：**

1. 构造同时包含 command、prompt、HTTP 和危险工具拦截的主会话场景。
2. 验证三层规则顺序、统一 Payload、prompt 一次消费和工具拒绝回灌。
3. 让 Agent 在收到拒绝后调整工具调用并完成当前轮次。
4. 注入 command 失败、HTTP 超时、无效响应和后台队列压力，验证主流程继续。
5. 验证 `/new` 重置 once/prompt，进程级恢复也允许 once 再次触发。
6. 验证 agent 占位没有创建 Provider、Agent、线程或会话。
7. 运行 Hook、权限、工具、Agent、上下文、Skill、MCP、会话和 CLI 回归测试。
8. 运行完整测试套件和源码编译检查，修复后重新全量运行。
9. 保存测试命令、通过数量和端到端观察结果，供 checklist 验收使用。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_integration.py -v

PYTHONPATH=src .venv/bin/python -m pytest

PYTHONPATH=src .venv/bin/python -m compileall -q src tests
```

预期：端到端场景和全量测试通过，源码与测试文件均可编译。

## 执行顺序

```text
T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10
```

T2 的模型被 T3–T8 共用；T4 与 T5 分离，使外部动作协议和调度状态可以独立验证；T6 先稳定工具拒绝与结果来源，再由 T7 接入完整 Agent 循环。

## 任务覆盖

| 设计范围 | 任务 |
|---|---|
| 共享匹配与权限兼容 | T1 |
| Hook 模型、条件和 Payload | T2 |
| 配置加载与集中校验 | T3 |
| 四类动作与执行控制 | T4 |
| 调度、once、诊断和 prompt lease | T5 |
| 工具拦截与结果来源 | T6 |
| 轮次、消息、系统事件和 Skill | T7 |
| 会话、CLI 与资源生命周期 | T8 |
| 用户文档与配置示例 | T9 |
| 端到端和全量回归 | T10 |
