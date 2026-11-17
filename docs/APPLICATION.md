# APPLICATION 模块（backend/app/application）

## 职责

应用服务层：HTTP 层与领域层之间的编排与业务规则。负责跨模块流程（登录签发、运行编排、工具调用、知识检索）与规则校验（最后一名管理员、角色约束、运行配额）；审计编排由各用例服务在事务内调用（`record_audit_log` 实现位于领域层审计服务），查询型审计用例集中在 `app/application/audit`。

按**功能域**组织为特性包（agents / workflows / knowledge / tools / identity / workspaces / teams / models / resource_folders / governance / audit / analytics / artifacts / email / runs / agent_skills / announcements / projects / publications / uploads），各特性的用例文件放 `service.py`，任务型/执行型逻辑放独立模块（`executor.py`、`runner.py`）；后台执行器组合与派发位于 `app/bootstrap/`。公开接口、依赖声明与边界检查见 [MODULAR_MONOLITH.md](MODULAR_MONOLITH.md)。

## 分层关系

```text
api/v1/<feature>/routes → application（编排/规则/审计）→ domain + ports
```

依赖方向不变：API 路由只面向 application 用例；application 编排领域服务并经由 `app/ports/*` 的稳定契约调用能力实现（LLM/MCP/向量库/执行/企业身份/公告的实现位于 `app/adapters`；统一 Tool 契约位于 `app/ports/tools.py`，provider 适配器仍收在 `tools/runtime/adapters/`，模型能力层 `models/registry.py` 也直接组合 `app/adapters/llm`）；跨对象事务通过 db unit of work 协调（会话与仓储，见 `app/infra/db`）；入参/出参 DTO 与校验集中在 `app/schemas/<feature>`。

门面说明：

- `agents/__init__.py` 是 Agent 用例门面（稳定入口，API 层直接 import）；
- workflows 不再保留门面包：其公开用例由 `workflows/definitions/service.py` 承载（定义/版本），运行和外部访问分别落在各自的 `service.py`，共用上传归 `uploads/service.py`；
- `tools/__init__.py`、`teams/__init__.py`、`audit/__init__.py`、`analytics/__init__.py` 是轻量门面，直接重导出对应领域用例；
- `agent_skills/__init__.py` 是 Agent Skill 用例门面（显式重导出 `service.py` 的公开用例），`announcements/__init__.py` 是公告与消息用例门面。

## 目录总览

```text
app/application/
├── agents/                 # Agent 用例（门面 + 子包）
│   ├── __init__.py         # 门面：重导出 CRUD/Run/访问/工具/提示词用例
│   ├── integration.py      # Workflow 使用的 Agent 能力接口
│   ├── prompts.py
│   ├── runs/{service,executor,children,memory,snapshots,session}.py
│   ├── access/service.py
│   └── tools/{builder,runtime}.py
├── workflows/              # Workflow 用例（公开用例面在 definitions/service）
│   ├── definitions/service.py
│   ├── access/service.py
│   ├── runs/{service,executor}.py
│   ├── nodes/executor.py
│   └── tools/runtime.py
├── knowledge/              # 知识库用例
│   ├── documents/service.py
│   ├── retrieval/service.py
│   └── evaluation/runner.py
├── tools/                  # 统一工具用例
│   ├── __init__.py         # 门面
│   ├── management/service.py
│   └── runtime/
│       ├── service.py
│       └── adapters/{__init__,builtin,mcp,image_generation,shell,_common}.py
├── identity/               # 身份用例
│   └── {service,sessions,invitations,password_reset,enterprise}.py
├── agent_skills/           # Agent Skill 用例（门面 + 服务/依赖/执行/脚本/包解析）
│   └── {service,dependencies,execution,scripts,packages}.py
├── announcements/{__init__,service,live}.py
├── workspaces/service.py
├── teams/__init__.py
├── models/{service,registry}.py
├── resource_folders/service.py
├── governance/service.py
├── audit/{__init__,system_logs}.py
├── analytics/__init__.py
├── artifacts/{service,workspace}.py
├── projects/{service,runtime}.py
├── publications/service.py
├── uploads/service.py
├── email/{delivery,smtp}.py
└── runs/{lifecycle,feedback,leases}.py
```

## 模块说明

### agents/

