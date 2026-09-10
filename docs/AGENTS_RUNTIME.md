# AGENTS_RUNTIME 模块（backend/app/domain/agents + application/agents）

## 职责

Agent 业务领域与运行时：Agent CRUD、发布与应用、外部访问身份（公开访客/API 凭据）、知识库/工具绑定与权限校验；基于 LangGraph 的多轮工具调用执行（计划 → 检索/工具调用 → 结果 → 终止条件），事件流式输出，跨模型供应商的会话记忆压缩与用量记录，以及 durable 运行执行（租约/checkpoint、四表持久化、Workflow Agent 子运行续延）与有界落地校验（grounding）。Agent/Workflow 共用同一套 durable Tool 运行时与运行派发入口，工具执行统一记账于 `tool_invocations`。

## 分层关系

```text
api/v1/agents/routes.py + access.py（工作区 CRUD/监控 + 公开/API 访问）
   → application/agents/__init__.py（用例门面，重导出 CRUD 与 Run/工具用例）
       → runs/service.py（提交/读取/审批/再生/反馈、可重放与实时事件订阅）
       → runs/executor.py（租约执行、checkpoint、工具账本与终态/恢复）
       → runs/memory.py + children.py + snapshots.py（记忆压缩、子运行续延与执行快照）
       → tools/builder.py + runtime.py（ToolSnapshot → StructuredTool / durable Tool 运行时桥）
       → access/service.py（发布上下文、凭据、限流与外部投影）
       → domain/agents/service.py + models.py（CRUD/绑定/发布编排与 ORM）
       → domain/agents/access/{permissions,publications}.py（权限规则、发布快照）
       → domain/agents/runtime/（LangGraph 状态图执行内核）
       → ports/*（llm/rag/tool_runtime 契约）+ adapters/*（供应商与工具实现）
共享：application/tools/runtime/service.py + adapters/tools/runtime.py（统一 Tool 运行时）
      application/runs/dispatch.py（Agent legacy/unified 与 Workflow durable 派发）
      tasks/agents/jobs.py（Celery 任务入口）
      infra/db/repositories/agents/repository.py（持久化仓储）
```

## 文件清单

### domain/agents/（领域层：配置、权限与执行内核）

- `backend/app/domain/agents/models.py` — Agent ORM 模型：`agents`、`agent_publication_versions`、`agent_knowledge_bases`、`agent_mcp_tools`、`agent_api_credentials`，以及 Run 四表 `agent_runs` / `agent_run_states` / `agent_run_snapshots` / `agent_run_events`（身份/谱系、可变状态与租约/checkpoint、创建时冻结快照、只追加事件）。纯 dataclass 实体集中在 `app/entities/agents/models.py`，仓储负责 ORM ↔ 实体映射。
- `backend/app/domain/agents/service.py` — Agent 服务层（原 services.py）：CRUD、可用模型/知识库/工具解析（含 legacy MCP 引用兼容）、权限前置校验、发布状态机（应用发布、未发布变更检测）与运行参数编排。
- `backend/app/domain/agents/evaluation.py` — 无副作用的 Agent 评测数据集契约、单样本断言与发布门禁聚合规则。
- `backend/app/domain/agents/access/permissions.py` — Agent 资源权限规则：`AGENT_RESOURCE_TYPE`、view/edit 判定与授权/撤销用例。
- `backend/app/domain/agents/access/publications.py` — 规范化不可变发布快照：schema 版本、定义哈希、配置/资源快照构造与从快照还原。

### domain/agents/runtime/（LangGraph 执行内核）

