# 生命周期 Hook Checklist

> 每项必须通过运行测试或观察实际行为验证；未取得证据前不得勾选。

## 配置加载与集中校验

- [x] AC1：用户、项目、本地三层规则全部加载，并按“用户 → 项目 → 本地 → 文件声明顺序”触发；任意文件缺失不影响启动。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_config.py tests/test_hooks_runtime.py`）
- [x] AC2：缺少 event/action、未知事件/字段、非法 all/any、非法正则、动作字段错误、非法异步和 `session_end` prompt 均在启动期报告文件、1-based 规则序号和字段。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_config.py`）
- [x] AC2：三层任一配置非法时不返回部分 Snapshot，CLI 在连接 MCP、创建 Hook worker 或执行任何规则前失败。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_config.py tests/test_cli.py`）
- [x] 合法配置只接受顶层 `hooks`，重复 YAML key、非列表 hooks、非对象规则及未知字段均被拒绝。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_config.py`）

## 共享匹配与条件

- [x] AC9：自动 exact/glob、显式 `glob:`、`re:` 和 `!` 对字符串、数字、布尔与 null 正确匹配；regex 使用大小写敏感 search，glob 使用大小写敏感整串匹配。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_matching.py tests/test_hooks_conditions.py`）
- [x] AC9：all 必须全部命中，any 至少一个命中；二者非空、不可混用或嵌套。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_conditions.py tests/test_hooks_config.py`）
- [x] AC9：不存在字段及对象/数组字段始终不匹配，前置 `!` 不会将其变成命中；动态工具参数和 result data 叶子可匹配。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_conditions.py`）
- [x] AC10：旧权限 exact/glob 配置结果不变；regex 与反向规则可用，并遵守“会话 > 本地 > 项目 > 用户、exact > regex > glob、deny、声明顺序”。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_matching.py tests/test_permissions_rules.py tests/test_permissions_config.py tests/test_permissions_service.py`）
- [x] Hook allow 不能绕过危险命令黑名单、工作区沙箱、权限规则、权限模式或人工审批。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_service.py tests/test_agent_executor.py`）

## 事件与 Payload

- [x] AC3：`session_start`、`session_end`、`turn_start`、`turn_end`、`message_received`、`message_sent`、`tool_before`、`tool_after`、`context_compacted`、`agent_error` 十种事件均能构造和分发。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_events.py tests/test_hooks_runtime.py`）
- [x] AC11：所有 Payload 均含 schema version、带时区时间、工作区和会话；活动轮次事件含 turn id/mode/input kind，各事件只含适用专属字段。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_events.py`）
- [x] AC11：条件和同一事件的所有动作观察同一个不可修改 Payload；Payload 可稳定 JSON 编码，command 与 HTTP 接收一致内容。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_events.py tests/test_hooks_actions.py tests/test_hooks_runtime.py`）
- [x] `tool_after` 只暴露受限 display 结果，来源准确区分 tool、permission、hook、validation，不复制无界 complete 结果。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_events.py tests/test_tool_executor.py tests/test_agent_executor.py`）

## 动作协议

- [x] AC12：command 在工作区根目录以 shell 运行，并从 UTF-8 stdin 读取完整事件 JSON；事件值不被插入命令文本或环境变量。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_actions.py`）
- [x] AC12：command 默认超时为 10 秒，0.1–300 秒自定义值生效，越界值在配置期失败；运行超时、取消和 close 会清理活动进程及后代。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_config.py tests/test_hooks_actions.py`）
- [x] AC13：HTTP 默认 POST，以 `application/json` 发送同一 Payload；合法自定义 method/headers 生效，用户不能覆盖 content type，事件值不插入 URL 或 headers。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_config.py tests/test_hooks_actions.py`）
- [x] AC13：HTTP 使用固定 10 秒边界并有界读取响应；2xx 普通动作成功，非 2xx、网络错误、超时和过大响应产生 Hook 失败。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_actions.py`）
- [x] AC15：agent 动作可以加载和触发，仅产生“尚未实现”占位诊断；没有创建新 Provider、Agent、线程或会话。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_config.py tests/test_hooks_actions.py tests/test_hooks_integration.py`）

## 工具前置拦截

- [x] AC16：`tool_before` command 返回 0 时放行；返回 2 时使用经过截断和脱敏的 stderr 拒绝，工具、权限和后续前置规则均不执行。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_actions.py tests/test_hooks_runtime.py tests/test_agent_executor.py`）
- [x] AC16：Hook 拒绝被转换为 `source=hook` 的失败工具结果并写回 Agent；模型可读取拒绝原因、调整调用并继续当前轮次。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py tests/test_hooks_integration.py`）
- [x] AC17：`tool_before` HTTP 只接受严格的 allow 或带非空 reason 的 deny JSON；allow 继续进入权限流程，deny 在工具启动前拦截。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_actions.py tests/test_agent_executor.py`）
- [x] AC17：HTTP 无效 JSON/shape、非 2xx、网络错误、超时及 command 其他退出码只产生日志并默认放行；既有权限仍可拒绝。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_actions.py tests/test_agent_executor.py tests/test_hooks_integration.py`）
- [x] AC6：每个调用无论成功、工具失败、权限拒绝、未知工具或 Hook 拒绝都恰好触发一次 `tool_after`；Hook 拒绝不产生工具开始事件。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_executor.py`）
- [x] AC6：同批 Hook 拒绝只停止该调用，其余调用继续；只读工具仍并发，`tool_after` 与历史回灌按原调用顺序确定。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_executor.py`）

