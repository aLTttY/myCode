# Mycode

Mycode 是一个命令行 AI 编程助手。当前版本支持交互式多轮对话、基础工具系统、Agent Loop 和分层权限控制，让模型可以围绕一次用户任务反复调用工具、观察结果并继续推进，直到任务完成或触发停止条件。

## 安装依赖

需要 Python 3.10 或更高版本。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

## 配置

默认读取当前目录的 `config.yaml`，也可以通过 `--config` 指定路径。

推荐从示例复制：

```bash
cp config.example.yaml config.yaml
```

DeepSeek 示例：

```yaml
protocol: deepseek
model: deepseek-v4-pro
base_url: https://api.deepseek.com
api_key: ${DEEPSEEK_API_KEY}
context_window_tokens: 128000
```

OpenAI 示例：

```yaml
protocol: openai
model: gpt-4.1
base_url: https://api.openai.com/v1
api_key: ${OPENAI_API_KEY}
context_window_tokens: 128000
```

Anthropic 示例：

```yaml
protocol: anthropic
model: claude-sonnet-4-5
base_url: https://api.anthropic.com
api_key: ${ANTHROPIC_API_KEY}
context_window_tokens: 200000
thinking:
  enabled: true
  budget_tokens: 4096
```

`context_window_tokens` 是必填项，应填写当前模型实际支持的上下文窗口。可选的 `tool_result_threshold_tokens` 和 `tool_batch_threshold_tokens` 默认分别为 8000 和 16000。

不要把真实 API Key 写入配置文件。请使用环境变量：

```bash
export DEEPSEEK_API_KEY="your-key"
```

### MCP Server

Mycode 启动时会发现外部 MCP Server 的工具，并以 `<server>__<tool>` 注册到工具中心。例如 Server `docs` 提供的 `search` 会成为 `docs__search`。支持本地子进程 stdio 和远程 Streamable HTTP：

```yaml
mcp_servers:
  local-files:
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "${MCP_ROOT}"]
    env:
      LOG_LEVEL: "${MCP_LOG_LEVEL}"

  company-tools:
    transport: http
    url: "https://${MCP_HOST}/mcp"
    headers:
      Authorization: "Bearer ${MCP_TOKEN}"
```

MCP Server 配置有两层：用户级 `~/.mycode/config.yaml` 先加载，项目级 `./config.yaml`（或 `--config` 指定文件）后加载。不同名字的 Server 都会保留；同名时项目级定义整体覆盖用户级定义，不做字段拼接。Provider 配置始终来自项目级文件。

`args`、`env`、`url` 和 `headers` 的字符串支持一个或多个 `${VAR}` 展开。变量未设置会在连接前产生配置错误，设置为空字符串则合法。stdio 子进程继承当前进程环境，配置中的 `env` 覆盖同名变量。HTTP 的协议 headers 和 Session ID 由 MCP SDK 管理，因此配置不能覆盖这些保留字段。

单个 Server 连接、初始化或工具发现失败只输出警告，不影响其他 Server 或七个内置工具。非法名称、最终名称超过 64 字符、重复工具也只跳过冲突项；已经注册的工具不会被覆盖。会话和连接在进程内缓存，并在 CLI 退出时关闭。

所有 MCP 工具都按有副作用工具处理并串行执行，不采信远端只读注解。权限规则目标固定为 `call`，例如：

```yaml
allow:
  - "company-tools__search(call)"
```

default 模式的“本会话同意”会允许该 MCP 工具之后的不同参数调用，但重启后失效。当前只接收文本与 `structuredContent`；image、audio、embedded resource 和 resource link 会返回结构化的不支持错误。本阶段不实现 Resources、Prompts、Sampling、健康检查、自动重连或运行时动态重载工具。

## 运行

```bash
PYTHONPATH=src .venv/bin/python -m mycode
```

指定配置：

```bash
PYTHONPATH=src .venv/bin/python -m mycode --config config.yaml
```

