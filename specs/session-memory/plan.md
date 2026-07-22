# MyCode 会话与长期记忆 Plan

## 架构概览

### 指令加载层

新增独立的指令加载器，在 CLI 完成工作区确定后读取三层 `MYCODE.md`。加载器按优先级处理项目 `.mycode/`、项目根和用户目录，逐行展开 `@include`，并以真实路径、作用域根、深度和 visited 集合执行安全校验。最终产出一段带来源标签和优先级说明的自定义指令文本，以及可安全显示的告警列表。

### 会话日志层

新增追加式 JSONL 会话日志。日志只保存原始用户、助手和工具消息，不保存上下文压缩产生的摘要、临时卸载路径、token 锚点或其他运行时状态。每条消息在进入活动上下文时同步追加并刷新到磁盘；JSONL 是跨进程恢复的事实源，现有 `ContextManager` 仍是当前进程中请求历史和压缩状态的唯一所有者。

### 会话目录与恢复层

新增会话目录协调器，负责创建 ID、启动清理、扫描派生信息、选择最近会话和恢复合法消息前缀。恢复先逐行容错解析，再以工具调用单元校验消息序列；首个孤立或未闭合工具单元之后的消息不进入活动上下文。恢复报告只包含 ID、标题、计数、时间和错误数量。

### 上下文接入层

扩展 `ContextManager`，允许从恢复后的完整消息初始化内部条目，并重新建立序号、工具批次和完整工具结果视图。恢复历史不会直接复用上次进程的摘要或 `.mycode/context/` 引用；下一次普通请求仍走现有轻量卸载、预算估算和最多一次重量摘要。时间跨度提醒作为一次性动态 system 指令加入恢复后的首次 Provider 请求。

### 自动记忆层

新增记忆存储、LLM 决策服务和单工作线程队列。自然完成的 Agent 轮次生成有界 `TurnSnapshot`，最终回复展示后立即入队。后台线程使用与前台相同配置创建的独立 Provider 实例，串行处理任务，避免共享流式客户端和覆盖索引。LLM 负责分类、作用域、去重和合并决策；代码负责路径边界、格式校验、秘密拦截、原子写入和索引硬上限。

### Prompt 与 CLI 接入层

现有 `PromptOptions.custom_instructions` 承载三层项目指令，`PromptOptions.long_term_memory` 承载项目级和用户级索引，因此三类 Provider 继续使用现有统一请求结构。CLI 增加 `--new` 和 `/new`，显示启动恢复、清理、坏行、截断、时间跨度及记忆任务告警，并在 `/new` 和退出时执行有界等待。

主数据流：

```text
CLI 启动
  -> 清理 30 天过期会话
  -> 加载三层 MYCODE.md
  -> --new ? 创建会话 : 扫描并恢复最近有效会话
  -> 恢复消息导入 ContextManager
  -> 读取项目/用户记忆索引
  -> AgentRunner

普通轮次
  -> 用户消息先追加 JSONL，再进入 ContextManager
  -> 组装指令 + 最新两级索引 + 可选时间跨度提醒
  -> 现有上下文预算与压缩
  -> Provider / 工具循环
  -> 每条助手和工具消息依次追加 JSONL 与活动上下文
  -> 无工具最终回复
  -> 展示完成事件
  -> TurnSnapshot 入后台记忆队列
  -> LLM 决策、秘密检查、原子更新笔记与索引
```

## 核心数据结构

### InstructionBundle

- `content: str`：按高到低优先级拼接并带来源边界的最终指令
- `loaded_files: tuple[str, ...]`：成功加载的安全展示路径
- `warnings: tuple[InstructionWarning, ...]`：错误类型与安全路径，不含正文

### InstructionWarning

- `code`：`missing_include`、`unreadable`、`outside_scope`、`symlink_escape`、`cycle` 或 `max_depth`
- `source`：安全展示的包含方路径
- `target`：安全展示的目标相对路径；不得包含文件内容

### SessionRecord

每行统一使用版本化 envelope：

```json
{"version":1,"timestamp":"2026-07-21T10:30:00.000000+08:00","type":"message","message":{"role":"user","content":"...","tool_calls":[],"tool_call_id":""}}
```

