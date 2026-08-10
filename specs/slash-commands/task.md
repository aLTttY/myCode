# MewCode 斜杠命令注册与分发 Tasks

## 依据

- 已批准需求：[`spec.md`](./spec.md)
- 已批准技术设计：[`plan.md`](./plan.md)

## 文件清单

### 新建文件

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mycode/commands/__init__.py` | 导出命令公共接口 |
| 新建 | `src/mycode/commands/models.py` | 命令、分流结果和安全状态快照 |
| 新建 | `src/mycode/commands/interfaces.py` | `CommandUI` 协议与命令错误 |
| 新建 | `src/mycode/commands/registry.py` | 注册、冲突检测、查找和补全候选 |
| 新建 | `src/mycode/commands/router.py` | 输入分类、命令解析和统一分发 |
| 新建 | `src/mycode/commands/builtins.py` | 内置命令、固定 review 提示和输出格式 |
| 新建 | `src/mycode/commands/completion.py` | Prompt Toolkit 补全适配器 |
| 新建 | `src/mycode/tools/git.py` | 固定参数的只读 Git 变更工具 |
| 新建 | `tests/test_command_registry.py` | 元数据、冲突、别名和顺序测试 |
| 新建 | `tests/test_command_router.py` | 输入分类、解析、分发和异常测试 |
| 新建 | `tests/test_command_builtins.py` | 十一条命令与三种类型测试 |
| 新建 | `tests/test_command_completion.py` | 补全候选与终端菜单测试 |
| 新建 | `tests/test_tools_git.py` | Git 工具安全与结果测试 |

### 修改文件

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `src/mycode/cli.py` | 命令启动、终端 UI、PromptSession、路由和状态栏 |
| 修改 | `src/mycode/agent/runner.py` | 指定模式的状态估算和压缩 |
| 修改 | `src/mycode/context/models.py` | 上下文状态与摘要 Token 字段 |
| 修改 | `src/mycode/context/manager.py` | 无副作用状态估算和 Token 传播 |
| 修改 | `src/mycode/context/summary.py` | 摘要 Token 收集与失败传播 |
| 修改 | `src/mycode/memory/models.py` | 记忆 Worker 状态快照 |
| 修改 | `src/mycode/memory/worker.py` | 非阻塞 Worker 状态查询 |
| 修改 | `src/mycode/permissions/service.py` | 会话规则数量查询 |
| 修改 | `src/mycode/tool_safety.py` | Git 工具只读分类 |
| 修改 | `src/mycode/tools/registry.py` | 默认注册 Git 工具 |
| 修改 | `src/mycode/tools/descriptions.py` | Git 工具强化说明 |
| 修改 | `src/mycode/tools/__init__.py` | 导出 Git 工具 |
| 修改 | `tests/test_cli.py` | CLI 分流、PromptSession、模式和回归测试 |
| 修改 | `tests/test_agent_runner.py` | 上下文状态和显式压缩模式测试 |
| 修改 | `tests/test_context_manager.py` | 状态估算和压缩 Token 测试 |
| 修改 | `tests/test_context_summary.py` | 摘要 Token 成功与失败测试 |
| 修改 | `tests/test_memory_worker.py` | Worker 状态测试 |
| 修改 | `tests/test_permissions_service.py` | 会话规则计数测试 |
| 修改 | `tests/test_agent_tools.py` | Plan Registry 的 Git 工具测试 |
| 修改 | `tests/test_tools_registry.py` | 默认工具集合测试 |
| 修改 | `tests/test_tool_descriptions.py` | Git 工具说明测试 |
| 修改 | `README.md` | 命令、别名、模式、状态和工具文档 |

## T1：上下文状态与压缩 Token 基础

**文件：**

- `src/mycode/context/models.py`
- `src/mycode/context/summary.py`
- `src/mycode/context/manager.py`
- `src/mycode/agent/runner.py`
- `tests/test_context_summary.py`
- `tests/test_context_manager.py`
- `tests/test_agent_runner.py`

**依赖：** 无

**步骤：**

1. 在上下文模型中增加不可变 `ContextStatus`，字段严格限于估算 Token、窗口、消息数、是否有摘要和自动摘要熔断状态。
2. 为 `SummaryOutput`、`SummaryFailure` 和 `CompactionReport` 增加可选摘要 `TokenUsage`，保持所有既有构造调用兼容。
3. 在 SummaryService 中保存最后一个 token 事件；成功解析、工具调用违规和格式失败均传播已经收到的用量，Provider 在统计前失败时保持 `None`。
4. 在 ContextManager 中把摘要用量写入成功与失败报告，不改变选择、事务、回滚、预算和熔断算法。
5. 增加无副作用 `status(template)`：只构建估算请求，不开启 transaction、不卸载内容、不调用 Provider、不修改 state 或 estimator anchor。
6. 在 AgentRunner 中增加按指定模式生成 ContextStatus 的入口；让 `compact` 可显式接收当前模式，同时保留旧缺省调用兼容。
7. 测试摘要成功、格式失败、工具调用违规、Provider 失败四种 Token 传播路径。
8. 测试 ContextStatus 的估算结果以及调用前后消息、summary、anchor、store 和 Provider 调用数完全不变。
9. 测试 AgentRunner 分别使用 default/plan 工具模板估算，并验证显式 compact 模式不受最近一次请求模式影响。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_context_summary.py \
  tests/test_context_manager.py \
  tests/test_agent_runner.py -q
```