- `agents/__init__.py` — Agent 用例门面：重导出 Agent CRUD、Run 编排、外部访问、工具构建与提示词用例，以及 Agent 权限用例（`list_agent_permissions`/`upsert_agent_permission`/`revoke_agent_permission`/`require_agent_edit`，来自 `app.domain.agents.access.permissions`），保持 API 层入口稳定（沿用旧 `agents.py` 的职责；同时透出共用上传服务）。
- `agents/integration.py` — Workflow 调用 Agent 的公开能力面：固定子运行、预检、工具构建与结果映射，内部实现仍由 Agent 模块拥有。
- `agents/prompts.py` — AI 辅助的 Agent 指令（system prompt）生成。
- `agents/runs/service.py` — Agent Run 编排：登录态运行的准备、执行、流式与列表；含提交入队、按来源主体查询、工具审批与可重放事件订阅。
- `agents/runs/executor.py` — Durable Executor：短事务装载、租约心跳/接管、节点 checkpoint、工具账本与 Redis 实时 delta 发布。
- `agents/runs/children.py` — Workflow Agent 节点的固定发布版本、durable child Run 的创建/恢复/取消编排。
- `agents/runs/memory.py` — Agent 对话记忆：按会话恢复角色消息，并在模型上下文预算内压缩旧轮次、持久化摘要。
- `agents/runs/session.py` — Run 来源主体授权后的持久后续任务追加；复用事件表与 RunState 终态锁，harness 消费状态进入 checkpoint。
- `agents/runs/snapshots.py` — Run 创建时冻结运行时长、模型轮次与工具调用预算、非敏感模型运行配置指纹和知识资源/可检索内容指纹，并提供执行前漂移校验；`max_knowledge_calls`/`max_knowledge_rounds`/`max_model_tokens` 仅作为历史快照兼容字段写入，不再作为硬门禁。
- `agents/access/service.py` — Agent 外部访问用例：发布资料、登录成员的公开会话（消费方标识为登录用户 id）、Agent 级 API Key 创建/轮换/撤销、公开/API 流安全投影（`sanitize_external_agent_stream`）与 Redis 成本限流；跨来源日志/用户/监控聚合。
- `agents/tools/builder.py` — 把已冻结的 `ToolSnapshot` 构造为模型可调用工具（知识检索工具、统一 Tool、MCP 工具），并提供 run→response 与来源引用的纯映射（`ToolRef → ToolSnapshot` 解析已下沉到领域层 `app/domain/tools/access/bindings.py`）。
- `agents/tools/runtime.py` — Agent 侧对接统一 durable Tool Runtime 的薄桥接：幂等身份、审批状态与结果映射。

### workflows/

- `workflows/definitions/service.py` — Workflow 定义/版本用例（草稿 CRUD、图校验、版本响应）；承载 workflows 的公开用例面，取代旧 `workflows.py` 门面的定义与版本部分。
- `workflows/runs/service.py` — Workflow 运行用例：草稿/发布运行创建、资源快照、Tool/Agent 预检、事件订阅与表单恢复。
- `workflows/runs/executor.py` — 图级确定性执行：租约/checkpoint、durable child Run 与终态编排。
- `workflows/nodes/executor.py` — 单节点执行器：节点作用域（Jinja 沙箱渲染、LLM 工具循环、直接 Tool 节点）与节点产物组装。
- `workflows/tools/runtime.py` — `WorkflowToolRuntime`：直接 Tool 节点与 LLM Tool 循环共用的 canonical `ToolInvocation` 适配。
- `workflows/access/service.py` — 已发布 Workflow 的公开/API Key 资料、会话、Run 与安全流投影。

### knowledge/

- `knowledge/documents/service.py` — 知识库/文档 API 的入口（规则：API 不得直达 domain/仓储）：知识库/文档 CRUD、文档生命周期与启停、附件与资产访问、任务派发。
- `knowledge/retrieval/service.py` — 统一检索编排（API、Agent、Workflow 共用）：分块、向量召回、重排、证据裁剪与相似度计算。
- `knowledge/evaluation/runner.py` — 检索评估 runner：执行评估任务（相似度/重排等指标）并汇总评估结果。

### tools/

- `tools/__init__.py` — 统一 Tool 用例门面：向 API 暴露目录、Source、授权与策略操作。
- `tools/management/service.py` — Tool/Source 管理用例：Tool/Source 查询、MCP Source 生命周期及 `view/use` 授权。
- `tools/runtime/service.py` — 跨 provider 的 durable Tool 执行：canonical `ToolInvocation` 预检、入队、租约执行、终态与 `uncertain` 处理。
- `app/ports/tools.py` — provider-neutral 执行契约：`ToolAdapter` Protocol、`ToolInvocationContext`、`ToolRuntimeResult`、`ToolAdapterBusy`。
- `tools/runtime/adapters/` — provider 分流实现：`__init__.build_tool_adapter` 按 tool kind 分发到 `BuiltinToolAdapter`、`McpToolAdapter`（内置含图片生成与 Skill 脚本等 spec）。

