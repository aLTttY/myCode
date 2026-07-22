# MyCode 会话与长期记忆 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mycode/instructions.py` | 三层指令加载、include、安全边界和告警 |
| 新建 | `src/mycode/sessions/__init__.py` | 会话模块公共导出 |
| 新建 | `src/mycode/sessions/models.py` | 会话记录、摘要、恢复结果和错误模型 |
| 新建 | `src/mycode/sessions/journal.py` | 会话 ID、JSONL 追加、flush/fsync 与关闭 |
| 新建 | `src/mycode/sessions/loader.py` | 坏行容错、消息校验和工具单元截断 |
| 新建 | `src/mycode/sessions/catalog.py` | 元数据扫描、最近会话选择和过期清理 |
| 新建 | `src/mycode/memory/__init__.py` | 记忆模块公共导出 |
| 新建 | `src/mycode/memory/models.py` | note、index、decision、job 与 notice 模型 |
| 新建 | `src/mycode/memory/prompts.py` | 记忆决策、合并和索引精简提示 |
| 新建 | `src/mycode/memory/parser.py` | LLM 决策与 Markdown/frontmatter 校验 |
| 新建 | `src/mycode/memory/secrets.py` | 确定性敏感凭据检查 |
| 新建 | `src/mycode/memory/storage.py` | 用户/项目双作用域存储和索引维护 |
| 新建 | `src/mycode/memory/service.py` | 无工具 LLM 决策、更新合并和索引精简 |
| 新建 | `src/mycode/memory/worker.py` | 单 daemon 队列、取消、drain 和通知 |
| 修改 | `src/mycode/context/manager.py` | 导入恢复历史并重建完整工具条目 |
| 修改 | `src/mycode/agent/events.py` | 会话持久化错误停止原因 |
| 修改 | `src/mycode/agent/runner.py` | journal 双写、恢复提醒、记忆入队和会话切换 |
| 修改 | `src/mycode/prompts/modules.py` | 指令与两级记忆的优先级包装 |
| 修改 | `src/mycode/cli.py` | `--new`、`/new`、启动恢复、清理和通知展示 |
| 修改 | `.gitignore` | 忽略项目会话和自动记忆目录 |
| 修改 | `README.md` | 使用方式、格式、生命周期和安全边界 |
| 新建 | `tests/test_instructions.py` | 指令优先级、include 和路径安全 |
| 新建 | `tests/test_session_journal.py` | 会话 ID、追加持久化与错误 |
| 新建 | `tests/test_session_loader.py` | JSONL 坏行和工具关联恢复 |
| 新建 | `tests/test_session_catalog.py` | 派生元数据、自动选择与过期清理 |
| 新建 | `tests/test_memory_parser.py` | 决策协议和 frontmatter 校验 |
| 新建 | `tests/test_memory_secrets.py` | 凭据模式与安全占位符 |
| 新建 | `tests/test_memory_storage.py` | 双作用域、原子写、协调与索引限制 |
| 新建 | `tests/test_memory_service.py` | LLM 分类、去重、合并与精简 |
| 新建 | `tests/test_memory_worker.py` | FIFO、单并发、取消和有限等待 |
| 修改 | `tests/test_context_manager.py` | 恢复消息导入与再次压缩 |
| 修改 | `tests/test_agent_runner.py` | journal、提醒、自然完成入队与新会话 |
| 修改 | `tests/test_cli.py` | 新参数、本地命令和启动/退出生命周期 |
| 修改 | `tests/test_prompts.py` | 三层指令与两级索引顺序 |
| 新建 | `tests/test_session_memory_integration.py` | 跨进程、三 Provider 与端到端场景 |

## T1: 实现三层项目指令加载

**文件：** `src/mycode/instructions.py`、`tests/test_instructions.py`

**依赖：** 无

**步骤：**

