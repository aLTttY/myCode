# MyCode Skill 系统 Checklist

> 每项都必须通过运行测试、命令或观察行为来验证。验收依据为已批准的 [`spec.md`](./spec.md)、[`plan.md`](./plan.md) 和 [`task.md`](./task.md)。开发完成前保持未勾选，验收时逐项记录实际证据。

## Skill 发现与定义

- [ ] AC1：项目、用户、内置三个层级存在同名 Skill 时只选择项目定义；逐层移除后依次回退到用户和内置定义。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_catalog.py -k 'priority or override or fallback' -q`）
- [ ] AC2：高优先级同名文件解析失败时产生安全警告，低优先级有效定义继续生效，其他 Skill 不受影响。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_catalog.py -k 'invalid and fallback or parse_isolation' -q`）
- [ ] AC3：单文件与带 `SKILL.md`、tool YAML、Python 脚本的目录包均可发现；缺失入口、非法 YAML、未知字段、空正文、非法模式/history/model 组合只跳过对应定义。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_parser.py tests/test_skill_catalog.py -k 'single or directory or invalid or strict or field or history or model' -q`）
- [ ] AC4：同层重名以及 Skill 名与固定命令/别名冲突都在交互前终止启动，并指出安全来源；失败不会创建部分命令或运行时状态。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_catalog.py tests/test_cli.py -k 'duplicate or reserved or command_conflict' -q`）
- [ ] AC5：生效白名单引用不存在的内置、MCP 或本 Skill 专属工具时启动失败；MCP 发现失败会让依赖它的 Skill 失败；任何合法白名单仍保留 `load_skill`。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_catalog.py tests/test_mcp_integration.py tests/test_skill_runtime.py -k 'unknown_tool or missing_mcp or load_skill' -q`）
- [ ] frontmatter 使用 `name`、`description`、`allowed_tools`、`mode`、`history`、`model` 的严格规则；共享模式禁止 history/model，独立模式要求非负 history，未知字段不被静默忽略。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_parser.py -k 'frontmatter or strict or shared or isolated' -q`）
- [ ] 专属工具局部名稳定暴露为 `<skill>__<tool>`，不同 Skill 的同名局部工具可同时存在，最终名称超过 64 字符会被拒绝。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_parser.py tests/test_skill_tools.py -k 'namespace or exposed_name or length' -q`）
- [ ] 内置 `commit.md`、`review.md`、`test.md` 能通过 `importlib.resources` 从包资源读取，不依赖源码工作目录。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_catalog.py -k 'builtin or package_resource' -q`）

## 两阶段加载与共享激活

- [ ] AC6：首次请求只出现所有生效 Skill 的名称和说明；不含 SOP、专属 schema、脚本内容或被覆盖定义。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_prompts.py tests/test_agent_runner.py -k 'skill_catalog or two_stage or unloaded' -q`）
- [ ] AC7：模型调用 `load_skill` 后，下一 Agent 迭代出现完整 SOP 和对应工具；未知、失效或加载失败返回结构化错误且循环可继续。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py tests/test_skill_tools.py -k 'load_skill or next_iteration or recoverable' -q`）
- [ ] AC8：两个共享 Skill 按首次激活顺序在每次请求和迭代重建；重复加载不重复；上下文压缩后 SOP 仍完整且未被摘要改写。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_runtime.py tests/test_agent_runner.py tests/test_context_integration.py -k 'active_order or duplicate_activation or compaction or skill_prompt' -q`）
- [ ] AC9：共享 Skill 的 user/assistant/tool 消息进入主历史；`/clear` 不清激活，`/new` 清除全部激活和专属工具。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py tests/test_cli.py -k 'shared_history or clear or new_session or reset_skill' -q`）
- [ ] AC10：无激活时提供原完整工具集；多 Skill 激活后仅提供白名单并集与 loader；Plan Mode 再移除有副作用业务工具，权限拒绝仍生效。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_runtime.py tests/test_agent_tools.py tests/test_permissions_service.py -k 'union or projection or plan or denied' -q`）
- [ ] AC11：目录工具加载前 schema 不可见，加载后按白名单出现，停用或 `/new` 后移除；调用会审批并安全处理拒绝、超时、超量输出和错误。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_tools.py tests/test_skill_integration.py -k 'dedicated or visibility or approval or timeout or too_large' -q`）
- [ ] `load_skill` 始终是串行系统工具并自动允许，但其实现本身不读写文件、不运行命令、不发网络请求；业务副作用仍由对应工具单独审批。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_tools.py tests/test_permissions_service.py tests/test_agent_tools.py -k 'load_skill or system_tool' -q`）

## 独立执行与参数边界

- [ ] AC12：`history: 0` 只传本次输入；`history: 2` 传最近两个完整已完成轮次；工具调用链不拆散，系统提示、摘要边界和主会话激活 SOP 不复制。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_context_manager.py tests/test_skill_isolated.py -k 'history or complete_turn or tool_chain or system_prompt' -q`）
- [ ] AC13：未指定模型沿用主模型；指定模型只替换同一 Provider 的 model；模型不可用或请求失败回流确定性失败摘要且主会话继续可用。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_isolated.py tests/test_providers.py -k 'model or provider_failure or failure_summary' -q`）
- [ ] AC14：独立完成后主历史只增加可识别调用与最终摘要，中间模型文本和工具消息不出现；下一次独立调用看不到上次临时上下文。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_isolated.py tests/test_session_memory_integration.py -k 'main_history or summary or isolation or fresh_context' -q`）
- [ ] AC15：独立上下文可以临时加载共享 Skill，且只在该上下文生效；再次调用独立 Skill 返回可恢复的 `nested_isolated_not_supported`，不创建嵌套 Agent。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_isolated.py tests/test_agent_runner.py -k 'nested or temporary_shared' -q`）
- [ ] AC16：普通文本、换行、Markdown 和伪系统指令作为 `{{input}}` 数据时始终保持 user 角色；多个占位符引用同一输入，无占位符时输入仍被传入。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_parser.py tests/test_prompts.py tests/test_skill_isolated.py -k 'placeholder or input_role or injection' -q`）
- [ ] 临时独立 Agent 不挂主 SessionJournal 或 MemoryWorker，结束、失败和取消路径都关闭 ContextManager 并清理临时上下文文件。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_isolated.py tests/test_session_memory_integration.py -k 'journal or memory or cleanup or cancelled' -q`）
- [ ] 独立执行的最终 assistant 文本直接回流，不产生第二次总结请求；没有最终文本、取消、超限和 Provider 错误使用系统生成的失败摘要。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_isolated.py -k 'single_pass or final_summary or deterministic_failure' -q`）

