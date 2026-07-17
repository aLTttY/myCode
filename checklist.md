# MewCode MCP 客户端 Checklist

> 每一项都必须通过运行测试、命令或观察进程行为验证。验收时记录实际结果和证据；不得仅凭代码审阅勾选。

## 运行时与依赖

- [ ] Python 最低版本声明为 3.10，当前验收解释器不低于 3.10，官方 MCP SDK 已安装且版本满足 `>=1.27,<2`。（验证：运行 `.venv/bin/python -c "import sys; from importlib.metadata import version; print(sys.version_info[:3], version('mcp'))"`，并检查 `pyproject.toml`）
- [ ] MCP SDK v2 预发布或稳定版不会被依赖解析选中。（验证：运行 `.venv/bin/python -m pip show mcp`，版本主版本必须为 1；检查依赖上界 `<2`）
- [ ] 没有 MCP Server 配置时不会创建后台 event loop 线程，六个内置工具和现有 CLI 行为保持可用。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_manager.py tests/test_cli.py tests/test_tools_registry.py`）

## 配置与合并

- [ ] AC1：用户级和项目级不同 Server 同时保留；项目级同名 Server 整体覆盖用户级，不做字段级拼接；`--config` 指定文件作为项目级来源。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_config.py tests/test_cli.py`，检查两层、同名覆盖及自定义路径用例）
- [ ] AC2：合法 stdio/HTTP 配置可加载；缺少 `transport`、缺少必填字段、字段类型错误、未知字段、传输字段混用、保留 HTTP header 或非法 URL 时，启动前产生带 Server/字段上下文的 ConfigError。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_config.py`）
- [ ] AC3：`${VAR}` 独占值、嵌入字符串和同一字符串多个变量均正确展开；未设置变量报错，已设置为空合法；错误输出不含测试 secret。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_config.py`，并检查 capsys 中 secret sentinel 不存在）
- [ ] 用户配置文件缺失按空 MCP 层处理，项目配置缺失或 Provider 必填字段缺失仍保持现有配置错误语义。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_config.py tests/test_cli.py`）
- [ ] 两层 YAML 的重复 key 均被拒绝，Server map 和 Server 内部重复字段不会静默采用后值。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_config.py`）
- [ ] Server 配置名只接受集中式合法工具名字符并能参与最终 64 字符限制；非法 Server 名在建立任何连接前终止启动。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_config.py tests/test_tools_registry.py tests/test_cli.py`）

## 传输、初始化与发现

- [ ] AC4：真实 stdio Server 通过 stdin/stdout 完成 initialize、initialized 和工具发现；子进程可读取父进程环境，配置 env 覆盖同名值。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_integration.py -v`，检查 stdio 环境用例）
- [ ] AC5：真实 Streamable HTTP Server 能以普通 JSON 和 SSE 响应完成会话；静态 URL/header 展开值到达 Server，协议 header 与 Session ID 由 SDK 管理，日志和错误不泄露 header secret。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_integration.py -v`，检查 HTTP JSON、SSE、header 与脱敏用例）
- [ ] AC6：两种传输都严格先 initialize 再 tools/list；连接、初始化或工具发现任一步失败的 Server 不注册任何工具，其他 Server 继续。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_manager.py tests/test_mcp_integration.py`）
- [ ] AC7：同一 Server 多个并发请求以不同顺序返回时仍按 JSON-RPC id 得到各自结果；通知、未知 id、重复响应不会误配或完成错误 future。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_manager.py tests/test_mcp_integration.py`，检查乱序与异常消息用例）
- [ ] tools/list 的所有 cursor 页均被读取；重复 cursor 会结束发现并产生该 Server 的协议警告，不会无限循环。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_manager.py`）
- [ ] Server 未声明 tools capability、协商到不受 SDK 支持的版本或返回无效 schema 时，只关闭该 Server 并产生对应阶段警告。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_manager.py`）
- [ ] 启动后收到 `notifications/tools/list_changed` 不会热更新 Registry，工具集合保持启动快照。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_manager.py tests/test_tools_registry.py`）

