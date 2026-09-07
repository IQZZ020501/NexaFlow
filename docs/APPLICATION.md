# APPLICATION 模块（backend/app/application）

## 职责

应用服务层：HTTP 层与领域层之间的编排与业务规则。负责跨模块流程（登录签发、运行编排、工具调用、知识检索）与规则校验（最后一名管理员、角色约束、运行配额）；审计编排由各用例服务在事务内调用（`record_audit_log` 实现位于领域层审计服务），查询型审计用例集中在 `app/application/audit`。

重构后按**功能域**组织为特性包（agents / workflows / knowledge / tools / identity / workspaces / teams / models / resource_folders / governance / audit / analytics / artifacts / email / runs），不再按单文件平铺；各特性的用例文件放 `service.py`，任务型/执行型逻辑放独立模块（`executor.py`、`runner.py`、`dispatch.py`）。

## 分层关系

```text
api/v1/<feature>/routes → application（编排/规则/审计）→ domain + ports
```

依赖方向不变：API 路由只面向 application 用例；application 编排领域服务并经由 `app/ports/*` 的稳定契约调用能力实现（实现位于 `app/adapters`）；跨对象事务通过 db unit of work 协调（会话与仓储，见 `app/infra/db`）；入参/出参 DTO 与校验集中在 `app/schemas/<feature>`。

门面说明：

- `agents/__init__.py` 是 Agent 用例门面（稳定入口，API 层直接 import）；
- workflows 不再保留门面包：其公开用例由 `workflows/definitions/service.py` 承载（定义/版本），运行、外部访问、上传分别落在各自的 `service.py`；
- `tools/__init__.py`、`teams/__init__.py`、`audit/__init__.py`、`analytics/__init__.py` 是轻量门面，直接重导出对应领域用例。

## 目录总览

```text
app/application/
├── agents/                 # Agent 用例（门面 + 子包）
│   ├── __init__.py         # 门面：重导出 CRUD/Run/访问/工具/提示词用例
│   ├── prompts.py
│   ├── runs/{service,executor,children,memory,grounding}.py
│   ├── access/service.py
│   └── tools/{builder,runtime}.py
├── workflows/              # Workflow 用例（公开用例面在 definitions/service）
│   ├── definitions/service.py
│   ├── access/service.py
│   ├── runs/{service,executor}.py
│   ├── nodes/executor.py
│   ├── tools/runtime.py
│   └── uploads/service.py
├── knowledge/              # 知识库用例
│   ├── documents/service.py
│   ├── retrieval/service.py
│   ├── evaluation/runner.py
│   └── graph/{service,build,query,maintenance}.py
├── tools/                  # 统一工具用例
│   ├── __init__.py         # 门面
│   ├── management/service.py
│   └── runtime/service.py
├── identity/               # 身份用例
│   └── {service,sessions,invitations,password_reset,enterprise}.py
├── workspaces/service.py
├── teams/__init__.py
├── models/{service,registry}.py
├── resource_folders/service.py
├── governance/service.py
├── audit/{__init__,system_logs}.py
├── analytics/__init__.py
├── artifacts/service.py
├── email/{delivery,smtp}.py
└── runs/dispatch.py
```

## 模块说明

### agents/

- `agents/__init__.py` — Agent 用例门面：重导出 Agent CRUD、Run 编排、外部访问、工具构建与提示词用例，保持 API 层入口稳定（沿用旧 `agents.py` 的职责；同时透出 workflow 上传服务供 Agent 侧复用）。
- `agents/prompts.py` — AI 辅助的 Agent 指令（system prompt）生成。
- `agents/runs/service.py` — Agent Run 编排：登录态运行的准备、执行、流式与列表；含提交入队、按来源主体查询、工具审批与可重放事件订阅（对应旧 `agent_runs.py`）。
- `agents/runs/executor.py` — Durable Executor：短事务装载、租约心跳/接管、节点 checkpoint、工具账本与 Redis 实时 delta 发布（对应旧 `agent_executor.py`）。
- `agents/runs/children.py` — Workflow Agent 节点的固定发布版本、durable child Run 的创建/恢复/取消编排（对应旧 `agent_child_runs.py`）。
- `agents/runs/memory.py` — Agent 对话记忆：按会话恢复角色消息，并在模型上下文预算内压缩旧轮次、持久化摘要（对应旧 `agent_memory.py`）。
- `agents/runs/grounding.py` — 知识支撑的草稿后置 grounding：有界地生成候选问题、检索并修订草稿。
- `agents/access/service.py` — Agent 外部访问用例：发布资料、HttpOnly 访客会话、Agent 级 API Key 创建/轮换/撤销、公开/API 流安全投影（`sanitize_external_agent_stream`）与 Redis 成本限流；跨来源日志/用户/监控聚合（对应旧 `agent_access.py`）。
- `agents/tools/builder.py` — 把 Agent 固定 `ToolRef` 解析为 `ToolSnapshot`，构造模型可调用工具，并提供 run→response 纯映射（对应旧 `agent_tools.py`）。
- `agents/tools/runtime.py` — Agent 侧对接统一 durable Tool Runtime 的薄桥接：幂等身份、审批状态与结果映射（对应旧 `agent_tool_runtime.py`）。

