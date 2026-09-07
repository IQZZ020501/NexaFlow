# INFRA 模块（backend/app/infra + backend/alembic + backend 根）

## 职责

技术基础设施：配置加载、异步数据库会话与仓库层（ORM↔实体映射 + 按特性划分的 repositories 数据访问层）、原始 SQL 脚本、Alembic 数据库迁移链、安全（密码/JWT、密钥加解密、Redis 限流）、日志体系（`log_error`/`log_event` 与内外部错误分类）、Celery 应用与任务分发、对象存储、Python 沙箱客户端、运行时工具、Agent 实时流、MCP stdio 处理、SMTP 发送与引导数据播种。

分层约定：业务领域代码通过 `app/ports/` 中稳定契约访问能力；本模块（`app/infra`）提供其基础设施实现与跨层工具，不反向依赖业务模块。

## 目录总览

### app/infra/config/

- `backend/app/infra/config/settings.py` — `Settings` dataclass 配置：从仓库根 `.env`（`ENV_FILE` 指向仓库根，宿主机与 Compose 共用）读取 PostgreSQL 组件并安全构造连接串（组件与 `DATABASE_URL` 不一致时强校验报错），以及数据库/JWT/Qdrant/Redis/Celery、Agent 外部请求限流、沙箱网络、引导管理员等全部环境配置与生产强校验。

### app/infra/db/

- `backend/app/infra/db/base.py` — SQLAlchemy `DeclarativeBase` 基类 `Base`，全部 ORM 模型与 Alembic 迁移环境共用。
- `backend/app/infra/db/session.py` — 异步数据库引擎与会话工厂：`configure_database(settings, *, worker_process)` 初始化（Celery worker 拒绝内存 SQLite），提供 FastAPI 依赖 `get_db`。
- `backend/app/infra/db/mapping.py` — 通用 ORM↔实体机械映射助手：`to_entity`/`to_orm`/`apply_to_orm`/`save`/`refresh_entity`。`app.entities` 中的实体字段与数据库列一一对应，映射按 `dataclasses.fields` 机械完成；repositories 在服务边界使用这些助手，业务代码不触碰 ORM 行。`save` 负责 `db.add` 与 `flush`。
- `backend/app/infra/db/repositories/<feature>/…` — 按特性划分子包的数据访问层；repositories 通过 `app/infra/db/mapping.py` 在 ORM 行与实体间映射，并拥有全部 `db.add`/`delete`/`flush` 写操作：
  - `agents/repository.py` — Agent/绑定/API 凭据，以及跨 Run 身份、状态、快照、事件和统一 ToolInvocation 投影的数据访问
  - `workflows/repository.py` — Workflow 发布版本与 Run 数据访问
  - `knowledge/repository.py`、`knowledge/evaluation.py`、`knowledge/graph.py`、`knowledge/references.py` — 知识库/文档/分块/任务、评估、证据图与文档引用数据访问
  - `tools/repository.py`、`tools/mcp.py` — Tool Source/Tool/Version/Policy/授权绑定与 durable ToolInvocation、MCP Server 与本地审核工具策略数据访问
  - `identity/users.py`、`identity/enterprise.py`、`identity/invitations.py` — 用户/刷新会话、企业身份连接、邀请数据访问
  - `platform` 相关特性仓库拆分于 `teams/repository.py`、`workspaces/repository.py`（含资源权限 `workspaces/resource_permissions.py`）、`governance/inventory.py`、`governance/settings.py`、`resource_folders/repository.py`、`analytics/repository.py`
  - `audit/repository.py`、`audit/system_logs.py` — 审计日志与系统日志列表查询
  - `models/registry.py` — 模型注册表数据访问
  - `artifacts/repository.py` — Agent 生成文件的二进制元数据与过期清理
  - `email/delivery.py`、`email/smtp.py` — 邮件投递记录与 SMTP 设置数据访问
- `backend/app/infra/db/sql/<feature>/…` — 手写 SQL：
  - `knowledge/query_keyword_chunk_ids.sql` — 使用 `pg_search` Jieba 匹配与 BM25 分数排序的关键词 chunk 查询
  - `graph/neighborhood.sql`、`graph/query_entity_candidates.sql`、`graph/shortest_path.sql` — 知识图谱邻域/实体候选/最短路径查询

### app/infra/queue/

- `backend/app/infra/queue/celery.py` — Celery 应用工厂：broker、序列化、ack 策略、任务失败全局错误钩子（走 `app.infra.observability.errors.log_error`）、重任务后 GC。任务模块以 `include` 注册：`app.tasks.<feature>.jobs`（knowledge/agents/tools/email/maintenance），任务实现在 `app/tasks/<feature>/jobs.py`，worker 辅助逻辑在 `app/tasks/runtime.py`。Worker 启动命令由 `backend/scripts/worker.py` 生成：`celery -A app.infra.queue.celery:celery_app`。

### app/infra/security/

- `backend/app/infra/security/auth.py` — 密码哈希（pwdlib）、JWT access token 签发/校验、refresh token 生成与哈希、隔离密钥派生的 Artifact 下载 token。
- `backend/app/infra/security/secrets.py` — Fernet 对称加解密工具与密钥尾号提示 `secret_hint`。
- `backend/app/infra/security/agent_rate_limit.py` — Redis 固定窗口限流（Lua 脚本，agent 级与 consumer 级双计数），约束 Agent 外部请求。
- `backend/app/infra/security/enterprise_login_rate_limit.py` — Redis 固定窗口企业登录限流，超限抛 `EnterpriseLoginRateLimitExceeded`（携带 `retry_after`）。

