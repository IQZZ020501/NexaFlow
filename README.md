<div align="center">
  <img src="frontend/public/NexaFlow-logo.png" width="96" alt="NexaFlow logo" />
  <h1>NexaFlow</h1>
  <p>面向团队的 AI 应用编排平台，将知识库、模型、Agent、工作流与统一工具能力组织在同一工作空间中。</p>

  <p>
    <a href="https://github.com/IQZZ020501/NexaFlow/actions/workflows/ci.yml"><img src="https://github.com/IQZZ020501/NexaFlow/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a>
    <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB" alt="Python 3.11+" />
    <img src="https://img.shields.io/badge/Next.js-15-000000" alt="Next.js 15" />
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPLv3-blue" alt="GPLv3 license" /></a>
  </p>
</div>

## 项目简介

NexaFlow 提供多工作空间隔离的 AI 应用构建与运行能力。团队可以管理模型和知识库，创建可发布的 Agent，使用可视化画布编排工作流，并在服务端权限、审批、预算和运行恢复机制约束下调用内置、Python 与 MCP 工具。

## 核心能力

- **应用构建**：统一管理 Agent 与工作流，支持草稿、发布快照、公开访问和 API 调用。
- **知识库与 RAG**：文档与显式 QA 导入、OCR、Parent/Child 分段、Qdrant 向量与 `pg_search` BM25 混合检索、RRF/重排、权限过滤、显式一跳引用与离线评测。
- **Agent 运行时**：基于 Celery 的耐久执行、运行租约、checkpoint、可重放事件、对话记忆和模型用量记录。
- **可视化工作流**：React Flow 画布、不可变发布版本、节点审计，以及隔离的 Python Code 节点沙箱。
- **模型管理**：支持 OpenAI-compatible、Anthropic、Amazon Bedrock、Azure OpenAI、DeepSeek、Gemini 和 Ollama。
- **统一工具系统**：内置、Python 与 MCP 工具共享目录、不可变版本、`view/use` 授权、应用绑定和调用账本；MCP 支持 Streamable HTTP、SSE、stdio、加密凭据与定义变更失效策略。
- **团队治理**：工作空间与团队分级管理、资源级权限、审计日志和简体中文、繁体中文、英文界面。

## 产品界面

### Agent 构建与调试

在同一工作区配置模型、知识库、统一工具和系统提示词，并在右侧调试区直接验证 Agent。工具绑定固定版本，发布后可继续维护草稿，再通过重新发布更新公开版本。

![NexaFlow Agent 构建与调试界面](docs/assets/agent-builder.png)

### 应用发布与 API

Agent 和工作流都可以发布为公开访问页面，也可以通过独立 API Key、API 地址和接口文档接入其他系统。

![NexaFlow 应用发布与 API 界面](docs/assets/application-publishing.png)

### 知识库文档

知识库集中管理文档/QA 上传、解析、向量化、启停、重建索引和命中测试，并提供检索 Trace 与异步评测。

![NexaFlow 知识库文档界面](docs/assets/knowledge-base-documents.png)

### 模型供应商

模型注册按供应商引导填写连接信息和凭据，可接入云端模型、OpenAI-compatible 服务和本地模型。

![NexaFlow 模型供应商选择界面](docs/assets/model-provider-selection.png)

### 工作空间管理

系统管理员可以创建和维护工作空间，并在工作空间内继续管理团队、用户和审计日志，实现组织与资源隔离。

![NexaFlow 工作空间管理界面](docs/assets/workspace-management.png)

## 技术架构

```mermaid
flowchart LR
    Browser[Browser] --> Web[Next.js frontend]
    Web --> API[FastAPI API]
    API --> DB[("PostgreSQL 17 + pg_search")]
    API --> Redis[(Redis)]
    API --> Qdrant[(Qdrant)]
    API --> Storage[("Shared upload storage")]
    Redis <--> Worker["Celery worker + embedded Beat"]
    Worker --> DB
    Worker --> Qdrant
    Worker --> Storage[(Shared upload storage)]
    Worker --> Sandbox[Isolated Python sandbox]
    Worker --> Models[LLM providers]
    Worker --> ToolRuntime[Unified Tool Runtime]
    ToolRuntime --> Sandbox
    ToolRuntime --> MCP[MCP servers]
```