### workflows/

- `workflows/definitions/service.py` — Workflow 定义/版本用例（草稿 CRUD、图校验、版本响应）；承载 workflows 的公开用例面，取代旧 `workflows.py` 门面的定义与版本部分。
- `workflows/runs/service.py` — Workflow 运行用例：草稿/发布运行创建、资源快照、Tool/Agent 预检、事件订阅与表单恢复（对应旧 `workflow_runs.py`）。
- `workflows/runs/executor.py` — 图级确定性执行：租约/checkpoint、durable child Run 与终态编排（旧 `workflow_executor.py` 的图执行部分）。
- `workflows/nodes/executor.py` — 单节点执行器：节点作用域（Jinja 沙箱渲染、LLM 工具循环、直接 Tool 节点）与节点级审计（旧 `workflow_executor.py` 的节点执行部分）。
- `workflows/tools/runtime.py` — `WorkflowToolRuntime`：直接 Tool 节点与 LLM Tool 循环共用的 canonical `ToolInvocation` 适配（对应旧 `workflow_tool_runtime.py`）。
- `workflows/access/service.py` — 已发布 Workflow 的公开/API Key 资料、会话、Run 与安全流投影（对应旧 `workflow_access.py`）。
- `workflows/uploads/service.py` — Workflow 附件上传：文件校验/存储、工作区文件解析与访问令牌（对应旧 `workflow_uploads.py`）。

### knowledge/

- `knowledge/documents/service.py` — 知识库用例门面（knowledge API 的唯一入口，禁止 API 直达下层）：知识库/文档 CRUD、文档生命周期与启停、任务派发、对象文件访问。
- `knowledge/retrieval/service.py` — 统一检索编排（API、Agent、Workflow 共用）：分块、向量召回、重排、证据裁剪与相似度计算。
- `knowledge/graph/service.py` — 图谱用例编排：图设置/schema/状态、实体与 Claim 查询与详情、评审流、重建触发与任务派发（细粒度查询与维护见 query/maintenance）。
- `knowledge/graph/query.py` — 图谱查询执行：查询意图规划、实体消歧/链接、邻域/路径遍历与多路融合排序。
- `knowledge/graph/build.py` — 图谱构建流水线：抽取批次暂存、实体/Claim 抽取与消解、版本（revision）与来源版本追踪。
- `knowledge/graph/maintenance.py` — 图谱维护：到期任务扫描与入队、孤立 revision 恢复、pending profile 修补、图谱对账。
- `knowledge/evaluation/runner.py` — 检索评估 runner：执行评估任务（相似度/重排等指标）并汇总评估结果。

### tools/

- `tools/__init__.py` — 统一 Tool 用例门面（对应旧 `tools.py`）：向 API 暴露目录、Source、Python 生命周期、授权与策略操作。
- `tools/management/service.py` — Tool/Source 管理用例：Tool/Source 查询、Python 草稿/测试/发布/启停/归档、MCP Source 生命周期及 `view/use` 授权（对应旧 `tool_management.py`）。
- `tools/runtime/service.py` — 跨 provider 的 durable Tool 执行：canonical `ToolInvocation` 预检、入队、租约执行、终态与 `uncertain` 处理（对应旧 `tool_runtime.py`；provider 分流经 `app/ports/tool_runtime` 契约 + `app/adapters/tools/runtime.build_tool_adapter`，见下）。

### identity/

- `identity/service.py` — 身份用例：登录认证、access/refresh token 签发、改密、用户 CRUD 与会话管理编排（对应旧 `identity.py`）。
- `identity/sessions.py` — 登录会话用例：会话列表、按 token 定位，以及吊销（单个/全部/其他设备）。
- `identity/invitations.py` — 工作区邀请用例：创建/列表/撤销/删除/接受，含邮件投递状态。
- `identity/password_reset.py` — 匿名找回密码：请求与确认令牌的签发/校验。
- `identity/enterprise.py` — 企业身份（SSO）用例：连接（connection）增删改查、公开连接列表、身份绑定、登录发起与回调完成。

