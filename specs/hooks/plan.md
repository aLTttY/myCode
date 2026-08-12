# 生命周期 Hook Plan

## 架构概览

实现分为“共享匹配、配置加载、事件调度、动作执行、宿主接入”五层。

### 共享匹配层

抽取与业务无关的字符串匹配器，统一解析自动精确/glob、显式 `glob:`、`re:` 和 `!` 反向语法。权限规则与 Hook 条件都依赖该匹配器；权限层继续负责工具名、规则效果和层级冲突，避免 Hook 反向依赖权限模块。

### 配置加载层

Hook 配置加载器一次读取用户、项目、本地三层 YAML，逐条生成带来源和声明序号的不可变规则快照。解析过程严格拒绝重复键、未知字段、非法事件、条件和动作组合；只有三层全部通过才发布快照。

顶层格式统一为：

```yaml
hooks:
  - event: tool_before
    if:
      all:
        - "tool.name(run_command)"
        - "tool.arguments.command(re:^rm\\s)"
    action:
      type: command
      command: "./scripts/check-tool"
      timeout_seconds: 10
      once: false
      async: false
```

### 事件调度层

每个主会话持有一个 Hook Runtime。Runtime 负责：

- 从统一事件工厂生成版本化 Payload；
- 按规则顺序筛选事件和条件；
- 串行执行同一事件的同步规则；
- 管理会话内 `once` 状态；
- 保存并一次性消费待注入提示词；
- 把有效的工具拒绝返回给工具执行链；
- 将运行失败转成安全、受限的日志诊断。

`/new` 复用同一份规则快照，但结束旧 Runtime 会话状态并重置 `once`、提示词队列和轮次计数。

### 动作执行层

command、HTTP、prompt、agent 使用统一动作结果协议：

- command 与 HTTP 执行器只负责有限输入、输出、超时和协议解析；
- prompt 写入 Runtime 的一次性队列；
- agent 返回稳定的“尚未实现”占位结果；
- 异步 command/HTTP 进入有界后台执行器；
- 所有异常在动作边界转换为 Hook 失败，不向 Agent 主流程抛出。

### 宿主接入层

- CLI：加载配置，触发主会话开始/结束，并处理 `/new` 的旧会话结束和新会话开始。
- AgentRunner：触发轮次、用户消息、最终 assistant 消息、上下文压缩和 Agent 错误事件，并在构建下一次模型请求时消费提示词。
- BatchToolExecutor：在原调用顺序上执行 `tool_before`，之后才进入权限和工具执行；为权限拒绝、Hook 拒绝、未知工具、超时及正常结果统一触发 `tool_after`。
- 独立 Skill 的临时 Agent 不安装 Hook Runtime；其输入和最终摘要只在主会话边界触发一次轮次/消息事件。
- 旧版 ChatSession 和直接使用 ToolExecutor 的路径默认不启用 Hook，保持兼容。

## 核心数据结构

### MatchPattern

```python
@dataclass(frozen=True)
class MatchPattern:
    kind: Literal["exact", "regex", "glob"]
    value: str
    negated: bool = False
```

共享匹配层将旧式无前缀表达式解析为 exact 或 glob，将 `glob:`、`re:` 解析为显式类型，并单独保存前置 `!`。`matches(value)` 先执行内部类型匹配，再在 `negated` 时取反。权限规则通过 `kind` 参与“exact > regex > glob”的优先级。

### HookCondition

```python
@dataclass(frozen=True)
class HookClause:
    field: str
    pattern: MatchPattern

@dataclass(frozen=True)
class HookCondition:
    operator: Literal["all", "any"]
    clauses: tuple[HookClause, ...]
```

条件项文本采用 `field(pattern)`。`all` 或 `any` 必须包含至少一个条件项。固定字段必须属于事件 Payload 的字段目录；`tool.arguments.<key...>` 和 `result.data.<key...>` 允许动态叶子路径。只匹配 JSON 字符串、数字、布尔值或 null 的规范文本，不把对象和数组隐式转成字符串。字段不存在或不是标量时视为不匹配；反向条件也不会把“字段不存在”变成命中。

### HookRule 与动作

