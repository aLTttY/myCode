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

单个 Server 连接、初始化或工具发现失败只输出警告，不影响其他 Server 或六个内置工具。非法名称、最终名称超过 64 字符、重复工具也只跳过冲突项；已经注册的工具不会被覆盖。会话和连接在进程内缓存，并在 CLI 退出时关闭。

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

默认启动会恢复当前项目 30 天内最近活动的有效会话。使用 `--new` 可在启动时跳过恢复，交互中输入 `/new` 可持久化当前会话后切换到新会话。会话以 `.mycode/sessions/<YYYYMMDD-HHMMSS-xxxx>.jsonl` 逐行追加保存，不维护单独 meta 文件；启动时会清理超过 30 天的存档。恢复间隔超过 24 小时时，下一次模型请求会收到一次状态可能变化的提醒。

支持两个模式前缀：

- `/plan <任务>`：Plan Mode，只开放 `read_file`、`find_files`、`search_code` 这类只读工具，让模型先观察项目并输出计划。
- `/do <任务>`：Do Mode，开放完整工具集，用于根据任务或已有计划执行实际改动。
- `/compact`：立即执行上下文轻量卸载与重量摘要，不会作为用户消息发送给模型，并显示压缩前后估算量。
- `/new`：完成当前会话收尾并创建空白会话，不会作为用户消息发送给模型。

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

Mycode 当前提供六个核心工具：

- `read_file`：读取工作区内文本文件。
- `write_file`：向工作区内文件写入完整内容。
- `edit_file`：用原文唯一匹配替换方式修改文件。
- `run_command`：在工作区内执行命令并返回退出码、stdout、stderr。
- `find_files`：按文件名或路径模式查找文件。
- `search_code`：按文本或正则搜索代码内容。

文件工具限制在启动 Mycode 时的当前工作区内。越界路径、命令失败、超时、权限拒绝和参数错误会作为结构化工具结果返回给模型，而不是让 Mycode 崩溃。

## 权限系统

`read_file`、`find_files`、`search_code` 是专用只读工具：目标和工作区边界校验通过后直接执行，不进入权限规则、权限模式或人工审批。历史配置中的只读 allow/deny 规则仍可解析，但不影响这三个工具执行。

`write_file`、`edit_file`、`run_command` 仍依次经过不可覆盖的危险命令黑名单、路径沙箱、分层规则、权限模式，以及必要时的用户确认。`run_command` 始终按有副作用工具处理，即使执行的是 `ls`、`cat` 或 Git 查看命令。权限拒绝会回灌 Agent Loop，模型可以改用更安全的工具、命令或路径继续任务。

权限规则使用三个可选 YAML 文件：

```text
用户级：~/.mycode/permissions.yaml
项目级：<workspace>/.mycode/permissions.yaml
本地级：<workspace>/.mycode/permissions.local.yaml
```

本地文件默认被 Git 忽略。规则优先级为“会话 > 本地 > 项目 > 用户”；同层精确匹配优先于 glob，同类型冲突时 deny 优先。

示例：

```yaml
mode: default

allow:
  - "run_command(git *)"

deny:
  - "write_file(.env)"
  - "run_command(git push *)"
```

规则使用真实工具名。`run_command` 匹配完整命令，写入和编辑工具匹配规范化的工作区相对路径。包含 `*`、`?` 或 `[...]` 的模式按大小写敏感 glob 匹配，其余模式精确匹配。三个专用只读工具不使用规则判定。

三档权限模式与 Plan/Do Agent 模式相互独立：

- `strict`：规则未命中时拒绝。
- `default`：规则未命中时请求用户确认。
- `allow`：规则未命中时放行。

命令行 `--permission-mode` 优先于本地、项目和用户配置；所有位置都未声明时使用 `default`。default 模式使用方向键菜单确认：上、下方向键移动高亮，回车确认。菜单只提供“不同意、仅本次同意、本会话同意”，默认高亮“不同意”，不接受字母命令，也不提供永久同意。

交互审批不会写入任何权限文件。需要长期规则时，用户可以手工编辑 `.mycode/permissions.local.yaml`；该文件仍在下次启动时加载，并保持“本地 > 项目 > 用户”的优先级。

危险命令黑名单和路径沙箱不能被配置、权限模式或人工确认覆盖。文件工具会解析符号链接并拒绝项目外路径；命令工具会检查可识别的显式路径。命令通过环境变量、用户配置、运行库或程序内部逻辑产生的隐式文件访问不受本阶段强隔离，完整限制需要后续引入操作系统沙箱或容器。

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

Plan Mode 和 Do Mode 的规则也通过系统级动态消息注入。Plan Mode 首轮和间隔轮会注入完整只读规则，其余轮次只注入精简提醒；默认和 Do Mode 会说明可以在安全边界内使用完整工具集。工具描述会额外强化专用工具优先、编辑前先读取或搜索确认、工作区边界等规则。

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
