# IDENTITY_WORKSPACE 模块（app/domain/{platform,identity,teams,audit,tools,…} + 对应 application / api / 仓储 / entities / schemas）

## 职责

身份与租户地基：`app/domain/platform/models.py` 提供 User/RefreshSession/Workspace/WorkspaceMembership/Team/TeamMembership/ResourcePermission/SmtpSettings/WorkspaceGovernance/WorkspaceInvitation 共享 ORM 实体；`domain/{teams,audit}` 承载团队与审计领域；`domain/identity/enterprise` 承载企业身份连接/身份与登录态 ORM；ResourceFolder 与治理（governance）为工作区级资源；另有 builtin/Python/MCP 统一 Tool 目录、版本、策略、授权、绑定和调用账本领域模型。身份与工作区应用服务负责登录、token、用户/成员/邀请/密码重置管理，资源文件夹与系统日志、治理入口位于其上的 application 与 api 层；所有核心资源使用 `workspace_id` 隔离。

## 分层关系

```text
app/api/v1/identity/{auth,enterprise}.py、workspaces|teams|resource_folders 的 routes.py、
admin/{users,audit,governance,smtp,system_logs}/routes.py
  → app/application/{identity,workspaces,teams,resource_folders,governance,audit}
  → app/domain/{platform,identity,teams,audit,resource_folders,email}（ORM/领域服务）
    + app/domain/tools（Tool 领域模型与目录/授权/绑定规则）
  → app/entities/*（纯领域对象） + app/schemas/*（请求/响应契约）
  → app/infra/db/repositories/{identity,workspaces,teams,audit,governance,resource_folders,email,tools}
```

## 文件清单

### app/domain/（领域层）

#### 平台共享 ORM 与身份域

- `backend/app/domain/platform/models.py` — 跨领域共享 ORM：User、RefreshSession、Workspace、WorkspaceMembership、Team、TeamMembership、ResourcePermission、SmtpSettings、WorkspaceGovernance、WorkspaceInvitation（用户/工作区/团队/成员/权限/治理/邀请的登记录在 alembic 迁移与 env.py 注册范围内）
- `backend/app/domain/identity/enterprise/models.py` — 企业身份 ORM：EnterpriseIdentityConnection、EnterpriseIdentity、EnterpriseLoginState
- `backend/app/domain/identity/enterprise/services.py` — 企业身份连接字段校验与回调 next-path 安全解析（`validate_connection_fields`、`safe_next_path`），供 application 层企业登录流程使用
- `backend/app/domain/teams/services.py` — 团队领域服务：团队 CRUD、成员添加/列表/改角色/移除、角色校验、`actor_manages_team_admins` 与最后一名团队管理员守卫
- `backend/app/domain/audit/models.py` — AuditLog ORM（audit_logs 表）
- `backend/app/domain/audit/services.py` — `record_audit_log`（全模块共用写审计）与审计日志列表/工作区过滤/计数查询
- `backend/app/domain/resource_folders/models.py` — ResourceFolder ORM（工作区级资源文件夹）
- `backend/app/domain/email/models.py` — EmailDelivery、PasswordResetToken ORM（密码重置令牌与投递记录落库）

#### Tool 目录域（app/domain/tools/）