切换本次进程的权限模式：

```bash
PYTHONPATH=src .venv/bin/python -m mycode --permission-mode strict
```

进入交互界面后输入问题，Mycode 会流式打印模型回复，并在需要时自动执行工具调用。输入 `exit`、`quit` 或 `退出` 结束会话。

默认启动会恢复当前项目 30 天内最近活动的有效会话。使用 `--new` 可在启动时跳过恢复。会话以 `.mycode/sessions/<YYYYMMDD-HHMMSS-xxxx>.jsonl` 逐行追加保存，不维护单独 meta 文件；启动时会清理超过 30 天的存档。恢复间隔超过 24 小时时，下一次模型请求会收到一次状态可能变化的提醒。

交互界面底部显示持久模式 `[DEFAULT]` 或 `[PLAN]`。`/plan` 进入只读计划模式，之后的普通输入都使用 Plan Mode；`/do` 返回默认执行模式。两条切换命令都不接受任务参数，也不会调用模型。新进程固定从 DEFAULT 开始。

斜杠命令由统一目录注册，命令名和别名大小写不敏感。输入命令前缀后按 Tab：单个候选会直接补全，多个候选显示带描述的菜单；隐藏命令不参与补全。

| 命令 | 别名 | 行为 |
|---|---|---|
| `/help [命令]` | `/h`、`/?` | 显示命令总览或单条帮助 |
| `/compact` | `/cmp` | 压缩当前上下文并显示前后估算与可用 Token |
| `/clear` | `/cls` | 只清除终端显示，不清除会话或上下文 |
| `/plan` | `/p` | 进入持久的 PLAN 模式 |
| `/do` | `/d` | 返回持久的 DEFAULT 模式 |
| `/session` | `/sess` | 显示当前会话 ID、来源、消息数和上下文概况 |
| `/memory` | `/mem` | 显示两级记忆数量、索引路径和后台状态 |
| `/permission` | `/perm` | 显示生效权限模式、来源和各层规则数量 |
| `/status` | `/st` | 汇总模式、模型、权限、会话、Token、上下文和记忆状态 |
| `/tasks` | 无 | 本地查看当前会话的子 Agent 任务、状态与用量 |
| `/commit [要求]` | 无 | 加载内置共享 Skill，检查、验证并按权限创建 Git 提交 |
| `/review [范围]` | `/rev` | 在独立、只读、无历史上下文中运行内置审查 Skill |
| `/test [要求]` | 无 | 加载内置共享 Skill，识别并运行相关测试 |

`/help` 总览会同时列出固定命令和当前生效的 Skill 命令。兼容命令 `/new` 仍可完成当前会话收尾并创建空白会话，但不会出现在总览或补全中；可用 `/help new` 显式查看。`/new` 保留当前模式、清空最近 Token 状态，并清除当前会话已激活的 Skill。

除 Skill 命令和 `/compact` 必要的摘要请求外，固定斜杠命令都不会进入 Agent Loop。`/compact` 在无需摘要时完全本地执行，需要摘要时只调用摘要 Provider。`/review` 不再是固定提示命令，而是内置的独立 Skill；它只报告缺陷、回归、安全问题和测试缺口，不修改文件。

## Skills

Skill 把可复用的 Agent 操作保存为 Markdown SOP。Mycode 按“项目 > 用户 > 内置”的优先级加载三个目录中的同名定义：

```text
项目级：<workspace>/.mycode/skills/
用户级：~/.mycode/skills/
内置：mycode.skills.builtins 包资源
```

最简单的 Skill 是目录根部的单个 `.md` 文件。文件使用严格 YAML frontmatter，正文是激活后发给模型的 SOP：

```markdown
---
name: explain-change
description: 解释当前改动及其风险
allowed_tools:
  - read_git_changes
  - read_file
  - search_code
mode: shared
---
先读取当前改动，再按风险顺序解释。附加要求见当前 user 消息：{{input}}
```

