# DEPLOYMENT 模块（deploy/、scripts/、仓库根）

## 职责

全栈部署拓扑：docker-compose 编排 PostgreSQL/Redis/Qdrant/API/Celery/前端；镜像构建（uv / bun 多阶段）；可选 Nginx 反向代理；仓库 Git hooks 启用脚本。

## 文件清单

### deploy/

- `deploy/docker-compose.yml` — 全栈编排：PostgreSQL 17/Redis 7/Qdrant/API/Celery worker+beat/Next.js 前端，含健康检查与持久卷（db-data/redis-data/qdrant-data/uploads）
- `deploy/README.md` — Compose 部署文档：快速启动、服务表、配置项、Nginx 分流与迁移说明
- `deploy/.env.example` — 部署环境变量模板：数据库、JWT、模型密钥、引导管理员、默认工作区与 CORS
- `deploy/nginx/default.conf` — 可选反向代理：`/api/` 与 `/health` 到 API，前端静态资源带缓存头转发 Next.js
- `deploy/dockerfiles/backend.Dockerfile` — 后端镜像：uv 多阶段构建，API/worker/beat 三进程共用，CMD 启动 uvicorn
- `deploy/dockerfiles/frontend.Dockerfile` — 前端镜像：bun 构建 Next.js standalone，node:22-alpine 运行

### scripts/

- `scripts/setup-hooks.sh` — 设置 `git config core.hooksPath .githooks` 启用仓库 Git hooks

### 仓库根

- `README.md` — 空占位文件
- `.gitignore` — 忽略规则（Python/Node 产物、虚拟环境、日志、.env、docs/MVP_TASK_PLAN.md、.codegraph、.playwright-cli/ 等）
- `.playwright-cli/` — Playwright 浏览器自动化运行产物目录（已被 gitignore 忽略）

## 关键约定

- API 与 Worker 必须共享 `KNOWLEDGE_STORAGE_DIR` 并连接同一个 `QDRANT_URL`，否则 worker 会漏读上传文件或写入不同向量库。
- API、Worker 与 Beat 必须连接同一 PostgreSQL/Redis；生产只运行一个 Beat，由它重新派发 queued/租约过期的 Agent Run。Celery 的 late ack、worker-lost reject 与数据库租约共同完成接管。
- `AGENT_EXECUTOR_HEARTBEAT_SECONDS` 必须小于 `AGENT_EXECUTOR_LEASE_SECONDS` 的一半。部署更新应先执行 Alembic，再滚动更新 API/Worker；回滚则先回滚进程，再降级 migration。
- 生产环境未配置 `QDRANT_URL` 时应用启动失败（有意强校验）。
