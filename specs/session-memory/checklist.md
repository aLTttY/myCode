# MyCode 会话与长期记忆 Checklist

> 开发完成后逐项运行或观察，并记录实际结果。未取得证据的条目不得标记通过。

## 项目指令

- [x] AC1：三份 `MYCODE.md` 同时存在且包含冲突内容时，请求中的自定义指令严格按 `.mycode/` 项目级、项目根、用户级排列，并明确靠前优先；任一入口缺失不影响其余入口。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_instructions.py tests/test_prompts.py -q`，由测试检查完整 Prompt 顺序和缺失入口场景）

- [x] AC2：合法 `@include` 在原位置展开，带空格的引号路径可用，重复文件只加载一次；直接/间接环路、第 6 层、绝对路径、`..` 及符号链接越界均被跳过，告警不包含被引用正文。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_instructions.py -q`）

- [x] 指令只在进程启动时读取；同一进程内修改 `MYCODE.md` 不会静默改变后续请求，新进程能读取新内容。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_instructions.py tests/test_cli.py -q`，观察启动快照测试）

## 会话日志与选择

- [x] AC3：新会话 ID 符合 `YYYYMMDD-HHMMSS-xxxx`，同秒冲突会重试；`.mycode/sessions/` 中只有逐行可独立解析的 JSONL 会话文件，没有 meta 文件。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_session_journal.py -q`）

- [x] AC4：包含多个工具调用的一轮按用户、助手调用、各工具结果和最终助手消息顺序持久化，call ID 与 result ID 可完整还原；标题、消息数、创建和最后活动时间只扫描 JSONL 得出。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_session_journal.py tests/test_session_loader.py tests/test_session_catalog.py -q`）

- [x] 每次 append 执行 flush/fsync；序列化或写入失败不破坏既有完整行，错误和日志不回显消息正文。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_session_journal.py -q`，由故障注入检查文件字节和错误文本）

- [x] AC5：普通启动在多个候选中恢复 30 天内最后活动时间最新者；并列时选择稳定。`--new` 跳过恢复，精确 `/new` 不进入模型或旧 JSONL，并在持久化旧会话后切换到新 ID。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_session_catalog.py tests/test_cli.py tests/test_agent_runner.py -q`）

- [x] AC6：启动删除超过 30 天的会话并保留边界内会话；空或完全损坏文件按 mtime 清理；单个删除失败只产生安全告警，CLI 仍进入交互。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_session_catalog.py tests/test_cli.py -q`）

## 会话恢复与上下文

- [x] AC7：JSON 语法错误、未知版本、非法字段和类型错误行被计数并跳过；坏行之后的独立合法消息仍可读取，任何告警都不打印坏行正文。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_session_loader.py -q`）

- [x] AC7：孤立工具结果、未知/重复结果 ID、缺失结果和坏行造成的关联断裂都从首个不完整工具单元起截断；完整多工具单元不被拆散。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_session_loader.py tests/test_session_memory_integration.py -q`）

- [x] 恢复历史导入后不携带旧摘要、token 锚点、熔断状态或 `.mycode/context/` 路径；完整工具结果仍能被当前进程的轻量压缩重新卸载。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_context_manager.py tests/test_context_integration.py -q`）

- [x] AC8：恢复历史超预算时，一次请求准备最多调用一次摘要；成功后正常请求，仍超限时普通 Provider 调用数不增加、JSONL 不变，终端同时提示 `/compact` 与 `/new`。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py tests/test_session_memory_integration.py -q`）

- [x] AC9：最后活动严格超过 24 小时时，首个实际 Provider 请求包含一次 system 时间跨度提醒；24 小时以内不包含。context overflow 未发送请求时提醒仍保留，成功发送后不再出现，JSONL 中没有该提醒。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_session_catalog.py tests/test_agent_runner.py tests/test_session_memory_integration.py -q`）

- [x] 恢复、新建、坏行、截断、清理、压缩和时间提醒状态只展示 ID、计数、时间与安全原因，不展示用户正文或工具结果。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py tests/test_session_memory_integration.py -q`，检查捕获的 stdout/stderr）