## 工具命名与注册

- [ ] AC8：合法远端工具以 `<server>__<tool>` 出现在 Agent 工具列表，description 和 inputSchema 与发现结果一致，并使用远端原名完成调用。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_tool.py tests/test_agent_runner.py tests/test_mcp_integration.py`）
- [ ] AC9：非法远端名、非法组合名或超过 64 字符的最终名不会被清洗或改写；只跳过该工具并输出含 Server/原因的 warning，同 Server 其他合法工具仍注册。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_manager.py tests/test_cli.py tests/test_tools_registry.py`）
- [ ] AC10：与内置工具、先注册 MCP 工具或同一 Server 重复工具冲突时，先注册项对象和 spec 保持不变；冲突项跳过并警告，后续合法工具仍注册。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tools_registry.py tests/test_mcp_manager.py tests/test_cli.py`）
- [ ] MCP SDK/Pydantic 类型不会进入 ToolSpec、Provider 请求或 ToolResult；边界外只出现项目内 dataclass、dict/list/scalar。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_tool.py tests/test_providers.py`）

## 调用、结果与上下文边界

- [ ] AC11：同一 Server 连续发现和多次调用复用一个 transport、ClientSession 和 MCP session；stdio 不重复启动子进程，HTTP 不重复 initialize。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_manager.py tests/test_mcp_integration.py`，检查 Server 侧会话计数）
- [ ] AC12：单/多文本块顺序正确，正常大小 `structuredContent` 保持 JSON 语义；`isError: true` 产生 `ok=False`，成功与失败均写回 Agent 消息历史。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_tool.py tests/test_agent_runner.py tests/test_mcp_integration.py`）
- [ ] AC13：image、audio、embedded resource、resource link 及混合结果均产生带不支持类型名的结构化失败；不会保存或回灌 base64、资源正文或 URI 内容。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_tool.py tests/test_mcp_integration.py`）
- [ ] AC20：超大文本按 max_output_chars 截断并标记；超大 structuredContent 以 `result_too_large` 失败且不产生残缺 JSON；Agent 上下文没有无界内容。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_tool.py tests/test_agent_runner.py tests/test_mcp_integration.py`）
- [ ] JSON-RPC error、连接错误、初始化错误、发现错误、超时、session terminated 和 manager closed 具有可区分的稳定原因码与 Server 上下文。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_manager.py tests/test_mcp_tool.py`）
- [ ] warning、异常、ToolResult 和 CLI 输出不包含 HTTP header 值、stdio env 值、Session ID 或测试 secret sentinel。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_config.py tests/test_mcp_manager.py tests/test_mcp_tool.py tests/test_cli.py tests/test_mcp_integration.py`，并检查脱敏断言）

## 权限与 Agent 集成