- `version`：当前固定为 `1`，未知版本按坏行跳过
- `timestamp`：带时区 ISO 8601 时间，用于派生创建和最后活动时间
- `type`：本阶段固定为 `message`，为以后扩展保留 envelope
- `message`：与现有 `Message` 等价的 JSON；助手工具调用完整保存在该对象内

不写 created、title、count 或 active 等元数据记录，避免形成另一种隐式 meta。

### SessionSummary

- `session_id`：从文件名取得并校验
- `path`：受会话根约束的 JSONL 路径
- `title`：第一条有效用户消息压平空白后最多 80 个字符
- `message_count`：有效 message 记录数
- `created_at`：最早有效记录时间；没有记录时回退到 ID 中的时间
- `last_active_at`：最后有效记录时间
- `bad_line_count`：被跳过的行数

### SessionLoadResult

- `summary: SessionSummary`
- `messages: tuple[Message, ...]`：通过语法校验的最长合法前缀
- `bad_line_count`
- `truncated_message_count`
- `gap`：最后活动时间到当前时间的间隔
- `needs_time_gap_reminder`：严格超过 24 小时

### SessionJournal

- 当前 `session_id` 与 `.jsonl` 路径
- 单条追加并 `flush + fsync` 的能力
- 文件描述符生命周期由会话切换和 CLI 退出管理
- 追加使用一条 JSON + 一个换行的一次逻辑写入；序列化失败时不接触文件

### MemoryNote

文件名使用 `YYYYMMDD-HHMMSS-xxxx.md`，frontmatter 固定字段：

```yaml
---
id: 20260721-103000-a1b2
category: user_preference
scope: project
importance: 3
created_at: 2026-07-21T10:30:00+08:00
updated_at: 2026-07-21T10:30:00+08:00
source_session: 20260721-090000-c3d4
---
```

- `category`：`user_preference`、`correction_feedback`、`project_knowledge`、`reference`
- `scope`：`user` 或 `project`
- `importance`：1 到 5，用于索引兜底裁剪
- 正文固定为一个标题、一段简洁摘要和必要细节
- 更新现有笔记时保留 `id`、`created_at`，更新其余允许变化的字段和正文

### MemoryIndexEntry

- note ID、相对文件名、分类、importance、updated_at、标题和单行摘要
- 索引按四个分类分段；每个条目保持单行，便于精确计算行数和稳定裁剪
- 项目与用户作用域分别写入各自的 `index.md`

### TurnSnapshot

- `session_id`
- 当前轮用户原文
- 本轮助手文本与最终回复
- 工具名称、成功/失败和安全的短说明，不包含工具参数正文或完整工具结果
- 当前两级索引快照

该快照只供后台记忆判断，不落入会话以外的额外日志。

### MemoryDecision

- `operations`：零个或多个 `ignore`、`create` 或 `update`
- 每个非 ignore 操作包含目标 scope、category、importance、标题、单行索引摘要和候选正文
- update 必须引用输入索引中真实存在且属于同一 scope 的 note ID
- 决策响应使用唯一外层标记包裹 JSON，解析后执行严格 schema 校验

### MemoryJob

- job ID、session ID、`TurnSnapshot` 和取消标志
- 状态：queued、running、committed、failed、cancelled
- 取消只阻止磁盘提交；已开始且无法中断的 Provider 流可自然返回，但结果必须丢弃

## 核心接口

### InstructionLoader

- `load(workspace_root, user_root) -> InstructionBundle`
- 三个入口按 `.mycode/MYCODE.md`、根 `MYCODE.md`、用户 `MYCODE.md` 顺序处理
- 项目两个入口共享 workspace visited 集合；用户入口使用独立 visited 集合和 `~/.mycode` 边界
- include 深度从入口文件的 0 开始，允许子引用到深度 5

### SessionCatalog

- 创建不碰撞的会话 ID 和日志文件
- 扫描单个日志并计算 `SessionSummary`
- 清理过期日志并返回成功数及安全告警
- 从未过期、有首条用户消息且能形成合法前缀的候选中选择 `last_active_at` 最新者；并列时按 session ID 降序
- 不缓存或写入扫描结果

### SessionLoader

