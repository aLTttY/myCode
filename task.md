# MewCode MCP 客户端 Tasks

## 执行约束

- 四份文档全部审批前不得执行以下实现任务。
- 当前工作树已有权限系统相关未提交改动。开始开发时先执行 T0；不得重置、覆盖或顺带提交这些既有改动。
- 每个任务必须先运行自己的定向验证，通过后才能进入依赖它的任务。
- 逻辑相关任务完成后只提交可明确归属于 MCP 功能的文件或 hunk；若重叠修改无法安全拆分，暂停并请用户处理，而不是扩大提交范围。
- 官方 MCP SDK 必须保持 `mcp>=1.27,<2`，不得在本阶段切换到 v2 预发布版。

## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 修改 | `pyproject.toml` | Python 下限升至 3.10，加入官方 MCP SDK v1 依赖 |
| 修改 | `src/mycode/types.py` | 定义 stdio/HTTP Server 配置并扩展 AppConfig |
| 修改 | `src/mycode/config.py` | 用户/项目两层读取、覆盖、校验和变量展开 |
| 新建 | `src/mycode/mcp/__init__.py` | MCP 子包公开入口 |
| 新建 | `src/mycode/mcp/models.py` | 远端工具、发现警告和错误分类模型 |
| 新建 | `src/mycode/mcp/manager.py` | 后台 event loop、SDK 会话、发现、调用、缓存和关闭 |
| 新建 | `src/mycode/mcp/tool.py` | MCP Tool 适配器和结果转换 |
| 修改 | `src/mycode/tools/registry.py` | 集中式工具名校验和既有重复保护 |
| 修改 | `src/mycode/permissions/config.py` | 允许已配置 MCP 动态命名空间规则 |
| 修改 | `src/mycode/permissions/rules.py` | 权限规则工具名语法支持合法 MCP 名称 |
| 修改 | `src/mycode/permissions/targets.py` | MCP 工具固定 `call` 目标和未知工具隔离 |
| 修改 | `src/mycode/permissions/service.py` | 注入已配置 MCP 命名空间 |
| 修改 | `src/mycode/cli.py` | MCP 发现、注册、警告和所有退出路径清理 |
| 修改 | `src/mycode/agent/tools.py` | 如测试需要，仅确认/固化 MCP side_effect 分类，不扩展只读集合 |
| 修改 | `README.md` | 使用说明、配置层级、命名、权限和失败语义 |
| 修改 | `config.example.yaml` | stdio/HTTP 与环境变量配置示例 |
| 修改 | `tests/test_config.py` | MCP 两层配置和错误测试 |
| 新建 | `tests/test_mcp_manager.py` | manager 单元与异步生命周期测试 |
| 新建 | `tests/test_mcp_tool.py` | Tool spec、调用和结果转换测试 |
| 修改 | `tests/test_tools_registry.py` | 工具名与冲突回归测试 |
| 修改 | `tests/test_permissions_config.py` | 动态 MCP 权限规则测试 |
| 修改 | `tests/test_permissions_rules.py` | MCP 工具名语法和规则匹配测试 |
| 修改 | `tests/test_permissions_service.py` | MCP 目标、模式与审批测试 |
| 修改 | `tests/test_agent_tools.py` | MCP 工具始终分类为 side_effect |
| 修改 | `tests/test_agent_executor.py` | 多个 MCP 调用维持串行执行 |
| 修改 | `tests/test_cli.py` | 启动失败隔离、警告和 finally 清理测试 |
| 新建 | `tests/fixtures/mcp_test_server.py` | stdio/HTTP 共用的真实 MCP 测试 Server |
| 新建 | `tests/test_mcp_integration.py` | 双传输、乱序、失败 Server 与清理端到端测试 |

## T0：保护当前工作树并确认实现基线

**文件：** 不修改文件

**依赖：** 无

**步骤：**