### 其余特性

- `workspaces/service.py` — 工作区应用服务：创建/更新/删除、成员增删改、成员角色校验与最后一名管理员规则；`build_workspace_context` 供 Agent/Workflow 运行构建上下文（对应旧 `workspace.py`）。
- `teams/__init__.py` — 团队用例门面：团队 CRUD、成员与角色管理。
- `models/service.py` — 模型注册表用例：模型管理流程的校验编排、审计记录与 DTO 组装；能力层本身不依赖业务域/审计/schema。
- `models/registry.py` — 模型能力层：凭据加解密与校验、provider 目录探测、注册模型管理辅助（供 `service.py` 与注册 API 使用）。
- `resource_folders/service.py` — 资源文件夹用例：创建/移动/批量移动/删除/查询。
- `governance/service.py` — 治理用例：工作区治理设置读写、工作区库存清单、管理员健康探测（DB/Redis/向量库/存储/Celery worker）与运行配额执行。
- `audit/__init__.py` — 审计日志查询用例门面：列表/计数/工作区范围审计查询。
- `audit/system_logs.py` — 系统日志用例：带敏感字段脱敏的分页查询（`SystemLog`）。
- `analytics/__init__.py` — 工作区分析用例门面（`get_workspace_analytics`）。
- `artifacts/service.py` — 生成物用例：创建/下载链接签发与校验、过期清理。
- `email/delivery.py` — 事务邮件：入队（含身份类邮件）、due 投递扫描、按租约投递与终态处理、来源撤销。
- `email/smtp.py` — SMTP 设置用例：读写（密码密文存储）、连通性测试、transport 配置构建。
- `runs/dispatch.py` — 后台任务入口：按 generation（legacy/unified）把持久化 run 分发给 Agent/Workflow durable 执行器，供 worker 任务调用。

## 旧文件迁移映射（重构前单文件 → 现树）

| 旧路径（已删除） | 新位置 |
| --- | --- |
| `app/application/identity.py` | `identity/service.py`（登录/令牌/改密/用户 CRUD）；会话与找回密码、SSO 分别见 `identity/{sessions,password_reset,enterprise}.py` |
| `app/application/workspace.py` | `workspaces/service.py`；工作区邀请见 `identity/invitations.py` |
| `app/application/agents.py` | `agents/__init__.py`（门面，表面保持稳定） |
| `app/application/agent_runs.py` | `agents/runs/service.py` |
| `app/application/agent_access.py` | `agents/access/service.py` |
| `app/application/agent_executor.py` | `agents/runs/executor.py` |
| `app/application/agent_tools.py` | `agents/tools/builder.py` |
| `app/application/agent_tool_runtime.py` | `agents/tools/runtime.py` |
| `app/application/agent_child_runs.py` | `agents/runs/children.py` |
| `app/application/agent_memory.py` | `agents/runs/memory.py` |
| `app/application/tools.py` | `tools/__init__.py`（门面，表面保持稳定） |
| `app/application/tool_management.py` | `tools/management/service.py` |
| `app/application/tool_runtime.py` | `tools/runtime/service.py` |
| `app/application/tool_adapters.py` | 无 application 层对应模块：builtin/Python/MCP 的 provider 分流边界下沉到 `app/adapters/tools/runtime.py`（`build_tool_adapter`），application 仅经 `app/ports/tool_runtime` 契约使用 |
| `app/application/workflows.py` | 门面取消：定义/版本公开用例由 `workflows/definitions/service.py` 承载；运行/访问/上传分别归位到对应 `service.py` |
| `app/application/workflow_runs.py` | `workflows/runs/service.py` |
| `app/application/workflow_executor.py` | 拆分为 `workflows/runs/executor.py`（图级执行/租约/终态）+ `workflows/nodes/executor.py`（单节点执行） |
| `app/application/workflow_tool_runtime.py` | `workflows/tools/runtime.py` |
| `app/application/workflow_access.py` | `workflows/access/service.py` |
| `app/application/workflow_uploads.py` | `workflows/uploads/service.py`（旧文档未列出但存在） |
| `app/application/knowledge*.py`（知识相关散件） | `knowledge/{documents,retrieval,evaluation,graph}/…` 按职责拆分 |
