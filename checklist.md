# myCode MVP Checklist

> 每一项都通过运行代码或观察行为验证，聚焦系统行为。

## 实现完整性

- [ ] myCode 可以通过 `python -m mycode --config config.yaml` 启动并显示交互式提示符。（验证：在终端运行命令，看到 `myCode>` 或等价提示符）
- [ ] myCode 支持默认读取当前目录的 `config.yaml`。（验证：存在 `config.yaml` 时运行 `python -m mycode`，能进入交互界面）
- [ ] myCode 支持通过 `--config` 指定配置文件路径。（验证：运行 `python -m mycode --config path/to/config.yaml`，能读取指定配置）
- [ ] YAML 配置支持 `protocol`、`model`、`base_url`、`api_key` 四个核心字段。（验证：运行配置解析单元测试）
- [ ] `api_key: ${ENV_NAME}` 能从环境变量读取真实密钥。（验证：设置测试环境变量后运行配置解析测试）
- [ ] 环境变量缺失或为空时，myCode 输出清晰错误并停止启动或请求。（验证：移除测试环境变量后运行配置错误测试）
- [ ] OpenAI Provider 能把 OpenAI SSE 响应转换为统一文本增量。（验证：运行 OpenAI Provider mock 流测试）
- [ ] Anthropic Provider 能把 Claude SSE 响应转换为统一文本增量。（验证：运行 Anthropic Provider mock 流测试）
- [ ] DeepSeek Provider 能按 OpenAI-compatible 格式处理流式响应。（验证：运行 DeepSeek Provider mock 流测试）
- [ ] Claude thinking 配置启用时请求体包含 thinking 配置，未启用时不包含。（验证：运行 Anthropic Provider thinking 测试）
- [ ] 会话层能在同一进程内保存多轮 user/assistant 历史。（验证：运行会话单元测试，检查第二轮 Provider 收到完整历史）
- [ ] CLI 能把 Provider 返回的 `text_delta` 立即打印并 flush。（验证：运行 CLI 测试或 tmux 观察流式输出）
- [ ] 用户输入退出命令后程序正常结束。（验证：输入 `exit`、`quit` 或 `退出`，进程退出码为 0）
- [ ] 配置错误、协议不支持、Provider 错误会显示可理解错误信息。（验证：运行错误路径测试，观察 stderr/stdout）

## 集成

- [ ] CLI、配置层、Provider 工厂、会话层能串联完成一次对话请求。（验证：使用 fake Provider 运行 CLI 集成测试）
- [ ] `protocol: openai` 时工厂创建 OpenAI Provider。（验证：运行 Provider 工厂测试）
- [ ] `protocol: anthropic` 时工厂创建 Anthropic Provider。（验证：运行 Provider 工厂测试）
- [ ] `protocol: deepseek` 时工厂创建 DeepSeek Provider。（验证：运行 Provider 工厂测试）
- [ ] 上层会话流程只依赖统一 Provider 接口，不分支处理具体供应商。（验证：代码 review + Provider 工厂测试）
- [ ] `config.example.yaml` 覆盖 DeepSeek、OpenAI、Anthropic 三种配置示例且不包含真实密钥。（验证：阅读文件并运行密钥扫描）

## 编译与测试

- [ ] Python 源码语法检查通过。（验证：运行 `python -m compileall src`）
- [ ] 配置解析测试通过。（验证：运行 `pytest tests/test_config.py`）
- [ ] SSE 解析测试通过。（验证：运行 `pytest tests/test_sse.py`）
- [ ] Provider 测试通过。（验证：运行 `pytest tests/test_providers.py`）
- [ ] 会话测试通过。（验证：运行 `pytest tests/test_session.py`）
- [ ] CLI 测试通过。（验证：运行 `pytest tests/test_cli.py`）
- [ ] 全量自动化测试通过。（验证：运行 `pytest`）
- [ ] 项目中没有错误项目名。（验证：运行 `rg -n "Mew[C]ode|mew[c]ode"`，期望无匹配；Python 包名 `mycode` 除外时需人工确认）
- [ ] 项目中没有提交真实 API Key。（验证：运行 `rg -n "sk-[A-Za-z0-9]"`，期望无匹配）

## 端到端场景

- [ ] 场景 1：DeepSeek 单轮流式对话可用。（验证：设置 `DEEPSEEK_API_KEY`，用 `protocol: deepseek`、`model: deepseek-v4-pro`、`base_url: https://api.deepseek.com` 启动 tmux，会话中输入“用一句话介绍你自己”，观察回复逐步打印）
- [ ] 场景 2：DeepSeek 多轮上下文可用。（验证：在同一 tmux 会话中先问“请记住我叫 Alex”，再问“我叫什么？”，观察回复能基于上一轮上下文）
- [ ] 场景 3：退出命令可用。（验证：在 tmux 会话中输入 `退出`，观察程序结束）
- [ ] 场景 4：缺失环境变量错误可读。（验证：不设置 `DEEPSEEK_API_KEY` 启动，观察错误提示明确指出环境变量缺失或为空）

## 验收记录要求

- [ ] 每个 checklist 条目执行后记录实际结果，不用“应该可以”代替证据。
- [ ] tmux 验收需要捕获 pane 输出作为证据。
- [ ] 如果任一条目失败，先修复并重新执行相关验证，再提交最终报告。
