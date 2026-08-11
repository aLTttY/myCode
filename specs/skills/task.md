# MyCode Skill 系统 Tasks

## 文件清单

### 新建文件

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mycode/skills/__init__.py` | Skill 公共导出 |
| 新建 | `src/mycode/skills/models.py` | Skill、工具、快照、诊断、调用与执行结果模型 |
| 新建 | `src/mycode/skills/parser.py` | Markdown frontmatter 与目录工具严格解析 |
| 新建 | `src/mycode/skills/catalog.py` | 三级发现、覆盖、校验、指纹与刷新 |
| 新建 | `src/mycode/skills/runtime.py` | 激活状态、提示内容、工具投影与快照发布 |
| 新建 | `src/mycode/skills/tools.py` | `load_skill` 与 Python 脚本工具适配器 |
| 新建 | `src/mycode/skills/isolated.py` | 一次性独立 Agent 执行与摘要回流 |
| 新建 | `src/mycode/skills/commands.py` | 动态 Skill 命令生成 |
| 新建 | `src/mycode/skills/builtins/__init__.py` | 内置 Skill 资源包 |
| 新建 | `src/mycode/skills/builtins/commit.md` | 内置共享 commit Skill |
| 新建 | `src/mycode/skills/builtins/review.md` | 内置独立 review Skill |
| 新建 | `src/mycode/skills/builtins/test.md` | 内置共享 test Skill |
| 新建 | `tests/test_skill_parser.py` | 格式、字段、路径与命名空间测试 |
| 新建 | `tests/test_skill_catalog.py` | 三级目录、覆盖、冲突、校验与刷新测试 |
| 新建 | `tests/test_skill_runtime.py` | 激活、提示、白名单、发布与重置测试 |
| 新建 | `tests/test_skill_tools.py` | loader、脚本协议、权限、超时与输出测试 |
| 新建 | `tests/test_skill_isolated.py` | 历史、模型、临时 Agent、摘要与嵌套测试 |
| 新建 | `tests/test_skill_commands.py` | 动态命令、帮助、补全和兼容别名测试 |
| 新建 | `tests/test_skill_integration.py` | 共享、独立、热更新和会话端到端测试 |

### 修改文件

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `src/mycode/cli.py` | 启动装配、刷新、命令执行和状态清理 |
| 修改 | `src/mycode/agent/runner.py` | Skill 提示/工具投影、loader、直接调用和摘要回写 |
| 修改 | `src/mycode/agent/tools.py` | Plan Mode 下保留系统 loader |
| 修改 | `src/mycode/prompts/modules.py` | Skill 目录与激活 SOP 提示区块 |
| 修改 | `src/mycode/context/manager.py` | 最近完整已完成轮次提取 |
| 修改 | `src/mycode/tools/registry.py` | 枚举、判断、子集复制和无覆盖合并 |
| 修改 | `src/mycode/tool_safety.py` | 系统工具及专属工具安全分类 |
| 修改 | `src/mycode/permissions/targets.py` | 动态专属工具 `call` 目标 |
| 修改 | `src/mycode/permissions/service.py` | loader 自动允许及动态工具集合更新 |
| 修改 | `src/mycode/commands/models.py` | 动态来源和安全帮助元信息 |
| 修改 | `src/mycode/commands/interfaces.py` | Skill 调用 UI 接口 |
| 修改 | `src/mycode/commands/registry.py` | 固定/动态命令原子替换 |
| 修改 | `src/mycode/commands/builtins.py` | 移除固定 review 并扩展帮助 |
| 修改 | `src/mycode/commands/__init__.py` | 导出新增命令接口 |
| 修改 | `pyproject.toml` | 打包内置 Markdown 资源 |
| 修改 | `README.md` | Skill 使用与能力包协议文档 |
| 修改 | `tests/test_agent_runner.py` | Agent Skill 请求、loader 和会话测试 |
| 修改 | `tests/test_agent_tools.py` | Plan 工具投影测试 |
| 修改 | `tests/test_prompts.py` | 两阶段提示与角色边界测试 |
| 修改 | `tests/test_context_manager.py` | 完整轮次提取和不变性测试 |
| 修改 | `tests/test_tools_registry.py` | Registry 组合与兼容测试 |
| 修改 | `tests/test_permissions_service.py` | 系统 loader 与动态专属工具权限测试 |
| 修改 | `tests/test_command_registry.py` | 动态替换原子性测试 |
| 修改 | `tests/test_command_builtins.py` | 动态帮助和固定 review 移除测试 |
| 修改 | `tests/test_command_completion.py` | 热更新后的 Skill 补全测试 |
| 修改 | `tests/test_cli.py` | 启动顺序、Skill 分流、刷新和会话测试 |
| 修改 | `tests/test_context_integration.py` | Skill 与上下文压缩集成测试 |
| 修改 | `tests/test_session_memory_integration.py` | 独立摘要与主会话记忆边界测试 |

## T1：建立领域模型与严格解析器

**文件：** `src/mycode/skills/__init__.py`、`src/mycode/skills/models.py`、`src/mycode/skills/parser.py`、`tests/test_skill_parser.py`

**依赖：** 无

**步骤：**

1. 定义 `SkillDefinition`、`SkillToolDefinition`、`SkillSnapshot`、`ActiveSkill`、诊断、刷新、调用、结果和独立执行 Protocol。
2. 为只读快照准备不可变映射构造方式，避免调用方直接修改 Catalog 状态。
3. 使用 `yaml.safe_load` 拆分并解析 YAML frontmatter 和非空 Markdown 正文。
4. 严格校验 `name`、`description`、`allowed_tools`、`mode`、`history`、`model`，拒绝未知字段、错误类型、多行说明和非法模式组合。
5. 复用现有斜杠命令命名规则；编译 SOP 时只把 `{{input}}` 替换为固定 user 输入引用，不插入真实参数。
6. 解析目录 `tools/*.yaml` 的 `name`、`description`、`parameters`、`script`，要求顶层 schema 为 object。
7. 生成 `<skill>__<local-tool>` 名称并校验 64 字符上限、重复局部名和冲突。
8. 拒绝绝对脚本路径、非 `.py` 文件、符号链接、缺失脚本和能力包目录逃逸。
9. 确保所有解析错误只包含安全来源、字段和错误类型，不包含 SOP、参数或脚本正文。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_parser.py -q
```

期望：单文件、目录包、严格字段、占位符、命名空间和路径安全用例全部通过。

## T2：实现三级 Catalog、内置资源与热更新候选快照

**文件：** `src/mycode/skills/catalog.py`、`src/mycode/skills/builtins/__init__.py`、`src/mycode/skills/builtins/commit.md`、`src/mycode/skills/builtins/review.md`、`src/mycode/skills/builtins/test.md`、`pyproject.toml`、`tests/test_skill_catalog.py`

**依赖：** T1

**步骤：**

1. 扫描项目 `.mycode/skills/`、用户 `~/.mycode/skills/` 和 `importlib.resources` 内置包；支持根目录 Markdown 和直接子目录 `SKILL.md`。
2. 对候选路径进行稳定排序，并记录项目、用户、内置来源及安全 `source_id`。
3. 跳过单个解析失败定义，保留诊断；让无效高优先级文件不遮蔽低优先级有效定义。
4. 对有效定义执行“项目 > 用户 > 内置”合并；启动时把同层重名、固定命令冲突和生效白名单未知工具转成启动错误。
5. 白名单只允许当前全局工具或该 Skill 自己的专属工具，不能引用其他 Skill 的专属工具。
6. 为入口、tool manifest 和脚本计算稳定内容摘要；用路径、大小和纳秒 mtime 建立快速状态指纹。
7. 实现运行期刷新：隔离问题名称，继续发布其他合法变化，并返回新增、修改、降级、移除和诊断信息。
8. 编写三个严格合法的内置 Skill；`review` 为 isolated/history 0，commit/test 为 shared 且不声明 history/model。
9. 配置 setuptools package data，确保从安装包读取三个 Markdown。
10. 测试源码资源、模拟安装资源、三级覆盖、非法回退、冲突、保留命令、MCP 缺失和刷新指纹。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_parser.py tests/test_skill_catalog.py -q
```

期望：初始加载与运行期刷新边界均符合 spec，三个内置 Skill 可由资源 API 发现。

## T3：扩展工具目录与权限基础设施

**文件：** `src/mycode/tools/registry.py`、`src/mycode/tool_safety.py`、`src/mycode/permissions/targets.py`、`src/mycode/permissions/service.py`、`tests/test_tools_registry.py`、`tests/test_permissions_service.py`

**依赖：** T1

**步骤：**

1. 为 `ToolRegistry` 增加稳定名称枚举、存在判断、按名称创建子集和无覆盖合并。
2. 保持现有注册顺序与重复工具错误语义，不允许组合时静默覆盖。
3. 把 `load_skill` 标记为串行系统工具；所有不在固定只读集合中的专属工具继续按 side-effect 分类。
4. 在权限服务中为 `load_skill` 增加不可配置的系统允许分支，但不让该分支执行任何业务动作。
5. 允许权限目标解析器持有并原子更新当前专属工具精确名称集合，统一映射到 `call`。
6. 保留现有 MCP 前缀和七个内置工具的全部权限行为。
7. 测试 Registry 子集/合并、未知工具、loader 自动允许、专属工具 default/strict/allow 及会话审批。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_tools_registry.py tests/test_permissions_service.py tests/test_agent_tools.py tests/test_tool_executor.py -q
```

期望：新基础能力通过，现有工具与权限回归保持不变。

## T4：实现 Runtime、两阶段提示和工具投影

**文件：** `src/mycode/skills/runtime.py`、`src/mycode/prompts/modules.py`、`src/mycode/agent/tools.py`、`tests/test_skill_runtime.py`、`tests/test_prompts.py`、`tests/test_agent_tools.py`

**依赖：** T1、T2、T3

**步骤：**

1. 实现主 Runtime 的 Snapshot、共享激活顺序、去重和加锁读取。
2. 实现独立 Runtime 工厂，把当前独立 Skill 固定为执行根能力，并允许临时加载共享 Skill。
3. 生成未激活 Skill 的名称/说明目录，确保不包含正文、schema、脚本或被覆盖定义。
4. 按执行根能力和共享激活顺序生成完整 SOP 区块，并放在可选系统提示首位。
5. 生成工具投影：无激活使用全局工具；有激活使用白名单并集；始终添加 loader；Plan Mode 再收窄业务工具。
6. 根据新旧 Snapshot 实现同源热替换、更高优先级替换、低优先级回退停用、模式变化停用和修复不自动激活。
7. 实现 Runtime reset，清除全部共享激活状态但不删除 Catalog。
8. 测试激活顺序、重复激活、目录隐藏、SOP 持续注入、并集、Plan Mode、热更新和 reset。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_runtime.py tests/test_prompts.py tests/test_agent_tools.py -q
```

期望：两阶段提示、工具收窄和热更新状态转换全部通过。

## T5：提供最近完整已完成轮次提取

**文件：** `src/mycode/context/manager.py`、`tests/test_context_manager.py`

**依赖：** 无

**步骤：**

1. 以 user 消息为起点，将后续 assistant 及其完整工具结果组成一个对话轮次。
2. 仅返回已经结束的轮次，排除等待工具结果或最终 assistant 的当前半完成轮次。
3. 从尾部选择最近 N 轮；`N=0` 返回空；不足 N 时返回全部可用完整轮次。
4. 不复制动态系统提示、摘要或边界消息；不改变 ContextManager 状态、Token anchor 或压缩状态。
5. 测试纯文本、多工具、批量工具、孤立非法输入保护、压缩后消息和调用不变性。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_context_manager.py -q
```

期望：历史选择不拆工具链且是只读操作。

## T6：实现 Python 专属工具子进程适配器

**文件：** `src/mycode/skills/tools.py`、`tests/test_skill_tools.py`

**依赖：** T1、T3

**步骤：**

1. 将 `SkillToolDefinition` 适配为现有 Tool Protocol 和 `ToolSpec`。
2. 使用 `sys.executable` 与 argv 直接启动脚本，禁止 `shell=True`，cwd 固定为 workspace。
3. 构造最小子进程环境，不继承 API Key 等业务凭据；stdin 只传 `arguments` 和只读 workspace 上下文 JSON。
4. 有界读取 stdout/stderr；达到超时或大小上限时终止进程并回收。
5. 要求 stdout 只有一个 JSON 对象，严格校验 `ok`、`message`、`data`，并生成 display/complete 结果。
6. 对退出码、无输出、非法 UTF-8、非法 JSON、额外输出、错误字段、超时和超量输出返回结构化安全错误。
7. 通过真实临时 Python 脚本验证参数、cwd、最小环境、审批拒绝和成功结果。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_tools.py tests/test_tool_executor.py tests/test_permissions_service.py -q
```

期望：脚本协议、进程生命周期、输出上限和权限路径全部通过。

## T7：把 Skill Runtime 与 Loader 接入 AgentRunner

**文件：** `src/mycode/agent/runner.py`、`src/mycode/skills/tools.py`、`tests/test_agent_runner.py`、`tests/test_skill_tools.py`

**依赖：** T4、T5、T6

**步骤：**

1. 让 `AgentRunner` 接收可选 `SkillRuntime` 和 `IsolatedSkillExecutor` Protocol，保持无 Skill 调用方兼容。
2. 在 Runner 初始化时注册绑定当前请求、历史和隔离深度回调的 `LoadSkillTool`。
3. 每次 Agent 迭代从 Runtime 重新生成目录提示、完整 SOP 和工具投影，保证 loader 激活后下一迭代立即生效。
4. loader 对共享 Skill 只执行激活；对独立 Skill 调用执行器；对未知、失效和嵌套独立返回结构化错误。
5. 实现共享斜杠调用入口：先激活，再将安全 Skill 调用文本作为 user 消息交给现有 run。
6. 实现外部轮次回写，确保独立斜杠调用只把调用与摘要追加到主 ContextManager 和 SessionJournal。
7. 在 `new_session` 中 reset Runtime；`close` 和 `/clear` 不清激活。
8. 用 fake 独立执行器测试 loader、下一迭代 SOP/工具变化、重复激活、Plan Mode、外部回写和新会话清理。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_agent_runner.py tests/test_skill_tools.py tests/test_skill_runtime.py tests/test_session.py -q
```

期望：Agent Loop 能按需加载并持续应用共享 Skill，既有无 Skill 路径不回归。

## T8：实现独立执行器与模型覆盖

**文件：** `src/mycode/skills/isolated.py`、`tests/test_skill_isolated.py`、`tests/test_agent_runner.py`

**依赖：** T2、T4、T5、T7

**步骤：**

1. 实现 `IsolatedSkillExecutor` Protocol 的具体执行器，通过依赖反转避免 `AgentRunner` 循环导入。
2. 固定调用开始时的 Snapshot，创建包含执行根 Skill 的临时 Runtime。
3. 从主 ContextManager 取得最近 N 个完整轮次，并把本次输入作为新的 user 消息。
4. 未指定模型时复用主模型配置；指定模型时仅替换 `AppConfig.model` 并创建临时 Provider。
5. 创建无 SessionJournal、无 MemoryWorker 的临时 AgentRunner，复用工作区、权限、上下文配置、取消和迭代上限。
6. 缓冲独立中间文本和工具事件，只向调用方产出简洁进度与最终结果。
7. 用最终 assistant 文本作为摘要；对 Provider 错误、取消、超限、上下文失败和缺少最终文本生成确定性失败摘要。
8. 始终关闭临时 ContextManager；验证独立中间历史、激活状态和上下文文件不进入主会话。
9. 允许临时加载共享 Skill，拒绝嵌套独立 Skill。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_isolated.py tests/test_agent_runner.py tests/test_providers.py -q
```

期望：history 0/N、模型覆盖、摘要、失败和嵌套边界全部通过，三类 Provider 请求保持合法。

## T9：实现动态 Skill 命令、帮助与补全

**文件：** `src/mycode/skills/commands.py`、`src/mycode/commands/models.py`、`src/mycode/commands/interfaces.py`、`src/mycode/commands/registry.py`、`src/mycode/commands/builtins.py`、`src/mycode/commands/__init__.py`、`tests/test_skill_commands.py`、`tests/test_command_registry.py`、`tests/test_command_builtins.py`、`tests/test_command_completion.py`

**依赖：** T2、T4

**步骤：**

1. 扩展 `CommandSpec`，记录固定/Skill 来源及可安全显示的 source、mode、history、model 元信息。
2. 给 `CommandUI` 增加 `invoke_skill(name, input)`，保持现有 Fake UI 易于测试。
3. 为每个生效 Skill 生成 `/<name> [input]` 命令；仅 `review` 自动附加 `/rev`。
4. 从固定内置命令中移除 review 常量、注册和 handler，其他固定命令保持不变。
5. 实现 `replace_dynamic`：锁内构建完整索引并验证全部名称/别名后一次替换，失败不污染旧状态。
6. 更新 `/help` 总览和单项输出，展示安全 Skill 元信息但不显示 SOP、白名单、schema 或脚本路径。
7. 让现有补全器通过稳定 Registry 对象自动读取最新动态快照。
8. 测试覆盖、保留字、动态替换失败原子性、帮助、补全、shared/isolated handler 和 `/review`/`/rev`。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_commands.py tests/test_command_registry.py tests/test_command_builtins.py tests/test_command_completion.py -q
```

期望：固定和动态命令共享同一确定目录，review 兼容入口正确。

## T10：完成 CLI 启动装配、热更新和会话边界

**文件：** `src/mycode/cli.py`、`tests/test_cli.py`

**依赖：** T2、T3、T4、T7、T8、T9

**步骤：**

1. 调整启动顺序为配置/Provider、内置工具、MCP 发现、固定命令、Skill 初始 Catalog、权限、Runtime、Agent、动态命令、会话与记忆。
2. 对初始 Skill 冲突和白名单错误输出安全配置错误并在进入交互前返回非零状态。
3. 在每次显示输入提示前刷新 Catalog；无变化不重建，变化时依次发布 Runtime、动态命令和权限专属工具集合。
4. 输出解析、冲突、未知工具和停用通知，不泄露 SOP、脚本正文、参数或凭据。
5. 实现 CLI `invoke_skill`：共享调用流式进入主 Agent；独立调用显示简洁进度并只展示最终摘要。
6. 保持 `/clear` 只清屏；`/new` 通过 Agent reset 清空激活状态；恢复历史会话时 Runtime 仍为空。
7. 保持 Ctrl+C、Ctrl+D、取消、ProviderError、MCP 关闭、MemoryWorker drain 和上下文清理路径。
8. 测试启动失败时序、普通消息自动 loader、两类 Skill 命令、热更新、降级停用、修复不激活和退出清理。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli.py tests/test_skill_commands.py tests/test_mcp_integration.py tests/test_session_memory_integration.py -q
```

期望：CLI 完整装配可测，现有交互、MCP、会话和记忆行为无回归。

## T11：补齐内置样板与端到端集成验证

**文件：** `src/mycode/skills/builtins/commit.md`、`src/mycode/skills/builtins/review.md`、`src/mycode/skills/builtins/test.md`、`tests/test_skill_integration.py`、`tests/test_context_integration.py`、`tests/test_session_memory_integration.py`

**依赖：** T8、T10

**步骤：**

1. 核对 commit SOP 先读 Git 改动、形成说明、运行相关验证，并只在权限允许时执行提交。
2. 核对 review SOP 只用只读工具、聚焦缺陷/回归/安全/测试缺口，并把最终文本写成可回流摘要。
3. 核对 test SOP 识别相关测试、报告真实结果，且白名单不包含文件修改工具。
4. 构造共享端到端：斜杠 commit 激活、主历史保留、再激活共享 Skill、白名单并集、`/new` 清空。
5. 构造独立端到端：已有历史和共享激活时调用 review，验证 history 0、只读工具、中间历史隔离和主状态保持。
6. 构造目录工具端到端：加载前 schema 不可见，加载后审批执行，停用后消失。
7. 构造热更新端到端：修改 SOP/白名单、更高优先级覆盖、删除降级、非法更新和修复。
8. 检查上下文压缩后激活 SOP 仍完整，独立回流可被正常压缩且不出现孤立工具消息。
9. 检查长期记忆只收到主轮次摘要，不接收独立中间工具轨迹。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_skill_integration.py tests/test_context_integration.py tests/test_session_memory_integration.py -q
```

期望：AC25、AC26 和跨上下文/会话集成场景全部通过。

## T12：更新文档并执行全量回归

**文件：** `README.md`、所有受影响测试文件

**依赖：** T1–T11

**步骤：**

1. 在 README 记录三级目录、完整 frontmatter、单文件/目录包布局、工具 JSON 协议、两种模式、热更新和三个内置命令。
2. 更新原 `/review`、命令数量和工具系统描述，避免旧固定命令文档与新行为冲突。
3. 运行源代码编译检查及 Skill、Agent、命令、权限、上下文、Provider、MCP、会话和记忆目标测试。
4. 运行全量 pytest，修复所有新增或既有回归，不通过时不得标记任务完成。
5. 运行 `git diff --check`，检查冲突标记、调试输出、测试临时文件、会话文件和真实凭据。
6. 对照 `spec.md` 的 AC1–AC27 记录可重复验证证据，供 checklist 阶段逐项验收。

**验证：**

```bash
PYTHONPATH=src .venv/bin/python -m compileall -q src
PYTHONPATH=src .venv/bin/python -m pytest -q
git diff --check
```

期望：编译成功、全量测试全部通过、diff 无空白错误，README 与实际行为一致。

## 执行顺序

```text
T1 ─┬→ T2 ─┬→ T4 ─────────┐
    └→ T3 ─┘               │
T5 ────────────────────────┼→ T7 → T8 ─┐
         T1 + T3 → T6 ─────┘           │
                 T2 + T4 → T9 ─────────┤
                                       └→ T10 → T11 → T12
```

可并行执行的安全分组：

- T5 可立即执行；T2、T3 在 T1 完成后可与其并行。
- T6 可与 T4 并行，但两者都必须在 T7 前完成。
- T9 可与 T7/T8 的独立执行链并行，但必须在 T10 前完成。

建议提交点：

1. T1–T2：格式、Catalog 与内置资源。
2. T3–T6：工具、权限、Runtime、提示与历史基础设施。
3. T7–T8：Agent loader 与独立执行。
4. T9–T10：动态命令、CLI 与热更新。
5. T11–T12：端到端、文档与最终回归。