- [ ] AC14：所有 MCP 工具均分类为 side_effect，进入现有权限判定并串行执行；`readOnlyHint` 不会进入只读免审批或并发路径。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_tools.py tests/test_agent_executor.py tests/test_permissions_service.py`）
- [ ] MCP 权限目标稳定为 `call`；default 模式请求审批，strict 拒绝，allow 放行，显式 allow/deny 和会话规则继续遵守现有优先级。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_rules.py tests/test_permissions_service.py tests/test_mcp_tool.py`）
- [ ] `server__tool(call)` 可用于已配置但暂时离线的 Server，权限配置不会因此阻止 CLI 启动；非配置前缀的未知工具仍产生 unknown_tool。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_config.py tests/test_permissions_service.py tests/test_cli.py`）
- [ ] ToolExecutor 在权限拒绝 MCP 工具时不调用 manager；批准后才发起远端请求。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_tool.py tests/test_tool_executor.py`，检查 manager 调用计数）
- [ ] MCP 成功、远端失败、权限拒绝和连接失效都作为结构化 ToolResult 回灌 Agent Loop，模型可以进入下一轮而不是因适配器异常终止。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py tests/test_mcp_integration.py`）

## 生命周期、隔离与超时

- [ ] AC15：正常退出、exit/quit/退出、EOF、等待输入 Ctrl+C、Agent 执行 Ctrl+C、ProviderError 和启动后异常都只调用一次 manager.close；HTTP client/session、stdio 管道/子进程、在途请求、event loop 和后台线程均结束。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py tests/test_mcp_manager.py tests/test_mcp_integration.py`）
- [ ] AC16：一个 Server 的 connect、initialize、list_tools 或 call 失败不影响其他 Server 和六个内置工具；全部 Server 失败时 CLI 仍启动并为每个失败项输出 warning。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_manager.py tests/test_cli.py tests/test_mcp_integration.py`）
- [ ] AC17：stdio 退出、HTTP session terminated 或连接失效后，后续调用返回结构化失败；应用层没有重新启动子进程、重建 ClientSession 或再次 initialize。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_manager.py tests/test_mcp_integration.py`，检查 Server 初始化计数保持不变）
- [ ] 同一 Streamable HTTP 请求/会话内的 SDK SSE resumption 可以完成原请求，但不会被实现误写成新 MCP 会话重连。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_manager.py tests/test_mcp_integration.py`）
- [ ] AC18：无响应 Server 的启动、发现、调用和关闭均在测试超时边界内结束；超时 future 被取消，随后无后台迟到结果或未完成 task。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_manager.py tests/test_mcp_integration.py`，检查 elapsed 上限与资源计数）
- [ ] 一个 Server 的异常、关闭或请求取消不会取消、完成或污染另一 Server 的请求。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_manager.py tests/test_mcp_integration.py`，检查跨 Server 隔离用例）
- [ ] manager.start、discover、call_tool 和 close 的非法状态有确定行为；close 幂等，close 后拒绝新调用且不重新创建 event loop。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_manager.py`）

## 既有能力回归

- [ ] AC19：六个内置工具的名称、描述、schema、执行路径和重复保护保持不变。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tools_registry.py tests/test_tool_descriptions.py tests/test_tools_files.py tests/test_tools_command.py tests/test_tools_search.py`）
- [ ] 现有权限黑名单、路径沙箱、规则优先级、三档模式和审批菜单不因动态 MCP 命名空间改变。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_blacklist.py tests/test_permissions_sandbox.py tests/test_permissions_rules.py tests/test_permissions_config.py tests/test_permissions_service.py tests/test_cli.py`）
- [ ] 普通聊天、Plan Mode、Do Mode、Provider 工具格式、工具流式回灌、取消、未知工具阈值和最大迭代行为保持可用。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_session.py tests/test_session_tools.py tests/test_providers.py tests/test_tool_streaming.py tests/test_agent_runner.py tests/test_cli.py`）

## 文档与范围

- [ ] README 和配置示例说明 Python 3.10、两层 merge、两种 transport、`${VAR}`、stdio 环境继承、HTTP headers、`<server>__<tool>`、`server__tool(call)`、失败隔离和关闭语义。（验证：运行 `rg -n "Python 3.10|mcp_servers|transport: stdio|transport: http|Streamable HTTP|server>__<tool|__.*call|失败|关闭" README.md config.example.yaml` 并人工核对）
- [ ] 文档明确说明仅支持 text/structuredContent，不做 Resources、Prompts、Sampling、健康检查、自动重连或运行时动态重载。（验证：运行 `rg -n "structuredContent|Resources|Prompts|Sampling|健康检查|自动重连|动态重载" README.md config.example.yaml`）
- [ ] 源码没有实现资源/提示词/采样发现、Server 健康检查、应用层重连或动态工具重载入口。（验证：运行 `rg -n "list_resources|read_resource|list_prompts|get_prompt|sampling|health.?check|reconnect|reload.*tool" src/mycode/mcp src/mycode/cli.py`，人工确认匹配仅可能是明确拒绝/说明而非实现）
- [ ] `config.example.yaml` 只使用占位环境变量，没有真实 token、Authorization 值或可用私有地址。（验证：人工检查示例，并运行 `rg -n "Bearer [A-Za-z0-9]|api[_-]?key:\s+[^$]|token:\s+[^$]" config.example.yaml`，期望无真实值）

## 编译、测试与代码质量

- [ ] Python 源码编译无语法或导入错误。（验证：运行 `PYTHONPYCACHEPREFIX=/tmp/mycode-pycache PYTHONPATH=src .venv/bin/python -m compileall -q src`）
- [ ] MCP 配置、manager、Tool 和真实传输测试全部通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_config.py tests/test_mcp_manager.py tests/test_mcp_tool.py tests/test_mcp_integration.py`）
- [ ] Registry、权限、工具执行、Agent 与 CLI 集成测试全部通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tools_registry.py tests/test_permissions_config.py tests/test_permissions_rules.py tests/test_permissions_service.py tests/test_agent_tools.py tests/test_agent_executor.py tests/test_tool_executor.py tests/test_agent_runner.py tests/test_cli.py`）
- [ ] 完整项目测试套件全部通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest`）
- [ ] 项目未配置独立 lint 时，以 compileall、完整 pytest 和 diff 检查作为静态质量门禁；若实施期间新增 lint 配置，则对应检查也必须通过。（验证：检查 `pyproject.toml`，运行配置中声明的 lint 命令，如无则记录“不适用”）
- [ ] 补丁无空白错误、调试打印或未完成占位符。（验证：运行 `git diff --check`，再运行 `rg -n "TO""DO|TB""D|breakpoint\(|pdb\.set_trace" src tests README.md config.example.yaml`）
- [ ] 变更范围没有覆盖或删除用户现有权限改动；根目录四份文档已按用户授权替换为本 MCP 功能版本。（验证：比较 T0 基线与最终 `git status --short`、`git diff --stat` 和重叠文件逐项 diff）

