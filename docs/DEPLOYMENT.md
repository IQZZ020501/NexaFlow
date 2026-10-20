# DEPLOYMENT 模块（deploy/、scripts/、仓库根）

## 职责

全栈部署拓扑：docker-compose 编排 PostgreSQL/Redis/Qdrant/API/Celery/前端；镜像构建（uv / bun 多阶段）；可选 Nginx 反向代理；仓库 Git hooks 启用脚本。

## 文件清单

### 部署拓扑与 deploy/

- 根 `docker-compose.yml` — 唯一 Compose 文件；默认单机拉取部署，内置密码/网站设置、应用与数据库/执行镜像 digest、OpenSandbox 控制面配置。`docker compose pull` 拉取全部依赖；一次性 `migrate` 成功后启动业务服务
- `deploy/opensandbox/README.md` / `configure.py` — 可选独立执行主机与私有配置生成；该生成器默认 Kata + dns+nft，缺少 Kata 不自动回退
- `deploy/nginx/default.conf` — 可选反向代理：`/api/` 与 `/health` 到 API，前端静态资源带缓存头转发 Next.js
- `deploy/dockerfiles/app.Dockerfile` — 多阶段业务镜像，API/两个 Worker/前端复用；不含沙箱源码
- `deploy/dockerfiles/sandbox.Dockerfile` — 独立构建 Python/Node 执行镜像，由 OpenSandbox 按需创建隔离执行容器
- `deploy/dockerfiles/postgres.Dockerfile` — PostgreSQL 17 + `pg_search` 0.25.2 + `pgvector` 定制镜像

### scripts/

- `scripts/dev.py` — 根 `make dev` / `make dev-rebuild` 的本地开发监督器；创建私有 `.env`、按输入指纹构建本地 PostgreSQL 与执行镜像、迁移并托管开发进程。基础设施从唯一 Compose 渲染后在内存中覆盖本地数据库凭据/镜像/回环端口，再通过 stdin 交给 Compose；不生成第二份配置文件
- `scripts/dev.py --infrastructure-only` — `cd backend && make dev` 复用的基础设施入口，不启动前端或 OpenSandbox
- `scripts/dev_test.py` — 开发入口与配置隔离的回归测试，CI 调用
- `scripts/setup-hooks.sh` — 设置 `git config core.hooksPath .githooks` 启用仓库 Git hooks

### 仓库根

- `README.md` — 开发、部署、验证入口
- `Makefile` — 根开发命令 `make dev` / `make dev-rebuild`
- `.env.example` — 宿主机本地开发的唯一环境变量模板；单机部署直接编辑 Compose，不依赖 `.env`
- `.githooks/` — 仓库 Git hooks（`pre-commit`，由 `scripts/setup-hooks.sh` 启用）
- `.dockerignore` — 镜像构建上下文裁剪（同时是 `dev.py` 的镜像构建输入）
- `.github/workflows/ci.yml` — CI：校验唯一 Compose 与开发入口，运行前后端套件
- `.gitignore` — 忽略规则（Python/Node 产物、虚拟环境、日志、.env、`deploy/data/`、`docs/local/`、`.agents/`、`coverage/`、docs/MVP_TASK_PLAN.md、.codegraph、.playwright-cli/ 等）
- `.playwright-cli/` — Playwright 浏览器自动化运行产物目录（已被 gitignore 忽略）

## 配置归属

### 单机安装

