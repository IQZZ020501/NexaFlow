# 应用与知识库默认私有设计

## 目标

将 workspace 内的应用（Agent）和知识库（KnowledgeBase）从“目录全员可见”改为“默认仅创建者可见”，并允许资源所有者或 workspace admin 显式授权其他成员访问。模型与 MCP server 继续保持 workspace 共享，published 应用继续通过公开入口访问。

## 范围

- 普通成员只能在列表中看到自己创建或已获授权的应用与知识库。
- workspace admin 始终可以查看和管理 workspace 内全部应用与知识库。
- 知识库继续使用现有 `view` / `edit` 两级授权。
- 应用只提供 `view` 授权：被授权成员可以查看应用、发起 console 对话并查看自己的运行记录，但不能编辑、删除、发布、查看管理日志、管理 API credential 或管理授权。
- 应用与知识库的存量数据在迁移后立即按创建者私有，不为其他成员自动补授权。
- 前端为应用所有者和 workspace admin 提供成员授权与撤销入口。

## 非目标

- 不改变 RegisteredModel 和 MCP server 的 workspace 共享行为。
- 不改变 published 应用页面及 Agent API credential 的外部访问语义。
- 不新增应用所有权转交功能。
- 不改变知识库既有的所有权转交和 `view` / `edit` 权限语义。
- 不引入团队级授权、公开链接授权或批量授权。

## 方案选择

复用并扩展现有 `resource_permissions` 表，新增 `resource_type = "agent"`。应用授权记录只允许 `permission = "view"`；知识库授权继续允许 `view` 和 `edit`。

该方案优于新增 `agent_permissions` 表，因为成员外键、唯一性、审计、workspace 成员移除清理和授权 CRUD 的语义可以复用；也优于在 Agent 上保存用户 ID 列表，因为关系表能够提供数据库约束、可索引查询和可靠的并发更新。

## 数据模型与迁移

Alembic migration 更新 `ck_resource_permissions_resource_type`，允许 `knowledge_base` 和 `agent`。`permission` 数据库约束仍允许 `view` / `edit`，应用只能使用 `view` 的限制由应用领域服务校验，避免为不同资源类型引入复杂的组合约束。

`resource_permissions` 继续使用 `(workspace_id, resource_type, resource_id, user_id)` 唯一约束和 `(workspace_id, user_id)` workspace membership 外键。迁移不插入任何授权记录，因此存量应用和知识库在新查询规则生效后立即变为 owner-only；admin 通过角色旁路访问，不需要持久化授权。

删除应用时删除其 `resource_type = "agent"` 授权。现有 workspace 成员移除与 workspace 删除流程已经按 workspace/user 清理通用授权记录，需通过回归测试确认对 Agent 授权同样生效。

## 后端设计

### 通用授权数据访问

将授权记录的查询、创建、更新、列举和删除收敛到通用 resource permission repository。知识库服务继续保持现有公开行为，应用领域新增权限服务并复用相同的数据访问边界。业务代码只使用 entity，所有 ORM 写操作由 repository 完成。

### 知识库列表

`list_knowledge_base_rows` 在 SQL 查询阶段按以下条件过滤，再执行排序、`limit` 和 `offset`：

- workspace admin：workspace 内全部知识库；
- 普通成员：`created_by_user_id == actor.id`，或存在当前用户的 `resource_type = "knowledge_base"` 授权。

列表不再返回 `permission = "none"` 的条目，也不再需要通过将统计数字置零来掩盖未授权资源。详情、文档、检索、更新和授权接口继续使用既有知识库权限校验。

### 应用访问

应用权限服务提供以下规则：

- `can_edit_agent`：workspace admin 或创建者；
- `require_agent_view`：admin、创建者或拥有 `agent/view` 授权；
- `require_agent_edit`：仅 admin 或创建者；
- 授权管理：仅 admin 或创建者。

应用列表在 repository 查询阶段过滤 owner/grant/admin，并在过滤后分页。应用详情响应、console run 创建以及 console run 列表/读取统一执行 `require_agent_view`。更新、删除、发布、管理日志、监控、API credential 和授权管理继续执行更严格的 owner/admin 校验。

`prepare_agent_run` 只对 `access_source = "console"` 执行私有授权校验。`public` 和 `api` 已由 published context 或 API credential 流程校验，保持原行为。

被授予 `view` 的成员在 Agent 响应中仍为 `can_edit = false`，不会获得 MCP 配置详情，也不能修改应用。运行时是否可使用绑定的 MCP tools 保持现有安全策略：非编辑者的 console run 不注入 MCP tools；可访问的知识库仍按运行用户自身的知识库权限过滤。

