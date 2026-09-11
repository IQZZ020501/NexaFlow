# NexaFlow 模块文档索引

> 每个功能模块一份独立文档，说明模块职责、分层关系与文件清单。

## 架构总览

```text
backend/   FastAPI 后端（Python >=3.11，SQLAlchemy 异步 + Celery）
frontend/  Next.js 16 App Router + React 19 + TypeScript（Bun，shadcn/ui，src 布局）
deploy/    Docker Compose 全栈编排、Dockerfile、Nginx 示例
```

后端调用链：`api/v1/<feature>/`（薄路由，routes.py）→ `application/<feature>/`（应用服务/业务规则）→ `domain/<feature>/`（领域服务与 ORM 模型）与 `adapters/` + `ports/`（LLM 运行时、RAG、MCP、解析管道等能力的实现与稳定契约）→ `infra/`（配置/DB/队列/安全/存储/日志/repositories）。实体与契约按功能拆分：`entities/<feature>/`（纯领域实体 dataclass）、`schemas/<feature>/`（Pydantic 契约）；Celery 后台任务位于 `tasks/<feature>/jobs.py`（共享辅助见 `tasks/runtime.py`）。所有核心资源表带 `workspace_id`，API 以 `/workspaces/{workspace_id}/...` 表达工作空间上下文。模块文档已随目录重构更名：CAPABILITIES.md → ADAPTERS.md、INFRASTRUCTURE.md → INFRA.md（见下表）。

前端：`app/` 路由薄壳委托 `components/` 页面组件（客户端渲染）；`contexts/` 全局状态（语言/主题/会话）；`lib/api/` 按域划分的 API 客户端统一走 `lib/api-client.ts`；`i18n/` 三语词典。

## 文档列表

| 文档 | 覆盖范围 |
| --- | --- |
| [API.md](API.md) | backend/app/api（HTTP 接口层）与 backend/app/schemas（Pydantic 契约） |
| [APPLICATION.md](APPLICATION.md) | backend/app/application（应用服务层） |
| [ADAPTERS.md](ADAPTERS.md) | backend/app/ports（稳定契约）与 backend/app/adapters（LLM 运行时 / RAG / MCP / 解析管道实现） |
| [KNOWLEDGE.md](KNOWLEDGE.md) | backend/app 知识库全栈：api/v1/knowledge、application/knowledge、domain/knowledge、entities + schemas/knowledge、tasks/knowledge、infra db/repositories + sql（知识库 API、领域、应用服务与 Celery 任务） |
| [AGENTS_RUNTIME.md](AGENTS_RUNTIME.md) | backend/app/domain/agents + application/agents + api/v1/agents + tasks/agents（Agent 领域与运行时） |
| [AGENT_EVALUATION.md](AGENT_EVALUATION.md) | Agent 确定性 CI 回归与真实环境发布前评测门禁、数据集契约和运行方式 |
| [IDENTITY_WORKSPACE.md](IDENTITY_WORKSPACE.md) | backend/app/domain/{platform,identity,teams,audit,tools,email,resource_folders} + 对应 application/api/repositories（身份/工作区/团队/审计/工具/资源夹领域） |
| [INFRA.md](INFRA.md) | backend/app/infra（配置/DB/队列/安全/存储/日志/repositories）+ alembic + backend 根配置 |
| [FRONTEND.md](FRONTEND.md) | frontend/ 全部（路由/组件/上下文/i18n/lib/测试） |
| [DEPLOYMENT.md](DEPLOYMENT.md) | deploy/、scripts/、仓库根文件 |
