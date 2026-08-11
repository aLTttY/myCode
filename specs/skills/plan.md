# MyCode Skill 系统 Plan

## 架构概览

### 1. Skill Catalog

新增独立的 `skills` 包负责三级目录扫描、Markdown/frontmatter 解析、目录工具解析、优先级合并和校验。Catalog 每次生成不可变快照，包含生效定义、诊断信息、资源指纹和专属工具元数据。

启动时，先完成内置工具与 MCP 工具发现，再校验 Skill 白名单；这样依赖未成功连接 MCP 的 Skill 会按规格立即报错。

### 2. Skill Runtime

运行时协调器持有当前 Catalog 快照、共享 Skill 激活顺序和对应专属工具。它统一处理：

- `load_skill` 调用；
- 共享 Skill 激活与去重；
- 白名单并集；
- `/new` 清理；
- 热更新后的替换、停用和诊断；
- 共享与独立执行分流。

Catalog 只描述“有哪些能力”，Runtime 管理“当前会话用了哪些能力”。

### 3. Prompt 与工具投影

每次 Agent 请求不直接使用全局工具目录，而由 Runtime 生成本轮工具投影：

```text
无共享 Skill：现有完整业务工具 + load_skill
有共享 Skill：激活白名单并集 + 对应专属工具 + load_skill
Plan Mode：上述结果再与只读工具求交集 + load_skill
```

提示构建器接收两个独立区块：

- 未加载 Skill 目录：仅名称和说明；
- 已激活 Skill：完整静态 SOP，按激活顺序置于高优先级动态环境区。

参数始终留在 user 消息中；SOP 里的 `{{input}}` 编译为受控引用标记。

### 4. 专属工具适配器

每个目录工具被包装为普通 MyCode Tool，但实际调用通过无 shell 的 Python 子进程执行。适配器负责 JSON stdin/stdout、路径约束、超时终止、输出截断和错误净化。

专属工具统一按有副作用工具分类，权限目标为 `call`。权限服务增加动态专属工具集合，但白名单不会绕过现有审批。

### 5. 独立执行器

独立执行器复用现有 Agent Loop 组件，但创建临时上下文，不挂接主 SessionJournal 或长期记忆 Worker。

它从主上下文提取最近 N 个已完成轮次，排除当前未完成工具轮次；仅注入选中 Skill、其工具投影和本次 user 输入。独立模式指定模型时，以当前配置复制出只修改 `model` 的 Provider。

最终 assistant 文本直接作为回流摘要；失败则生成确定性失败摘要。外层独立上下文可以临时激活共享 Skill，但拒绝再次启动独立 Skill。

### 6. 命令与热更新桥接

固定命令和动态 Skill 命令仍通过统一命令目录分发。命令目录增加原子替换动态项的能力，使帮助、路由和补全始终看到同一快照。

CLI 在显示下一次输入提示前刷新 Catalog：

1. 扫描资源指纹；
2. 无变化则复用快照；
3. 有变化则解析并构建候选快照；
4. 原子更新 Runtime、命令目录和权限动态工具集合；
5. 输出警告及停用通知。

`/review` 从固定命令移除，由动态 `review` Skill 注册；`/rev` 作为该名称的固定兼容别名。

## 核心数据结构

### `SkillDefinition`

```python
@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    allowed_tools: tuple[str, ...]
    mode: Literal["shared", "isolated"]
    history: int | None
    model: str | None
    sop: str
    compiled_sop: str
    source: Literal["project", "user", "builtin"]
    source_id: str
    package_root: Path | None
    dedicated_tools: tuple[SkillToolDefinition, ...]
    fingerprint: str
```

`compiled_sop` 把每个 `{{input}}` 替换为固定的 user 输入引用标记，不包含实际参数。`source_id` 用于诊断和帮助输出，不暴露正文。

### `SkillToolDefinition`

```python
@dataclass(frozen=True)
class SkillToolDefinition:
    local_name: str
    exposed_name: str
    description: str
    parameters: dict[str, object]
    script_path: Path
    fingerprint: str
```

实际工具名固定为 `<skill-name>__<local-name>`。schema 和脚本必须位于能力包目录内，不接受绝对路径、符号链接或目录逃逸。

### `SkillSnapshot`

```python
@dataclass(frozen=True)
class SkillSnapshot:
    definitions: Mapping[str, SkillDefinition]
    dedicated_tools: Mapping[str, SkillToolDefinition]
    diagnostics: tuple[SkillDiagnostic, ...]
    fingerprint: str
```

所有映射只读。Catalog 完整构建并校验候选快照后才一次性发布，避免提示、命令和工具看到不同版本。

