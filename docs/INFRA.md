# INFRA 模块（backend/app/infra + backend/alembic + backend 根）

## 职责

技术基础设施：配置加载、异步数据库会话与仓库层（ORM↔实体映射 + 按特性划分的 repositories 数据访问层）、原始 SQL 脚本、Alembic 数据库迁移链、安全（密码/JWT、密钥加解密、Redis 限流）、日志体系（`log_error`/`log_event` 与内外部错误分类）、Celery 应用与任务分发、对象存储、Python 沙箱客户端、运行时工具、Agent 实时流、MCP stdio 处理、SMTP 发送与引导数据播种。

分层约定：业务领域代码通过 `app/ports/` 中稳定契约访问能力；本模块（`app/infra`）提供其基础设施实现与跨层工具，不反向依赖业务模块。

## 目录总览

### app/infra/config/

- `backend/app/infra/config/settings.py` — `Settings` dataclass 配置：从仓库根 `.env`（`ENV_FILE` 指向仓库根，宿主机与 Compose 共用）读取 PostgreSQL/Qdrant 连接、密钥、引导账号和部署边界，安全构造 PostgreSQL 连接串（组件与 `DATABASE_URL` 不一致时强校验报错），并集中声明稳定服务地址、Agent 预算、执行器租约/轮询、限流和认证时长的代码默认值。既有高级环境覆盖继续兼容；普通 `.env` 不再复制整套运行策略。

### app/infra/db/

- `backend/app/infra/db/base.py` — SQLAlchemy `DeclarativeBase` 基类 `Base`，全部 ORM 模型与 Alembic 迁移环境共用。
- `backend/app/infra/db/session.py` — 异步数据库引擎与会话工厂：`configure_database(settings, *, worker_process)` 初始化（Celery worker 拒绝内存 SQLite），提供 FastAPI 依赖 `get_db`。
- `backend/app/infra/db/mapping.py` — 通用 ORM↔实体机械映射助手：`to_entity`/`to_orm`/`apply_to_orm`/`save`/`refresh_entity`。`app.entities` 中的实体字段与数据库列一一对应，映射按 `dataclasses.fields` 机械完成；repositories 在服务边界使用这些助手，业务代码不触碰 ORM 行。`save` 负责 `db.add` 与 `flush`。
- `backend/app/infra/db/repositories/<feature>/…` — 按特性划分子包的数据访问层；repositories 通过 `app/infra/db/mapping.py` 在 ORM 行与实体间映射，并拥有全部 `db.add`/`delete`/`flush` 写操作：
  - `agents/repository.py` — Agent/绑定/API 凭据、Agent 维度的 Run 列表与会话记忆，以及统一 ToolInvocation 投影的数据访问
  - `runs/runs.py`、`runs/leases.py`、`runs/events.py`、`runs/session_inputs.py` — 四表 Run 身份/状态/快照，执行租约认领与续约，Run 事件追加与读取，以及 append-only 会话输入队列的数据访问
  - `workflows/repository.py` — Workflow 发布版本与 Run 数据访问
  - `knowledge/repository.py`、`knowledge/documents.py`、`knowledge/bases.py`、`knowledge/tasks.py`、`knowledge/storage.py`、`knowledge/evaluation.py`、`knowledge/graph.py`、`knowledge/references.py` — 知识库/文档/分块（含 `query_keyword_chunk_ids`）、知识库基础设置、任务、存储清理、评估、证据图与文档引用数据访问
  - `tools/repository.py`、`tools/catalog.py`、`tools/bindings.py`、`tools/invocations.py`、`tools/drafts.py`、`tools/mcp.py` — Tool Source/Tool/Version/Policy、应用绑定、durable ToolInvocation 生命周期、草稿，以及 MCP Server 与本地审核工具策略数据访问
  - `agent_skills/repository.py`、`announcements/repository.py` — 技能包与公告数据访问
  - `identity/users.py`、`identity/enterprise.py`、`identity/invitations.py` — 用户/刷新会话、企业身份连接、邀请数据访问
  - `platform` 相关特性仓库拆分于 `teams/repository.py`、`workspaces/repository.py`（含资源权限 `workspaces/resource_permissions.py`）、`governance/inventory.py`、`governance/settings.py`、`resource_folders/repository.py`、`analytics/repository.py`
  - `audit/repository.py`、`audit/system_logs.py` — 审计日志与系统日志列表查询
  - `models/registry.py` — 模型注册表数据访问
  - `artifacts/repository.py` — Agent 生成文件的二进制元数据与过期清理
  - `email/delivery.py`、`email/smtp.py` — 邮件投递记录与 SMTP 设置数据访问