1. 定义 instruction bundle、warning code 和最大 include 深度常量。
2. 按 `.mycode/MYCODE.md`、根 `MYCODE.md`、`~/.mycode/MYCODE.md` 读取入口；入口缺失静默按空内容处理。
3. 解析仅占整行的 `@include`，支持带引号的相对路径，不展开 glob、URL、环境变量或绝对路径。
4. 以包含文件目录解析目标，再用真实路径校验 workspace 或 `~/.mycode` 作用域；项目入口共享 visited，用户入口使用独立 visited。
5. 在深度 5、重复/环路、缺失、不可读、`..` 越界及符号链接越界时跳过目标并记录不含正文的 warning。
6. 为每一层添加来源边界和“靠前优先”说明，生成稳定拼接结果。
7. 测试正常优先级、内联展开、路径含空格、直接/间接环路、重复引用、第 6 层、绝对路径、`..` 和 symlink escape。

**验证：** 运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_instructions.py -q`，期望全部通过且告警断言不包含被引用文件正文。

## T2: 建立版本化 JSONL 会话日志

**文件：** `src/mycode/sessions/__init__.py`、`src/mycode/sessions/models.py`、`src/mycode/sessions/journal.py`、`tests/test_session_journal.py`

**依赖：** 无

**步骤：**

1. 定义 `SessionRecord`、会话错误和 `YYYYMMDD-HHMMSS-xxxx` ID 校验规则。
2. 生成带本地时区时间戳和随机四位十六进制后缀的 ID；文件已存在时重新生成，不覆盖旧日志。
3. 将现有 `Message` 序列化进 version 1 message envelope，保留 tool calls、arguments 与 tool call ID。
4. 每次 append 先在内存完成 JSON 序列化，再写一行、flush 并 fsync；失败转成不包含消息正文的会话错误。
5. 实现幂等 close，并保证日志目录和文件真实路径位于 workspace 的 `.mycode/sessions/`。
6. 测试 ID 格式、同秒碰撞重试、中文与工具消息 round-trip、多次追加、close、序列化/写入失败，以及目录中没有 meta 文件。

**验证：** 运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_session_journal.py -q`，期望 JSONL 每行可独立解析，失败注入后既有行保持不变。

## T3: 实现会话扫描、损坏恢复和过期清理

**文件：** `src/mycode/sessions/models.py`、`src/mycode/sessions/loader.py`、`src/mycode/sessions/catalog.py`、`src/mycode/sessions/__init__.py`、`tests/test_session_loader.py`、`tests/test_session_catalog.py`

**依赖：** T2

**步骤：**

1. 严格校验 envelope 版本、时间戳、message role、content、tool calls 和 arguments 类型；未知版本或非法行计入 bad line 后继续。
2. 从有效记录扫描第一条用户消息、消息数、最早/最晚时间，标题压平空白并截到 80 字符，不写缓存文件。
3. 用状态机验证工具单元：助手声明的每个 call ID 必须恰好收到一个结果；结果允许按任意完成顺序出现，但在齐备前不能出现非 tool 消息。
4. 遇到孤立结果、未知 ID、重复结果或未闭合调用时，返回首个非法单元之前的最长合法消息前缀和截断计数。
5. 按最后活动时间选择 30 天内最近且有有效用户消息的会话；并列时按 ID 降序，完全损坏文件不得成为候选。
6. 启动清理按最后有效记录时间判断；空/完全损坏文件回退 mtime。删除失败只进入安全 warning。
7. 计算恢复 gap，并在严格超过 24 小时时标记一次性提醒。
8. 覆盖坏行位于头部/中部/尾部、坏行破坏工具结果、完整并发工具批次、未闭合尾部、标题派生、候选并列和 30 天边界测试。

**验证：** 运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_session_loader.py tests/test_session_catalog.py -q`，期望损坏被隔离、合法前缀稳定且清理边界准确。

## T4: 让上下文管理器接收恢复历史

**文件：** `src/mycode/context/manager.py`、`tests/test_context_manager.py`

**依赖：** T3

**步骤：**

1. 增加一次性导入合法 Message 序列的入口，只允许在空 ContextManager 上调用。
2. 按原顺序重建 sequence；普通消息直接形成 managed entry。
3. 为助手工具调用及其连续 tool 结果重建同一 batch ID，并将 tool content 同时作为完整内容，保留现有轻量卸载能力。
4. 导入后保持 summary、boundary、failure breaker 和 token anchor 为空，不接受旧 `.mycode/context/` 引用作为持久状态。
5. 对非法或非空导入给出明确错误，避免在 ContextManager 内再次实现容错恢复。
6. 测试纯对话导入、工具批次导入、恢复后大型结果卸载、恢复后重量摘要、序号延续和关闭时只清理本进程临时 context。

**验证：** 运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_context_manager.py tests/test_context_integration.py -q`，期望恢复历史能走现有压缩路径且无旧临时引用。