- 容错解析全部行并统计坏行
- 校验 message、tool call 和时间字段
- 按完整工具单元构造最长合法前缀
- 助手声明 N 个工具调用时，后面必须恰好出现这 N 个不同 ID 的 tool 消息；顺序可不同，但在全部结果齐备前不得出现非 tool 消息
- 首个孤立 tool、重复结果、未知结果 ID 或未闭合调用都会确定截断点

### SessionJournal

- `append(message, timestamp)` 同步追加一条 message record
- `close()` 刷新并关闭当前文件
- 写入失败抛出可分类错误；用户消息未成功持久化时不得发送 Provider 请求，助手或工具消息持久化失败时停止当前 Agent Loop，避免继续扩大不可恢复历史

### MemoryStore

- 分别绑定项目 memory root 与用户 memory root
- 读取并校验 index 和被选中的 note
- 对 note 与 index 使用同目录临时文件、`fsync`、原子替换
- 扫描 note frontmatter 与索引引用，在加载时补齐缺失条目、移除悬空条目并稳定排序
- 所有 LLM 提供的 ID、路径和 scope 都经过白名单校验，LLM 不能指定任意文件路径

### SecretScanner

- 检查 PEM 私钥块、常见 token 前缀、Bearer 凭据，以及 `api_key`、`token`、`password`、`secret`、`private_key` 等赋值形态
- 明确占位符和测试掩码可放行；实际候选命中时拒绝整项 note 及由它产生的 index 变更
- 返回规则代码，不返回命中的秘密文本

### MemoryService

- 第一阶段请求携带 `TurnSnapshot` 和两级 index，使用空工具集合，让 LLM 输出零到多个结构化决策
- create 决策可直接进入校验；update 决策先由代码读取唯一目标 note，再发起一次无工具合并请求，要求输出完整替换内容
- 对每项结果校验 scope、category、ID、frontmatter、正文和秘密规则
- 在持有单 worker 写入权时提交 note，再重建对应 index；崩溃造成的未索引 note 在下次加载时由扫描协调
- index 接近任一上限时发起无工具精简请求；若结果仍超限，按 importance 降序、updated_at 降序、ID 升序保留条目，并从最低优先级开始移除，最后按 UTF-8 字节边界缩短摘要

### MemoryWorker

- 一个 daemon 线程和 FIFO 队列，进程内最多一个 running job
- `submit(snapshot)` 在最终回复完成后立即返回
- `drain(timeout=5)` 等待当前及已排队任务；超时后取消未提交任务并返回安全告警
- worker 不直接写终端，把完成或失败通知放入线程安全 notice 队列，由 CLI 在输出边界读取

### ContextManager

- 新增从合法 `Message` 序列恢复活动条目的入口
- 恢复 tool 消息的 `complete_content`，让既有轻量卸载仍能写出完整工具结果
- 按恢复顺序重建 sequence；每个助手工具调用及其连续结果使用一个新 batch ID
- 不从 JSONL 恢复摘要、boundary、熔断计数、token anchor 或临时文件引用

### AgentRunner

- 接收当前 `SessionJournal`、`InstructionBundle`、两级 `MemoryStore` 和 `MemoryWorker`
- 所有原始 Message 都通过统一的“先 journal、后 context”入口加入两处
- 每次 Provider 请求前重新读取并渲染两级 `index.md`，保证已完成的后台更新对后续请求可见
- 恢复后的首个 iteration 注入一次时间跨度动态指令；仅在普通 Provider 请求真正发出后消费
- 自然完成时构造 `TurnSnapshot` 并提交后台任务；其他 stop reason 不提交
- 新增 `new_session()`：有界 drain 旧记忆任务、关闭旧日志和临时 context、创建新日志与 ContextManager，并清除恢复提醒和上一请求状态
- `close()` 依次有界 drain、关闭日志、清理当前 `.mycode/context/`，合并安全告警

### CLI

- 参数解析新增 `--new`
- 启动顺序固定为：加载配置、确定工作区、清理会话、加载指令、选择或创建会话、构建 Agent
- `/new` 必须是精确本地命令，不作为用户消息发送
- 启动和切换显示 session ID、恢复消息数、坏行数、截断数和时间跨度；不显示正文
- 每轮输入提示前和 Agent 结束后排空 memory notice 队列

## 模块设计