- `backend/app/infra/db/sql/<feature>/…` — 手写 SQL：
  - `knowledge/query_keyword_chunk_ids.sql` — 使用 `pg_search` Jieba 匹配与 BM25 分数排序的关键词 chunk 查询
  - `knowledge/graph/neighborhood.sql`、`knowledge/graph/query_entity_candidates.sql`、`knowledge/graph/shortest_path.sql` — 知识图谱邻域/实体候选/最短路径查询（`sql/` 目前仅含 `knowledge/` 一个特性目录）

### app/infra/queue/

- `backend/app/infra/queue/celery.py` — Celery 应用工厂：broker、序列化、ack 策略、任务失败全局错误钩子（走 `app.infra.observability.errors.log_error`）、重任务后 GC。任务模块以 `include` 注册：`app.tasks.<feature>.jobs`（knowledge/agents/tools/email/storage/maintenance），任务实现在 `app/tasks/<feature>/jobs.py`，worker 辅助逻辑在 `app/tasks/runtime.py`；另有 `beat_schedule`（30s/60s 维护恢复，均指向 `app.maintenance.run`）、按平台选择 pool 的 `worker_pool_for_platform`、`NexaFlowTask` 任务基类与 `publish_task` 按名投递辅助。Worker 启动命令由 `backend/scripts/worker.py` 生成：`python -m celery -A app.infra.queue.celery:celery_app worker --beat --queues=celery,agents-legacy,agents-v2 --loglevel=info --pool <threads|solo|prefork> --pidfile <tmp>`；未设置 `OPENSANDBOX_API_KEY` 时直接报错退出，pidfile 路径由仓库路径与 broker 端点指纹生成。

### app/infra/security/

- `backend/app/infra/security/auth.py` — 密码哈希（pwdlib）、JWT access token 签发/校验、refresh token 生成与哈希、隔离密钥派生的 Artifact 下载 token。
- `backend/app/infra/security/secrets.py` — Fernet 对称加解密工具与密钥尾号提示 `secret_hint`。
- `backend/app/infra/security/agent_rate_limit.py` — Redis 固定窗口限流（Lua 脚本，agent 级与 consumer 级双计数），约束 Agent 外部请求；同模块另提供 `AgentRateLimitExceeded`/`AgentRateLimitUnavailable` 与登录、密码重置限流错误（`LoginRateLimitExceeded` 等，均携带 `retry_after`）。
- `backend/app/infra/security/enterprise_login_rate_limit.py` — Redis 固定窗口企业登录限流，超限抛 `EnterpriseLoginRateLimitExceeded`（携带 `retry_after`）。

### app/infra/observability/

- `backend/app/infra/observability/logger.py` — 全局日志初始化 `setup_logging`、项目前缀 logger 与结构化事件 `log_event`。
- `backend/app/infra/observability/errors.py` — 错误日志单一入口 `log_error`：内部（`source=internal`）/外部上游服务（`source=external`）错误来源分类 `classify_error`（`ExternalServiceError` 基类定义在 `app/ports/errors.py`，本模块仅导入）供服务边界代码抛内部包装后的上游失败。
- `backend/app/infra/observability/system_log.py` — `SystemLog` ORM 模型（`system_logs` 表）与 `record_system_log` 系统日志落库。

### app/infra/storage/

- `backend/app/infra/storage/object_storage.py` — `ObjectStorage` 协议端口（业务领域消费，绝不依赖具体类）与 `LocalObjectStorage` 实现、`ObjectStorageError`/`ObjectTooLargeError`/`EmptyObjectError` 错误层次；用于 Artifact/生成文件的二进制持久化（同步 `put_bytes` 与流式 `put_chunks`、`delete_prefix` 过期清理）。

### app/infra/sandbox/

- `backend/app/infra/sandbox/client.py` — Workflow/Artifact 语义与结果校验：通过 `app/ports/execution.py` 委托外部 OpenSandbox，保持 `execute_workflow_code`/`execute_artifact_code`/`execute_skill_artifact` 契约；无 Unix socket 或宿主进程回退。
- `backend/app/infra/execution/` — 公网域名语法/私网 deny 列表、非敏感执行配置指纹；生命周期在 `adapters/execution/opensandbox.py`，运行器在独立执行镜像。

### app/infra/runtime/