1. 记录 `git status --short` 和所有计划修改文件的现有 diff。
2. 标记已经由用户修改的重叠文件，重点检查 `src/mycode/permissions/*`、`src/mycode/cli.py` 和相关 tests。
3. 确认用户已提交并允许覆盖原文档；本功能的 MCP 文档直接使用根目录 `spec.md`、`plan.md`、`task.md`、`checklist.md`。
4. 后续补丁以当前磁盘内容为基线；禁止 reset、checkout 或覆盖用户改动。
5. 如任何重叠文件无法通过小范围补丁安全修改，停止实现并向用户报告具体冲突。

**验证：**

```bash
git status --short
git diff -- src/mycode/cli.py src/mycode/permissions tests/test_cli.py tests/test_permissions_config.py tests/test_permissions_service.py
```

期望：获得可审计基线，没有文件被修改或清理。

## T1：升级运行时并实现两层 MCP 配置

**文件：** `pyproject.toml`、`src/mycode/types.py`、`src/mycode/config.py`、`tests/test_config.py`

**依赖：** T0

**步骤：**

1. 将 `requires-python` 改为 `>=3.10`，加入 `mcp>=1.27,<2`。
2. 定义不可变 stdio/HTTP Server 配置类型，并在 AppConfig 中增加有序 `mcp_servers` 默认值，保持现有测试构造 AppConfig 的兼容性。
3. 提取拒绝重复 YAML key 的安全读取逻辑；项目配置仍为必需，用户配置缺失按空处理。
4. 从默认 `~/.mycode/config.yaml` 或测试注入路径读取用户层，只合并 `mcp_servers`；Provider 配置继续来自项目层。
5. 实现按 Server key 的整体覆盖：用户层先进入有序 map，项目同名定义替换，项目新增定义追加。
6. 严格校验 `transport`、允许字段、必填字段、字符串列表/map、URL scheme 和保留 HTTP headers。
7. 实现字符串内全部 `${VAR}` 展开，区分未设置与已设置为空，不支持 shell 扩展语法或递归展开。
8. 保证错误只包含配置路径、Server、字段或变量名，不回显敏感配置值。
9. 添加合法配置、默认值、覆盖顺序、`--config` 数据来源、完整/嵌入/空变量、缺失变量、重复 key、混用字段、未知字段、非法 URL/header/type 的测试。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_config.py
PYTHONPYCACHEPREFIX=/tmp/mycode-pycache PYTHONPATH=src .venv/bin/python -m compileall -q src/mycode/config.py src/mycode/types.py
```

期望：配置测试全部通过；源文件可编译；错误测试中不出现测试用 secret 值。

**建议提交边界：** `MCP config loading and Python 3.10 baseline`

## T2：统一工具命名并接入动态权限命名空间

**文件：** `src/mycode/tools/registry.py`、`src/mycode/permissions/config.py`、`src/mycode/permissions/rules.py`、`src/mycode/permissions/targets.py`、`src/mycode/permissions/service.py`、`tests/test_tools_registry.py`、`tests/test_permissions_config.py`、`tests/test_permissions_rules.py`、`tests/test_permissions_service.py`、`tests/test_agent_tools.py`、`tests/test_agent_executor.py`

**依赖：** T1

**步骤：**

1. 增加集中工具名验证：只允许字母、数字、下划线、连字符，长度 1-64；保持 Registry 重复注册抛错且不覆盖。
2. 扩展权限规则解析器，使合法的 `<server>__<tool>` 和连字符工具名可被解析，既有内置规则保持兼容。
3. 让 PermissionConfigLoader 接收已配置 Server 的动态前缀；精确 MCP 工具即使本次未发现，也可在对应前缀下通过配置语法校验。
4. 让 PermissionTargetResolver 只为已配置动态前缀生成固定目标 `call`；其他未知工具继续返回 `unknown_tool`。
5. PermissionService 把动态前缀传给 resolver，不改变黑名单、沙箱、规则优先级、三档模式和审批逻辑。
6. 验证 `server__tool(call)` 的 exact allow/deny、本会话规则、strict/default/allow 行为和离线 Server 配置场景。
7. 验证所有 MCP 名称默认是 `side_effect`，远端只读注解不会进入固定 `READ_TOOLS`。
8. 使用 fake MCP Tool 调用序列验证 BatchToolExecutor 串行执行，不进入只读并发 batch。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_tools_registry.py tests/test_permissions_config.py tests/test_permissions_rules.py tests/test_permissions_service.py tests/test_agent_tools.py tests/test_agent_executor.py
```