## once、异步与顺序

- [x] AC18：once 同步规则成功、deny、prompt 入队和 agent placeholder 后不再执行；条件未命中、failed 或 cancelled 不消耗机会。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_runtime.py`）
- [x] AC18：异步动作成功入队即消耗 once；队列满或提交失败不消耗。`/new` 和进程重启会重置状态，恢复相同会话也可再次触发。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_actions.py tests/test_hooks_runtime.py tests/test_cli.py`）
- [x] AC19：同步动作严格按合并顺序执行；command/HTTP 异步提交后主流程立即继续；prompt 与 agent 不接受异步，所有 `tool_before` 动作均禁止异步。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_config.py tests/test_hooks_runtime.py`）
- [x] AC19：后台 worker 和队列数量有界；close 后拒绝新任务、取消未启动任务并清理活动 command；`session_end` 不等待后台任务完成且进程能退出。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_actions.py tests/test_cli.py`）

## 失败隔离与日志安全

- [x] AC20：command 启动失败、异常、超时、HTTP 错误、无效响应和 agent 占位不会改变 Agent 原有结果或停止原因。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_actions.py tests/test_hooks_runtime.py tests/test_hooks_integration.py`）
- [x] AC20：stdout、stderr、HTTP body、拒绝原因与 Hook 日志均有大小边界，不产生无界内存或上下文输入。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_actions.py tests/test_hooks_events.py`）
- [x] AC20：诊断只显示配置来源、规则序号、事件、稳定错误码和安全消息，不包含完整 command、URL、headers、环境、Payload、工具敏感参数或测试 secret。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_actions.py tests/test_hooks_runtime.py tests/test_cli.py`）
- [x] Hook 动作及诊断不会递归触发 Hook 或 `agent_error`。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_runtime.py tests/test_agent_runner.py`）

## 主会话生命周期

- [x] AC4：一条普通用户输入即使包含多次模型—工具迭代，也只触发一次 `turn_start` 和一次 `turn_end`。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py tests/test_hooks_integration.py`）
- [x] AC4：completed、cancelled、stream/tool parse/context/session error、Skill 失败、未知工具和迭代上限均产生唯一且正确的 turn stop reason；渲染时 Ctrl+C 会关闭生成器并执行 finally。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py tests/test_cli.py`）
- [x] AC5：完整用户输入仅触发一次 `message_received`，最终 assistant 文本仅触发一次 `message_sent`；流式 delta、中间工具响应和工具结果不触发消息事件。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py tests/test_tool_streaming.py`）
- [x] AC7：新建和恢复会话分别以 `origin=new|restored` 触发 `session_start`；exit、EOF、interrupt 和 fatal error 在资源关闭前触发一次带原因的 `session_end`。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py`）
- [x] AC7：`/new` 的事件顺序严格为旧 session_end(switched) → 旧资源关闭 → once/prompt/turn 清空 → 新日志创建 → session_start(new)。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py tests/test_agent_runner.py`）
- [x] AC8：自动与手动压缩仅在 success 时触发 `context_compacted` 并带完整报告；not_needed、failed 和 tripped 不触发。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_context_manager.py tests/test_agent_runner.py tests/test_cli.py`）
- [x] AC8：stream_error、tool_parse_error、context_overflow、session_error 和 internal_error 各触发一次 `agent_error`；普通工具失败、权限/Hook 拒绝、取消、迭代上限和 Hook 失败不触发。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py`）

## Prompt 注入与 Skill 隔离

- [x] AC14：prompt 在下一次实际 Provider 请求中作为独立动态指令出现一次，提交 lease 后不再出现，并且不写入会话消息或日志。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_runtime.py tests/test_agent_runner.py`）
- [x] AC14：请求未发出或上下文准备失败时 lease 被释放，prompt 保留；自动压缩产生的 prompt 刷新到当前请求并重新复核预算，手动压缩产生的 prompt 进入后续首个请求。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_context_manager.py tests/test_agent_runner.py`）
- [x] turn/message/tool/system 晚期事件产生的 prompt 按已确认时序排队，`session_end` prompt 在配置期被拒绝。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_config.py tests/test_hooks_runtime.py tests/test_agent_runner.py`）
- [x] 共享 Skill 只产生一组主轮次/消息事件；独立 Skill 临时 Agent 接收一次性 prompt，但内部会话、轮次、消息、工具和错误不触发 Hook，最终摘要在主会话触发 `message_sent`。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_runtime.py tests/test_skill_isolated.py tests/test_agent_runner.py`）

## 架构与兼容性

- [x] ContextManager 的动态指令替换与预算复核不依赖 Hook 模块，可独立测试。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_context_manager.py`，并检查 `rg -n "mycode\\.hooks" src/mycode/context` 无匹配）
- [x] 共享 matching 模块不依赖 permissions 或 hooks；权限模块不依赖 hooks；Hook 动作模块不导入 Agent/Provider，避免循环依赖和占位动作误运行。（验证：运行 `rg -n "mycode\\.(permissions|hooks)" src/mycode/matching.py; rg -n "mycode\\.hooks" src/mycode/permissions; rg -n "mycode\\.(agent|providers)" src/mycode/hooks/actions.py`，期望无匹配）
- [x] 未配置 Hook 时不创建 Hook command 子进程或后台 worker，ChatSession、直接 ToolExecutor 和独立临时 Agent 保持原路径。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_session.py tests/test_tool_executor.py tests/test_skill_isolated.py tests/test_cli.py`）
- [x] AC21：会话恢复、普通聊天、Plan/Do、工具、权限、上下文、Skill、MCP 和 CLI 退出回归测试通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_session_memory_integration.py tests/test_agent_runner.py tests/test_permissions_service.py tests/test_context_integration.py tests/test_skill_integration.py tests/test_mcp_integration.py tests/test_cli.py`）
- [x] README、配置示例和 gitignore 与实现一致，覆盖三层路径、十种事件、条件语法、四类动作、拦截、once、异步、超时、失败隔离与阶段外事项。（验证：运行 `rg -n "hooks.yaml|hooks.local.yaml|session_start|tool_before|context_compacted|agent_error|once|async|timeout|decision|re:|glob:|子 Agent" README.md config.example.yaml .gitignore` 并人工核对）

