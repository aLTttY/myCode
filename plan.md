# Structured System Prompt Plan

## 架构概览

本阶段新增独立的提示构建层，位于 Agent 层和 Provider 层之间。Agent 仍负责循环、模式选择和工具执行；提示构建层负责生成稳定系统提示、环境系统消息、会话级补充消息和强化后的工具描述；Provider 层只负责把这些结构转换成各供应商 API 请求格式。

整体调用链：

```text
CLI
  -> AgentRunner.run(AgentRequest)
  -> PromptBuilder.build(mode, iteration, environment)
  -> Provider.stream_chat(ChatRequest)
  -> Provider converts stable prompt / dynamic system messages / messages / tools
  -> StreamCollector collects text, tool calls, token usage and cache usage
```

提示内容分为两类：

- 稳定内容：固定系统提示模块、可选静态模块、强化后的工具描述。该部分保持确定性，用于缓存。
- 动态内容：环境信息、按轮注入的模式补充指令、普通对话历史。该部分每轮可变化，不进入稳定缓存段。

Provider 兼容策略：

- OpenAI/DeepSeek 协议：用 `system` 角色消息承载稳定系统提示和动态系统补充消息；如目标接口支持缓存字段，则在稳定系统消息或工具描述上加缓存标记；不支持时保持普通请求。
- Anthropic 协议：用顶层 `system` content blocks 承载稳定系统提示和动态补充消息；稳定 block 和工具定义使用 `cache_control`；动态 block 不加缓存控制。

## 核心数据结构

### `PromptModule`

表示一个系统提示模块。

```python
@dataclass(frozen=True)
class PromptModule:
    key: str
    title: str
    content: str
    stable: bool = True
```

- `key`: 稳定标识，用于测试顺序和后续插入模块。
- `title`: 模块标题，渲染为可读分隔。
- `content`: 模块正文。
- `stable`: 是否属于稳定缓存段。本阶段固定全局模块为稳定，环境信息为动态。

### `PromptOptions`

表示可选提示输入。

```python
@dataclass(frozen=True)
class PromptOptions:
    custom_instructions: str = ""
    active_skills: tuple[str, ...] = ()
    long_term_memory: str = ""
```

- `custom_instructions`: 预留自定义指令内容；本阶段默认空。
- `active_skills`: 预留已激活 Skill 摘要；本阶段默认空。
- `long_term_memory`: 预留长期记忆内容；本阶段默认空。

### `EnvironmentInfo`

表示运行时环境信息。

```python
@dataclass(frozen=True)
class EnvironmentInfo:
    cwd: str
    date: str
    mode: AgentMode
```

- `cwd`: 当前工作目录。
- `date`: 当前日期或时间字符串。
- `mode`: 当前请求模式。

### `DynamicInstruction`

表示系统级补充消息。

```python
@dataclass(frozen=True)
class DynamicInstruction:
    tag: str
    content: str
    full: bool
```

- `tag`: 特殊标签，例如 `<mewcode_runtime_instruction>`。
- `content`: 动态规则正文。
- `full`: 本轮是否为完整注入；用于测试首轮、间隔轮和精简轮。

### `PromptBundle`

表示提示构建结果。

```python
@dataclass(frozen=True)
class PromptBundle:
    stable_system_prompt: str
    optional_system_prompt: str
    dynamic_system_messages: tuple[DynamicInstruction, ...]
    environment_message: DynamicInstruction
```

- `stable_system_prompt`: 七个固定模块渲染后的稳定提示。
- `optional_system_prompt`: 自定义指令、已激活 Skill、长期记忆等可选模块渲染后的提示；本阶段默认空。
- `dynamic_system_messages`: 按轮注入的模式补充消息。
- `environment_message`: 当前环境信息补充消息。

### `ChatRequest`

Provider 层统一输入。

```python
@dataclass(frozen=True)
class ChatRequest:
    stable_system_prompt: str
    dynamic_system_messages: tuple[DynamicInstruction, ...]
    messages: tuple[Message, ...]
    optional_system_prompt: str = ""
    tools: tuple[ToolSpec, ...] = ()
    cache_static_content: bool = True
```

- `stable_system_prompt`: Provider 转换为系统消息或顶层 system blocks。
- `optional_system_prompt`: Provider 放在环境信息之后，保持“固定模块 -> 环境信息 -> 可选模块”的优先级顺序。
- `dynamic_system_messages`: Provider 转换为非缓存系统级内容。
- `messages`: 普通用户、助手和工具历史。
- `tools`: 当前模式开放的工具描述。
- `cache_static_content`: 是否尝试给稳定内容加缓存标记。