必填字段是 `name`、`description`、`allowed_tools` 和 `mode`。`mode` 只能是 `shared` 或 `isolated`。独立模式还必须提供非负整数 `history`，表示复制最近多少个完整主对话轮次；它可以用 `model` 指定同一 Provider 下的另一模型。共享模式禁止 `history` 和 `model`，未知字段会使该定义失效。`{{input}}` 只引用斜杠命令或当前请求传入的 user 角色数据，不会把参数拼进 system/SOP 文本。

Mycode 使用两阶段加载。启动和每轮重建时，模型只看到尚未激活 Skill 的名字与一句说明；需要时模型调用系统工具 `load_skill`，下一轮才会看到完整 SOP 和专属工具。`load_skill` 始终可用且无需业务权限，但不会代替任何业务工具执行读写、命令或网络操作。

共享模式在当前主对话中运行，消息和工具结果保留在主历史；多个共享 Skill 可同时激活，其 `allowed_tools` 取并集。独立模式创建一次性 Agent，只带指定数量的完整历史，结束时把最终 assistant 文本作为摘要回流主历史，中间文本和工具轨迹不会进入主会话。独立 Agent 可以临时加载共享 Skill，但不能嵌套另一个独立 Skill。Plan Mode 会在白名单基础上继续移除有副作用工具；白名单只控制可见性，不授予权限。

目录型 Skill 是一个能力包，入口固定为 `<skill-dir>/SKILL.md`。专属工具放在 `tools/` 下，每个工具由同名 YAML schema 和 Python 实现脚本组成。例如 `tools/lookup.yaml`：

```yaml
name: lookup
description: 查询项目内的受控数据
parameters:
  type: object
  properties:
    key: {type: string}
  required: [key]
  additionalProperties: false
script: lookup.py
```

它会以 `<skill-name>__lookup` 暴露。Mycode 用当前 Python 解释器直接启动脚本，不经过 shell；stdin 是 `{"arguments": {...}, "context": {"workspace_root": "..."}}`，stdout 必须只包含 `{"ok": true|false, "message": "...", "data": {...}}`。脚本使用最小环境、受限工作目录、有界输出和超时，并始终按有副作用工具走目标为 `call` 的权限审批。

每个生效 Skill 会自动注册为 `/<name> [input]`，并出现在 `/help` 和 Tab 补全中。Mycode 在处理下一条输入前检查文件变化；新增、修改、删除、优先级覆盖和专属脚本更新无需重启。单个非法文件会被隔离并打印诊断，不阻断其他合法 Skill 更新。`/clear` 只清屏，不清除激活状态；`/new` 清除全部激活状态。内置样板为共享 `/commit`、独立只读 `/review`（别名 `/rev`）和共享 `/test`，都可以被项目或用户级同名定义覆盖。

本阶段不包含 Skill 市场分发、远程安装或版本管理。

## 子 Agent 委派

主 Agent 始终拥有 schema 固定的 `Agent` 与 `Task` 两个控制工具。`Agent` 通过 `type: defined|fork` 选择两条路径：

- 定义式需要 `role`，从空白消息历史、项目指令和角色系统提示开始，不继承父对话、激活 Skill、长期记忆或 journal。
- Fork 式禁止 `role`，复制触发 `Agent` 调用前实际发送的父请求，包括 system、消息和原顺序工具 schema，再追加子任务 user 消息；它始终立即进入后台。首次请求不插入压缩或 Hook prompt，以保留可缓存前缀。

角色是严格的 Markdown + YAML frontmatter 文件：

```markdown
---
name: reviewer
description: 只读审查当前工作区改动
allowed_tools: [read_file, find_files, search_code, read_git_changes]
denied_tools: []
model: inherit
max_iterations: 8
permission_mode: strict
---
你是只读代码审查 Agent。按严重程度报告可验证的问题。
```