### `ActiveSkill`

```python
@dataclass(frozen=True)
class ActiveSkill:
    name: str
    activated_fingerprint: str
    order: int
```

运行时不复制 SOP，而是按名称回查最新 Snapshot。这样合法热更新会立即替换内容；定义失效或模式变化时可以准确停用。

### `SkillInvocation` 与 `IsolatedSkillResult`

```python
@dataclass(frozen=True)
class SkillInvocation:
    name: str
    input_text: str
    origin: Literal["slash", "agent"]
    runtime_mode: Literal["default", "plan"]

@dataclass(frozen=True)
class IsolatedSkillResult:
    status: Literal["completed", "failed", "cancelled"]
    summary: str
    token_usage: TokenUsage | None
```

## 核心接口

### `SkillCatalog`

```python
class SkillCatalog:
    def load_initial(
        self,
        workspace_root: Path,
        known_tools: Collection[str],
        reserved_commands: Collection[str],
    ) -> SkillSnapshot: ...

    def refresh(
        self,
        current: SkillSnapshot,
        known_tools: Collection[str],
        reserved_commands: Collection[str],
    ) -> SkillRefreshReport: ...
```

`load_initial` 对同层重名、命令冲突和未知白名单工具抛出启动错误；普通解析错误进入 diagnostics。`refresh` 隔离问题定义并返回新快照、停用列表和警告，不终止进程。

### `SkillRuntime`

```python
class SkillRuntime:
    @classmethod
    def for_isolated(
        cls,
        snapshot: SkillSnapshot,
        execution_skill: SkillDefinition,
    ) -> SkillRuntime: ...
    def publish(self, snapshot: SkillSnapshot) -> SkillRuntimeUpdate: ...
    def activate_shared(self, name: str) -> SkillActivation: ...
    def active_definitions(self) -> tuple[SkillDefinition, ...]: ...
    def catalog_prompt(self) -> str: ...
    def active_prompt(self) -> tuple[str, ...]: ...
    def project_registry(
        self,
        base_registry: ToolRegistry,
        runtime_mode: RuntimeMode,
    ) -> ToolRegistry: ...
    def reset(self) -> None: ...
```

内部使用锁保护 Snapshot 发布与激活集合。主 Runtime 没有 `execution_skill`；临时 Runtime 把当前独立 Skill 固定为执行根能力，并允许额外激活共享 Skill。工具投影先合并执行根能力与共享白名单，再应用 Plan Mode；`load_skill` 无条件加入。

### `LoadSkillTool`

```python
class LoadSkillTool:
    # schema 只接收 name
    def run(self, arguments, context) -> ToolResult: ...
```

该工具由 `AgentRunner` 创建，因此可以读取当前请求和主上下文：

- 目标为共享 Skill：只激活，下一 Agent 迭代看到 SOP 与新工具。
- 目标为独立 Skill：以当前 user 请求作为 Skill 输入，同步运行临时 Agent，并把最终摘要作为工具结果返回。
- 已处于独立执行时再次请求独立 Skill：返回嵌套禁止错误。

`load_skill` 被归类为串行系统工具，由权限服务直接允许；它本身不执行文件、命令或网络业务动作。

### `SkillScriptTool`

```python
class SkillScriptTool:
    def run(
        self,
        arguments: Mapping[str, object],
        context: ToolContext,
    ) -> ToolResult | ToolExecutionResult: ...
```

适配器使用 `sys.executable <script.py>`，工作目录固定为 workspace；JSON stdin 包含参数和工作区路径。它负责终止超时子进程、限制 stdout/stderr、验证唯一 JSON 输出，并把失败转成安全结果。

### `IsolatedSkillRunner`

```python
class IsolatedSkillRunner:
    def run(
        self,
        invocation: SkillInvocation,
        definition: SkillDefinition,
        history: Sequence[Message],
        cancellation: CancellationToken,
    ) -> IsolatedSkillResult: ...
```

内部创建无 SessionJournal、无 MemoryWorker 的临时 `AgentRunner`。指定模型时用 `dataclasses.replace(app_config, model=...)` 创建临时 Provider；上下文窗口继续采用当前配置的保守上限。

`AgentRunner` 只依赖定义在 `skills.models` 中的 `IsolatedSkillExecutor` Protocol，不导入具体 `skills.isolated` 模块；具体执行器可以反向复用 `AgentRunner`，从而保持单向可导入依赖。

### `ContextManager.recent_complete_turns`

```python
def recent_complete_turns(self, limit: int) -> tuple[Message, ...]: ...
```