## 端到端场景

- [ ] AC21 / 场景 1：配置一个真实 stdio Server、一个真实 Streamable HTTP Server 和一个故障 Server → MewCode 并发启动发现 → 两个可用 Server 的 `<server>__<tool>` 注册 → 故障 Server 只警告 → 两种工具分别通过权限判定 → text 与 structuredContent 回灌 Agent → CLI 退出后无连接、线程或子进程残留。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_integration.py -v` 对应混合场景，并记录进程/资源断言）
- [ ] 场景 2：用户级声明 stdio Server，项目级以同名 HTTP Server 整体覆盖并新增另一个 Server → 仅项目级同名定义生效 → `${VAR}` header 展开 → 两个项目有效工具可调用。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_config.py tests/test_mcp_integration.py -v` 对应覆盖场景）
- [ ] 场景 3：default 模式调用 `server__tool` → 审批目标显示 `call` 且不显示敏感 arguments → 选择本会话同意 → 后续不同参数调用不再审批 → 重启后重新审批。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_service.py tests/test_mcp_tool.py tests/test_cli.py` 对应会话审批场景）
- [ ] 场景 4：活动 stdio/HTTP 会话在首次成功调用后失效 → 后续调用返回带 Server 和稳定原因码的 ToolResult → Agent 收到失败并继续 → Server 初始化计数不增加，证明没有自动重连。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_integration.py -v` 对应 session loss 场景）
- [ ] 场景 5：远端同时返回 text 与不支持的 image/audio/resource block → 结果整体失败 → 二进制或资源内容未进入 ToolResult、日志和 Agent history。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_tool.py tests/test_mcp_integration.py` 对应混合内容场景）

## 验收覆盖索引

| Spec 验收标准 | Checklist 位置 |
|---------------|----------------|
| AC1-AC3 | 配置与合并 |
| AC4-AC7 | 传输、初始化与发现 |
| AC8-AC10 | 工具命名与注册 |
| AC11-AC13、AC20 | 调用、结果与上下文边界 |
| AC14 | 权限与 Agent 集成 |
| AC15-AC18 | 生命周期、隔离与超时 |
| AC19 | 既有能力回归 |
| AC21 | 端到端场景 1 |