| 层级 | 技术 |
| --- | --- |
| 前端 | Next.js 15、React 19、TypeScript、Bun、shadcn/ui、Tailwind CSS、React Flow |
| API | Python 3.11+、FastAPI、SQLAlchemy Async、Alembic |
| 异步执行 | Celery、Redis、PostgreSQL checkpoint 与事件 |
| 工具 | builtin / Python / MCP 统一目录、不可变版本、授权、策略、绑定与 ToolInvocation |
| 检索 | Qdrant、PostgreSQL `pg_search` 0.25.2（Jieba/BM25）、RRF、显式引用一跳扩展、可选 reranker |
| 部署 | PostgreSQL 17 + `pg_search`、Docker Compose、Nginx、独立无网络 Python 沙箱 |

## 快速开始

### 前置要求

- Docker 与 Docker Compose v2

### 1. 准备配置

```bash
cp deploy/.env.example deploy/.env
```

编辑 `deploy/.env`，至少替换以下值：

- `POSTGRES_PASSWORD`
- `JWT_SECRET_KEY`
- `MODEL_SECRET_KEY`
- `BOOTSTRAP_ADMIN_PASSWORD`

生产环境不要继续使用示例文件中的凭据。

### 2. 初始化并启动

```bash
docker compose -f deploy/docker-compose.yml build db
docker compose -f deploy/docker-compose.yml up -d db redis qdrant sandbox
docker compose -f deploy/docker-compose.yml run --rm --build api alembic upgrade head
docker compose -f deploy/docker-compose.yml up -d --build
```

`db` 镜像内置 PostgreSQL 17、`pg_search` 0.25.2 及 `pgvector`，并在数据库启动时预加载 `pg_search`。使用外部 PostgreSQL 时必须先安装 `pg_search` 与 `pgvector`，将 `pg_search` 加入 `shared_preload_libraries` 并重启数据库，再执行 Alembic 迁移。

最后一条命令会启动 API、前端、Worker 和无网络沙箱；Python Tool 与 Workflow Python 需要 Worker 和沙箱同时运行。

启动完成后访问：

- Web：<http://localhost:3000>
- API 健康检查：<http://localhost:8000/health>
- OpenAPI：<http://localhost:8000/docs>

使用 `deploy/.env` 中的 `BOOTSTRAP_ADMIN_USERNAME` 和 `BOOTSTRAP_ADMIN_PASSWORD` 登录。首次登录必须修改初始密码。

### 3. 查看状态与日志

```bash
docker compose -f deploy/docker-compose.yml ps
docker compose -f deploy/docker-compose.yml logs -f api worker frontend
```

停止服务：

```bash
docker compose -f deploy/docker-compose.yml down
```

数据保存在 `deploy/data` 的 bind mount 中，`down` 不会删除它。如需重置本地数据，必须先停止相关容器；不要在 Redis、PostgreSQL 或 Qdrant 运行时删除其挂载目录。

详细的部署、迁移、Nginx 和安全配置见 [deploy/README.md](deploy/README.md)。

## 本地开发