以 user 消息为轮次起点，包含其后的 assistant 和完整工具结果，排除当前仍等待工具结果的未完成轮次，再从尾部取 N 轮。

### `CommandRegistry.replace_dynamic`

```python
def replace_dynamic(self, commands: Sequence[CommandSpec]) -> None: ...
```

在锁内先构建并校验“固定命令 + 动态 Skill 命令”的完整索引，再一次替换。`CommandSpec` 增加安全帮助元信息，Skill handler 统一调用 `CommandUI.invoke_skill(name, arguments)`。

### `AgentRunner` 扩展

```python
def invoke_skill(
    self,
    invocation: SkillInvocation,
    cancellation: CancellationToken | None = None,
) -> Iterator[AgentEvent]: ...

def append_external_turn(
    self,
    user_text: str,
    assistant_text: str,
) -> None: ...
```

共享斜杠调用先激活再进入现有 `run`；独立斜杠调用运行临时 Agent 后，通过 `append_external_turn` 只记录调用与摘要。Agent 内部调用独立 Skill 则由 `load_skill` 的工具调用和摘要结果自然进入当前轮次。

## 模块交互

### 启动流程

```text
读取配置并创建主 Provider
  → 注册现有内置工具
  → 发现并注册 MCP 工具
  → 创建固定命令目录（不再包含 review）
  → 扫描并解析三级 Skill
  → 合并优先级并校验保留命令、白名单、专属工具
  → 用全局工具和生效专属工具加载权限配置
  → 创建 SkillRuntime
  → 创建 AgentRunner 并注册 load_skill
  → 原子注册动态 Skill 命令
  → 恢复会话历史，但保持 Skill 激活集合为空
  → 进入交互循环
```

Skill 白名单校验放在 MCP 发现后；权限配置装配放在 Skill 发现后，使专属工具规则能够被识别。

### 普通消息触发共享 Skill

```text
用户普通消息
  → AgentRunner 构建提示和当前工具投影
  → 模型从名称/说明判断需要 Skill
  → 调用 load_skill(name)
  → SkillRuntime 激活共享 Skill
  → load_skill 返回激活确认
  → 下一次 Agent 迭代重建提示
      - 注入完整 SOP
      - 收窄为激活白名单并集
      - 加入专属工具
  → 模型继续处理原始用户请求
  → 全部消息留在主历史
```

`load_skill` 只接收名称。模型调用时，本轮原始 user 消息就是 `{{input}}` 所引用的输入，避免在工具结果之间插入新的 user 消息破坏 Provider 消息顺序。

### 斜杠调用共享 Skill

```text
/<skill> arguments
  → 命令路由识别动态 Skill
  → SkillRuntime 激活
  → 把“Skill 名称 + arguments”构造成 user 级调用消息
  → 进入现有 AgentRunner.run
  → SOP 与工具投影从第一次模型请求起生效
  → 调用、回复和工具结果写入主 Journal 与 ContextManager
```

原始斜杠字符串不保存；保存的是可识别的 Skill 调用 user 消息及原始参数。

### 斜杠调用独立 Skill

```text
/<isolated-skill> arguments
  → 从主 ContextManager 提取最近 N 个已完成轮次
  → 创建临时 Provider（可选模型覆盖）
  → 创建临时 SkillRuntime 和 AgentRunner
      - 无 SessionJournal
      - 无 MemoryWorker
      - 仅选中 Skill 的 SOP 与工具
  → 以 arguments 作为独立 user 输入运行
  → 缓冲中间模型文本，只显示简洁进度
  → 取得最终 assistant 摘要或确定性失败摘要
  → 关闭临时上下文
  → 主 AgentRunner.append_external_turn(调用, 摘要)
  → CLI 显示摘要
```

主会话已有共享 Skill 的激活状态在整个过程中保持不变。

### Agent 调用独立 Skill

```text
主 Agent 调用 load_skill(isolated-name)
  → LoadSkillTool 读取当前 user 请求
  → 提取当前请求之前最近 N 个已完成轮次
  → 同步运行独立执行器
  → 摘要作为 load_skill 的 ToolResult 回灌
  → 主 Agent 继续当前轮次并生成最终回复
```

独立内部工具调用不会进入主历史；主历史只看到 `load_skill` 调用及其摘要结果。

### 独立上下文内继续加载

```text
独立 Agent 调用 load_skill(shared-name)
  → 只在临时 Runtime 激活共享 Skill
  → 后续独立迭代使用白名单并集

独立 Agent 调用 load_skill(isolated-name)
  → 返回 nested_isolated_not_supported
  → 外层 Agent 可继续或结束
```

### 热更新流程