- `backend/app/domain/tools/models.py` — ORM：ToolSource、Tool、ToolDraft、ToolVersion、ToolPolicy、ApplicationToolBinding、ToolInvocation、McpServer、McpToolPolicy
- `backend/app/domain/tools/catalog/service.py` — builtin/Python/MCP 统一目录构造（`build_workspace_system_catalog`、inline Python/artifact/skill artifact 构造）、stable catalog id、定义 hash、MCP function 命名与目录条目模型
- `backend/app/domain/tools/mcp/service.py` — MCP Source 生命周期：传输配置解析（bearer/stdio）、server 连接与发现对账、legacy MCP 策略模式兼容
- `backend/app/domain/tools/python/service.py` — Python Tool 草稿、测试快照、发布、启停、归档与函数名规则
- `backend/app/domain/tools/access/permissions.py` — owner/admin/`view`/`use` 授权计算（`ToolAuthorization`、`evaluate_tool_authorization`）与 view/use/manage 断言、权限值校验
- `backend/app/domain/tools/access/bindings.py` — Agent/Workflow 固定 Tool/Version 绑定快照构建（binder 身份保持）
- `backend/app/domain/tools/runtime.py` — ToolSnapshot 序列化与载荷还原、参数 schema 校验/归一化、参数 hash、effect/approval 与运行终态约束
- 纯领域对象（FrozenJson 容器、ToolRef、ToolSnapshot、ToolAccess、Tool 授权枚举等）在 `backend/app/entities/tools/models.py`，供 runtime/bindings/permissions 共用；上层用例编排在 `app/application/tools/{runtime,management}/service.py`，其 API 入口在 `app/api/v1/tools/{routes,sources,mcp}.py`（详见 API 文档），仓储在 `app/infra/db/repositories/tools/{repository,mcp}.py`

### app/application/（应用服务层）

- `backend/app/application/identity/service.py` — 身份与应用服务：登录认证、access/refresh token 签发/刷新/吊销、改密、用户 CRUD、最后一名工作区管理员规则、scope 装配与用户响应
- `backend/app/application/identity/sessions.py` — 会话管理：会话列表、按会话/全部/其他会话吊销
- `backend/app/application/identity/invitations.py` — 工作区邀请：token 哈希、创建/列表/撤销/删除/接受
- `backend/app/application/identity/password_reset.py` — 密码重置：申请与确认（哈希化 token）
- `backend/app/application/identity/enterprise.py` — 企业身份应用服务：连接 CRUD/启停、公开连接、身份绑定、企业登录 begin/complete、回调 URL、`EnterpriseLoginRejected`
- `backend/app/application/workspaces/service.py` — 工作区应用服务：CRUD、成员增删改与角色校验、跨工作区访问守卫、全局管理员规则、级联删除
- `backend/app/application/teams/__init__.py` — 团队用例门面（facade）：re-export 领域层 create/get/list/update/delete team 与成员管理
- `backend/app/application/resource_folders/service.py` — 资源文件夹：CRUD、层级（descendant 判定）、资源移入/移出
- `backend/app/application/governance/service.py` — 治理：空间治理设置读写、空间资源清点（inventory）、运行配额执行、管理员健康探测
- `backend/app/application/audit/__init__.py` — 审计用例门面：`list_audit_logs`/`list_workspace_audit_logs`/`count_audit_logs`
- `backend/app/application/audit/system_logs.py` — 系统日志：列表/计数与敏感值脱敏（`redact_system_value`）

### app/api/v1/（路由层）

- `backend/app/api/v1/identity/auth.py` — `prefix="/auth"`：登录/刷新/登出、会话列表与吊销、改密、me、邀请接受
- `backend/app/api/v1/identity/enterprise.py` — 双路由：`public_router`（`/auth/enterprise`：公开连接、start/QR 登录、`/callback/{provider}`）与 `admin_router`（`/enterprise-identity`：连接与身份管理）
- `backend/app/api/v1/workspaces/routes.py` — `prefix="/workspaces"`：工作区与成员管理
- `backend/app/api/v1/teams/routes.py` — `prefix="/workspaces/{workspace_id}/teams"`
- `backend/app/api/v1/resource_folders/routes.py` — `prefix="/workspaces/{workspace_id}/resource-folders"`
- `backend/app/api/v1/admin/users/routes.py` — `prefix="/users"`（平台级用户管理）
- `backend/app/api/v1/admin/audit/routes.py` — `prefix="/audit-logs"`
- `backend/app/api/v1/admin/governance/routes.py` — `prefix="/governance"`（治理/健康/清单）
- `backend/app/api/v1/admin/smtp/routes.py` — `prefix="/smtp"`（SMTP 设置与测试）
- `backend/app/api/v1/admin/system_logs/routes.py` — `prefix="/system-logs"`（SystemLog 的 ORM 表定义在 `app/infra/observability/system_log.py`，写入由日志采集侧完成）

