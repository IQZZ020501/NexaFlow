# NexaFlow 模块文档索引

> 每个功能模块一份独立文档，说明模块职责、分层关系与文件清单。

## 架构总览

```text
backend/   FastAPI 后端（Python >=3.11，SQLAlchemy 异步 + Celery）
frontend/  Next.js 15 App Router + React 19 + TypeScript（Bun，shadcn/ui）
deploy/    Docker Compose 全栈编排、Dockerfile、Nginx 示例
```

后端调用链：`api`（薄路由）→ `application`（应用服务/业务规则）→ `shareddomain`（领域服务）与 `capabilities`（LLM 运行时/RAG/MCP/解析管道）→ `infrastructure`（配置/DB/安全/日志/repositories）。`domain/` 为共享 ORM 实体，`schemas/` 为 Pydantic 契约。所有核心资源表带 `workspace_id`，API 以 `/workspaces/{workspace_id}/...` 表达工作空间上下文。

前端：`app/` 路由薄壳委托 `components/` 页面组件（客户端渲染）；`contexts/` 全局状态（语言/主题/会话）；`lib/api/` 按域划分的 API 客户端统一走 `lib/api-client.ts`；`i18n/` 三语词典。

## 文档列表

| 文档 | 覆盖范围 |
| --- | --- |
| [API.md](API.md) | backend/app/api（HTTP 接口层）与 backend/app/schemas（Pydantic 契约） |
| [APPLICATION.md](APPLICATION.md) | backend/app/application（应用服务层） |
| [CAPABILITIES.md](CAPABILITIES.md) | backend/app/capabilities（LLM 运行时 / RAG / MCP 客户端 / 解析管道） |
| [KNOWLEDGE.md](KNOWLEDGE.md) | backend/app/shareddomain/knowledge + tasks（知识库领域与 Celery 任务） |
| [AGENTS_RUNTIME.md](AGENTS_RUNTIME.md) | backend/app/shareddomain/agents + application/agents（Agent 领域与运行时） |
| [IDENTITY_WORKSPACE.md](IDENTITY_WORKSPACE.md) | backend/app/domain + shareddomain/{teams,audit,tools}（身份/租户/团队/审计/工具领域） |
| [INFRASTRUCTURE.md](INFRASTRUCTURE.md) | backend/app/infrastructure + alembic + backend 根配置 |
| [FRONTEND.md](FRONTEND.md) | frontend/ 全部（路由/组件/上下文/i18n/lib/测试） |
| [DEPLOYMENT.md](DEPLOYMENT.md) | deploy/、scripts/、仓库根文件 |