### identity/

- `identity/service.py` — 身份用例：登录认证、access/refresh token 签发、改密、用户 CRUD 与会话管理编排。
- `identity/sessions.py` — 登录会话用例：会话列表、按 token 定位，以及吊销（单个/全部/其他设备）。
- `identity/invitations.py` — 工作区邀请用例：创建/列表/撤销/删除/接受，含邮件投递状态。
- `identity/password_reset.py` — 匿名找回密码：请求与确认令牌的签发/校验。
- `identity/enterprise.py` — 企业身份（SSO）用例：连接（connection）增删改查、公开连接列表、身份绑定、登录发起与回调完成。

### 其余特性

- `workspaces/service.py` — 工作区应用服务：创建/更新/删除、成员增删改、成员角色校验与最后一名管理员规则；`build_workspace_context` 供 Agent/Workflow 运行构建上下文。
- `teams/__init__.py` — 团队用例门面：团队 CRUD、成员与角色管理。
- `models/service.py` — 模型注册表用例：模型管理流程的校验编排、审计记录与 DTO 组装（能力层实现见下）。
- `models/registry.py` — 模型能力层：凭据加解密与校验、provider 目录探测、注册模型管理辅助（供 `service.py` 与注册 API 使用）；该层不依赖审计与 schema，但仍依赖 `app/domain/models/registered.py` 的 ORM 模型与 `app/adapters/llm`。
- `resource_folders/service.py` — 资源文件夹用例：创建/移动/批量移动/删除/查询。
- `governance/service.py` — 治理用例：工作区治理设置读写、工作区库存清单、管理员健康探测（DB/Redis/向量库/存储/Celery worker）与运行配额执行。
- `audit/__init__.py` — 审计日志查询用例门面：列表/计数/工作区范围审计查询。
- `audit/system_logs.py` — 系统日志用例：带敏感字段脱敏的分页查询（`SystemLog`）。
- `analytics/__init__.py` — 工作区分析用例门面（`get_workspace_analytics`）。
- `artifacts/service.py` — 生成物用例：创建/下载链接签发与校验、过期清理。
- `projects/service.py`、`projects/runtime.py` — 创建者私有项目、不可变文件版本、Run 绑定与工作树恢复/保存，详见 [项目文件](PROJECT_FILES.md)。
- `email/delivery.py` — 事务邮件：入队（含身份类邮件）、due 投递扫描、按租约投递与终态处理、来源撤销。
- `email/smtp.py` — SMTP 设置用例：读写（密码密文存储）、连通性测试、transport 配置构建。
- `agent_skills/service.py` — Agent Skill 用例：技能包 CRUD、版本与发布、应用绑定同步与 `view/use` 授权。
- `agent_skills/dependencies.py` — Skill 依赖安装：固定版本 PyPI/npm 需求解析、安装计划、出口域名校验与执行。
- `agent_skills/execution.py`、`agent_skills/scripts.py`、`agent_skills/packages.py` — 运行期 Skill 授权加载、脚本执行与导入检查。
- `announcements/service.py` — 公告用例：全局/工作空间公告 CRUD、发布/归档/删除、按用户的消息已读状态与审计（`announcement.*`）。
- `announcements/live.py` — 消息 SSE 流：订阅者更新推送与工作空间访问校验（经 `app/ports/announcements.py` + `app/adapters/announcements/live_stream.py`）。
- `runs/lifecycle.py` — 共享 Run 生命周期用例：取消 run 树并结算工具调用（Agent 与 Workflow 共用）。
- `runs/feedback.py` — 共享 Run 反馈用例：终态 Run 的反馈写入与清除。
- `runs/leases.py` — Agent / Workflow 共用的持久运行租约心跳。
- `publications/service.py` — 共享发布上下文、发布者有效性与工作空间成员校验，供 Agent、Workflow 与生成物下载使用。
- `uploads/service.py` — Agent / Workflow 共用的临时附件校验、存储、文本解析与访问令牌；持久清理位于 `app/domain/uploads/service.py`。
- `app/bootstrap/runs.py` — Worker 组合入口，按 generation 和 Run 类型选择 durable 执行器；用例通过 `app/ports/runs.py` 入队，保持队列与 eager 行为。