## T5: 定义自动记忆协议、解析器与秘密检查

**文件：** `src/mycode/memory/__init__.py`、`src/mycode/memory/models.py`、`src/mycode/memory/prompts.py`、`src/mycode/memory/parser.py`、`src/mycode/memory/secrets.py`、`tests/test_memory_parser.py`、`tests/test_memory_secrets.py`

**依赖：** 无

**步骤：**

1. 定义四种 category、两种 scope、importance 1-5、note/index/decision/job/notice 模型和 ID 规则。
2. 固定 Markdown frontmatter 字段、正文结构和 update 时不可变化的 ID/created_at 约束，使用 `yaml.safe_load` 解析。
3. 编写 decision、update merge 和 index compact 三类 prompt；均要求无工具、秘密禁令、默认 project 和唯一标记包裹 JSON。
4. 严格解析 `<memory_update>`，拒绝重复/缺失标记、尾随内容、未知字段、非法枚举、空正文、跨 scope target 与不存在的 update ID。
5. 实现 PEM、Bearer、常见 token 前缀和敏感赋值模式扫描；仅返回命中规则 code，不返回原值。
6. 明确放行 `${VAR}`、`<TOKEN>`、`your-api-key`、全星号等占位符和测试掩码。
7. 测试 create/update/ignore、多 operation、恶意路径/ID、frontmatter round-trip、私钥/API key/password 命中与占位符放行。

**验证：** 运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory_parser.py tests/test_memory_secrets.py -q`，期望所有非法模型输出被拒绝且错误不回显秘密。

## T6: 实现双作用域笔记存储与有界索引

**文件：** `src/mycode/memory/storage.py`、`src/mycode/memory/models.py`、`tests/test_memory_storage.py`

**依赖：** T5

**步骤：**

1. 将 project scope 固定到 `<workspace>/.mycode/memory/`，user scope 固定到指定 user root 的 `memory/`；真实路径和 symlink 必须保持在各自边界。
2. 为 note 和 `index.md` 实现同目录临时文件、flush/fsync 与原子替换；失败时清理临时文件并保留旧文件。
3. 创建 note 时由代码生成 ID 和 frontmatter；更新时只允许引用已扫描到的同 scope ID。
4. 扫描所有 note 并安全解析 frontmatter，隔离损坏文件；协调 index 中的悬空条目、漏项和重复项，不创建 meta。
5. 以四分类和单行条目稳定渲染 index，统一 LF/UTF-8，并按 importance 降序、updated_at 降序、ID 升序排序。
6. 实现 180 行/22KB 预警判断与 200 行/25KB 硬限制；兜底时先移除低价值旧条目，再在 UTF-8 字节边界缩短摘要，永不删除 note 文件。
7. 每次 note/index 提交前调用 SecretScanner；任一候选命中时拒绝该项以及对应索引变更。
8. 测试作用域隔离、symlink escape、create/update、写入回滚、损坏 note/index 协调、稳定排序、双上限和原始 note 保留。

**验证：** 运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory_storage.py tests/test_memory_secrets.py -q`，期望两级目录互不污染，索引同时满足行数与字节限制。

## T7: 实现无工具 LLM 记忆决策与合并

**文件：** `src/mycode/memory/service.py`、`src/mycode/memory/prompts.py`、`src/mycode/memory/parser.py`、`tests/test_memory_service.py`

**依赖：** T5、T6

**步骤：**