```python
@dataclass(frozen=True)
class HookRule:
    rule_id: str
    source: Literal["user", "project", "local"]
    source_path: Path
    source_index: int
    event: HookEventName
    condition: HookCondition | None
    action: HookAction
```

`rule_id` 由来源和文件内序号稳定生成，仅用于日志与当前进程的 `once` 集合，不作为跨进程标识。

动作使用四个互斥结构：

```python
@dataclass(frozen=True)
class CommandAction:
    command: str
    timeout_seconds: float = 10.0
    once: bool = False
    asynchronous: bool = False

@dataclass(frozen=True)
class HTTPAction:
    url: str
    method: str = "POST"
    headers: Mapping[str, str] = field(default_factory=dict)
    once: bool = False
    asynchronous: bool = False

@dataclass(frozen=True)
class PromptAction:
    content: str
    once: bool = False

@dataclass(frozen=True)
class AgentAction:
    prompt: str
    once: bool = False
```

HTTP URL 只接受 `http`/`https`；method 规范化为大写 HTTP token，Payload 始终作为 JSON body 发送。配置中的 `Content-Type` 不允许覆盖固定的 `application/json`。

### HookEvent

```python
HookEventName = Literal[
    "session_start", "session_end",
    "turn_start", "turn_end",
    "message_received", "message_sent",
    "tool_before", "tool_after",
    "context_compacted", "agent_error",
]

@dataclass(frozen=True)
class HookEvent:
    name: HookEventName
    payload: Mapping[str, object]
```

Payload `schema_version` 固定为 `1`，使用本地带时区 ISO 8601 时间。公共字段：

```json
{
  "schema_version": 1,
  "event": "tool_before",
  "occurred_at": "2026-08-12T10:00:00.000000+08:00",
  "workspace": "/workspace",
  "session": {
    "id": "20260812-100000-abcd",
    "origin": "new"
  },
  "turn": {
    "id": 1,
    "mode": "default",
    "input_kind": "message"
  }
}
```

不适用的 `turn` 省略。事件专属字段：

- 会话事件：`session.end_reason`。
- 轮次事件：`turn.stop_reason`。
- 消息事件：`message.role`、`message.content`。
- 工具事件：`tool.call_id`、`tool.name`、`tool.arguments`；`tool_after` 追加 `result.ok`、`result.message`、`result.data`、`result.source`。
- 压缩事件：`context.trigger`、`before_tokens`、`after_tokens`、`budget_tokens`、卸载与摘要计数。
- 错误事件：`error.code`、`error.message`。

`result.source` 区分 `tool`、`permission`、`hook`、`validation`，便于条件和日志判断结果来源。
`tool_after` 的结果字段取自已受大小限制的 display 结果，不把仅供会话存储与上下文卸载使用的 complete 结果复制给 Hook。

### HookActionOutcome 与 HookDispatchResult

```python
@dataclass(frozen=True)
class HookActionOutcome:
    status: Literal[
        "success", "failed", "cancelled", "submitted", "denied", "placeholder"
    ]
    reason: str = ""

@dataclass(frozen=True)
class HookDispatchResult:
    denied: bool = False
    reason: str = ""
```

`failed`、`cancelled` 和 `placeholder` 只生成日志；`submitted` 表示异步任务已成功进入队列；只有 `tool_before` 的 `denied` 会终止剩余前置规则并返回拒绝原因。

### HookDiagnostic

```python
@dataclass(frozen=True)
class HookDiagnostic:
    source_path: Path
    source_index: int
    event: HookEventName
    code: str
    message: str
```

诊断只携带可安全展示的规则位置、稳定错误码和受限消息，由注入的日志 sink 处理。

### HookSnapshot

```python
@dataclass(frozen=True)
class HookSnapshot:
    rules: tuple[HookRule, ...]
```

快照在三层全部校验后一次性发布，规则顺序已经固定为用户、项目、本地及各文件声明顺序。

### HookRuntime

```python
@dataclass(frozen=True)
class HookPromptLease:
    lease_id: str
    instructions: tuple[DynamicInstruction, ...]
```

Prompt lease 标识一次请求拟消费的队列前缀；同一时刻至多存在一个活动 lease。