期望：全部通过；状态查询的 Provider 调用数为 0，压缩报告在可用时含摘要 Token。

## T2：记忆与权限的安全状态入口

**文件：**

- `src/mycode/memory/models.py`
- `src/mycode/memory/worker.py`
- `src/mycode/permissions/service.py`
- `tests/test_memory_worker.py`
- `tests/test_permissions_service.py`

**依赖：** 无

**步骤：**

1. 增加只含 `idle/busy` 和 `pending_jobs` 的 MemoryWorkerStatus。
2. 在 MemoryWorker 的现有 condition 锁内读取 `_jobs`，实现不等待、不 drain、不取消的 `status()`。
3. 覆盖空闲、队列中、执行中、完成后和失败后状态，确保任务总数不会为负或泄漏 job 内容。
4. 在 PermissionService 增加线程安全的 `session_rule_count` 只读属性。
5. 覆盖无会话规则、一次“本会话同意”、重复同意去重以及并发读取；断言接口不返回规则表达式或 target。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_memory_worker.py \
  tests/test_permissions_service.py -q
```

期望：全部通过；状态查询立即返回且只暴露数量和枚举状态。

## T3：实现安全的 Git 变更读取工具

**文件：**

- `src/mycode/tools/git.py`
- `src/mycode/tool_safety.py`
- `src/mycode/tools/registry.py`
- `src/mycode/tools/descriptions.py`
- `src/mycode/tools/__init__.py`
- `tests/test_tools_git.py`
- `tests/test_agent_tools.py`
- `tests/test_tools_registry.py`
- `tests/test_tool_descriptions.py`

**依赖：** 无

**步骤：**

1. 定义无参数、拒绝 additional properties 的 `read_git_changes` ToolSpec。
2. 运行时再次拒绝非空 arguments，确保模型 schema 失效时也不能注入参数。
3. 使用参数数组和 `shell=False` 固定执行 status、未暂存 diff、已暂存 diff；禁用 external diff 和 textconv。
4. 用 monotonic 截止时间让三次调用共享 ToolContext 总超时；剩余时间耗尽时不再启动下一次调用。
5. 将成功结果按 status、unstaged_diff、staged_diff 组织；未跟踪文件正文不主动读取。
6. 将非仓库、Git 缺失、非零退出、超时和解码问题转为安全结构化结果，不输出环境、Git 配置或异常原文中的敏感内容。
7. 复用 ToolExecutionResult 的展示/完整双视图：展示受 `max_output_chars` 限制，完整结果交给既有上下文卸载。
8. 把工具加入默认 Registry、READ_TOOLS、公共导出和描述强化规则。
9. 使用临时 Git 仓库覆盖 staged、unstaged、untracked 和 clean 场景；通过 mock 验证完整 argv、`shell=False`、cwd 与共享超时。
10. 回归验证 Plan Registry 包含四个专用只读工具，权限分类为 read，默认 Registry 无命名冲突。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_tools_git.py \
  tests/test_agent_tools.py \
  tests/test_tools_registry.py \
  tests/test_tool_descriptions.py -q
```

