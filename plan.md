# MewCode MCP 客户端 Plan

## 设计依据

- 已批准需求：[`spec.md`](./spec.md)
- MCP 当前正式协议版本：[`2025-11-25`](https://modelcontextprotocol.io/specification/2025-11-25)
- MCP 生命周期：[`initialize` → `notifications/initialized` → operation → transport shutdown](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)
- MCP 标准传输：[`stdio` 与 Streamable HTTP](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- MCP 工具协议：[`tools/list`、cursor 分页、`tools/call` 与结果类型](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- 官方 Python SDK：稳定 v1 系列，项目依赖锁定为 `mcp>=1.27,<2`，避免 v2 正式发布后发生未经设计的破坏性升级。

## 架构概览

MCP 接入分为配置、会话管理和工具适配三层。配置层从用户级与项目级 YAML 解析并合并 Server 定义，在建立任何连接前完成严格校验和环境变量展开。会话管理层在专用后台 asyncio 事件循环中使用官方 MCP SDK 建立 stdio 或 Streamable HTTP 会话，缓存每个 Server 的连接，执行初始化、分页工具发现、调用和关闭。工具适配层把远端工具转换成现有同步 `Tool`，从而继续复用 Registry、权限服务、ToolExecutor 和 Agent Loop。

现有 CLI 和 Tool 接口保持同步。`MCPManager` 是同步世界与 SDK 异步世界的唯一桥梁：主线程通过线程安全 future 提交协程，SDK 的传输、JSON-RPC id 分配、乱序响应配对、SSE、协议版本和 HTTP Session ID 均留在后台事件循环内。所有异步上下文也在该事件循环中创建和销毁，避免跨线程关闭资源。

启动阶段并发连接多个 Server，防止总等待时间随故障 Server 数量线性增长；结果按合并后的配置顺序注册，保证冲突处理和警告顺序确定。连接或发现失败只产生该 Server 的警告。配置解析发生在连接之前，任何配置错误均直接终止启动。

```text
用户级 config ─┐
               ├─ MCP 配置解析/合并 ── MCPManager 后台事件循环
项目级 config ─┘                          ├─ stdio SDK transport ─ MCP Server A
                                          └─ HTTP SDK transport  ─ MCP Server B
                                                       │
                                             initialize + tools/list
                                                       │
内置工具 ──────────────── ToolRegistry ◀──── MCPTool 适配器
                                  │
Agent → ToolExecutor → PermissionService → MCPTool.run → MCPManager.call_tool
```

## 核心数据结构

### `StdioMCPServerConfig`

位置：`src/mycode/types.py`

```python
@dataclass(frozen=True)
class StdioMCPServerConfig:
    name: str
    transport: Literal["stdio"]
    command: str
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = ...
```

保存已经校验和完成 `${VAR}` 展开的 stdio 配置。传入 SDK 时使用 `{**os.environ, **config.env}`，满足完整继承当前进程环境、配置值覆盖同名变量的需求，而不是采用 SDK 默认的有限环境白名单。

### `HTTPMCPServerConfig`

位置：`src/mycode/types.py`

```python
@dataclass(frozen=True)
class HTTPMCPServerConfig:
    name: str
    transport: Literal["http"]
    url: str
    headers: Mapping[str, str] = ...
```

保存已经校验和展开的 Streamable HTTP 配置。URL 只接受 `http` 或 `https`。用户 headers 通过预配置的 `httpx.AsyncClient` 交给 SDK；`Accept`、`Content-Type`、`MCP-Session-Id`、`MCP-Protocol-Version` 等协议控制 header 由 SDK 管理，配置中出现这些保留名时报告配置错误。

### `AppConfig`

位置：`src/mycode/types.py`

在现有 Provider 字段后增加：

```python
mcp_servers: tuple[StdioMCPServerConfig | HTTPMCPServerConfig, ...] = ()
```

使用有序 tuple 保存合并后的 Server，避免可变 map 进入 frozen dataclass，并提供确定的连接、注册与警告顺序。

### `MCPRemoteTool`

位置：`src/mycode/mcp/models.py`

```python
@dataclass(frozen=True)
class MCPRemoteTool:
    server_name: str
    remote_name: str
    exposed_name: str
    description: str
    input_schema: dict[str, object]
```

这是工具发现结果的项目内表示。只保留 Tool 适配需要的字段，不把 SDK/Pydantic 对象泄漏到现有工具和 Provider 层。

### `MCPDiscoveryWarning`

位置：`src/mycode/mcp/models.py`

```python
@dataclass(frozen=True)
class MCPDiscoveryWarning:
    server_name: str
    stage: Literal["connect", "initialize", "list_tools", "tool_validation", "registration"]
    message: str
```

向 CLI 提供已脱敏、可测试的警告。异常对象和 HTTP headers/env 不直接进入用户消息。

### `_ServerConnection`

位置：`src/mycode/mcp/manager.py`，模块私有。

```python
@dataclass
class _ServerConnection:
    config: MCPServerConfig
    session: ClientSession
    exit_stack: AsyncExitStack
    negotiated_protocol: str
```

每个成功初始化的 Server 对应一个连接对象。`exit_stack` 持有 stdio 或 HTTP transport、HTTP client 和 `ClientSession` 的异步上下文；它们始终在 manager 的后台事件循环中退出。

### `MCPManager`

位置：`src/mycode/mcp/manager.py`

```python
class MCPManager:
    def start(self) -> None: ...
    def discover(self) -> tuple[list[MCPRemoteTool], list[MCPDiscoveryWarning]]: ...
    def call_tool(
        self,
        server_name: str,
        remote_name: str,
        arguments: Mapping[str, object],
        timeout_seconds: float,
    ) -> CallToolResult: ...
    def close(self) -> None: ...
```

`start` 创建一个 daemon 线程和该线程专属的 asyncio event loop；没有配置 Server 时不创建线程。`discover` 并发建立所有 Server 会话并分页获取完整工具列表。`call_tool` 把同步调用提交到 event loop，并在超时后取消 future；内部请求超时略早于 ToolExecutor 外层超时，使 MCP 调用能够返回结构化超时结果，而不是留下仍在运行的协程。`close` 幂等：先取消在途请求，再关闭各连接，最后停止 event loop 并 join 线程。

### `MCPTool`

位置：`src/mycode/mcp/tool.py`

```python
class MCPTool:
    @property
    def spec(self) -> ToolSpec: ...
    def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult: ...
```

适配器保存 `MCPRemoteTool` 和共享 `MCPManager`。`spec` 暴露 `<server>__<tool>`、远端 description 与 `inputSchema`；`run` 使用远端原始工具名调用 manager，并把 SDK 的 `CallToolResult` 转换为 MewCode `ToolResult`。

## 模块设计

### 配置加载与合并

**职责：** 在建立连接前读取两层配置、校验 schema、展开变量并形成不可变 Server 配置。

**对外接口：** 保持 `load_config(project_path)` 的调用方式；增加可注入的 `user_path` 仅供测试，默认使用 `~/.mycode/config.yaml`。

**行为：**

1. 项目级配置仍必须包含现有 Provider 必填字段；用户级配置允许只包含 `mcp_servers`，其中的 Provider 字段不参与本阶段合并。
2. 用户配置文件不存在时按空 `mcp_servers` 处理；项目配置文件不存在仍沿用当前配置错误语义。
3. 两层 YAML 都使用拒绝重复 key 的 loader。只严格校验 `mcp_servers` 及其内部字段，不趁本功能改变现有 Provider 顶层未知字段行为。
4. 先解析用户 map，再用项目 map 按 Server key 整体覆盖；项目新增项追加到有序结果。
5. Server 名和最终工具名采用所有现有 Provider 与权限规则均可接受的交集：`[A-Za-z0-9_-]+`，最终工具名最长 64 字符。Server 名在配置阶段校验；远端名和组合名在发现阶段校验。
6. stdio 允许字段为 `transport`、`command`、`args`、`env`；`command` 必填，`args` 默认为空字符串列表，`env` 默认为字符串 map。
7. HTTP 允许字段为 `transport`、`url`、`headers`；`url` 必填，`headers` 默认为字符串 map。
8. `${VAR}` 扫描字符串中的所有占位符并逐个替换。用 `name in os.environ` 区分“未设置”和“已设置为空”；不支持 shell 默认值、命令替换或递归展开。
9. 错误只报告配置路径、Server 名、字段和变量名，不回显 command 参数、URL query、header 值或 env 值。

**覆盖：** F1-F6，AC1-AC5。

### SDK 传输与会话创建

**职责：** 把项目配置转换为官方 SDK transport，并在同一个后台事件循环中完成整个上下文生命周期。

**stdio：** 使用 `StdioServerParameters` 和 `stdio_client`。显式传入完整合并后的环境；stderr 作为 Server 日志流处理，不把 stderr 内容判定为协议失败。SDK负责 UTF-8、每行一个 JSON-RPC 消息以及子进程关闭时的 stdin close → terminate → kill 顺序。

**HTTP：** 为每个 Server 创建独立 `httpx.AsyncClient(headers=..., timeout=...)`，再交给稳定 v1 的 `streamable_http_client`。SDK负责每条消息独立 POST、JSON/SSE 两种响应、GET SSE、协议版本 header、Session ID、DELETE 关闭和 JSON-RPC 配对。配置 headers 仅作为默认 header，协议 header 由 SDK覆盖。

**协议生命周期：** `ClientSession` 以空客户端 capabilities 初始化，明确不声明 Resources、Prompts、Sampling、Roots 或 Elicitation。调用 `initialize()` 后检查协商版本与 Server 的 `tools` capability，然后发送/等待 SDK 管理的 initialized 流程，再进入工具发现。SDK支持的历史版本可参与协商；Server 返回 SDK不支持的版本时关闭该连接并产生 initialize 警告。

**重连边界：** 不在应用层重新创建失效会话或重启 stdio 进程。Streamable HTTP 为完成同一请求而进行的 SSE resumption 属于标准传输恢复，由 SDK处理；HTTP 404/session terminated 不触发新的 initialize，后续调用返回失效连接错误。

**覆盖：** F3、F4、F7、F8、F16-F19，N1-N3，AC4-AC7、AC11、AC15-AC18。

### 工具发现

**职责：** 获取 Server 的完整工具清单，验证并转换为项目内工具描述。

**流程：**

1. 每个 Server 初始化后调用 `tools/list`。
2. 只要响应含 `nextCursor`，继续请求下一页；对 cursor 循环设置保护，重复 cursor 视为协议错误，避免无限循环。
3. 校验每个工具的 name、组合后名称、description 和 `inputSchema`。description 缺失时使用包含 Server/远端名的中性说明；`inputSchema` 必须是 JSON object schema，否则跳过该工具并警告。
4. 构造 `<server>__<remote_name>`，不清洗、不重写远端名。
5. 内置工具先注册；MCP 工具按 Server 配置顺序和远端返回顺序注册。Registry 抛出重复错误时转为 registration 警告并继续。
6. 本阶段不响应 `notifications/tools/list_changed` 来动态重载；SDK可以接收通知，但工具集合保持启动时快照。

**覆盖：** F7、F9-F11、F18，AC6、AC8-AC10、AC16。

### 异步请求与同步桥接

**职责：** 保持现有同步 Tool API，同时让多个 Server 与同一 Server 的多个在途请求能异步配对。

**设计：**

- manager 后台线程只运行一个 asyncio event loop；每个 Server 使用独立 SDK `ClientSession`。
- 调用方通过 `asyncio.run_coroutine_threadsafe` 提交请求。官方 SDK为请求分配 JSON-RPC id，并在 session reader 中按 id 完成对应 future，因此响应乱序不会改变调用归属。
- 多 Server 连接对象隔离，异常只完成该 Server 的调用 future。
- `discover` 使用并发 gather 且 `return_exceptions=True`；每个 Server 具有独立初始化/发现超时，最终按配置顺序整理结果。
- `call_tool` 超时会取消提交的 future。SDK session 负责发送协议取消通知；无论取消通知是否被远端接受，本地等待都会结束。
- manager 进入 closing 状态后拒绝新调用；关闭时所有未完成调用得到明确的连接关闭错误。

**覆盖：** F8、F12、F16-F19，N1-N3，AC7、AC11、AC15-AC18。

### 工具结果适配

**职责：** 把 `CallToolResult` 安全转换成现有 `ToolResult`。

**转换规则：**

1. 遍历 `content`；只接受 text block。多个文本块按顺序以换行连接。
2. `structuredContent` 通过 SDK/Pydantic 转成普通 JSON 兼容 dict/list/scalar，写入 `data["structured_content"]`。
3. 任一 image、audio、embedded resource 或 resource link block 出现时，整次适配返回 `ok=False`，只记录不支持的类型名，不保存或回灌 base64/资源内容。
4. `isError=True` 映射为 `ok=False`；文本作为远端错误消息。JSON-RPC error、连接错误、超时和已关闭会话分别转换为带 `server`、`remote_tool` 和稳定原因码的失败结果。
5. 没有文本的成功结果使用简短默认消息；没有文本的失败结果使用简短默认错误消息。
6. 文本超过 `ToolContext.max_output_chars` 时沿用现有截断语义并设置 `truncated=True`。结构化内容序列化后超过边界时返回 `ok=False` 的 `result_too_large`，不截断成无效 JSON。
7. 日志、异常和 ToolResult 都不包含 HTTP headers、stdio env 或 SDK session id。

**覆盖：** F12-F14、F18-F19，N5-N6，AC12-AC13、AC16-AC18、AC20。

### Registry 与命名

**职责：** 让动态工具安全加入现有 Registry，而不改变内置工具语义。

新增一个集中式工具名验证函数供配置、MCP 发现和权限规则复用。`ToolRegistry.register` 继续拒绝重复名称，不增加覆盖能力。MCP 编排层捕获重复错误并形成警告。Provider 仍从 Registry 的 `ToolSpec` 生成各自格式，MCP 层不直接依赖 Provider。

**覆盖：** F9-F11，N4，AC8-AC10、AC19。

### 权限系统接入

**职责：** 让 MCP 工具进入既有受控工具流程，同时避免暂时离线的 Server 破坏权限配置加载。

**设计：**

1. `classify_tool` 已把不在固定 `READ_TOOLS` 中的工具归为 `side_effect`，MCP 工具不加入只读集合，因此批执行自然保持串行。
2. `PermissionConfigLoader` 除已注册内置工具外，接收已配置 Server 的动态前缀集合，例如 `github__`。权限规则可引用语法合法的 `github__create_issue`，即使该工具本次因 Server 离线未发现；这保证 Server 故障不会变成全局配置失败。
3. `PermissionTargetResolver` 同样接收动态前缀。只有 Registry 已成功找到工具后才进入权限服务；对匹配配置前缀的动态工具生成稳定目标 `call`，其他未知工具仍返回 `unknown_tool`。
4. MCP 权限规则形式为 `server__tool(call)`；glob 仍可用于工具调用目标，但固定目标只有 `call`。选择“本会话同意”表示当前进程内允许该 MCP 工具后续所有参数组合。
5. 不把任意远端 arguments 作为权限 target，避免 token、密码、正文等未知敏感字段进入审批提示、规则文件或错误结果。CLI 既有工具事件仍只展示经过筛选和截断的简单参数。
6. 权限规则的工具名语法扩展为与集中式工具名验证一致，支持字母、数字、下划线和连字符；现有规则继续兼容。

**覆盖：** F15、F18，N4-N5，AC14、AC16、AC19。

### CLI 启动与关闭

**职责：** 串联配置、权限、发现、注册、Agent 和确定性清理。

**启动顺序：**

1. 加载并完整校验项目 Provider 配置和两层 MCP 配置。
2. 创建 Provider 与内置 Registry。
3. 依据配置的 Server 前缀加载权限配置并创建 PermissionService；配置错误在任何 MCP 连接前返回 exit code 1。
4. 创建 MCPManager，启动后台 loop，并发现各 Server 工具。
5. 将合法 MCPTool 注册到 Registry；逐条警告输出到 stderr，不输出敏感配置。
6. 创建 AgentRunner 并进入现有交互循环。

**关闭顺序：** 用 `try/finally` 覆盖 `exit`、`quit`、EOF、等待输入时 Ctrl+C、启动后异常和正常函数返回。finally 调用 manager.close；关闭警告不改变已经确定的正常退出码，但会写 stderr。配置错误发生在 manager 创建前，无需清理连接。

**覆盖：** F7、F16-F19，N1、N5，AC6、AC11、AC15-AC18、AC21。

## 模块交互

### 启动与发现

```text
CLI
 ├─ load_config(project, user)
 │   ├─ parse provider from project
 │   ├─ parse user mcp_servers
 │   ├─ parse project mcp_servers
 │   └─ merge + validate + expand env
 ├─ create_default_registry()
 ├─ PermissionConfigLoader(local tools, configured MCP prefixes)
 ├─ MCPManager.start()
 ├─ MCPManager.discover()
 │   ├─ connect all servers concurrently
 │   └─ per server: transport → ClientSession → initialize → paged tools/list
 ├─ register MCPTool adapters in deterministic order
 └─ AgentRunner(...)
```

### 工具调用

```text
Agent tool call: server__tool(arguments)
 → ToolRegistry.get
 → PermissionService.authorize(target="call")
 → MCPTool.run
 → MCPManager.call_tool(server, remote tool, arguments)
 → background event loop
 → ClientSession.call_tool / JSON-RPC id pairing
 → CallToolResult
 → text + structuredContent conversion
 → ToolResult
 → existing Agent result feedback
```

### 退出

```text
CLI finally
 → MCPManager.close
 → reject new calls
 → cancel pending calls
 → close ClientSession / transport stacks per server
    ├─ HTTP: DELETE session when applicable + close AsyncClient
    └─ stdio: close stdin → wait → terminate → kill fallback
 → stop event loop
 → join background thread
```

## 文件组织

| 操作 | 文件 | 职责 |
|------|------|------|
| 修改 | `pyproject.toml` | Python 下限升至 3.10，加入 `mcp>=1.27,<2` |
| 修改 | `src/mycode/types.py` | 增加两类 MCP Server 配置并扩展 AppConfig |
| 修改 | `src/mycode/config.py` | 两层读取、Server 合并、严格校验和 `${VAR}` 展开 |
| 新建 | `src/mycode/mcp/__init__.py` | MCP 子包公开入口 |
| 新建 | `src/mycode/mcp/models.py` | 发现工具、警告和内部错误模型 |
| 新建 | `src/mycode/mcp/manager.py` | 后台事件循环、SDK transport、连接缓存、发现、调用和关闭 |
| 新建 | `src/mycode/mcp/tool.py` | MCP Tool 适配及结果转换 |
| 修改 | `src/mycode/tools/registry.py` | 集中工具名校验，保持重复注册拒绝语义 |
| 修改 | `src/mycode/permissions/config.py` | 允许已配置 MCP Server 命名空间中的权限规则 |
| 修改 | `src/mycode/permissions/rules.py` | 工具名语法与集中验证一致 |
| 修改 | `src/mycode/permissions/targets.py` | 为已配置 MCP 命名空间生成固定 `call` 权限目标 |
| 修改 | `src/mycode/permissions/service.py` | 向 target resolver 注入 MCP 命名空间 |
| 修改 | `src/mycode/cli.py` | 启动发现、警告输出、动态注册和 finally 清理 |
| 修改 | `config.example.yaml` | 添加 stdio/HTTP、headers/env 与两层覆盖示例 |
| 修改 | `README.md` | 记录 Python 版本、MCP 配置、命名、权限和失败语义 |
| 修改 | `tests/test_config.py` | 两层 MCP 配置、覆盖、校验与变量展开测试 |
| 新建 | `tests/test_mcp_manager.py` | SDK 会话、分页、并发配对、隔离、超时与关闭测试 |
| 新建 | `tests/test_mcp_tool.py` | 工具 spec、结果类型、大小边界和错误映射测试 |
| 修改 | `tests/test_tools_registry.py` | MCP 名称合法性和冲突回归测试 |
| 修改 | `tests/test_permissions_config.py` | 动态命名空间规则及离线 Server 场景测试 |
| 修改 | `tests/test_permissions_service.py` | MCP 固定目标、三档模式和审批范围测试 |
| 修改 | `tests/test_cli.py` | 启动警告、部分/全部失败及所有退出路径清理测试 |
| 新建 | `tests/fixtures/mcp_test_server.py` | 同时供 stdio 与 HTTP 端到端测试使用的最小 MCP Server |
| 新建 | `tests/test_mcp_integration.py` | 两种真实传输、故障 Server、调用和无遗留资源端到端测试 |

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| MCP 实现 | 官方 Python SDK v1，`mcp>=1.27,<2` | 复用规范级 JSON-RPC、SSE、版本协商和 Session 管理；避免自制协议兼容负担 |
| Python 版本 | 最低 3.10 | 官方 SDK硬要求，已获用户确认 |
| 同步/异步边界 | manager 专属 asyncio 后台线程 | 不重写现有同步 Tool/Agent；所有 SDK资源仍固定在同一 event loop 生命周期内 |
| Server 启动 | 并发连接、按配置顺序注册 | 故障等待不线性叠加，同时保证冲突和输出确定 |
| 协议版本 | 由 SDK以当前正式版本发起并协商其支持版本 | 遵守生命周期且不新增用户配置项 |
| HTTP 响应 | SDK同时支持 JSON 与 SSE | Streamable HTTP 规范要求客户端支持两者 |
| HTTP 会话 | 每 Server 独立 AsyncClient、ClientSession 和 Session ID | 隔离 headers、状态、错误和关闭 |
| SSE 恢复 | 允许同一请求/会话内的 SDK resumption；不新建 MCP 会话 | 满足传输规范，同时遵守“不自动重连 Server 会话”范围 |
| 工具列表 | cursor 循环获取全部页 | `tools/list` 是分页接口，只取第一页会漏工具 |
| 名称 | `<server>__<tool>`；不清洗，非法跳过 | 来源清晰、避免隐式重命名和不可预测冲突 |
| 冲突 | 内置优先，后注册项跳过并警告 | 保持现有工具稳定，不让单项问题扩大 |
| 权限分类 | 所有 MCP 工具为 side_effect | 不信任远端注解，符合已批准 spec 和 MCP安全建议 |
| 权限目标 | 固定字符串 `call` | 远端参数无统一安全目标；避免敏感 JSON进入审批和规则 |
| 离线 Server 权限规则 | 允许已配置 Server 的动态工具前缀 | 单 Server 故障不得使全局权限配置失败 |
| 非文本结果 | 整次调用结构化失败 | 当前 Agent Loop不能正确消费二进制/资源，禁止静默丢弃 |
| 大结构化结果 | 超限失败，不截断 JSON | 保持结构有效并保护上下文边界 |
| 动态工具变更 | 忽略 list_changed，不热更新 | 已明确不做运行时重载，遵守 YAGNI |
| OAuth | 本阶段不实现；使用静态 headers | 用户范围仅要求 headers，OAuth 会引入额外交互与 token 生命周期 |

## Spec 覆盖矩阵

| Spec | 设计覆盖 |
|------|----------|
| F1-F6 | 配置加载与合并、配置模型 |
| F7-F8 | SDK传输与会话、异步请求桥接 |
| F9-F11 | 工具发现、Registry 与命名 |
| F12-F14 | MCPTool、工具结果适配 |
| F15 | 权限系统接入 |
| F16-F19 | MCPManager、CLI 生命周期与失败隔离 |
| N1-N3 | 并发连接、每请求超时、SDK id 配对、连接隔离 |
| N4 | 适配层边界与内置工具回归 |
| N5-N6 | 脱敏警告、结果转换和大小边界 |
| N7 | 单元、集成与真实双传输端到端测试 |

## 风险与控制

- **同步外层超时与异步内层超时竞态：** manager 的请求截止时间略早于 ToolExecutor，超时先取消 SDK future 并返回结构化结果；测试验证没有后台遗留调用。
- **用户配置 headers/env 泄露：** 配置错误、warning、ToolResult 和日志适配只使用 Server 名与阶段；不格式化完整配置对象。
- **stdio 子进程遗留：** 关闭全部交给 SDK async context，并为 manager close 设置外层上限；端到端测试检查子进程退出。
- **HTTP Server 自动失效：** 不在 manager 中重建 `_ServerConnection`；session terminated 映射为失败。只保留 SDK对同一 Streamable HTTP 请求的标准 SSE resumption。
- **权限规则引用离线工具：** 根据已配置 Server 前缀做语法许可，实际执行仍由 Registry先拦截，避免扩大执行面。
- **项目当前存在未提交权限改造：** 实施时只修改 task 明确列出的文件，先复核工作树差异并保留用户现有改动；冲突处以当前已修改代码为基线做最小补丁。
