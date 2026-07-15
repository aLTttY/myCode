# Mycode 五层权限系统 Checklist

> 每项都必须通过运行测试、检查配置文件或观察 CLI 行为验证。危险命令只允许传给权限判定器测试，禁止实际执行。

## 不可绕过安全层

- [ ] AC1：所有已注册工具在实现执行前都经过权限判定，被拒绝的工具实现调用次数为零。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tool_executor.py tests/test_tools_registry.py`）
- [ ] AC2：根目录或用户目录破坏、磁盘覆写或格式化、系统目录递归权限修改、关机重启和 fork bomb 样例全部被黑名单判定器拒绝。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_blacklist.py`，确认测试不调用 shell）
- [ ] AC3：strict、default、allow、各层 allow 规则和人工放行均不能覆盖黑名单。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_blacklist.py tests/test_permissions_service.py`）
- [ ] AC4：普通删除项目内文件、包安装或管道命令等可能合理的开发操作不被硬黑名单直接命中，仍进入规则、模式或审批层。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_blacklist.py tests/test_permissions_service.py`）
- [ ] AC5：文件工具拒绝绝对路径、`..` 越界和解析到项目外的符号链接，且目标文件内容不发生变化。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_sandbox.py tests/test_tools_files.py`）
- [ ] AC6：命令中的可识别项目外显式路径、无法规范化路径和项目外符号链接被拒绝，错误结果建议使用项目内路径或专用工具。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_sandbox.py tests/test_tools_command.py`）

## 规则与权限模式

- [ ] AC7：无通配符规则只匹配完整目标；包含 `*`、`?` 或字符类的规则按大小写敏感 glob 匹配，且不命中无关目标。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_rules.py`）
- [ ] AC8：`run_command(git *)` 匹配完整命令；文件规则匹配规范化相对路径；文件内容和搜索 query 的变化不改变路径规则结果。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_rules.py tests/test_permissions_service.py tests/test_tools_search.py`）
- [ ] AC9：会话、本地、项目、用户层存在冲突时，结果严格符合“会话 > 本地 > 项目 > 用户”。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_rules.py tests/test_permissions_config.py`）
- [ ] AC10：同层精确规则优先于 glob；相同匹配类型下 deny 优先于 allow。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_rules.py`）
- [ ] AC11：所有规则未命中时，strict 拒绝、default 请求审批、allow 放行。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_service.py`）
- [ ] AC12：任意显式 deny 命中后不调用审批器，也不受 allow 模式影响。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_service.py`）

## 人在回路与持久化

- [ ] AC13：default 模式审批提示可观察到工具名、安全处理后的目标、判定原因，以及拒绝、本次、本会话、永久四种选择。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py tests/test_permissions_service.py`）
- [ ] AC14：本次放行只允许当前调用，随后相同调用会重新经过规则或审批。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_service.py`）
- [ ] AC15：本会话放行在当前权限服务实例中直接命中；重建服务后该规则消失。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_service.py`）
- [ ] AC16：永久放行去重写入 `.mycode/permissions.local.yaml`；重建服务后仍命中，项目和用户配置保持不变。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_config.py tests/test_permissions_service.py`）
- [ ] AC17：CLI 能收集真实审批选择；无审批接口、EOF 或非交互调用会安全拒绝待审批请求。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py tests/test_permissions_service.py tests/test_session_tools.py`）

## Agent Loop 与集成

- [ ] AC18：黑名单、沙箱、规则 deny 和用户拒绝均形成包含稳定原因码的 `ToolResult(ok=False)` 并写入消息历史。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tool_executor.py tests/test_agent_runner.py tests/test_session_tools.py`）
- [ ] AC19：模型第一轮工具调用被拒绝后，Agent Loop 进入下一轮，模型能选择安全替代方案并正常完成。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py`）
- [ ] AC20：多个有副作用工具继续串行判定和执行；并发只读调用不会产生重叠审批或重复永久写入。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_executor.py tests/test_permissions_service.py`）
- [ ] AC21：用户、项目、本地 YAML 均能加载；任一或全部可选文件不存在时启动仍正常。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_config.py tests/test_cli.py`）
- [ ] AC22：重复键、未知字段、YAML 语法错误、无效模式、未知结果、无效规则和未知工具名产生可理解配置错误，且不会降级放行。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_config.py tests/test_cli.py`）
- [ ] AC23：普通聊天、Plan Mode、Do Mode、工具流式回灌、用户取消、未知工具阈值和最大迭代次数继续通过回归测试。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_session.py tests/test_tool_streaming.py tests/test_agent_runner.py tests/test_cli.py`）
- [ ] AC24：自动化测试覆盖不可绕过层、规则与模式、三种放行范围、无交互拒绝和拒绝后继续循环。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_blacklist.py tests/test_permissions_sandbox.py tests/test_permissions_rules.py tests/test_permissions_config.py tests/test_permissions_service.py tests/test_agent_runner.py`）

