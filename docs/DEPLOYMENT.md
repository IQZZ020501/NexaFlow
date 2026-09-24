# DEPLOYMENT 模块（deploy/、scripts/、仓库根）

## 职责

全栈部署拓扑：docker-compose 编排 PostgreSQL/Redis/Qdrant/API/Celery/前端；镜像构建（uv / bun 多阶段）；可选 Nginx 反向代理；仓库 Git hooks 启用脚本。

## 文件清单

### deploy/

- `deploy/docker-compose.yml` — 全栈编排：PostgreSQL 17/Redis 7/Qdrant/一次性 `migrate`/API/内嵌 Beat 的 Celery worker/Next.js 前端；三个应用服务共用一个可从镜像仓库拉取的应用镜像，API 与 Worker 依赖 `migrate` 成功完成
- `deploy/docker-compose.server.yml` — 阿里云镜像仓库拉取版：同样内置一次性 `migrate` 服务，再按健康状态启动全部服务
- `deploy/docker-compose.dev.yml` — 开发覆盖：向宿主发布 5432/6379/6333 并固定容器名，供宿主机后端（`make dev`）使用
- `deploy/opensandbox/README.md` / `configure.py` — 独立执行主机部署、固定版本与私有配置生成；生产默认 Kata + dns+nft，开发需显式选择普通 Docker
- `deploy/nginx/default.conf` — 可选反向代理：`/api/` 与 `/health` 到 API，前端静态资源带缓存头转发 Next.js
- `deploy/dockerfiles/app.Dockerfile` — `runtime` 构建业务应用（含 API 与 Celery 入口 `backend/scripts/worker.py`），`sandbox-runtime` 单独构建 Python/Node 执行镜像（`job.py`、`renderer_checks`、`skills`）；业务镜像不含沙箱源码
- `deploy/dockerfiles/postgres.Dockerfile` — PostgreSQL 17 + `pg_search` 0.25.2 + `pgvector` 定制镜像

### scripts/

- `scripts/dev.py` — 根 `make dev` / `make dev-rebuild` 的本地开发监督器：创建 `.env`、生成缺失密钥、按构建输入指纹重建 PostgreSQL 与执行镜像、启动基础 Compose 服务、应用 Alembic，并统一托管 OpenSandbox/API/Worker/前端
- `scripts/dev_test.py` — `dev.py` 的单元测试（当前未被 Makefile/CI 调用）
- `scripts/setup-hooks.sh` — 设置 `git config core.hooksPath .githooks` 启用仓库 Git hooks

### 仓库根

- `README.md` — 开发、部署、验证入口
- `Makefile` — 根命令 `make dev` / `make dev-rebuild`
- `.env.example` — 宿主机后端与 Compose 共用的唯一环境变量模板；Compose 显式覆盖容器网络地址
- `.githooks/` — 仓库 Git hooks（`pre-commit`，由 `scripts/setup-hooks.sh` 启用）
- `.dockerignore` — 镜像构建上下文裁剪（同时是 `dev.py` 的镜像构建输入）
- `.github/workflows/ci.yml` — CI：渲染并校验两套 Compose 配置，运行前后端套件
- `.gitignore` — 忽略规则（Python/Node 产物、虚拟环境、日志、.env、`deploy/data/`、`docs/local/`、`.agents/`、`coverage/`、docs/MVP_TASK_PLAN.md、.codegraph、.playwright-cli/ 等）
- `.playwright-cli/` — Playwright 浏览器自动化运行产物目录（已被 gitignore 忽略）

## 配置归属

`.env` 只承担进程启动前必须知道的部署边界：PostgreSQL 与向量数据库连接、
应用密钥、OpenSandbox 连接/镜像/出网白名单，以及首次引导账号。稳定的本地服务
地址、公开 Origin、超时、Agent 单次运行预算、租约/轮询、外部 Run 限流和令牌有效期以
`Settings` 的代码默认值为准。SMTP、企业身份连接、工作空间配额与保留策略、
模型、工具等可由管理员修改的产品配置保存在 PostgreSQL。

`.env.example` 只列常用且必须关注的部署边界。以下变量仍可按部署需要覆盖，
但无需复制到每个 `.env`：