### app/infra/db/repositories/（仓储层）

- `backend/app/infra/db/repositories/identity/users.py` — 用户/刷新会话/成员资格/scope 行/管理空间查询与用户图删除
- `backend/app/infra/db/repositories/identity/invitations.py` — 邀请 CRUD 与 token 哈希查询
- `backend/app/infra/db/repositories/identity/enterprise.py` — 企业连接/身份/登录态读写与连接禁用时的会话/身份清理
- `backend/app/infra/db/repositories/workspaces/repository.py` — 工作区与成员资格仓储（含管理员计数/最后管理员守卫的查询支撑）
- `backend/app/infra/db/repositories/workspaces/resource_permissions.py` — ResourcePermission 授予谓词与授权读写
- `backend/app/infra/db/repositories/teams/repository.py` — 团队与团队成员资格仓储
- `backend/app/infra/db/repositories/audit/repository.py` — AuditLog 写入与列表/计数/工作区过滤
- `backend/app/infra/db/repositories/audit/system_logs.py` — SystemLog 列表/计数与过滤子句
- `backend/app/infra/db/repositories/governance/inventory.py` — 空间资源清点查询
- `backend/app/infra/db/repositories/governance/settings.py` — WorkspaceGovernance 设置读写
- `backend/app/infra/db/repositories/resource_folders/repository.py` — ResourceFolder 与资源移动仓储
- `backend/app/infra/db/repositories/email/delivery.py` — 邮件投递记录与密码重置 token 读写/清理
- `backend/app/infra/db/repositories/email/smtp.py` — SmtpSettings 全局单例读写

### app/entities/ 与 app/schemas/（纯领域对象与契约）

- `backend/app/entities/identity/user.py`（User、RefreshSession）、`invitations.py`（WorkspaceInvitation）、`enterprise.py`（EnterpriseIdentityConnection、EnterpriseIdentity、EnterpriseLoginState）
- `backend/app/schemas/identity/contracts.py`（用户/会话/登录契约）、`invitations.py`、`enterprise.py`
- `backend/app/entities/workspaces/models.py`（Workspace、WorkspaceMembership）、`resource_permissions.py`；`backend/app/schemas/workspaces/contracts.py`
- `backend/app/entities/teams/models.py`（Team、TeamMembership）；`backend/app/schemas/teams/contracts.py`
- `backend/app/entities/audit/models.py`（AuditLog）、`system_logs.py`（SystemLog）；`backend/app/schemas/audit/contracts.py`、`system_logs.py`
- `backend/app/entities/governance/models.py`（WorkspaceGovernance）；`backend/app/schemas/governance/contracts.py`
- `backend/app/entities/resource_folders/models.py`（ResourceFolder）；`backend/app/schemas/resource_folders/contracts.py`
- `backend/app/entities/email/delivery.py`（EmailDelivery、PasswordResetToken）、`smtp.py`（SmtpSettings）；`backend/app/schemas/email/smtp.py`
- Tool 纯对象与 MCP 契约：`backend/app/entities/tools/models.py`、`backend/app/schemas/tools/{contracts,mcp}.py`

## 关键约定