七个字段均必填，未知字段、重复 YAML key、空正文、非法工具或 `bypass` 权限都会使单个定义失效。`model` 可为 `inherit`、`haiku`、`sonnet`、`opus`；后三者必须在 `config.yaml` 的 `agents.model_aliases` 中映射到当前 Provider 的真实模型 ID。`permission_mode` 只允许 `inherit`、`default`、`strict`。

加载优先级固定为：

```text
项目 <workspace>/.mycode/agents/ > 用户 ~/.mycode/agents/
  > 内置 mycode.agents.builtins > 宿主按顺序注入的插件目录
```

启动时和每次主请求前都会检查增删改；已创建任务固定使用创建时快照。插件目录只通过 `AgentCatalog` 构造参数注入，不进行插件发现或安装；多个插件目录同名时先注入者生效并产生诊断。内置 `explore` 角色只允许四个只读工具。

定义式默认前台等待 30 秒：期限内完成会直接返回结果和 Token/cache 用量；`background: true` 会立即返回任务 ID；超时或等待界面按 `Ctrl+B` 时，同一任务转为后台继续执行，不取消、不重启。所有任务由固定 worker 和 FIFO 队列托管，默认并发 4、额外排队 32，可在 `agents` 配置中调整。Fork 强制后台。

后台结束只打印一次终端通知，不自动调用主模型。结果进入所属主会话 inbox，在下一次真实用户请求前以带边界的普通 user 消息注入，并沿用现有 SessionJournal；完整结果可用 `Task get`，也可用 `Task list|get|wait|cancel` 管理当前会话任务。`Task wait` 有配置上限，超时不会取消任务；用户可用 `/tasks` 查看脱敏摘要。

每个子 Agent 隔离消息、Token 累计、临时权限授权、文件读取缓存、取消状态和 Hook scope，同时复用 Provider 连接池、Hook 规则/动作引擎和同一工作区文件系统。子 Agent 不显示审批菜单：需要人工批准的调用会收到结构化拒绝并可继续改用安全方案。工具调用依次受全局禁令、角色白黑名单、Plan 只读限制、后台 allowlist、Hook 和独立权限限制；Defined 看不到 `Agent`、`Task`、`load_skill`，Fork 为缓存保留父工具 schema，但运行时同样硬拒绝这些调用，因此不能创建孙 Agent 或管理同级任务。

`/new` 会取消旧会话任务并清空未投递 inbox；退出会在有界时间内取消任务并关闭共享基础设施。任务表、队列、未投递结果和独立权限审计不跨进程恢复；已经注入历史的结果只按普通消息恢复。

本阶段不提供子 Agent Worktree/分支隔离、多 Agent 团队编排、任务依赖图、远程执行或后台任务跨会话/跨进程持久化。

## 项目指令与长期记忆

Mycode 启动时按高到低优先级加载 `.mycode/MYCODE.md`、项目根 `MYCODE.md` 和 `~/.mycode/MYCODE.md`。指令可用整行 `@include relative/path.md` 引用文件，最多嵌套 5 层；项目引用不能离开工作区，用户引用不能离开 `~/.mycode/`，环路、越界和符号链接逃逸会被跳过。

Agent 自然完成一轮后会异步分析是否需要记录用户偏好、纠正反馈、项目知识或参考资料。项目记忆位于 `.mycode/memory/`，用户记忆位于 `~/.mycode/memory/`；每条记忆是带 frontmatter 的 Markdown，两级目录各有 `index.md`。下一次请求前会直接注入项目级和用户级索引，项目级优先。索引最多 200 行且不超过 25KB。

自动记忆使用相同模型配置但不开放工具。`/new` 和正常退出最多等待 5 秒让后台更新收尾；疑似 API Key、令牌、密码或私钥的候选会被拒绝。项目的会话和自动记忆目录默认由 Git 忽略；手写 `MYCODE.md` 仍可提交。本阶段不包含向量数据库、RAG、团队同步或任意历史会话选择器。

