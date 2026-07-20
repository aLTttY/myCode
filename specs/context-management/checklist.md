# MyCode 上下文管理 Checklist

> 每一项都通过运行代码或观察行为验证。开发完成后逐项记录实际结果与证据。

## 配置与轻量压缩

- [x] AC1：合法配置加载必填窗口和默认 8K/16K 阈值；缺失、布尔值、零、负数、字符串及其他非法阈值均在启动阶段给出字段级错误。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_config.py`）

- [x] AC2：单个超 8K token 的工具结果把字符截断前完整 JSON 写入会话文件；模型历史只含首尾各 1,000 字符、相对路径、原始大小和卸载说明。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_context_manager.py -k 'single or preview'`，并由测试读取落盘文件与候选请求）

- [x] AC3：多个单项未超限但合计超 16K 的结果按体积从大到小卸载，达到阈值后停止，仍可容纳的小结果保持原文。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_context_manager.py -k 'batch or largest'`）

- [x] AC4：连续及并发结果文件名不冲突，保留路径可由 `read_file` 读取，正常关闭后本会话目录消失。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_context_storage.py tests/test_context_manager.py -k 'unique or readable or cleanup or concurrent'`）

## Token 估算与触发

- [x] AC5：无 usage 时估算完整请求；普通请求成功后以 input usage 和该请求快照为锚点；消息、系统提示和工具定义增删只计算差量，摘要 usage 不覆盖锚点。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_context_estimator.py tests/test_agent_runner.py -k 'estimate or anchor or usage'`）

- [x] AC6：普通请求在窗口减 13K 处才触发自动摘要，执行顺序为轻量后重量；一次请求准备最多调用一次摘要，阈值以下不调用。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_context_manager.py tests/test_agent_runner.py -k 'auto or reserve or once or preflight'`）

- [x] 混合字符算法按非 ASCII 每字符 1 token、ASCII 每 3 字符约 1 token 向上取整，规范化快照在字典顺序不同但语义相同时保持稳定。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_context_estimator.py -k 'ascii or unicode or stable'`）

## 手动压缩与重量摘要

- [x] AC7：精确输入 `/compact` 不进入历史；有早期历史时使用窗口减 3K 目标强制压缩，无可压缩历史时显示“无需压缩”，报告包含前后估算和处理范围。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_cli.py tests/test_context_manager.py -k 'compact or manual or no_op'`）

- [x] AC8：近期区在历史足够时达到约 10K token 且不少于 5 条消息，助手工具调用及全部结果始终位于同一侧，不产生孤立结果。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_context_manager.py -k 'recent or unit or tool_group'`）

- [x] AC9：摘要请求的工具集合为空，Prompt 明确禁止工具并要求两个标记区块；正式摘要恰有六个标题，草稿不进入返回对象、事件、日志或后续请求。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_context_summary.py -k 'prompt or tools or draft or headings'`）

- [x] AC10：压缩后早期可压缩历史被正式摘要替代，摘要和边界分别作为动态 system 块注入，近期消息保持原文；边界明确要求重新读取文件且禁止臆测。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_context_manager.py tests/test_providers.py -k 'summary_block or boundary or recent'`）

- [x] AC11：预算足够时所有早期用户消息仍以原始文本保留；只有最终预算不足时才按时间顺序原文存盘并换成路径引用，摘要模型的改写不替代用户原文。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_context_manager.py -k 'user_original or user_offload'`）

## 失败、事务与熔断

- [x] AC12：文件写入失败、摘要 API 失败、工具调用、空响应、标记错误、标题错误和压缩后仍超目标都返回可区分失败；活动历史与旧摘要保持不变，本事务文件被回滚。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_context_storage.py tests/test_context_summary.py tests/test_context_manager.py -k 'failure or invalid or rollback or atomic'`）

- [x] AC13：连续三次自动摘要失败后本会话熔断，第四次不再自动调用；`/compact` 仍可调用，成功后失败次数清零并恢复自动摘要。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_context_manager.py -k 'breaker or consecutive or recover'`）

