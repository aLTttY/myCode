# Mycode 只读自动执行与方向键审批 Checklist

> 每项必须通过自动化测试、静态检查或可观察的 CLI 行为验证。灾难性命令只允许传给权限判定器，禁止交给 shell 实际执行。

## 专用只读工具

- [ ] AC1：`read_file`、`find_files`、`search_code` 在 strict、default、allow 三种模式下均返回 `readonly_allow`，且审批器调用次数为零。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_service.py`）
- [ ] AC2：只读工具命中历史 deny 规则、没有审批器或处于 strict 模式时仍直接执行。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_service.py tests/test_session_tools.py`）
- [ ] AC3：只读工具的无效参数、绝对路径、`..`、项目外符号链接仍被拒绝或跳过，且项目外内容未被读取。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_sandbox.py tests/test_tools_files.py tests/test_tools_search.py`）
- [ ] AC4：`run_command("ls -la")` 不进入只读快速路径；default 模式无规则时调用审批器。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_service.py tests/test_agent_tools.py`）
- [ ] AC5：`write_file`、`edit_file`、`run_command` 被拒绝时工具实现调用次数为零。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tool_executor.py tests/test_session_tools.py`）

## 不可绕过安全层

- [ ] AC6：根目录或用户目录破坏、磁盘覆写或格式化、系统目录递归权限修改、关机重启和 fork bomb 样例全部被判定器硬拒绝，测试不调用 shell。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_blacklist.py`）
- [ ] AC7：strict、default、allow、各层 allow 规则和人工同意均不能覆盖黑名单。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_blacklist.py tests/test_permissions_service.py`）
- [ ] AC8：项目内普通删除、包安装、管道和 Git 强制操作等潜在开发命令不被硬黑名单误拦，继续进入规则、模式或审批层。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_blacklist.py tests/test_permissions_service.py`）
- [ ] AC9：写入和编辑工具拒绝绝对路径、`..` 和项目外符号链接，目标内容不发生变化。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_sandbox.py tests/test_tools_files.py`）
- [ ] AC10：命令中可识别的项目外显式路径、无法规范化路径和项目外符号链接被拒绝，结果给出项目内路径或专用工具建议。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_sandbox.py tests/test_tools_command.py`）

## 规则与权限模式

- [ ] AC11：受控工具的精确规则只匹配完整目标；glob 规则只匹配预期目标。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_rules.py`）
- [ ] AC12：`run_command(git *)` 匹配完整命令；写入和编辑规则匹配规范化相对路径，内容变化不影响规则目标。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_rules.py tests/test_permissions_service.py`）
- [ ] AC13：会话、本地、项目、用户规则冲突时严格使用“会话 > 本地 > 项目 > 用户”。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_rules.py tests/test_permissions_config.py`）
- [ ] AC14：同层精确规则优先于 glob；相同匹配类型下 deny 优先于 allow。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_rules.py`）
- [ ] AC15：受控工具规则未命中时，strict 拒绝、default 审批、allow 放行。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_service.py`）
- [ ] AC16：受控工具命中显式 deny 后不调用审批器，也不受 allow 模式影响。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_service.py`）

## 三选项交互审批

