# Agent 代码问题核查与后续建议

## 背景

本文件记录对其他 AI 提出的 Agent 代码问题清单的复核结果。复核范围包括当前仓库中的 CLI Agent、Provider 流式请求、事件收集、工具批处理与现有 spec/test 文档。

本次只做代码审阅和建议整理；未执行测试，原因是 `pytest` 可能写入 `.pytest_cache` 或临时产物。

## 总体结论

复核后认为：

- `CancellationToken` 在 Provider 流式读取期间存在协作式取消盲区，属于真实问题。
- CLI 没有处理 `token_usage` 事件，属于真实缺口。
- `ToolBatcher` 只合并相邻同安全等级工具，符合当前任务文档和测试定义，不应直接视为 bug。
- 读批次执行存在嵌套线程池，属于代码质量和资源使用问题，建议重构。

## 问题 1：Provider 流式请求期间取消不可观测

### 判断

基本成立，但“用户按 Ctrl+C 无法响应”这个描述不够精确。

CLI 的 `KeyboardInterrupt` 可能会直接中断主流程；真正的问题是：如果外部只是调用 `CancellationToken.cancel()`，Provider 正在同步读取 HTTP stream 时，Agent 没有机会检查 cancellation token。

### 证据

`AgentRunner.run()` 只在每轮模型调用前检查取消：

- `src/mycode/agent/runner.py`
- 关键位置：调用 `provider.stream_chat(...)` 之前

工具执行后也会再次检查取消：

- `src/mycode/agent/runner.py`
- 关键位置：工具批次执行结束后

但 Provider 内部使用同步 `httpx.Client(timeout=None)` 读取流：

- `src/mycode/providers/openai.py`
- `src/mycode/providers/anthropic.py`

SSE 读取过程也没有接收 cancellation token：

- `src/mycode/providers/sse.py`

### 风险

优先级：高。

影响包括：

- 外部取消请求无法及时停止正在进行的模型流式响应。
- `timeout=None` 可能导致网络连接异常时长时间挂住。
- 当前测试只覆盖“调用前已取消”，没有覆盖“流式过程中取消”。

### 建议

推荐先做最小修复：

1. 给 Provider HTTP client 设置合理的 connect/read/write/pool timeout。
2. 在 `AgentRunner._collect_provider_response()` 消费 provider events 时检查 cancellation token。
3. 如果检测到取消，产出 `done_event("cancelled", ...)` 并停止后续处理。

更彻底的方案：

1. 将 Provider stream 消费放到独立线程。
2. 主线程轮询 cancellation token。
3. 取消时关闭响应流或终止后台消费。

需要注意，Python 线程无法安全强杀，所以更好的方向是让 HTTP 读取本身具备 timeout，并让 stream 迭代能定期返回控制权。

## 问题 2：CLI 未展示 token_usage 事件

### 判断

成立。

Collector 和 Provider 已经具备 token usage 事件链路，但 CLI 没有处理该事件类型，导致用户界面看不到 token 用量。

### 证据

Provider 会产出 `StreamEvent(type="token_usage")`：

- `src/mycode/providers/openai.py`
- `src/mycode/providers/anthropic.py`

Collector 会转发为 `AgentEvent(type="token_usage")`：

- `src/mycode/agent/collector.py`

现有测试也覆盖了 collector 转发：

- `tests/test_agent_collector.py`

但 CLI 事件分支只处理：

- `text_delta`
- `progress`
- `tool_call_started`
- `tool_result`
- `done`
- `error`

缺少：

- `token_usage`

相关文件：

- `src/mycode/cli.py`

同时，`spec.md` 明确要求统一事件流包含 Token 用量。

### 风险

优先级：中。

影响包括：

- 用户看不到 token 消耗。
- 实现了 Provider 和 Collector 的 token usage，但 CLI 没有消费，形成半成品链路。
- 后续如果做成本统计或调试分析，CLI 侧缺少反馈。

### 建议

最小修复：

1. 在 CLI 事件循环中添加 `elif event.type == "token_usage"` 分支。
2. 当字段存在时打印 input/output/total token。
3. 缺失字段保持空值容忍，不要报错。

建议补充测试：

1. 在 `tests/test_cli.py` 增加 fake agent 产出 `token_usage`。
2. 断言 CLI 输出包含 token 用量。

## 问题 3：ToolBatcher 只合并相邻工具

### 判断

不应直接视为 bug。这是当前设计定义。

### 证据

`ToolBatcher.batch()` 按相邻 safety 分批：

- `src/mycode/agent/tools.py`

任务文档明确写了“按相邻安全等级分批”：