```python
class HookRuntime:
    def begin_session(self, session_id: str, origin: str) -> None: ...
    def end_session(self, reason: str) -> None: ...
    def begin_turn(self, mode: str, input_kind: str) -> int: ...
    def message_received(self, content: str) -> None: ...
    def message_sent(self, content: str) -> None: ...
    def end_turn(self, stop_reason: str) -> None: ...
    def before_tool(self, call: ToolCall) -> HookDispatchResult: ...
    def after_tool(
        self,
        call: ToolCall,
        result: ToolExecutionResult,
        source: str,
    ) -> None: ...
    def context_compacted(self, report: CompactionReport) -> None: ...
    def agent_error(self, code: str, message: str) -> None: ...
    def reserve_prompts(self) -> HookPromptLease: ...
    def refresh_prompt_lease(self, lease_id: str) -> HookPromptLease: ...
    def commit_prompt_lease(self, lease_id: str) -> None: ...
    def release_prompt_lease(self, lease_id: str) -> None: ...
    def close(self) -> None: ...
```

Runtime 串行维护当前会话、轮次、自增 turn id、`once` 集合和提示词队列。每个 prompt 使用唯一动态指令 tag；构建模型请求时先预留，只有即将调用 Provider 时才提交并视为已消费。独立 Skill 可接收 lease 中的指令和提交/释放回调，但不持有 Runtime、也不产生内部 Hook。

### HookConfigLoader 与 HookActionExecutor

```python
class HookConfigLoader:
    def load(self, workspace_root: Path) -> HookSnapshot: ...

class HookActionExecutor:
    def execute(
        self,
        rule: HookRule,
        event: HookEvent,
    ) -> HookActionOutcome: ...

    def close(self, *, wait: bool = False) -> None: ...
```

加载器负责整体校验和定位错误。执行器负责 command、HTTP、占位动作及有界异步队列；prompt 由 Runtime 直接排队。时钟、HTTP client、进程启动器、日志 sink 和后台 executor 均可在测试中替换。

## 模块设计

### 共享字符串匹配器

**位置：** `src/mycode/matching.py`

**职责：**

- 解析旧式自动 exact/glob、显式 `glob:`、`re:` 和 `!`。
- 编译并缓存正则。
- 对标量规范文本执行大小写敏感匹配。
- 向权限层暴露匹配类型，用于 exact > regex > glob 排序。

该模块不了解 Hook、工具或权限效果，避免模块间循环依赖。

### Hook 模型与配置

**位置：**

- `src/mycode/hooks/models.py`
- `src/mycode/hooks/config.py`

**职责：**

- 定义事件、条件、规则、动作、执行结果和快照。
- 用支持重复键检测的 SafeLoader 读取三层 YAML。
- 为每个文件保留路径与 1-based 规则序号。
- 校验字段集合、事件与字段路径、动作专属字段、URL/method/header、超时范围及异步约束。
- 三层全部成功后才返回不可变快照。

Hook 配置使用独立加载器，不并入 Provider 的 `config.yaml`，与现有权限配置分层方式保持一致。

### 条件与 Payload

**位置：**

- `src/mycode/hooks/conditions.py`
- `src/mycode/hooks/events.py`

**职责：**

- `conditions.py` 解析 `field(pattern)`，校验该事件允许的字段，并执行 all/any。
- `events.py` 集中构造十种事件的 schema v1 Payload，统一时间、工作区、会话、轮次和专属字段。
- JSON 标量规范化为：字符串原值、数字十进制文本、布尔值 `true|false`、null 为 `null`。
- 对象、数组及不存在字段不参与匹配。
- Payload 在调度前冻结为只读快照；动作只能观察，不能修改后续动作看到的数据。

### 动作执行器

**位置：** `src/mycode/hooks/actions.py`

**职责：**

- command 使用受控 `Popen`，工作目录固定为工作区，stdin 写入 UTF-8 JSON，stdout/stderr 有界读取；超时或关闭时终止仍活动的 Hook 子进程。
- HTTP 使用现有 `httpx`，发送固定 JSON body 和 content type，限制响应体大小并关闭响应。
- `tool_before` command 解析 0/2 协议；HTTP 只接受单个严格 JSON 决定对象。
- agent 动作返回 placeholder，不导入或创建 Agent。
- 运行异常统一转成 `HookActionOutcome(failed)` 和脱敏诊断。