- `backend/app/domain/agents/runtime/graph.py` — LangGraph 智能体状态图：多轮工具调用循环、模型文本流过滤（含 DSML 解析与增量清洗）、证据去重与终止条件。
- `backend/app/domain/agents/runtime/executor.py` — LangGraph 执行入口 `run_agent`：可串行化 checkpoint 的保存/恢复，以及单次生成 grounding 状态与审计元数据的持久化。
- `backend/app/domain/agents/runtime/grounding.py` — 单次生成 grounding 协议：在答案 Markdown 前解析并隐藏有界 manifest，确定性校验证据 ID，失败时在正文输出前关闭。
- `backend/app/domain/agents/runtime/tools.py` — LangChain StructuredTool 通用适配、参数 schema 校验、暂停/uncertain/busy 信号与元数据读取。
- `backend/app/domain/agents/runtime/callbacks.py` — 智能体事件总线（`AgentEventBus`/`NexaFlowCallback`）：事件订阅、敏感字段脱敏与 LLM 流式回调。
- `backend/app/domain/agents/runtime/state.py` — 运行状态 TypedDict 定义（消息、事件、轮次、证据与待执行工具调用等）。
- `backend/app/domain/agents/runtime/usage.py` — 各供应商 token/cache usage 的统一归一化，区分已上报与未上报调用。

### application/agents/（用例层）

- `backend/app/application/agents/__init__.py` — Agent 用例门面：重导出 CRUD 用例与 Run 编排/工具构造用例（拆分至 `runs/service.py` 与 `tools/builder.py`），保持调用方入口稳定。
- `backend/app/application/agents/runs/service.py` — Run 编排：创建/准备/入队、列表与读取、工具审批解析、取消与 run 树取消、从源再生（regenerate）、反馈、canonical 工具调用列表、可重放执行消息与实时流订阅。
- `backend/app/application/agents/runs/executor.py` — durable Run 执行（原 agent_executor 职责）：Run 租约/心跳/接管（`maintain_agent_run_lease`）、节点 checkpoint 落库、工具幂等账本（`DurableToolLedger`）与终态/失败收尾，并导出 legacy/unified 恢复候选查询。
- `backend/app/application/agents/runs/memory.py` — 会话记忆准备与压缩：按 `conversation_id` 读取历史成功 Run、token 预算估算、摘要消息与最近轮次保留。
- `backend/app/application/agents/runs/children.py` — Workflow Agent 子运行的 durable 续延：子运行创建/恢复、等待父运行 reconcile、过期父运行失败收尾。
- `backend/app/application/agents/runs/snapshots.py` — 创建 Run 时冻结运行预算、非敏感模型配置指纹和知识资源版本信息（含可检索文档/分块内容指纹）；执行前检查模型或知识漂移。
- `backend/app/application/agents/tools/builder.py` — 工具构造与纯映射（原 agent_tools 职责）：知识检索工具、统一 ToolSnapshot → StructuredTool 包装、MCP 工具构造、Run → response 与错误/输出脱敏。
- `backend/app/application/agents/tools/runtime.py` — 通往 provider-neutral durable Tool 运行时的薄桥（`UnifiedAgentToolRuntime`）：固定幂等身份，并把 `ToolRuntimeResult` 映射回 `AgentToolResult`。
- `backend/app/application/agents/access/service.py` — 公开/API 访问领域：发布上下文解析（Agent/Workflow/Application）、访客 Cookie 与 API 凭据（高熵 token、SHA-256 哈希、轮换/吊销）、外部 Run CRUD/流式投影与清洗、限流与工作区运行日志/会话用户查询。
- `backend/app/application/agents/prompts.py` — AI 辅助 Agent 指令编写（生成/改写 instructions 契约）。

### api/v1/agents/

- `backend/app/api/v1/agents/routes.py` — 工作区 Agent 路由器：CRUD、权限授予/撤销、API 凭据管理、指令生成、附件上传、Run 提交/读取/取消/再生/反馈/审批/流式与重连、日志与会话监控。
- `backend/app/api/v1/agents/access.py` — 公开与 API 路由器：公开 profile/会话管理、外部 Run CRUD/流式 NDJSON、工具审批与 API 文档入口。

### 共享运行时、任务入口与持久化（Agent/Workflow/测试共用）