## 自动笔记格式与作用域

- [x] AC10：无工具最终回复先完整展示并产生 completed，再立即提交后台 job；记忆 Provider 与前台使用相同协议、模型和凭据，所有记忆请求 `tools=()`，模型尝试工具调用时不执行并安全失败。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py tests/test_memory_service.py -q`）

- [x] AC10：max iterations、取消、未知工具、stream error、工具解析错误、session error 和 context overflow 都不提交记忆 job；记忆 API/格式失败不改变会话、note 或 index。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py tests/test_memory_service.py -q`）

- [x] AC11：用户偏好、纠正反馈、项目知识和参考资料分别生成带完整 frontmatter 的单独 Markdown；跨项目偏好/纠正进入用户级，项目特定内容进入项目级，无法判断时进入项目级。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory_parser.py tests/test_memory_service.py tests/test_memory_storage.py -q`）

- [x] 项目 note/index 只能写入 `<workspace>/.mycode/memory/`，用户 note/index 只能写入 `~/.mycode/memory/`；恶意 ID、路径、`..` 和 symlink escape 被拒绝。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory_parser.py tests/test_memory_storage.py -q`）

- [x] AC12：语义相同但措辞不同的后续轮次由 LLM 选择 update 或 ignore，不重复创建 note；update 先读取唯一目标正文再合并，并保留 ID/created_at。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory_service.py tests/test_memory_storage.py -q`）

- [x] AC12：连续提交多个自然完成轮次时 worker 严格 FIFO 且同时最多运行一个 job，先完成的 note/index 更新不会被后续任务覆盖。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory_worker.py tests/test_memory_service.py -q`）

- [x] note 或 index 原子替换失败时旧文件保持有效；启动协调能补齐未索引 note、移除悬空/重复 index 项并隔离损坏文件，不创建额外 meta。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory_storage.py -q`）

## 异步生命周期与索引

- [x] AC13：`submit` 不等待 LLM，最终回复无额外延迟；`/new` 和正常退出最多等待 5 秒，及时完成的任务已入索引，超时任务被取消并告警，daemon worker 不阻止进程结束。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory_worker.py tests/test_agent_runner.py tests/test_cli.py -q`）

- [x] 被取消但 Provider 稍后返回的旧 job 在每次提交前检测取消状态，不会在 `/new` 后或退出收尾后写入 note/index。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory_worker.py tests/test_memory_service.py -q`）

- [x] AC14：索引达到 180 行或 22KB 时触发 LLM 精简；模型只能处理已存在 note ID。若结果仍超限，确定性兜底后文件同时不超过 200 行和 25KB，UTF-8 完整且原始 note 数量不减少。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory_storage.py tests/test_memory_service.py tests/test_session_memory_integration.py -q`）

- [x] 同一批 note 在内容不变时多次重建得到相同条目顺序和兜底结果；优先级依次为 importance、updated_at、ID。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory_storage.py -q`）

- [x] AC15：每个普通 Provider 请求前重新读取 index；optional system prompt 中项目级索引位于用户级之前。后台更新完成后的下一请求能直接使用新索引，任一 index 缺失或损坏不阻止请求。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_prompts.py tests/test_agent_runner.py tests/test_memory_storage.py -q`）