- 系统管理员（`is_global_admin`）是平台级治理者：可创建、管理和审计所有工作空间，并治理跨工作空间的成员、团队、运行与安全策略；工作空间管理员负责本空间成员、全部团队及空间级策略。资源级授权仍按工作空间隔离并记录审计。
- 角色只有 `admin`/`member` 两级，且**不参与资源可见性**：知识库、Agent、Tool 都按「创建者 + `ResourcePermission` 显式授权」判定（知识库 `view/edit`，Agent `view`，Tool 不可转授的 `view/use`），工作空间管理员与系统管理员都不能看到或管理别人的资源。授权管理（`require_can_manage_permissions`）与归档恢复也只限创建者；唯一例外是工作区公共的 builtin 工具，管理员仍可治理其策略与测试。运行遥测（`/logs`、`/conversation-users`、`/monitoring`）保留管理员只读入口，用于工作区运营。
- 资源文件夹是「谁的目录谁管」的私有结构：任何成员都可创建目录（根目录，或自己可见的目录下），可见范围只有创建者本人，以及通过 `ResourcePermission` 授权或自己拥有的知识库/应用/工具所揭示的目录链（含祖先）；系统管理员与工作空间管理员都不再看到别人的目录。改名、移动、删除仅限创建者（系统管理员保留平台级兜底）。资源本身仍按 `view/edit` 授权判定；前端把「归入不可见目录」的资源显示在根目录，避免列表丢项。
- 团队是组织标签：支持成员管理（添加/列表/改角色/移除，需工作区管理员），不参与资源授权；团队成员必须是工作区成员。
- 知识库 owner（`created_by_user_id`）可通过 owner 转移接口变更；资源权限只有创建者本人可管理（工作空间管理员不再代管别人的知识库）。
- 删除工作区会在同一事务内级联删除知识库、Agent/运行记录、MCP、模型、团队/成员及资源授权；存在 queued/running 知识任务时返回 409。向量集合和对象存储文件由持久清理记录交给 Celery 异步删除，失败后自动重试。
- 敏感写操作（创建/修改/删除）一律 `record_audit_log`。
- Tool 默认 owner 私有：只有创建者或被授权者能查看、使用和管理；builtin 工具属工作区公共资源（所有成员可用、管理员可治理），MCP 服务器与工具策略治理仍限工作空间管理员。`view` 只能查看脱敏详情，`use` 还允许绑定到自己的 Agent/Workflow；撤销、Source/Tool 禁用、成员失效和策略漂移在 dispatch 前重新校验。
- 普通成员可创建 Python Tool 与公网 HTTP/SSE MCP Source；stdio 和私网地址只允许工作空间管理员。Bearer token、stdio 参数/工作目录/环境值加密保存且不返回明文；stdio 具备后端进程级执行能力，因此部署必须信任 MCP 管理员。
- Agent、Workflow 与 Python 测试都固定 Tool/Version 快照并写 `tool_invocations`；builtin/Python/MCP 只在 application adapter 内分流。

## 相关测试

在 `backend/` 下以 dotted module 运行（`uv run python -m …`）：

- `tests.identity.identity` — 身份认证端到端：登录/刷新/登出、刷新会话落库与审计日志、账号删除对会话/Tool/审计的联动
- `tests.identity.enterprise_identity` — 企业身份连接、绑定与企业登录流程
- `tests.identity.email` / `tests.identity.smtp` — 邮件与密码重置、SMTP 设置与传输回归
- `tests.platform.workspaces` — 工作区端到端：CRUD、成员管理、跨工作区访问隔离、全资源级联与外部存储清理重试
- `tests.platform.teams` — 团队端到端：CRUD、管理员成员管理与跨工作区团队成员约束
- `tests.platform.resource_folders` — 资源文件夹 CRUD、层级、资源移动与成员可见性
- `tests.platform.system_governance` — 治理设置、健康探测与空间清点/系统日志入口
- `tests.platform.workspace_admin_coverage` — 工作区/身份/团队/admin 域覆盖套件（纯脚本，逐块独立内存库）
- `tests.platform.unit` — 平台域单元测试片段
- `tests.tools.tools` — 统一 Tool 目录/持久化/迁移回归：目录契约、租户隔离关系、授权与网络策略迁移、版本不可变
- `tests.tools.unit` — 工具域单元测试片段
- `tests.infra.mcp_transports` — Streamable HTTP/SSE/stdio 传输、凭据隐藏、网络边界与 discovery 行为