## 架构与配置一致性

- [ ] 所有工具入口共享统一 PermissionService，不存在 AgentRunner 或 ChatSession 绕过 ToolExecutor 权限门禁的路径。（验证：运行 `rg -n "ToolExecutor|PermissionService" src/mycode` 并结合 `tests/test_tool_executor.py`、`tests/test_session_tools.py` 的结果检查）
- [ ] 黑名单模式只存在于代码常量，不接受 YAML 注入、删除或覆盖。（验证：检查 `src/mycode/permissions/blacklist.py` 与配置解析允许字段，并运行权限配置测试）
- [ ] 权限模式来源符合 CLI > 本地 > 项目 > 用户 > default，且与 Plan/Do Agent 模式使用不同字段和类型。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_config.py tests/test_cli.py tests/test_agent_runner.py`）
- [ ] 本地权限文件被忽略，项目共享权限文件未被忽略。（验证：运行 `git check-ignore .mycode/permissions.local.yaml` 应成功；运行 `git check-ignore .mycode/permissions.yaml` 应不匹配）
- [ ] README 明确记录三层配置、会话优先级、三档模式、四种审批决定、不可覆盖层和命令隐式访问限制。（验证：运行 `rg -n "permissions\.yaml|permissions\.local\.yaml|strict|default|allow|隐式文件访问" README.md`）
- [ ] 文档和用户可见文案统一使用 `Mycode`。（验证：运行 `rg -n "Mycode" spec.md plan.md task.md checklist.md README.md config.example.yaml` 并人工确认命名一致）

## 编译与测试

- [ ] Python 源码可编译，无语法或导入错误。（验证：运行 `PYTHONPATH=src .venv/bin/python -m compileall -q src`）
- [ ] 权限模块全部定向测试通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_blacklist.py tests/test_permissions_sandbox.py tests/test_permissions_rules.py tests/test_permissions_config.py tests/test_permissions_service.py`）
- [ ] 全部项目测试通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest`）
- [ ] 变更不存在空白错误或未解决占位符。（验证：运行 `git diff --check`，再运行 `rg -n "TODO|TBD" spec.md plan.md task.md checklist.md src tests README.md config.example.yaml || true`）

## 端到端场景

- [ ] 场景 1：default 模式下模型请求未命中规则的工具 → 用户拒绝 → 拒绝结果回灌 → 模型下一轮改用已允许的安全工具 → 任务完成。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py tests/test_cli.py`）
- [ ] 场景 2：用户选择永久放行 → 本地 YAML 原子写入精确 allow → 重建权限服务 → 相同工具目标无需再次审批。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_config.py tests/test_permissions_service.py`）
- [ ] 场景 3：allow 模式和高优先级 allow 规则尝试放行黑名单命令或项目外符号链接 → 不可覆盖安全层仍拒绝，工具实现不执行。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_blacklist.py tests/test_permissions_sandbox.py tests/test_permissions_service.py tests/test_tool_executor.py`）
- [ ] 场景 4：Plan Mode 只向模型暴露只读工具 → 只读调用仍经过权限判定 → 获准后执行并返回结果。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py tests/test_agent_tools.py`）

## 已知限制核对

- [ ] 实现和文档没有宣称命令工具具备完整运行时文件系统隔离；只承诺检查可识别的显式路径。（验证：检查 README 与 `src/mycode/permissions/sandbox.py`，对照 `spec.md` F5 和 `plan.md`“已知限制与后续工作”）
- [ ] 网络限制、资源配额、审计日志、GUI 和容器化没有混入本阶段实现。（验证：检查变更文件清单和 `git diff --stat`，对照 spec“ 不做的事”）