后台任务由内部有界 daemon worker 队列执行，固定 worker 数和队列容量；队列已满视为提交失败，不消耗 `once`。Runtime 最终关闭时停止接收新任务、取消未开始任务、终止活动 command，但不等待 `session_end` 动作完成。

### Hook Runtime

**位置：** `src/mycode/hooks/runtime.py`

**职责：**

- 串行管理主会话事件、turn id、`once` 集合和提示词队列。
- 每次 dispatch 固定完成：选择事件规则 → 计算条件 → 执行动作 → 更新 once → 记录诊断。
- `tool_before` 收到 deny 后立即结束 dispatch。
- prompt 按规则触发顺序排队，在下一次模型请求构建时整体预留，并在 Provider 调用前一次性提交。
- Runtime 使用锁保护异步完成记录、提示词和状态，但不持锁执行外部 command/HTTP。
- Hook 动作不经过 Runtime 再分发生命周期事件，从结构上阻止递归。

### 权限规则适配

**位置：**

- `src/mycode/permissions/models.py`
- `src/mycode/permissions/rules.py`
- `src/mycode/permissions/config.py`
- `src/mycode/permissions/service.py`

**职责：**

- `PermissionRule` 持有共享 `MatchPattern`。
- 旧字符串规则继续使用原外层 `tool(pattern)` 格式。
- RuleEngine 先按层级取首个有匹配的层，再在层内选择最高匹配类型，之后 deny 优先，最后按声明顺序。
- 会话审批产生的临时规则仍为非反向 exact。
- Hook allow 结束后仍必须执行黑名单、沙箱、权限规则、模式和人工审批，既有安全边界不变。

### 工具执行接入

**位置：**

- `src/mycode/tools/executor.py`
- `src/mycode/agent/executor.py`

`ToolExecutor` 增加保留结果来源的内部执行记录接口，来源为 `tool`、`permission` 或 `validation`；现有 `execute()` 仍返回 `ToolExecutionResult`，保持直接调用方兼容。

`BatchToolExecutor` 接收可选 Hook Runtime：

1. 按模型给出的工具调用顺序执行 `tool_before`。
2. 被 Hook 拒绝时合成 `source=hook` 的失败结果，不发起权限判定或工具执行。
3. 放行后才产生工具开始事件并调用 ToolExecutor。
4. 只读工具仍并发执行，但结果收集完成后按原始调用顺序触发 `tool_after`，确保 Hook 同步动作和 prompt 排队顺序确定。
5. Agent 历史继续按原始调用顺序写入，现有并发收益和结果关联不变。

### Agent 接入

**位置：** `src/mycode/agent/runner.py`

**职责：**

- 主 `run()` 在 try/finally 边界保证每轮各一次 start/end。
- `run()` 与 `invoke_skill()` 复用同一个主轮次协调器，避免共享 Skill 内部再次触发一组轮次事件。
- 用户消息写入前触发 `message_received`；最终 assistant 消息形成后触发 `message_sent`。
- 在每次构造 Provider 请求时预留 Hook prompt，并转换为带唯一 tag 的动态系统指令；请求发出前提交 lease。
- 自动或手动压缩报告为 success 时触发 `context_compacted`。
- 现有结构化 Agent 错误在统一出口触发一次 `agent_error`。
- BatchToolExecutor 使用同一 Runtime。
- `invoke_skill()` 把共享或独立 Skill 视为一个主轮次；独立 Skill 接收本轮预留的动态 Hook prompt，但临时 AgentRunner 不安装 Runtime。
- `new_session()` 完成旧会话 end、状态重置、新日志创建和新会话 start。

### CLI 生命周期接入

**位置：** `src/mycode/cli.py`

**职责：**