## 编译与测试

- [x] 新增 Hook 和匹配测试全部通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_matching.py tests/test_hooks_conditions.py tests/test_hooks_events.py tests/test_hooks_config.py tests/test_hooks_actions.py tests/test_hooks_runtime.py tests/test_hooks_integration.py`）
- [x] 权限、工具、Agent、上下文、Skill 和 CLI 定向回归全部通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_rules.py tests/test_permissions_config.py tests/test_permissions_service.py tests/test_tool_executor.py tests/test_agent_executor.py tests/test_context_manager.py tests/test_agent_runner.py tests/test_skill_isolated.py tests/test_cli.py`）
- [x] 完整测试套件通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest`）
- [x] 源码和测试文件可编译。（验证：运行 `PYTHONPATH=src .venv/bin/python -m compileall -q src tests`）

## 端到端场景

- [x] AC22 / 场景 1：用户、项目、本地分别声明记录 command、一次性 prompt 和 HTTP 通知 → 启动新会话 → 按层级顺序触发 → command/HTTP 收到同一版本 Payload → prompt 只进入一次模型请求 → 正常完成并产生会话结束事件。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_integration.py -v` 对应主流程场景）
- [x] AC22 / 场景 2：模型请求危险工具 → `tool_before` command 或 HTTP deny → 权限和工具均未启动 → 拒绝原因作为失败工具结果回灌 → 模型调整为安全调用 → 当前轮次完成，每个调用各有一次 `tool_after`。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_integration.py -v` 对应拦截恢复场景）
- [x] 场景 3：command 失败、HTTP 超时/无效响应、后台队列满和 agent 占位同时发生 → 仅输出安全 Hook 诊断 → Agent 原流程继续 → 无递归事件、敏感值、无界内容或遗留进程。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_integration.py tests/test_hooks_actions.py -v`）
- [x] 场景 4：once 规则成功后同会话不重复 → `/new` 结束旧会话并清空状态 → 新会话再次触发；进程退出后恢复旧会话时也可再次触发。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hooks_integration.py tests/test_cli.py -v`）

## AC 覆盖矩阵

| Spec AC | Checklist 范围 |
|---|---|
| AC1 | 配置加载与集中校验 |
| AC2 | 配置加载与集中校验 |
| AC3 | 事件与 Payload |
| AC4 | 主会话生命周期 |
| AC5 | 主会话生命周期 |
| AC6 | 工具前置拦截 |
| AC7 | 主会话生命周期 |
| AC8 | 主会话生命周期 |
| AC9 | 共享匹配与条件 |
| AC10 | 共享匹配与条件 |
| AC11 | 事件与 Payload |
| AC12 | 动作协议 |
| AC13 | 动作协议 |
| AC14 | Prompt 注入与 Skill 隔离 |
| AC15 | 动作协议 |
| AC16 | 工具前置拦截；端到端场景 2 |
| AC17 | 工具前置拦截；端到端场景 2 |
| AC18 | once、异步与顺序；端到端场景 4 |
| AC19 | once、异步与顺序 |
| AC20 | 失败隔离与日志安全；端到端场景 3 |
| AC21 | 架构与兼容性；编译与测试 |
| AC22 | 端到端场景 1–4 |
