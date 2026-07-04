# myCode MVP Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | `pyproject.toml` | 项目元数据、依赖、pytest 配置、`mycode` 命令入口 |
| 新建 | `README.md` | 运行方式、配置说明、Provider 支持范围、安全说明 |
| 新建 | `config.example.yaml` | 示例配置，使用环境变量形式 API Key |
| 已有 | `spec.md` | 已批准需求文档 |
| 已有 | `plan.md` | 已批准技术设计文档 |
| 新建 | `src/mycode/__init__.py` | 包初始化和版本号 |
| 新建 | `src/mycode/__main__.py` | 支持 `python -m mycode` |
| 新建 | `src/mycode/types.py` | 共享 dataclass、Protocol 相关类型和异常 |
| 新建 | `src/mycode/config.py` | YAML 配置加载、校验和环境变量解析 |
| 新建 | `src/mycode/session.py` | 当前进程内多轮会话管理 |
| 新建 | `src/mycode/cli.py` | CLI 参数解析和简单交互循环 |
| 新建 | `src/mycode/providers/__init__.py` | Provider 包初始化 |
| 新建 | `src/mycode/providers/base.py` | Provider 抽象接口 |
| 新建 | `src/mycode/providers/factory.py` | Provider 工厂 |
| 新建 | `src/mycode/providers/sse.py` | SSE data 行解析 |
| 新建 | `src/mycode/providers/openai.py` | OpenAI Chat Completions 流式 Provider |
| 新建 | `src/mycode/providers/deepseek.py` | DeepSeek OpenAI-compatible Provider |
| 新建 | `src/mycode/providers/anthropic.py` | Anthropic Messages 流式 Provider |
| 新建 | `tests/test_config.py` | 配置解析测试 |
| 新建 | `tests/test_session.py` | 会话历史和流式汇总测试 |
| 新建 | `tests/test_sse.py` | SSE 解析测试 |
| 新建 | `tests/test_providers.py` | Provider 事件转换测试 |
| 新建 | `tests/test_cli.py` | CLI 参数、退出和错误展示测试 |

## T1: 初始化 Python 项目骨架

**文件：** `pyproject.toml`, `src/mycode/__init__.py`, `src/mycode/__main__.py`, `src/mycode/providers/__init__.py`

**依赖：** 无

**步骤：**

1. 创建 `src/` layout。
2. 在 `pyproject.toml` 中声明项目名、Python 版本、依赖 `httpx`、`PyYAML`、开发依赖 `pytest`。
3. 配置 console script：`mycode = "mycode.cli:main"`。
4. 添加包初始化文件。
5. 添加 `__main__.py`，调用 `mycode.cli.main()`。

**验证：** 运行 `python -m compileall src`，期望无语法错误。

## T2: 定义共享类型和异常

**文件：** `src/mycode/types.py`

**依赖：** T1

**步骤：**

1. 定义 `ThinkingConfig`。
2. 定义 `AppConfig`。
3. 定义 `Message`。
4. 定义 `StreamEvent`。
5. 定义带 `user_message` 的 `ConfigError` 和 `ProviderError`。
6. 确保类型只表达第一阶段需要的 user/assistant 文本消息。

**验证：** 运行 `python -m compileall src/mycode/types.py`，期望无语法错误。

## T3: 实现配置加载与校验

**文件：** `src/mycode/config.py`, `tests/test_config.py`

**依赖：** T2

**步骤：**

1. 实现 `load_config(path)` 读取 YAML。
2. 校验 `protocol`、`model`、`base_url`、`api_key` 四个必填字段。
3. 限制 `protocol` 为 `openai`、`anthropic`、`deepseek`。
4. 实现 `${ENV_NAME}` 环境变量解析。
5. 环境变量不存在或为空时抛出 `ConfigError`。
6. 解析可选 `thinking.enabled` 和 `thinking.budget_tokens`。
7. 校验 `thinking.budget_tokens` 非空时必须为正整数。
8. 编写配置成功、缺字段、协议不支持、环境变量缺失、thinking 配置的测试。

**验证：** 运行 `pytest tests/test_config.py`，期望全部通过。

## T4: 实现 Provider 抽象和工厂