- `backend/app/application/tools/runtime/service.py` — durable、provider-neutral 的 Tool 执行：`queue_tool_invocation`/`execute_tool_invocation`、幂等冲突检测、审批等待、busy/conflict 语义、执行前 preflight 与过期调用恢复。
- `backend/app/adapters/tools/runtime.py` — ToolAdapter 实现：`BuiltinToolAdapter`/`PythonToolAdapter`/`McpToolAdapter` 与 `build_tool_adapter` 工厂（含 sandbox/artifact 执行路径）。
- `backend/app/application/runs/dispatch.py` — `run_durable_application_run`：按 Run 类型（agent legacy/unified、workflow）分派到对应 durable executor 并协调 Workflow Agent 子运行恢复。
- `backend/app/tasks/agents/jobs.py` — Celery 任务入口：agent legacy/unified 运行任务、过期/失败运行恢复任务与入队辅助。
- `backend/app/infra/db/repositories/agents/repository.py` — Agent 持久化仓储：Agent/发布版本/API 凭据/绑定查询与写入、Run 四表（claim/renew 租约、checkpoint、终态、事件追加与游标投影、恢复候选、run 树取消）、会话记忆读取与摘要保存，以及统一 `ToolInvocation` 的审批/幂等状态落库与 canonical 工具调用视图。

## 相关测试

Agent feature 测试并入 `backend/tests/agents/` 包，从 `backend/` 以 `uv run python -m tests.agents.<suite>` 运行：

- `tests/agents/agents.py` — Agent 端到端套件：检索策略、租约接管、断线、统一 Tool 固定版本、MCP 审批/只读策略、uncertain、预算、run 树取消与安全边界。
- `tests/agents/unit.py` — 纯单元测试（无数据库/HTTP/网络，仓储与端口打桩）。
- `tests/agents/agent_access.py` — 公开/API 访问域覆盖：`application/agents/access/service.py`、`api/v1/agents/access.py` 与限流 Lua（`infra/security/agent_rate_limit.py`）。
- `tests/agents/agent_services_coverage.py` — Agent services/权限/发布/仓储/tasks 域覆盖。
- `tests/agents/agent_runtime_coverage.py` — 执行内核覆盖：durable Run executor/runs service、记忆、domain runtime（executor/usage/tools/callbacks）与 Redis 实时流基础设施。
- `tests/agents/evaluation.py` — 无网络的确定性生产门禁：直接回答、工具、grounding、usage 与必需用例聚合规则。

## 运行策略与生产边界

