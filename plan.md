# Mycode 专用只读工具自动执行 Plan

## 架构概览

保留 `ToolExecutor` 作为所有工具的统一执行入口，并在现有权限服务中增加一条集中、可测试的专用只读快速路径。快速路径只覆盖 `read_file`、`find_files`、`search_code`，先完成参数和工作区边界校验，再立即返回允许结果，不进入权限规则、权限模式或人工审批。

```text
AgentRunner / ChatSession
  -> ToolExecutor
  -> PermissionService.authorize
       -> 提取并校验工具目标
       -> 专用只读工具？
            是：readonly_allow，跳过规则、模式和审批
            否：继续黑名单、路径沙箱、规则、模式和审批
  -> 获准后执行 Tool.run
  -> 返回结构化 ToolResult
```

`run_command` 始终属于有副作用工具。系统不分析 shell 命令是否“看起来只读”，因此 `ls`、`pwd`、`cat`、`rg` 和 Git 查看命令仍按现有权限流程处理。

并发语义保持不变：专用只读工具可以并发；写入、编辑和终端命令串行判定与执行。

default 模式需要用户确认时，CLI 使用 `prompt_toolkit` 渲染三选项内联菜单：上、下方向键移动高亮，回车确认。菜单不接受字母快捷键，不提供永久同意，也不写入权限配置。

## 核心数据结构

### `READ_TOOLS`

集中定义自动执行工具集合：

```python
READ_TOOLS = frozenset({"read_file", "find_files", "search_code"})
```

该集合同时供 Agent 工具分批、Plan Mode 工具注册表和权限服务使用，避免多处名单漂移。未知工具及 `run_command` 默认归为有副作用工具。

### `PermissionDecision`

沿用现有结构，新增稳定原因码：

```text
readonly_allow
```

它表示专用只读工具已通过目标校验并自动执行。该决定不记录匹配规则，也不调用审批器。

现有 `blacklisted`、`sandbox_escape`、`rule_allow`、`rule_deny`、`mode_allow`、`mode_deny` 和人工审批原因码保持不变。

### `ApprovalChoice`

审批结果缩减为：

```python
ApprovalChoice = Literal["deny", "allow_once", "allow_session"]
```

删除 `allow_permanent`。本地 YAML 中的手工规则仍通过配置加载器进入 `PermissionConfigSet.local`，不依赖交互审批结果。

### `ApprovalMenuOption`

方向键菜单使用固定的展示标签和内部值：

```text
不同意       -> deny
仅本次同意   -> allow_once
本会话同意   -> allow_session
```

默认高亮“不同意”，防止用户直接按回车时意外授权。

## 核心接口

### 工具安全分类

新增独立的共享分类模块：

```python
READ_TOOLS: frozenset[str]

def classify_tool(name: str) -> Literal["read", "side_effect"]: ...

def is_read_tool(name: str) -> bool: ...
```

`agent.tools` 不再维护自己的只读名单，而是复用共享分类。权限服务也只从该模块读取名单，避免权限层反向依赖 Agent 编排模块。

### `PermissionService.authorize`

接口保持不变：

```python
def authorize(self, call: ToolCall, context: ToolContext) -> PermissionDecision: ...
```

内部顺序调整为：

1. 通过目标解析器校验工具名、必需参数和工作区目标。
2. 如果工具属于 `READ_TOOLS`，立即返回 `readonly_allow`。
3. 如果是 `run_command`，执行不可覆盖黑名单和显式路径沙箱检查。
4. 对写入、编辑和终端命令执行会话、本地、项目、用户规则匹配。
5. 规则未命中时应用 strict、default 或 allow 模式。
6. default 模式仅对受控工具调用人工审批。

只读快速路径位于规则、模式和审批之前，因此历史 `read_file(...)`、`find_files(...)`、`search_code(...)` allow/deny 规则不会影响执行；配置格式仍兼容，不要求用户立刻清理旧规则。

目标解析失败不会进入快速路径，确保“自动执行”不等于绕过路径边界。

收到审批结果后只处理三种分支：拒绝、仅本次允许、写入内存会话规则。权限服务不再接收本地规则写入器，也不存在审批后持久化分支。

### `TerminalApprovalHandler`

接口保持为：

```python
def request(self, approval: ApprovalPrompt) -> ApprovalChoice: ...
```

实现使用 `prompt_toolkit` 的非全屏 `Application`、`FormattedTextControl` 和 `KeyBindings`：

- 上方向键选择前一项，下方向键选择后一项；边界处循环选择。
- 回车返回当前高亮项。
- 初始项固定为“不同意”。
- `Ctrl+C`、`Ctrl+D`、EOF、非 TTY 或菜单异常返回 `deny`。
- 普通字母不绑定任何审批动作，不会提交选择。
- 菜单结束后清理临时渲染，保留工具、目标、原因和最终选择的可读输出。

