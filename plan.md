# Mycode 五层权限系统 Plan

## 架构概览

权限系统位于工具注册表与工具实现之间，所有调用统一经过 `PermissionService`，避免文件工具、命令工具或旧会话入口各自实现不同的权限逻辑。

整体调用链：

```text
CLI / ChatSession / AgentRunner
  -> ToolExecutor
  -> PermissionService.authorize
  -> 黑名单检查
  -> 权限目标提取与路径沙箱
  -> 分层规则引擎
  -> 权限模式默认行为
  -> 必要时调用 ApprovalHandler
  -> 获准后执行 Tool.run
  -> 拒绝时返回结构化 ToolResult
```

模块划分：

1. `permissions.models`：定义权限模式、规则、请求、判定结果、审批选择和配置对象。
2. `permissions.blacklist`：保存不可配置的灾难性命令正则，并在命令解析或规则判断前检查原始命令。
3. `permissions.targets`：按工具提取稳定权限目标；文件路径规范化为工作区相对路径，命令保留完整命令字符串。
4. `permissions.sandbox`：强制验证文件工具路径；对命令文本中可识别的显式路径做规范化、符号链接解析和越界检查。命令运行时隐式文件访问明确不在本阶段保证范围内。
5. `permissions.rules`：负责精确/glob 匹配、同层冲突处理和“会话 > 本地 > 项目 > 用户”的跨层选择。
6. `permissions.config`：加载三层 YAML、解析模式和规则、校验未知字段，并原子更新本地永久 allow 规则。
7. `permissions.approval`：定义可注入审批协议、非交互安全拒绝实现和 CLI 终端审批实现。
8. `permissions.service`：按固定顺序编排五层判定，维护会话规则，并把审批选择转换为本次放行、会话规则或本地永久规则。
9. `tools.executor`：只负责查找工具、调用权限服务、执行已获准工具、处理超时和结构化异常；拒绝不会抛出终止 Agent Loop 的异常。

并发策略：

- 有副作用工具继续串行执行。
- 权限服务对审批和规则写入加锁，避免并发只读调用产生重叠提示或重复写入。
- 只有获准后的只读工具实现可以并发运行。

## 核心数据结构

### `PermissionMode`

`strict | default | allow`，与 Agent 的 `plan | do | default` 模式分离。

### `PermissionRule`

- `tool`：真实工具名。
- `pattern`：括号内模式。
- `effect`：`allow | deny`。
- `source`：`session | local | project | user`。
- `match_type`：`exact | glob`。

### `PermissionLayer`

- `source`：规则来源。
- `mode`：本层可选权限模式。
- `rules`：本层已校验规则。

### `PermissionRequest`

- `tool_call_id`：当前调用标识。
- `tool`：工具名。
- `target`：已规范化的权限目标。
- `arguments`：原始参数的只读引用，仅供安全检查，不直接写入拒绝消息。
- `workspace_root`：已解析的项目根目录。

### `PermissionDecision`

- `allowed`：是否允许执行。
- `reason_code`：稳定原因码，如 `blacklisted`、`sandbox_escape`、`rule_allow`、`rule_deny`、`mode_allow`、`user_denied`。
- `message`：面向用户和模型的简洁说明。
- `matched_source`：可选规则来源。
- `matched_rule`：可选命中规则。
- `target`：权限目标。

### `ApprovalChoice`

`deny | allow_once | allow_session | allow_permanent`。

### `PermissionConfigSet`

- `user`：用户层配置。
- `project`：项目层配置。
- `local`：本地层配置。
- `effective_mode`：CLI 参数优先，否则本地、项目、用户依次取首个已声明模式，最终默认 `default`。

## 核心接口

### `PermissionService`

```python
class PermissionService:
    def authorize(
        self,
        call: ToolCall,
        context: ToolContext,
    ) -> PermissionDecision: ...
```

内部固定顺序：

