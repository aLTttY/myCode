# myCode

myCode 是一个命令行 AI 编程助手。当前版本支持简单交互式多轮对话，并提供基础工具系统，让模型可以在单轮对话中请求读取文件、写入文件、修改文件、执行命令和搜索代码。

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

进入交互界面后输入问题，myCode 会流式打印模型回复。输入 `exit`、`quit` 或 `退出` 结束会话。

## 工具系统

myCode 当前提供六个核心工具：

- `read_file`：读取工作区内文本文件。
- `write_file`：向工作区内文件写入完整内容。
- `edit_file`：用原文唯一匹配替换方式修改文件。
- `run_command`：在工作区内执行命令并返回退出码、stdout、stderr。
- `find_files`：按文件名或路径模式查找文件。
- `search_code`：按文本或正则搜索代码内容。

文件和命令工具默认限制在启动 myCode 时的当前工作区内。越界路径、命令失败、超时和参数错误会作为结构化工具结果返回给模型，而不是让 myCode 崩溃。

当前工具系统只实现“一次工具调用结果回灌”：一次用户输入最多触发一轮工具执行，然后模型基于工具结果生成最终回复。本阶段不实现多工具连续自动循环，也不是完整 Agent Loop。

## 测试

```bash
PYTHONPATH=src .venv/bin/python -m pytest
```

工具系统相关测试可以单独运行：

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_tools_files.py tests/test_tools_command.py tests/test_tools_search.py tests/test_session_tools.py
```