- `backend/app/infra/runtime/event_loop.py` — Windows 下为 Celery/psycopg 安装 selector 事件循环策略（其他平台 no-op）。
- `backend/app/infra/runtime/request_body_limit.py` — ASGI 中间件 `RequestBodyLimitMiddleware`（默认 100 MiB 上界）。
- `backend/app/infra/runtime/validation.py` — 输入规范化：email/username/name 校验与 trim。
- 通用工具已迁出本包：UUID 主键 `new_id`、UTC 时间 `utc_now`、应用时区 `Asia/Shanghai`（`APP_TIMEZONE_NAME`/`APP_TIMEZONE`）现位于 `backend/app/entities/defaults.py`。

### app/infra/agents/

- `backend/app/infra/agents/live_stream.py` — Agent 答案/推理增量（`answer_delta`/`answer_reset`/`reasoning_delta`/`tool_input_delta`）的有界 Redis Stream（`AgentLiveStreamPublisher`/`AgentLiveStreamReader`）；提供短期补发游标并在 Redis 故障时安全降级。

### app/infra/tools/

- `backend/app/infra/tools/dispatch.py` — durable ToolInvocation 的 broker 分发：`enqueue_tool_invocation` 经 Celery `send_task("app.tools.run", …)` 投递。
- `backend/app/infra/tools/mcp_stdio.py` — MCP stdio 配置（command/args/cwd/env/egress_domains）解析、加密序列化和输入边界；路径属于执行镜像，不查询或执行业务宿主文件。

### app/infra/email/

- `backend/app/infra/email/smtp.py` — 纯 stdlib SMTP 异步传输（系统管理功能使用）：`SmtpConfigurationError` 与继承 `ExternalServiceError` 的 `SmtpDeliveryError`，支持 TLS/认证。

### app/infra/bootstrap/

- `backend/app/infra/bootstrap/seed.py` — 引导数据播种：按 Settings 创建初始管理员 `seed_bootstrap_admin`（幂等，已存在则跳过）。

## Alembic 迁移链

- `backend/alembic/env.py` — Alembic 迁移环境：导入 ORM 模型注册到 `Base.metadata`，覆盖 `app.domain` 各特性模型（agent/tool/knowledge/workflow/graph/platform/identity-enterprise/email/audit/artifacts/resource_folders/agent_skills/announcements 与 `app.domain.models.registered.RegisteredModel`）及 `app.infra.observability.system_log.SystemLog`；从 Settings 读 `DATABASE_URL`，支持在线/离线迁移。
- 迁移版本（`backend/alembic/versions/*.py`，时间戳编号，单链演进）：从 `202607040001_identity_workspace_foundation`（users / workspaces / teams 初始表）到 `202609230001_detach_user_references`，先后覆盖租户约束与系统/审计日志、知识库文档分块流水线与 BM25 检索、模型注册与凭据、Agent 发布/公开访问/四表 Run 存储/会话记忆、统一 Tool 持久化与 Workflow 基础、MCP 传输与网络策略、生成 Artifact 与资源文件夹、企业身份、治理与邀请、技能与内建工具、上海时区、视觉模型、公告、文档引用模板、Agent 运行时治理、当前时间工具、知识调用预算与查询模式移除、技能控制面与依赖安装、PPT/图片生成技能、用户引用解耦等演进。
- 根配置：`backend/alembic.ini`（`script_location = alembic`、`prepend_sys_path = .`）与 `backend/Makefile` 目标 `dev`/`migrate`/`worker`/`coverage`。

## 相关测试

- `backend/tests/support/` — 测试共享基础设施：内存 SQLite + eager Celery 的 TestClient 环境、Settings 构造、登录/激活管理员/激活用户辅助函数、MCP 测试服务器
- `backend/tests/infra/unit.py` — 本模块单元测试（配置、运行时工具、密钥、对象存储、日志器等）
- `backend/tests/infra/infra_unit_coverage.py` — 基础设施覆盖聚合
- `backend/tests/infra/logger.py` — 全局日志器与错误分类（internal/external）单元测试
- `backend/tests/infra/architecture.py` — 分层依赖守卫：AST 扫描 `backend/app` 的跨层 import 规则与 `entities`/`ports` 纯净性
- `backend/tests/infra/mcp_transports.py` — 本地 HTTP/SSE Server 与 mock execution port 回归：Bearer、DNS/代理边界、stdio 配置传递和取消；真实 stdio 进程在执行镜像自检中验证
- `backend/tests/smoke/test_main.py` — 应用冒烟测试：/health、bootstrap 管理员登录、auth/me、404 路由

按特性套件运行（点号路径，`python -m tests.<feature>.<file>`）：`python -m tests.infra.unit`、`python -m tests.infra.infra_unit_coverage`、`python -m tests.infra.logger`、`python -m tests.infra.mcp_transports`、`python -m tests.infra.architecture`、`python -m tests.smoke.test_main`。