服务器需要已安装并运行的 Docker Engine 和 Docker Compose v2.23.1+。首次安装可以只把仓库根 [`docker-compose.yml`](../docker-compose.yml) 放进一个空目录，也可从 [Releases](https://github.com/IQZZ020501/NexaFlow/releases) 下载对应版本的该文件；不需要 `.env`、源码、Python 或单独的 OpenSandbox 配置文件。已有安装升级时继续使用原数据目录，不能把新空目录当作原来的部署。

#### 1. 设置凭据和网站地址

编辑文件顶部的 `x-settings`：

| 配置 | 是否需要修改 | 填写方式 |
| --- | --- | --- |
| `postgres-password` | 必改 | 独立的随机数据库密码 |
| `admin-password` | 必改 | 初始管理员登录密码，首次登录后必须修改 |
| `managed-user-password` | 必改 | 管理员新建受管用户时的初始密码，用户首次登录必须修改 |
| `sandbox-api-key` | 必改 | 自行生成的随机密钥，无需向 OpenSandbox 申请；调用端和服务端通过同一 anchor 共用 |
| `public-app-url` | 远程访问必改 | 浏览器实际使用的完整网站地址，例如 `http://203.0.113.10:8080` 或 `https://nexaflow.example.com`；不含 `/api`、查询参数或片段 |
| `web-port` | 按需 | 默认 `"8080:3000"`，左侧是宿主访问端口，右侧 `3000` 是容器端口；改成 `"80:3000"` 时，HTTP 网站地址通常无需再带端口 |
| `environment` | 按访问方式 | HTTP 使用 `development`；完成 HTTPS 反向代理配置后使用 `production` |

前四项应使用四个不同的随机值。可分别执行下面的命令，将每次输出填入一项：

```bash
openssl rand -hex 32
```

例如，使用服务器 IP 直接访问时，配置结构如下。将四个 `REPLACE_WITH_…` 替换为生成的值，将示例 IP 换成实际服务器地址：

```yaml
x-settings:
  postgres-password: &postgres-password "REPLACE_WITH_POSTGRES_PASSWORD"
  admin-password: &admin-password "REPLACE_WITH_ADMIN_PASSWORD"
  managed-user-password: &managed-user-password "REPLACE_WITH_USER_PASSWORD"
  sandbox-api-key: &sandbox-api-key "REPLACE_WITH_SANDBOX_API_KEY"
  public-app-url: &public-app-url http://203.0.113.10:8080
  web-port: &web-port "8080:3000"
  environment: &environment development
```

只改值，保留 `&postgres-password` 等 anchor 和服务中的 `*postgres-password` 引用。实际部署文件须私密保存，避免提交真实凭据。上面的十六进制随机值不包含 `$`；自行设置的密码若包含字面 `$`，在 Compose 中必须写成 `$$`。

管理员用户名、邮箱和显示名称在 `x-backend-environment` 中按需修改：

```yaml
  BOOTSTRAP_ADMIN_USERNAME: admin
  BOOTSTRAP_ADMIN_EMAIL: admin@example.com
  BOOTSTRAP_ADMIN_NAME: 系统管理员
```

`admin-password` 只用于创建初始管理员，修改 Compose 不会重置已有账号密码；已有账号请在系统中修改。已有 PostgreSQL 数据目录的数据库密码也不会因修改 `postgres-password` 自动更新，不能只改配置后重启来轮换数据库密码。

#### 2. 校验、拉取和启动

在 `docker-compose.yml` 所在目录执行：

```bash
docker compose config --quiet
docker compose pull
docker compose up -d --wait
docker compose ps -a
```

`config --quiet` 校验配置，不启动服务。定制应用、PostgreSQL 和执行镜像已公开发布，固定 digest 且同时提供 AMD64/ARM64，默认地址可直接匿名拉取；Redis、Qdrant 和 OpenSandbox 辅助组件使用公开镜像。日常安装沿用 `x-images` 中的镜像和 `db`、`redis`、`qdrant`、`opensandbox` 等容器内部地址。

OpenSandbox 配置通过 Compose `configs.content` 内置，控制面走容器内网 `http://opensandbox:8088`；只有控制面拥有 Docker socket。三个 `*-image` 服务和 `migrate` 是正常退出的一次性容器，8 个常驻服务以健康状态或持续运行作为就绪条件。执行容器及网络侧车按任务创建。

使用配置的网站地址访问，健康检查路径为 `/health`，API 文档为 `/docs`。默认管理员用户名是 `admin`，密码为设置的 `admin-password`。模型凭据、SMTP、企业身份和工作空间产品设置登录后管理，不写到部署文件。

#### 3. HTTPS、网络与执行隔离

HTTP 网站使用 `environment: development`，前端仍运行已经构建的镜像。配置好 HTTPS 反向代理后，在同一份 Compose 中同时修改：

```yaml
  public-app-url: &public-app-url https://nexaflow.example.com
  environment: &environment production
```

再运行 `docker compose up -d --wait`，启用 Secure Cookie 和 HTTPS 地址校验。仅修改 `environment` 不会自动配置证书或 HTTPS 入口。如果反向代理运行在宿主机，可将 `web-port` 设为 `"127.0.0.1:8080:3000"`，由反向代理转发到 `http://127.0.0.1:8080`；容器内反向代理需使用它实际可达的地址。

云安全组/外部防火墙仅开放网站和必要运维端口。控制面不发布 `8088`，但上游 OpenSandbox 动态映射宿主 `40000–60000` 沙箱端口，须阻止公网访问该范围。普通 Docker 共享宿主内核。需要 VM 隔离时，可将执行平面迁到独立 Kata 主机：先等待当前任务结束，在同一 Compose 文件中移除本地控制面和三个镜像预拉取服务及业务服务对它的依赖，改用外部 HTTPS `OPENSANDBOX_URL` / API Key，并设置 `OPENSANDBOX_ALLOW_INSECURE_HTTP=0`。

#### 4. 日志、升级与数据保留

```bash
docker compose logs -f api worker agent-worker frontend
docker compose down
```

`down` 停止并移除容器及网络，数据仍保存在 Compose 所在目录的 `deploy/data`。不要在服务运行时删除或移动数据库、Redis、Qdrant 及上传目录。

升级前备份 Compose、PostgreSQL 和上传目录，按发行说明更新 `x-images` digest，再拉取并启动。若升级 execd/egress，同时更新内置 TOML 中对应的镜像 digest。保留自己的密码和网站设置；升级数据库结构后须核对迁移兼容要求，不能假定切回旧镜像就完全回滚。原部署的数据目录仍是 `deploy/data`，移动 Compose 文件时也要保持这些挂载路径指向原数据，不能误启空库。

### 环境变量与产品配置

部署的进程环境直接来自 Compose 的共享 `x-backend-environment` 和各服务的 `environment`。根 `.env.example` / `.env` 只用于宿主机开发；开发监督器会覆盖数据库容器的本地凭据与回环端口，不修改部署文件，也不将部署密码带入开发服务。

`JWT_SECRET_KEY` 与 `MODEL_SECRET_KEY` 是唯一由应用创建并持久化的密钥：API 与
Worker 启动时先查 `platform_secrets`，缺失才创建（用环境变量中的值作为初始值，
否则随机生成），已存在时永远使用库中的值；`.env.example` 因此不再列出这两个变量。
密钥不可变，环境变量只对空库生效，所以重写或改错 `.env` 不会让会话失效或让已保存
的密文无法解密。

`.env.example` 只列常用的本地开发边界。高级进程变量可按需写入 Compose 的
共享后端 `environment`；不必把稳定的代码默认值全部抄入部署文件：

- 拓扑与运维：`POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_HOST`、`POSTGRES_PORT`、
  `DATABASE_URL`、`ENVIRONMENT`、`LOG_LEVEL`、`KNOWLEDGE_STORAGE_DIR`、
  `CELERY_BROKER_URL`、`PUBLIC_APP_URL`、
  `MCP_ALLOW_PRIVATE_NETWORKS`、`CORS_ORIGINS`。部署镜像和网站端口直接编辑 `x-images` / `x-settings.web-port`；`NEXAFLOW_APP_IMAGE` 和 `NEXAFLOW_PORT` 不再控制部署 Compose。`NEXAFLOW_POSTGRES_IMAGE` 仅用于本地开发的数据库镜像覆盖。
- 执行容量：共享后端配置的 `OPENSANDBOX_MAX_SANDBOXES` 限制所有 Worker 同时存活的沙箱总数，当前单机 Compose 设置为 `4`。代码默认 `0` 表示不限制，但 `production` 要求正数。按执行主机的承载能力设置；槽位记录在 Redis（`CELERY_BROKER_URL`）中，按沙箱的原生过期时间自动失效。满载时最多等待 5 秒，仍无空位的工具调用回到队列，由 Run 稍后重试，不会被判为失败；Redis 不可用时不创建沙箱。
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

- 根 `docker-compose.yml` 是唯一部署配置；镜像在 `x-images`，凭据和网站设置在 `x-settings`。本地开发仍单独读取私有根 `.env`，不会把它注入部署容器。
- API、Worker 与 Frontend 共享业务镜像并保持独立容器；OpenSandbox 控制面默认与业务服务一起运行，也可改用外部服务。执行容器由控制面按需创建，不挂载业务数据。两个 Worker 都丢弃全部 capability，保留默认 AppArmor/seccomp 和 `no-new-privileges`，不需要 Docker socket 或 root 隔离启动流程。
- API 与 Worker 必须共享 `KNOWLEDGE_STORAGE_DIR` 并连接同一个 `QDRANT_URL`，否则 worker 会漏读上传文件或写入不同向量库。
- `backend/scripts/worker.py --role` 决定一个 Worker 的职责：`all`（默认，本地开发）消费全部队列并内嵌 Beat；`background` 只消费 `celery` 队列（知识库、工具测试、邮件、清理）并内嵌 Beat，用 prefork 自动伸缩；`agents` 只消费 `agents-legacy`/`agents-v2`，不带 Beat，用线程池让同一进程的所有对话共享一个事件循环，默认并发 32（可追加 `--concurrency=N`）。Worker 使用 NullPool，每个执行中的 Run 会短暂占用 PostgreSQL 连接，调大并发或 `--scale agent-worker=N` 前要确认 `max_connections` 足够。
- API 与内嵌 Beat 的后台 Worker 必须连接同一 PostgreSQL/Redis；后台 Worker 只运行一个实例，由 Beat 重新派发 queued/租约过期的 Knowledge Task 与 Agent Run。Agent Run 只在消息超过租约时长仍未被消费、或租约刚过期时才重新派发，并记录在 `agent_run_states.redispatched_at`，积压时不会每轮重复投递；发现 Run 已被其他 Worker 持有有效租约的重复消息直接结束，不再定时重试。Celery 的 late ack、worker-lost reject 与数据库租约共同完成接管。
- Compose 中设置 `OPENSANDBOX_URL`、私有 API key 和执行镜像；生产镜像必须使用 digest。stdio MCP 和已批准的 Skill 依赖安装可请求 `OPENSANDBOX_EGRESS_DOMAINS` 子集；其他程序无外网。适配器在写入代码/凭据前核对实际 dns+nft 默认拒绝与私网 deny 规则，不接受 dns-only 降级。Agent/Workflow Run 冻结非敏感镜像/网络指纹，配置变化会拒绝重试。
- `execution_sessions` 持久化 Run 的沙箱 ID、短租约和依赖锁；任意 Worker 按 ID 接回，Python、生成文件、渲染器、Workflow 代码节点和 bash 共用 Run 沙箱。结束/取消主动销毁，Beat 按分钟回收过期、孤儿和待关闭会话。Run 内 stdio 服务通过另一台宿主沙箱的 HTTP 桥接进程复用，工具发现仍然一次性。
- 新建 Agent Run 默认自带 bash 能力，无需绑定，工具目录与选择器隐藏它；默认预算为 24 轮、64 次工具调用、900 秒，历史 Run 保留原冻结预算。单条命令最多 300 秒，输出最多 30 KiB。新生成的执行主机配置 TTL 上限为 1860 秒；已有 `server.toml` 需由操作者提高上限，覆盖 Run 最长截止时间加 60 秒，配置生成器不会自动覆盖。
- `OPENSANDBOX_WARM_POOL_SIZE` 默认为 0，开启后从 `OPENSANDBOX_MAX_SANDBOXES` 扣除池大小；公开/API 每位访客最多同时占两台（含 stdio 宿主）。small/standard/heavy 暂用 1 CPU/512 MiB、1 CPU/1 GiB、2 CPU/2 GiB；这些规格尚未做 Kata 生产校准。
- 旧 Unix Broker、Seatbelt/namespace supervisor、`SANDBOX_NETWORK`、宿主 Skills 目录和宿主依赖安装已移除。schema-v1 测试 Skills 需重新导入。
- Agent 执行器的代码默认心跳必须小于租约的一半；使用兼容环境覆盖时仍执行同一强校验。部署更新应先执行 Alembic，再滚动更新 API/Worker；回滚则先回滚进程，再降级 migration。
- 公开链接与 Agent API 的 Run 提交通过同一 Redis 做双桶限流；Redis 不可用时这些成本型入口返回 503，避免恢复后集中执行未受限请求。
- FastAPI `/docs` 和 `/openapi.json` 保留完整接口文档；Agent 概览中的专属文档页单独使用 Agent API Key 解锁，不替代或裁剪全局 Swagger。
- 宿主进程未覆盖 `QDRANT_URL` 时使用代码中的本地默认地址，Compose 则显式覆盖为服务地址；显式配置为空仍会在 `Settings.validate` 中失败。