期望：全部通过；任意参数被拒绝，Plan 模式可使用 `read_git_changes`，固定 Git 调用不经过 shell。

## T4：建立命令模型、UI 协议和注册中心

**文件：**

- `src/mycode/commands/__init__.py`
- `src/mycode/commands/models.py`
- `src/mycode/commands/interfaces.py`
- `src/mycode/commands/registry.py`
- `tests/test_command_registry.py`

**依赖：** T1

**步骤：**

1. 定义 CommandSpec、CommandInvocation、InputRoute、运行模式、命令类型和全部安全状态视图。
2. 定义 CommandUI Protocol，包含显示、清屏、发送消息、模式切换、压缩、Token/状态查询、新会话和状态栏刷新。
3. 定义 CommandRegistrationError 与 CommandExecutionError；前者只用于启动期元数据错误，后者携带安全用户消息。
4. 实现命令和别名合法性检查：规范名称正则、`?` 特例、禁止 `/` 和空白、`lower()` 归一化。
5. Registry 在提交前验证整条命令，保证失败注册不污染顺序表或 lookup。
6. 实现 resolve、visible/all commands 和 completion_candidates；保持登记顺序，隐藏过滤和完整可见别名优先规则。
7. 测试有效登记、无 handler 元数据、非法名称、名称—名称、名称—别名、别名—别名、大小写冲突、命令内部重复以及失败原子性。
8. 测试可见/隐藏枚举、别名解析、规范名称前缀和完整别名候选。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_registry.py -q
```

期望：全部通过；所有冲突在登记时确定性失败且不会覆盖先注册项。

## T5：实现输入路由与安全分发

**文件：**

- `src/mycode/commands/router.py`
- `src/mycode/commands/__init__.py`
- `tests/test_command_router.py`

**依赖：** T4

**步骤：**

1. 按批准顺序实现 empty、exit、plain、command、error 五类纯解析结果。
2. 对斜杠输入只在第一次空白处分隔，命令词 lower 后解析，参数仅 strip 外围空白。
3. 为 `/` 和未知命令生成包含 `/help` 的安全错误，不把原始长参数完整回显。
4. 实现 dispatcher：handler 缺失返回安全错误；CommandExecutionError 显示预定义消息；其他 Exception 只显示异常类型和规范命令名。
5. 确保 KeyboardInterrupt、EOFError 和 SystemExit 不被 dispatcher 捕获。
6. 测试空白、中文普通消息、大小写退出词、大小写命令、alias、内部参数空白、未知命令和仅 `/`。
7. 用记录型 CommandUI 验证解析阶段零副作用、命令只调用一次 handler、错误不触发 send_user_message。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_router.py -q
```

期望：全部通过；未知和失败命令不发送 Agent 消息，控制流异常保持上抛。

## T6：登记并实现全部内置命令

**文件：**

- `src/mycode/commands/builtins.py`
- `src/mycode/commands/__init__.py`
- `tests/test_command_builtins.py`

**依赖：** T1、T2、T4、T5

**步骤：**