菜单选择逻辑与审批文案分离，并允许注入输入/输出或选择器，便于在测试中用虚拟终端发送方向键序列，不依赖真实人工输入。

## 模块设计

### `tool_safety`

**职责：** 集中声明工具安全分类。

**对外接口：** `READ_TOOLS`、`classify_tool()`、`is_read_tool()`。

**依赖：** 仅依赖标准库类型，不依赖 Agent 或权限模块，避免循环依赖。

### `permissions.service`

**职责：** 在目标校验后对专用只读工具自动放行；其余工具继续执行现有权限链。

**约束：**

- 不根据命令字符串推断 `run_command` 为只读。
- 不调用只读工具对应的规则、模式或审批器。
- 不改变黑名单、路径沙箱和受控工具的判定顺序。
- 自动放行仍返回结构化决定，便于测试和诊断。
- 审批结果只产生本次授权或进程内会话规则，不写入磁盘。

### `permissions.approval`

**职责：** 展示审批上下文并运行三选项方向键菜单。

**约束：**

- 菜单标签固定为“不同意、仅本次同意、本会话同意”。
- 默认选择和所有异常降级均为拒绝。
- 不保留 `d/o/s/p` 字母解析循环。
- 不提供“永久同意”标签、值或隐藏快捷键。

### `permissions.config`

**职责：** 继续加载用户、项目、本地 YAML。`.mycode/permissions.local.yaml` 仍由用户手工维护并参与“本地 > 项目 > 用户”的规则优先级。

交互审批不调用 `LocalRuleStore`。现有本地规则解析能力保持不变；是否保留内部写入辅助类不影响 CLI，但不得从审批链路调用。

### `permissions.targets` 与 `permissions.sandbox`

**职责：** 在只读快速路径之前完成输入目标验证。

- `read_file`：规范化工作区相对路径，拒绝绝对路径、越界路径和项目外符号链接。
- `find_files`：拒绝绝对或包含 `..` 的查找模式。
- `search_code`：规范化搜索范围，拒绝绝对路径、越界路径和项目外符号链接。
- 写入、编辑和命令目标校验保持现状。

### `tools.search`

**职责：** 保证递归查找和代码搜索不会通过工作区内的符号链接读取项目外文件。

遍历候选文件时解析真实路径，并确认真实路径仍位于工作区根目录内。项目外符号链接不返回、不读取。这样即使只读工具跳过权限规则，也仍满足工作区边界要求。

### `agent.tools` 与 `agent.executor`

**职责：** 复用共享安全分类并保留批量执行语义。

- Plan Mode 仍只暴露三个专用只读工具。
- 相邻只读调用仍可并发执行。
- `run_command`、`write_file`、`edit_file` 仍串行执行。
- 并发只读调用不会触发审批锁或终端提示。

### `tools.executor`

**职责：** 保持统一入口：先获取已注册工具，再调用权限服务，最后执行工具实现。

不在执行器中复制只读名单或绕过权限服务，以保证参数验证、结构化结果和所有入口行为一致。

## 模块交互

### 合法专用只读调用

```text
read_file("README.md")
  -> 注册表确认工具存在
  -> 目标解析并确认位于工作区
  -> 命中 READ_TOOLS
  -> readonly_allow
  -> 读取文件并返回结果
```

不会读取 YAML 权限规则的判定结果，不应用 strict/default/allow，也不会调用审批器。

### 越界专用只读调用

```text
read_file("../secret.txt")
  -> 目标解析失败
  -> sandbox_escape
  -> 工具实现不执行
```

### 终端查看命令

```text
run_command("ls -la")
  -> 不属于 READ_TOOLS
  -> 黑名单与命令路径检查
  -> 规则匹配
  -> default 模式无规则时请求审批
```

### 受控写入调用

`write_file` 和 `edit_file` 沿用现有路径沙箱、规则、权限模式和审批流程；拒绝结果继续回灌 Agent Loop。

### 方向键审批

```text
[permission] 工具：run_command
[permission] 目标：ls -la
[permission] 原因：没有权限规则明确允许或拒绝此调用。

  > 不同意
    仅本次同意
    本会话同意
```

下方向键移动高亮，回车确认。若用户直接回车、取消、输入结束或终端不支持交互，结果均为拒绝。确认“本会话同意”时只更新当前 `PermissionService` 的内存规则。

## 文件组织

### 新建

- `src/mycode/tool_safety.py`：共享只读工具集合和安全分类函数；位于顶层以避免权限模块导入 `tools` 包时触发执行器循环依赖。

### 修改