本地开发需要 Docker Compose v2、Python 3.11+、[uv](https://docs.astral.sh/uv/)、Bun 1.3+ 和 GNU Make。Windows 需要额外安装 GNU Make；Makefile 目标通过 Python 编排，不依赖 Bash。此模式只在 Docker 中运行 PostgreSQL、Redis、Qdrant、Worker 和沙箱，API 与前端直接在宿主机运行；不需要 `deploy/.env`。

### 1. 首次初始化

```bash
test -f backend/.env || cp backend/.env.example backend/.env
docker compose \
  -f deploy/docker-compose.yml \
  -f deploy/docker-compose.dev.yml \
  up -d --build db redis qdrant

cd backend
uv sync --dev --frozen
uv run python -m alembic upgrade head

cd ../frontend
bun install --frozen-lockfile
```

默认配置使用本机端口 `5432`、`6379` 和 `6333`。如果修改数据库账号或端口，需要同时更新 `backend/.env`。

### 2. 启动容器服务

```bash
docker compose \
  -f deploy/docker-compose.yml \
  -f deploy/docker-compose.dev.yml \
  up -d --build db redis qdrant sandbox worker
```

这条命令会一起启动全部开发容器。Compose Worker 内嵌唯一的 Celery Beat，并挂载沙箱 socket 和 `backend/storage`。不要同时运行宿主 `make worker`；宿主 Worker 没有沙箱 socket，不能执行 Python Tool 或 Workflow Python。

### 3. 启动 API

```bash
cd backend
make dev
```

`make dev` 会先执行 Alembic 迁移，再在 <http://127.0.0.1:8000> 启动 API，并自动把 Compose Worker 日志同步到同一个终端。
如果端口已被其他 API 占用，先停止旧进程，或使用 `make dev PORT=8001` 启动到其他端口。

### 4. 启动前端

```bash
cd frontend
bun run dev
```

前端默认运行在 <http://localhost:3000>，开发服务器会把 `/api`、`/health`、`/docs` 和 `/openapi.json` 代理到后端。

## 仓库结构

```text
NexaFlow/
├── backend/    FastAPI API、服务、能力适配器、Celery 与 Alembic
├── frontend/   Next.js App Router、页面组件、API 客户端与三语词典
├── sandbox/    Workflow Python Code 节点的隔离执行服务
├── deploy/     Docker Compose、Dockerfile 与 Nginx 示例
├── docs/       模块、产品与工程文档
├── scripts/    仓库辅助脚本
└── imgs/       项目标识
```

后端依赖方向和模块索引见 [docs/INDEX.md](docs/INDEX.md)，运行时与部署细节见 [backend/README.md](backend/README.md) 和 [deploy/README.md](deploy/README.md)。

## 测试

后端：

```bash
cd backend
uv run python -m compileall app tests main.py
uv run python -m tests.unit
uv run python -m tests.knowledge
uv run python -m tests.agents
uv run python -m tests.workflows
```

前端：

```bash
cd frontend
bun run typecheck
bun run lint
bun test --parallel
bun run build
```

沙箱：

```bash
python3 -m sandbox.self_check
```

完整 CI 套件以 [.github/workflows/ci.yml](.github/workflows/ci.yml) 为准。

## 安全说明

- API 与内嵌 Beat 的 Worker 必须连接同一 PostgreSQL、Redis、Qdrant，并共享上传存储和加密密钥；不要同时运行第二个 Beat。
- 远程 MCP 默认拒绝私网与回环地址；只有明确可信的部署才应启用 `MCP_ALLOW_PRIVATE_NETWORKS`。
- stdio MCP 配置允许工作空间管理员启动后端进程，因此只应向可信管理员开放管理权限。
- Python Tool 与 Python Code 节点必须运行在独立沙箱服务中；不要把沙箱 socket 暴露给 API 或宿主外部网络。
- 不要提交 `backend/.env`、`deploy/.env`、模型凭据或其他真实密钥。

## 贡献

`main` 分支受保护，变更通过 Pull Request 合入。提交信息和 PR 标题使用 Conventional Commits：

```text
<type>(<scope>): <summary>
```

开始贡献前请阅读 [AGENTS.md](AGENTS.md)，并确保受影响模块的最小测试、静态检查和构建检查通过。

## 许可证

本项目基于 [GNU General Public License v3.0](LICENSE) 发布。内置数据库镜像使用的 `pg_search` Community 扩展采用 AGPLv3，第三方组件仍保留各自许可条款；部署前请查阅 [deploy/README.md](deploy/README.md)。