1. 验证工具已注册且参数可形成权限目标。
2. 对 `run_command` 检查硬黑名单。
3. 执行文件路径或命令显式路径沙箱检查。
4. 从会话、本地、项目、用户逐层寻找首个有匹配的层。
5. 无规则命中时应用权限模式。
6. `default` 模式调用审批接口。
7. 根据审批结果只放行本次，或写入会话/本地精确规则。
8. 返回最终 allow/deny，不直接执行工具。

### `PermissionTargetResolver`

```python
class PermissionTargetResolver:
    def resolve(
        self,
        tool: str,
        arguments: Mapping[str, object],
        workspace_root: Path,
    ) -> PermissionRequest: ...
```

每种已注册工具必须有明确目标解析策略；未知工具或缺失关键参数返回安全拒绝。

### `RuleEngine`

```python
class RuleEngine:
    def decide(
        self,
        request: PermissionRequest,
        layers: Sequence[PermissionLayer],
    ) -> PermissionDecision | None: ...
```

返回首个有效层的最终规则结果；没有任何规则匹配时返回 `None`。

### `ApprovalHandler`

```python
class ApprovalHandler(Protocol):
    def request(self, prompt: ApprovalPrompt) -> ApprovalChoice: ...
```

`TerminalApprovalHandler` 使用 CLI 输入；`DenyApprovalHandler` 用于无交互环境。

### `PermissionConfigLoader` / `LocalRuleStore`

```python
class PermissionConfigLoader:
    def load(self, workspace_root: Path) -> PermissionConfigSet: ...

class LocalRuleStore:
    def add_exact_allow(self, tool: str, target: str) -> None: ...
```

本地写入采用临时文件加原子替换；写入前重新读取并校验，避免覆盖当前磁盘内容。

## 模块交互

### 启动阶段

1. CLI 解析 Provider 配置和可选 `--permission-mode`。
2. 权限配置加载器依次读取：
   - `~/.mycode/permissions.yaml`
   - `<workspace>/.mycode/permissions.yaml`
   - `<workspace>/.mycode/permissions.local.yaml`
3. 每层独立校验 YAML 字段、模式、规则语法和工具名。
4. 按 CLI > 本地 > 项目 > 用户 > default 解析有效权限模式。
5. 创建终端审批器、规则存储和 `PermissionService`。
6. 将同一个权限服务注入 AgentRunner、ChatSession 和 ToolExecutor。

三层 YAML 使用统一结构：

```yaml
mode: default

allow:
  - "read_file(**)"
  - "run_command(git *)"

deny:
  - "write_file(.env)"
  - "run_command(git push *)"
```

`mode`、`allow` 和 `deny` 均可省略。不存在的可选配置文件不报错；未知字段、重复字段、无效模式、无效工具名或规则语法导致明确配置错误并安全停止。

### 单次工具调用

1. ToolExecutor 获取已注册工具。
2. 目标解析器验证参数并生成规范化权限目标。
3. `run_command` 先对原始命令和规范化命令执行不可绕过黑名单检查。
4. 沙箱检查文件工具路径或命令中的显式路径。
5. 规则引擎依次检查会话、本地、项目、用户层。
6. 规则未命中时应用有效权限模式。
7. `default` 模式调用审批器。
8. 会话或永久放行先成功写入对应规则，再允许本次调用。
9. 最终允许时调用工具；最终拒绝时直接构造 `ToolResult(ok=False, ...)`。
10. AgentRunner 按现有逻辑回写结果并进入下一轮。

## 关键安全算法

### 硬黑名单

- 黑名单模式以代码常量维护，不从 YAML 加载。
- 正则同时检查原始命令和去除多余空白后的规范化命令，采用大小写不敏感匹配。
- 模式覆盖命令前缀、复合命令片段和常见参数顺序，避免简单增加 `sudo`、空白或连接符即可绕过。
- 命中后立即返回 `blacklisted`，不进入规则、模式或审批。
- 测试只调用判定器，不实际运行危险命令。