1. 使用 `TurnSnapshot` 与两级 index 组装 decision 请求，设置 `tools=()`、关闭静态缓存，并收集完整文本响应。
2. 检测任何 tool call 事件、Provider 错误、空响应和格式错误，整次转成安全失败 notice，不执行模型动作。
3. 对 create 执行 scope/category/default-project/秘密校验并提交；对 update 先读取唯一目标 note，再发起无工具 merge 请求生成完整替换内容。
4. 支持一轮产生零个或多个 operation；逐项验证，单项失败不破坏此前已有笔记，重复语义由 LLM 选择 update 或 ignore。
5. 索引达到预警线时调用 compact prompt；只接受现有 note ID，并在写入前再次执行硬限制兜底。
6. 在每个磁盘事务前检查 job 取消标志，取消后丢弃尚未提交的模型结果。
7. 测试四分类、跨项目/项目 scope、无法判断默认 project、重复 update、ignore、merge 读取目标、工具调用拒绝、API/格式失败和恶意 target。

**验证：** 运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory_service.py -q`，期望请求均为空工具，作用域和目标校验严格，失败不破坏既有存储。

## T8: 实现串行异步记忆 Worker

**文件：** `src/mycode/memory/worker.py`、`src/mycode/memory/models.py`、`tests/test_memory_worker.py`

**依赖：** T7

**步骤：**

1. 使用一个 daemon thread 和 FIFO queue，确保进程内至多一个 running job。
2. `submit` 只复制有界 snapshot 并立即返回 job ID，不在前台等待 LLM。
3. 将成功、失败、拒绝和取消结果写入线程安全 notice queue，禁止 worker 直接打印终端。
4. 实现默认 5 秒 `drain`；完成时返回 notices，超时时取消 queued/running 未提交 job 并立即返回。
5. 允许正在阻塞 Provider 的 daemon 调用自然结束，但 service 在后续 commit 前看到取消标志并丢弃结果。
6. 测试提交延迟、FIFO、单并发、正常 drain、超时上界、取消后不落盘、notice 排空和 daemon 不阻止进程关闭。

**验证：** 运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory_worker.py -q`，期望计时断言有宽容边界且无非 daemon 泄漏。

## T9: 接入 AgentRunner 的会话双写、Prompt 和记忆触发

**文件：** `src/mycode/agent/runner.py`、`src/mycode/agent/events.py`、`src/mycode/prompts/modules.py`、`tests/test_agent_runner.py`、`tests/test_prompts.py`

**依赖：** T1、T2、T4、T6、T8

**步骤：**

1. 让 AgentRunner 接收 journal、instruction bundle、memory stores/worker、恢复消息和 gap 信息，同时为旧测试保留明确的无持久化测试默认值。
2. 统一用户、助手和工具 Message 的“先 journal、后 context”追加路径；工具结果保持模型调用顺序。
3. 用户 append 失败时不请求 Provider；助手或工具 append 失败时发出 `session_error` error/done 并停止循环。
4. 每个 iteration 重新读取项目和用户 `index.md`，按项目在前组装 `PromptOptions`；指令保持启动时 bundle 快照。
5. 只在恢复后的第一个实际 Provider 请求注入时间跨度动态 tag；请求因 context overflow 未发出时保留提醒，发出后消费。
6. 记录本轮用户、助手文本和安全工具摘要；仅在无工具最终回复产生 completed 后构造 `TurnSnapshot` 并提交 worker。
7. 确保取消、最大迭代、未知工具、解析错误、stream error 和 context overflow 均不提交记忆任务。
8. 实现 `new_session()` 和扩展 `close()`：drain、取消、关闭 journal、清理旧临时 context、创建空 ContextManager 并返回安全状态。
9. 测试原始消息与压缩视图分离、journal 错误、提醒一次、索引每请求刷新、自然/非自然触发矩阵、`/new` 重置和 close 告警合并。

