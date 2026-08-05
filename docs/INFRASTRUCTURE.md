# INFRASTRUCTURE 模块（backend/app/infrastructure + alembic + backend 根）

## 职责

技术基础设施：配置加载、异步数据库会话、安全（密码/JWT）、日志体系（`log_error`/`log_event` 与内外部错误分类）、密钥加解密、Celery 应用、种子数据、repositories 数据访问层、原始 SQL 脚本、Alembic 数据库迁移链。

## 文件清单

### app/infrastructure/

- `backend/app/infrastructure/config.py` — Settings 配置 dataclass：.env 加载、数据库/JWT/Qdrant/Celery 等全部环境配置与生产强校验
- `backend/app/infrastructure/session.py` — 异步数据库引擎与会话工厂，提供 FastAPI 依赖 `get_db`
- `backend/app/infrastructure/security.py` — 密码哈希（pwdlib）、JWT access token 签发/校验、refresh token 生成与哈希
- `backend/app/infrastructure/errors.py` — 错误日志入口 `log_error`：内部/外部（上游服务）错误来源分类与 `ExternalServiceError` 基类
- `backend/app/infrastructure/logger.py` — 全局日志初始化 `setup_logging`、项目前缀 logger 与结构化事件 `log_event`
- `backend/app/infrastructure/secrets.py` — Fernet 对称加解密工具与密钥尾号提示 `secret_hint`
- `backend/app/infrastructure/model_utils.py` — 通用工具：UUID 主键 `new_id` 与 UTC 时间 `utc_now`
- `backend/app/infrastructure/validation.py` — 输入规范化：email/username/name 校验与 trim
- `backend/app/infrastructure/system_log.py` — SystemLog ORM 模型与 `record_system_log` 系统日志落库
- `backend/app/infrastructure/celery.py` — Celery 应用工厂（broker、序列化、ack 策略）与任务失败全局错误钩子
- `backend/app/infrastructure/seed.py` — 引导数据播种：初始管理员、默认工作空间/团队/成员
- `backend/app/infrastructure/base.py` — SQLAlchemy DeclarativeBase 基类

### infrastructure/repositories/（数据访问层）

- `backend/app/infrastructure/repositories/agent.py` — Agent/知识库绑定/MCP 工具绑定/运行记录数据访问层
- `backend/app/infrastructure/repositories/knowledge.py` — 知识库/文档/分块/任务数据访问层，含关键词命中 chunk 查询
- `backend/app/infrastructure/repositories/user.py` — 用户与刷新会话、工作空间/团队成员关系数据访问层
- `backend/app/infrastructure/repositories/mcp.py` — MCP 服务器与 AgentMCP 工具绑定数据访问层
- `backend/app/infrastructure/repositories/audit.py` — 审计日志列表查询数据访问层
- `backend/app/infrastructure/repositories/team.py` — 团队及成员关系数据访问层（含级联删除）
- `backend/app/infrastructure/repositories/workspace.py` — 工作空间与成员关系数据访问层（含管理员计数）

### infrastructure/sql/（手写 SQL）

- `backend/app/infrastructure/sql/knowledge/query_keyword_chunk_ids.sql` — 关键词检索 chunk 的原始 SQL 查询脚本

### alembic/（数据库迁移链）

- `backend/alembic/env.py` — Alembic 迁移环境：导入全部模型注册到 Base.metadata，从 Settings 读 DATABASE_URL，支持在线/离线迁移
- 迁移版本（`backend/alembic/versions/*.py`，时间戳编号，单链演进）：
  - `202607040001_identity_workspace_foundation.py` — 初始表结构：users / workspaces / workspace_memberships / teams
  - `202607040002_team_memberships.py` — team_memberships 团队成员关系表
  - `202607050001_audit_logs.py` — audit_logs 审计日志表
  - `202607050002_system_logs.py` — system_logs 系统日志表
  - `202607050003_tenant_constraints.py` — 租户约束：补 workspace_id、状态/角色 CHECK 约束、跨表外键、owner→admin 角色迁移
  - `202607050004_knowledge_bases_resource_permissions.py` — 知识库与资源权限相关表结构
  - `202607060001_model_registry.py` — 模型注册表 model 及 provider 类型约束
  - `202607060002_workspace_team_descriptions.py` — workspaces/teams 增加 description 列
  - `202607060003_rename_model_knowledge_tables.py` — 重命名 model 与 knowledge 相关表
  - `202607060004_knowledge_documents.py` — knowledge_documents 文档表
  - `202607060005_knowledge_model_settings.py` — 知识库嵌入/检索模型设置列
  - `202607060006_knowledge_document_pipeline.py` — 文档流水线：chunks 分块表、last_error、状态约束与索引
  - `202607060007_knowledge_task_progress_columns.py` — 知识任务进度相关列
  - `202607060008_knowledge_task_options.py` — 知识任务选项列
  - `202607060009_knowledge_document_meta.py` — 文档元数据列
  - `202607060010_knowledge_task_lease.py` — 任务租约列（worker 抢占/恢复）
  - `202608020011_knowledge_document_is_active.py` — 文档 is_active 软删除标记列
  - `202608030001_agent_goal_runs.py` — Agent 目标运行（goal runs）表结构
  - `202608030002_agent_mcp_tools.py` — Agent 与 MCP 工具关联表
  - `202608040001_refresh_sessions.py` — refresh_sessions 刷新会话表
  - `202608040002_drop_agent_run_citations.py` — 删除 agent run citations 字段/表
  - `202608040004_agent_published.py` — agent 表增加 published 发布标记列
  - `202608050001_knowledge_chunk_search.py` — 知识块 content 全文检索 GIN 索引（仅 PostgreSQL）
  - `202608050002_model_provider_credentials.py` — 模型凭据改造：credential_config/secret_hints JSON 列与 provider_type 归一化
  - `202608050003_knowledge_parent_chunks.py` — 智能分段 Parent 表、Child 父级偏移及文档/租户组合外键约束

## backend 根配置

- `backend/pyproject.toml` — 项目元数据与依赖声明（FastAPI/Celery/LangChain/LangGraph/MCP/Qdrant/Alembic 等）
- `backend/.env.example` — 环境变量模板：环境/日志/数据库/JWT/模型密钥/知识存储/Qdrant/Redis/MCP/CORS/引导管理员与默认工作区
- `backend/README.md` — 后台 worker 运行说明（Celery 命令与共享 `KNOWLEDGE_STORAGE_DIR`/`QDRANT_URL` 要求）
- `backend/uv.lock` — uv 依赖锁文件

## 相关测试

- `backend/tests/support.py` — 测试共享基础设施：内存 SQLite + eager Celery 的 TestClient 环境、Settings 构造、登录/激活管理员/激活用户辅助函数
- `backend/tests/logger.py` — 全局日志器与错误分类（internal/external）单元测试
- `backend/tests/test_main.py` — 应用冒烟测试：/health、bootstrap 管理员登录、auth/me、404 路由