**文件：** `src/mycode/providers/base.py`, `src/mycode/providers/factory.py`, `tests/test_providers.py`

**依赖：** T2

**步骤：**

1. 在 `base.py` 定义 `LLMProvider` Protocol。
2. 在 `factory.py` 根据 `AppConfig.protocol` 返回具体 Provider。
3. 暂时引用后续 Provider 类名，确保工厂边界清晰。
4. 对未知协议抛出 `ConfigError`。
5. 编写工厂选择 OpenAI、Anthropic、DeepSeek 的测试。

**验证：** 运行 `pytest tests/test_providers.py -k factory`，期望全部通过。

## T5: 实现 SSE 解析工具

**文件：** `src/mycode/providers/sse.py`, `tests/test_sse.py`

**依赖：** T2

**步骤：**

1. 实现 `iter_sse_data_lines(response)`。
2. 从响应字节/文本行中提取 `data:` 内容。
3. 忽略空行、注释行和 keep-alive 行。
4. 保留 `[DONE]` 作为上层可识别的结束标记。
5. 对底层迭代异常包装为 `ProviderError`。
6. 编写普通 data 行、空行、`[DONE]`、异常包装测试。

**验证：** 运行 `pytest tests/test_sse.py`，期望全部通过。

## T6: 实现 OpenAI Provider

**文件：** `src/mycode/providers/openai.py`, `tests/test_providers.py`

**依赖：** T2, T5

**步骤：**

1. 实现 `OpenAIProvider.__init__(config)`。
2. 将通用 `Message` 转换为 OpenAI `messages`。
3. 使用 `httpx` 同步客户端发送 `{base_url}/chat/completions`。
4. 请求 header 使用 Bearer token。
5. 请求体包含 `model`、`messages`、`stream: true`。
6. 解析 `choices[0].delta.content` 为 `text_delta`。
7. 解析 `[DONE]` 为 `message_done`。
8. HTTP 状态错误、JSON 错误、流中断包装为 `ProviderError`。
9. 用 fake stream 测试文本增量、结束事件和错误路径。

**验证：** 运行 `pytest tests/test_providers.py -k openai`，期望全部通过。

## T7: 实现 DeepSeek Provider

**文件：** `src/mycode/providers/deepseek.py`, `tests/test_providers.py`

**依赖：** T6

**步骤：**

1. 定义 `DeepSeekProvider` 复用 `OpenAIProvider` 的请求和解析逻辑。
2. 保持独立类名，便于后续扩展 DeepSeek 专有参数。
3. 测试 `protocol: deepseek` 时工厂返回 `DeepSeekProvider`。
4. 测试 DeepSeek fake stream 能输出统一 `StreamEvent`。

**验证：** 运行 `pytest tests/test_providers.py -k deepseek`，期望全部通过。

## T8: 实现 Anthropic Provider

**文件：** `src/mycode/providers/anthropic.py`, `tests/test_providers.py`

**依赖：** T2, T5

**步骤：**

1. 实现 `AnthropicProvider.__init__(config)`。
2. 将通用 `Message` 转换为 Anthropic Messages API 格式。
3. 使用 `httpx` 同步客户端发送 `{base_url}/v1/messages`。
4. 请求 header 包含 `x-api-key`、`anthropic-version`、`content-type`。
5. 请求体包含 `model`、`messages`、`max_tokens`、`stream: true`。
6. 当 `thinking.enabled=True` 时加入 thinking 配置。
7. 当 `thinking.enabled=False` 时不发送 thinking 配置。
8. 解析 `content_block_delta` 中的 text delta 为 `text_delta`。
9. 解析 `message_stop` 为 `message_done`。
10. HTTP 状态错误、JSON 错误、流中断包装为 `ProviderError`。
11. 编写文本增量、结束事件、thinking 开关和错误路径测试。

**验证：** 运行 `pytest tests/test_providers.py -k anthropic`，期望全部通过。

## T9: 实现会话管理

**文件：** `src/mycode/session.py`, `tests/test_session.py`

**依赖：** T2, T4

**步骤：**

