# Mycode 只读自动执行与方向键审批 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mycode/tool_safety.py` | 集中定义专用只读工具集合并避免权限/工具循环导入 |
| 修改 | `src/mycode/agent/tools.py` | 复用共享分类，保持 Plan Mode 和批处理语义 |
| 修改 | `src/mycode/permissions/models.py` | 删除交互式永久审批结果 |
| 修改 | `src/mycode/permissions/service.py` | 增加只读快速路径并移除审批持久化分支 |
| 修改 | `src/mycode/permissions/approval.py` | 实现三选项方向键审批菜单 |
| 修改 | `src/mycode/cli.py` | 接入新菜单并解除审批链路与本地规则写入器的连接 |
| 修改 | `src/mycode/tools/search.py` | 阻止查找和搜索读取项目外符号链接 |
| 修改 | `tests/test_agent_tools.py` | 验证共享分类和只读注册表 |
| 修改 | `tests/test_permissions_service.py` | 验证只读快速路径、三种审批结果和受控权限 |
| 修改 | `tests/test_cli.py` | 验证方向键、回车、默认拒绝和异常降级 |
| 修改 | `tests/test_permissions_config.py` | 验证手工本地规则仍可加载 |
| 修改 | `tests/test_tool_executor.py` | 验证只读执行及拒绝工具不进入实现层 |
| 修改 | `tests/test_agent_executor.py` | 验证只读并发无审批、副作用调用仍串行 |
| 修改 | `tests/test_permissions_sandbox.py` | 验证只读目标的路径边界 |
| 修改 | `tests/test_tools_search.py` | 验证项目外符号链接不被查找或读取 |
| 修改 | `tests/test_session_tools.py` | 验证无审批会话仍可执行合法只读工具 |
| 修改 | `tests/test_agent_runner.py` | 验证 Agent 中只读执行和受控拒绝回灌 |
| 修改 | `README.md` | 说明只读自动执行、三选项菜单和手工本地规则 |
| 修改 | `config.example.yaml` | 补充只读规则及手工本地规则说明 |

## T1：建立共享工具安全分类

**文件：** `src/mycode/tool_safety.py`、`src/mycode/agent/tools.py`、`tests/test_agent_tools.py`

**依赖：** 无

**步骤：**

1. 新建不依赖 Agent 或权限模块的共享安全分类模块。
2. 使用不可变集合声明 `read_file`、`find_files`、`search_code`。
3. 提供安全分类和只读判断函数；未知工具默认归为有副作用。
4. 让 Agent 批处理和 Plan Mode 注册表复用共享分类。
5. 验证 `run_command`、写入、编辑和未知工具不会被误判为只读。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_tools.py
```

期望：共享分类、批次分组和 Plan Mode 工具集合测试全部通过。

## T2：实现权限服务只读快速路径

**文件：** `src/mycode/permissions/service.py`、`tests/test_permissions_service.py`

**依赖：** T1

**步骤：**

1. 保留权限目标解析作为所有工具授权的第一步。
2. 目标校验成功后，对共享集合中的工具返回 `readonly_allow`。
3. 确认只读调用不进入规则、模式或审批器。
4. 保持写入、编辑、终端、黑名单和路径沙箱的现有顺序。
5. 覆盖 strict/default/allow、历史只读 deny、无审批器和 `run_command("ls -la")` 场景。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_service.py tests/test_permissions_rules.py tests/test_permissions_blacklist.py
```

期望：三个专用只读工具直接允许；终端查看命令仍受控；黑名单与受控规则测试通过。

## T3：加固只读工具工作区边界

**文件：** `src/mycode/tools/search.py`、`tests/test_permissions_sandbox.py`、`tests/test_tools_search.py`

**依赖：** T2

**步骤：**

1. 保持只读工具的参数和搜索范围校验。
2. 递归遍历候选文件时解析真实路径并确认仍在工作区。
3. `find_files` 不返回项目外符号链接文件。
4. `search_code` 不打开或读取项目外符号链接文件。
5. 添加绝对路径、`..`、项目外链接及项目内合法链接测试。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_sandbox.py tests/test_tools_files.py tests/test_tools_search.py
```

期望：合法项目内读取成功，越界读取被拒绝或跳过，项目外内容不出现在结果中。

## T4：移除交互式永久同意

**文件：** `src/mycode/permissions/models.py`、`src/mycode/permissions/service.py`、`src/mycode/cli.py`、`tests/test_permissions_service.py`、`tests/test_permissions_config.py`

**依赖：** T2

**步骤：**

1. 从 `ApprovalChoice` 删除 `allow_permanent`。
2. 从权限服务删除永久审批分支和本地规则写入器依赖。
3. 从 CLI 权限服务构造过程移除 `LocalRuleStore` 接线。
4. 确认审批结果只可能拒绝、允许本次或创建内存会话规则。
5. 保留用户、项目、本地 YAML 加载以及本地规则优先级。
6. 验证手工写入 `.mycode/permissions.local.yaml` 的 allow/deny 在重新加载后仍生效。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_service.py tests/test_permissions_config.py tests/test_cli.py
rg -n "allow_permanent|user_allow_permanent" src tests
```