- 在连接外部服务和进入交互循环之前加载、整体校验 Hook 配置。
- 创建共享动作执行器与 Runtime，并注入主 AgentRunner。
- 主 Agent 创建完成后触发 `session_start`。
- 交互循环返回明确的退出原因，如 `exit`、`eof`、`interrupt`、`startup_error`。
- 渲染循环在 Ctrl+C 时先取消并显式关闭当前 Agent 事件迭代器，确保轮次 finally 立即执行。
- 在关闭 Agent、日志、MCP 和其他资源前触发 `session_end`。
- Hook 运行诊断统一以 `[hook]` 前缀写入 stderr；不打印敏感动作配置或完整 Payload。
- 最外层 finally 幂等关闭 Runtime 和动作执行器。

### 独立 Skill 接入

**位置：** `src/mycode/skills/isolated.py`

独立 Skill Runner 增加可选的一次性动态指令参数，仅把主轮次已消费的 Hook prompt 加入临时 Agent 的模型请求；不传递 Hook Runtime，不产生内部会话、轮次、消息、工具或错误 Hook。

### 文档与示例

**位置：**

- `README.md`
- `config.example.yaml`
- `.gitignore`

README 说明事件目录、三层文件、条件与动作协议、拦截和失败语义。示例配置新增注释化 Hook YAML 示例或单独展示配置片段。本地 `hooks.local.yaml` 加入默认忽略规则。

## 模块交互

### 启动与会话开始

1. CLI 解析基础配置并确定工作区。
2. HookConfigLoader 在连接 MCP、创建后台服务前读取三层 Hook 文件。
3. 三层全部校验成功后创建 HookActionExecutor 与 HookRuntime。
4. CLI 继续初始化工具、权限、Skill、会话日志和主 AgentRunner。
5. 主 Agent 可用后调用 `begin_session`，触发 `session_start`。
6. `session_start` 产生的 prompt 留在队列中，等待首个模型请求。

Hook 配置无效时在外部连接或 Hook 动作发生前终止启动，不存在部分规则生效。

### 普通主轮次

```text
begin_turn
  → turn_start
  → message_received
  → 写入用户消息
  → 准备上下文和模型请求
  → 模型/工具内部迭代
  → 最终 assistant 文本形成
  → message_sent
  → 写入最终 assistant 消息
  → turn_end
```

`turn_end` 通过 `finally` 保证至多一次；若生成器因用户 Ctrl+C 被关闭，则根据 CancellationToken 记录 `cancelled`。其中：

- 正常完成时顺序为 `message_sent → turn_end(completed)`。
- 结构化错误时顺序为 `agent_error → turn_end(error reason)`。
- 取消、未知工具阈值、Skill 失败和迭代上限只触发 `turn_end`，不触发 `agent_error`。
- `turn_end` 产生的 prompt 留给下一轮。

### Prompt 预留与消费

Runtime 对 prompt 使用“预留—提交”协议：

1. 构建请求前取得当前提示词 lease，但不删除队列。
2. 把 lease 中的提示词纳入动态系统消息和 token 估算。
3. 若自动压缩成功，先触发 `context_compacted`，刷新 lease，并让 ContextManager 用新的动态消息重新构造请求及复核预算，但不重复触发压缩。
4. 只有请求获准、即将调用 Provider 时才提交 lease 并从队列移除。
5. 上下文准备失败或请求未发出时取消预留，提示词继续等待下一次请求。

因此，自动 `context_compacted` 产生的 prompt 可进入当前即将发出的请求；手动 `/compact` 产生的 prompt 进入之后的首个请求。为此在 `src/mycode/context/manager.py` 增加通用的“替换动态指令并重新估算”能力，该模块不直接依赖 Hook。

### 工具调用

对一批工具调用：

1. 按模型给出的调用顺序逐个触发 `tool_before`。
2. 对单个调用，一旦某条规则 deny，只停止该调用剩余的前置规则，不影响同批其他调用。
3. 被 deny 的调用直接生成 `source=hook` 的失败 ToolResult。
4. 放行的调用进入原有注册校验、黑名单、路径沙箱、权限规则、审批和工具执行。
5. 只读调用中的放行项仍并发执行。
6. 所有结果收集后，按原始调用顺序触发 `tool_after` 并写入 Agent 历史。
7. 每个调用只产生一次 `tool_after`，来源区分：
   - `hook`：Hook 拒绝；
   - `permission`：黑名单、沙箱、权限规则、模式或人工审批拒绝；
   - `validation`：未知工具或非法调用；
   - `tool`：工具成功、工具失败、异常或超时。