- `src/mycode/agent/tools.py`：复用共享分类，移除重复名单。
- `src/mycode/permissions/service.py`：目标校验后增加 `readonly_allow` 快速路径。
- `src/mycode/permissions/models.py`：从 `ApprovalChoice` 删除 `allow_permanent`。
- `src/mycode/permissions/approval.py`：用三选项方向键菜单替换字母输入循环。
- `src/mycode/cli.py`：接入菜单审批器，移除审批链路中的 `LocalRuleStore`。
- `src/mycode/tools/search.py`：过滤解析到工作区外的符号链接候选文件。
- `tests/test_permissions_service.py`：覆盖三种模式、deny 规则、无审批器下的只读自动执行，以及 `run_command("ls -la")` 仍受控。
- `tests/test_tool_executor.py`：证明只读调用直接执行，受控工具拒绝时仍不进入工具实现。
- `tests/test_agent_executor.py`：证明多个只读调用并发且不触发审批，副作用工具仍串行。
- `tests/test_agent_tools.py`：验证共享分类和 Plan Mode 只读集合。
- `tests/test_permissions_sandbox.py`、`tests/test_tools_search.py`：覆盖只读绝对路径、`..` 和项目外符号链接。
- `tests/test_session_tools.py`、`tests/test_agent_runner.py`：覆盖无审批入口和 Agent Loop 集成。
- `tests/test_cli.py`：覆盖上下方向键、回车、默认拒绝、字母不提交、取消/EOF/非交互拒绝，以及无永久选项。
- `tests/test_permissions_config.py`：确认手工本地 allow/deny 规则仍可加载并作用于受控工具。
- `README.md`、`config.example.yaml`：说明专用只读工具自动执行、历史只读规则不生效，以及 `run_command` 仍受控。

`permissions.blacklist`、`permissions.rules` 和权限配置层级原则上不修改，只运行回归测试确认行为不变。交互式永久持久化逻辑从模型、服务和 CLI 链路移除；手工本地规则加载逻辑保留。

## 需求覆盖

- F1-F2、AC1-AC3：共享只读分类、目标预校验、只读快速路径和符号链接测试。
- F3-F4、AC4-AC5：受控工具保留完整权限链，`run_command` 永不进入只读快速路径。
- F5-F8、AC6-AC10：复用黑名单和路径沙箱，并运行既有不可覆盖测试。
- F9-F14、AC11-AC16：只读规则被快速路径跳过；受控工具继续使用现有规则和模式。
- F15-F20、AC17-AC23：三选项方向键菜单、默认拒绝、无字母提交、无交互式持久化，并保留手工本地规则加载。
- F21-F24、AC24-AC30：保留结构化回灌、迭代收尾、配置校验、并发和完整回归测试。
- N1-N12：集中分类、无 Provider 耦合、只读路径边界不降级、终端异常 fail closed、受控工具保护不回退。

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 自动执行范围 | 固定三个专用工具 | 与批准的方案 A 一致，边界清晰 |
| 自动放行位置 | `PermissionService` 目标校验之后 | 所有入口一致，同时保留参数和工作区保护 |
| 共享分类 | 独立顶层 `tool_safety` 模块 | 避免重复名单，也避免权限模块通过 `tools.__init__` 反向导入执行器 |
| 历史只读规则 | 保持可解析，但执行时忽略 | 满足直接执行并保持配置兼容 |
| Shell 查看命令 | 继续视为有副作用 | 不引入不可靠的 shell 语义识别 |
| 自动放行结果 | 返回 `readonly_allow` | 保持工具执行可观察、可测试 |
| 搜索符号链接 | 解析后限制在工作区 | 防止自动执行扩大读取边界 |
| 并发 | 三个专用工具可并发 | 保留现有性能和调度语义 |
| 菜单实现 | 复用现有 `prompt_toolkit` 构建非全屏方向键菜单 | 无需新增依赖，与当前 CLI 输入栈一致 |
| 默认高亮 | 不同意 | 直接回车和误操作保持 fail closed |
| 交互选择 | 上下方向键移动、回车确认 | 符合 Claude Code 风格，不再输入字母 |
| 永久授权 | 从交互类型、服务分支和 CLI 接线中删除 | 防止一次交互形成长期授权 |
| 本地规则 | 保留 YAML 手工加载 | 满足用户仍可显式维护本地策略的要求 |

## 已知限制

本阶段不判断通用终端命令是否只读，因此用户通过 `run_command` 查看文件仍可能收到审批提示。需要无审批查看项目时，Agent 应优先使用三个专用只读工具。

命令工具仍只检查命令文本中可识别的显式路径，不提供操作系统级沙箱；该既有限制不因本次只读快速路径而改变。
