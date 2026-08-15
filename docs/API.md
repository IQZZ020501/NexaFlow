# API 模块（backend/app/api + schemas）

## 职责

FastAPI 薄路由层：只做参数解析、认证/授权依赖与响应组装，业务逻辑下沉到 `application`/`shareddomain`。所有路由挂在 `/api/v1` 前缀；认证与工作空间上下文依赖集中在 `api/deps.py`。Pydantic 请求/响应契约集中在 `schemas/`。

## 分层关系

```text
HTTP → api/deps.py（Bearer 校验、WorkspaceContext、角色守卫）
     → endpoints/*（路由 + 权限依赖 + 响应组装）
     → application / shareddomain 服务
     → schemas/（请求/响应模型）
```

## 接口约定（速查）

- 工作空间上下文：路径参数 `/workspaces/{workspace_id}/...`，非成员 403，工作空间非 active 403。
- 状态码：创建 201、删除 204、异步任务 202；错误统一 FastAPI `{"detail": ...}`。
- 分页：所有列表端点统一 `limit`（`ge=1 le=200`，默认 100）+ `offset`（`ge=0`）查询参数。
- 鉴权：`/auth/login|refresh|logout`、`/health` 与已发布 Agent 的 `/public/agents/{agent_id}/*` 不要求登录；公开 Agent 会话使用 HttpOnly 访客 Cookie 隔离。`/agent-api/{agent_id}/*` 使用 Agent 级 API Key Bearer 鉴权，其中 `/documentation` 用于校验 Key 并解锁该 Agent 的专属文档页；其余接口使用登录 Bearer，且需完成初始改密（`require_password_changed`）。
- API 文档：后端 `/docs` 与 `/openapi.json` 始终保留完整 FastAPI 文档，覆盖登录态管理、公开访问和 Agent API 全部接口。Agent 概览的“API 文档”入口跳转到 `/agent-api/{agent_id}/docs`，输入该 Agent 的有效 API Key 后只展示该 Agent 的 Run 创建、查询和流式订阅接口。
- 流式：登录态 Agent 先 `POST /runs` 持久提交，再 `GET /runs/{run_id}/stream?after={sequence}&live_after={redis_stream_id}` 订阅 NDJSON。`after` 重放 PostgreSQL 过程/终态事件，`live_after` 补发短期 Redis 答案/推理增量；实时事件的 `stream_epoch` 变化表示新 worker 已接管，客户端必须清空已累积的答案和推理后重新累积。公开/API Key 流复用同一 durable Run，只输出固定枚举的安全进度摘要、知识片段数量、答案增量、模型思考过程（`reasoning_delta` 增量与 progress 累积文本）和终态白名单，不返回工具名称/参数、检索原文、System Prompt 或 trace。终态 Run 快照始终覆盖实时片段，断线不取消 Run。请求中的旧 `preview` 字段仅为兼容保留并被忽略，所有 Run 都是持久执行。所有 `/api` 响应默认 `no-store`。
- 全局管理员仅限 `/admin/*` 与工作空间生命周期管理。

## 文件清单

### app/api/

- `backend/app/api/deps.py` — 认证与授权依赖：Bearer token 解析、当前用户、全局管理员、工作空间上下文（`WorkspaceContext`）与路径角色守卫
- `backend/app/api/v1/api.py` — 汇总所有子路由为 `/api/v1` 前缀并挂载 `/admin` 子路由的聚合入口

### app/api/v1/endpoints/

- `backend/app/api/v1/endpoints/auth.py` — `/auth`：登录/刷新/登出/改密/当前用户（`/me`），refresh token 走 HttpOnly Cookie
- `backend/app/api/v1/endpoints/workspaces.py` — `/workspaces`：工作区 CRUD、成员管理、成员用户创建、工作区审计日志
- `backend/app/api/v1/endpoints/teams.py` — `/workspaces/{workspace_id}/teams`：团队 CRUD（admin 角色限定）
- `backend/app/api/v1/endpoints/knowledge.py` — `/workspaces/{workspace_id}/knowledge-bases` 主接口族：知识库 CRUD、普通文档/QA 表上传、分块/解析/索引、任务列表与重试、重建索引、模型测试、资源权限管理；文档创建通过 `import_mode=document|qa` 显式选择导入语义
- `backend/app/api/v1/endpoints/knowledge_legacy.py` — 同前缀兼容接口族：文档拆分预览 `POST /documents/split`、批量创建 `POST /documents/batch-create`
- `backend/app/api/v1/endpoints/knowledge_lifecycle.py` — 同前缀文档生命周期：下载、删除、激活状态更新（PATCH）
- `backend/app/api/v1/endpoints/knowledge_retrieval.py` — 同前缀 RAG 检索接口：兼容结果列表 `POST /{kb_id}/query` 与带生产链路 trace 的 `POST /{kb_id}/query/inspect`
- `backend/app/api/v1/endpoints/knowledge_evaluation.py` — 同前缀 `/evaluations`：评测用例 CRUD、异步运行、运行列表/详情、指定运行与最近运行指标汇总；读取要求 view/edit，写入要求 edit
- `backend/app/api/v1/endpoints/models.py` — 供应商目录接口（`/model-providers` 系列）与 `/workspaces/{workspace_id}/models` 已注册模型 CRUD
- `backend/app/api/v1/endpoints/mcp_servers.py` — MCP Server CRUD/刷新，以及管理员按工具定义哈希审核执行策略；创建请求用 `transport` 区分 `streamable_http`/`sse`（URL + 可选 Bearer）与 `stdio`（命令、参数、工作目录和环境变量）
- `backend/app/api/v1/endpoints/agents.py` — Agent CRUD、发布、API 凭据、跨来源对话日志/用户/统计，以及登录态 Run 提交、工具账本、审批/拒绝与游标 NDJSON 订阅
- `backend/app/api/v1/endpoints/agent_access.py` — `/public/agents/{agent_id}` 提供已发布 Agent 的公开资料、访客会话、对话历史和安全 Run 流；`/agent-api/{agent_id}` 提供 Agent API Key 校验、专属文档解锁、Run 提交、查询和安全流

### app/api/v1/admin/

- `backend/app/api/v1/admin/users.py` — `/admin/users`：全局用户管理（列表/创建/更新/重置密码/删除，仅全局管理员）
- `backend/app/api/v1/admin/audit.py` — `/admin/audit-logs`：全局审计日志分页列表（仅全局管理员）

### app/schemas/（Pydantic 契约）

- `backend/app/schemas/user.py` — 登录/Token/改密/用户信息/成员关系模型（含密码强度校验）
- `backend/app/schemas/workspace.py` — 工作区及其成员、管理员创建请求的请求/响应模型
- `backend/app/schemas/team.py` — 团队创建/更新/响应模型
- `backend/app/schemas/knowledge.py` — 知识库、文档、QA 导入模式、分块、解析参数、任务、批量创建、检索命中/trace 与检索评测请求/响应模型
- `backend/app/schemas/agent.py` — Agent 创建/更新/响应与运行/计划/事件/流式响应模型
- `backend/app/schemas/model.py` — LLM 供应商目录（model-types/base-models/credential-form）与已注册模型模型
- `backend/app/schemas/mcp.py` — MCP Server、三种传输互斥配置、stdio 配置与工具列表的请求/响应模型
- `backend/app/schemas/audit.py` — 审计日志响应模型