- 拓扑与运维：`NEXAFLOW_APP_IMAGE`、`NEXAFLOW_POSTGRES_IMAGE`、
  `POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_HOST`、`POSTGRES_PORT`、
  `DATABASE_URL`、`ENVIRONMENT`、`LOG_LEVEL`、`KNOWLEDGE_STORAGE_DIR`、
  `CELERY_BROKER_URL`、`PUBLIC_APP_URL`、
  `MCP_ALLOW_PRIVATE_NETWORKS`、`NEXAFLOW_PORT`、`CORS_ORIGINS`。
- 兼容既有部署的高级运行策略：`MCP_REQUEST_TIMEOUT_SECONDS`、
  `MODEL_REQUEST_TIMEOUT_SECONDS`、`AGENT_TOOL_TIMEOUT_SECONDS`、
  `AGENT_RUN_TIMEOUT_SECONDS`、`AGENT_MAX_TURNS`、`AGENT_MAX_TOOL_CALLS`、
  `AGENT_MAX_KNOWLEDGE_CALLS`、`AGENT_MAX_KNOWLEDGE_ROUNDS`、
  `AGENT_MAX_MODEL_TOKENS`、`AGENT_EXECUTOR_LEASE_SECONDS`、
  `AGENT_EXECUTOR_HEARTBEAT_SECONDS`、`AGENT_EVENT_POLL_SECONDS`、
  `WORKFLOW_SANDBOX_TIMEOUT_SECONDS`、
  `AGENT_EXTERNAL_AGENT_RUNS_PER_MINUTE`、
  `AGENT_EXTERNAL_CONSUMER_RUNS_PER_MINUTE`、`JWT_EXPIRES_MINUTES`、
  `REFRESH_TOKEN_EXPIRES_DAYS`。这些值的权威默认值在
  `backend/app/infra/config/settings.py`；保留环境覆盖是为了已有部署兼容和受控调优。

## 关键约定

- 仓库根 `.env` 是宿主机后端与 Compose 的唯一配置源；Compose 命令显式传 `--env-file .env`，并通过 `NEXAFLOW_APP_IMAGE` / `NEXAFLOW_POSTGRES_IMAGE` 选择本地或镜像仓库标签。
- API、Worker 与 Frontend 共享业务镜像并保持三个独立容器；独立 OpenSandbox 不进入业务 Compose、不挂载业务数据。Worker 丢弃全部 capability，保留默认 AppArmor/seccomp 和 `no-new-privileges`，不需要 Docker socket 或 root 隔离启动流程。
- API 与 Worker 必须共享 `KNOWLEDGE_STORAGE_DIR` 并连接同一个 `QDRANT_URL`，否则 worker 会漏读上传文件或写入不同向量库。
- API 与内嵌 Beat 的 Worker 必须连接同一 PostgreSQL/Redis；该组合 Worker 只运行一个实例，由 Beat 重新派发 queued/租约过期的 Knowledge Task 与 Agent Run。Celery 的 late ack、worker-lost reject 与数据库租约共同完成接管。
- 根 `.env` 设置 `OPENSANDBOX_URL`、私有 API key 和执行镜像；生产镜像必须使用 digest。单次 stdio MCP 可请求 `OPENSANDBOX_EGRESS_DOMAINS` 子集；其他程序无外网。适配器在写入代码/凭据前核对实际 dns+nft 默认拒绝与私网 deny 规则，不接受 dns-only 降级。Agent Run 冻结非敏感镜像/网络指纹，配置变化会拒绝重试。
- 旧 Unix Broker、Seatbelt/namespace supervisor、`SANDBOX_NETWORK`、宿主 Skills 目录和运行时依赖安装已移除。schema-v1 测试 Skills 需重新导入。
- Agent 执行器的代码默认心跳必须小于租约的一半；使用兼容环境覆盖时仍执行同一强校验。部署更新应先执行 Alembic，再滚动更新 API/Worker；回滚则先回滚进程，再降级 migration。
- 公开链接与 Agent API 的 Run 提交通过同一 Redis 做双桶限流；Redis 不可用时这些成本型入口返回 503，避免恢复后集中执行未受限请求。
- FastAPI `/docs` 和 `/openapi.json` 保留完整接口文档；Agent 概览中的专属文档页单独使用 Agent API Key 解锁，不替代或裁剪全局 Swagger。
- 宿主进程未覆盖 `QDRANT_URL` 时使用代码中的本地默认地址，Compose 则显式覆盖为服务地址；显式配置为空仍会在 `Settings.validate` 中失败。