### 指令解析

**职责：** 解析三层入口和安全 include。

**语法：** 仅整行 `@include <relative-path>` 被识别；路径可使用 shell 风格单引号或双引号表示空格，但不支持 glob、URL、环境变量或绝对路径。相对路径以当前包含文件所在目录为基准。

**安全步骤：** 先拒绝绝对路径和语法错误，再拼接路径，最后解析真实路径并检查其属于当前作用域根。文件在 visited 中则报告 cycle/duplicate 并跳过；深度超过 5 不再读取。

### JSONL 持久化

**职责：** 保存永不被压缩改写的原始 Message 流。

**提交顺序：** 用户、助手和工具消息均先同步写 journal，再追加到 `ContextManager`。工具调用助手消息会在执行工具前写入，因此执行或进程中断自然形成可检测的未闭合尾部。一个批次的工具结果按模型调用顺序写入，不按并发完成顺序写入。

**错误处理：** 用户记录失败时本轮不发请求；助手或工具记录失败时产生 `session_error` 并停止循环。已经成功落盘的前缀保持有效，恢复时按工具单元规则截断不完整尾部。

### 恢复与压缩

**职责：** 把 JSONL 事实源转换为本进程活动历史。

恢复不修改原日志，也不把跳过和截断结果回写。合法前缀进入新的 `ContextManager`；下一次用户输入正常追加后，请求准备阶段调用现有 `prepare_request`。一次 prepare 最多调用一次摘要；失败或仍超预算时沿用 `context_overflow`，提示同时加入 `/new`。

时间跨度提醒使用独立动态 tag，内容只包含“距上次活动约 N 小时/天，文件、依赖、服务和需求状态可能已变化，请先核实再继续”。它不进入 Message 列表或 JSONL。

### 记忆 LLM 协议

**职责：** 将开放式模型输出收敛为可验证操作。

决策 prompt 明确四种分类、两种 scope、默认 project、语义去重、秘密禁令和不必每轮都记录。响应必须包含唯一 `<memory_update>`，内部是 JSON object。解析器拒绝额外标记、未知字段、非法枚举、跨 scope 更新、未知 target ID、空标题/正文和超过固定单项尺寸的结果。

update 使用第二个 prompt，输入当前 note 和新证据，输出完整 Markdown 正文与更新后的索引摘要；旧 note 不由第一阶段模型猜测。所有记忆请求 `tools=()`、`cache_static_content=False`，事件中出现工具调用即整次失败。

### 索引维护

**职责：** 让请求前注入保持小而有用。

正常写入后根据所有有效 note frontmatter 与 LLM 提供的单行摘要重建 index。索引包含作用域说明、四个分类标题和条目；使用 UTF-8/LF 计算硬限制。达到 180 行或 22KB 时提前请求 LLM 精简，最终写入前硬校验 200 行和 25KB。

LLM 精简只能修改条目摘要和 importance，不能发明、删除或改写 note ID。确定性兜底优先保留 importance 高、更新时间新、ID 稳定靠前的条目。未进入 index 的 note 文件保留在磁盘。

### 异步生命周期

**职责：** 在不延迟最终回复的前提下防止任务泄漏和覆盖。

队列只有一个 worker。`/new` 与退出调用 5 秒 drain；若超时，设置所有未提交 job 的取消标志。Provider 调用返回后、每个落盘事务开始前都检查取消标志，保证被放弃的旧 job 不会稍后写入。daemon worker 不阻止 Python 进程退出。

## 模块交互

### 启动恢复

1. CLI 解析 `--new`，加载配置、Provider 和工具。
2. `SessionCatalog` 扫描 `.mycode/sessions/`，按有效记录时间清理超过 30 天的文件。
3. `InstructionLoader` 读取三层 `MYCODE.md` 并收集告警。
4. `--new` 创建新日志；否则扫描未过期候选并恢复最近一份，没有候选时创建新日志。
5. `SessionLoader` 跳过坏行并截断不完整工具尾部。
6. `ContextManager` 导入合法消息，初始化空摘要和空 token 锚点。
7. `MemoryStore` 协调两个 scope 的 note 与 index。
8. CLI 输出不含正文的启动报告并进入交互循环。

### 普通 Agent Loop