- [ ] AC17：审批界面显示工具名、脱敏目标和原因，并且只出现“不同意、仅本次同意、本会话同意”。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py`，并检查渲染文本）
- [ ] AC18：选择“仅本次同意”只允许当前调用，下一次相同调用重新审批。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_service.py`）
- [ ] AC19：选择“本会话同意”后当前服务实例直接命中；重建服务后规则消失。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_service.py`）
- [ ] AC20：虚拟终端发送上、下方向键可以循环移动高亮，回车提交当前项；发送 `d/o/s/p` 不提交审批。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py`）
- [ ] AC21：完成拒绝、仅本次或本会话审批前后，用户、项目、本地权限文件内容均不变化。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py tests/test_permissions_service.py`）
- [ ] AC22：用户手工写入 `.mycode/permissions.local.yaml` 后，重建权限服务能加载 allow/deny 并作用于受控工具。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_config.py tests/test_permissions_service.py`）
- [ ] AC23：直接回车默认拒绝；Ctrl+C、Ctrl+D、EOF、非 TTY、菜单异常和无审批接口均安全拒绝，但合法只读工具仍自动执行。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py tests/test_permissions_service.py tests/test_session_tools.py`）
- [ ] 审批类型、服务分支和测试中不存在 `allow_permanent` 或 `user_allow_permanent`。（验证：运行 `rg -n "allow_permanent|user_allow_permanent" src tests`，期望无匹配；菜单标签由 `tests/test_cli.py` 证明没有永久选项）
- [ ] CLI 不再构造或向权限服务传入 `LocalRuleStore`，审批路径没有磁盘写入调用。（验证：运行 `rg -n "LocalRuleStore|add_exact_allow" src/mycode/cli.py src/mycode/permissions/service.py src/mycode/permissions/approval.py`，期望无匹配）

## Agent Loop、并发与配置

- [ ] AC24：黑名单、沙箱、规则 deny 和用户拒绝形成带稳定原因码的 `ToolResult(ok=False)` 并写入消息历史。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tool_executor.py tests/test_agent_runner.py tests/test_session_tools.py`）
- [ ] AC25：第一轮受控工具被拒绝后，Agent 进入下一轮，可改用安全工具并最终完成；持续请求也受最大迭代限制。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py`）
- [ ] AC26：多个副作用工具串行；多个专用只读工具并发且不会产生审批提示。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_executor.py tests/test_permissions_service.py`）
- [ ] AC27：用户、项目、本地 YAML 均能加载；缺失配置不影响启动；历史只读规则不阻止只读工具。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_config.py tests/test_cli.py tests/test_permissions_service.py`）
- [ ] AC28：重复键、未知字段、YAML 错误、无效模式、无效规则和未知工具产生可理解错误，受控调用不降级放行。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_config.py tests/test_cli.py`）
- [ ] AC29：普通聊天、Plan Mode、Do Mode、工具流式回灌、取消、未知工具阈值和最大迭代路径通过回归。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_session.py tests/test_tool_streaming.py tests/test_agent_runner.py tests/test_agent_tools.py tests/test_cli.py`）
- [ ] AC30：只读自动执行、路径边界、硬黑名单、规则模式、两种交互放行、无永久同意、方向键菜单、无交互拒绝和拒绝后继续循环均有自动化测试。（验证：运行全部定向测试及完整测试套件）

## 架构与文档一致性

- [ ] 只读工具集合只在共享安全分类模块定义；Agent 和权限服务均复用它。（验证：运行 `rg -n "READ_TOOLS" src/mycode` 并检查不存在重复集合字面量）
- [ ] 所有工具入口共享 `ToolExecutor` 和 `PermissionService`；只读快速路径没有绕过目标校验。（验证：检查调用关系，并运行 `tests/test_tool_executor.py`、`tests/test_session_tools.py`）
- [ ] `run_command`、未知工具、写入和编辑始终分类为有副作用。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_tools.py`）
- [ ] 本地权限文件仍被 Git 忽略，项目共享权限文件不被忽略。（验证：运行 `git check-ignore .mycode/permissions.local.yaml` 应成功；运行 `git check-ignore .mycode/permissions.yaml` 应不匹配）
- [ ] README 和配置示例记录三个自动执行工具、工作区边界、三选项方向键菜单、无永久同意、手工本地规则和命令隐式访问限制。（验证：运行 `rg -n "read_file|find_files|search_code|方向键|permissions.local.yaml|隐式文件访问" README.md config.example.yaml` 并人工核对）
- [ ] 文档不再宣称所有只读调用需要权限审批，也不包含旧 `[d]/[o]/[s]/[p]` 菜单。（验证：运行 `rg -n "只读工具仍经过权限|\[d\]|\[o\]|\[s\]|\[p\]" README.md config.example.yaml`，期望无匹配）