- `task.md`

测试也直接断言读、写、读会分成三批：

- `tests/test_agent_tools.py`

### 风险

优先级：低。

当前策略更保守，能避免副作用工具和读工具跨顺序重排。代价是读工具并发机会减少。

### 建议

保持现状，除非产品目标明确要求“最大化读工具并发”。

如果要优化，需要先重新定义顺序语义。例如：

1. 不跨越副作用工具重排。
2. 只在连续的纯读区间内并发。
3. 禁止把副作用工具之后的读操作提前到副作用工具之前。

当前实现已经满足第 2 点，所以不建议为了减少批次数而跨越 side effect 边界。

## 问题 4：读批次中存在嵌套线程池

### 判断

成立。属于代码质量和资源使用问题。

### 证据

`BatchToolExecutor._execute_read_batch()` 外层创建线程池并发执行读工具：

- `src/mycode/agent/executor.py`

每个并发任务调用 `ToolExecutor.execute()`，而 `ToolExecutor.execute()` 内部又创建一个 `ThreadPoolExecutor(max_workers=1)` 用于 timeout：

- `src/mycode/tools/executor.py`

这会形成：

```text
read batch thread pool
  -> ToolExecutor.execute()
       -> per-tool single-worker thread pool
```

### 风险

优先级：中。

影响包括：

- 线程数量膨胀。
- timeout 与 cancellation 语义变复杂。
- 大量读工具并发时资源使用不必要地升高。
- 出现长时间阻塞工具时，外层线程和内层线程的生命周期不易推理。

### 建议

推荐重构方向：

1. 将工具执行拆成两个层次：
   - 一个不额外开线程的同步执行方法，例如 `ToolExecutor.execute_sync(call)`。
   - 一个带 timeout 包装的方法，例如 `ToolExecutor.execute(call)`。
2. `BatchToolExecutor._execute_read_batch()` 在外层线程池中调用同步执行方法。
3. 外层 future 负责 timeout 和结果聚合。

需要注意：`future.result(timeout=...)` 超时后不能杀死正在运行的 Python 线程，只能停止等待。因此如果工具本身可能长时间阻塞，仍需工具内部具备 timeout 或可取消机制。

## 推荐修复顺序

1. 修复 CLI `token_usage` 展示。
   - 范围小，风险低，和 spec 明确对齐。
   - 推荐同时补 `tests/test_cli.py`。

2. 增强 Provider streaming 的 timeout 与取消语义。
   - 先加 HTTP timeout，避免无限挂住。
   - 再考虑将 cancellation token 传入 stream 消费链路。
   - 推荐补“流式过程中取消”的测试。

3. 重构工具执行线程池。
   - 保持现有行为不变。
   - 先拆出同步执行路径，再让 batch executor 统一控制并发。

4. 暂不调整 ToolBatcher 分批策略。
   - 当前行为符合文档和测试。
   - 若要优化，应先更新 spec，再改实现和测试。

## 建议新增测试

建议补充以下测试：

1. CLI 展示 token usage。
   - 位置：`tests/test_cli.py`
   - 断言：fake agent 产出 token usage 后，CLI 输出包含 token 统计。

2. 流式过程中取消。
   - 位置：`tests/test_agent_runner.py`
   - 构造一个 provider iterator，在 yield 若干事件后触发 cancellation。
   - 断言 Agent 停止并产生 `cancelled`。

3. Provider timeout 配置。
   - 位置：`tests/test_providers.py`
   - 重点验证 Provider 不再使用完全无限 timeout。

4. 读批次执行不创建嵌套线程池。
   - 可通过结构化重构后的单元测试覆盖，不建议强依赖 monkeypatch 线程池实现细节。

## 暂不建议处理的事项

以下点目前不建议作为 bug 修：

- `CollectedResponse` 通过 generator `return collected` 返回给 `yield from`：这是 Python 生成器的合法用法，当前调用方式正确。
- 绝对 import 与相对 import 混用：当前 agent 模块大体使用 `mycode...` 绝对导入，不构成问题。
- `PendingToolCall` 是可变 dataclass：这里用于流式累积 tool call 参数，属于合理用法。
- DeepSeekProvider 复用 OpenAIProvider：只要配置提供正确 `base_url`，当前做法成立。

## 结论

当前最值得优先处理的是两个用户可见或运行稳定性问题：

1. CLI 未展示 `token_usage`。
2. Provider streaming 阶段缺少可观测取消和合理 timeout。

线程池嵌套问题建议作为第二阶段重构处理。ToolBatcher 的相邻分批策略应保持现状，除非后续明确要改变工具执行顺序模型。
