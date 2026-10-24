# AGENTS_RUNTIME 模块（backend/app/domain/agents + application/agents）

## 职责

Agent 业务领域与运行时：Agent CRUD、发布与应用、外部访问身份（公开访客/API 凭据）、知识库/工具绑定与权限校验；基于 LangGraph 的多轮工具调用执行（模型 → 可选工具 → 结果 → 模型/回答），事件流式输出，跨模型供应商的会话记忆压缩与用量记录，以及 durable 运行执行（租约/checkpoint、四表持久化、Workflow Agent 子运行续延）。Agent/Workflow 共用同一套 durable Tool 运行时与运行派发入口，工具执行统一记账于 `tool_invocations`。

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
       → ports/*（llm/vector_store/mcp/execution 契约）+ adapters/*（供应商实现）
       → application/tools/runtime/contracts.py（provider-neutral Tool 契约）
共享：application/tools/runtime/service.py + application/tools/runtime/adapters/（统一 Tool 运行时）
      infra/agents/live_stream.py（实时增量 Redis Stream）
      infra/tools/dispatch.py + mcp_stdio.py（Tool 派发与 MCP stdio 契约）
      application/runs/dispatch.py（Agent legacy/unified 与 Workflow durable 派发）
      tasks/agents/jobs.py（Celery 任务入口）
      infra/db/repositories/agents/repository.py（持久化仓储）
```

## 文件清单

### domain/agents/（领域层：配置、权限与执行内核）

- `backend/app/domain/agents/models.py` — Agent ORM 模型：`agents`、`agent_publication_versions`、`agent_knowledge_bases`、`agent_mcp_tools`、`agent_api_credentials`，以及 Run 四表 `agent_runs` / `agent_run_states` / `agent_run_snapshots` / `agent_run_events`（身份/谱系、可变状态与租约/checkpoint、创建时冻结快照、只追加事件）。纯 dataclass 实体中 Agent 侧在 `app/entities/agents/models.py`，Run 四表实体在 `app/entities/runs/models.py`（`AgentRun`/`AgentRunEvent`，仓储与用例统一从 `app.entities.runs` 导入），仓储负责 ORM ↔ 实体映射。
- `backend/app/domain/agents/service.py` — Agent 服务层（原 services.py）：CRUD、可用模型/知识库/工具解析（含 legacy MCP 引用兼容）、权限前置校验、发布状态机（应用发布、未发布变更检测）与运行参数编排。
- `backend/app/domain/agents/evaluation.py` — 无副作用的 Agent 评测数据集契约、单样本断言与发布门禁聚合规则。
- `backend/app/domain/agents/access/permissions.py` — Agent 资源权限规则：`AGENT_RESOURCE_TYPE`、view/edit 判定与授权/撤销用例。
- `backend/app/domain/agents/access/publications.py` — 规范化不可变发布快照：schema 版本、定义哈希、配置/资源快照构造与从快照还原。
- `backend/app/domain/agents/approval.py` — 每次 Run 的交互式同意模式（`always_ask`/`ask_risky`/`full_access`，默认 `always_ask`）与 Tool/MCP 审批判定；`access_source=api` 的运行固定为 `always_ask`。

### domain/agents/runtime/（LangGraph 执行内核）

- `backend/app/domain/agents/runtime/graph.py` — LangGraph 智能体状态图：多轮工具调用循环、模型文本流过滤（含 DSML 解析与增量清洗）与统一轮次/工具预算。
- `backend/app/domain/agents/runtime/executor.py` — LangGraph 执行入口 `run_agent`：可串行化 checkpoint 的保存/恢复；旧 checkpoint 的 RAG/grounding 字段被忽略，系统协议在恢复时更新。
- `backend/app/domain/agents/runtime/tools.py` — LangChain StructuredTool 通用适配、参数 schema 校验、暂停/uncertain/busy 信号与元数据读取。
- `backend/app/domain/agents/runtime/callbacks.py` — 智能体事件总线（`AgentEventBus`/`NexaFlowCallback`）：事件订阅、敏感字段脱敏与 LLM 流式回调。
- `backend/app/domain/agents/runtime/state.py` — 运行状态 TypedDict 定义（消息、事件、轮次、用量、最终答案与待执行工具调用）。
- `backend/app/domain/agents/runtime/session.py` — AgentSession harness：轮次前输入消费、context/extension 生命周期与能力状态恢复。
- `backend/app/domain/agents/runtime/capabilities.py` — 授权能力目录、可 checkpoint 的启用工具集合、search_tools / activate_tools / load_skill。
- `backend/app/domain/agents/runtime/context.py` — 执行中轮次间上下文估算与摘要，保留工具消息组，摘要调用计入用量。
- `backend/app/domain/agents/runtime/extensions.py` — 受信任项目代码的扩展契约与 context / before_tool / after_tool hooks；不加载用户扩展代码。
- `backend/app/domain/agents/runtime/usage.py` — 各供应商 token/cache usage 的统一归一化，区分已上报与未上报调用。

### application/agents/（用例层）

- `backend/app/application/agents/__init__.py` — Agent 用例门面：重导出 CRUD 用例与 Run 编排/工具构造用例（拆分至 `runs/service.py` 与 `tools/builder.py`），保持调用方入口稳定。
- `backend/app/application/agents/runs/service.py` — Run 编排：创建/准备/入队、列表与读取、工具审批解析、取消与 run 树取消、从源再生（regenerate）、反馈、canonical 工具调用列表、可重放执行消息与实时流订阅。
- `backend/app/application/agents/runs/executor.py` — durable Run 执行（原 agent_executor 职责）：Run 租约/心跳/接管（`maintain_agent_run_lease`）、节点 checkpoint 落库、工具幂等账本（`DurableToolLedger`）与终态/失败收尾，并导出 legacy/unified 恢复候选查询。
- `backend/app/application/agents/runs/memory.py` — 会话记忆准备与压缩：按 `conversation_id` 读取历史成功 Run、token 预算估算、摘要消息与最近轮次保留。
- `backend/app/application/agents/runs/session.py` — Console/公开/API Key Run 的授权输入追加；消费逻辑在 domain session，队列在既有事件表。
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
- `backend/app/application/tools/runtime/contracts.py` — provider-neutral Tool 契约：`ToolAdapter` 协议、`ToolInvocationContext`（含 resource_snapshot/approval_required/deadline_at）、`ToolRuntimeResult` 与 `ToolAdapterBusy`。
- `backend/app/application/tools/runtime/adapters/` — `ToolAdapter` 实现与工厂：`BuiltinToolAdapter`/`PythonToolAdapter`/`McpToolAdapter`（`builtin.py`/`python_tool.py`/`mcp.py`，含 sandbox/artifact 执行路径），`build_tool_adapter` 在 `adapters/__init__.py`；`image_generation.py` 提供 `generate_image_artifact`，`shell.py` 执行 bash、实时核验 Skill 授权、恢复已批准的依赖并流式登记生成物（均由 builtin 适配器内部分派）。
- `backend/app/application/tools/management/service.py` — Tool 目录、Python 工具生命周期/测试与 `view/use` 授权用例。
- `backend/app/application/runs/lifecycle.py` — `cancel_run_tree`：取消 Run 树并结算被取消的 Tool invocation（Agent/Workflow 共用）。
- `backend/app/application/runs/feedback.py` — `update_run_feedback`：终态 Run 的反馈写入与清除。
- `backend/app/application/runs/dispatch.py` — `run_durable_application_run`：按 Run 类型（agent legacy/unified、workflow）分派到对应 durable executor 并协调 Workflow Agent 子运行恢复；同文件提供 `enqueue_agent_run`（按 generation 投递 `agents-legacy`/`agents-v2`）。
- `backend/app/infra/agents/live_stream.py` — 按 Run 隔离的 Redis Stream 实时增量（`AgentLiveStreamPublisher`/`AgentLiveStreamReader`，maxlen 4096、TTL 900s、key `nexaflow:agent-live:{run_id}`）。
- `backend/app/infra/tools/dispatch.py` — `enqueue_tool_invocation`：经 Celery `app.tools.run` 投递 durable ToolInvocation。
- `backend/app/infra/tools/mcp_stdio.py` — MCP stdio 配置契约与上限校验（command/args/cwd/env/egress_domains 属于执行镜像路径）。
- `backend/app/infra/execution/sessions.py` / `infra/db/repositories/execution/sessions.py` — 持久化沙箱所有权与 Run 租约核验；`adapters/execution/opensandbox.py` 按 ID 接回、短租约监督、原生 TTL 和清理，`pool.py` 使用 SDK 的共享 Redis 预热池，`resources.py` 保存待 Kata 校准的三档规格。`adapters/execution/capacity.py` 按主机、外部 consumer 与工作空间三个维度在 Redis 记账容量；`opensandbox.py` 的出网策略在每条命令前 reconcile（清理上一位 worker 遗留的放行规则），因此 worker 硬死不会再让该 Run 丢失工作区；创建、执行与销毁共享调用方的整体 deadline。
- `sandbox/command.py` / `mcp_bridge.py` — 独立执行镜像中的 bash 监督与 stdio HTTP 桥接；业务进程不执行子程序。`sandbox/command.py` 对工作区施加 512 MiB / 20 000 文件的上限，持续增长时以退出码 125 停止命令，并回收旧的导出目录。
- `backend/app/tasks/agents/jobs.py` — Celery 任务入口：`run_agent_job`（agent legacy/unified 运行任务）。
- `backend/app/tasks/maintenance/jobs.py` — 周期恢复编排：agent legacy/unified 恢复、Workflow Agent 子运行 reconcile 与 Tool invocation 恢复。
- `backend/app/infra/db/repositories/agents/repository.py` — Agent 持久化仓储：Agent/发布版本/API 凭据/绑定查询与写入、Agent 维度的 Run 列表与会话记忆读取/摘要保存，以及统一 `ToolInvocation` 的审批/幂等状态落库与 canonical 工具调用视图。
- `backend/app/infra/db/repositories/runs/{runs,leases,events}.py` — Run 四表身份/状态/快照读写、执行租约 claim/renew/requeue/cancel 与恢复候选、Run 事件追加与游标投影。
- `backend/app/infra/db/repositories/runs/session_inputs.py` — append-only 输入队列：RunState 行锁、幂等冲突、数量限制与待消费查询；成功终态使用相同锁。

## 相关测试

Agent feature 测试并入 `backend/tests/agents/` 包，从 `backend/` 以 `uv run python -m tests.agents.<suite>` 运行：

- `tests/agents/agents.py` — Agent 端到端套件：检索策略、租约接管、断线、统一 Tool 固定版本、MCP 审批/只读策略、uncertain、预算、run 树取消与安全边界。
- `tests/agents/unit.py` — 纯单元测试（无数据库/HTTP/网络，仓储与端口打桩）。
- `tests/agents/agent_access.py` — 公开/API 访问域覆盖：`application/agents/access/service.py`、`api/v1/agents/access.py` 与限流 Lua（`infra/security/agent_rate_limit.py`）。
- `tests/agents/agent_services_coverage.py` — Agent services/权限/发布/仓储/tasks 域覆盖。
- `tests/agents/agent_runtime_coverage.py` — 执行内核覆盖：durable Run executor/runs service、记忆、domain runtime（executor/usage/tools/callbacks）与 Redis 实时流基础设施。
- `tests/agents/evaluation.py` — 无网络的确定性生产门禁：直接回答、通用工具循环、无核验即时流式输出、usage 与必需用例聚合规则。
- `tests/agents/harness.py` — harness 确定性循环、能力授权/恢复、Skill 渐进加载、context/扩展 hooks，以及数据库队列/终态与 Console/公开/API Key 隔离、本地模拟模型 durable 执行。

## 运行策略与生产边界

- Agent 生成的 HTML/HTM、PDF、DOCX、XLSX、PPTX 在调试页和已发布聊天页中以文件卡片展示，点击后在当前页右侧分栏预览，不加遮罩，左侧仍可聊天和发送追问；调试页预览时暂时收起配置区域，关闭后恢复。手机端使用全宽预览，关闭后回到聊天并保留草稿。每个会话共用一个预览面板，切换文件替换当前预览，切换会话关闭预览，并保留原文件下载。预览只从当前回答轮次内成功的 `create_artifact`、四个固定文档 Skill、bash 或 Skill 脚本事件提取平台文件；历史回答与追问分别保留各自生成物，同名文件以最新结果为准。点击后才通过签名下载接口读取，沿用 5 MiB / 24 小时有效期，检查 MIME、大小，处理超时、过期、解析失败、重试和关闭时取消。
- HTML 只进入 `sandbox="allow-scripts"` 的不透明源 iframe，先于生成内容设置 CSP，允许内联 CSS/JavaScript 和内嵌图片，禁止网络、子框架、Worker、同源、弹窗、表单及顶层导航。Agent 回答协议引导交付自包含 HTML；普通代码块仍显示源码。
- PDF/Office 同样在不透明源 iframe 内解析，宿主仅通过校验来源窗口和随机通道的消息传递文件字节及翻页状态，不传下载凭据，不将文档挂载到宿主 DOM，不上传第三方服务。CSP 仅开放 `/file-preview/` 的本地静态渲染资源、内嵌媒体和受控 Worker。Office ZIP 先限制条目数及声明解压大小；PDF 使用本地 PDF.js Worker 按页渲染，并保留文本供辅助技术读取。DOCX 保留分页布局；PPTX 展示静态幻灯片并支持翻页；XLSX 展示可见工作表、基本单元格样式和缓存公式结果，最多 500 行/50 列并提示截断，不执行公式/宏。复杂字体、图表、动画和 Office 排版不保证完全还原；旧版 DOC/XLS/PPT 及其他文件保留下载。
- `frontend/scripts/build-file-preview.ts` 用 Bun 独立打包按格式加载的查看器与 PDF Worker，复制字体、CMap、WASM 和许可证到忽略版本控制的 `frontend/public/file-preview/`；`bun run dev` / `bun run build` 自动执行，单独更新查看器可运行 `bun run build:file-preview`。Next.js 仅对该公开静态目录开放匿名 CORS，API 的权限及下载响应头不变。现有镜像构建及 `public/` 复制流程直接包含这些资源，不需要数据库迁移或额外预览服务。

- Agent 内核不预设 RAG 路径。知识库检索、MCP、内置/自定义工具和可执行 Skills 都以 StructuredTool 接入同一模型/工具循环，由模型根据任务选择是否调用；知识工具暴露 `search_mode`（embedding/keywords/blend，默认 blend）等参数，`similarity` 缺省使用 `DEFAULT_KNOWLEDGE_SIMILARITY = 0.5`（归一化余弦下限），单次最多 8 条命中（`MAX_KNOWLEDGE_HITS_PER_CALL`）；选中的命中不会为迁就消息长度被丢弃，超出 `MAX_KNOWLEDGE_CONTEXT_CONTENT_CHARS` 的单条内容就地截断并标记 `content_truncated`，命中条数只由 `KnowledgeSearchInput.limit` 决定；一次调用会检索全部已配置来源并在来源之间轮流取命中，`knowledge_base` 可把该次调用收窄到单个来源（按名称或 id 精确匹配，仅限该 Run 已授权来源，未知名称报错并列出可用来源）；知识工具的来源说明和引用格式随工具描述提供，不注入通用 Agent 系统协议。没有前置强制检索、证据充分性/来源多样性门控、重复检索拦截、grounding manifest、后置核验或失败替换答案。来源卡片从成功的知识工具事件直接生成，并不代表所有检索片段都被答案引用。
- 每个 Run 都属于一个 `conversation_id`，并以 `access_source + consumer_id` 区分控制台/工作区成员、已发布应用的公开访问（消费方为登录用户 id）和 API 凭据；同一工作区、Agent、来源主体、会话最多只有一个活动 Run。未传会话 ID 的旧登录客户端复用最近会话，前端把当前会话写入 URL，并可显式开始新会话。
- AgentSession 把输入消费、CapabilityRegistry、轮次间 ContextManager 和受信任扩展生命周期组合成 harness。默认 bash 优先装入初始 Schema 预算，并在大目录、activate_tools 和 checkpoint 恢复后持续可用；最多 8 个工具的小目录再按配置顺序使用 16 KiB 总预算的剩余额度，放不下的单个工具延迟加载。更大的目录通过 search_tools/activate_tools 渐进选择可选工具。Skills 初始仅目录，通过 load_skill/read_skill_file 读取固定版本正文和 UTF-8 文件。load_skill 通过实时授权检查后，如果包里含 `.py` / `.js` 且 Run 目录已授权 run_skill_script，就自动激活该工具并随 checkpoint 保存，下一轮可直接执行；Run 包含 bash 时同时返回经过规范化、带版本哈希的 `/skills/` 路径。管理工具只改变内存/下一 checkpoint；run_skill_script 是普通 ledger-backed Tool，真实动作经过审批/幂等/租约策略与外部 OpenSandbox。
- `execution_sessions` 按工作区、Run、purpose、owner_key 对未关闭记录建立唯一索引。执行前核验 Run 身份、截止时间和镜像/网络指纹，SDK 按 ID 接回；启动租约 60 秒，运行时每 2 秒续期至 15 秒并核验 worker_task_id，失去所有权立即中止。旧 holder 过期后，接管者先清理旧进程；关闭中记录阻止新建，确认销毁后才释放 Redis 容量。Python Tool、Workflow 代码、生成物、渲染器和 Skill/bash 共用 Run 沙箱，终态/取消主动关闭，Beat 回收过期、孤儿与遗留标签。依赖锁在普通重连时直接复用，重建时才重放已批准的安装并返回 workspace_reset。
- bash 是 Agent 默认内置能力，新建 Run 自动注入并冻结版本，计入统一工具调用预算，无需手动绑定；工具目录、选择器和 Agent 绑定列表隐藏它，历史手动绑定保存时自动清除。新建 Run 默认冻结 24 轮/64 次调用/900 秒，历史 Run 保留原预算；单命令 1–300 秒，工具截止时间为命令超时加 60 秒并受 Run 截止时间约束。非零退出和超时 124 作为正常结果；输出最多 30 KiB，结束后清理该 UID 的所有进程，outputs 每条最多 8 个、单个 5 MiB 的文件按流登记生成物。控制台时间线显示命令和退出码，外部投影继续隐藏工具参数。
- 会话生成文件独立于沙箱保存：有持久 Run 的生成物随会话保留，独立工具测试等无 Run 文件仍按 24 小时清理；下载链接保持 24 小时有效期。bash 执行前，按工作空间、应用、访问来源、consumer、执行用户和会话筛选文件，将此前成功轮次（及本轮已导出文件）的最新版本恢复到 `/workspace/outputs/`，保留子目录；旧数据没有路径时使用文件名。每个路径在单个沙箱内只恢复一次，不覆盖本轮编辑，沙箱重建后重新恢复已保存版本。每次修改导出新生成物，历史版本和链接不被替换；重新生成已取代的历史轮次和失败轮次不作为后续编辑来源。删除会话或应用时在同一事务内删除对应文件，工作空间删除沿用级联清理。沙箱仍在每轮结束后销毁，不跨用户共享，也不提供多人共同编辑。
- Run 内 stdio 注册各用独立宿主沙箱，桥接进程只启动一次服务并通过控制面代理暴露 Streamable HTTP。应用认证使用专用 X-NexaFlow-MCP-Token 头，控制面密钥被代理剥离；连接池按 Run 复用，关闭/60 秒空闲会销毁宿主。发现与非 Run 调用继续使用一次性沙箱。公开/API 消费方最多同时占两台，主 Run 和 stdio 宿主都计数；SDK 预热池默认关闭，启用时扣减按需容量。
- 运行中的后续任务通过各来源 `POST runs/{run_id}/inputs` 追加到既有事件表，并只在当前任务产生普通答案后继续执行；`input_id` 幂等、最大 32 条/每条 4000 字符，消费 ID 随 checkpoint 保存。输入与成功终态共用 RunState 行锁，已接受但未消费的任务阻止成功收尾；失败/取消仍保留可读任务。它们不会重置整次执行预算或解除工具审批。Console 与公开聊天在运行中按回车发送后续任务，API Key 使用同一输入接口。
- 执行中的消息也在每轮前检查窗口；旧消息可摘要，系统协议和最近工具消息组保持完整。若当前交互或工具 schema 已无法容纳，则显式报错，原始 durable 记录不删除；这与历史轮次准备阶段的最佳努力摘要是两个不同边界。不是无限上下文，也没有引入 pi 的树形分支或用户扩展安装。
- 历史成功 Run 以真实 `user`/`assistant` 角色恢复。上下文在保守 token 预算内直接复用；超预算时用当前注册模型压缩较旧轮次，摘要持久化在最后被覆盖的成功 Run 上，同时保留最近 6 轮。摘要调用失败时回退到截断历史，不阻断当前问题，原始 Run 记录始终保留。
- `model_usage` 累加 Agent loop 与摘要调用的实际供应商用量，并单列 compaction、cache read/create 与未上报调用数。系统不会为未返回 usage 的供应商猜测计费 token；服务端 prompt cache 的写法仍由各供应商 SDK 决定，不伪造跨供应商通用的 `cache_control`。
- Run 创建时冻结整次执行时长、模型轮次和工具调用次数三项生效执行预算；`max_knowledge_calls`/`max_knowledge_rounds`/`max_model_tokens` 继续写入快照以兼容历史 Run，但自适应检索与 Agent 执行已不再用它们作为硬门禁。总截止时间只在第一次成功 claim 时写入，worker 重试、租约接管和 checkpoint 恢复不会刷新；人工审批或输入等待时间会显式加回截止时间。每次工具调用仍有独立硬超时，达到最后一轮时不再向模型暴露工具。工具预算耗尽时，所有能力一致撤下工具 schema，允许模型用已有结果完成答案；超预算批次在执行前整批拒绝并返回失败工具结果，随后撤下工具让模型用已有信息收尾，而不是令整个 Run 失败。模型供应商的上下文窗口和单次输出限制仍然生效。
- HTTP 只提交/观察 Run；Celery Agent worker（`backend/scripts/worker.py --role=agents`，线程池中的所有 Run 共享进程内同一个事件循环；任务入口 `app/tasks/agents/jobs.py`，经 `app/application/runs/dispatch.py` 派发到 `app/application/agents/runs/executor.py`）用数据库租约执行，节点 checkpoint、过程事件游标和工具账本均持久化。答案与推理 delta 不写 PostgreSQL，而是进入按 Run 隔离、限长并带 15 分钟 TTL 的 Redis Stream；API 把 Redis 增量与数据库事件合并为同一 NDJSON。客户端分别用 `after` 和 `live_after` 恢复持久与实时游标，终态数据库快照负责最终校正；Redis 不可用时自动降级为过程事件加完整终态答案。断开 NDJSON 不会取消 Run。
- Run 持久层按职责拆分：`agent_runs` 只保存身份、调用者、谱系、反馈和 trace；`agent_run_states` 保存状态、租约、总截止时间、checkpoint、结果与模型用量；`agent_run_snapshots` 保存创建时冻结的执行配置、预算字段（三项生效 + 三项兼容）、非敏感模型配置指纹和知识资源信息；`agent_run_events` 只追加事件。版本化 Run 若检测到模型端点、凭据版本或请求参数漂移，以及知识权限被撤销，会在执行前失败关闭。所有 Agent/Workflow/测试工具执行统一写入 `tool_invocations`，不再维护第二套工具调用账本。
- 发布前真实质量门禁使用 `backend/scripts/agent_eval.py` 调用现有工作区 Run API，按答案、工具、来源数量、token、模型调用数和延迟断言；数据集与运行说明见 `docs/AGENT_EVALUATION.md`。报告不保存问题、答案、证据正文或令牌。
- Agent 草稿保存稳定的 `ToolRef(tool_id, version_id)`；发布版本和 Run 再冻结完整 ToolSnapshot。Tool/Source 禁用、授权撤销、成员失效或策略漂移会在 dispatch 前 fail closed，不静默换到新版本。
- 新发现的 MCP 工具默认逐次审批；只有管理员按当前定义哈希显式设置为 `read_only` 才会自动运行，远端 `readOnlyHint` 等注解不会单独改变审批策略。管理员可按当前定义哈希设置为只读、审批或禁用，工具定义变化后已有策略回落到逐次审批。副作用调用携带稳定幂等键；传输超时、worker 在外部调用后崩溃或结果未落账时标记 `uncertain`，禁止自动重试，只能人工确认后"不重试并继续"。远端 MCP 若不兑现幂等键，系统提供的是保守恢复而非跨系统 exactly-once。
- 发布和 API 凭据写操作仅工作空间管理员可执行。发布固化当时的模型、知识库和 ToolSnapshot；后续草稿变化不撤销既有发布，公开/API 继续运行上一发布版本，直到重新发布、取消发布或停用应用。外部运行使用发布者快照身份受审计，但不冒充访问者；仅允许仍有效、无需逐次审批的只读工具，不开放外部审批路径。
- 公开访客 Cookie 和 API Key 都使用高熵随机值，数据库只保存 SHA-256 派生标识或密钥哈希。外部提交同时受 Agent 总量桶和来源主体桶限流；Redis 不可用时成本型请求失败关闭，不先排队后补跑。
- 公开/API Key Run 复用内部 durable 事件链，HTTP 契约只投影固定枚举的分析、知识检索、工具调用、回答生成状态、知识片段数量与模型思考过程（`reasoning_delta` 增量及 progress 上的累积文本）；工具名称/参数、检索原文、System Prompt 和 trace 不离开内部边界。

- 退役字段：数据库及 Run API 的 `grounding_status` / `grounding_meta` 尚未做删列迁移，新运行固定为 `skipped` / `{}`，不显示或投影核验事件。Skill 升级 schema-v2，拒绝旧 retrieval/stop/evaluation/budgets；旧测试包重新创建，不保留全局预算钳制。知识/工具引用仍受授权与审批；脚本只允许绑定版本的 .py/.js，执行镜像/网络指纹随 Run 冻结。可执行 Skills 通过 `install_skill_dependencies`（隐式绑定，`application/agent_skills/dependencies.py`，含 egress 域名校验与 OpenSandbox 执行）与 `run_skill_script` 参与同一 ledger；内置 `generate_image` 工具按调用冻结 image 模型资源快照并写入 artifact store；Agent 可在设置页选定一个生图模型（`agents.image_model_id`，冻结进运行配置快照，重试不会静默换模型），未选定或非 Agent 调用（Workflow/测试工具）回退到工作空间唯一启用的生图模型；工具接受可选的 `filename`（模型依据用户原话起名，缺省用提示词首个分句），由 `domain/artifacts/services.py::artifact_filename_from_label` 清洗与截断，下载文件名与聊天展示都用它。内置工具定义变更（例如新增参数）通过一次性 Alembic 数据迁移前滚已有工作区：新版本按定义哈希生成，迁移同时把 `tools.current_version_id` 与 policy 的 `tool_version_id`/`definition_hash` 指向它，已绑定旧版本的 Agent 继续执行其固定版本。
