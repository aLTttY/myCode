# MewCode 斜杠命令注册与分发 Checklist

> 每项都通过运行测试、命令或观察终端行为验证。验收依据为已批准的 [`spec.md`](./spec.md)、[`plan.md`](./plan.md) 和 [`task.md`](./task.md)。

## 命令核心

- [x] AC1：命令目录恰有十个可见命令和隐藏 `/new`；每条元数据包含名称、别名、描述、用法、类型、隐藏状态、参数提示和 handler 状态。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_registry.py tests/test_command_builtins.py -q`，观察元数据与数量断言通过）
- [x] AC2：名称—名称、名称—别名、别名—别名、同命令重复别名和仅大小写不同的冲突均在注册时失败；失败注册不覆盖或污染已有项。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_registry.py -q`）
- [x] AC3：空白输入无动作，普通输入只形成 plain 路由，`/HELP status` 解析为 help，参数只去除外围空白并保留内部内容。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_router.py -q`）
- [x] AC4：未知命令、仅 `/`、多词 help 参数和无参数命令携带参数均不发送 Agent 消息，并显示正确用法与 `/help` 引导。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_router.py tests/test_command_builtins.py -q`）
- [x] AC5：使用 FakeCommandUI 可独立观察 local、ui、prompt 三类路径，命令测试不需要真实终端、Provider 或 AgentRunner。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_builtins.py -q`）
- [x] AC6：十个规范名称和全部约定别名均大小写不敏感地命中同一规范命令。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_registry.py tests/test_command_builtins.py -q`）
- [x] AC7：`/cl` + Tab 直接补为 `/clear `；`/s` 显示 session/status；`/p` 优先归一化为 `/plan `；`/n` 不暴露隐藏 new。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_completion.py -q`）
- [x] AC8：`/help` 只列十个可见命令；`/help st` 显示 status 的规范名、别名、类型、描述、用法和参数提示；`/help new` 可显式查询隐藏命令。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_builtins.py -q`）

## 内置命令行为

- [x] AC9：`/compact` 不进入 Agent Loop；无需摘要时不调用 Provider，需要摘要时只调用摘要 Provider，并显示压缩前后估算和可用 Token；摘要格式失败时也保留已收到的 Token。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_builtins.py tests/test_context_summary.py tests/test_context_manager.py tests/test_cli.py -q`）
- [x] AC10：`/clear` 只触发终端清屏；会话 ID、消息、上下文状态、最近 Token 和当前模式在清屏前后相同。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_builtins.py tests/test_cli.py -q`）
- [x] AC11：启动状态栏为 `[DEFAULT]`；`/plan` 后为 `[PLAN]` 且普通输入使用 plan；`/do` 后为 `[DEFAULT]` 且普通输入使用 default；两个切换命令都不调用 Agent。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py -q`，观察模式、AgentRequest 和 toolbar 断言通过）
- [x] AC12：新进程固定从 default 开始；处于 plan 时执行隐藏 `/new`，新会话保持 plan，但最近 Token 被清空。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py -q`）
- [x] AC13：`/session` 显示当前 ID、消息数、new/restored 和上下文概况，不创建或切换会话，不调用 Agent。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_builtins.py tests/test_cli.py -q`）
- [x] AC14：`/memory` 显示项目/用户条目数、两级索引路径、idle/busy 和任务数；输出不含记忆正文且不调用 Provider。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory_worker.py tests/test_command_builtins.py tests/test_cli.py -q`）
- [x] AC15：`/permission` 显示 effective mode、mode source、`session > local > project > user`、配置是否加载及规则数量；执行前后权限决策不变，输出不含规则表达式。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_service.py tests/test_command_builtins.py tests/test_cli.py -q`）
- [x] AC16：模型请求前 `/status` 把 Token 标为 unavailable；请求后显示模式、Provider/模型、权限、会话、最近 Token、上下文和记忆状态；查询过程中 Provider 与 MCP 的调用计数保持 0。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_builtins.py tests/test_cli.py -q`）
- [x] AC17：`/review` 发送固定提示而不是字面量命令，单次使用 plan，只能看到四个只读工具；`read_git_changes` 能提供 staged/unstaged/untracked 状态，审查后工作区无新增修改且持久模式不变。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_builtins.py tests/test_tools_git.py tests/test_agent_tools.py tests/test_cli.py -q`）
- [x] AC18：隐藏 `/new` 仍关闭当前会话并创建新 ID，不进入对话历史，不出现在 help 总览或补全候选，但 `/help new` 可查询。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_builtins.py tests/test_command_completion.py tests/test_cli.py -q`）

## Git 只读工具与架构集成