```text
CLI 准备显示下一次输入提示
  → Catalog 比较资源状态指纹
  → 无变化：直接复用 Snapshot
  → 有变化：完整构建候选 Snapshot
      - 解析错误：跳过单个定义
      - 运行期同层冲突或未知工具：隔离对应名称
      - 其余合法更新继续进入候选快照
  → 原子发布 Snapshot
  → Runtime 对比旧、新来源
      - 同一来源内容修改：保持激活并使用新内容
      - 新增更高优先级覆盖：保持激活并切换新定义
      - 当前来源删除后降级到低优先级：停用
      - 定义非法、消失或变为 isolated：停用
  → 原子替换动态命令
  → 更新权限服务的动态专属工具集合
  → 输出解析、冲突和停用通知
```

独立执行开始时固定使用当时的 Snapshot；执行途中发生的文件变化只影响下一次调用，避免一次执行混用两个版本。

## 文件组织

### 新增 Skill 核心模块

| 文件 | 职责 |
|---|---|
| `src/mycode/skills/__init__.py` | 导出 Skill 公共类型与构造入口 |
| `src/mycode/skills/models.py` | 定义 Skill、专属工具、快照、诊断、调用及结果模型 |
| `src/mycode/skills/parser.py` | 严格解析 Markdown frontmatter、SOP 和工具 YAML |
| `src/mycode/skills/catalog.py` | 三级扫描、优先级合并、初始校验、资源指纹和热更新快照 |
| `src/mycode/skills/runtime.py` | 管理激活集合、提示投影、工具白名单并集、发布与重置 |
| `src/mycode/skills/tools.py` | 实现 `load_skill` 和 Python 子进程专属工具适配器 |
| `src/mycode/skills/isolated.py` | 提取输入、构建临时 Agent、模型覆盖、摘要与清理 |
| `src/mycode/skills/commands.py` | 把 Snapshot 转换为动态 `CommandSpec` |
| `src/mycode/skills/builtins/__init__.py` | 提供内置资源读取入口 |
| `src/mycode/skills/builtins/commit.md` | 共享 commit 样板 |
| `src/mycode/skills/builtins/review.md` | `history: 0` 的独立只读 review 样板 |
| `src/mycode/skills/builtins/test.md` | 共享 test 样板 |

### 修改现有模块

| 文件 | 改动 |
|---|---|
| `src/mycode/cli.py` | 调整启动顺序，装配 Catalog/Runtime，刷新热更新，执行 Skill 命令 |
| `src/mycode/agent/runner.py` | 注入 Skill 提示与工具投影，注册 loader，支持直接调用与外部摘要回写 |
| `src/mycode/agent/tools.py` | Plan Mode 投影保留 `load_skill`，其余仍只保留只读工具 |
| `src/mycode/prompts/modules.py` | 分离 Skill 目录与激活 SOP，并把激活区放在可选系统提示首位 |
| `src/mycode/context/manager.py` | 提供最近 N 个完整已完成轮次的只读提取 |
| `src/mycode/tools/registry.py` | 增加名称枚举、包含判断、子集复制与无覆盖合并 |
| `src/mycode/tool_safety.py` | 明确 `load_skill` 为串行系统工具；未知专属工具仍默认有副作用 |
| `src/mycode/permissions/targets.py` | 将当前专属工具映射为 `call` 权限目标 |
| `src/mycode/permissions/service.py` | 自动允许 `load_skill`，支持原子更新动态专属工具名 |
| `src/mycode/commands/models.py` | 增加动态来源和安全帮助元信息 |
| `src/mycode/commands/interfaces.py` | 增加 `invoke_skill` UI 能力 |
| `src/mycode/commands/registry.py` | 支持固定项与动态项的加锁原子替换 |
| `src/mycode/commands/builtins.py` | 移除固定 review，实现动态 Skill 帮助展示 |
| `src/mycode/commands/__init__.py` | 导出新增接口 |
| `pyproject.toml` | 把内置 Markdown 声明为包资源 |
| `README.md` | 记录格式、目录、优先级、执行模式、命令和工具协议 |

### 新增测试

| 文件 | 主要覆盖 |
|---|---|
| `tests/test_skill_parser.py` | frontmatter、正文、严格字段、工具 schema 和路径安全 |
| `tests/test_skill_catalog.py` | 三级覆盖、解析隔离、冲突、白名单、资源指纹和热更新 |
| `tests/test_skill_runtime.py` | 激活顺序、去重、并集、更新、降级停用和重置 |
| `tests/test_skill_tools.py` | loader、名称空间、JSON 子进程、审批、超时、输出限制 |
| `tests/test_skill_isolated.py` | 历史轮次、临时 Agent、模型覆盖、摘要、失败与嵌套拒绝 |
| `tests/test_skill_commands.py` | 动态注册、帮助、补全、覆盖和 `/rev` |
| `tests/test_skill_integration.py` | 共享与独立端到端场景、会话边界和现有系统集成 |