期望：动态命名空间规则可加载，未知非 MCP 工具仍失败；MCP 工具受控且串行；全部既有权限回归通过。

**建议提交边界：** `Integrate MCP tool names with permissions`

## T3：实现 MCPManager、双传输会话与工具发现

**文件：** `src/mycode/mcp/__init__.py`、`src/mycode/mcp/models.py`、`src/mycode/mcp/manager.py`、`tests/test_mcp_manager.py`

**依赖：** T1、T2

**步骤：**

1. 定义不依赖 SDK 对象的远端工具模型、分阶段脱敏 warning 和稳定错误分类。
2. 实现幂等 `start`：有 Server 时创建 daemon 线程和专属 asyncio loop，无 Server 时保持无资源状态。
3. 通过可注入 transport/session factory 构造测试缝隙；生产路径使用官方 `stdio_client`、`streamable_http_client` 和 `ClientSession`。
4. stdio 参数显式传入 `{**os.environ, **config.env}`；HTTP 为每个 Server 创建带静态 headers 和 timeout 的独立 AsyncClient。
5. 每个 Server 使用独立 AsyncExitStack，在后台 loop 内依次进入 transport、ClientSession、initialize。
6. 检查版本协商和 tools capability；失败时关闭该 Server stack，并按 connect/initialize 阶段返回 warning。
7. 实现 cursor 分页 `tools/list`，检测重复 cursor；将每页工具转成 MCPRemoteTool，非法名称/schema 只产生单项 warning。
8. `discover` 并发连接 Server，使用独立超时和 `return_exceptions` 隔离错误，最终按配置顺序返回工具与 warning。
9. 保持 `_ServerConnection` 缓存；连续调用不重建 transport/session。
10. 实现 `call_tool` 的线程安全提交、内部截止时间、future 取消、关闭状态拒绝和稳定错误分类。
11. 实现幂等 `close`：拒绝新请求、取消在途请求、关闭所有 stack、停止 loop、join 线程；HTTP session terminated 不重新 initialize。
12. 用 fake async session 覆盖：无 Server、初始化成功/失败、分页、cursor 循环、非法工具、并发发现、跨 Server 隔离、同 Server 乱序结果、调用超时、会话复用、关闭中调用、重复 close、关闭资源顺序。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_manager.py
PYTHONPYCACHEPREFIX=/tmp/mycode-pycache PYTHONPATH=src .venv/bin/python -m compileall -q src/mycode/mcp
```

期望：manager 定向测试全部通过；每个测试结束后无后台线程、未完成 task 或未关闭 fake stack。

**建议提交边界：** `Add cached MCP client sessions and discovery`

## T4：实现 MCP Tool 适配和结果转换

**文件：** `src/mycode/mcp/tool.py`、`src/mycode/mcp/__init__.py`、`tests/test_mcp_tool.py`、`tests/test_tool_executor.py`、`tests/test_agent_runner.py`

**依赖：** T3

**步骤：**

1. 将 MCPRemoteTool 映射为现有 ToolSpec，使用 exposed name、远端 description 和 inputSchema；不把 SDK 类型传给 Provider。
2. `run` 使用 server name 和 remote name 调用共享 manager，并传入 ToolContext 的 timeout 与输出边界。
3. 按顺序合并多个 text block；保留正常范围内的 `structuredContent` 为普通 JSON 数据。
4. 将 `isError`、JSON-RPC error、连接失败、会话失效、超时和关闭分别映射为带稳定原因码的 ToolResult 失败。
5. image/audio/resource/resource_link 任一出现时整次失败，只回传类型名，不保留二进制、URI 内容或 SDK对象。
6. 文本超限时截断并标注；结构化 JSON 超限时返回 `result_too_large`，不得生成残缺 JSON。
7. 确保 ToolResult 不含 headers、env、session id；异常消息经过脱敏边界。
8. 验证 MCPTool 经过 ToolExecutor 权限判定后才调用 manager；拒绝时 manager 调用次数为零。
9. 验证成功和失败结果都通过现有 AgentRunner 写入消息历史并进入下一轮。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_tool.py tests/test_tool_executor.py tests/test_agent_runner.py
```