Hook 拒绝的调用不产生“工具开始”事件，但仍产生可见失败结果和 `tool_after`。

### `/new` 与退出

`/new` 的顺序：

```text
旧 session_end(reason=switched)
  → 关闭旧会话日志和上下文
  → 清空 once、prompt lease、prompt 队列和 turn 状态
  → 创建新会话
  → session_start(origin=new)
```

应用退出时，CLI 根据路径产生 `exit`、`eof`、`interrupt` 或 `fatal_error`，先触发活动会话的 `session_end`，再关闭 Agent、日志、Hook 执行器、MCP 和其他资源。关闭过程幂等。

### Skill 调用

- 共享 Skill 直接走普通主轮次，仅产生一组轮次和消息事件。
- 独立 Skill 由主 Agent 建立轮次，临时 Agent 不持有 HookRuntime。
- 主 Runtime 将 prompt lease 作为一次性动态指令交给临时 Agent；临时 Agent 在首次实际 Provider 请求时提交 lease。
- 独立 Skill 的内部工具、错误和消息不触发 Hook；最终摘要回流时触发主会话的 `message_sent` 和 `turn_end`。

### 运行失败与诊断

动作失败转成 `HookDiagnostic`，仅包含来源文件、规则序号、事件、稳定错误码和受限安全消息。日志不包含完整 command、URL、headers、Payload、stdout 或 HTTP body。

command stderr 和 HTTP deny reason 只有在有效拦截时才会经截断与敏感值清理后进入工具结果。Hook 诊断本身不会再次分发 `agent_error` 或其他 Hook。