- [x] AC16：候选中出现测试 API Key、Bearer token、password 或 PEM 私钥时，note 与关联 index 均不落盘；`${VAR}`、`<TOKEN>` 和明确掩码可通过。所有拒绝告警只含规则 code，不含秘密值。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory_secrets.py tests/test_memory_storage.py tests/test_memory_service.py -q`）

## Git、编译与回归

- [x] AC17：`.mycode/sessions/example.jsonl` 和 `.mycode/memory/example.md` 被 Git 忽略。（验证：运行 `git check-ignore -v .mycode/sessions/example.jsonl .mycode/memory/example.md`，两条路径都应显示匹配规则）

- [x] AC17：`MYCODE.md` 和 `.mycode/MYCODE.md` 不被 Git 忽略，仍可跟踪。（验证：分别运行 `git check-ignore MYCODE.md` 与 `git check-ignore .mycode/MYCODE.md`，两条命令都应无输出并返回未忽略状态）

- [x] Python 源码和测试可编译，无语法错误。（验证：运行 `PYTHONPATH=src .venv/bin/python -m compileall -q src tests`）

- [x] 差异不存在空白错误，且项目仍无独立 lint 配置；不虚构 lint 结果。（验证：运行 `git diff --check`，并检查 `pyproject.toml` 的工具配置）

- [x] AC18：OpenAI、Anthropic、DeepSeek 在全新、恢复、时间提醒、两级索引及压缩状态下都收到合法 system/message/tool 序列，tool call/result ID 完整配对，记忆请求无工具定义。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_providers.py tests/test_session_memory_integration.py tests/test_memory_service.py -q`）

- [x] AC18：内置工具、MCP、权限模式、Plan/Do、流式输出、旧 ChatSession、token usage 与上下文压缩的既有测试全部通过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q`）

## 端到端场景

- [x] AC19：进程 A 加载三层指令，完成含多个工具调用的自然轮次并异步写入正确作用域笔记后正常退出；进程 B 在超过 24 小时后自动恢复同一 JSONL，下一请求已包含项目/用户索引和一次时间提醒，且不依赖 meta 文件。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_session_memory_integration.py -q` 的完整恢复场景，记录 session ID、恢复计数和 note/index 断言）

- [x] AC19：在上述存档中加入坏行与不完整工具尾部后再次恢复，坏行被跳过、尾部被截断、原 JSONL 不重写；新一轮仍能自然完成并更新记忆。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_session_memory_integration.py -q` 的损坏恢复场景）

- [x] 超预算端到端：恢复大型原始工具历史后系统最多自动摘要一次；不足时阻止请求并保留存档，执行 `/compact` 成功后可继续，`/new` 能切换且旧会话仍存在。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_session_memory_integration.py tests/test_context_integration.py -q`）

- [x] 完整验收无失败，并记录通过数量、耗时和任何跳过项；关键端到端场景不得跳过。（验证：运行 `PYTHONPATH=src .venv/bin/python -m pytest -q`）

## 验收覆盖索引

| Spec 验收标准 | Checklist 位置 |
|---|---|
| AC1-AC2 | 项目指令 |
| AC3-AC6 | 会话日志与选择 |
| AC7-AC9 | 会话恢复与上下文 |
| AC10-AC12 | 自动笔记格式与作用域 |
| AC13-AC16 | 异步生命周期与索引 |
| AC17-AC18 | Git、编译与回归 |
| AC19 | 端到端场景 |

## 验收记录

- 验收日期：2026-07-21
- 定向验收：指令、会话、记忆、Agent、CLI 和跨进程恢复测试均通过；最终定向批次为 `36 passed in 1.74s`。
- 全量回归：在允许 localhost 绑定的环境运行 `PYTHONPATH=src .venv/bin/python -m pytest -q`，结果为 `329 passed in 11.06s`。
- 编译检查：`PYTHONPATH=src .venv/bin/python -m compileall -q src tests` 通过。
- 差异检查：`git diff --check` 通过。
- Git ignore：sessions 和 memory 示例路径均命中新规则；项目根与 `.mycode/` 下的 `MYCODE.md` 均返回未忽略状态。
- lint 状态：`pyproject.toml` 未配置独立 lint 工具，未虚构 lint 结果。
- 测试隔离：CLI 测试使用临时工作区；工作区 `.mycode/sessions/` 中没有测试遗留空文件。