## 上下文管理

Mycode 在每次模型请求前先检查工具结果。单个结果或同一轮结果合计过大时，完整内容会临时写入工作区的 `.mycode/context/<会话>/`，模型历史只保留首尾预览和可重新读取的相对路径。

当累计历史接近窗口上限时，Mycode 会把较早历史压缩成六段结构化摘要，同时保留近期约 10K token 且至少 5 条消息。摘要和压缩边界作为 system 上下文发送；模型需要文件或代码细节时必须重新读取，不能根据摘要猜测。

自动压缩预留 13K token 安全余量，`/compact` 使用 3K 余量。摘要连续失败三次后，本会话停止自动摘要，但仍可执行 `/compact`；手动成功后恢复。压缩后仍超预算时，请求不会发送，并会显示当前估算量和重试提示。

上下文文件只供当前进程会话使用，正常退出时自动删除。异常崩溃可能留下文件，因此 `.mycode/context/` 默认被 Git 忽略。

## 工具系统

Mycode 当前提供七个核心工具：

- `read_file`：读取工作区内文本文件。
- `write_file`：向工作区内文件写入完整内容。
- `edit_file`：用原文唯一匹配替换方式修改文件。
- `run_command`：在工作区内执行命令并返回退出码、stdout、stderr。
- `find_files`：按文件名或路径模式查找文件。
- `search_code`：按文本或正则搜索代码内容。
- `read_git_changes`：用固定、无参数的 Git 调用读取当前工作区的 staged、unstaged 和 untracked 状态。

`read_git_changes` 不接受 revision、路径、Git 参数或任意命令，并禁用 external diff 与 textconv。它主要供 `/review` 识别未提交变更；未跟踪文件只显示在状态列表中，需要内容时再由 `read_file` 读取。

文件工具限制在启动 Mycode 时的当前工作区内。越界路径、命令失败、超时、权限拒绝和参数错误会作为结构化工具结果返回给模型，而不是让 Mycode 崩溃。

## 权限系统

`read_file`、`find_files`、`search_code`、`read_git_changes` 是专用只读工具：目标和工作区边界校验通过后直接执行，不进入权限规则、权限模式或人工审批。历史配置中的只读 allow/deny 规则仍可解析，但不影响这四个工具执行。

`write_file`、`edit_file`、`run_command` 仍依次经过不可覆盖的危险命令黑名单、路径沙箱、分层规则、权限模式，以及必要时的用户确认。`run_command` 始终按有副作用工具处理，即使执行的是 `ls`、`cat` 或 Git 查看命令。权限拒绝会回灌 Agent Loop，模型可以改用更安全的工具、命令或路径继续任务。

权限规则使用三个可选 YAML 文件：

```text
用户级：~/.mycode/permissions.yaml
项目级：<workspace>/.mycode/permissions.yaml
本地级：<workspace>/.mycode/permissions.local.yaml
```

本地文件默认被 Git 忽略。规则优先级为“会话 > 本地 > 项目 > 用户”；同层按“精确 > 正则 > glob、deny、声明顺序”选择。

示例：

```yaml
mode: default

allow:
  - "run_command(glob:git *)"
  - "run_command(re:^python3? -m pytest(?: |$))"

deny:
  - "write_file(.env)"
  - "run_command(glob:git push *)"
  - "!write_file(glob:docs/*)"
```

规则使用真实工具名。`run_command` 匹配完整命令，写入和编辑工具匹配规范化的工作区相对路径。无前缀模式继续兼容旧行为：包含 `*`、`?` 或 `[...]` 时使用大小写敏感 glob，否则精确匹配。`glob:` 可显式指定 glob，`re:` 使用大小写敏感正则搜索；规则最前面的 `!` 表示反向匹配。四个专用只读工具不使用规则判定。

三档权限模式与 `[DEFAULT]`/`[PLAN]` 交互模式相互独立：

