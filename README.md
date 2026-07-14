# myCode

myCode 是一个命令行 AI 编程助手。当前版本支持交互式多轮对话、基础工具系统和 Agent Loop，让模型可以围绕一次用户任务反复调用工具、观察结果并继续推进，直到任务完成或触发停止条件。

## 安装依赖

```bash
python3 -m venv .venv
.venv/bin/python -m pip install httpx prompt_toolkit PyYAML pytest
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
```

OpenAI 示例：

```yaml
protocol: openai
model: gpt-4.1
base_url: https://api.openai.com/v1
api_key: ${OPENAI_API_KEY}
```

Anthropic 示例：

```yaml
protocol: anthropic
model: claude-sonnet-4-5
base_url: https://api.anthropic.com
api_key: ${ANTHROPIC_API_KEY}
thinking:
  enabled: true
  budget_tokens: 4096
```

不要把真实 API Key 写入配置文件。请使用环境变量：

```bash
export DEEPSEEK_API_KEY="your-key"
```

## 运行

```bash
PYTHONPATH=src .venv/bin/python -m mycode
```

指定配置：

```bash
PYTHONPATH=src .venv/bin/python -m mycode --config config.yaml
```

进入交互界面后输入问题，myCode 会流式打印模型回复，并在需要时自动执行工具调用。输入 `exit`、`quit` 或 `退出` 结束会话。

支持两个模式前缀：

- `/plan <任务>`：Plan Mode，只开放 `read_file`、`find_files`、`search_code` 这类只读工具，让模型先观察项目并输出计划。
- `/do <任务>`：Do Mode，开放完整工具集，用于根据任务或已有计划执行实际改动。

## 工具系统

myCode 当前提供六个核心工具：

- `read_file`：读取工作区内文本文件。
- `write_file`：向工作区内文件写入完整内容。
- `edit_file`：用原文唯一匹配替换方式修改文件。
- `run_command`：在工作区内执行命令并返回退出码、stdout、stderr。
- `find_files`：按文件名或路径模式查找文件。
- `search_code`：按文本或正则搜索代码内容。

文件和命令工具默认限制在启动 myCode 时的当前工作区内。越界路径、命令失败、超时和参数错误会作为结构化工具结果返回给模型，而不是让 myCode 崩溃。

## Agent Loop

Agent Loop 使用 ReAct 风格循环工作：每一轮请求模型、流式收集文本和工具调用、执行工具、把工具结果回写进对话历史，再进入下一轮判断。循环会在以下情况停止：

- 模型不再请求工具并给出最终回复。
- 达到最大迭代次数。
- 用户取消当前任务。
- 连续请求未知工具超过阈值。
- 模型流式响应出错，或工具调用参数无法解析。

一次模型响应里出现多个工具调用时，myCode 会按安全性分批：只读工具可以并发执行，写文件、改文件、执行命令等有副作用工具串行执行。本阶段仍不包含权限系统、上下文压缩和用户交互式确认。

## 系统提示

myCode 会为每轮模型请求构造结构化系统提示。稳定的全局规则按身份、系统约束、任务模式、动作执行、工具使用、语气风格和文本输出组织；工作目录、日期、运行模式等环境信息作为系统级动态消息注入，不混入用户输入。

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