1. 按 plan 固定顺序登记十个可见命令和隐藏 new，完整填写名称、别名、描述、用法、类型、参数提示、隐藏标记和 handler。
2. 为所有无参数命令使用统一验证；help 只接受零个或一个无空白命令词。
3. 实现 help 总览和详情，保证总览隐藏 new、显式 `/help new` 可查看、别名查询显示规范命令。
4. 实现 compact 报告格式，复用现有状态标签并追加可用的摘要 Token。
5. 实现 clear、plan、do，验证它们只调用对应 UI 能力；plan/do 切换后刷新状态栏。
6. 实现 session、memory、permission、status 的安全快照格式；不可用 Token 明确显示 unavailable，路径和计数按批准字段输出。
7. 固化 REVIEW_PROMPT，要求先调用 read_git_changes、只读核对、按严重度报告且不修改；handler 使用 mode_override=plan。
8. 实现隐藏 new，确保只调用 UI 新会话能力。
9. 用 FakeCommandUI 逐条验证全部规范名称与别名、三类 command_type、参数拒绝、无 Agent 调用的本地/UI 命令和 review 唯一发送路径。
10. 对状态格式执行敏感哨兵测试，确认输出不含 API Key、权限规则正文、记忆正文或 Provider URL。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_command_registry.py \
  tests/test_command_router.py \
  tests/test_command_builtins.py -q
```

期望：全部通过；Registry 中恰有十个可见命令和一个隐藏命令，只有 review 调用 `send_user_message`。

## T7：实现 Tab 补全适配器

**文件：**

- `src/mycode/commands/completion.py`
- `src/mycode/commands/__init__.py`
- `tests/test_command_completion.py`

**依赖：** T4、T6

**步骤：**

1. 实现 Prompt Toolkit Completer，只读取 `Document.text_before_cursor`。
2. 非斜杠、存在前导多词内容、命令词后已有空白或光标位于参数区时返回空。
3. 把 Registry 候选转换成替换完整命令词的 Completion，插入规范名称和结尾空格。
4. display 使用规范 `/name`，display_meta 包含描述与非空参数提示。
5. 验证 `/cl` 单匹配 clear、`/s` 多匹配 session/status、`/p` 完整别名优先 plan、`/n` 不暴露 new。
6. 使用 PipeInput 与 DummyOutput 验证 PromptSession 在 Tab 后的单补全、多候选菜单和中文描述渲染不异常。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_command_completion.py -q
```

期望：全部通过；隐藏命令从候选和菜单中消失，参数区没有命令补全。

## T8：接入 CLI、持久模式和状态栏

**文件：**

- `src/mycode/cli.py`
- `tests/test_cli.py`

**依赖：** T1—T7

**步骤：**

1. 在 CLI 参数解析后、配置和 Provider 初始化前创建默认命令 Registry；捕获 CommandRegistrationError，打印冲突并返回 1。
2. 创建 TerminalCommandUI，注入 Agent、AppConfig、PermissionConfigSet/Service、MemoryStore/Worker、工作区、恢复来源和 Agent 单轮渲染回调。
3. 用唯一字段保存 current_mode、session_origin 和 last_token_usage；初始 mode 为 default，恢复会话只改变 origin。
4. 实现全部 CommandUI 方法：安全显示、Prompt Toolkit 清屏、模式切换、同步 Agent 请求、compact、状态组合、new session 和 toolbar 刷新。
5. `send_user_message` 使用 `mode_override or current_mode` 构造 AgentRequest；token_usage 事件更新 last usage，compact 报告有摘要 usage 时同样更新。
6. `/new` 完成后 origin 设为 new、Token 清空、mode 不变；`/clear` 不改变任何三项状态。
7. 从 MemoryStore、MemoryWorker、PermissionConfigSet/Service、AgentRunner 构造安全快照；mode source 正确处理 CLI/local/project/user/default，规则来源顺序为 session/local/project/user。
8. 创建一个 PromptSession，配置 CommandCompleter、`complete_while_typing=False`、列式菜单和动态 `[DEFAULT]/[PLAN]` bottom toolbar。
9. 将输入循环改为 InputRouter：empty 继续、exit 退出、error 显示、plain 发送、command 分发；移除 `/compact`、`/new`、`parse_agent_request` 的旧分支。
10. 抽出并复用 Agent 单轮事件渲染，保持流式文本、工具事件、Token、上下文报告、ProviderError 和取消行为。
11. 更新现有 FakeAgent/Fake input 测试缝隙，避免测试依赖真实 TTY。
12. 增加启动冲突早于 Provider、普通输入当前模式、plan/do 不调用 Agent、review 单次 plan、status 不联网、clear 保状态、new 保模式、PromptSession 复用和 toolbar 切换测试。
13. 增加端到端输入序列 `/p` → 普通任务 → `/status` → `/review` → `/d` → `/clear` → `/help status` → `exit`，断言只有普通任务和 review 进入 Agent。
14. 回归 Ctrl+C/Ctrl+D、exit/quit/退出、中文输入、MCP 清理、会话恢复、记忆通知和 ProviderError。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_cli.py \
  tests/test_command_registry.py \
  tests/test_command_router.py \
  tests/test_command_builtins.py \
  tests/test_command_completion.py -q
