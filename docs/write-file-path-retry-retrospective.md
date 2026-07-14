# write_file 路径重试问题记录

## 现象

用户请求：

```text
在这个目录下新建一个test.md
```

运行日志中出现：

```text
[tool] write_file 开始
[tool] write_file 失败：路径必须是工作区内的相对路径。
...
[tool] write_file 开始
[tool] write_file 成功：文件写入成功。
```

表面看起来像同一次 `write_file` 的结果从 `false` 变成了 `true`。

## 根因

这不是同一次工具调用状态变化，而是 agent 的两轮工具调用：

1. 第一轮模型传入了绝对路径，例如 `/Users/.../test.md`。
2. `resolve_workspace_path()` 按安全策略拒绝绝对路径，返回失败：`路径必须是工作区内的相对路径。`
3. agent 将工具失败结果作为 `tool` 消息写回历史。
4. 第二轮模型根据失败信息修正参数，改用相对路径 `test.md`。
5. `write_file` 使用相对路径写入成功。

也就是说，安全策略本身是正确的；问题在于日志只显示工具名和结果，没有显示两次调用的参数差异，容易让用户误判为同一次调用状态翻转。

## 改动

本次改动保持原有文件安全策略不变，只增强诊断和提示：

- `AgentEvent` 新增 `tool_arguments` 字段，用于在工具开始事件中携带调用参数。
- `BatchToolExecutor` 在 `tool_call_started` 事件中传递当前工具调用参数。
- CLI 在工具开始时展示安全的短参数，例如：

```text
[tool] write_file 开始：path=test.md
```

- CLI 参数展示会跳过 `content`、`old_text`、`new_text`、`command`，避免泄露大段文件内容或命令正文。
- 文件工具 schema 的 `path` 描述补充说明：必须使用工作区相对路径，绝对路径无效。
- 新增测试覆盖：
  - CLI 工具开始日志会展示 `path`。
  - CLI 参数展示会隐藏敏感/大字段。
  - 文件工具会拒绝绝对路径。

## 影响范围

涉及文件：

- `src/mycode/agent/events.py`
- `src/mycode/agent/executor.py`
- `src/mycode/cli.py`
- `src/mycode/tools/files.py`
- `tests/test_cli.py`
- `tests/test_tools_files.py`

未改变：

- `write_file` 仍然拒绝绝对路径。
- `../` 和软链逃逸工作区的保护逻辑不变。
- 工具失败后由 agent 继续迭代修正的行为不变。

## 验证

执行：

```bash
.venv/bin/python -m pytest tests/test_cli.py tests/test_tools_files.py tests/test_agent_executor.py
```

结果：

```text
25 passed
```