现有 Agent、CLI、Prompt、Context、Permission、Provider、MCP 和 Command 测试同步补充回归断言。

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| frontmatter 解析 | `yaml.safe_load`，仅接受映射 | 复用现有依赖，禁止任意对象构造 |
| 字段策略 | 必填字段和未知字段均严格校验 | 尽早暴露拼写与配置错误 |
| Skill 名称 | 复用现有小写斜杠命令规则 | 保证名称、命令和帮助一致 |
| 工具 manifest | `name`、`description`、`parameters`、`script` 四字段 | 最小且足够描述一个工具 |
| 参数 schema | 要求顶层 JSON Schema 为 `type: object` | 与三个 Provider 的工具协议兼容 |
| 专属工具命名 | 自动 `<skill>__<local>` | 支持多 Skill 组合且避免冲突 |
| 脚本执行 | 当前 Python 的独立子进程，无 shell | 支持热更新、强制终止和主进程故障隔离 |
| 子进程环境 | 最小环境变量、workspace cwd、受限 JSON 上下文 | 避免默认把 API Key 等凭据传给脚本 |
| 输出读取 | 有界读取 stdout/stderr，超限或超时终止进程 | 防止内存无界增长并满足安全错误要求 |
| Catalog 状态 | 不可变 Snapshot，完整构建后原子发布 | 命令、提示和工具始终保持同一版本 |
| 热更新检测 | 每轮前比较路径、大小和纳秒修改时间；变化后计算内容摘要 | 无常驻监听且避免无变化时重复解析 |
| 启动错误 | 语法类单文件隔离；目录冲突、保留命令和有效白名单错误终止 | 对应 spec 的容错与立即失败边界 |
| 运行期错误 | 隔离问题名称，继续发布其余合法定义 | 不让单个热更新破坏交互进程 |
| 激活更新 | 同源修改和更高优先级覆盖热替换；降级回退停用 | 同时满足立即更新与不静默切换低优先级定义 |
| 参数占位 | SOP 编译为固定引用，原文只存在于 user 消息 | 保持提示角色安全边界 |
| 白名单组合 | 激活 Skill 白名单并集，再应用运行模式限制 | 支持多 Skill 协作且不绕过 Plan Mode |
| Loader 权限 | 始终可见、系统自动允许、串行执行 | loader 只做能力选择，业务副作用仍单独审批 |
| 专属工具权限 | 全部为 side-effect，目标固定 `call` | 不信任能力包自报只读属性 |
| 独立执行 | 复用临时 `AgentRunner`，不挂主日志和记忆 | 最大化复用 Provider、Agent Loop、权限与取消机制 |
| 依赖反转 | AgentRunner 依赖独立执行 Protocol，具体 isolated 模块依赖 AgentRunner | 避免 Agent 与 Skill 执行器循环导入 |
| 独立摘要 | 最终 assistant 文本直接回流 | 少一次模型调用并降低失败面 |
| 模型覆盖 | `replace(AppConfig, model=...)` 后创建临时 Provider | 不引入新的凭据或 Provider 路由 |
| 历史复制 | 仅复制最近 N 个完整已完成 user 轮次 | 保持协议合法且不复制当前半完成工具链 |
| Snapshot 边界 | 独立执行开始时固定版本 | 避免一次任务混用热更新前后内容 |
| 会话恢复 | 恢复消息但不恢复激活状态 | 对应 Skill 生命周期范围 |
| 内置资源 | `importlib.resources` + setuptools package data | 安装包和源码运行方式都能读取样板 |

## 需求覆盖

| Spec 范围 | 设计覆盖 |
|---|---|
| F1–F10 | Parser、Catalog、严格 schema、三级覆盖、命名空间和安全参数绑定 |
| F11–F18 | Runtime、Prompt 投影、LoadSkillTool、白名单并集和专属工具适配器 |
| F19–F23 | IsolatedSkillRunner、完整轮次提取、临时 Provider 和摘要回流 |
| F24–F32 | 动态 CommandRegistry、CLI 刷新和不可变 Snapshot 发布 |
| F33–F36 | 三个包内 Markdown 样板及端到端测试 |
| N1–N15 | 原子快照、角色边界、权限映射、进程隔离、错误净化和回归测试 |