1. AgentRunner 将用户 Message 追加到 journal，成功后加入 ContextManager。
2. 每个 iteration 读取两级索引，PromptBuilder 按 custom instructions、memory index 组装 optional system prompt。
3. 若为恢复后的首次真实请求，额外加入时间跨度动态指令。
4. ContextManager 执行现有轻量卸载、预算判断和必要摘要。
5. Provider 响应产生助手工具调用时，先追加助手记录，再执行工具；结果按调用顺序逐条追加。
6. 没有工具调用的助手结果先追加 journal 和 context，再发出 completed 事件。
7. completed 事件之后把本轮安全快照提交 MemoryWorker。

### `/new`

1. CLI 识别精确命令，不创建 AgentRequest。
2. AgentRunner 最多等待 5 秒处理当前及排队记忆任务。
3. 超时任务标记取消，旧 journal 关闭，旧临时 context 清理。
4. 创建新 session ID、journal 和空 ContextManager。
5. 手写指令保持启动时快照；记忆索引在下一普通请求前重新读取。
6. CLI 输出新 session ID 和安全告警。

### 自动记忆更新

1. worker 取出自然完成轮次的 TurnSnapshot。
2. 决策请求读取两个 index，输出零到多个操作。
3. 代码校验操作；update 只读取被引用的目标 note，并通过第二次请求合并。
4. 每个候选先经过格式、路径和 SecretScanner 校验。
5. 在未取消前原子写 note，按 scope 重建 index。
6. 接近上限时调用 LLM 精简；仍超限则确定性裁剪。
7. 成功或安全失败 notice 等待 CLI 在输出边界展示。

