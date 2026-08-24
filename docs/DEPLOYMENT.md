# DEPLOYMENT 模块（deploy/、scripts/、仓库根）

## 职责

全栈部署拓扑：docker-compose 编排 PostgreSQL/Redis/Qdrant/API/Celery/前端；镜像构建（uv / bun 多阶段）；可选 Nginx 反向代理；仓库 Git hooks 启用脚本。

## 文件清单

### deploy/

- `deploy/docker-compose.yml` — 全栈编排：PostgreSQL 17/Redis 7/Qdrant/API/内嵌 Beat 与源码沙箱监管的 Celery worker/Next.js 前端；三个应用服务共用一个可从镜像仓库拉取的应用镜像
- `deploy/docker-compose.server.yml` — 阿里云镜像仓库拉取版：自动执行 Alembic 迁移，再按健康状态启动全部服务
- `deploy/README.md` — Compose 部署文档：快速启动、服务表、配置项、Nginx 分流与迁移说明
- `deploy/nginx/default.conf` — 可选反向代理：`/api/` 与 `/health` 到 API，前端静态资源带缓存头转发 Next.js
- `deploy/dockerfiles/app.Dockerfile` — 统一应用镜像：uv 分别构建后端与沙箱运行时、bun 构建 Next.js standalone；Compose 用不同命令启动 API、Worker 和前端，Sandbox 由 Worker 从源码监管
- `deploy/dockerfiles/postgres.Dockerfile` — PostgreSQL 17 + `pg_search` 0.25.2 + `pgvector` 定制镜像

### scripts/

- `scripts/setup-hooks.sh` — 设置 `git config core.hooksPath .githooks` 启用仓库 Git hooks

### 仓库根

- `README.md` — 空占位文件
- `.env.example` — 宿主机后端与 Compose 共用的唯一环境变量模板；Compose 显式覆盖容器网络地址
- `.gitignore` — 忽略规则（Python/Node 产物、虚拟环境、日志、.env、docs/MVP_TASK_PLAN.md、.codegraph、.playwright-cli/ 等）
- `.playwright-cli/` — Playwright 浏览器自动化运行产物目录（已被 gitignore 忽略）

## 关键约定

- 仓库根 `.env` 是宿主机后端与 Compose 的唯一配置源；Compose 命令显式传 `--env-file .env`，并通过 `NEXAFLOW_APP_IMAGE` / `NEXAFLOW_POSTGRES_IMAGE` 选择本地或镜像仓库标签。
- API、Worker 与 Frontend 共享同一应用镜像并保持三个独立容器；Sandbox 不是 Compose 服务。Worker 必须保留 namespace/chroot 所需 capability，关闭会拦截 mount 的 Docker 默认 AppArmor profile，保留 `no-new-privileges` 和默认 seccomp，并在启动 Celery 前丢弃 capability。
- API 与 Worker 必须共享 `KNOWLEDGE_STORAGE_DIR` 并连接同一个 `QDRANT_URL`，否则 worker 会漏读上传文件或写入不同向量库。
- API 与内嵌 Beat 的 Worker 必须连接同一 PostgreSQL/Redis；该组合 Worker 只运行一个实例，由 Beat 重新派发 queued/租约过期的 Knowledge Task 与 Agent Run。Celery 的 late ack、worker-lost reject 与数据库租约共同完成接管。
- `AGENT_EXECUTOR_HEARTBEAT_SECONDS` 必须小于 `AGENT_EXECUTOR_LEASE_SECONDS` 的一半。部署更新应先执行 Alembic，再滚动更新 API/Worker；回滚则先回滚进程，再降级 migration。
- 公开链接与 Agent API 的 Run 提交通过同一 Redis 做双桶限流；Redis 不可用时这些成本型入口返回 503，避免恢复后集中执行未受限请求。
- FastAPI `/docs` 和 `/openapi.json` 保留完整接口文档；Agent 概览中的专属文档页单独使用 Agent API Key 解锁，不替代或裁剪全局 Swagger。
- 生产环境未配置 `QDRANT_URL` 时应用启动失败（有意强校验）。
