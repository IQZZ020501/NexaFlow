# IDENTITY_WORKSPACE 模块（backend/app/domain + shareddomain/{teams,audit,tools} + application/{identity,workspace}）

## 职责

身份与租户地基：User/Workspace/Team/ResourcePermission 共享实体；团队与审计领域；以及 builtin/Python/MCP 统一 Tool 目录、版本、策略、授权、绑定和调用账本。身份与工作区应用服务负责登录、token、用户和成员管理；所有核心资源使用 `workspace_id` 隔离。

## 分层关系

```text
api/{auth,workspaces,teams,tool_sources,tools,mcp_servers,admin/users,admin/audit}.py
  → application/{identity,workspace}（登录/token/用户与工作区管理）
  → application/tools（Tool 用例编排）
  → shareddomain/{teams,audit,tools}（领域服务）
  → entities/（纯领域实体）+ domain/shareddomain/*/models.py（ORM）
  → infrastructure/repositories/{user,workspace,team,audit,mcp,tools,resource_permission}
```

## 文件清单

### app/domain/（共享 ORM 实体）

- `backend/app/domain/user.py` — User 与 RefreshSession 实体（含关系与级联）
- `backend/app/domain/workspace.py` — Workspace 与 WorkspaceMembership 实体（状态/角色约束）
- `backend/app/domain/team.py` — Team 与 TeamMembership 实体（复合外键约束）
- `backend/app/domain/resource_permission.py` — ResourcePermission ORM（知识库、Agent 与 Tool 的资源级授权）

### app/entities/（纯领域实体）

- `backend/app/entities/tools.py` — ToolSource、Tool、Version、Draft、Policy、Binding、Snapshot 与 Invocation 纯实体

### app/application/

- `backend/app/application/identity.py` — 身份与应用服务：登录认证、access/refresh token 签发、改密、用户 CRUD 及审计记录
- `backend/app/application/workspace.py` — 工作区应用服务：创建/更新/删除、成员增删改、最后一名管理员等规则校验

### app/shareddomain/teams/

- `backend/app/shareddomain/teams/services.py` — 团队服务层：CRUD、成员与权限管理

### app/shareddomain/audit/

- `backend/app/shareddomain/audit/services.py` — 审计日志记录与查询服务（`record_audit_log` 全模块共用）
- `backend/app/shareddomain/audit/models.py` — AuditLog ORM 模型（audit_logs 表）

### app/shareddomain/tools/

- `backend/app/shareddomain/tools/services.py` — Tool 领域门面与 MCP Source 生命周期：传输配置、发现、刷新、凭据加密和策略管理
- `backend/app/shareddomain/tools/catalog.py` — builtin/Python/MCP 统一目录、MCP discovery 对账、不可变版本与 tombstone
- `backend/app/shareddomain/tools/python_tools.py` — Python Tool 草稿、乐观并发、测试快照、发布、启停和归档规则
- `backend/app/shareddomain/tools/permissions.py` — owner/admin/`view`/`use` 权限计算、授权写入与撤销
- `backend/app/shareddomain/tools/bindings.py` — Agent/Workflow 固定 Tool/Version 绑定及 binder 身份保持
- `backend/app/shareddomain/tools/runtime.py` — ToolSnapshot 序列化、参数 schema 校验、effect/approval 与运行约束
- `backend/app/shareddomain/tools/models.py` — ToolSource、Tool、ToolVersion、ToolDraft、ToolPolicy、应用绑定和 ToolInvocation ORM

## 关键约定

- 全局管理员（`is_global_admin`）是平台超管：创建/管理工作空间生命周期，不穿透工作空间成员/知识库/工具权限。
- 角色只有 `admin`/`member` 两级；资源级授权通过 `ResourcePermission`。知识库使用 `view/edit`，Agent 使用 `view`，Tool 使用不可转授的 `view/use`。
- 团队是组织标签：支持成员管理（添加/列表/改角色/移除，需工作区管理员），不参与资源授权；团队成员必须是工作区成员。
- 知识库 owner（`created_by_user_id`）可通过 owner 转移接口变更；创建者与工作区管理员可管理资源权限。
- 删除工作区会在同一事务内级联删除知识库、Agent/运行记录、MCP、模型、团队/成员及资源授权；存在 queued/running 知识任务时返回 409。向量集合和对象存储文件由持久清理记录交给 Celery 异步删除，失败后自动重试。
- 敏感写操作（创建/修改/删除）一律 `record_audit_log`。
- Tool 默认 owner 私有；工作空间管理员具有治理权限。`view` 只能查看脱敏详情，`use` 还允许绑定到自己的 Agent/Workflow；撤销、Source/Tool 禁用、成员失效和策略漂移在 dispatch 前重新校验。
- 普通成员可创建 Python Tool 与公网 HTTP/SSE MCP Source；stdio 和私网地址只允许工作空间管理员。Bearer token、stdio 参数/工作目录/环境值加密保存且不返回明文；stdio 具备后端进程级执行能力，因此部署必须信任 MCP 管理员。
- Agent、Workflow 与 Python 测试都固定 Tool/Version 快照并写 `tool_invocations`；builtin/Python/MCP 只在 application adapter 内分流。

## 相关测试

- `backend/tests/identity.py` — 身份认证端到端测试：登录/刷新/登出、刷新会话落库与审计日志
- `backend/tests/workspaces.py` — 工作区端到端测试：CRUD、成员管理、跨工作区访问隔离、全资源级联与外部存储清理重试
- `backend/tests/teams.py` — 团队端到端测试：CRUD、管理员成员管理与跨工作区团队成员约束
- `backend/tests/tools.py` — Tool/Source/Python 生命周期、授权、策略、绑定、运行账本与跨租户隔离
- `backend/tests/mcp_transports.py` — Streamable HTTP/SSE/stdio 传输、凭据隐藏、网络边界与 discovery 行为