### 文件路径沙箱

- 工作区根目录先执行 `resolve()`。
- 现有文件解析完整符号链接链；待创建文件解析其最近存在父目录及符号链接后再拼接文件名。
- 使用路径层级关系判断是否位于根目录内，不使用字符串前缀判断。
- 绝对路径、`..` 逃逸、项目外符号链接和解析失败均返回 `sandbox_escape`。
- 文件规则只接收沙箱验证后的 POSIX 风格相对路径。

### 命令显式路径检查

- 保留现有 shell 命令能力。
- 对命令词法拆分后可识别的绝对路径、`./`、`../`、`~/`、包含目录分隔符的路径参数、重定向目标和路径型选项值执行沙箱校验。
- 明确指向项目外、符号链接解析到项目外或无法规范化的显式路径拒绝执行。
- 不把可执行文件本身的系统路径当作项目文件访问目标。
- 环境变量展开、程序配置、运行库和程序内部自行访问的路径无法由本阶段完整拦截；该限制写入“已知限制与后续工作”。

### 权限目标

- `read_file`、`write_file`、`edit_file`：规范化项目相对路径。
- `run_command`：原始完整命令字符串。
- `find_files`：glob pattern。
- `search_code`：新增可选搜索范围 `path`，默认 `.`；规则只匹配该范围，不匹配 query。
- 后续新增工具必须注册权限目标解析器，否则调用安全拒绝。

### 规则解析与匹配

- 规则语法使用完整锚定解析，不接受括号外多余文本。
- 包含 `*`、`?` 或字符类的模式使用大小写敏感 glob 匹配，其余使用完整字符串相等。
- 同层先收集全部命中项，再按“精确优先、同类型 deny 优先”得出唯一结果。
- 某层只要有匹配就停止检查更低层。
- YAML 使用能检测重复键的安全加载器；未知字段和无效规则使该配置层加载失败，而不是忽略。

### 审批与规则写入

- CLI 显示工具名、经过长度限制和敏感值遮蔽的目标摘要、请求原因与四个选择。
- 本次放行不修改规则。
- 会话放行在内存层添加精确 allow。
- 永久放行在锁内重新读取本地 YAML，校验后去重追加，再通过同目录临时文件原子替换。
- 永久写入失败时不宣称成功，返回结构化失败结果。
- 无审批器、审批异常或输入无效时默认拒绝。

模式中包含 `*`、`?` 或 `[...]` 时视为 glob，否则视为精确匹配。路径统一转换为 `/` 分隔的工作区相对路径后再匹配。本会话放行和永久放行都生成当前权限目标的精确 allow 规则，不自动扩大成 glob。永久写入只向本地 YAML 的 `allow` 追加规则，已有相同规则时不重复写入，并保留原有 `mode`、`deny` 和其他 allow 规则。

## 文件组织

### 新建

- `src/mycode/permissions/__init__.py`：导出权限系统公共接口。
- `src/mycode/permissions/models.py`：权限模式、规则层、请求、决定、审批选择和配置集合。
- `src/mycode/permissions/blacklist.py`：不可配置的灾难性命令正则与匹配逻辑。
- `src/mycode/permissions/targets.py`：各工具的权限目标提取和规范化。
- `src/mycode/permissions/sandbox.py`：文件路径强制沙箱与命令显式路径检查。
- `src/mycode/permissions/rules.py`：精确/glob 匹配、同层冲突与跨层优先级。
- `src/mycode/permissions/config.py`：三层 YAML 加载、严格校验、模式解析和本地规则原子写入。
- `src/mycode/permissions/approval.py`：审批协议、终端审批器和无交互拒绝实现。
- `src/mycode/permissions/service.py`：五层判定编排、会话规则维护和审批结果处理。
- `tests/test_permissions_blacklist.py`：黑名单测试。
- `tests/test_permissions_sandbox.py`：路径沙箱测试。
- `tests/test_permissions_rules.py`：规则匹配和优先级测试。
- `tests/test_permissions_config.py`：分层配置和永久写入测试。
- `tests/test_permissions_service.py`：模式、审批和五层编排测试。