1. 实现 `ChatSession` 保存 `list[Message]`。
2. `send(user_text)` 先追加 user 消息。
3. 调用 Provider `stream_chat()` 并透传 `StreamEvent`。
4. 汇总所有 `text_delta` 为完整 assistant 回复。
5. 收到 `message_done` 后追加 assistant 消息。
6. Provider 抛错时不追加空 assistant 消息。
7. 编写单轮、多轮、错误路径测试。

**验证：** 运行 `pytest tests/test_session.py`，期望全部通过。

## T10: 实现 CLI 交互循环

**文件：** `src/mycode/cli.py`, `tests/test_cli.py`

**依赖：** T3, T4, T9

**步骤：**

1. 实现 `main(argv=None)`。
2. 支持 `--config`，默认值为 `config.yaml`。
3. 加载配置并创建 Provider、ChatSession。
4. 打印 myCode 启动提示和输入提示符。
5. 循环读取用户输入。
6. 支持退出命令，例如 `exit`、`quit`、`退出`。
7. 对 `text_delta` 立即打印并 flush。
8. 每轮结束后打印换行并回到提示符。
9. 捕获 `ConfigError`，返回非 0 退出码。
10. 捕获 `ProviderError`，显示错误并继续会话。
11. 处理 Ctrl+C，正常退出。
12. 编写参数解析、退出命令、配置错误、Provider 错误展示测试。

**验证：** 运行 `pytest tests/test_cli.py`，期望全部通过。

## T11: 更新 Provider 工厂集成

**文件：** `src/mycode/providers/factory.py`, `tests/test_providers.py`

**依赖：** T6, T7, T8

**步骤：**

1. 确保 `openai` 返回 `OpenAIProvider`。
2. 确保 `anthropic` 返回 `AnthropicProvider`。
3. 确保 `deepseek` 返回 `DeepSeekProvider`。
4. 确保未知协议抛出 `ConfigError`。
5. 补齐工厂测试。

**验证：** 运行 `pytest tests/test_providers.py -k factory`，期望全部通过。

## T12: 添加示例配置和 README

**文件：** `config.example.yaml`, `README.md`

**依赖：** T3, T10

**步骤：**

1. 编写 DeepSeek 示例配置，使用 `deepseek-v4-pro` 和 `${DEEPSEEK_API_KEY}`。
2. 编写 OpenAI 示例配置。
3. 编写 Anthropic 示例配置和 thinking 示例。
4. README 说明安装、运行、配置、退出命令和安全注意事项。
5. 明确示例不包含真实 API Key。
6. 全文使用 `myCode` 作为展示名。

**验证：** 运行 `rg -n "Mew[C]ode|mew[c]ode|sk-" README.md config.example.yaml`，期望无匹配。

## T13: 运行完整自动化测试和命名扫描

**文件：** 全项目

**依赖：** T1-T12

**步骤：**

1. 运行 `python -m compileall src`。
2. 运行 `pytest`。
3. 扫描错误项目名：`rg -n "Mew[C]ode|mew[c]ode"`。
4. 扫描疑似真实密钥：`rg -n "sk-[A-Za-z0-9]"`。
5. 修复发现的问题并重跑。

**验证：** compile、pytest、命名扫描、密钥扫描均通过。

## T14: tmux 端到端验证

**文件：** `checklist.md` 生成后按其执行

**依赖：** T13, checklist 审批通过

**步骤：**

1. 在环境变量中设置 `DEEPSEEK_API_KEY`。
2. 使用 DeepSeek 配置启动 tmux 会话运行 myCode。
3. 输入第一轮真实问题，例如“用一句话介绍你自己”。
4. 观察回复是否流式打印。
5. 输入第二轮问题，例如“刚才我问了什么？”。
6. 观察回复是否体现多轮上下文。
7. 输入退出命令。
8. 捕获 tmux 输出作为验收证据。

**验证：** 对照 `checklist.md` 逐项验收，全部通过。

## 执行顺序

```text
T1 → T2
      ├─→ T3
      ├─→ T4 → T11
      ├─→ T5 → T6 → T7
      │          └─→ T8
      └─→ T9 → T10

T12 → T13 → T14
```

实际执行时，T3、T4、T5 可在 T2 后并行；T14 必须等 `checklist.md` 审批通过后执行。