- `strict`：规则未命中时拒绝。
- `default`：规则未命中时请求用户确认。
- `allow`：规则未命中时放行。

命令行 `--permission-mode` 优先于本地、项目和用户配置；所有位置都未声明时使用 `default`。default 模式使用方向键菜单确认：上、下方向键移动高亮，回车确认。菜单只提供“不同意、仅本次同意、本会话同意”，默认高亮“不同意”，不接受字母命令，也不提供永久同意。

交互审批不会写入任何权限文件。需要长期规则时，用户可以手工编辑 `.mycode/permissions.local.yaml`；该文件仍在下次启动时加载，并保持“本地 > 项目 > 用户”的优先级。

危险命令黑名单和路径沙箱不能被配置、权限模式或人工确认覆盖。文件工具会解析符号链接并拒绝项目外路径；命令工具会检查可识别的显式路径。命令通过环境变量、用户配置、运行库或程序内部逻辑产生的隐式文件访问不受本阶段强隔离，完整限制需要后续引入操作系统沙箱或容器。

## 生命周期 Hooks

Hooks 用声明式“事件 + 可选条件 + 动作”在 Agent 生命周期的固定节点执行自动化。配置从以下三层加载，并严格按用户、项目、本地及文件声明顺序触发：

```text
用户级：~/.mycode/hooks.yaml
项目级：<workspace>/.mycode/hooks.yaml
本地级：<workspace>/.mycode/hooks.local.yaml
```

本地文件默认由 Git 忽略。缺失文件等同空配置；任一层存在重复 YAML key、未知字段、非法正则或不兼容动作时，Mycode 会在连接 Provider/MCP 及执行任何 Hook 前阻止启动，不会加载部分规则。

每条规则必须包含一个 `event` 和一个 `action`，`if` 省略时无条件触发：

```yaml
hooks:
  - event: tool_before
    if:
      all:
        - "tool.name(run_command)"
        - "tool.arguments.command(re:^(rm|sudo)\\s)"
    action:
      type: command
      command: ./scripts/check-tool.sh
      timeout_seconds: 5
      once: false
      async: false

  - event: context_compacted
    action:
      type: prompt
      content: 压缩刚刚发生，请重新核对关键文件后再继续。
      once: true

  - event: turn_end
    action:
      type: http
      url: https://example.internal/agent-events
      method: POST
      headers:
        Authorization: Bearer static-token
      async: true
```

支持十种事件：

- 会话级：`session_start`、`session_end`
- 轮次级：`turn_start`、`turn_end`
- 消息级：`message_received`、`message_sent`
- 工具级：`tool_before`、`tool_after`
- 系统级：`context_compacted`、`agent_error`

一次完整用户输入只产生一组轮次事件；模型流式增量和内部模型—工具迭代不会重复产生消息或轮次事件。`tool_after` 的 `result.source` 可区分 `tool`、`permission`、`hook`、`policy` 和 `validation`。子 Agent 事件额外带任务类型、任务 ID 和角色作用域。只有成功的自动/手动压缩产生 `context_compacted`；普通工具失败、权限/Hook 拒绝、取消和迭代上限不产生 `agent_error`。

条件顶层必须且只能使用一个非空 `all` 或 `any` 列表，不支持嵌套或混用。条件项格式为 `字段(模式)`，使用与权限规则相同的精确、`glob:`、`re:` 和前置 `!` 语法，例如 `!tool.arguments.command(glob:safe/*)`。缺失字段、对象和数组不匹配，即使使用反向模式也不会变成命中。常用字段包括 `event`、`session.id`、`turn.mode`、`message.content`、`tool.name`、`tool.arguments.<路径>`、`result.ok`、`result.source` 和 `result.data.<路径>`；启动校验会拒绝当前事件不可用的字段。

四类动作行为如下：