```

期望：全部通过；端到端序列只有两个 AgentRequest，模式和状态栏符合预期，所有本地状态查询零网络调用。

## T9：文档、编译检查与全量回归

**文件：**

- `README.md`
- 上述全部新增和修改文件

**依赖：** T8

**步骤：**

1. 更新 README 启动提示和交互说明，列出十个可见命令、全部别名、`/help <命令>`、双模式状态栏和隐藏 `/new` 兼容行为。
2. 把工具系统从六个更新为七个，说明 `read_git_changes` 是固定调用、无参数、只读且用于 review。
3. 明确 `/compact` 可能调用摘要 Provider，其他本地/UI 命令不调用模型；review 单次只读且不改变持久模式。
4. 搜索并更新仍把 `/plan <任务>`、`/do <任务>` 描述为一次性前缀的过期文案。
5. 运行 compileall、命令相关测试、领域回归和全量 pytest。
6. 运行 `git diff --check`，检查没有调试输出、测试临时文件、真实密钥或工作区会话文件进入变更。
7. 对照 spec 的 F1—F21 和 N1—N10 做实现覆盖复核，未覆盖项不得进入 checklist 验收。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m compileall -q src
PYTHONPATH=src .venv/bin/python -m pytest -q
git diff --check
```

期望：编译成功、全量测试全部通过、diff 无空白错误，README 与最终行为一致。

## 需求覆盖

| 任务 | 覆盖需求 |
|---|---|
| T1 | F10、F12、F14、F17；N2、N7、N8 |
| T2 | F15、F16、F17；N3、N6、N7 |
| T3 | F18；N2、N5、N6、N7、N8 |
| T4 | F1、F2、F5、F6、F8、F19、F20；N1、N3、N4、N5 |
| T5 | F3、F4、F7、F21；N1、N2、N4、N5、N8 |
| T6 | F5、F9、F10、F11、F12、F13、F14、F15、F16、F17、F18、F19、F20；N2、N3、N6、N7 |
| T7 | F8、F19、F20；N1、N7、N9 |
| T8 | F3、F4、F6、F7、F8、F10、F11、F12、F13、F14、F15、F16、F17、F18、F20、F21；N2、N3、N4、N5、N6、N7、N8、N9、N10 |
| T9 | F1、F2、F3、F4、F5、F6、F7、F8、F9、F10、F11、F12、F13、F14、F15、F16、F17、F18、F19、F20、F21；N1、N2、N3、N4、N5、N6、N7、N8、N9、N10 |

## 执行顺序

```text
T1 ───────────────┐
T2 ───────────┐   │
T3 ───────────┼───┼──────────────┐
T4 → T5 ──────┼───┤              │
      └─→ T6 ←┘   │              │
T4 ─────→ T7 ← T6 │              │
                  └─→ T8 ← T2/T3/T5/T6/T7
                           │
                           └─→ T9
```

推荐顺序为 `T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9`。T1、T2、T3 在代码依赖上可独立，但串行执行便于每个验证点保持清晰；T8 只有在全部基础模块完成后开始。
