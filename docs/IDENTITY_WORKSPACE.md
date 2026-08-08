# IDENTITY_WORKSPACE 模块（backend/app/domain + shareddomain/{teams,audit,tools} + application/{identity,workspace}）

## 职责

身份与租户地基：User/Workspace/Team/ResourcePermission 共享 ORM 实体；团队、审计、MCP 工具三个小领域服务；身份与工作区应用服务（登录、token 签发、用户/成员管理）。所有核心资源带 `workspace_id` 实现租户隔离。

## 分层关系

```text
api/{auth,workspaces,teams,mcp_servers,admin/users,admin/audit}.py
  → application/{identity,workspace}（登录/token/用户与工作区管理）
  → shareddomain/{teams,audit,tools}（领域服务）
  → domain/（ORM 实体）
  → infrastructure/repositories/{user,workspace,team,audit,mcp}
```

## 文件清单

### app/domain/（共享 ORM 实体）

- `backend/app/domain/user.py` — User 与 RefreshSession 实体（含关系与级联）
- `backend/app/domain/workspace.py` — Workspace 与 WorkspaceMembership 实体（状态/角色约束）
- `backend/app/domain/team.py` — Team 与 TeamMembership 实体（复合外键约束）
- `backend/app/domain/resource_permission.py` — ResourcePermission 实体（知识库 view/edit 细粒度权限）

### app/application/

- `backend/app/application/identity.py` — 身份与应用服务：登录认证、access/refresh token 签发、改密、用户 CRUD 及审计记录
- `backend/app/application/workspace.py` — 工作区应用服务：创建/更新/删除、成员增删改、最后一名管理员等规则校验

### app/shareddomain/teams/

- `backend/app/shareddomain/teams/services.py` — 团队服务层：CRUD、成员与权限管理

### app/shareddomain/audit/

- `backend/app/shareddomain/audit/services.py` — 审计日志记录与查询服务（`record_audit_log` 全模块共用）
- `backend/app/shareddomain/audit/models.py` — AuditLog ORM 模型（audit_logs 表）

### app/shareddomain/tools/

- `backend/app/shareddomain/tools/services.py` — MCP 服务器服务层：三种传输 CRUD、Bearer/stdio 配置加解密、工具发现及解析为智能体工具
- `backend/app/shareddomain/tools/models.py` — McpServer ORM 模型（mcp_servers 表）

## 关键约定

- 全局管理员（`is_global_admin`）是平台超管：创建/管理工作空间生命周期，不穿透工作空间成员/知识库/工具权限。
- 角色只有 `admin`/`member` 两级；资源级授权通过 `ResourcePermission`（当前仅 knowledge_base 的 view/edit）。
- 团队是组织标签：支持成员管理（添加/列表/改角色/移除，需工作区管理员），不参与资源授权；团队成员必须是工作区成员。
- 知识库 owner（`created_by_user_id`）可通过 owner 转移接口变更；创建者与工作区管理员可管理资源权限。
- 删除工作区会在同一事务内级联删除知识库、Agent/运行记录、MCP、模型、团队/成员及资源授权；存在 queued/running 知识任务时返回 409。向量集合和对象存储文件由持久清理记录交给 Celery 异步删除，失败后自动重试。
- 敏感写操作（创建/修改/删除）一律 `record_audit_log`。
- stdio 配置由工作空间管理员提交并加密保存；命令与工作目录必须是后端运行环境中的绝对路径，列表接口不返回参数、工作目录或环境值。stdio 具备后端进程级文件系统与网络访问能力，因此部署时必须信任可管理 MCP Server 的工作空间管理员。

## 相关测试

- `backend/tests/identity.py` — 身份认证端到端测试：登录/刷新/登出、刷新会话落库与审计日志
- `backend/tests/workspaces.py` — 工作区端到端测试：CRUD、成员管理、跨工作区访问隔离、全资源级联与外部存储清理重试
- `backend/tests/teams.py` — 团队端到端测试：CRUD、管理员成员管理与跨工作区团队成员约束