- [x] AC14：摘要失败、熔断或压缩不足且仍超预算时，普通 Provider 调用次数不增加；事件和 CLI 显示当前估算、目标预算、原因及 `/compact` 提示。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_agent_runner.py tests/test_cli.py -k 'context_overflow or over_budget or compact_hint'`）

- [x] 一次自动请求准备不会递归进入压缩，也不会因摘要请求再次触发摘要。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_context_manager.py tests/test_agent_runner.py -k 'recursive or once'`）

## Provider、工具与生命周期集成

- [x] AC15：OpenAI、Anthropic 和 DeepSeek 在压缩后仍收到合法 system/message/tool 序列；工具调用 ID 与结果保持配对；摘要请求在三类协议下均无工具定义。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_providers.py tests/test_context_summary.py -k 'openai or anthropic or deepseek or tool'`）

- [x] 双视图隔离成立：CLI 事件和旧 Session 只看到受限视图，上下文管理器能取得完整视图，短结果的两个视图语义相同。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_tool_executor.py tests/test_agent_executor.py tests/test_session.py`）

- [x] 文件读取、命令、搜索和 MCP 的超长内容可从完整视图恢复；搜索数量上限、命令超时、路径限制、不支持 MCP 类型和远端错误语义保持不变。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_tools_files.py tests/test_tools_command.py tests/test_tools_search.py tests/test_mcp_tool.py`）

- [x] 只读工具并发完成顺序不同于调用顺序时，写入历史的工具结果仍按原始调用顺序排列并正确关联 ID。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_agent_executor.py -k 'order or concurrent'`）

- [x] AC16：正常退出执行会话目录清理；模拟清理失败时打印不含正文的警告，MCP 清理及进程退出仍完成；压缩状态和错误不打印工具结果或用户原文。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_cli.py tests/test_context_storage.py -k 'cleanup or warning or secret or redaction'`）

- [x] 路径安全成立：上下文目录和文件解析后始终位于工作区，符号链接越界被拒绝，模型历史仅出现工作区相对路径。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_context_storage.py -k 'boundary or symlink or relative'`）

## 编译与回归

- [x] Python 源码与测试均可编译，无语法错误。（验证：运行 `PYTHONPATH=src .venv/bin/python -m compileall -q src tests`）

- [x] 差异中不存在空白错误。（验证：运行 `git diff --check`）

- [x] 项目没有配置独立 lint 工具；不虚构 lint 结果，使用编译检查与全量 pytest 作为本阶段静态和行为门禁。（验证：检查 `pyproject.toml`，确认没有 lint 配置）

- [x] AC17：六个内置工具、MCP、权限规则、Plan/Do、流式文本、旧 Session 和 token usage 展示的既有测试全部通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q`）

## 端到端场景

- [x] AC18：脚本化长会话依次产生单项超限工具结果、多结果合计超限和累计历史超限；系统完成存盘、预览、六段摘要与近期保留，随后继续普通请求并能按路径重读完整结果，正常退出后目录消失。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_context_integration.py -k 'long_session'`）

- [x] 端到端失败恢复：连续三次摘要失败造成熔断和请求拒绝，手动 `/compact` 成功恢复后下一次普通请求正常发送，所有报告不含原始敏感正文。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_context_integration.py -k 'breaker_recovery'`）

- [x] 完整验收测试无失败、错误或跳过关键上下文场景。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q`，记录通过数量和耗时）

## 验收记录

- 验收日期：2026-07-20
- 定向验收：清单中全部 pytest 选择器均至少命中一项测试并通过。
- 并发顺序：只读工具完成顺序为 `2 → 1`，写回顺序仍为 `1 → 2`。
- 生命周期：上下文清理失败仅输出脱敏警告，MCP 管理器仍完成关闭。
- 编译检查：`PYTHONPATH=src .venv/bin/python -m compileall -q src tests` 通过。
- 差异检查：`git diff --check` 通过。
- lint 状态：`pyproject.toml` 未配置独立 lint 工具，未虚构 lint 结果。
- 全量回归：`PYTHONPATH=src .venv/bin/python -m pytest -q` 得到 `305 passed in 12.93s`。