## 斜杠命令与热更新

- [ ] AC17：所有生效 Skill 注册为 `/<name> [input]` 并出现在 help/Tab；单项帮助只显示来源、说明、模式、history/model；项目覆盖后命令指向项目定义。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_commands.py tests/test_command_completion.py -k 'help or completion or override or metadata' -q`）
- [ ] AC18：`/review` 与 `/rev` 都调用当前生效的 review Skill，原始斜杠文本不进历史；其他固定命令和别名保持原行为。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_commands.py tests/test_command_builtins.py tests/test_cli.py -k 'review or rev or fixed_command' -q`）
- [ ] AC19：运行时新增 Skill 后，下一轮目录/help/补全可见；修改说明、SOP、白名单、专属工具或优先级后，下一轮统一使用新定义。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_catalog.py tests/test_skill_runtime.py tests/test_cli.py -k 'hot_reload or added or modified or higher_priority' -q`）
- [ ] AC20：已激活定义删除、非法或改为 isolated 后立即停用并警告；低优先级回退不自动激活；修复后只重新进入目录。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_runtime.py tests/test_cli.py -k 'deactivate or downgrade or repaired or mode_change' -q`）
- [ ] AC21：热更新引入非法文件、同层重名或未知工具时只隔离问题名称，其他合法更新仍发布；目录、命令、提示、权限动态工具集合始终来自同一快照。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_catalog.py tests/test_skill_commands.py tests/test_skill_integration.py -k 'atomic or invalid_refresh or snapshot_consistency' -q`）
- [ ] 动态命令替换在完整冲突校验后原子发布；失败时旧路由、help 和补全结果完全不变。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_registry.py tests/test_skill_commands.py -k 'replace_dynamic or atomic' -q`）

## 内置样板

- [ ] AC22：内置 commit 先检查 Git 变化、生成提交说明、运行必要验证，并只在权限允许时创建提交；被拒绝时不修改仓库且不声称成功。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_catalog.py tests/test_skill_integration.py -k 'builtin_commit or commit_denied' -q`）
- [ ] AC23：内置 review 使用 isolated/history 0 和只读白名单，报告缺陷/回归/安全/测试缺口；主历史只收到摘要，执行前后工作区状态一致。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_integration.py tests/test_tools_git.py -k 'builtin_review or review_readonly' -q`）
- [ ] AC24：内置 test 识别并运行相关测试、报告真实结果；默认白名单不含 write/edit，未明确要求修复时产品代码无变化。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_catalog.py tests/test_skill_integration.py -k 'builtin_test or test_readonly_files' -q`）
- [ ] 项目和用户同名定义均可按三级优先级覆盖三个内置样板，`/rev` 始终跟随生效 review。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_catalog.py tests/test_skill_commands.py -k 'builtin_override or rev' -q`）

## 架构、安全与兼容性

