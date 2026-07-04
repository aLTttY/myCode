# myCode

myCode 是一个命令行 AI 编程助手。当前 MVP 只实现简单交互式多轮对话，不包含 tool use、文件操作、代码编辑或 shell 执行能力。

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

## 测试

```bash
PYTHONPATH=src .venv/bin/python -m pytest
```