期望：审批链路不存在永久结果或持久化分支；手工本地规则测试通过。`rg` 不应在实现和有效测试中找到遗留永久审批标识。

## T5：实现三选项方向键审批菜单

**文件：** `src/mycode/permissions/approval.py`、`src/mycode/cli.py`、`tests/test_cli.py`

**依赖：** T4

**步骤：**

1. 使用现有 `prompt_toolkit` 创建非全屏内联菜单，不新增依赖。
2. 菜单只显示“不同意、仅本次同意、本会话同意”。
3. 默认高亮“不同意”；上下方向键循环移动；回车确认。
4. 不为 `d`、`o`、`s`、`p` 或其他普通字母绑定提交动作。
5. `Ctrl+C`、`Ctrl+D`、EOF、非 TTY 和菜单异常统一返回拒绝。
6. 保留工具名、脱敏目标和审批原因输出，并在菜单结束后清理临时渲染。
7. 通过可注入输入/输出或选择器测试真实按键序列，无需人工参与。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py
```

期望：上、下、回车、默认拒绝、字母不提交、取消/EOF/非交互拒绝和无永久选项测试全部通过。

## T6：验证执行入口、并发和 Agent 收尾

**文件：** `tests/test_tool_executor.py`、`tests/test_agent_executor.py`、`tests/test_session_tools.py`、`tests/test_agent_runner.py`

**依赖：** T3、T4、T5

**步骤：**

1. 验证无审批器时合法只读工具可以执行。
2. 验证受控工具被拒绝后不调用工具实现。
3. 验证多个只读调用并发执行且审批器调用次数为零。
4. 验证写入、编辑和终端调用保持串行。
5. 验证无审批 ChatSession 可以读取，但未授权受控工具仍拒绝。
6. 验证 Agent 获得真实只读结果后完成；受控拒绝结构化回灌并在上限内收尾。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_tool_executor.py tests/test_agent_executor.py tests/test_session_tools.py tests/test_agent_runner.py
```

期望：只读执行、受控拒绝、并发、结果回灌和 Agent 收尾场景全部通过。

## T7：更新用户文档和配置说明

**文件：** `README.md`、`config.example.yaml`

**依赖：** T3、T5

**步骤：**

1. 说明三个专用只读工具无需规则、模式或审批。
2. 说明只读工具仍受参数和工作区边界保护。
3. 说明历史只读规则不影响专用只读工具执行。
4. 说明 `run_command` 即使查看文件也仍受控。
5. 把四选项字母输入说明替换为三选项方向键菜单。
6. 明确交互审批不会写入权限文件，但用户仍可手工维护本地 YAML。

**验证：**

```bash
rg -n "read_file|find_files|search_code|run_command|方向键|本会话|permissions.local.yaml" README.md config.example.yaml
rg -n "\[d\]|\[o\]|\[s\]|\[p\]|永久同意" README.md config.example.yaml
```

期望：新行为说明完整；第二条搜索不应发现旧字母菜单或永久同意说明。

## T8：全量回归和变更检查

**文件：** 全部变更文件

**依赖：** T1-T7

**步骤：**

1. 编译 Python 源码并检查导入关系。
2. 运行完整测试套件。
3. 检查补丁空白错误和未完成占位符。
4. 对照 `spec.md` AC1-AC30 逐项收集证据。
5. 确认没有扩展到 shell 只读识别、网络沙箱或其他未批准范围。

**验证：**

```bash
PYTHONPYCACHEPREFIX=/tmp/mycode-pycache PYTHONPATH=src .venv/bin/python -m compileall -q src
PYTHONPATH=src .venv/bin/python -m pytest
git diff --check
rg -n "TO""DO|TB""D" src tests README.md config.example.yaml
```

期望：编译、全量测试和补丁检查通过；实现和用户文档中没有新增未完成占位符。

## 执行顺序

```text
T1 → T2
      ├→ T3 ─────┬→ T6 ─┐
      └→ T4 → T5 ┘      ├→ T8
           T3 + T5 → T7 ┘
```

T3 与 T4 可在 T2 后分别推进；T5 依赖永久审批移除完成；T6 汇总执行入口行为，T7 更新文档，最终由 T8 全量验收。