### `TokenUsage`

扩展现有 token 用量结构。

```python
@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None
    cache_unavailable: bool = False
```

- `cache_read_tokens`: 从缓存读取的输入 token。
- `cache_creation_tokens`: 本次写入缓存的输入 token。
- `cache_unavailable`: Provider 不支持或未返回缓存指标时为 `True`。

## 模块设计

### `mycode.prompts.modules`

**职责：** 定义固定提示模块和可选模块的生成规则。

**对外接口：**

```python
def fixed_prompt_modules() -> tuple[PromptModule, ...]
def optional_prompt_modules(options: PromptOptions) -> tuple[PromptModule, ...]
```

**模块顺序：**

1. 身份
2. 系统约束
3. 任务模式
4. 动作执行
5. 工具使用
6. 语气风格
7. 文本输出
环境信息由动态补充消息承载，插入在固定模块之后。

可选模块追加在环境信息之后：

1. 自定义指令（可选）
2. 已激活的 Skill（可选）
3. 长期记忆（可选）

环境信息不放入稳定模块列表，由动态补充消息单独生成；可选模块默认为空，不影响固定模块顺序。

**覆盖需求：** F1-F4、F12-F14、AC1-AC4、AC11-AC13。

### `mycode.prompts.builder`

**职责：** 拼装稳定系统提示、环境信息和模式补充消息，保证稳定内容与动态内容分离。

**对外接口：**

```python
class PromptBuilder:
    def build(
        self,
        mode: AgentMode,
        iteration: int,
        environment: EnvironmentInfo,
        options: PromptOptions = PromptOptions(),
    ) -> PromptBundle: ...
```

**关键规则：**

- 固定模块按 `modules.py` 的顺序渲染。
- 模块之间用双换行分隔，模块标题稳定。
- 环境信息渲染为 `<mewcode_environment>...</mewcode_environment>`。
- 可选模块渲染在 `optional_system_prompt` 中，由 Provider 放在环境信息之后。
- 模式补充指令渲染为 `<mewcode_runtime_instruction>...</mewcode_runtime_instruction>`。
- `stable_system_prompt` 不包含 `cwd`、日期、用户输入、对话历史或当前迭代次数。

**覆盖需求：** F5-F8、AC2、AC5-AC7。

### `mycode.prompts.modes`

**职责：** 管理会话级开关的注入频率和不同模式的完整/精简指令。

**对外接口：**

```python
def mode_instruction(mode: AgentMode, iteration: int, repeat_interval: int) -> DynamicInstruction
```

**轮次策略：**

- `iteration == 1`: 完整注入。
- `iteration % repeat_interval == 0`: 完整注入。
- 其他轮次：精简提醒。

**Plan Mode 完整规则：**

- 只观察、分析和产出计划。
- 只能使用只读工具。
- 不写文件、不改文件、不执行命令。
- 输出可执行计划，不执行计划。

**Do/default 完整规则：**

- 可在全局规则、安全边界和工具约定下使用完整工具集。
- 编辑前先读取或搜索确认。
- 优先用专用工具，命令只用于合适场景。

**覆盖需求：** F9-F11、AC8-AC10。

### `mycode.tools.descriptions`

**职责：** 集中维护工具描述强化文本，避免每个工具类各自散落重复规则。

**对外接口：**

```python
def reinforce_tool_spec(spec: ToolSpec) -> ToolSpec
def reinforce_tool_specs(specs: Sequence[ToolSpec]) -> tuple[ToolSpec, ...]
```

**强化规则：**

- 每个工具描述追加“何时优先使用该工具”。
- 文件编辑工具追加“编辑前必须读取或搜索确认当前内容”。
- 文件和命令工具追加工作区边界说明。
- 规则只改描述，不改变参数 schema 和工具执行逻辑。

**覆盖需求：** F12-F14、AC11-AC13。

### `mycode.providers.base`

**职责：** 把 Provider 协议从 `messages + tools` 升级为统一 `ChatRequest`。

**对外接口：**

```python
class LLMProvider(Protocol):
    def stream_chat(self, request: ChatRequest) -> Iterator[StreamEvent]: ...
```

**兼容策略：**