### 修改

- `src/mycode/tools/executor.py`：在工具实现前调用权限服务。
- `src/mycode/tools/search.py`：为 `search_code` 增加可选搜索范围参数，并保证范围在工作区内。
- `src/mycode/agent/executor.py`：向单个 ToolExecutor 传递同一权限服务，维持串行副作用和受控并发读取。
- `src/mycode/agent/runner.py`：接收并传递权限服务；拒绝结果继续正常回灌。
- `src/mycode/session.py`：旧会话入口同样经过权限层；未注入交互审批时安全拒绝。
- `src/mycode/cli.py`：增加权限模式参数、加载三层配置、创建终端审批器并展示权限结果。
- `src/mycode/types.py`：补充权限集成所需的类型引用或上下文字段。
- `.gitignore`：忽略 `.mycode/permissions.local.yaml`。
- `README.md`：记录配置路径、YAML 示例、三档模式、审批选项、安全边界和已知限制。
- `config.example.yaml`：仅补充权限配置位置说明；Provider 配置与权限 YAML 保持分离。
- 现有工具、Agent、CLI、配置和会话测试：更新构造方式并补充权限回归及拒绝后继续循环场景。

## 需求覆盖

- F1、F14-F18：统一 PermissionService、审批接口、ToolExecutor 和 Agent Loop 集成。
- F2-F3：blacklist 模块与不可覆盖的首层判定。
- F4-F5：sandbox 模块、符号链接解析和命令显式路径检查。
- F6-F9：targets、rules、三层配置和会话规则。
- F10-F13：独立 PermissionMode、CLI 覆盖、审批范围和本地写入。
- F19：严格 YAML 校验、启动错误和 fail-closed 行为。
- N1-N10：纯判定模块、锁、原子写入、结构化结果、回归测试和文档说明。

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 权限拦截位置 | ToolExecutor 前置统一拦截 | 覆盖 AgentRunner 和旧 ChatSession，避免旁路 |
| 黑名单来源 | 代码内只读正则常量 | 保证配置和审批无法覆盖 |
| 路径边界判断 | `Path.resolve` 后使用层级关系 | 防止字符串前缀和符号链接逃逸 |
| 命令兼容性 | 保留 shell，检查可识别显式路径 | 保留现有能力，同时落实本阶段可验证边界 |
| 规则格式 | YAML 的 `allow` / `deny` 字符串列表 | 直接符合 `工具名(模式)` 约定 |
| glob 实现 | 大小写敏感匹配 | 与命令和 POSIX 路径语义一致且可预测 |
| 模式来源 | CLI > 本地 > 项目 > 用户 > default | 支持本次显式切换和分层默认 |
| 默认审批 | 无交互时拒绝 | 满足 fail-closed |
| 会话状态 | 进程内精确规则 | 生命周期清晰且不污染磁盘 |
| 永久状态 | 本地 YAML 原子追加 | 不影响团队和用户全局配置 |
| 拒绝传播 | `ToolResult(ok=False)` | 复用现有回灌机制，不新增停止条件 |
| 并发 | 审批和规则写入加锁，获准只读工具再并发 | 避免交互和持久化竞态 |

## 已知限制与后续工作

本阶段不提供操作系统级文件访问隔离。命令工具会拦截可识别的显式越界路径，但程序通过环境变量、用户配置、运行库或内部逻辑产生的隐式项目外访问，只有引入 OS 沙箱或容器后才能可靠限制。该强化项不在本阶段实现，不得在文档中宣称命令工具已经具备完整运行时文件系统隔离。