### app/infra/observability/

- `backend/app/infra/observability/logger.py` — 全局日志初始化 `setup_logging`、项目前缀 logger 与结构化事件 `log_event`。
- `backend/app/infra/observability/errors.py` — 错误日志单一入口 `log_error`：内部（`source=internal`）/外部上游服务（`source=external`）错误来源分类，`ExternalServiceError` 基类供服务边界代码抛内部包装后的上游失败。
- `backend/app/infra/observability/system_log.py` — `SystemLog` ORM 模型（`system_logs` 表）与 `record_system_log` 系统日志落库。

### app/infra/storage/

- `backend/app/infra/storage/object_storage.py` — `ObjectStorage` 协议端口（业务领域消费，绝不依赖具体类）与 `LocalObjectStorage` 实现、`ObjectStorageError`/`ObjectTooLargeError`/`EmptyObjectError` 错误层次；用于 Artifact/生成文件的二进制持久化（同步 `put_bytes` 与流式 `put_chunks`、`delete_prefix` 过期清理）。

### app/infra/sandbox/

- `backend/app/infra/sandbox/client.py` — 通过 Worker 私有 Unix socket 调用 Python sandbox 的客户端：有界 JSON 结果（`WorkflowSandboxResult`）与通用可下载 Artifact（`ArtifactSandboxResult`），支持 `execute_workflow_code`/`execute_artifact_code`/`execute_skill_artifact`；API 进程不执行用户代码，请求大小/超时均有上界。

### app/infra/runtime/

- `backend/app/infra/runtime/event_loop.py` — Windows 下为 Celery/psycopg 安装 selector 事件循环策略（其他平台 no-op）。
- `backend/app/infra/runtime/request_body_limit.py` — ASGI 中间件 `RequestBodyLimitMiddleware`（默认 100 MiB 上界）。
- `backend/app/infra/runtime/validation.py` — 输入规范化：email/username/name 校验与 trim。
- `backend/app/infra/runtime/model_utils.py` — 通用工具：UUID 主键 `new_id`、UTC 时间 `utc_now`、应用时区 `Asia/Shanghai`。

### app/infra/agents/

- `backend/app/infra/agents/live_stream.py` — Agent 答案/推理增量（answer/resonance/tool 增量事件）的有界 Redis Stream（`AgentLiveStreamPublisher`/`AgentLiveStreamReader`）；提供短期补发游标并在 Redis 故障时安全降级。

### app/infra/tools/

- `backend/app/infra/tools/dispatch.py` — durable ToolInvocation 的 broker 分发：`enqueue_tool_invocation` 经 Celery `send_task("app.tools.run", …)` 投递。
- `backend/app/infra/tools/mcp_stdio.py` — MCP stdio 内联配置（command/args/cwd/env）解析与序列化、输入边界校验及可执行文件/工作目录运行时校验（`McpStdioConfigError`）。

### app/infra/email/

- `backend/app/infra/email/smtp.py` — 纯 stdlib SMTP 异步传输（系统管理功能使用）：`SmtpConfigurationError` 与继承 `ExternalServiceError` 的 `SmtpDeliveryError`，支持 TLS/认证。

### app/infra/bootstrap/

- `backend/app/infra/bootstrap/seed.py` — 引导数据播种：按 Settings 创建初始管理员 `seed_bootstrap_admin`（幂等，已存在则跳过）。

## Alembic 迁移链

- `backend/alembic/env.py` — Alembic 迁移环境：导入 ORM 模型注册到 `Base.metadata`，覆盖 `app.domain` 各特性模型（agent/tool/knowledge/workflow/graph/platform/identity-enterprise/email/audit/artifacts/resource_folders 与 `app.domain.models.registered.RegisteredModel`）及 `app.infra.observability.system_log.SystemLog`；从 Settings 读 `DATABASE_URL`，支持在线/离线迁移。
- 迁移版本（`backend/alembic/versions/*.py`，时间戳编号，单链演进）：从 `202607040001_identity_workspace_foundation`（users / workspaces / teams 初始表）到 `202609060004_enterprise_refresh_sessions`，先后覆盖租户约束与系统/审计日志、知识库文档分块流水线与 BM25 检索、模型注册与凭据、Agent 发布/公开访问/四表 Run 存储/会话记忆、统一 Tool 持久化与 Workflow 基础、MCP 传输与网络策略、生成 Artifact 与资源文件夹、企业身份、治理与邀请、技能与内建工具、上海时区、视觉模型等演进。

## 相关测试

- `backend/tests/support/` — 测试共享基础设施：内存 SQLite + eager Celery 的 TestClient 环境、Settings 构造、登录/激活管理员/激活用户辅助函数、MCP 测试服务器
- `backend/tests/infra/unit.py` — 本模块单元测试（配置、运行时工具、密钥、对象存储、日志器等）
- `backend/tests/infra/infra_unit_coverage.py` — 基础设施覆盖聚合
- `backend/tests/infra/logger.py` — 全局日志器与错误分类（internal/external）单元测试
- `backend/tests/infra/mcp_transports.py` — 真实子进程/HTTP Server 回归：传输、Bearer 校验、stdio 环境变量传递与超时进程回收
- `backend/tests/smoke/test_main.py` — 应用冒烟测试：/health、bootstrap 管理员登录、auth/me、404 路由

按特性套件运行（点号路径，`python -m tests.<feature>.<file>`）：`python -m tests.infra.unit`、`python -m tests.infra.infra_unit_coverage`、`python -m tests.infra.logger`、`python -m tests.infra.mcp_transports`、`python -m tests.smoke.test_main`。