期望：所有支持与不支持结果类型、大小边界、权限前置和 Agent 回灌测试通过。

**建议提交边界：** `Adapt MCP tools into the MewCode tool loop`

## T5：接入 CLI 启动、注册、警告和生命周期

**文件：** `src/mycode/cli.py`、`tests/test_cli.py`

**依赖：** T2、T3、T4

**步骤：**

1. 保持 Provider 与内置 Registry 创建语义，先从已配置 Server 生成权限动态前缀并加载权限配置。
2. 权限配置成功后创建 manager、启动并发现；配置错误必须发生在任何连接之前。
3. 按 discover 返回顺序构造并注册 MCPTool；捕获重复注册，保留先注册项并追加 registration warning。
4. 把 connect/initialize/list_tools/tool_validation/registration warning 输出到 stderr，只展示 Server、阶段和脱敏消息。
5. 全部 Server 失败时仍创建 AgentRunner，Registry 保留六个内置工具；部分失败时成功 Server 工具正常可用。
6. 用统一 `try/finally` 包围 manager 生命周期，覆盖 exit/quit/退出、EOF、等待输入 Ctrl+C、Agent 运行 Ctrl+C、ProviderError 和启动后异常。
7. manager.close 的异常只产生关闭 warning，不覆盖既有正常退出码；配置错误继续返回 1。
8. 更新测试 fake，使无 MCP 配置时无需真实 SDK；添加启动顺序、注册顺序、冲突、警告脱敏、全部/部分失败、每种退出路径仅 close 一次的测试。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py
```

期望：CLI MCP 定向场景和全部既有 CLI 交互测试通过；每个创建 manager 的场景都可观察到 close。

**建议提交边界：** `Discover and manage MCP servers from the CLI`

## T6：建立真实 stdio 与 Streamable HTTP 端到端验证

**文件：** `tests/fixtures/mcp_test_server.py`、`tests/test_mcp_integration.py`

**依赖：** T3、T4、T5

**步骤：**

1. 使用锁定的官方 SDK实现最小测试 Server，同一脚本可按参数运行 stdio 或 Streamable HTTP。
2. 提供 text、structuredContent、isError、不支持内容、超大结果、延迟结果和环境变量回显工具。
3. 为 HTTP 测试动态选择本机 loopback 端口，等待明确 readiness，并确保 fixture 无论测试成功失败都终止 Server。
4. 构造一个可用 stdio、一个可用 HTTP 和一个必然失败的 Server 配置；验证并发发现只为失败项警告。
5. 验证 stdio 继承父环境并被配置 env 覆盖；HTTP 验证展开后的静态 header 能到达 Server，但测试输出不泄漏值。
6. 直接并发调用同一 Server 的快/慢工具，使响应顺序不同，断言每个调用拿到自己的结果。
7. 连续调用同一工具并通过 Server 侧计数确认会话未重建。
8. 模拟 session 失效，断言后续调用失败且没有新的 initialize 或子进程重启。
9. 让 MCPTool 通过 PermissionService 与 AgentRunner 完成一次真实结果回灌。
10. close 后断言 manager 线程结束、stdio 子进程退出、HTTP client/session 关闭且没有在途请求。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_integration.py -v
```

期望：两种真实传输、故障隔离、乱序配对、权限、回灌与清理场景全部通过，测试进程退出后无 fixture 子进程。

**建议提交边界：** `Add MCP stdio and Streamable HTTP integration coverage`

## T7：更新用户文档和配置示例

**文件：** `README.md`、`config.example.yaml`

**依赖：** T1、T2、T5、T6

**步骤：**