### 应用授权接口

在 workspace Agent 路由下新增：

- `GET /api/v1/workspaces/{workspace_id}/agents/{agent_id}/permissions`
- `PUT /api/v1/workspaces/{workspace_id}/agents/{agent_id}/permissions/{user_id}`
- `DELETE /api/v1/workspaces/{workspace_id}/agents/{agent_id}/permissions/{user_id}`

`PUT` 请求只接受 `permission = "view"`。目标用户必须是当前 workspace 的 active member。重复授予执行 upsert；撤销不存在的授权返回 `404`。授予和撤销写入现有 `resource_permission.grant` / `resource_permission.revoke` audit event，并标记 `resource_type = "agent"`。

API router 保持薄层，只导入 `application/` facade 和 schema；应用用例通过 `application/agents.py` 暴露。

## 错误处理与安全语义

- 资源不存在或资源不属于路径中的 workspace：`404`。
- 用户属于 workspace 但没有资源访问权：`403`。
- 非 owner/admin 管理应用授权：`403`。
- 目标用户不是 active workspace member：`404`。
- 应用授权提交非 `view` 权限：`422`。
- 撤销不存在的应用授权：`404`。

列表过滤与详情/运行授权必须同时存在：列表过滤负责隐私体验，服务层授权负责阻止通过已知 ID 绕过列表。授权查询始终包含 `workspace_id`、`resource_type`、`resource_id` 和 `user_id`，防止跨租户授权碰撞。

## 前端设计

应用列表继续以接口结果为唯一数据源，不在客户端重新实现可见性规则。owner/admin 的应用卡片操作菜单增加“资源授权”入口；获得 `view` 权限的成员只看到现有的查看/使用界面，不显示授权入口。

授权对话框在打开时加载 workspace members 与当前应用授权，排除资源创建者，支持：

- 选择成员并授予查看权限；
- 显示当前已授权成员；
- 撤销单个成员的授权；
- 独立的加载、保存、撤销和错误状态。

应用 API module 新增授权类型和 list/upsert/revoke 调用。所有新增可见文案、按钮文本、tooltip、aria-label 和通知消息通过 `t()` 获取，并同步写入 `zhHans`、`zhHant` 和 `en` 字典。

知识库前端保留现有授权对话框和 `view/edit` 控件；列表会自然反映后端过滤结果。

## 测试策略

遵循 TDD，先增加失败测试，再实现最小改动。

后端集成测试覆盖：

- 未授权成员的应用和知识库列表不包含私有资源；
- 过滤在分页前执行，避免出现空页或跨页泄漏；
- owner 与 workspace admin 始终可见；
- Agent `view` 授权后成员可列出、读取和发起 console run，但更新、删除、发布、监控、管理日志和授权管理仍被拒绝；
- 撤销 Agent 授权后列表隐藏，详情和新 run 被拒绝；
- 非 `view` Agent 授权、非成员授权和跨 workspace 授权被拒绝；
- 删除 Agent、移除成员和删除 workspace 会清理 Agent 授权；
- published 与 Agent API credential 流程不受私有授权影响；
- 知识库 `view/edit` 现有行为不回归，仅替换原先 `permission = "none"` 的列表预期。

前端测试覆盖 Agent 授权 API 请求、授权入口可见条件、对话框授予/撤销行为和三语字典同步。验证按影响范围运行 backend compileall、`tests.unit`、`tests.knowledge`、`tests.agents`，以及 frontend 的相关 Bun tests、typecheck 和 lint；若全量检查成本可接受，再运行 frontend build。

## 验收标准

- 新建及存量应用、知识库默认仅 owner 和 workspace admin 可见。
- 明确授权后，目标成员才能在列表看到并使用对应资源。
- Agent 授权成员只能查看和使用，不能获得编辑或管理能力。
- 知识库仍支持 `view/edit`，未授权条目不再泄漏名称或元数据。
- published 应用、模型和 MCP server 的现有共享/公开行为不变。
- 跨 workspace 访问与授权无法建立。

## 风险与回滚

主要风险是迁移后普通成员立即失去对存量资源的目录访问，这是确认后的预期行为。查询过滤若放在分页之后会造成不完整页面，因此必须在 SQL 层完成。遗漏详情或 run 授权会形成 ID 绕过，因此所有 console 入口都需要服务层校验和测试。

代码回滚时恢复旧列表和访问逻辑即可重新显示资源；数据库回滚需先删除 `resource_type = "agent"` 的授权记录，再恢复只允许 `knowledge_base` 的 check constraint，避免 downgrade 失败。