- 先迁移 AgentRunner 和 tests 使用 `ChatRequest`。
- Provider 内部保留 `_convert_message` 和工具转换 helper。
- 如有必要，测试辅助 Provider 也记录 `ChatRequest`，便于断言系统提示和动态消息。

**覆盖需求：** F15、F20、AC5、AC18-AC20。

### `mycode.providers.openai`

**职责：** 把 `ChatRequest` 转为 OpenAI/DeepSeek 兼容 payload，并解析缓存字段。

**请求转换：**

- `stable_system_prompt` 转为第一条 `system` 消息。
- `environment_message` 转为第二条 `system` 消息。
- `optional_system_prompt` 非空时转为环境信息之后的 `system` 消息。
- 模式补充消息转为后续 `system` 消息。
- 普通 `messages` 保持原顺序追加。
- 工具描述使用强化后的 `ToolSpec` 转为 `tools`。
- 缓存标记仅在配置或协议允许时添加；默认不破坏现有兼容接口。

**缓存解析：**

- 从 `usage.prompt_tokens_details.cached_tokens` 或等价字段解析缓存读取。
- 如返回 `cache_creation_input_tokens`、`cache_read_input_tokens` 等字段，也映射到统一 `TokenUsage`。
- 未返回缓存字段时设置 `cache_unavailable=True`。

**覆盖需求：** F15-F18、AC14-AC16。

### `mycode.providers.anthropic`

**职责：** 把 `ChatRequest` 转为 Anthropic Messages payload，并解析缓存字段。

**请求转换：**

- 顶层 `system` 使用 content block 数组。
- 稳定系统提示 block 加 `cache_control: {"type": "ephemeral"}`。
- 动态环境 block 放在固定模块之后，不加缓存控制。
- 可选提示 block 放在环境信息之后；本阶段默认不加缓存控制，避免未来 Skill 或记忆变化污染固定缓存。
- 模式补充 block 不加缓存控制。
- 工具定义在支持时加缓存控制，工具结果转换沿用现有逻辑。

**缓存解析：**

- 从 `usage.cache_read_input_tokens` 和 `usage.cache_creation_input_tokens` 映射统一字段。
- 未返回缓存字段时设置 `cache_unavailable=True`。

**覆盖需求：** F15-F18、AC14-AC16。

### `mycode.agent.runner`

**职责：** 在每轮模型调用前构造 `ChatRequest`，移除把模式说明拼入用户文本的逻辑。

**关键变化：**

- 用户消息只保存原始用户文本。
- 每轮循环用当前模式、迭代次数和工作区环境构造提示。
- 根据模式选择只读或完整工具集后，再强化工具描述。
- 调用 Provider 时传入 `ChatRequest`。

**覆盖需求：** F6-F11、F20、AC6-AC10、AC18-AC19。

### `mycode.cli`

**职责：** 展示扩展后的 token/cache 用量。

**关键变化：**

- `format_token_usage` 增加 `cache_read`、`cache_create`、`cache=unavailable`。
- 其他事件展示保持不变。

**覆盖需求：** F18、AC15-AC16。

### `docs/manual-eval-structured-prompts.md`

**职责：** 记录人工对比场景和观察点。

**场景：**

1. 读取后编辑：要求修改文件，观察是否先读取/搜索再编辑。
2. Plan Mode 只读：使用 `/plan`，观察是否只开放和使用只读工具。
3. 专用工具优先：要求找文件、读文件、搜代码，观察是否选择对应工具。
4. 环境变化缓存稳定：改变工作目录或日期模拟输入，观察稳定提示内容不变。
5. 多轮动态注入：连续工具循环，观察首轮完整、间隔轮完整、其余精简。

**覆盖需求：** F19、AC17。

## 模块交互

### 普通对话

```text
用户输入
  -> CLI parse AgentRequest(mode="default")
  -> AgentRunner append Message(role="user", content=原始文本)
  -> PromptBuilder build stable prompt + env + default mode instruction
  -> reinforce_tool_specs(full_registry.tool_specs())
  -> Provider.stream_chat(ChatRequest)
  -> Provider sends system messages + history + tools
  -> StreamCollector emits text_delta/token_usage
  -> AgentRunner done(completed)
```

### Plan Mode

```text
/plan 用户任务
  -> AgentRequest(mode="plan", text=不含 /plan 的原始任务)
  -> AgentRunner selects readonly registry
  -> PromptBuilder injects Plan Mode dynamic instruction
  -> Provider receives user message without mode prefix
  -> Model can see readonly tools only
  -> Agent emits plan text
```

