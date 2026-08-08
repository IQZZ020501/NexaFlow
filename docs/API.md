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
- 鉴权：仅 `/auth/login|refresh|logout` 与 `/health` 公开；其余全部 Bearer，且需完成初始改密（`require_password_changed`）。
- 流式：Agent 先 `POST /runs` 持久提交，再 `GET /runs/{run_id}/stream?after={sequence}&live_after={redis_stream_id}` 订阅 NDJSON。`after` 重放 PostgreSQL 过程/终态事件，`live_after` 补发短期 Redis 答案/推理增量；实时事件的 `stream_epoch` 变化表示新 worker 已接管，客户端必须清空已累积的答案和推理后重新累积。终态 Run 快照始终覆盖实时片段。断线不取消 Run。请求中的旧 `preview` 字段仅为兼容保留并被忽略，所有 Run 都是持久执行。所有 `/api` 响应默认 `no-store`。
- 全局管理员仅限 `/admin/*` 与工作空间生命周期管理。

## 文件清单

### app/api/

- `backend/app/api/deps.py` — 认证与授权依赖：Bearer token 解析、当前用户、全局管理员、工作空间上下文（`WorkspaceContext`）与路径角色守卫
- `backend/app/api/v1/api.py` — 汇总所有子路由为 `/api/v1` 前缀并挂载 `/admin` 子路由的聚合入口

### app/api/v1/endpoints/

- `backend/app/api/v1/endpoints/auth.py` — `/auth`：登录/刷新/登出/改密/当前用户（`/me`），refresh token 走 HttpOnly Cookie
- `backend/app/api/v1/endpoints/workspaces.py` — `/workspaces`：工作区 CRUD、成员管理、成员用户创建、工作区审计日志
- `backend/app/api/v1/endpoints/teams.py` — `/workspaces/{workspace_id}/teams`：团队 CRUD（admin 角色限定）
- `backend/app/api/v1/endpoints/knowledge.py` — `/workspaces/{workspace_id}/knowledge-bases` 主接口族：知识库 CRUD、文档上传/分块/解析/索引、任务列表与重试、重建索引、模型测试、资源权限管理
- `backend/app/api/v1/endpoints/knowledge_legacy.py` — 同前缀兼容接口族：文档拆分预览 `POST /documents/split`、批量创建 `POST /documents/batch-create`
- `backend/app/api/v1/endpoints/knowledge_lifecycle.py` — 同前缀文档生命周期：下载、删除、激活状态更新（PATCH）
- `backend/app/api/v1/endpoints/knowledge_retrieval.py` — 同前缀 RAG 检索接口 `POST /{kb_id}/query`
- `backend/app/api/v1/endpoints/models.py` — 供应商目录接口（`/model-providers` 系列）与 `/workspaces/{workspace_id}/models` 已注册模型 CRUD
- `backend/app/api/v1/endpoints/mcp_servers.py` — MCP Server CRUD/刷新，以及管理员按工具定义哈希审核执行策略；创建请求用 `transport` 区分 `streamable_http`/`sse`（URL + 可选 Bearer）与 `stdio`（命令、参数、工作目录和环境变量）
- `backend/app/api/v1/endpoints/agents.py` — Agent CRUD、Run 提交/状态/工具账本、审批/拒绝与游标 NDJSON 订阅

### app/api/v1/admin/

- `backend/app/api/v1/admin/users.py` — `/admin/users`：全局用户管理（列表/创建/更新/重置密码/删除，仅全局管理员）
- `backend/app/api/v1/admin/audit.py` — `/admin/audit-logs`：全局审计日志分页列表（仅全局管理员）

### app/schemas/（Pydantic 契约）

- `backend/app/schemas/user.py` — 登录/Token/改密/用户信息/成员关系模型（含密码强度校验）
- `backend/app/schemas/workspace.py` — 工作区及其成员、管理员创建请求的请求/响应模型
- `backend/app/schemas/team.py` — 团队创建/更新/响应模型
- `backend/app/schemas/knowledge.py` — 知识库、文档、分块、解析参数、任务、批量创建、检索命中等请求/响应模型
- `backend/app/schemas/agent.py` — Agent 创建/更新/响应与运行/计划/事件/流式响应模型
- `backend/app/schemas/model.py` — LLM 供应商目录（model-types/base-models/credential-form）与已注册模型模型
- `backend/app/schemas/mcp.py` — MCP Server、三种传输互斥配置、stdio 配置与工具列表的请求/响应模型
- `backend/app/schemas/audit.py` — 审计日志响应模型
