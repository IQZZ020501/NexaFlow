# NexaFlow 模块文档索引

> 每个功能模块一份独立文档，说明模块职责、分层关系与文件清单。

## 架构总览

```text
backend/   FastAPI 后端（Python >=3.11，SQLAlchemy 异步 + Celery）
frontend/  Next.js 16 App Router + React 19 + TypeScript（Bun，shadcn/ui，src 布局）
deploy/    Docker Compose 全栈编排、Dockerfile、Nginx 示例
```

后端调用链：`api/v1/<feature>/`（薄路由，routes.py）→ `application/<feature>/`（应用服务/业务规则）→ `domain/<feature>/`（领域服务与 ORM 模型）与 `adapters/` + `ports/`（LLM 运行时、RAG、MCP、OpenSandbox 执行平面、企业身份等能力的实现与稳定契约；文档解析在 `domain/knowledge/documents/parsing.py`，统一工具运行时在 `application/tools/runtime/`）→ `infra/`（配置/DB/队列/安全/存储/日志/repositories/沙箱客户端/runtime）。实体与契约按功能拆分：`entities/<feature>/`（纯领域实体 dataclass）、`schemas/<feature>/`（Pydantic 契约）；Celery 后台任务位于 `tasks/<feature>/jobs.py`（共享辅助见 `tasks/runtime.py`）。所有核心资源表带 `workspace_id`，API 以 `/workspaces/{workspace_id}/...` 表达工作空间上下文。模块文档已随目录重构更名：CAPABILITIES.md → ADAPTERS.md、INFRASTRUCTURE.md → INFRA.md（见下表）。

前端：`app/` 路由薄壳委托 `components/` 页面组件（客户端渲染）；`contexts/` 全局状态（语言/主题/会话）；`lib/api/` 按域划分的 API 客户端统一走 `lib/api-client.ts`；`i18n/` 三语词典。

## 文档列表

| 文档 | 覆盖范围 |
| --- | --- |
| [API.md](API.md) | backend/app/api（HTTP 接口层）与 backend/app/schemas（Pydantic 契约） |
| [APPLICATION.md](APPLICATION.md) | backend/app/application（应用服务层） |
| [ADAPTERS.md](ADAPTERS.md) | backend/app/ports（稳定契约）与 backend/app/adapters（LLM 运行时 / RAG / MCP / 执行平面 / 企业身份实现） |
| [KNOWLEDGE.md](KNOWLEDGE.md) | backend/app 知识库全栈：api/v1/knowledge、application/knowledge、domain/knowledge、entities + schemas/knowledge、tasks/knowledge、infra db/repositories + sql（知识库 API、领域、应用服务与 Celery 任务） |
| [AGENTS_RUNTIME.md](AGENTS_RUNTIME.md) | backend/app/domain/agents + application/agents + api/v1/agents + tasks/agents（Agent 领域与运行时） |
| [agentic-platform-integration.md](agentic-platform-integration.md) | Agentic 架构分期落地、Skill 控制面、运行时快照与回滚边界 |
| [AGENT_EVALUATION.md](AGENT_EVALUATION.md) | Agent 确定性 CI 回归与真实环境发布前评测门禁、数据集契约和运行方式 |
| [IDENTITY_WORKSPACE.md](IDENTITY_WORKSPACE.md) | backend/app/domain/{platform,identity,teams,audit,tools,email,resource_folders} + 对应 application/api/repositories（身份/工作区/团队/审计/工具/资源夹领域） |
| [INFRA.md](INFRA.md) | backend/app/infra（配置/DB/队列/安全/存储/日志/repositories）+ alembic + backend 根配置 |
| [FRONTEND.md](FRONTEND.md) | frontend/ 全部（路由/组件/上下文/i18n/lib/测试） |
| [SKILLS.md](SKILLS.md) | 工作空间 Skill 包（schema v2 控制面、渐进加载、包内脚本与依赖安装、固定渲染器） |
| [WORKFLOW_DESIGN.md](WORKFLOW_DESIGN.md) | Workflow 确定性图引擎、节点目录、数据模型、执行沙箱与 API |
| [model-providers.md](model-providers.md) | 模型供应商接入矩阵（22 个目录项、integration 字段与请求路径） |
| [ENTERPRISE_IDENTITY.md](ENTERPRISE_IDENTITY.md) | 飞书/钉钉/企业微信企业登录配置与安全行为 |
| [UNIFIED_TOOLS_TEST_PLAN.md](UNIFIED_TOOLS_TEST_PLAN.md) | 统一 Tool 系统有效测试规范（范围、用例、证据与门禁） |
| [DEPLOYMENT.md](DEPLOYMENT.md) | deploy/、scripts/、仓库根文件 |