- [x] `read_git_changes` 的 schema 为空对象且拒绝所有参数；三条 Git 调用使用固定 argv、`shell=False`、工作区 cwd，并禁用 external diff/textconv。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tools_git.py -q`）
- [x] 三条 Git 调用共享一个总截止时间；Git 缺失、非仓库、非零退出、超时和解码异常均返回安全结构化错误。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tools_git.py -q`）
- [x] 大型 Git 差异的显示视图遵守 `max_output_chars`，完整视图进入既有上下文卸载路径，不把截断 JSON 或无界终端输出交给模型。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tools_git.py tests/test_context_integration.py -q`）
- [x] 默认 Registry 含七个内置工具；`read_git_changes` 被分类为 read、出现在 Plan Registry、绕过权限审批，其他六个工具行为不变。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tools_registry.py tests/test_tool_descriptions.py tests/test_agent_tools.py tests/test_agent_executor.py tests/test_permissions_service.py -q`）
- [x] ContextStatus 查询不调用 Provider、不写 ContextStore、不卸载消息、不改变 summary、anchor 或熔断状态。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_context_manager.py tests/test_agent_runner.py -q`）
- [x] MemoryWorker 状态查询不 drain、不等待、不取消；PermissionService 只暴露会话规则数量。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory_worker.py tests/test_permissions_service.py -q`）
- [x] 命令核心不导入 CLI 或具体 Agent，领域模块不导入内置命令，公共模块可以顺序导入且无循环依赖。（验证：运行 `PYTHONPATH=src .venv/bin/python -c "import mycode.commands; import mycode.context; import mycode.memory; import mycode.permissions; import mycode.agent.runner; import mycode.cli"`，期望退出码 0）
- [x] 命令冲突在配置加载、Provider 创建和 MCP 发现前终止启动，且返回退出码 1。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py -k registration_conflict -q`）

## 兼容性与安全

- [x] AC19：`exit`、`quit`、`退出`、等待输入 Ctrl+C、Agent 执行 Ctrl+C、Ctrl+D 和普通中文消息保持原行为。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py -q`）
- [x] AC20：CommandExecutionError 后仍可处理下一次输入；未知 Exception 只显示类型和命令名，不泄露异常正文、API Key、权限规则、记忆正文或 Provider URL。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_router.py tests/test_command_builtins.py tests/test_cli.py -q`）
- [x] PromptSession 使用一个实例、关闭边输入边补全，并可通过 PipeInput/DummyOutput 正确处理中文描述、宽字符、Backspace 和 Tab 菜单。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_completion.py tests/test_cli.py -q`）
- [x] 普通输入、MCP 初始化/关闭、会话恢复、记忆通知、权限审批、ProviderError 和上下文压缩既有回归测试全部通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py tests/test_mcp_integration.py tests/test_session_memory_integration.py tests/test_context_integration.py tests/test_permissions_service.py -q`）

## 编译、测试与文档

- [x] 项目源代码可编译导入，无语法错误。（验证：运行 `PYTHONPATH=src .venv/bin/python -m compileall -q src`，期望退出码 0）
- [x] AC21：注册、路由、内置命令、补全、Git 工具、状态快照和 CLI 集成测试全部通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_registry.py tests/test_command_router.py tests/test_command_builtins.py tests/test_command_completion.py tests/test_tools_git.py tests/test_cli.py -q`）
- [x] 全量自动化测试通过，无现有功能回归。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q`）
- [x] README 不再把 `/plan <任务>`、`/do <任务>` 描述为一次性前缀，并准确列出十个可见命令、别名、状态栏、隐藏 `/new`、`/compact` Provider 边界和第七个只读工具。（验证：运行 `rg -n '/plan|/do|/help|/compact|/review|read_git_changes|七个' README.md` 并人工核对相关段落）
- [x] 代码和文档 diff 无尾随空白或冲突标记，变更中没有测试临时文件、会话文件或真实凭据。（验证：运行 `git diff --check`、`git status --short` 并审阅 `git diff --stat` 与待提交文件列表）

> 项目当前没有配置独立 linter；本阶段以 `compileall`、目标测试、全量 pytest 和 `git diff --check` 作为静态与格式门禁。

## 端到端场景

- [x] AC22：自动化输入依次执行 `/p` → 普通任务 → `/status` → `/review` → `/d` → `/clear` → `/help status` → `exit`。观察到 `[PLAN]`/`[DEFAULT]` 正确切换，普通任务使用 plan，review 单次只读，status 不联网，clear 不丢状态，help 内容正确，且只有普通任务和 review 形成两个 AgentRequest。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py -k slash_command_end_to_end -q`）
- [x] 真实临时 Git 仓库端到端：同时存在 staged、unstaged 和 untracked 变更时，review 链路能先发现三类状态，再用只读文件能力核对内容；结束后 `git status --short` 与执行前一致。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tools_git.py tests/test_cli.py -k 'review or git_changes' -q`）