## 文件组织

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mycode/instructions.py` | 三层 `MYCODE.md`、include 展开、边界和告警 |
| 新建 | `src/mycode/sessions/__init__.py` | 导出会话公共类型 |
| 新建 | `src/mycode/sessions/models.py` | record、summary、load result、告警模型 |
| 新建 | `src/mycode/sessions/journal.py` | ID、JSONL 追加、flush/fsync 和关闭 |
| 新建 | `src/mycode/sessions/catalog.py` | 扫描派生元数据、最近选择和过期清理 |
| 新建 | `src/mycode/sessions/loader.py` | 坏行容错、schema 校验和工具单元截断 |
| 新建 | `src/mycode/memory/__init__.py` | 导出记忆公共类型 |
| 新建 | `src/mycode/memory/models.py` | note、index、decision、job、notice 模型 |
| 新建 | `src/mycode/memory/prompts.py` | 决策、合并和索引精简 prompt |
| 新建 | `src/mycode/memory/parser.py` | LLM JSON 响应及 Markdown/frontmatter 校验 |
| 新建 | `src/mycode/memory/secrets.py` | 确定性秘密检测 |
| 新建 | `src/mycode/memory/storage.py` | 双 scope note/index 原子存储与协调 |
| 新建 | `src/mycode/memory/service.py` | 无工具 LLM 决策、更新合并和索引精简 |
| 新建 | `src/mycode/memory/worker.py` | 单 daemon 队列、取消、drain 和 notices |
| 修改 | `src/mycode/context/manager.py` | 合法历史导入和恢复条目重建 |
| 修改 | `src/mycode/agent/events.py` | `session_error` 停止原因和安全状态事件 |
| 修改 | `src/mycode/agent/runner.py` | journal 双写、Prompt 注入、恢复提醒、记忆提交、新会话生命周期 |
| 修改 | `src/mycode/prompts/modules.py` | 指令与两级记忆的来源/优先级包装文案 |
| 修改 | `src/mycode/cli.py` | `--new`、`/new`、启动恢复和 notice 展示 |
| 修改 | `.gitignore` | 忽略 `.mycode/sessions/` 与 `.mycode/memory/` |
| 修改 | `README.md` | 指令、会话恢复、命令、记忆格式和边界说明 |
| 新建 | `tests/test_instructions.py` | 优先级、include、环路、深度和路径安全 |
| 新建 | `tests/test_session_journal.py` | ID、追加、fsync 错误和无 meta |
| 新建 | `tests/test_session_loader.py` | 坏行、schema、工具关联和截断 |
| 新建 | `tests/test_session_catalog.py` | 派生信息、最近选择和 30 天清理 |
| 新建 | `tests/test_memory_parser.py` | LLM schema、frontmatter 和非法目标 |
| 新建 | `tests/test_memory_secrets.py` | 凭据命中、占位符和安全错误 |
| 新建 | `tests/test_memory_storage.py` | 双 scope、原子写、协调和索引双上限 |
| 新建 | `tests/test_memory_service.py` | 分类、scope、去重、update 合并和空工具 |
| 新建 | `tests/test_memory_worker.py` | FIFO、单并发、取消、5 秒 drain 和 notices |
| 修改 | `tests/test_context_manager.py` | 恢复导入与完整工具结果再卸载 |
| 修改 | `tests/test_agent_runner.py` | journal 双写、提醒一次、自然完成入队和错误停止 |
| 修改 | `tests/test_cli.py` | `--new`、`/new`、启动/清理/恢复状态与退出等待 |
| 修改 | `tests/test_prompts.py` | 三层指令和项目/用户索引顺序 |
| 新建 | `tests/test_session_memory_integration.py` | 三类 Provider 兼容和完整跨进程场景 |

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 长期事实源 | 原始 Message JSONL | 压缩状态是模型窗口实现细节，不能替代可恢复原文 |
| 会话元数据 | 每次扫描派生 | 满足无 meta，消除双写同步问题 |
| JSONL durability | 每条 `flush + fsync` | 把异常损失限制在当前记录，代价在 CLI 交互频率下可接受 |
| 工具一致性 | 助手调用先落盘，结果逐条落盘，恢复按原子单元截断 | 崩溃状态可检测，不伪造缺失结果 |
| ContextManager 接入 | 导入恢复消息，不恢复旧摘要/锚点 | 沿用现有压缩器并避免临时路径失效 |
| 指令注入 | 复用 optional `custom_instructions` | Provider 已统一支持，不改变稳定系统 prompt 缓存 |
| 记忆注入 | 每次请求前读取两级 index | 后台任务完成后下一请求自然可见，无需热更新 Agent 状态 |
| 后台执行 | 单 daemon FIFO worker | 串行避免索引覆盖，超时任务不阻塞进程退出 |
| Provider 实例 | 同配置独立实例 | 保持模型与凭据一致，同时避免和前台流式请求共享客户端并发 |
| `/new`/退出等待 | 固定 5 秒 | 给正常短任务收尾机会，并提供明确上界；本阶段不新增配置 |
| 记忆协议 | 标记包裹 JSON + 严格 schema | 比自由 Markdown 更易验证操作、scope 和目标 ID |
| 更新去重 | LLM 先看有界 index，update 再读取唯一目标 note | 满足语义去重，不引入向量或无界加载全部正文 |
| 文件命名 | 时间戳 ID + 随机后缀 | 可读、可排序并降低同秒碰撞 |
| frontmatter | PyYAML 安全解析 | 项目已有依赖，避免手写 YAML 解析 |
| index 预警线 | 180 行或 22KB | 在 200 行/25KB 硬限制前留出标题和编码余量 |
| index 兜底 | importance、更新时间、ID 的稳定排序 | 在 LLM 不守限制时仍确定性满足双上限 |
| 秘密防护 | prompt 禁令 + 确定性 scanner | 单靠模型判断不足以保护磁盘持久化 |
| 新依赖 | 不增加 | 标准库线程/队列/文件 API 与现有 PyYAML 足够 |

## Spec 覆盖

- F1-F5：指令加载层、InstructionLoader、指令解析
- F6-F12：会话日志层、SessionJournal、SessionCatalog、CLI 启动与 `/new`
- F13-F17：SessionLoader、ContextManager 恢复、时间提醒与状态展示
- F18-F19：MemoryNote、MemoryStore、目录与 Git 忽略
- F20-F24：MemoryService、MemoryWorker、AgentRunner 自然停止和生命周期
- F25-F27：索引维护、请求前注入与 SecretScanner
- N1-N4：真实路径限制、原子文件操作、稳定排序和损坏隔离
- N5-N7：空工具记忆请求、单 worker、取消提交和安全 notice
- N8-N9：复用 Prompt/Context/Provider 边界与分层自动化测试