**验证：** 运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py tests/test_prompts.py tests/test_context_manager.py -q`，期望现有 Agent 行为及新增持久化行为全部通过。

## T10: 接入 CLI 启动恢复、`--new`、`/new` 和退出收尾

**文件：** `src/mycode/cli.py`、`tests/test_cli.py`

**依赖：** T3、T9

**步骤：**

1. 参数解析增加 `--new`，不改变现有 `--config` 和 `--permission-mode`。
2. 按批准顺序完成启动：配置/工作区、会话清理、指令加载、最近恢复或新建、memory store 协调、前台 Provider 和同配置后台 Provider、AgentRunner。
3. 无恢复候选或 `--new` 时创建新 journal；普通启动恢复最近合法前缀并传入 ContextManager。
4. 把精确 `/new` 作为与 `/compact` 同级的本地命令，调用 AgentRunner 切换，不进入 `parse_agent_request` 或 JSONL。
5. 安全显示清理数量、session ID、恢复消息数、bad line、截断数和是否存在时间提醒，不显示标题之外的正文。
6. 每个输入边界和 Agent 轮次后排空 memory notices；`/new`、exit、EOF、Ctrl+C 退出和异常 finally 都执行有限 drain/close。
7. 后台 Provider 创建失败时输出清晰启动错误，不允许前台在“声称自动记忆可用”的半初始化状态运行。
8. 测试默认恢复、`--new`、`/new`、无候选、过期清理告警、坏行/截断状态、notice 展示、退出超时和 MCP 生命周期回归。

**验证：** 运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py -q`，期望所有 CLI 路径关闭 journal、worker、context 和 MCP manager。

## T11: 完成 Git 忽略与用户文档

**文件：** `.gitignore`、`README.md`

**依赖：** T1-T10

**步骤：**

1. 仅新增 `.mycode/sessions/` 和 `.mycode/memory/` 忽略规则，保留 `.mycode/MYCODE.md` 可跟踪。
2. 文档说明三层 `MYCODE.md` 优先级、`@include` 语法、5 层限制和两个安全作用域。
3. 文档说明默认自动恢复、`--new`、`/new`、JSONL 路径/ID、无 meta、24 小时提醒与 30 天启动清理。
4. 文档说明四类自动笔记、用户/项目作用域、异步更新、5 秒收尾、index 双上限和秘密拒绝。
5. 明确本阶段没有向量检索、RAG、团队同步和任意历史会话选择器。
6. 验证 Git ignore 只命中自动目录，不命中两处项目 `MYCODE.md`。

**验证：** 运行 `git check-ignore -v .mycode/sessions/example.jsonl .mycode/memory/example.md` 应命中；运行 `git check-ignore .mycode/MYCODE.md MYCODE.md` 应无输出并返回未忽略状态。

## T12: 完成跨模块集成与全量回归

**文件：** `tests/test_session_memory_integration.py`

**依赖：** T1-T11

**步骤：**

1. 构造跨进程场景：首进程完成含并发工具调用的自然轮次并关闭，第二进程从 JSONL 自动恢复并继续对话。
2. 在会话中注入坏行和不完整工具尾部，验证坏行跳过、合法前缀截断、原日志不被重写且无 meta。
3. 将最后活动时间置于 24 小时外，验证只注入一次时间提醒；构造超预算恢复，验证只压缩一次，仍不足时 Provider 不被调用并提示 `/compact`、`/new`。
4. 让后台模型依次产生 user preference、project knowledge、重复 update 和 secret candidate，验证正确作用域、语义合并、秘密拒绝和下一请求索引注入。
5. 构造超过 index 双上限的数据，验证 LLM 精简失败后确定性兜底，note 文件不删除。
6. 对 OpenAI、Anthropic、DeepSeek 请求适配分别断言系统指令、动态提醒、optional prompt 和消息/工具关联合法。
7. 运行现有 permissions、tools、MCP、Agent、context、Provider 和 CLI 回归，修复本功能引入的兼容问题，不改变既有语义。

**验证：**

1. 运行 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_session_memory_integration.py -q`，期望端到端场景全部通过。
2. 运行 `PYTHONPATH=src .venv/bin/python -m pytest -q`，期望全量测试通过。

## 执行顺序

```text
T1 -> T2 -> T3 -> T4 -> T5 -> T6 -> T7 -> T8 -> T9 -> T10 -> T11 -> T12
```

其中 T1、T2、T5 在实现资源允许时可并行，但合并后的主线仍按上述顺序逐项验证。