- 知识策略显式分为 `required`（默认，用用户原始问题在首个模型节点前检索）和 `agentic`（模型生成查询并决定何时调用）。不再在答案生成后追加第二次 LLM 核验。最终模型节点先在同一次生成中对照证据，输出一个不展示给用户的 grounding manifest，后端确定性校验其证据 ID 后才放行随后的 Markdown 流。`required` 的 manifest 缺失、证据 ID 非法或证据不足时在正文前 fail closed；`agentic` 没有使用知识证据时可标记 `skipped` 并继续普通回答。终态 `grounding_meta` 保存决定、证据 ID、包数量与截断标记；最终 Markdown 不再被第二个模型重写。
- 每个 Run 都属于一个 `conversation_id`，并以 `access_source + consumer_id` 区分登录用户、公开访客和 API 凭据；同一工作区、Agent、来源主体、会话最多只有一个活动 Run。未传会话 ID 的旧登录客户端复用最近会话，前端把当前会话写入 URL，并可显式开始新会话。
- 历史成功 Run 以真实 `user`/`assistant` 角色恢复。上下文在保守 token 预算内直接复用；超预算时用当前注册模型压缩较旧轮次，摘要持久化在最后被覆盖的成功 Run 上，同时保留最近 6 轮。摘要调用失败时回退到截断历史，不阻断当前问题，原始 Run 记录始终保留。
- `model_usage` 累加 Agent loop 与摘要调用的实际供应商用量，并单列 compaction、cache read/create 与未上报调用数。系统不会为未返回 usage 的供应商猜测计费 token；服务端 prompt cache 的写法仍由各供应商 SDK 决定，不伪造跨供应商通用的 `cache_control`。
- Run 创建时冻结整次执行时长、模型轮次、工具调用次数和模型 token 四项预算。总截止时间只在第一次成功 claim 时写入，worker 重试、租约接管和 checkpoint 恢复不会刷新；人工审批或输入等待时间会显式加回截止时间。每次工具调用仍有独立硬超时，达到最后一轮时不再向模型暴露工具；grounding 与最终答案共享同一次模型调用和 token 预算。连续两轮没有新知识证据后停止继续检索，保留 MCP 外部能力供模型决定是否需要。
- HTTP 只提交/观察 Run；Celery worker（任务入口 `app/tasks/agents/jobs.py`，经 `app/application/runs/dispatch.py` 派发到 `app/application/agents/runs/executor.py`）用数据库租约执行，节点 checkpoint、过程事件游标和工具账本均持久化。答案与推理 delta 不写 PostgreSQL，而是进入按 Run 隔离、限长并带 15 分钟 TTL 的 Redis Stream；API 把 Redis 增量与数据库事件合并为同一 NDJSON。客户端分别用 `after` 和 `live_after` 恢复持久与实时游标，终态数据库快照负责最终校正；Redis 不可用时自动降级为过程事件加完整终态答案。断开 NDJSON 不会取消 Run。
- Run 持久层按职责拆分：`agent_runs` 只保存身份、调用者、谱系、反馈和 trace；`agent_run_states` 保存状态、租约、总截止时间、checkpoint、结果与模型用量；`agent_run_snapshots` 保存创建时冻结的执行配置、四项预算、非敏感模型配置指纹和知识资源信息；`agent_run_events` 只追加事件。版本化 Run 若检测到模型端点、凭据版本或请求参数漂移，以及知识权限被撤销，会在执行前失败关闭。所有 Agent/Workflow/测试工具执行统一写入 `tool_invocations`，不再维护第二套工具调用账本。
- 发布前真实质量门禁使用 `backend/scripts/agent_eval.py` 调用现有工作区 Run API，按答案、grounding、工具、证据数量、token、模型调用数和延迟断言；数据集与运行说明见 `docs/AGENT_EVALUATION.md`。报告不保存问题、答案、证据正文或令牌。
- Agent 草稿保存稳定的 `ToolRef(tool_id, version_id)`；发布版本和 Run 再冻结完整 ToolSnapshot。Tool/Source 禁用、授权撤销、成员失效或策略漂移会在 dispatch 前 fail closed，不静默换到新版本。
- 新发现的 MCP 工具默认逐次审批；只有管理员按当前定义哈希显式设置为 `read_only` 才会自动运行，远端 `readOnlyHint` 等注解不会单独改变审批策略。管理员可按当前定义哈希设置为只读、审批或禁用，工具定义变化后已有策略回落到逐次审批。副作用调用携带稳定幂等键；传输超时、worker 在外部调用后崩溃或结果未落账时标记 `uncertain`，禁止自动重试，只能人工确认后"不重试并继续"。远端 MCP 若不兑现幂等键，系统提供的是保守恢复而非跨系统 exactly-once。
- 发布和 API 凭据写操作仅工作空间管理员可执行。发布固化当时的模型、知识库和 ToolSnapshot；后续草稿变化不撤销既有发布，公开/API 继续运行上一发布版本，直到重新发布、取消发布或停用应用。外部运行使用发布者快照身份受审计，但不冒充访问者；仅允许仍有效、无需逐次审批的只读工具，不开放外部审批路径。
- 公开访客 Cookie 和 API Key 都使用高熵随机值，数据库只保存 SHA-256 派生标识或密钥哈希。外部提交同时受 Agent 总量桶和来源主体桶限流；Redis 不可用时成本型请求失败关闭，不先排队后补跑。
- 公开/API Key Run 复用内部 durable 事件链，HTTP 契约只投影固定枚举的分析、知识检索、工具调用、回答生成状态、知识片段数量与模型思考过程（`reasoning_delta` 增量及 progress 上的累积文本）；工具名称/参数、检索原文、System Prompt 和 trace 不离开内部边界。