### 多轮工具循环

```text
iteration 1
  -> full mode instruction
  -> model calls tools
  -> tool results append to history

iteration 2
  -> compact mode reminder
  -> model observes tool results

iteration N where N % repeat_interval == 0
  -> full mode instruction repeated
```

### 缓存用量

```text
Provider SSE event with usage
  -> provider-specific parser extracts normal tokens
  -> provider-specific parser extracts cache read/create tokens when present
  -> StreamEvent(type="token_usage", token_usage=...)
  -> AgentEvent(type="token_usage", token_usage=...)
  -> CLI prints usage and cache fields
```

## 文件组织

```text
src/mycode/
  prompts/
    __init__.py
    modules.py              # 固定/可选提示模块
    builder.py              # PromptBuilder、PromptBundle、EnvironmentInfo
    modes.py                # 模式动态指令与注入频率
  tools/
    descriptions.py         # ToolSpec 描述强化
  providers/
    base.py                 # ChatRequest + LLMProvider 协议
    openai.py               # OpenAI/DeepSeek 请求转换和缓存字段解析
    anthropic.py            # Anthropic 请求转换和缓存字段解析
  agent/
    runner.py               # 构造 ChatRequest，移除用户文本模式拼接
  cli.py                    # cache usage 展示
  types.py                  # TokenUsage 扩展；必要时共享基础类型

tests/
  test_prompts.py           # 模块顺序、稳定/动态分离、模式注入频率
  test_tool_descriptions.py # 工具描述强化规则
  test_providers.py         # Provider payload 和缓存字段解析
  test_agent_runner.py      # Plan/Do/default 请求构造回归
  test_cli.py               # cache usage 展示

docs/
  manual-eval-structured-prompts.md
```

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 提示构建位置 | 新增 `mycode.prompts` 包 | 保持 Agent 只管流程，Provider 只管协议转换，便于测试稳定提示文本。 |
| Provider 入参 | 使用 `ChatRequest` 替代 `messages, tools` 两参数 | 系统提示、动态消息和缓存标记需要结构化传输，继续加参数会让接口膨胀。 |
| 动态补充消息形式 | 系统级消息 + `<mewcode_runtime_instruction>` 标签 | 满足“不污染用户输入”和“模型知道这是运行时指令”的需求。 |
| 环境信息位置 | 动态系统消息 `<mewcode_environment>`，位于固定模块之后、可选模块之前 | 环境会变化，不应进入稳定缓存段，同时保持用户指定的提示优先级。 |
| 模式注入频率 | 默认首轮完整、每 3 轮完整、其他精简 | 成本和可见性折中；后续可放入配置，本阶段先作为 AgentConfig 默认值。 |
| 工具描述强化 | 通过 `reinforce_tool_specs` 包装已有 ToolSpec | 不改变工具执行类和 schema，降低回归风险。 |
| Anthropic 缓存 | 稳定 system block 和工具定义使用 `cache_control` | Anthropic 原生支持 content block 缓存控制，最符合稳定/动态分离。 |
| OpenAI/DeepSeek 缓存 | 解析已知缓存字段，缓存标记采用能力检测/兼容降级 | OpenAI 兼容服务字段差异大，不能让缓存能力破坏普通请求。 |
| 缓存不可验证 | `TokenUsage.cache_unavailable=True` | 用户能区分“没有命中”和“Provider 没返回指标”。 |
| 人工对比 | 文档化场景，不做自动评分 | 符合 spec 中“不做自动化评估”的边界。 |

## Spec 覆盖

- F1-F4、AC1-AC4：由 `mycode.prompts.modules` 和 `PromptBuilder` 覆盖。
- F5-F8、AC5-AC7：由 `PromptBundle`、`ChatRequest` 和 Provider 转换覆盖。
- F9-F11、AC8-AC10：由 `mycode.prompts.modes` 和 `AgentRunner` 模式处理覆盖。
- F12-F14、AC11-AC13：由固定提示模块和 `tools.descriptions` 双重强化覆盖。
- F15-F18、AC14-AC16：由 Provider `ChatRequest` 转换和 `TokenUsage` 扩展覆盖。
- F19、AC17：由 `docs/manual-eval-structured-prompts.md` 覆盖。
- F20、AC18-AC20：由 Agent、Provider、CLI 回归测试覆盖。