- `command`：以工作区为 cwd 通过 shell 执行，事件的 schema v1 JSON 从 UTF-8 stdin 输入；`timeout_seconds` 为 0.1–300 秒，默认 10 秒。
- `http`：把同一 JSON Payload 作为固定 `application/json` body 发送，默认 `POST`，固定 10 秒超时；可配置静态 URL、method 和 headers，但不能覆盖 `Content-Type`。
- `prompt`：把静态内容注入事件后的下一次真实模型请求，成功提交后立即移除，不进入会话历史；`session_end` 禁止此动作。
- `agent`：本阶段只校验并记录“尚未实现”，不会创建 Provider、Agent、线程或会话。

command、URL 和 headers 不做事件模板替换，动态数据只能从 JSON Payload 读取。`once: true` 在当前活动会话内成功、拒绝、入队或占位后不再触发；失败、取消和条件未命中不消耗，`/new` 或进程重启后重置。只有 command/HTTP 可设置 `async: true`；所有 `tool_before` 动作都必须同步，后台队列有界且退出时不等待。

`tool_before` 在注册校验、权限和工具启动前执行。command 返回 0 表示放行，返回 2 表示拒绝并使用受限 stderr 作为原因；HTTP 必须返回严格的 `{"decision":"allow"}` 或 `{"decision":"deny","reason":"..."}`。拒绝会停止该工具调用剩余前置规则，并作为失败工具结果回灌模型；allow 不能绕过危险命令、沙箱或权限。其他退出码、超时、网络错误、无效响应及普通 Hook 故障只产生 `[hook]` 诊断并默认继续 Agent 主流程，也不会递归触发 Hook。

Payload 始终包含 `schema_version`、带时区时间、工作区和会话信息；活动轮次及事件专属的消息、工具、结果、压缩或错误字段按需出现。各条件和动作观察同一份只读 Payload。

## Agent Loop

Agent Loop 使用 ReAct 风格循环工作：每一轮请求模型、流式收集文本和工具调用、执行工具、把工具结果回写进对话历史，再进入下一轮判断。循环会在以下情况停止：

- 模型不再请求工具并给出最终回复。
- 达到最大迭代次数。
- 用户取消当前任务。
- 连续请求未知工具超过阈值。
- 模型流式响应出错，或工具调用参数无法解析。

一次模型响应里出现多个工具调用时，Mycode 会按安全性分批：有副作用工具串行判定和执行；专用只读工具通过目标校验后直接并发执行，不会产生审批提示。审批过程保持串行，避免多个交互菜单重叠。

## 系统提示

Mycode 会为每轮模型请求构造结构化系统提示。稳定的全局规则按身份、系统约束、任务模式、动作执行、工具使用、语气风格和文本输出组织；工作目录、日期、运行模式等环境信息作为系统级动态消息注入，不混入用户输入。

Plan Mode 的规则也通过系统级动态消息注入。Plan Mode 首轮和间隔轮会注入完整只读规则，其余轮次只注入精简提醒；默认模式会说明可以在安全边界内使用完整工具集。工具描述会额外强化专用工具优先、编辑前先读取或搜索确认、工作区边界等规则。Agent 内部仍保留旧 Do Mode 兼容入口，但交互式 `/do` 只负责返回 DEFAULT。

如果模型 API 返回缓存命中字段，CLI 的 `[usage]` 行会展示 `cache_read`、`cache_create` 或 `cache=unavailable`。

## 测试

```bash
PYTHONPATH=src .venv/bin/python -m pytest
```

工具系统相关测试可以单独运行：

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_tools_files.py tests/test_tools_command.py tests/test_tools_search.py tests/test_session_tools.py
```

Agent Loop 相关测试可以单独运行：

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_collector.py tests/test_agent_executor.py tests/test_agent_runner.py tests/test_agent_tools.py
```

权限系统测试可以单独运行：

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_permissions_blacklist.py tests/test_permissions_sandbox.py tests/test_permissions_rules.py tests/test_permissions_config.py tests/test_permissions_service.py
```