1. 更新 Python 最低版本和安装依赖说明。
2. 说明用户级 `~/.mycode/config.yaml` 与项目级 `./config.yaml`/`--config` 的 MCP merge 规则和整体覆盖语义。
3. 添加 stdio `transport/command/args/env` 与 HTTP `transport/url/headers` 示例，展示完整和嵌入式 `${VAR}`。
4. 说明 stdio 继承环境、HTTP 保留 headers、未设置变量导致启动配置错误。
5. 说明 Agent 可见名称 `<server>__<tool>`、非法/冲突工具跳过警告和 Server 失败隔离。
6. 说明所有 MCP 工具按受控 side_effect 处理，权限规则使用 `server__tool(call)`，本会话同意覆盖该工具后续参数组合。
7. 说明只支持文本和 structuredContent，以及本阶段不做的非工具能力、健康检查、自动重连和动态重载。

**验证：**

```bash
rg -n "mcp_servers|transport: stdio|transport: http|server>__<tool|__.*call|Python 3.10|Streamable HTTP|自动重连" README.md config.example.yaml
```

期望：关键行为均有可检索说明；示例不包含真实凭据；与批准的 spec/plan 一致。

**建议提交边界：** `Document MCP server configuration and behavior`

## T8：全量回归与提交范围审计

**文件：** 所有本功能修改文件；不新增功能

**依赖：** T1-T7

**步骤：**

1. 运行源码编译、所有 MCP 定向测试、权限/工具/Agent/CLI 回归和完整测试套件。
2. 运行 `git diff --check`，检查新增代码无未完成占位符、调试输出或敏感测试值。
3. 对照 `spec.md` 的 F1-F19、N1-N7 和 AC1-AC21，确认每项都有测试证据，缺口留给 checklist 阶段执行，不以“代码看起来正确”代替验证。
4. 检查 `git diff --stat` 和逐文件 diff，确认根目录四份文档是本功能版本，且未删除或覆盖用户既有权限改动。
5. 若此前因重叠文件未能安全提交，保持未提交并向用户报告；不得使用全量 `git add .` 把无关改动纳入提交。

**验证：**

```bash
PYTHONPYCACHEPREFIX=/tmp/mycode-pycache PYTHONPATH=src .venv/bin/python -m compileall -q src
PYTHONPATH=src .venv/bin/python -m pytest tests/test_config.py tests/test_mcp_manager.py tests/test_mcp_tool.py tests/test_mcp_integration.py
PYTHONPATH=src .venv/bin/python -m pytest tests/test_tools_registry.py tests/test_permissions_config.py tests/test_permissions_rules.py tests/test_permissions_service.py tests/test_agent_tools.py tests/test_agent_executor.py tests/test_tool_executor.py tests/test_agent_runner.py tests/test_cli.py
PYTHONPATH=src .venv/bin/python -m pytest
git diff --check
rg -n "TO""DO|TB""D|print\(.*secret" src tests README.md config.example.yaml
git status --short
```

期望：编译和全部测试通过；diff 无空白错误或占位符；工作树审计能区分 MCP 改动与用户先前改动。

## 执行顺序

```text
T0 → T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8
```

## 依赖关系

| 任务 | 依赖 | 解锁内容 |
|------|------|----------|
| T0 | 无 | 安全修改当前脏工作树 |
| T1 | T0 | MCP 配置模型与 SDK 可用性 |
| T2 | T1 | 动态工具名称和权限语义 |
| T3 | T1、T2 | 会话、发现和远端调用能力 |
| T4 | T3 | 现有 Tool/Agent 可消费 MCP 结果 |
| T5 | T2、T3、T4 | CLI 启动与生命周期闭环 |
| T6 | T3、T4、T5 | 真实双传输和端到端证据 |
| T7 | T1、T2、T5、T6 | 与实际行为一致的用户说明 |
| T8 | T1-T7 | 完整回归与实现范围审计 |

## Plan 覆盖检查

| Plan 模块 | 对应任务 |
|-----------|----------|
| 配置加载与合并 | T1 |
| SDK 传输与会话创建 | T3、T6 |
| 工具发现 | T3、T5、T6 |
| 异步请求与同步桥接 | T3、T6 |
| 工具结果适配 | T4、T6 |
| Registry 与命名 | T2、T5 |
| 权限系统接入 | T2、T4、T6 |
| CLI 启动与关闭 | T5、T6 |
| 用户文档 | T7 |
| 回归与验收准备 | T8 |