## 文件组织

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mycode/matching.py` | 共享 exact/regex/glob/反向匹配 |
| 新建 | `src/mycode/hooks/__init__.py` | Hook 公共导出 |
| 新建 | `src/mycode/hooks/models.py` | 规则、动作、Payload 与结果模型 |
| 新建 | `src/mycode/hooks/config.py` | 三层 YAML 加载与整体校验 |
| 新建 | `src/mycode/hooks/conditions.py` | 条件解析、字段解析与 all/any |
| 新建 | `src/mycode/hooks/events.py` | 十种 schema v1 事件构造 |
| 新建 | `src/mycode/hooks/actions.py` | command、HTTP、agent 占位及后台队列 |
| 新建 | `src/mycode/hooks/runtime.py` | 调度、once、prompt 与生命周期状态 |
| 修改 | `src/mycode/permissions/models.py` | 使用共享 MatchPattern |
| 修改 | `src/mycode/permissions/rules.py` | 新语法和冲突顺序 |
| 修改 | `src/mycode/permissions/config.py` | 保持规则声明顺序和错误定位 |
| 修改 | `src/mycode/tools/executor.py` | 暴露带来源的内部执行记录 |
| 修改 | `src/mycode/agent/executor.py` | 工具前后 Hook 与确定顺序 |
| 修改 | `src/mycode/agent/runner.py` | 轮次、消息、压缩、错误和 prompt 接入 |
| 修改 | `src/mycode/context/manager.py` | 替换动态指令后重构请求并复核预算 |
| 修改 | `src/mycode/skills/isolated.py` | 接收一次性动态 Hook prompt |
| 修改 | `src/mycode/cli.py` | 加载、会话事件、退出原因和清理 |
| 修改 | `README.md` | 用户配置与语义文档 |
| 修改 | `config.example.yaml` | Hook 文件示例说明 |
| 修改 | `.gitignore` | 忽略本地 Hook 配置 |
| 新建 | `tests/test_matching.py` | 共享匹配语法、语义和兼容性 |
| 新建 | `tests/test_hooks_config.py` | 三层加载、字段与组合集中校验 |
| 新建 | `tests/test_hooks_conditions.py` | 字段选择、标量规范化和 all/any |
| 新建 | `tests/test_hooks_events.py` | 十种 schema v1 Payload |
| 新建 | `tests/test_hooks_actions.py` | command、HTTP、agent 占位、超时和异步队列 |
| 新建 | `tests/test_hooks_runtime.py` | 顺序、once、拒绝、诊断和 prompt lease |
| 新建 | `tests/test_hooks_integration.py` | 主会话端到端 Hook 场景 |
| 修改 | `tests/test_permissions_rules.py` | regex、反向和冲突优先级 |
| 修改 | `tests/test_permissions_config.py` | 新语法加载与旧配置兼容 |
| 修改 | `tests/test_permissions_service.py` | 新匹配规则与既有安全流程集成 |
| 修改 | `tests/test_tool_executor.py` | 内部结果来源与兼容接口 |
| 修改 | `tests/test_agent_executor.py` | 工具前后 Hook、拦截和只读确定顺序 |
| 修改 | `tests/test_agent_runner.py` | 轮次、消息、系统事件与 prompt lease |
| 修改 | `tests/test_context_manager.py` | 动态指令替换和预算复核 |
| 修改 | `tests/test_skill_isolated.py` | 独立 Skill 一次性指令且无内部 Hook |
| 修改 | `tests/test_cli.py` | 加载、会话切换、退出原因和清理 |

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 表达式语法 | `["!"] selector("(" matcher ")")`；matcher 为自动 exact/glob、`glob:` 或 `re:` | 同时兼容旧权限规则和已确认的 Hook 示例 |
| 正则语义 | 大小写敏感 `search`；启动时编译 | 使 `re:^rm\\s` 能匹配命令前缀，并提前发现非法正则 |
| glob 语义 | 大小写敏感整串 `fnmatchcase` | 保持现有权限行为 |
| 反向缺失字段 | 字段缺失或不是标量始终不匹配，不执行反向取真 | 防止拼写错误或事件不适用字段意外扩大命中范围 |
| 动态字段路径 | 点分路径，只允许合法字段段；叶子必须是 JSON 标量 | 支持嵌套工具参数，同时保持解析与校验简单确定 |
| 权限冲突 | 层级优先；层内 exact > regex > glob；再 deny；再声明顺序 | 落实已批准的冲突规则 |
| Hook 合并 | 用户 → 项目 → 本地 → 文件声明顺序 | 落实已批准的执行顺序，不引入显式优先级 |
| command 信任边界 | Hook 配置视为用户授权的本地自动化，命令不再经过 Agent 工具权限；继承进程环境，不注入事件环境变量 | 避免 Hook 与工具权限递归，Payload 只通过 stdin 传递 |
| command 启动 | 工作区 cwd、shell 执行、独立进程组、UTF-8 JSON stdin | 满足 shell 动作并支持超时/关闭时清理后代进程 |
| command 结果 | 普通事件仅退出码 0 成功；`tool_before` 中 0 allow、2 deny、其他失败并放行 | 落实拦截协议和 fail-open 原则 |
| HTTP 决定 | 2xx 且响应严格为 `{"decision":"allow"}` 或 `{"decision":"deny","reason":"..."}` | 避免模糊响应错误拦截 |
| HTTP 普通动作 | 任意 2xx 视为成功，其他状态或网络错误视为失败 | 普通通知不需要响应业务协议 |
| HTTP headers | 固定覆盖为 `application/json`；拒绝用户配置 `Content-Type`；不做事件或环境变量插值 | 保持统一 Payload 并消除隐式动态注入 |
| once 消耗 | success、submitted、denied、prompt 入队及 agent placeholder 消耗；failed/cancelled 不消耗 | 四类动作和拦截都获得一致的一次性语义 |
| 异步资源 | 固定少量 daemon worker + 有界队列；满队列提交失败；退出不等待，command 子进程尽力终止 | 保证 Agent 与进程退出不被后台动作阻塞 |
| 输出边界 | stdout、stderr、HTTP body 使用统一有限缓冲；拒绝原因和日志再使用更小上限 | 防止无界数据进入内存、终端和模型 |
| Agent 错误目录 | `stream_error`、`tool_parse_error`、`context_overflow`、`session_error`、`internal_error` | 与已确认的系统事件边界一致 |
| 兼容路径 | Hook Runtime 为可选依赖；ChatSession、直接 ToolExecutor 和独立临时 Agent 默认不启用 | 未配置 Hook 时保持既有调用行为 |

## Spec 覆盖

| 需求 | 设计覆盖 |
|---|---|
| F1 | HookConfigLoader 读取用户、项目、本地三层固定路径，缺失文件产生空层。 |
| F2 | HookSnapshot 在加载期固化用户 → 项目 → 本地 → 文件声明顺序。 |
| F3 | HookRule 模型和严格配置校验确保 event/action 必填、if 可选且每条只有一个动作。 |
| F4 | events.py 集中构造十种 HookEvent，Runtime 暴露对应生命周期入口。 |
| F5 | AgentRunner 的 run/invoke_skill 主边界和 Runtime turn 状态定义单次用户输入的一轮。 |
| F6 | AgentRunner 只在完整用户输入与最终 assistant 文本处触发消息事件。 |
| F7 | BatchToolExecutor 在权限和工具前调用 before_tool，并为每个结果调用 after_tool。 |
| F8 | CLI 与 `/new` 流程负责新建、恢复、切换和退出时的会话事件。 |
| F9 | AgentRunner 的压缩与结构化错误出口触发系统事件，Hook 诊断绕过 Runtime 分发。 |
| F10 | HookCondition 只允许非空 all 或 any，conditions.py 拒绝嵌套和混用。 |
| F11 | matching.py 统一实现自动 exact/glob、显式 glob、regex 和反向匹配并在加载期编译。 |
| F12 | PermissionRule 使用 MatchPattern，RuleEngine 实现层级、类型、deny、声明顺序选择。 |
| F13 | events.py 生成统一 schema v1 Payload，条件和动作共享同一个冻结快照。 |
| F14 | 四个互斥动作 dataclass 与 config.py 的类型专属字段校验覆盖动作目录。 |
| F15 | actions.py 的 command runner 固定 cwd、JSON stdin、默认与范围受限超时。 |
| F16 | actions.py 的 HTTP runner 固定 JSON body/content type、10 秒超时和静态 URL/headers。 |
| F17 | Runtime prompt 队列与 HookPromptLease 实现下一请求一次性注入且不写会话历史。 |
| F18 | AgentAction 只由 actions.py 返回 placeholder，不导入或创建 Agent。 |
| F19 | actions.py 按事件解析 command 0/2 和严格 HTTP allow/deny 协议。 |
| F20 | BatchToolExecutor 把 deny 转为 source=hook 的失败工具结果，并跳过权限和工具执行。 |
| F21 | Runtime 用会话内 rule_id 集合记录 success/submitted/denied/prompt/placeholder，`/new` 重置。 |
| F22 | config.py 只允许 command/HTTP 异步并拒绝所有 tool_before 异步配置。 |
| F23 | Runtime 串行同步动作，ActionExecutor 有界提交异步动作，退出路径不等待。 |
| F24 | HookConfigLoader 在三层全部解析校验完成后才构造并返回 HookSnapshot。 |
| F25 | ActionExecutor 将所有运行异常转为 failed 诊断，Runtime 除有效 deny 外始终继续。 |
| N1 | 动作异常边界、Runtime fail-open 与唯一 deny 出口隔离 Agent 主流程。 |
| N2 | BatchToolExecutor 在启动权限判定和工具线程之前同步完成 before_tool。 |
| N3 | 固化快照顺序、串行 dispatch 和只读结果按原调用顺序分发保证确定性。 |
| N4 | HookDiagnostic 只含来源、1-based 规则序号、稳定错误码和安全消息。 |
| N5 | command/HTTP 有界读取及更小的日志和拒绝原因上限控制所有外部输出。 |
| N6 | 诊断不记录完整配置/Payload，拒绝原因经截断和敏感值清理。 |
| N7 | 动态数据只通过 command stdin 或 HTTP JSON body 传递，不提供模板引擎。 |
| N8 | 固定 daemon worker、有界队列、关闭拒绝新任务和活动进程清理控制后台资源。 |
| N9 | HookRuntime 为可选依赖，ChatSession、ToolExecutor 和临时 Agent 默认保持原路径。 |
| N10 | 共享匹配器保留旧自动 exact/glob 语义，权限回归测试固定既有判定。 |
| N11 | 文件组织列出匹配、Hook、权限、Agent、CLI、集成和端到端测试入口。 |