## 编译与测试

- [ ] Python 源码编译无语法或导入错误。（验证：运行 `PYTHONPYCACHEPREFIX=/tmp/mycode-pycache PYTHONPATH=src .venv/bin/python -m compileall -q src`）
- [ ] 权限和审批定向测试全部通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_blacklist.py tests/test_permissions_sandbox.py tests/test_permissions_rules.py tests/test_permissions_config.py tests/test_permissions_service.py tests/test_cli.py`）
- [ ] 工具和 Agent 集成测试全部通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tools_files.py tests/test_tools_search.py tests/test_tool_executor.py tests/test_agent_tools.py tests/test_agent_executor.py tests/test_session_tools.py tests/test_agent_runner.py`）
- [ ] 完整项目测试全部通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest`）
- [ ] 补丁无空白错误，实现和用户文档中无新增未完成占位符。（验证：运行 `git diff --check`，再运行 `rg -n "TO""DO|TB""D" src tests README.md config.example.yaml`）

## 端到端场景

- [ ] 场景 1：default/strict 模式下 Agent 调用 `read_file` → 不显示审批 → 返回真实内容 → Agent 正常答复。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py tests/test_session_tools.py`）
- [ ] 场景 2：Agent 调用 `run_command("ls -la")` → 显示三选项菜单 → 下键选择“仅本次同意”并回车 → 命令执行 → 相同命令下次再次审批。（验证：使用虚拟终端集成测试运行 `tests/test_cli.py tests/test_permissions_service.py`）
- [ ] 场景 3：Agent 调用未匹配的写入工具 → 下键两次选择“本会话同意” → 当前会话相同目标不再审批 → 重启后重新审批，所有权限 YAML 均未变化。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py tests/test_permissions_service.py` 并比较临时配置文件内容）
- [ ] 场景 4：用户手工写入本地 allow 规则 → 重启 Mycode → 受控目标无需审批；手工 deny 目标保持拒绝。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_config.py tests/test_permissions_service.py`）
- [ ] 场景 5：allow 模式或高优先级 allow 尝试放行 `rm -rf /` 或项目外路径 → 硬安全层拒绝 → 工具实现不执行 → Agent 得到清晰结果并收尾。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_blacklist.py tests/test_permissions_sandbox.py tests/test_permissions_service.py tests/test_tool_executor.py tests/test_agent_runner.py`）

## 范围核对

- [ ] 未实现 shell 只读命令识别；`run_command` 始终受控。（验证：检查共享安全分类和权限服务测试）
- [ ] 未新增网络限制、资源配额、审计日志、GUI 或容器化。（验证：检查 `git diff --stat` 和新增依赖）
- [ ] 未宣称命令工具具有完整 OS 文件隔离；文档仍只承诺检查可识别显式路径。（验证：检查 README 与 `src/mycode/permissions/sandbox.py`）

## 本次验收记录

- [x] Python 编译通过。证据：使用 `/tmp/mycode-pycache` 运行 `compileall`，退出码为 0。
- [x] 完整测试通过。证据：`203 passed in 1.89s`。
- [x] 补丁格式通过。证据：`git diff --check` 无输出。
- [x] 永久审批已移除。证据：在 `src`、`tests` 中搜索 `allow_permanent|user_allow_permanent` 无匹配。
- [x] 审批持久化接线已移除。证据：在 CLI、权限服务和审批模块中搜索 `LocalRuleStore|add_exact_allow` 无匹配。
- [x] 旧字母菜单已移除。证据：README 和配置示例中搜索 `[d]/[o]/[s]/[p]` 无匹配。
- [x] 手工本地规则保留。证据：配置加载测试通过，`.mycode/permissions.local.yaml` 仍由 Git 忽略。