- [ ] Snapshot 及内部映射不可由调用方修改；Catalog 只有在候选完整校验后发布，独立调用在开始时固定 Snapshot。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_catalog.py tests/test_skill_runtime.py tests/test_skill_isolated.py -k 'immutable or snapshot' -q`）
- [ ] `AgentRunner` 只依赖独立执行 Protocol，`skills.isolated` 可复用 Runner 而无循环导入；公共模块可顺序导入。（验证：运行 `PYTHONPATH=src .venv/bin/python -c "import mycode.skills; import mycode.skills.isolated; import mycode.agent.runner; import mycode.commands; import mycode.cli"`，期望退出码 0）
- [ ] Python 工具使用 `sys.executable`、argv 和 `shell=False`；脚本/manifest 不允许绝对路径、符号链接或包目录逃逸。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_parser.py tests/test_skill_tools.py -k 'path or symlink or shell or argv' -q`）
- [ ] Python 工具子进程只获得最小环境和受限 JSON 上下文，不继承测试哨兵 API Key；stdout/stderr 有界，错误不泄露输入、SOP、脚本正文或凭据。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_tools.py -k 'environment or secret or output or safe_error' -q`）
- [ ] 专属工具一律走 side-effect 权限目标 `call`，strict/default/allow 和会话审批行为正确；白名单只影响可见性，不授予权限。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_tools.py tests/test_permissions_service.py -k 'dedicated or call or strict or default or allow' -q`）
- [ ] OpenAI、Anthropic、DeepSeek 的 Skill 目录、激活 SOP、历史工具消息和独立摘要请求转换均合法。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_providers.py tests/test_skill_isolated.py tests/test_context_integration.py -q`）
- [ ] 普通 Agent、MCP 初始化/关闭、上下文压缩、会话恢复、长期记忆、权限审批、取消和流式输出既有行为无回归。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py tests/test_mcp_integration.py tests/test_context_integration.py tests/test_session_memory_integration.py tests/test_permissions_service.py tests/test_tool_streaming.py -q`）
- [ ] 恢复历史会话时消息被恢复但 Skill 激活集合为空；`/new` 清激活，正常退出不额外持久化激活状态。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py tests/test_session_loader.py tests/test_skill_integration.py -k 'restore or new_session or activation' -q`）

## 编译、测试与文档

- [ ] 项目源代码可编译导入，无语法错误。（验证：运行 `PYTHONPATH=src .venv/bin/python -m compileall -q src`，期望退出码 0）
- [ ] Skill 解析、Catalog、Runtime、工具、独立执行、命令和集成测试全部通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_parser.py tests/test_skill_catalog.py tests/test_skill_runtime.py tests/test_skill_tools.py tests/test_skill_isolated.py tests/test_skill_commands.py tests/test_skill_integration.py -q`）
- [ ] AC27：全量自动化测试通过，现有 Provider、MCP、权限、上下文、会话、命令、记忆和 Agent 测试无回归。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q`）
- [ ] README 准确记录三级目录、frontmatter、两种能力包、工具 JSON 协议、共享/独立模式、白名单、热更新、动态命令和三个内置样板，不再把 review 描述为固定提示命令。（验证：运行 `rg -n 'skills|SKILL.md|allowed_tools|shared|isolated|load_skill|commit|review|test|热更新' README.md` 并人工核对相关段落）
- [ ] `pyproject.toml` 包含内置 Markdown package data，资源测试从非仓库工作目录仍可读取。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_catalog.py -k 'package_resource or builtin' -q`）
- [ ] 代码和文档 diff 无尾随空白或冲突标记，变更中没有测试临时目录、会话文件、上下文卸载文件或真实凭据。（验证：运行 `git diff --check`、`git status --short`，审阅 `git diff --stat` 和全部待提交文件）

> 项目当前没有配置独立 linter；本阶段以 `compileall`、目标测试、全量 pytest 和 `git diff --check` 作为静态与格式门禁。

## 端到端场景

- [ ] AC25：共享场景依次执行 `/commit <要求>`、加载另一个共享 Skill、检查工具并集、执行 `/clear`、执行 `/new`；观察到 SOP 从首个请求生效、完整历史保留、clear 不清激活、new 清空全部状态。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_integration.py tests/test_cli.py -k 'shared_end_to_end' -q`）
- [ ] AC26：已有历史和共享 Skill 激活时执行 `/review`；独立上下文使用 history 0 和只读工具，结束后只回流摘要，主共享激活状态和工作区保持不变。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_integration.py tests/test_cli.py -k 'isolated_end_to_end or review_end_to_end' -q`）
- [ ] 目录工具场景依次观察未加载 schema、加载后的命名空间工具、审批执行结果、热更新脚本和停用后的移除；每一步提示/命令/权限/工具来自同一 Snapshot。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_integration.py -k 'directory_tool_end_to_end' -q`）
- [ ] 热更新场景依次新增、同源修改、更高优先级覆盖、删除降级、非法冲突和修复；无需重启且每次下一轮状态符合激活规则。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_integration.py tests/test_cli.py -k 'hot_reload_end_to_end' -q`）
